"""S3 Search Metadata: do titles and descriptions represent each page accurately and win the click?

Deterministic checks on every page; one batched LLM call (fast tier) for relevance,
accuracy and drafts on the entry page, key pages and pages that failed a
deterministic check (at most MAX_LLM_PAGES). Drafts must pass length limits and the
fact guard (every number must appear in that page's data) before becoming patches.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from engine.agents.base import Agent
from engine.agents.common import PageView, entry_page, fact_sheet, key_page_urls, load_pages, tally
from engine.context import AgentContext, WorkUnit
from engine.lib.grounding import normalize, quote_in_text
from engine.lib.jsonld import page_nodes, types_of
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
    Finding,
    Locator,
    Patch,
    PatchType,
    Pillar,
    Severity as Sev,
)

TITLE_MIN, TITLE_MAX, DESC_MIN, DESC_MAX = 30, 60, 70, 155
MAX_LLM_PAGES = 8
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


class PageReview(BaseModel):
    url: str
    title_verdict: str
    title_reason: str = ""
    description_verdict: str
    description_reason: str = ""
    unsupported_claims: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    descriptions: list[str] = Field(default_factory=list)


class MetadataReview(BaseModel):
    pages: list[PageReview]


def grounded_numbers(text: str, source: str) -> bool:
    return all(n in source for n in _NUMBER.findall(text))


OG_TAGS = ("og:title", "og:description", "og:image")
_NOT_A_PREVIEW = re.compile(r"logo|icon|sprite|favicon|placeholder|pixel|/tr\?|\.svg(\?|$)|\.gif(\?|$)|^data:",
                            re.I)


_IMAGE_FILE = re.compile(r"\.(jpe?g|png|webp|avif)(\.|$)", re.I)  # also CDN variants: hero.jpg.imgw.1280.jpeg


def og_image(page: PageView, template_images: set[str] = frozenset()) -> str | None:
    """The page's own main image: its first content image (not in the header, menu or footer, not
    repeated across the site, not a logo, icon or tracking pixel). JSON-LD `image` is only a fallback,
    and never the organisation's: structured data can describe the wrong entity; the page can't."""
    def usable(src) -> bool:
        return isinstance(src, str) and src.startswith("http") and src not in template_images             and bool(_IMAGE_FILE.search(urlsplit(src).path)) and not _NOT_A_PREVIEW.search(src)

    shown = next((i["src"] for i in page.model.get("images", [])
                  if not i.get("in_boilerplate") and usable(i.get("src"))), None)
    if shown:
        return shown
    for node in page_nodes(page.model):
        if types_of(node) & {"Organization", "Corporation", "WebSite"}:
            continue
        image = node.get("image")
        image = image[0] if isinstance(image, list) and image else image
        image = image.get("url") if isinstance(image, dict) else image
        if usable(image):
            return image
    return None


def template_images(pages: list[PageView]) -> set[str]:
    """Image URLs on at least a quarter of the sampled pages: site template, not any one page's image."""
    counts: dict[str, int] = {}
    for page in pages:
        for src in {i.get("src") for i in page.model.get("images", []) if i.get("src")}:
            counts[src] = counts.get(src, 0) + 1
    return {src for src, n in counts.items() if n >= max(3, len(pages) / 4)}


def proposed_head(patches: list[Patch]) -> dict[str, dict[str, str]]:
    """S3's proposed title and description per page, so Open Graph copies the improved text."""
    out: dict[str, dict[str, str]] = {}
    for patch in patches:
        if patch.key.startswith("S3:title:"):
            out.setdefault(patch.page_url, {})["title"] = patch.after
        elif patch.key.startswith("S3:description:"):
            content = re.search(r'content="([^"]*)"', patch.after)
            if content:
                out.setdefault(patch.page_url, {})["description"] = html.unescape(content.group(1))
    return out


class SearchMetadata(Agent):
    id = "S3"
    name = "Search Metadata"
    pillar = Pillar.SEO
    requires = frozenset({EvidenceType.PAGES_PARSED, EvidenceType.FACTS})
    signature_columns = ["Page", "Current title (length)", "Proposed title", "Current description (length)",
                         "Proposed description"]
    checks = [
        CheckSpec(id="S3.01", title="Title present and unique", default_severity=Sev.HIGH, method="D"),
        CheckSpec(id="S3.02", title="Title length", default_severity=Sev.LOW, method="D"),
        CheckSpec(id="S3.03", title="Title relevance", default_severity=Sev.MEDIUM, method="L"),
        CheckSpec(id="S3.04", title="Title vs H1 alignment", default_severity=Sev.LOW, method="D"),
        CheckSpec(id="S3.05", title="Meta description present and unique", default_severity=Sev.LOW, method="D"),
        CheckSpec(id="S3.06", title="Meta description accuracy", default_severity=Sev.MEDIUM, method="L"),
        CheckSpec(id="S3.07", title="Open Graph and Twitter tags", default_severity=Sev.LOW, method="D"),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        pages = [p for p in load_pages(ctx) if p.is_html]
        keys = key_page_urls(pages, ctx.client.primary_url)
        entry = entry_page(pages, ctx.client.primary_url)
        findings: list[Finding] = []
        det_flags: dict[str, list[str]] = {}

        findings += self._presence_uniqueness(pages, det_flags)
        findings += self._lengths(pages, det_flags)
        findings += self._h1_alignment(pages)
        findings += self._descriptions(pages, det_flags)

        chosen = self._choose_for_llm(pages, entry, keys, det_flags)
        reviews, llm_note = self._review(ctx, chosen)
        llm_findings, patches, rows = self._from_reviews(ctx, chosen, reviews, keys)
        findings += llm_findings
        # Open Graph copies the page's own title and description, so it comes after the proposed rewrites.
        social_findings, social_patches = self._social(pages, keys, proposed_head(patches))
        findings += social_findings
        patches += social_patches
        coverage = Coverage(examined={"pages": len(pages), "llm_reviewed_pages": len(reviews)})
        if llm_note:
            coverage.skipped.append(llm_note)
        if len(pages) > len(chosen):
            coverage.limits.append(f"Relevance and accuracy were judged on {len(chosen)} priority pages "
                                   f"(entry, key and flagged pages), not all {len(pages)}.")
        return AgentResult(findings=findings, patches=patches, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    # ------------------------------------------------------- deterministic

    def _presence_uniqueness(self, pages, flags):
        missing = [p for p in pages if not p.model.get("title")]
        by_title: dict[str, list[PageView]] = {}
        for p in pages:
            if p.model.get("title"):
                by_title.setdefault(normalize(p.model["title"]), []).append(p)
        dupes = [g for g in by_title.values() if len(g) > 1]
        for p in missing + [p for g in dupes for p in g]:
            flags.setdefault(p.url, []).append("title missing or duplicated")
        if not missing and not dupes:
            return [self.finding("S3.01", St.PASS, "Every page has a unique title")]
        pages_hit = [p.url for p in missing] + [p.url for g in dupes for p in g]
        return [self.finding(
            "S3.01", St.FAIL, tally((len(missing), "page(s) without a title"), (len(dupes), "duplicated title(s)")),
            pages=pages_hit,
            evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt="<title> missing") for p in missing[:3]]
            + [EvidenceRef(type="html_excerpt", excerpt=f"\"{g[0].model['title']}\" on {len(g)} pages: "
                           + ", ".join(p.url for p in g[:3])) for g in dupes[:3]],
            impact="Search engines can't tell these pages apart, so they compete and show vague results.",
            fix="Give every page a unique title that leads with its topic.",
            verification="Re-crawl: every page has a unique <title>.", effort=Effort.S)]

    def _lengths(self, pages, flags):
        bad = [p for p in pages if p.model.get("title") and not TITLE_MIN <= len(p.model["title"]) <= TITLE_MAX]
        for p in bad:
            flags.setdefault(p.url, []).append("title length")
        if not bad:
            return [self.finding("S3.02", St.PASS, "Titles are 30–60 characters")]
        return [self.finding(
            "S3.02", St.WARN, f"{len(bad)} title(s) outside 30–60 characters", pages=[p.url for p in bad],
            evidence=[EvidenceRef(type="html_excerpt", url=p.url,
                                  excerpt=f"{len(p.model['title'])} chars: {p.model['title'][:90]}") for p in bad[:5]],
            impact="Long titles get cut off in results; very short ones waste the most visible line.",
            fix="Keep titles between 30 and 60 characters.", verification="Titles are 30–60 characters.",
            effort=Effort.S)]

    def _h1_alignment(self, pages):
        misaligned = []
        for p in pages:
            h1 = next((h["text"] for h in p.model.get("headings", []) if h["level"] == 1), "")
            title = p.model.get("title") or ""
            h1_words = set(re.findall(r"[a-z]{3,}", normalize(h1)))
            if h1_words and title and len(h1_words & set(re.findall(r"[a-z]{3,}", normalize(title)))) / len(h1_words) < 0.3:
                misaligned.append((p, title, h1))
        if not misaligned:
            return [self.finding("S3.04", St.PASS, "Titles and H1s describe the same topic")]
        return [self.finding(
            "S3.04", St.WARN, f"{len(misaligned)} page(s) where the title and H1 describe different things",
            pages=[p.url for p, _, _ in misaligned], confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt=f"title \"{t[:70]}\" vs H1 \"{h[:70]}\"")
                      for p, t, h in misaligned[:5]],
            impact="Google may rewrite titles that don't match the page's main heading.",
            fix="Align the title with the page's H1 topic.", verification="Title and H1 share the main topic.",
            effort=Effort.S)]

    def _descriptions(self, pages, flags):
        missing = [p for p in pages if not p.model.get("meta", {}).get("description")]
        by_desc: dict[str, list[PageView]] = {}
        for p in pages:
            d = p.model.get("meta", {}).get("description")
            if d:
                by_desc.setdefault(normalize(d), []).append(p)
        dupes = [g for g in by_desc.values() if len(g) > 1]
        bad_len = [p for p in pages if p.model.get("meta", {}).get("description")
                   and not DESC_MIN <= len(p.model["meta"]["description"]) <= DESC_MAX]
        for p in missing + bad_len + [p for g in dupes for p in g]:
            flags.setdefault(p.url, []).append("description missing/duplicate/length")
        if not (missing or dupes or bad_len):
            return [self.finding("S3.05", St.PASS, "Every page has a unique, well-sized meta description")]
        status = St.FAIL if missing or dupes else St.WARN
        return [self.finding(
            "S3.05", status, "Meta descriptions: " + tally((len(missing), "missing"), (len(dupes), "duplicated"),
                                                           (len(bad_len), "outside 70–155 characters")),
            pages=sorted({p.url for p in missing + bad_len + [p for g in dupes for p in g]}),
            evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt="no meta description") for p in missing[:3]]
            + [EvidenceRef(type="html_excerpt", excerpt=f"same description on {len(g)} pages") for g in dupes[:2]]
            + [EvidenceRef(type="html_excerpt", url=p.url,
                           excerpt=f"{len(p.model['meta']['description'])} chars") for p in bad_len[:3]],
            impact="Without a good description, search engines pick a snippet themselves, often a poor one.",
            fix="Write a unique 70–155 character description for each page.",
            verification="Every page has a unique, well-sized description.", effort=Effort.S)]

    def _social(self, pages, keys, proposed: dict[str, dict[str, str]]):
        """Missing Open Graph tags, with patches that copy what the page already says (its title, its
        description, its declared image), or S3's proposed rewrite of them. Nothing is invented."""
        incomplete = [p for p in pages if p.url in keys and not all(
            p.model.get("meta", {}).get(k) for k in OG_TAGS)]
        if not incomplete:
            return [self.finding("S3.07", St.PASS, "Key pages have Open Graph title, description and image")], []
        patches, shared = [], template_images(pages)
        for page in incomplete:
            meta, mine = page.model.get("meta", {}), proposed.get(page.url, {})
            values = {"og:title": (mine.get("title") or page.model.get("title"), "title"),
                      "og:description": (mine.get("description") or meta.get("description"), "meta description"),
                      "og:image": (og_image(page, shared), "main image")}
            for tag, (value, source) in values.items():
                if meta.get(tag) or not value:
                    continue
                patches.append(Patch(
                    key=f"S3:{tag}:{page.record.id}", agent_id=self.id, page_url=page.url, type=PatchType.HEAD_UPSERT,
                    locator=Locator(css=f'head > meta[property="{tag}"]'), before=None,
                    after=f'<meta property="{tag}" content="{html.escape(value, quote=True)}">',
                    confidence=Confidence.CONFIRMED, rationale=f"Uses the page's own {source} for {tag}.",
                    client_visible_note="Links shared on WhatsApp, LinkedIn or Facebook show a proper preview."))
        return [self.finding(
            "S3.07", St.WARN, f"{len(incomplete)} key page(s) miss Open Graph tags", pages=[p.url for p in incomplete],
            patch_keys=[pt.key for pt in patches],
            evidence=[EvidenceRef(type="html_excerpt", url=p.url,
                                  excerpt="missing " + ", ".join(k for k in ("og:title", "og:description", "og:image")
                                                                 if not p.model.get("meta", {}).get(k)))
                      for p in incomplete[:5]],
            impact="Shared links show a poor preview on WhatsApp, LinkedIn and Facebook.",
            fix="Add og:title, og:description and og:image (1200×630) to key pages.",
            verification="Link previews show title, description and image.", effort=Effort.S)], patches

    # ----------------------------------------------------------------- LLM

    @staticmethod
    def _choose_for_llm(pages, entry, keys, flags) -> list[PageView]:
        ordered = ([entry] if entry else []) + [p for p in pages if p.url in keys] + \
                  [p for p in pages if p.url in flags]
        unique = {}
        for page in ordered:
            if page is not None:
                unique.setdefault(page.url, page)
        return list(unique.values())[:MAX_LLM_PAGES]

    @staticmethod
    def _page_block(page: PageView, facts: list[dict], entry_url: str = "") -> str:
        h1 = next((h["text"] for h in page.model.get("headings", []) if h["level"] == 1), "")
        headings = "; ".join(dict.fromkeys(h["text"] for h in page.model.get("headings", [])
                                           if h["level"] in (2, 3) and h["text"]))[:400]
        page_type = "homepage" if page.is_home else "entry" if page.url.rstrip("/") == entry_url.rstrip("/") else "other"
        opening = " ".join(p["text"] for p in page.model.get("passages", [])[:4] if "{{" not in p["text"])
        page_facts = "; ".join(f"{f['key']}={f['value']}" for f in facts
                               if f["status"] == "site-stated" and f["source_url"].rstrip("/") == page.url.rstrip("/"))
        return (f"PAGE: {page.url}\nTYPE: {page_type}\nTITLE: {page.model.get('title') or ''}\n"
                f"DESCRIPTION: {page.model.get('meta', {}).get('description', '')}\nH1: {h1}\n"
                f"HEADINGS: {headings or 'none'}\n"
                f"OPENING: {' '.join(opening.split()[:90])}\nFACTS: {page_facts[:600] or 'none'}")

    def _review(self, ctx: AgentContext, chosen: list[PageView]) -> tuple[dict[str, PageReview], str | None]:
        if ctx.llm is None or not chosen:
            return {}, "Title relevance and description accuracy need the LLM (off in this run)."
        facts = fact_sheet(ctx)
        data = "\n\n".join(self._page_block(p, facts, ctx.client.primary_url) for p in chosen)
        try:
            answer = ctx.llm.complete_json(load_prompt("s3.metadata", 2), MetadataReview, pages=data).data
        except LLMError as exc:
            return {}, f"LLM review failed: {exc}"
        by_url = {p.url.rstrip("/"): p for p in chosen}
        return {r.url.rstrip("/"): r for r in answer.pages if r.url.rstrip("/") in by_url}, None

    def _from_reviews(self, ctx, chosen, reviews: dict[str, PageReview], keys):
        findings, patches, rows = [], [], []
        weak_titles, bad_descriptions, good_titles = [], [], []
        facts = fact_sheet(ctx)
        for page in chosen:
            review = reviews.get(page.url.rstrip("/"))
            title = page.model.get("title") or ""
            desc = page.model.get("meta", {}).get("description", "")
            if review is None:
                rows.append([page.url, f"{title} ({len(title)})", "—", f"{desc[:60]} ({len(desc)})", "—"])
                continue
            source = normalize(self._page_block(page, facts, ctx.client.primary_url))
            titles = [t for t in review.titles if TITLE_MIN <= len(t) <= TITLE_MAX and grounded_numbers(t, source)]
            descs = [d for d in review.descriptions if DESC_MIN <= len(d) <= DESC_MAX and grounded_numbers(d, source)]
            claims = [c for c in review.unsupported_claims if quote_in_text(c, desc)]
            keys_for_page = []
            if review.title_verdict in ("weak", "poor") and titles:
                key = f"S3:title:{page.record.id}"
                patches.append(Patch(key=key, agent_id=self.id, page_url=page.url, type=PatchType.TEXT_REPLACE,
                                     locator=Locator(**page.model["title_locator"]) if page.model.get("title_locator")
                                     else Locator(css="head > title"),
                                     before=title, after=titles[0], confidence=Confidence.LIKELY,
                                     rationale=f"{review.title_reason} Alternative: \"{titles[1]}\"" if len(titles) > 1
                                     else review.title_reason,
                                     client_visible_note="A clearer title helps searchers see what this page offers."))
                keys_for_page.append(key)
                weak_titles.append((page, review, key))
            elif review.title_verdict == "good":
                good_titles.append(page)
            if review.description_verdict in ("weak", "poor", "missing") and descs:
                key = f"S3:description:{page.record.id}"
                patches.append(Patch(key=key, agent_id=self.id, page_url=page.url, type=PatchType.HEAD_UPSERT,
                                     locator=Locator(css='head > meta[name="description"]'),
                                     before=desc or None, after=f'<meta name="description" content="{descs[0]}">',
                                     confidence=Confidence.LIKELY, rationale=review.description_reason,
                                     client_visible_note="A specific description improves the snippet shown in search."))
                bad_descriptions.append((page, review, claims, key))
            rows.append([page.url, f"{title} ({len(title)})", titles[0] if titles else "—",
                         f"{desc[:60]} ({len(desc)})", descs[0] if descs else "—"])

        if reviews:
            if weak_titles:
                findings.append(self.finding(
                    "S3.03", St.WARN if all(r.title_verdict == "weak" for _, r, _ in weak_titles) else St.FAIL,
                    f"{len(weak_titles)} title(s) don't clearly describe their page", confidence=Confidence.LIKELY,
                    pages=[p.url for p, _, _ in weak_titles], key_page=any(p.url in keys for p, _, _ in weak_titles),
                    patch_keys=[k for _, _, k in weak_titles],
                    evidence=[EvidenceRef(type="html_excerpt", url=p.url,
                                          excerpt=f"\"{p.model.get('title')}\": {r.title_reason}")
                              for p, r, _ in weak_titles[:5]],
                    impact="Vague titles rank and get clicked less than titles naming the page's topic and place.",
                    fix="Use the proposed titles, or write ones that lead with the page's topic.",
                    verification="Titles name the property/service and place.", effort=Effort.S))
            else:
                findings.append(self.finding("S3.03", St.PASS, "Reviewed titles describe their pages",
                                             confidence=Confidence.LIKELY,
                                             evidence=[EvidenceRef(type="html_excerpt", excerpt=f"{len(good_titles)} "
                                                                   "titles judged good")]))
            if bad_descriptions:
                with_claims = [x for x in bad_descriptions if x[2]]
                findings.append(self.finding(
                    "S3.06", St.FAIL if with_claims else St.WARN,
                    f"{len(bad_descriptions)} meta description(s) are vague, missing or overclaim",
                    confidence=Confidence.LIKELY, pages=[p.url for p, *_ in bad_descriptions],
                    patch_keys=[k for *_, k in bad_descriptions],
                    evidence=[EvidenceRef(type="html_excerpt", url=p.url,
                                          excerpt=(f"unsupported: {', '.join(c)}. " if c else "") + r.description_reason)
                              for p, r, c, _ in bad_descriptions[:5]],
                    impact="Descriptions that are vague or claim things the page doesn't back up lose clicks and trust.",
                    fix="Use the proposed descriptions: specific, accurate, 70–155 characters.",
                    verification="Descriptions match the page and state one concrete detail.", effort=Effort.S))
            else:
                findings.append(self.finding("S3.06", St.PASS, "Reviewed descriptions are accurate and specific",
                                             confidence=Confidence.LIKELY))
        else:
            findings += [self.finding("S3.03", St.UNVERIFIABLE, "Title relevance not judged (LLM unavailable)"),
                         self.finding("S3.06", St.UNVERIFIABLE, "Description accuracy not judged (LLM unavailable)")]
        return findings, patches, rows
