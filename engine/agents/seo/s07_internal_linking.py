"""S7 Internal Linking: are important pages linked from relevant body text with descriptive anchors?

Everything is measured on the sample graph (default 25 pages), so absence findings are
worded as "in the sample" with matching confidence. Ownership: links to 4xx/5xx targets are
S1.01 (reported with their source pages); S7.05 owns links that point at redirects.

Deterministic: S7.01–S7.06. LLM (one batched call, fast tier): S7.07 filters candidate link
opportunities and picks an anchor copied exactly from the passage (validated).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from engine.agents.base import Agent
from engine.agents.common import PageView, entry_page, key_page_urls, load_pages, norm, sample_info, tally
from engine.context import AgentContext, WorkUnit
from engine.lib.content import template_blocks
from engine.lib.grounding import normalize, quote_in_text
from engine.lib.linkgraph import LinkGraph
from engine.lib.locators import text_hash
from engine.llm import LLMError, load_prompt
from engine.schemas import (
    AgentResult,
    CheckSpec,
    CheckStatus as St,
    Confidence,
    Coverage,
    Effort,
    EvidenceRef,
    EvidenceType,
    Locator,
    Patch,
    PatchType,
    Pillar,
    Severity as Sev,
)

GENERIC_ANCHORS = {"click here", "here", "read more", "know more", "learn more", "more", "view more", "view details",
                   "details", "explore", "visit", "link", "this", "go", "see more", "find out more", "continue"}
MAX_CANDIDATES = 10
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "with", "from", "by", "is", "your",
         "our", "best", "stay", "close"}


class LinkPick(BaseModel):
    id: str
    useful: bool
    anchor: str | None = None


class LinkPicks(BaseModel):
    links: list[LinkPick] = Field(default_factory=list)


def destination_name(page) -> str | None:
    """A linked page's own name: its single H1, else its title before the site name ("Gold loan | Brand")."""
    h1s = [h["text"].strip() for h in page.model.get("headings", []) if h["level"] == 1 and h["text"].strip()]
    name = h1s[0] if len(h1s) == 1 else re.split(r"\s+[|–—-]\s+", page.model.get("title") or "")[0].strip()
    return name if 3 <= len(name) <= 50 and not is_generic(name) else None


def is_generic(text: str) -> bool:
    return normalize(text).strip(" .!›»>") in GENERIC_ANCHORS


def phrases(text: str, brand: set[str]) -> list[str]:
    """2–4 word phrases from a title/H1 that could serve as an anchor (brand-only phrases excluded)."""
    parts = re.split(r"\s*[|–—:-]\s*", text.lower())
    out = []
    for part in parts:
        words = _WORD.findall(part)
        for size in (4, 3, 2):
            for i in range(len(words) - size + 1):
                gram = words[i:i + size]
                content = [w for w in gram if w not in _STOP]
                if len(content) >= 2 and not set(content) <= brand and gram[0] not in _STOP and gram[-1] not in _STOP:
                    out.append(" ".join(gram))
    return list(dict.fromkeys(out))


class InternalLinking(Agent):
    id = "S7"
    name = "Internal Linking"
    pillar = Pillar.SEO
    requires = frozenset({EvidenceType.PAGES_RAW, EvidenceType.PAGES_PARSED, EvidenceType.SITE_FILES})
    signature_columns = ["Page", "Body inlinks", "Nav/footer inlinks", "Click depth", "Generic body anchors",
                         "Suggested links"]
    checks = [
        CheckSpec(id="S7.01", title="Pages without inlinks in the sample", default_severity=Sev.MEDIUM, method="D"),
        CheckSpec(id="S7.02", title="Click depth of key pages", default_severity=Sev.MEDIUM, method="D"),
        CheckSpec(id="S7.03", title="Contextual inlinks to key pages", default_severity=Sev.MEDIUM, method="D"),
        CheckSpec(id="S7.04", title="Anchor text", default_severity=Sev.LOW, method="D"),
        CheckSpec(id="S7.05", title="Internal links to redirects", default_severity=Sev.MEDIUM, method="D"),
        CheckSpec(id="S7.06", title="Contextual linking from key pages", default_severity=Sev.LOW, method="D"),
        CheckSpec(id="S7.07", title="Link opportunities", default_severity=Sev.LOW, method="D+L"),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        all_pages = load_pages(ctx)
        pages = [p for p in all_pages if p.is_html]
        graph = LinkGraph.build(pages, all_pages)
        keys = {norm(u) for u in key_page_urls(pages, ctx.client.primary_url)}
        entry = entry_page(pages, ctx.client.primary_url)
        home = next((p for p in pages if p.is_home), None)
        in_menus = {e.target for e in graph.edges if e.placement in ("nav", "footer")}
        sitemap_count = sample_info(ctx).get("sitemap_url_count") or 0
        coverage = Coverage(examined={"pages": len(pages), "links": len(graph.edges),
                                      "links_to_unsampled_pages": graph.outside_sample})
        coverage.limits.append(f"Link graph of the {len(pages)} sampled pages"
                               + (f" (of ~{sitemap_count} in the sitemap)" if sitemap_count else "")
                               + "; a page may be linked from pages outside the sample.")

        findings = [
            self._no_inlinks(graph, home, entry, sitemap_count),
            self._depth(graph, home, keys, coverage),
            self._contextual_inlinks(graph, keys, in_menus, home),
        ]
        anchor_finding, anchor_patches = self._anchors(graph, home)
        findings.append(anchor_finding)
        redirect_finding, redirect_patches = self._redirects(graph)
        findings.append(redirect_finding)
        findings.append(self._contextual_outlinks(graph, keys))
        opportunity_finding, link_patches = self._opportunities(ctx, graph, pages, keys, entry, home, coverage)
        findings.append(opportunity_finding)

        suggested = {}
        for patch in link_patches:
            suggested[norm(patch.page_url)] = suggested.get(norm(patch.page_url), 0) + 1
        depths = graph.depths(norm(home.url)) if home else {}
        rows = []
        for node in sorted(keys | ({norm(entry.url)} if entry else set())):
            if node not in graph.nodes:
                continue
            body = graph.inbound(node, "body")
            menus = [e for e in graph.inbound(node) if e.placement != "body"]
            generic = sum(1 for e in graph.outbound(node, "body") if is_generic(e.text))
            rows.append([graph.nodes[node].url, len({e.source for e in body}), len({e.source for e in menus}),
                         depths.get(node, "not reached"), generic, suggested.get(node, 0)])
        return AgentResult(findings=findings, patches=redirect_patches + link_patches + anchor_patches,
                           coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    # ------------------------------------------------------------ S7.01

    def _no_inlinks(self, graph: LinkGraph, home, entry, sitemap_count):
        isolated = [p for node, p in graph.nodes.items()
                    if not graph.inbound(node) and p is not home]
        if not isolated:
            return self.finding("S7.01", St.PASS, "Every sampled page is linked from another sampled page")
        small_sample = sitemap_count and len(graph.nodes) < sitemap_count / 2
        return self.finding(
            "S7.01", St.WARN, f"{len(isolated)} sampled page(s) have no links from the other sampled pages",
            pages=[p.url for p in isolated], confidence=Confidence.HYPOTHESIS if small_sample else Confidence.LIKELY,
            key_page=any(p is entry for p in isolated),
            evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt="0 inlinks within the sample")
                      for p in isolated[:5]],
            impact="Pages that few other pages link to are crawled less often and pass on less authority.",
            fix="Link these pages from relevant pages (hub pages, related content, the nav if they're important).",
            verification="Re-crawl with a larger sample: each page has inlinks.", effort=Effort.S)

    # ------------------------------------------------------------ S7.02

    def _depth(self, graph: LinkGraph, home, keys: set[str], coverage: Coverage):
        if home is None:
            return self.finding("S7.02", St.UNVERIFIABLE, "Homepage not in the sample")
        depths = graph.depths(norm(home.url))
        unreached = [k for k in keys if k in graph.nodes and k not in depths]
        if unreached:
            coverage.limits.append(f"{len(unreached)} key page(s) aren't reachable from the homepage within the "
                                   "sample, so their click depth is unknown.")
        deep = [(k, depths[k]) for k in keys if depths.get(k, 0) >= 4]
        if not deep:
            return self.finding("S7.02", St.PASS, "Key pages are within 3 clicks of the homepage (in the sample)",
                                evidence=[EvidenceRef(type="html_excerpt",
                                                      excerpt=", ".join(f"{graph.nodes[k].url}: {depths[k]}"
                                                                        for k in sorted(keys) if k in depths)[:300])])
        worst = max(d for _, d in deep)
        return self.finding(
            "S7.02", St.FAIL if worst >= 5 else St.WARN, f"{len(deep)} key page(s) are 4+ clicks from the homepage",
            pages=[graph.nodes[k].url for k, _ in deep],
            evidence=[EvidenceRef(type="html_excerpt", url=graph.nodes[k].url, excerpt=f"{d} clicks from home")
                      for k, d in deep[:5]],
            impact="Deep pages get crawled less and look less important.",
            fix="Link key pages from the homepage, the nav or hub pages.", verification="Key pages ≤3 clicks deep.",
            effort=Effort.S)

    # ------------------------------------------------------------ S7.03

    def _contextual_inlinks(self, graph: LinkGraph, keys: set[str], in_menus: set[str], home):
        weak = [k for k in keys if k in graph.nodes and k not in in_menus and graph.nodes[k] is not home
                and not graph.inbound(k, "body")]
        checked = [k for k in keys if k in graph.nodes and k not in in_menus and graph.nodes[k] is not home]
        if not weak:
            return self.finding(
                "S7.03", St.PASS, "Key pages outside the nav are linked from body text",
                evidence=[EvidenceRef(type="html_excerpt", url=graph.nodes[k].url,
                                      excerpt=f"{len({e.source for e in graph.inbound(k, 'body')})} page(s) link here "
                                              "from body text") for k in checked[:3]]
                or [EvidenceRef(type="html_excerpt", excerpt="all key pages are in the nav")])
        return self.finding(
            "S7.03", St.FAIL, f"{len(weak)} key page(s) aren't in the nav and have no body links in the sample",
            pages=[graph.nodes[k].url for k in weak], key_page=True, confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="html_excerpt", url=graph.nodes[k].url, excerpt="0 body inlinks, not in nav/footer")
                      for k in weak[:5]],
            impact="Search engines judge importance partly by internal links; these key pages get almost none.",
            fix="Link to them from related body text (suggestions under S7.07) and from hub/listing pages.",
            verification="Each key page has contextual inlinks.", effort=Effort.S)

    # ------------------------------------------------------------ S7.04

    def _anchor_patches(self, graph: LinkGraph, generic) -> list[Patch]:
        """Prepared changes (approval required): a vague text link names its destination, from that page's own H1
        or title ("Know more" → "Know more about Gold loan"). Links that are images, or whose destination has no
        clear name, are left for the team."""
        patches, seen = [], set()
        for edge in generic:
            locator, target = edge.link.get("locator"), graph.nodes[edge.target]
            name = destination_name(target)
            key = f"S7.04:{text_hash(edge.source + edge.link['href'] + edge.text)}"
            if not locator or edge.link.get("image") or not name or key in seen:
                continue
            seen.add(key)
            words = normalize(edge.text).strip(" .!›»>")
            text = name if words in ("click here", "here", "link", "this", "go", "visit")                 else f"{edge.text.strip(' .!›»>')} about {name}"
            patches.append(Patch(key=key, agent_id=self.id, page_url=graph.nodes[edge.source].url,
                                 type=PatchType.TEXT_REPLACE, locator=Locator(**locator), before=edge.text,
                                 after=text, confidence=Confidence.LIKELY, approval="required",
                                 rationale=f"Names the page the link opens ({target.url}), using that page's own heading. "
                                           "If the link holds an icon, keep it in your template.",
                                 client_visible_note="Link words that say where the link goes."))
        return patches[:10]

    def _anchors(self, graph: LinkGraph, home):
        home_node = norm(home.url) if home else None
        body = [e for e in graph.edges if e.placement == "body" and e.target != home_node]  # breadcrumb "Home" is fine
        if not body:
            return self.finding("S7.04", St.NOT_APPLICABLE, "No body links between sampled pages"), []
        generic = [e for e in body if is_generic(e.text)]
        empty = [e for e in body if not e.text.strip()]
        share = (len(generic) + len(empty)) / len(body)
        if share <= 0.3 and not empty:
            return self.finding("S7.04", St.PASS, "Body links use descriptive anchor text",
                                evidence=[EvidenceRef(type="html_excerpt", excerpt=f"{len(body)} body links checked")]), []
        patches = self._anchor_patches(graph, generic)
        return self.finding(
            "S7.04", St.WARN,
            f"{tally((len(generic), 'generic'), (len(empty), 'empty'))} anchor(s) among {len(body)} body links",
            pages=sorted({graph.nodes[e.source].url for e in generic + empty}),
            evidence=[EvidenceRef(type="html_excerpt", url=graph.nodes[e.source].url,
                                  excerpt=f"\"{e.text or '(image link without alt text)'}\" → {graph.nodes[e.target].url}")
                      for e in (empty + generic)[:5]],
            impact="Anchors like \"know more\" or image links without alt text tell search engines nothing about "
                   "the linked page.",
            fix="Use anchors that name the destination; give linked images descriptive alt text.",
            patch_keys=[p.key for p in patches],
            verification="Body anchors describe their targets.", effort=Effort.S), patches

    # ------------------------------------------------------------ S7.05

    def _redirects(self, graph: LinkGraph):
        hops = [e for e in graph.edges if e.via_redirect]
        if not hops:
            return self.finding("S7.05", St.PASS, "No internal links point at redirecting URLs"), []
        patches, keys = [], []
        for edge in hops:
            locator = edge.link.get("locator")
            if not locator:
                continue  # nav/footer links: the template has to change
            key = f"S7.05:{text_hash(edge.source + edge.link['href'])}"
            if key in keys:
                continue
            final = graph.nodes[edge.target].url
            patches.append(Patch(key=key, agent_id=self.id, page_url=graph.nodes[edge.source].url,
                                 type=PatchType.ATTRIBUTE_SET, locator=Locator(**locator), before=edge.link["href"],
                                 after=f'href="{final}"', rationale=f"Point the link straight at {final} instead "
                                                                    "of a URL that redirects there.",
                                 client_visible_note="Saves a redirect for visitors and crawlers."))
            keys.append(key)
        return self.finding(
            "S7.05", St.WARN, f"{len(hops)} internal link(s) point at URLs that redirect",
            pages=sorted({graph.nodes[e.source].url for e in hops}), patch_keys=keys,
            evidence=[EvidenceRef(type="html_excerpt", url=graph.nodes[e.source].url,
                                  excerpt=f"{e.link['href']} → {graph.nodes[e.target].url} ({e.placement})")
                      for e in hops[:5]],
            impact="Every redirect hop slows visitors and wastes crawl budget.",
            fix="Update links to the final URLs (nav/footer links need a template change).",
            verification="No internal links to redirecting URLs.", effort=Effort.S), patches

    # ------------------------------------------------------------ S7.06

    def _contextual_outlinks(self, graph: LinkGraph, keys: set[str]):
        silent = [k for k in keys if k in graph.nodes and not graph.outbound(k, "body")]
        if not silent:
            return self.finding("S7.06", St.PASS, "Key pages link to related pages from their body text")
        return self.finding(
            "S7.06", St.WARN, f"{len(silent)} key page(s) link to other sampled pages only from nav/footer",
            pages=[graph.nodes[k].url for k in silent], confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="html_excerpt", url=graph.nodes[k].url, excerpt="no body links to sampled pages")
                      for k in silent[:5]],
            impact="Body links pass context about related pages; menus alone don't.",
            fix="Link related pages from the body text where they're mentioned.",
            verification="Key pages have contextual links.", effort=Effort.S)

    # ------------------------------------------------------------ S7.07

    def _opportunities(self, ctx, graph: LinkGraph, pages, keys, entry, home, coverage):
        titles = [p.model.get("title") or "" for p in pages]
        words_in = {}
        for t in titles:
            for w in set(_WORD.findall(t.lower())):
                words_in[w] = words_in.get(w, 0) + 1
        brand = {w for w, n in words_in.items() if n >= max(3, len(pages) / 2)}  # e.g. "sterling", "holidays"
        template = template_blocks([p.model for p in pages])
        targets = [graph.nodes[k] for k in keys if k in graph.nodes and graph.nodes[k] is not home]
        if entry is not None and entry not in targets:
            targets.insert(0, entry)
        candidates = []
        for target in targets:
            h1 = next((h["text"] for h in target.model.get("headings", []) if h["level"] == 1), "")
            target_phrases = phrases(f"{h1} | {target.model.get('title') or ''}", brand)
            if not target_phrases:
                continue
            # Only an existing *body* link counts: every page has the nav link, which gives no context.
            linked_from = {e.source for e in graph.inbound(norm(target.url), "body")}
            for source in pages:
                if source is target or norm(source.url) in linked_from:
                    continue
                for passage in source.model.get("passages", []):
                    if "{{" in passage["text"] or text_hash(passage["text"]) in template:
                        continue
                    lowered = passage["text"].lower()
                    hit = next((p for p in target_phrases if re.search(rf"\b{re.escape(p)}\b", lowered)), None)
                    if hit:
                        candidates.append({"source": source, "passage": passage, "target": target, "phrase": hit})
                        break
        candidates = candidates[:MAX_CANDIDATES]
        if not candidates:
            return self.finding("S7.07", St.PASS, "No missed link opportunities found in the sample"), []
        if ctx.llm is None:
            coverage.skipped.append("Link suggestions need the LLM to check relevance (off in this run).")
            return self.finding("S7.07", St.UNVERIFIABLE, f"{len(candidates)} possible link opportunities not "
                                                          "reviewed (LLM off)"), []
        data = "\n".join(f"CANDIDATE L{i + 1}\nPASSAGE ({c['source'].url}): {c['passage']['text'][:600]}\n"
                         f"TARGET: {c['target'].url} | {c['target'].model.get('title') or ''}"
                         for i, c in enumerate(candidates))
        try:
            picks = ctx.llm.complete_json(load_prompt("s7.links", 1), LinkPicks, candidates=data).data
        except LLMError as exc:
            coverage.skipped.append(f"Link suggestion review failed: {exc}")
            return self.finding("S7.07", St.UNVERIFIABLE, "Link opportunities not reviewed (LLM error)"), []
        by_id = {p.id: p for p in picks.links}
        patches = []
        for i, c in enumerate(candidates):
            pick = by_id.get(f"L{i + 1}")
            if not pick or not pick.useful or not pick.anchor:
                continue
            anchor = pick.anchor.strip()
            words = len(anchor.split())
            if not quote_in_text(anchor, c["passage"]["text"]) or is_generic(anchor) or not 2 <= words <= 6:
                continue  # the anchor must be real words from the passage
            patches.append(Patch(
                key=f"S7.07:{text_hash(c['source'].url + c['target'].url)}", agent_id=self.id,
                page_url=c["source"].url, type=PatchType.LINK_INSERT, locator=Locator(**c["passage"]["locator"]),
                before=None, after=f'<a href="{c["target"].url}">{anchor}</a>', confidence=Confidence.LIKELY,
                rationale=f"The passage mentions \"{anchor}\"; linking it to {c['target'].url} helps readers and "
                          "tells search engines what that page is about.",
                client_visible_note="Adds a link to a related page where it's mentioned."))
        if not patches:
            return self.finding("S7.07", St.PASS, "Candidate links reviewed; none would help readers",
                                confidence=Confidence.LIKELY), []
        return self.finding(
            "S7.07", St.WARN, f"{len(patches)} missed internal link opportunit{'y' if len(patches) == 1 else 'ies'}",
            pages=sorted({p.page_url for p in patches}), confidence=Confidence.LIKELY,
            patch_keys=[p.key for p in patches],
            evidence=[EvidenceRef(type="html_excerpt", url=p.page_url, excerpt=f"{p.after}") for p in patches[:5]],
            impact="Relevant pages mention each other without linking, so readers and crawlers miss the connection.",
            fix="Add the suggested contextual links.", verification="Links present.", effort=Effort.S), patches
