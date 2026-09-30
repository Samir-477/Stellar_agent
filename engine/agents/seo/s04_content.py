"""S4 On-Page Content Quality: are key pages clearly structured, readable and current, and does the
entry page match the intent of the searches it should rank for?

Deterministic: H1 count (S4.01), heading hierarchy of the main content (S4.02), thin or boilerplate
pages (S4.06), outdated or undated offers (S4.07), readability (S4.08), repeated phrases (S4.09).
LLM (one batched call, fast tier): the page type of the entry page vs the types of page that rank
for its target query (S4.04), subtopics the top results share and whether the page covers them
(S4.05, quotes verified), whether the opening answers the searcher (S4.03), and whether each key
page's H1 describes it (S4.01).

Competitor pages aren't fetched yet (C8): SERP comparisons use result titles and snippets, and thin
content is judged against fixed thresholds rather than the ranking median. Findings say so.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from engine.agents.base import Agent
from engine.agents.common import (PageView, archetype, brand_tokens, business_name, entry_page, fact_sheet,
                                  key_page_urls, load_pages, norm, tally)
from engine.context import AgentContext, WorkUnit
from engine.lib.content import own_text, sampled_text, template_blocks, template_headings
from engine.lib.grounding import normalize, quote_in_text
from engine.lib.locators import text_hash
from engine.lib.retrieval import tokens
from engine.lib.textstats import outdated_mentions, repeated_phrases, sentences, undated_offer, words
from engine.llm import LLMError, load_prompt
from engine.rules.packs import pack
from engine.schemas import (
    AgentResult,
    CheckSpec,
    CheckStatus as St,
    Confidence,
    Coverage,
    Effort,
    EvidenceRef,
    EvidenceType,
    Pillar,
    Severity as Sev,
)

PAGE_TYPES = {"listing", "single_business", "product", "service", "article", "homepage", "social_video", "other"}
TOOL_PATH = re.compile(r"/(book|booking|bookings|login|sign-?in|register|cart|checkout|search|feedback|contact|"
                       r"contact-us|account|my-?account|enquiry|apply)(/|-|$)", re.I)
BOILERPLATE_XPATH = re.compile(r"/(header|nav|footer|aside)(\[|/|$)")
INTRO_WORDS = 100
THIN_WORDS = 150
DENSE_PARAGRAPH = 120
WALL_PARAGRAPH = 250
LONG_SENTENCES = 25
TEMPLATED_SHARE = 0.6  # a phrase mostly repeated in identical card or list copy is not stuffing


class TypedResult(BaseModel):
    id: str
    type: str


class Subtopic(BaseModel):
    topic: str
    results: list[str] = Field(default_factory=list)
    covered: bool = False
    quote: str | None = None


class IntroVerdict(BaseModel):
    verdict: str | None = None
    quote: str | None = None


class H1Verdict(BaseModel):
    id: str
    descriptive: bool
    note: str | None = None


class ContentAnswer(BaseModel):
    page_type: str | None = None
    results: list[TypedResult] = Field(default_factory=list)
    subtopics: list[Subtopic] = Field(default_factory=list)
    intro: IntroVerdict = Field(default_factory=IntroVerdict)
    h1s: list[H1Verdict] = Field(default_factory=list)


@dataclass
class Target:
    query: str
    source: str  # mapped (the team mapped it to the entry page) | inferred (first non-brand query)
    results: list[dict]


@dataclass
class Judged:
    page_type: str | None = None
    result_types: dict[str, str] = field(default_factory=dict)
    subtopics: list[tuple[str, list[str], str]] = field(default_factory=list)  # (topic, result ids, status)
    intro: str | None = None
    intro_quote: str | None = None
    h1: dict[str, H1Verdict] = field(default_factory=dict)  # by page url
    dropped: int = 0


def h1_texts(page: PageView) -> list[str]:
    """Distinct non-empty H1 texts (identical copies for mobile and desktop count once)."""
    return list(dict.fromkeys(h["text"].strip() for h in page.model.get("headings", [])
                              if h["level"] == 1 and h["text"].strip()))


def main_headings(page: PageView, template_headings: set[str]) -> list[dict]:
    """Headings of the main content, in order: the parser's outline (no header, nav, footer) minus
    headings repeated across the site (widgets)."""
    return [b for b in page.model.get("outline", [])
            if b["type"] == "heading" and normalize(b["text"]) not in template_headings]


def empty_main_headings(page: PageView) -> int:
    return sum(1 for h in page.model.get("headings", [])
               if not h["text"].strip() and not BOILERPLATE_XPATH.search((h.get("locator") or {}).get("xpath", "")))


def own_passages(page: PageView, template: set[str]) -> list[str]:
    seen: dict[str, None] = {}
    for p in page.model.get("passages", []):
        if "{{" not in p["text"] and text_hash(p["text"]) not in template:
            seen.setdefault(p["text"], None)
    return list(seen)


def own_words_estimate(page: PageView, own: list[str], template: set[str]) -> tuple[int, int]:
    """(own words, main-content words). Own text is main content minus site-template passages, so
    text in <div>s counts; paragraphs alone undercount pages built from divs."""
    total = page.model.get("main_text_words") or 0
    template_words = sum(len(p["text"].split()) for p in page.model.get("passages", [])
                         if text_hash(p["text"]) in template)
    return max(sum(len(t.split()) for t in own), total - template_words), total


def brand_phrases(ctx: AgentContext) -> list[list[str]]:
    """The business's names as word lists (singular), e.g. ["sterling", "holiday", "resort", "limited"]."""
    names = [business_name(ctx), ctx.client.name] + [
        f["value"] for f in fact_sheet(ctx)
        if f["key"] in ("brand", "business_name", "legal_name", "property_name") and f["status"] == "site-stated"]
    return [[w.rstrip("s") for w in words(n)] for n in names if n]


def in_brand(phrase: str, brands: list[list[str]]) -> bool:
    """True if the phrase is part of a business name ("holiday resort" in "Sterling Holiday Resorts")."""
    ws = [w.rstrip("s") for w in phrase.split()]
    return any(b[i:i + len(ws)] == ws for b in brands for i in range(len(b) - len(ws) + 1))


def templated_share(phrase: str, texts: list[str]) -> float:
    """Share of the phrase's occurrences that sit in identical wording: the same two words before
    it (or nothing, when it opens a card) or the same two words after it. Card and list copy
    repeats like this ("…ICICI bank customers: Avail a flat…", "…Amex card customers: Avail a
    flat…"); keyword stuffing varies the words around the phrase."""
    target = phrase.split()
    before: Counter[tuple] = Counter()
    after: Counter[tuple] = Counter()
    for text in texts:
        ws = words(text)
        for i in range(len(ws) - len(target) + 1):
            if ws[i:i + len(target)] == target:
                before[tuple(ws[max(0, i - 2):i])] += 1
                after[tuple(ws[i + len(target):i + len(target) + 2])] += 1
    total = sum(before.values())
    if total < 3:
        return 0.0
    return max(before.most_common(1)[0][1], after.most_common(1)[0][1]) / total


def pick_target(ctx: AgentContext, entry_url: str) -> Target | None:
    """The query the entry page should win: the team's mapping when it isn't the brand name, else the
    highest-priority non-brand query with captured results (latest capture per query)."""
    sets = ctx.snapshot.evidence(EvidenceType.QUERY_SET)
    if not sets:
        return None
    payload = sets[-1].payload
    serps = {e.payload["query"]: e.payload for e in ctx.snapshot.evidence(EvidenceType.SERP)
             if e.payload.get("organic")}
    queries = sorted(payload.get("queries", []), key=lambda q: q.get("priority", 99))
    mapped = next((v for k, v in (payload.get("page_query_map") or {}).items() if norm(k) == norm(entry_url)), None)
    for query in queries:
        if query["q"] == mapped and query["intent"] != "brand" and mapped in serps:
            return Target(mapped, "mapped", serps[mapped]["organic"][:10])
    for query in queries:
        if query["intent"] != "brand" and query["q"] in serps:
            return Target(query["q"], "inferred", serps[query["q"]]["organic"][:10])
    return None


class OnPageContent(Agent):
    id = "S4"
    name = "On-Page Content Quality"
    pillar = Pillar.SEO
    requires = frozenset({EvidenceType.PAGES_PARSED, EvidenceType.QUERY_SET, EvidenceType.SERP})
    signature_columns = ["Page", "H1", "Own words", "Target query", "Top-result type", "Page type",
                         "Subtopics missing"]
    checks = [
        CheckSpec(id="S4.01", title="Single descriptive H1", default_severity=Sev.MEDIUM, method="D+L"),
        CheckSpec(id="S4.02", title="Heading hierarchy", default_severity=Sev.LOW, method="D"),
        CheckSpec(id="S4.03", title="Intro answers the page intent", default_severity=Sev.MEDIUM, method="L"),
        CheckSpec(id="S4.04", title="Intent match with the SERP", default_severity=Sev.HIGH, method="S+L"),
        CheckSpec(id="S4.05", title="Subtopic coverage", default_severity=Sev.MEDIUM, method="S+L"),
        CheckSpec(id="S4.06", title="Thin or boilerplate content", default_severity=Sev.MEDIUM, method="D"),
        CheckSpec(id="S4.07", title="Freshness", default_severity=Sev.MEDIUM, method="D"),
        CheckSpec(id="S4.08", title="Readability", default_severity=Sev.LOW, method="D"),
        CheckSpec(id="S4.09", title="Over-optimization", default_severity=Sev.LOW, method="D"),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        pages = [p for p in load_pages(ctx) if p.is_html]
        template = template_blocks([p.model for p in pages])
        template_heads = template_headings([p.model for p in pages])
        entry = entry_page(pages, ctx.client.primary_url)
        keys = key_page_urls(pages, ctx.client.primary_url)
        key_pages = [p for p in pages if p.url in keys]
        if entry is not None and entry not in key_pages:
            key_pages.insert(0, entry)
        own = {p.url: own_passages(p, template) for p in key_pages}
        target = pick_target(ctx, ctx.client.primary_url) if entry is not None else None
        coverage = Coverage(examined={"key_pages": len(key_pages), "serp_results": len(target.results) if target
                                      else 0})
        coverage.limits.append("Competitor pages aren't fetched yet: SERP comparisons use result titles and "
                               "snippets, and thin content uses fixed thresholds rather than the ranking median.")
        if target is not None and target.source == "inferred":
            coverage.limits.append(f"Target query for the entry page inferred from the query set: \"{target.query}\" "
                                   "(map pages to queries to confirm).")

        judged = self._judge(ctx, entry, key_pages, template, target, coverage)
        the_pack = pack(archetype(ctx))
        loans = bool(the_pack and the_pack.ymyl == "high")
        names = brand_tokens(ctx)
        findings = [
            self._h1(key_pages, judged, entry),
            self._hierarchy(key_pages, template_heads, own),
            self._intro(entry, judged, target),
            self._intent(entry, judged, target),
            self._subtopics(entry, judged, target),
            self._thin(key_pages, own, template, entry),
            self._freshness(key_pages, own, loans),
            self._readability(key_pages, own),
            self._stuffing(key_pages, own, names, brand_phrases(ctx)),
        ]
        types = Counter(judged.result_types.values())
        entry_cells = [target.query if target else "—", types.most_common(1)[0][0] if types else "—",
                       judged.page_type or "—",
                       ", ".join(t for t, _, status in judged.subtopics if status == "missed") or "—"]
        rows = [[page.url, " / ".join(h1_texts(page))[:80] or "(none)", sum(len(t.split()) for t in own[page.url]),
                 *(entry_cells if page is entry else ["—"] * 4)] for page in key_pages]
        return AgentResult(findings=findings, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    # ------------------------------------------------------------ LLM

    def _judge(self, ctx, entry, key_pages, template, target: Target | None, coverage: Coverage) -> Judged:
        judged = Judged()
        with_h1 = [p for p in key_pages if len(h1_texts(p)) == 1]
        if entry is None and not with_h1:
            return judged
        if ctx.llm is None:
            coverage.skipped.append("Intent, subtopic, intro and H1 judgements need the LLM (off in this run).")
            return judged
        intro = " ".join(own_text(entry.model, template).split()[:INTRO_WORDS]) if entry else ""
        body = sampled_text(entry.model, template, 350) if entry else ""
        h1 = (h1_texts(entry) or [""])[0] if entry else ""
        page = (f"PAGE ({entry.url}): TITLE: {entry.model.get('title') or ''} | H1: {h1}\nINTRO: {intro}\n"
                f"PAGE TEXT: {body}") if entry else "PAGE: none"
        results = "\n".join(f"R{i} ({r.get('domain')}): {r.get('title') or ''} | {r.get('snippet') or ''}"
                            for i, r in enumerate(target.results, start=1)) if target else "none"
        h1s = "\n".join(f"K{i} ({p.url}): TITLE: {p.model.get('title') or ''} | H1: {h1_texts(p)[0]}"
                        for i, p in enumerate(with_h1, start=1))
        query = target.query if target else "none (judge the intro against the page's title and H1)"
        try:
            answer = ctx.llm.complete_json(load_prompt("s4.content", 2), ContentAnswer,
                                           business=f"{business_name(ctx)} ({archetype(ctx) or 'archetype unknown'})",
                                           query=query, page=page, results=results, h1s=h1s).data
        except LLMError as exc:
            coverage.skipped.append(f"Content review failed: {exc}")
            return judged
        valid_ids = {f"R{i}" for i in range(1, len(target.results) + 1)} if target else set()
        judged.page_type = answer.page_type if answer.page_type in PAGE_TYPES else None
        judged.result_types = {r.id: r.type for r in answer.results if r.id in valid_ids and r.type in PAGE_TYPES}
        top5 = {f"R{i}" for i in range(1, 6)}
        seen_text = f"{intro} {body}"
        full_text = own_text(entry.model, template) if entry else ""
        for sub in answer.subtopics[:6]:
            ids = [r for r in dict.fromkeys(sub.results) if r in top5 & valid_ids]
            if len(ids) < 2:
                continue  # must be shared by at least two of the top five results
            if sub.covered and sub.quote and quote_in_text(sub.quote, seen_text):
                status = "covered"
            elif sub.covered:
                status, judged.dropped = "unclear", judged.dropped + 1  # claimed covered, quote not on the page
            elif self._mentioned(sub.topic, full_text):
                status = "unclear"  # the sampled text missed it, but the page mentions its words
            else:
                status = "missed"
            judged.subtopics.append((sub.topic, ids, status))
        if answer.intro.verdict in ("answers", "partial", "filler") and answer.intro.quote \
                and quote_in_text(answer.intro.quote, intro):
            judged.intro, judged.intro_quote = answer.intro.verdict, answer.intro.quote.strip()
        elif answer.intro.verdict:
            judged.dropped += 1
        by_id = {v.id: v for v in answer.h1s}
        judged.h1 = {p.url: by_id[f"K{i}"] for i, p in enumerate(with_h1, start=1) if f"K{i}" in by_id}
        if judged.dropped:
            coverage.limits.append(f"{judged.dropped} verdict(s) dropped because their quote isn't on the page.")
        return judged

    @staticmethod
    def _mentioned(topic: str, text: str) -> bool:
        """The page uses every content word of the topic, or of one of its alternatives ("X or Y")."""
        found = set(tokens(text)) | {w.rstrip("s") for w in tokens(text)}
        for alternative in re.split(r"\bor\b|\band\b|,|/", topic):
            content = [w for w in tokens(alternative) if len(w) > 3]
            if content and all(w in found or w.rstrip("s") in found for w in content):
                return True
        return False

    # ------------------------------------------------------------ S4.01 / S4.02

    def _h1(self, key_pages, judged: Judged, entry):
        missing = [p for p in key_pages if not h1_texts(p)]
        competing = [p for p in key_pages if len(h1_texts(p)) > 1]
        generic = [p for p in key_pages if p.url in judged.h1 and not judged.h1[p.url].descriptive]
        if missing or competing:
            bad = missing + competing
            return self.finding(
                "S4.01", St.FAIL, tally((len(missing), "key page(s) without an H1"),
                                        (len(competing), "key page(s) with competing H1s")),
                pages=[p.url for p in bad], key_page=any(p is entry for p in bad),
                evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt="no H1") for p in missing[:3]]
                + [EvidenceRef(type="html_excerpt", url=p.url, excerpt="H1s: " + " | ".join(h1_texts(p))[:300])
                   for p in competing[:3]]
                + [EvidenceRef(type="html_excerpt", url=p.url, excerpt=f"generic H1: \"{h1_texts(p)[0]}\"")
                   for p in generic[:2]],
                impact="The H1 is the page's main heading for readers and search engines; missing or competing "
                       "H1s blur what the page is about.",
                fix="Give each page exactly one H1 that names its subject (what it is and, where it matters, where).",
                verification="One descriptive H1 per page.", effort=Effort.S)
        if generic:
            return self.finding(
                "S4.01", St.WARN, f"{len(generic)} key page(s) have an H1 that doesn't say what the page is about",
                pages=[p.url for p in generic], confidence=Confidence.LIKELY, key_page=any(p is entry for p in generic),
                evidence=[EvidenceRef(type="html_excerpt", url=p.url,
                                      excerpt=f"H1: \"{h1_texts(p)[0]}\"" + (f" ({judged.h1[p.url].note})"
                                                                             if judged.h1[p.url].note else ""))
                          for p in generic[:5]],
                impact="Slogan or promotional H1s don't tell search engines or AI assistants what the page covers.",
                fix="Rewrite the H1 to name the page's subject; keep the slogan as a subheading.",
                verification="H1s describe their pages.", effort=Effort.S)
        return self.finding("S4.01", St.PASS, "Key pages have one H1", confidence=Confidence.LIKELY
                            if judged.h1 else Confidence.CONFIRMED,
                            evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt=f"H1: \"{h1_texts(p)[0]}\"")
                                      for p in key_pages[:3]])

    def _hierarchy(self, key_pages, template_headings, own):
        skipped, styling, flat = [], [], []
        for page in key_pages:
            heads = main_headings(page, template_headings)
            jumps = [(a, b) for a, b in zip(heads, heads[1:]) if b["level"] > a["level"] + 1]
            if jumps:
                skipped.append((page, jumps[0]))
            empty = empty_main_headings(page)
            long = [h for h in heads if len(h["text"].split()) > 25]
            if empty >= 3 or long:
                styling.append((page, empty, long))
            if sum(len(t.split()) for t in own[page.url]) >= 600 and len(heads) < 2:
                flat.append(page)
        if flat:
            return self.finding(
                "S4.02", St.FAIL, f"{len(flat)} long key page(s) with no headings in the main content",
                pages=[p.url for p in flat],
                evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt="600+ words, fewer than 2 headings")
                          for p in flat[:5]],
                impact="Long unstructured text is hard to scan and hard for search engines to split into topics.",
                fix="Break the content into sections with descriptive H2/H3 headings.",
                verification="Headings structure every long page.", effort=Effort.S)
        if skipped or styling:
            evidence = [EvidenceRef(type="html_excerpt", url=p.url,
                                    excerpt=f"H{a['level']} \"{a['text'][:60]}\" is followed by H{b['level']} "
                                            f"\"{b['text'][:60]}\"") for p, (a, b) in skipped[:3]]
            evidence += [EvidenceRef(type="html_excerpt", url=p.url,
                                     excerpt=f"{empty} empty heading tag(s) in the content" if empty
                                     else f"heading used as body text: \"{long[0]['text'][:120]}\"")
                         for p, empty, long in styling[:3]]
            return self.finding(
                "S4.02", St.WARN, tally((len(skipped), "key page(s) skip heading levels"),
                                        (len(styling), "key page(s) use heading tags for styling")),
                pages=sorted({p.url for p, _ in skipped} | {p.url for p, _, _ in styling}),
                evidence=evidence,
                impact="Headings are the page outline for screen readers and search engines; skipped levels and "
                       "empty headings make the outline misleading.",
                fix="Use H2 for sections and H3 inside them without skipping levels; style text with CSS, not "
                    "heading tags.", verification="Main-content outline has no gaps or empty headings.",
                effort=Effort.S)
        return self.finding("S4.02", St.PASS, "Main-content headings form a logical outline",
                            evidence=[EvidenceRef(type="html_excerpt", excerpt=f"{len(key_pages)} key pages checked")])

    # ------------------------------------------------------------ S4.03–S4.05

    def _intro(self, entry, judged: Judged, target):
        if entry is None or judged.intro is None:
            return self.finding("S4.03", St.UNVERIFIABLE, "Entry page opening not reviewed")
        evidence = [EvidenceRef(type="html_excerpt", url=entry.url, excerpt=f"\"{judged.intro_quote}\"")]
        if judged.intro == "answers":
            return self.finding("S4.03", St.PASS, "The entry page opens with what the searcher came for",
                                pages=[entry.url], confidence=Confidence.LIKELY, evidence=evidence)
        return self.finding(
            "S4.03", St.FAIL if judged.intro == "filler" else St.WARN,
            "The entry page opens with filler" if judged.intro == "filler"
            else "The entry page's opening only partly answers the searcher",
            pages=[entry.url], confidence=Confidence.LIKELY, key_page=True, evidence=evidence,
            impact="Searchers and AI assistants read the first lines to decide if a page answers them.",
            fix=f"Open with the direct answer for \"{target.query}\": what it is, where, the key facts."
            if target else "Open with what the page offers: what it is, where, the key facts.",
            verification="Re-run S4: opening answers the intent.", effort=Effort.S)

    def _intent(self, entry, judged: Judged, target: Target | None):
        if entry is None or target is None or not judged.result_types or not judged.page_type:
            return self.finding("S4.04", St.UNVERIFIABLE, "Search intent not compared (no target query results "
                                                          "or no review)")
        types = Counter(judged.result_types.values())
        share = types[judged.page_type] / sum(types.values())
        dominant, count = types.most_common(1)[0]
        summary = ", ".join(f"{n} {t}" for t, n in types.most_common())
        evidence = [EvidenceRef(type="serp", excerpt=f"top results for \"{target.query}\": {summary}"),
                    EvidenceRef(type="html_excerpt", url=entry.url, excerpt=f"entry page type: {judged.page_type}")]
        evidence += [EvidenceRef(type="serp", url=r.get("link"), excerpt=f"#{i} {r.get('domain')}: {r.get('title')}")
                     for i, r in enumerate(target.results[:3], start=1)]
        if share >= 0.5:
            return self.finding("S4.04", St.PASS, f"The entry page is the kind of page that ranks for "
                                                  f"\"{target.query}\"", pages=[entry.url],
                                confidence=Confidence.LIKELY, evidence=evidence)
        mismatch = share < 0.2
        inferred = target.source == "inferred"
        title = (f"Top results for \"{target.query}\" are mostly {dominant} pages; the entry page is a "
                 f"{judged.page_type} page" if mismatch else
                 f"Mixed results for \"{target.query}\": {dominant} pages lead, {judged.page_type} pages are a "
                 "minority")
        return self.finding(
            "S4.04", St.FAIL if mismatch and not inferred else St.WARN,
            title + (" (target query inferred)" if inferred else ""), pages=[entry.url],
            confidence=Confidence.LIKELY, severity=Sev.MEDIUM if inferred else None, evidence=evidence,
            impact="Google ranks the type of page searchers want; a different page type rarely ranks, however good.",
            fix=f"Target queries where {judged.page_type} pages rank (more specific ones), and reach "
                f"\"{target.query}\" through the {dominant} sites that rank for it or a page of that type.",
            verification="Re-run S4 with the confirmed target query.", effort=Effort.M)

    def _subtopics(self, entry, judged: Judged, target):
        if entry is None or target is None or not judged.result_types:
            return self.finding("S4.05", St.UNVERIFIABLE, "Subtopics not compared (no target query results or no "
                                                          "review)")
        missed = [(t, ids) for t, ids, s in judged.subtopics if s == "missed"]
        covered = [t for t, _, s in judged.subtopics if s == "covered"]
        domains = {f"R{i}": r.get("domain") for i, r in enumerate(target.results, start=1)}
        if not missed:
            return self.finding("S4.05", St.PASS, "The entry page covers the subtopics the top results share",
                                pages=[entry.url], confidence=Confidence.LIKELY,
                                evidence=[EvidenceRef(type="serp",
                                                      excerpt=f"covered: {', '.join(covered) or 'none shared'}")])
        status = St.FAIL if len(missed) >= 3 and len(missed) > len(judged.subtopics) / 2 else St.WARN
        return self.finding(
            "S4.05", status, f"The entry page misses {len(missed)} subtopic(s) the top results share: "
                             + ", ".join(t for t, _ in missed), pages=[entry.url], confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="serp", excerpt=f"\"{t}\" in {', '.join(domains.get(i, i) for i in ids)}")
                      for t, ids in missed[:5]], missing_facts=[t for t, _ in missed],
            impact="Searchers expect these subtopics; pages that cover them satisfy the search better.",
            fix="Add a short section for each missing subtopic, using facts you can stand behind.",
            verification="Re-run S4: subtopics covered.", effort=Effort.M)

    # ------------------------------------------------------------ S4.06–S4.09

    def _thin(self, key_pages, own, template, entry):
        content = [p for p in key_pages if not TOOL_PATH.search(urlsplit(p.url).path)]
        rows = [(page, *own_words_estimate(page, own[page.url], template)) for page in content]
        boilerplate = [(p, o, t) for p, o, t in rows if o < 100 and t and o / t < 0.3]
        thin = [(p, o, t) for p, o, t in rows if o < THIN_WORDS and (p, o, t) not in boilerplate]
        if not boilerplate and not thin:
            return self.finding("S4.06", St.PASS, "Key content pages have substantial text of their own",
                                confidence=Confidence.LIKELY,
                                evidence=[EvidenceRef(type="metric", url=p.url, excerpt=f"{o} own words")
                                          for p, o, _ in rows[:3]])
        bad = boilerplate + thin
        return self.finding(
            "S4.06", St.FAIL if boilerplate else St.WARN,
            tally((len(boilerplate), "key page(s) are mostly site template"), (len(thin), "key page(s) are thin")),
            pages=[p.url for p, _, _ in bad], confidence=Confidence.LIKELY, key_page=any(p is entry for p, _, _ in bad),
            evidence=[EvidenceRef(type="metric", url=p.url, excerpt=f"~{o} words of its own out of {t} in the "
                                                                    "main content") for p, o, t in bad[:5]],
            impact="Pages with little of their own text rarely rank and give AI assistants nothing to quote.",
            fix="Add the page's own content: what it offers, key facts, and answers to common questions.",
            verification=f"Each key page has {THIN_WORDS}+ words of its own.", effort=Effort.M)

    def _freshness(self, key_pages, own, loans: bool):
        year = date.today().year
        outdated, undated = [], []
        for page in key_pages:
            for text in own[page.url]:
                outdated += [(page, s) for s in outdated_mentions(text, year)]
                if undated_offer(text):
                    undated.append((page, text))
        severity = Sev.HIGH if loans else None
        if outdated:
            return self.finding(
                "S4.07", St.FAIL, f"{len(outdated)} outdated offer, rate or seasonal mention(s) on key pages",
                pages=sorted({p.url for p, _ in outdated}), severity=severity,
                evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt=f"\"{s}\"") for p, s in outdated[:5]],
                impact="Expired offers and past-year rates make the whole page look unmaintained and can mislead "
                       "customers.", fix="Remove or update expired offers, rates and seasonal content.",
                verification="No past-year offers or rates.", effort=Effort.S)
        if undated:
            return self.finding(
                "S4.07", St.WARN, f"{len(undated)} offer(s) with prices but no dates", confidence=Confidence.LIKELY,
                pages=sorted({p.url for p, _ in undated}), severity=severity,
                evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt=f"\"{t[:200]}\"")
                          for p, t in undated[:5]],
                impact="Undated offers leave customers unsure if they still apply.",
                fix="Add validity dates to offers and 'rates as of' dates to prices.",
                verification="Offers show validity dates.", effort=Effort.S)
        return self.finding("S4.07", St.PASS, "No outdated or undated offers on key pages",
                            confidence=Confidence.LIKELY,
                            evidence=[EvidenceRef(type="html_excerpt", excerpt=f"{len(key_pages)} key pages checked "
                                                                               f"against {year}")])

    def _readability(self, key_pages, own):
        walls, dense = [], []
        for page in key_pages:
            texts = own[page.url]
            long = [t for t in texts if len(t.split()) > DENSE_PARAGRAPH]
            # Sentence length over prose only: card labels without full stops would read as one long sentence.
            prose = [s for t in texts if len(t.split()) >= 20 for s in sentences(t)]
            average = sum(len(s.split()) for s in prose) / len(prose) if len(prose) >= 3 else 0
            if any(len(t.split()) > WALL_PARAGRAPH for t in texts):
                walls.append((page, max(texts, key=lambda t: len(t.split()))))
            elif len(long) >= 2:
                dense.append((page, f"{len(long[0].split())}-word paragraph: \"{long[0][:120]}…\""))
            elif average > LONG_SENTENCES:
                sentence = max(prose, key=lambda s: len(s.split()))
                dense.append((page, f"sentences average {average:.0f} words, e.g. \"{sentence[:120]}…\""))
        if walls or dense:
            bad = walls + dense
            return self.finding(
                "S4.08", St.FAIL if walls else St.WARN,
                tally((len(walls), "key page(s) with walls of text"),
                      (len(dense), "key page(s) with dense paragraphs or long sentences")),
                pages=[p.url for p, _ in bad],
                evidence=[EvidenceRef(type="html_excerpt", url=p.url,
                                      excerpt=f"{len(t.split())}-word paragraph: \"{t[:120]}…\"")
                          for p, t in walls[:3]]
                + [EvidenceRef(type="html_excerpt", url=p.url, excerpt=note) for p, note in dense[:3]],
                impact="Dense text is skimmed or skipped, on phones especially; short paragraphs get read and quoted.",
                fix=f"Keep paragraphs under {DENSE_PARAGRAPH} words and sentences under {LONG_SENTENCES} words; use "
                    "lists for features.", verification="No dense paragraphs on key pages.", effort=Effort.S)
        return self.finding("S4.08", St.PASS, "Key pages use short paragraphs and sentences",
                            evidence=[EvidenceRef(type="metric", excerpt=f"{len(key_pages)} key pages checked")])

    def _stuffing(self, key_pages, own, names: set[str], brands: list[list[str]]):
        stuffed, repetitive = [], []
        for page in key_pages:
            text = " ".join(own[page.url])
            total = len(text.split())
            if total < 100:
                continue
            candidates = [(phrase, count) for phrase, count in repeated_phrases(text, exclude=names)[:20]
                          if not in_brand(phrase, brands) and templated_share(phrase, own[page.url]) < TEMPLATED_SHARE]
            for phrase, count in candidates[:3]:
                per = total / count
                if count >= 10 and per <= 25:
                    stuffed.append((page, phrase, count, total))
                    break
                if count >= 6 and per <= 50:
                    repetitive.append((page, phrase, count, total))
                    break
        if stuffed or repetitive:
            bad = stuffed + repetitive
            return self.finding(
                "S4.09", St.FAIL if stuffed else St.WARN,
                f"{len(bad)} key page(s) repeat a phrase unnaturally often", pages=[p.url for p, *_ in bad],
                confidence=Confidence.LIKELY,
                evidence=[EvidenceRef(type="metric", url=p.url, excerpt=f"\"{phrase}\" {count} times in {total} words")
                          for p, phrase, count, total in bad[:5]],
                impact="Repeating a keyword reads as spam to people and search engines.",
                fix="Say it once where it matters (title, H1, opening); vary the wording elsewhere.",
                verification="No phrase repeated more than once per 50 words.", effort=Effort.S)
        return self.finding("S4.09", St.PASS, "Natural wording: no phrase repeated unusually often",
                            confidence=Confidence.LIKELY,
                            evidence=[EvidenceRef(type="metric", excerpt=f"{len(key_pages)} key pages checked")])
