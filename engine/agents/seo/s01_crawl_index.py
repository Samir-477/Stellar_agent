"""S1 Crawl & Index Health: can search engines reach, crawl and index the right pages?

Deterministic only (no LLM calls). Checks S1.01–S1.11 from docs/spec/04-diagnosis-matrix.md.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from engine.agents.base import Agent
from engine.agents.common import PageView, key_page_urls, load_pages, sample_info, site_file
from engine.context import AgentContext, WorkUnit
from engine.lib.content import jaccard, own_text, shingles, template_blocks
from engine.lib.robots import parse_robots
from engine.schemas import (
    AgentResult,
    CheckSpec,
    CheckStatus as St,
    Confidence,
    Coverage,
    Effort,
    EvidenceRef,
    EvidenceType,
    Finding,
    Locator,
    Patch,
    PatchType,
    Pillar,
    Severity as Sev,
)

GOOGLEBOT = "Googlebot"
_SOFT_404 = re.compile(r"\b(404|page not found|not found|doesn'?t exist|no longer available)\b", re.I)
_ACTIVE = {"script", "iframe", "link"}


def _norm(url: str | None) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    return f"{parts.scheme}://{(parts.hostname or '').lower()}{parts.path or '/'}".rstrip("/")


def _noindex(page: PageView) -> str | None:
    """Return where the noindex came from, or None."""
    robots_meta = (page.model or {}).get("meta_robots") or ""
    if "noindex" in robots_meta.lower() or "none" in robots_meta.lower().split(","):
        return f'<meta name="robots" content="{robots_meta}">'
    header = page.headers.get("x-robots-tag", "")
    if "noindex" in header.lower():
        return f"X-Robots-Tag: {header}"
    return None


class CrawlIndexHealth(Agent):
    id = "S1"
    name = "Crawl & Index Health"
    pillar = Pillar.SEO
    requires = frozenset({EvidenceType.PAGES_RAW, EvidenceType.PAGES_PARSED, EvidenceType.SITE_FILES,
                          EvidenceType.URL_VARIANTS})
    signature_columns = ["URL", "Status", "Final URL", "Indexable", "Canonical target", "In sitemap"]
    checks = [
        CheckSpec(id="S1.01", title="HTTP status of sampled URLs", default_severity=Sev.HIGH, method="D"),
        CheckSpec(id="S1.02", title="Soft 404s", default_severity=Sev.MEDIUM, method="D"),
        CheckSpec(id="S1.03", title="Redirect chains", default_severity=Sev.MEDIUM, method="D"),
        CheckSpec(id="S1.04", title="Indexability directives", default_severity=Sev.HIGH, method="D"),
        CheckSpec(id="S1.05", title="robots.txt for search engines", default_severity=Sev.CRITICAL, method="D"),
        CheckSpec(id="S1.06", title="Canonical tags", default_severity=Sev.HIGH, method="D"),
        CheckSpec(id="S1.07", title="XML sitemap", default_severity=Sev.MEDIUM, method="D"),
        CheckSpec(id="S1.08", title="URL variants resolve to one version", default_severity=Sev.HIGH, method="D"),
        CheckSpec(id="S1.09", title="Duplicate / near-duplicate pages", default_severity=Sev.HIGH, method="D"),
        CheckSpec(id="S1.10", title="HTTPS and mixed content", default_severity=Sev.HIGH, method="D"),
        CheckSpec(id="S1.11", title="html lang attribute", default_severity=Sev.LOW, method="D"),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        pages = load_pages(ctx)
        keys = key_page_urls(pages, ctx.client.primary_url)
        sample = sample_info(ctx)
        in_sitemap = {_norm(u) for u in sample.get("sample_in_sitemap", [])}
        html_pages = [p for p in pages if p.status == 200 and p.model and not p.model.get("parse_error")]
        findings: list[Finding] = []
        patches: list[Patch] = []

        findings += self._status(pages, keys, html_pages, in_sitemap)
        findings += self._soft_404(html_pages)
        findings += self._redirects(pages)
        findings += self._indexability(html_pages, keys, in_sitemap)
        findings += self._robots(ctx, pages, keys)
        canonical_findings, canonical_patches = self._canonicals(html_pages, pages)
        findings += canonical_findings
        patches += canonical_patches
        findings += self._sitemap(ctx, pages, in_sitemap)
        findings += self._variants(ctx)
        duplicate_findings, thin_own_content = self._duplicates(html_pages)
        findings += duplicate_findings
        findings += self._https(html_pages, keys)
        lang_findings, lang_patches = self._lang(html_pages)
        findings += lang_findings
        patches += lang_patches

        rows = [[p.record.url, p.status, p.url, "no" if _noindex(p) else "yes",
                 (p.model or {}).get("canonical") or "—", "yes" if _norm(p.url) in in_sitemap else "no"]
                for p in pages]
        limits = [f"Checked the {len(pages)} sampled pages, not the whole site."]
        if thin_own_content:
            limits.append(f"{len(thin_own_content)} page(s) had too little content of their own in the "
                          "server HTML to compare for duplicates (content may load via JavaScript; see G1): "
                          + ", ".join(thin_own_content[:5]))
        coverage = Coverage(examined={"pages": len(pages), "html_pages": len(html_pages)}, limits=limits)
        return AgentResult(findings=findings, patches=patches, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    # ----------------------------------------------------------------- S1.01

    @staticmethod
    def _found_at(target: PageView, html_pages: list[PageView], in_sitemap: set[str]) -> str:
        """Where the crawler found a URL: which pages link to it (and how), or the sitemap."""
        wanted = {_norm(target.record.url), _norm(target.url)}
        sources = []
        for p in html_pages:
            for link in p.model.get("links", []):
                if _norm(link["href"]) in wanted:
                    place = "nav" if link.get("in_nav") else "footer" if link.get("in_footer") else "body"
                    sources.append(f"{p.url} ({place} link \"{link['text'][:40]}\")")
                    break
        if _norm(target.record.url) in in_sitemap:
            sources.append("the XML sitemap")
        return "; linked from " + ", ".join(sources[:3]) if sources else ""

    def _status(self, pages: list[PageView], keys: set[str], html_pages: list[PageView],
                in_sitemap: set[str]) -> list[Finding]:
        broken = [p for p in pages if p.status is not None and p.status >= 400]
        unreachable = [p for p in pages if p.status is None]
        out = []
        if broken:
            out.append(self.finding(
                "S1.01", St.FAIL, f"{len(broken)} sampled URL(s) return an error status",
                pages=[p.record.url for p in broken], key_page=any(p.url in keys or p.is_home for p in broken),
                severity=Sev.CRITICAL if any(p.is_home for p in broken) else None,
                evidence=[EvidenceRef(type="status", url=p.record.url,
                                      excerpt=f"HTTP {p.status}{self._found_at(p, html_pages, in_sitemap)}")
                          for p in broken[:5]],
                impact="Visitors and crawlers following these links hit an error page, and the links waste crawl effort.",
                fix="Update or remove the links shown in the evidence, or 301-redirect each URL to the closest live page.",
                verification="Re-crawl: each URL returns 200 or a single 301 hop.", effort=Effort.S))
        if unreachable:
            out.append(self.finding(
                "S1.01", St.WARN, f"{len(unreachable)} sampled URL(s) could not be fetched",
                pages=[p.record.url for p in unreachable],
                evidence=[EvidenceRef(type="status", url=p.record.url, excerpt=p.record.fetch.get("error") or "no response")
                          for p in unreachable[:5]],
                confidence=Confidence.LIKELY,
                impact="Timeouts or blocks for our crawler may also affect search engine crawlers.",
                fix="Check server logs and firewall rules for these URLs.",
                verification="Re-crawl succeeds for each URL."))
        if not broken and not unreachable:
            out.append(self.finding("S1.01", St.PASS, "All sampled URLs return 200",
                                    evidence=[EvidenceRef(type="status", excerpt=f"{len(pages)} pages, all HTTP 200")]))
        return out

    # ----------------------------------------------------------------- S1.02

    def _soft_404(self, html_pages: list[PageView]) -> list[Finding]:
        suspects = []
        for p in html_pages:
            if p.is_home:
                continue
            title = p.model.get("title") or ""
            h1 = " ".join(h["text"] for h in p.model.get("headings", []) if h["level"] == 1)
            if _SOFT_404.search(title) or _SOFT_404.search(h1):
                suspects.append((p, title or h1))
        if not suspects:
            return [self.finding("S1.02", St.PASS, "No soft 404s detected")]
        return [self.finding(
            "S1.02", St.FAIL, f"{len(suspects)} page(s) look like error pages but return 200",
            pages=[p.record.url for p, _ in suspects], confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="html_excerpt", url=p.record.url, excerpt=text[:160]) for p, text in suspects[:5]],
            impact="Search engines may index these as thin pages or treat them as errors inconsistently.",
            fix="Return a real 404/410 status for missing pages, or restore the intended content.",
            verification="Re-crawl: these URLs return 404/410, or show real content.", effort=Effort.S)]

    # ----------------------------------------------------------------- S1.03

    def _redirects(self, pages: list[PageView]) -> list[Finding]:
        long_chains, two_hops, temporary = [], [], []
        for p in pages:
            hops = p.record.fetch.get("redirects") or []
            if len(hops) >= 3:
                long_chains.append((p, hops))
            elif len(hops) == 2:
                two_hops.append((p, hops))
            if any(h["status"] in (302, 307) for h in hops):
                temporary.append((p, hops))

        def chain(hops: list[dict]) -> str:
            return " → ".join(f"{h['url']} ({h['status']})" for h in hops)[:300]

        out = []
        if long_chains:
            out.append(self.finding(
                "S1.03", St.FAIL, f"{len(long_chains)} URL(s) redirect through 3 or more hops",
                pages=[p.record.url for p, _ in long_chains],
                evidence=[EvidenceRef(type="status", url=p.record.url, excerpt=chain(h)) for p, h in long_chains[:5]],
                impact="Each hop slows crawling and page loads; long chains may not be followed at all.",
                fix="Point each old URL straight at its final destination with one 301.",
                verification="Re-crawl: at most one redirect hop.", effort=Effort.S))
        if two_hops or temporary:
            affected = {p.record.url: h for p, h in two_hops + temporary}
            out.append(self.finding(
                "S1.03", St.WARN, "Some redirects use 2 hops or temporary (302/307) status",
                pages=list(affected),
                evidence=[EvidenceRef(type="status", url=u, excerpt=chain(h)) for u, h in list(affected.items())[:5]],
                impact="Temporary redirects may not pass signals to the destination if the move is permanent.",
                fix="Use a single 301 (or 308) for permanent moves.",
                verification="Re-crawl: one 301/308 hop."))
        if not out:
            out.append(self.finding("S1.03", St.PASS, "No redirect chains or temporary redirects in the sample"))
        return out

    # ----------------------------------------------------------------- S1.04

    def _indexability(self, html_pages: list[PageView], keys: set[str], in_sitemap: set[str]) -> list[Finding]:
        key_blocked, sitemap_blocked = [], []
        for p in html_pages:
            source = _noindex(p)
            if not source:
                continue
            if p.is_home or p.url in keys:
                key_blocked.append((p, source))
            elif _norm(p.url) in in_sitemap:
                sitemap_blocked.append((p, source))
        out = []
        if key_blocked:
            out.append(self.finding(
                "S1.04", St.FAIL, f"{len(key_blocked)} key page(s) are set to noindex",
                pages=[p.record.url for p, _ in key_blocked], severity=Sev.CRITICAL,
                evidence=[EvidenceRef(type="html_excerpt", url=p.record.url, excerpt=src) for p, src in key_blocked[:5]],
                impact="These pages are excluded from Google and every AI system grounded in search.",
                fix="Remove the noindex directive from these pages unless hiding them is intended.",
                verification="Re-crawl: no noindex in meta robots or X-Robots-Tag.", effort=Effort.S))
        if sitemap_blocked:
            out.append(self.finding(
                "S1.04", St.WARN, f"{len(sitemap_blocked)} noindex page(s) are listed in the sitemap",
                pages=[p.record.url for p, _ in sitemap_blocked],
                evidence=[EvidenceRef(type="html_excerpt", url=p.record.url, excerpt=src) for p, src in sitemap_blocked[:5]],
                impact="Mixed signals: the sitemap asks for indexing while the page refuses it.",
                fix="Either remove noindex or remove the URL from the sitemap.",
                verification="Re-crawl: sitemap and directives agree."))
        if not out:
            out.append(self.finding("S1.04", St.PASS, "Key pages are indexable"))
        return out

    # ----------------------------------------------------------------- S1.05

    def _robots(self, ctx: AgentContext, pages: list[PageView], keys: set[str]) -> list[Finding]:
        info, text = site_file(ctx, "robots.txt")
        if info is None:
            return [self.finding("S1.05", St.UNVERIFIABLE, "robots.txt was not captured")]
        status = info.get("status")
        if status is None or status >= 500:
            return [self.finding(
                "S1.05", St.WARN, "robots.txt is unreachable",
                evidence=[EvidenceRef(type="status", url=info.get("url"), excerpt=f"HTTP {status} {info.get('error') or ''}")],
                impact="Google treats a 5xx robots.txt as 'disallow everything' after a while.",
                fix="Make /robots.txt return 200 (or 404 if you have no rules).",
                verification="GET /robots.txt returns 200 or 404.")]
        if status != 200 or not text:
            return [self.finding("S1.05", St.PASS, "No robots.txt rules (404), so everything is allowed",
                                 evidence=[EvidenceRef(type="status", url=info.get("url"), excerpt=f"HTTP {status}")])]
        robots = parse_robots(text)
        blocked = []
        for p in pages:
            if p.is_home or p.url in keys:
                rule = robots.matching_rule(GOOGLEBOT, p.url)
                if rule and rule[0] == "disallow":
                    blocked.append((p, rule))
        home = next((p for p in pages if p.is_home and p.model), None)
        blocked_resources = []
        if home:
            home_host = urlsplit(home.url).hostname
            for res in home.model.get("resources", []):
                src = res.get("src") or ""
                if res["tag"] not in ("script", "link") or urlsplit(src).hostname != home_host:
                    continue
                rule = robots.matching_rule(GOOGLEBOT, src)
                if rule and rule[0] == "disallow":
                    blocked_resources.append((src, rule))
        if blocked:
            return [self.finding(
                "S1.05", St.FAIL, f"robots.txt blocks {len(blocked)} key page(s) from Google",
                pages=[p.record.url for p, _ in blocked], severity=Sev.CRITICAL,
                evidence=[EvidenceRef(type="file_excerpt", url=info.get("url"),
                                      excerpt=f"line {r[2]}: Disallow: {r[1]}  (blocks {p.record.url})")
                          for p, r in blocked[:5]],
                impact="Blocked pages can't be crawled, so their content can't rank or be cited.",
                fix="Remove or narrow the Disallow rules that match these pages.",
                verification="robots.txt allows Googlebot on every key page.", effort=Effort.S)]
        if blocked_resources:
            return [self.finding(
                "S1.05", St.FAIL, "robots.txt blocks CSS/JS needed to render the homepage",
                severity=Sev.HIGH,
                evidence=[EvidenceRef(type="file_excerpt", url=info.get("url"),
                                      excerpt=f"line {r[2]}: Disallow: {r[1]}  (blocks {src})")
                          for src, r in blocked_resources[:5]],
                impact="Google can't render the page as users see it.",
                fix="Allow crawling of CSS and JavaScript files.",
                verification="robots.txt allows the homepage's CSS and JS.", effort=Effort.S)]
        return [self.finding("S1.05", St.PASS, "robots.txt allows key pages and their resources")]

    # ----------------------------------------------------------------- S1.06

    def _canonicals(self, html_pages: list[PageView], pages: list[PageView]) -> tuple[list[Finding], list[Patch]]:
        # Exact requested URLs first, so a redirected URL never shadows its destination.
        by_url: dict[str, PageView] = {}
        for p in pages:
            by_url.setdefault(_norm(p.record.url), p)
        for p in pages:
            by_url.setdefault(_norm(p.url), p)
        missing, bad = [], []
        for p in html_pages:
            canonical = p.model.get("canonical")
            if not canonical:
                missing.append(p)
                continue
            target = by_url.get(_norm(canonical))
            if target is None or target is p:
                continue
            if target.status != 200 or _noindex(target) or (target.record.fetch.get("redirects")):
                bad.append((p, canonical, target))
        out: list[Finding] = []
        patches: list[Patch] = []
        if bad:
            out.append(self.finding(
                "S1.06", St.FAIL, f"{len(bad)} page(s) point their canonical at a broken, redirected or noindex URL",
                pages=[p.record.url for p, _, _ in bad],
                evidence=[EvidenceRef(type="html_excerpt", url=p.record.url,
                                      excerpt=f'<link rel="canonical" href="{c}"> → HTTP {t.status}')
                          for p, c, t in bad[:5]],
                impact="Search engines may ignore the canonical or consolidate signals onto a dead URL.",
                fix="Point each canonical at the live, indexable version of the page (usually itself).",
                verification="Each canonical target returns 200 and is indexable.", effort=Effort.S))
        if missing:
            keys = []
            for p in missing:
                key = f"S1.06:canonical:{p.record.id}"
                keys.append(key)
                patches.append(Patch(
                    key=key, agent_id=self.id, page_url=p.url, type=PatchType.HEAD_UPSERT,
                    locator=Locator(css="head"), before=None,
                    after=f'<link rel="canonical" href="{p.url}">',
                    rationale="Self-referencing canonical on the page's final URL.",
                    client_visible_note="Tells search engines which URL is the main version of this page."))
            out.append(self.finding(
                "S1.06", St.WARN, f"{len(missing)} page(s) have no canonical tag",
                pages=[p.record.url for p in missing], patch_keys=keys,
                evidence=[EvidenceRef(type="html_excerpt", url=p.record.url, excerpt="no <link rel=\"canonical\"> in <head>")
                          for p in missing[:5]],
                impact="Without a canonical, URL variants (tracking parameters, slashes) can split signals.",
                fix="Add a self-referencing canonical to each page.",
                verification="Each page has one canonical pointing to its own final URL.", effort=Effort.S))
        if not out:
            out.append(self.finding("S1.06", St.PASS, "Canonical tags are present and point to live pages"))
        return out, patches

    # ----------------------------------------------------------------- S1.07

    def _sitemap(self, ctx: AgentContext, pages: list[PageView], in_sitemap: set[str]) -> list[Finding]:
        sitemaps = [e.payload for e in ctx.snapshot.evidence(EvidenceType.SITE_FILES) if e.payload.get("kind") == "sitemap"]
        valid = [s for s in sitemaps if s.get("status") == 200 and (s.get("url_count") or s.get("child_count"))]
        robots_info, robots_text = site_file(ctx, "robots.txt")
        declared = bool(robots_text and parse_robots(robots_text).sitemaps)
        if not valid:
            return [self.finding(
                "S1.07", St.FAIL, "No valid XML sitemap found",
                evidence=[EvidenceRef(type="status", url=s.get("url"), excerpt=f"HTTP {s.get('status')}") for s in sitemaps[:3]]
                or [EvidenceRef(type="status", excerpt="no sitemap declared or at /sitemap.xml")],
                impact="Search engines discover and refresh pages more slowly without a sitemap.",
                fix="Publish /sitemap.xml listing every indexable canonical URL and declare it in robots.txt.",
                verification="/sitemap.xml returns valid XML and is declared in robots.txt.", effort=Effort.S)]
        sampled_from_sitemap = [p for p in pages if _norm(p.url) in in_sitemap or _norm(p.record.url) in in_sitemap]
        bad = [p for p in sampled_from_sitemap if p.status != 200 or p.record.fetch.get("redirects")]
        if sampled_from_sitemap and len(bad) / len(sampled_from_sitemap) >= 0.10:
            return [self.finding(
                "S1.07", St.FAIL, f"{len(bad)} of {len(sampled_from_sitemap)} sampled sitemap URLs are not clean 200s",
                pages=[p.record.url for p in bad],
                evidence=[EvidenceRef(type="status", url=p.record.url, excerpt=f"HTTP {p.status}"
                                      + (" after redirect" if p.record.fetch.get("redirects") else "")) for p in bad[:5]],
                impact="Sitemaps with broken or redirected URLs lose search engines' trust.",
                fix="List only final, 200, indexable canonical URLs in the sitemap.",
                verification="Every sitemap URL returns 200 without redirects.", effort=Effort.S)]
        if not declared:
            return [self.finding(
                "S1.07", St.WARN, "Sitemap exists but isn't declared in robots.txt",
                evidence=[EvidenceRef(type="file_excerpt", url=(robots_info or {}).get("url"), excerpt="no 'Sitemap:' line")],
                impact="Crawlers other than Google may not find the sitemap.",
                fix="Add 'Sitemap: <absolute sitemap URL>' to robots.txt.",
                verification="robots.txt contains a Sitemap line.", effort=Effort.S)]
        return [self.finding("S1.07", St.PASS, "Valid sitemap, declared in robots.txt, with clean URLs")]

    # ----------------------------------------------------------------- S1.08

    def _variants(self, ctx: AgentContext) -> list[Finding]:
        evidence = ctx.snapshot.evidence(EvidenceType.URL_VARIANTS)
        if not evidence:
            return [self.finding("S1.08", St.UNVERIFIABLE, "URL variants were not probed")]
        data = evidence[0].payload
        home = urlsplit(data["canonical_home"])
        stray = [v for v in data["variants"]
                 if v["status"] == 200 and (urlsplit(v["final_url"]).scheme, urlsplit(v["final_url"]).hostname)
                 != (home.scheme, home.hostname)]
        if not stray:
            return [self.finding("S1.08", St.PASS, "All http/https and www/non-www variants resolve to one version")]
        return [self.finding(
            "S1.08", St.FAIL if len(stray) >= 2 else St.WARN,
            f"{len(stray)} URL variant(s) serve the site without redirecting to {home.scheme}://{home.hostname}",
            evidence=[EvidenceRef(type="status", url=v["variant"], excerpt=f"{v['variant']} → 200 at {v['final_url']}")
                      for v in stray],
            impact="Duplicate hostnames split ranking signals and can create duplicate content.",
            fix=f"301-redirect every variant to {home.scheme}://{home.hostname}/.",
            verification="Each variant returns a single 301 to the main version.", effort=Effort.S)]

    # ----------------------------------------------------------------- S1.09

    def _duplicates(self, html_pages: list[PageView]) -> tuple[list[Finding], list[str]]:
        """Returns findings and the pages with too little own content to compare."""
        # One view per final URL: a redirect and its destination are the same page.
        unique_pages = list({p.url: p for p in sorted(html_pages, key=lambda v: v.record.url != v.url)}.values())
        template = template_blocks([p.model for p in unique_pages])
        own = {p.url: own_text(p.model, template) for p in unique_pages}
        substantive = [p for p in unique_pages if len(own[p.url].split()) >= 50]
        thin = [p.url for p in unique_pages if p not in substantive]
        exact_groups: dict[str, list[PageView]] = {}
        for p in substantive:
            exact_groups.setdefault(" ".join(own[p.url].lower().split()), []).append(p)
        exact = [g for g in exact_groups.values() if len(g) > 1
                 and len({_norm(p.model.get("canonical") or p.url) for p in g}) > 1]
        firsts = [g[0] for g in exact_groups.values()]
        grams = {p.url: shingles(own[p.url]) for p in firsts}
        near = [(a, b) for i, a in enumerate(firsts) for b in firsts[i + 1:]
                if jaccard(grams[a.url], grams[b.url]) >= 0.9]
        out = []
        if exact:
            out.append(self.finding(
                "S1.09", St.FAIL, f"{len(exact)} group(s) of pages have identical content without a shared canonical",
                pages=[p.record.url for g in exact for p in g],
                evidence=[EvidenceRef(type="html_excerpt", excerpt=" = ".join(p.url for p in g)[:300]) for g in exact[:5]],
                impact="Duplicate pages compete with each other and dilute signals.",
                fix="Merge the duplicates, or canonicalize them to the one you want indexed.",
                verification="Each duplicate group has one indexable URL.", effort=Effort.M))
        if near:
            out.append(self.finding(
                "S1.09", St.WARN, f"{len(near)} pair(s) of pages are near-duplicates (90%+ of their own content matches)",
                pages=sorted({p.record.url for pair in near for p in pair}), confidence=Confidence.LIKELY,
                evidence=[EvidenceRef(type="html_excerpt", excerpt=f"{a.url} ~ {b.url}") for a, b in near[:5]],
                impact="Near-identical pages (e.g. city-swapped templates) look thin and may be treated as doorways.",
                fix="Make each page substantively unique, or consolidate them.",
                verification="Re-crawl: pages no longer near-identical."))
        if not out:
            out.append(self.finding(
                "S1.09", St.PASS, "No duplicate or near-duplicate pages in the sample",
                evidence=[EvidenceRef(type="html_excerpt",
                                      excerpt=f"compared {len(substantive)} pages on their own content "
                                              f"({len(template)} site-wide template blocks excluded)")]))
        return out, thin

    # ----------------------------------------------------------------- S1.10

    def _https(self, html_pages: list[PageView], keys: set[str]) -> list[Finding]:
        http_pages = [p for p in html_pages if p.url.startswith("http://")]
        active, passive = [], []
        for p in html_pages:
            if not p.url.startswith("https://"):
                continue
            for res in p.model.get("resources", []):
                src = res.get("src") or ""
                if src.startswith("http://"):
                    (active if res["tag"] in _ACTIVE else passive).append((p, res["tag"], src))
        out = []
        if http_pages or active:
            out.append(self.finding(
                "S1.10", St.FAIL,
                "Pages served over HTTP" if http_pages else f"Active mixed content on {len({p.url for p, _, _ in active})} page(s)",
                pages=sorted({p.record.url for p in http_pages} | {p.record.url for p, _, _ in active}),
                key_page=any(p.is_home for p in http_pages),
                evidence=[EvidenceRef(type="html_excerpt", url=p.record.url, excerpt=f"page served over {p.url[:5]}")
                          for p in http_pages[:3]]
                + [EvidenceRef(type="html_excerpt", url=p.record.url, excerpt=f"<{tag} src=\"{src}\">") for p, tag, src in active[:5]],
                impact="Browsers block active mixed content and warn users; HTTP pages lose trust signals.",
                fix="Serve everything over HTTPS and update resource URLs to https://.",
                verification="Re-crawl: all pages and resources load over HTTPS.", effort=Effort.S))
        if passive:
            out.append(self.finding(
                "S1.10", St.WARN, f"Passive mixed content (images/media over HTTP) on {len({p.url for p, _, _ in passive})} page(s)",
                pages=sorted({p.record.url for p, _, _ in passive}),
                evidence=[EvidenceRef(type="html_excerpt", url=p.record.url, excerpt=f"<{tag} src=\"{src}\">") for p, tag, src in passive[:5]],
                impact="Browsers flag the page as not fully secure.",
                fix="Load images and media over https://.",
                verification="Re-crawl: no http:// resources on HTTPS pages.", effort=Effort.S))
        if not out:
            out.append(self.finding("S1.10", St.PASS, "All sampled pages and resources load over HTTPS"))
        return out

    # ----------------------------------------------------------------- S1.11

    def _lang(self, html_pages: list[PageView]) -> tuple[list[Finding], list[Patch]]:
        missing = [p for p in html_pages if not p.model.get("lang")]
        if not missing:
            return [self.finding("S1.11", St.PASS, "Every page declares its language")], []
        patches, keys = [], []
        for p in missing:
            key = f"S1.11:lang:{p.record.id}"
            keys.append(key)
            patches.append(Patch(
                key=key, agent_id=self.id, page_url=p.url, type=PatchType.ATTRIBUTE_SET,
                locator=Locator(css="html", xpath="/html"), before=None, after='lang="en-IN"',
                rationale="Pages are in English for an India audience.", confidence=Confidence.LIKELY,
                client_visible_note="Declares the page language for search engines and screen readers."))
        return [self.finding(
            "S1.11", St.WARN, f"{len(missing)} page(s) have no html lang attribute",
            pages=[p.record.url for p in missing], patch_keys=keys,
            evidence=[EvidenceRef(type="html_excerpt", url=p.record.url, excerpt="<html> without lang") for p in missing[:5]],
            impact="Search engines and assistive technology have to guess the language.",
            fix='Add lang="en-IN" (or the correct language) to the <html> tag.',
            verification="Every page has a lang attribute.", effort=Effort.S)], patches
