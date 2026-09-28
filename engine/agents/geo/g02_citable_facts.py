"""G2 Citable Facts & Evidence: do key pages contain specific, first-hand, sourced facts that AI
assistants can quote, and are the brand's figures the same everywhere?

Deterministic: picks the key pages to judge, finds quotable passages (G2.05, a research heuristic,
low weight) and brand figures that differ across pages (G2.06 candidates, e.g. "70 destinations"
on one page and "60+ destinations" on another). LLM (one batched call, fast tier): judges
G2.01–G2.04 per page with quotes (verified against the page text) and classifies each figure
pair; contradictions get a second opinion from the other model family.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from engine.agents.base import Agent
from engine.agents.common import (PageView, archetype, brand_tokens, business_name, entry_page, fact_sheet,
                                  key_page_urls, load_pages, tally)
from engine.context import AgentContext, WorkUnit
from engine.lib.content import own_text, sampled_text, template_blocks
from engine.lib.grounding import quote_in_text
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
    Pillar,
    Severity as Sev,
)

MAX_PAGES = 5
PAGE_WORDS = 450
MIN_SECTION_WORDS = 30
MIN_OWN_WORDS = 120
MAX_FIGURE_PAIRS = 5
# "70 unique destinations", "over 3,800 keys", "60+ resorts": a number, at most one describing word, a scale noun.
FIGURE = re.compile(
    r"(?:\b(?:over|more than|nearly|about|around|almost|up to)\s+)?(\d[\d,]*(?:\.\d+)?)\s*(\+|plus)?\s+"
    r"(?:(?!(?:from|to|in|at|of|by|for|and|or|with|away|km|kms|mins?|minutes?|hours?|hrs|stars?)\b)[a-z-]+\s+)?"
    r"(resorts?|hotels?|destinations?|properties|keys|branches|cities|states|countries|customers|members|"
    r"families|employees|locations|outlets|stores|warehouses|lenders|partners)\b", re.I)
DANGLING = re.compile(r"^(it|this|these|those|they|he|she|such|also|however|there)\b", re.I)


class PageVerdict(BaseModel):
    id: str
    facts: list[str] = Field(default_factory=list)
    generic: list[str] = Field(default_factory=list)
    first_hand: str | None = None
    first_hand_quote: str | None = None
    claims: list[dict] = Field(default_factory=list)
    entity: str | None = None
    entity_quote: str | None = None


class FigureVerdict(BaseModel):
    id: str
    verdict: str


class FactsAnswer(BaseModel):
    pages: list[PageVerdict] = Field(default_factory=list)
    figures: list[FigureVerdict] = Field(default_factory=list)


class PairCheck(BaseModel):
    id: str
    contradicts: bool


class PairChecks(BaseModel):
    pairs: list[PairCheck] = Field(default_factory=list)


@dataclass
class Judgement:
    """One key page, with only the quotes that were found verbatim in its text."""
    page: PageView
    text: str
    facts: list[str] = field(default_factory=list)
    generic: list[str] = field(default_factory=list)
    first_hand: str | None = None  # strong | some | none | None (not judged)
    first_hand_quote: str | None = None
    claims: list[tuple[str, bool]] = field(default_factory=list)
    entity: str | None = None  # explicit | implied | absent | None
    entity_quote: str | None = None
    dropped: int = 0  # quotes the model gave that aren't on the page
    facts_offered: int = 0
    judged: bool = False


@dataclass
class FigurePair:
    id: str
    noun: str
    a: tuple[str, str]  # (url, sentence) with the lowest value
    b: tuple[str, str]  # (url, sentence) with the highest value, on another page
    values: list[tuple[str, str]] = field(default_factory=list)  # every (value, url) seen
    verdict: str | None = None

    def summary(self) -> str:
        return f"{self.noun}: " + ", ".join(f"{value} ({url})" for value, url in self.values)


def page_text(page: PageView, template: set[str]) -> str:
    return sampled_text(page.model, template, PAGE_WORDS, MIN_SECTION_WORDS)


def quotable_passages(page: PageView, template: set[str]) -> list[str]:
    """Self-contained, fact-bearing paragraphs of 50–200 words (a research heuristic for AI citation)."""
    out: list[str] = []
    for passage in page.model.get("passages", []):
        text = passage["text"]
        words = text.split()
        if "{{" in text or text_hash(text) in template or not 50 <= len(words) <= 200 or DANGLING.match(text):
            continue
        capitalised = sum(1 for w in words[1:] if w[:1].isupper())
        if (re.search(r"\d", text) or capitalised >= 2) and text not in out:
            out.append(text)
    return out


def _window(text: str, start: int, end: int, reach: int = 90) -> str:
    """The words around a match, within its sentence, never cutting a word."""
    left = max(text.rfind(". ", 0, start) + 2, text.rfind("\n", 0, start) + 1, 0)
    if start - left > reach:
        left = text.find(" ", start - reach) + 1
    stops = [i + 1 for i in (text.find(". ", end), text.find("\n", end)) if i != -1]
    right = min(stops + [len(text)])
    if right - end > reach:
        right = text.rfind(" ", end, end + reach)
    return " ".join(text[left:right].split())


def figure_pairs(pages: list[PageView], facts: list[dict]) -> list[FigurePair]:
    """Brand-scale figures (resorts, destinations, branches...) with different values on different
    pages, plus differing founding years in the Fact Sheet. Candidates only: the LLM decides."""
    seen: dict[str, dict[str, tuple[str, str]]] = {}  # noun → value → (url, sentence)
    for page in pages:
        # Passages skip short lines, and taglines ("One card, 15 hotels") are where brand figures live.
        text = page.visible_text() + " \n" + (page.model.get("main_text_sample") or "")
        for m in FIGURE.finditer(text):
            noun = m.group(3).lower()
            noun = noun[:-3] + "y" if noun.endswith("ies") else noun.rstrip("s")
            value = m.group(1).replace(",", "") + ("+" if m.group(2) else "")
            seen.setdefault(noun, {}).setdefault(value, (page.url, _window(text, m.start(), m.end())))
    pairs = []
    for noun, values in seen.items():
        ranked = sorted(values.items(), key=lambda v: float(v[0].rstrip("+")))
        low = ranked[0][1]
        high = next((where for _, where in reversed(ranked) if where[0] != low[0]), None)
        if high is not None:  # differing values on at least two pages
            pairs.append(FigurePair(f"F{len(pairs) + 1}", noun, low, high,
                                    [(value, url) for value, (url, _) in ranked]))
    years = {}
    for fact in facts:
        if fact["key"] == "founded_year" and fact["status"] == "site-stated":
            year = re.search(r"\b(1[89]\d\d|20\d\d)\b", fact["value"])
            if year:
                years.setdefault(year.group(1), (fact["source_url"], fact["quote"]))
    if len(years) >= 2 and len({url for url, _ in years.values()}) >= 2:
        (_, low), (_, high) = sorted(years.items())[0], sorted(years.items())[-1]
        pairs.append(FigurePair(f"F{len(pairs) + 1}", "founding year", low, high,
                                [(year, url) for year, (url, _) in sorted(years.items())]))
    return pairs[:MAX_FIGURE_PAIRS]


class CitableFacts(Agent):
    id = "G2"
    name = "Citable Facts & Evidence"
    pillar = Pillar.GEO
    requires = frozenset({EvidenceType.PAGES_PARSED, EvidenceType.FACTS})
    signature_columns = ["Page", "Distinctive facts", "Generic claims", "First-hand", "Entity defined",
                         "Quotable passages"]
    checks = [
        CheckSpec(id="G2.01", title="Distinctive facts on key pages", default_severity=Sev.MEDIUM, method="L"),
        CheckSpec(id="G2.02", title="First-hand, non-commodity content", default_severity=Sev.MEDIUM, method="L"),
        CheckSpec(id="G2.03", title="Source attribution", default_severity=Sev.LOW, method="L"),
        CheckSpec(id="G2.04", title="Entity clarity", default_severity=Sev.MEDIUM, method="L"),
        CheckSpec(id="G2.05", title="Quotable passages (research heuristic)", default_severity=Sev.LOW, method="D"),
        CheckSpec(id="G2.06", title="Brand fact consistency", default_severity=Sev.HIGH, method="D+L"),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        pages = [p for p in load_pages(ctx) if p.is_html]
        template = template_blocks([p.model for p in pages])
        entry = entry_page(pages, ctx.client.primary_url)
        home = next((p for p in pages if p.is_home), None)
        chosen = self._pick(pages, entry, home, key_page_urls(pages, ctx.client.primary_url), template)
        judgements = [Judgement(p, page_text(p, template)) for p in chosen]
        pairs = figure_pairs(pages, fact_sheet(ctx))
        coverage = Coverage(examined={"key_pages_judged": len(chosen), "pages_scanned_for_figures": len(pages),
                                      "figure_pairs": len(pairs)})
        coverage.limits.append(f"Judged {len(chosen)} key page(s): the entry page, the homepage and the key pages "
                               f"with the most text of their own (~{PAGE_WORDS} words each, sampled across the page).")
        facts = fact_sheet(ctx)
        names = brand_tokens(ctx, *(f["value"] for f in facts if f["key"] in ("brand", "business_name",
                                                                               "property_name")
                                    and f["status"] == "site-stated"))
        self._judge(ctx, judgements, pairs, names, coverage)
        confirmed = self._second_opinion(ctx, pairs, coverage)
        quotable = {j.page.url: quotable_passages(j.page, template) for j in judgements}
        focus = {p.url for p in (entry, home) if p is not None}

        findings = [self._facts(judgements, entry), self._first_hand(judgements, entry),
                    self._sources(judgements, focus), self._entity(judgements, entry, home),
                    self._quotable(judgements, quotable), self._consistency(ctx, pairs, confirmed, len(pages))]
        rows = [[j.page.url, len(j.facts), len(j.generic), j.first_hand or "—", j.entity or "—",
                 len(quotable[j.page.url])] for j in judgements]
        return AgentResult(findings=findings, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    # ------------------------------------------------------------ selection and LLM

    @staticmethod
    def _pick(pages, entry, home, keys, template) -> list[PageView]:
        own = {p.url: len(own_text(p.model, template).split()) for p in pages}
        others = sorted((p for p in pages if p.url in keys and own[p.url] >= MIN_OWN_WORDS),
                        key=lambda p: -own[p.url])
        chosen: dict[str, PageView] = {}
        for page in [entry, home, *others]:
            if page is not None and page.url not in chosen:
                chosen[page.url] = page
        return list(chosen.values())[:MAX_PAGES]

    def _judge(self, ctx, judgements: list[Judgement], pairs: list[FigurePair], names: set[str],
               coverage: Coverage) -> None:
        asked = [j for j in judgements if j.text]
        if not asked and not pairs:
            return
        if ctx.llm is None:
            coverage.skipped.append("Fact, first-hand, source and entity judgements need the LLM (off in this run).")
            return
        page_lines = "\n".join(f"PAGE K{i} ({j.page.url}): {j.text}" for i, j in enumerate(asked, start=1))
        figure_lines = "\n".join(f'FIGURES {p.id}: A ({p.a[0]}): "{p.a[1]}" | B ({p.b[0]}): "{p.b[1]}"'
                                 for p in pairs)
        try:
            answer = ctx.llm.complete_json(load_prompt("g2.facts", 2), FactsAnswer,
                                           business=f"{business_name(ctx)} ({archetype(ctx) or 'archetype unknown'})",
                                           pages=page_lines, figures=figure_lines).data
        except LLMError as exc:
            coverage.skipped.append(f"Fact review failed: {exc}")
            return
        by_id = {v.id: v for v in answer.pages}
        for i, j in enumerate(asked, start=1):
            v = by_id.get(f"K{i}")
            if v is None:
                continue
            j.judged = True

            def keep(quotes: list[str], limit: int) -> list[str]:
                ok = [q.strip() for q in quotes[:limit] if isinstance(q, str) and quote_in_text(q, j.text)]
                j.dropped += len(quotes[:limit]) - len(ok)
                return ok

            j.facts_offered = len(v.facts[:5])
            j.facts, j.generic = keep(v.facts, 5), keep(v.generic, 3)
            for claim in v.claims[:3]:
                quote = str(claim.get("quote") or "")
                if quote_in_text(quote, j.text):
                    j.claims.append((quote.strip(), bool(claim.get("sourced"))))
                else:
                    j.dropped += 1
            # A positive verdict needs its evidence on the page; otherwise it's unknown, not a pass.
            first_hand_ok = v.first_hand == "none" or (v.first_hand_quote and quote_in_text(v.first_hand_quote, j.text))
            j.first_hand = v.first_hand if v.first_hand in ("strong", "some", "none") and first_hand_ok else None
            j.first_hand_quote = v.first_hand_quote if j.first_hand in ("strong", "some") else None
            entity_ok = v.entity != "explicit" or (
                v.entity_quote and quote_in_text(v.entity_quote, j.text)
                and len(v.entity_quote.split()) >= 5  # a tagline isn't a definition
                and (not names or any(w in v.entity_quote.lower() for w in names)))
            j.entity = v.entity if v.entity in ("explicit", "implied", "absent") and entity_ok else None
            j.entity_quote = v.entity_quote if j.entity == "explicit" else None
        dropped = sum(j.dropped for j in judgements)
        if dropped:
            coverage.limits.append(f"{dropped} quote(s) from the model weren't found on the page and were dropped.")
        verdicts = {v.id: v.verdict for v in answer.figures}
        for pair in pairs:
            verdict = verdicts.get(pair.id)
            pair.verdict = verdict if verdict in ("same", "drift", "contradiction", "different_subjects") else None

    def _second_opinion(self, ctx, pairs: list[FigurePair], coverage: Coverage) -> set[str]:
        """Contradictions are shown to the client as errors on their site: a second model family must agree."""
        flagged = [p for p in pairs if p.verdict == "contradiction"]
        if not flagged:
            return set()
        text = "\n".join(f'PAIR {p.id}: A "{p.a[1]}" | B "{p.b[1]}"' for p in flagged)
        try:
            checks = ctx.llm.complete_json(load_prompt("g2.verify", 1), PairChecks, prefer="groq", pairs=text).data
        except LLMError as exc:
            coverage.limits.append(f"Second opinion unavailable ({exc}); contradictions reported as drift.")
            for p in flagged:
                p.verdict = "drift"
            return set()
        confirmed = {c.id for c in checks.pairs if c.contradicts}
        overturned = [p for p in flagged if p.id not in confirmed]
        for p in overturned:
            p.verdict = "overturned"
        if overturned:
            coverage.limits.append(f"{len(overturned)} contradiction(s) overturned by a second model and not reported.")
        return confirmed

    # ------------------------------------------------------------ checks

    def _facts(self, judgements: list[Judgement], entry):
        judged = [j for j in judgements if j.judged]
        if not judged:
            return self.finding("G2.01", St.UNVERIFIABLE, "Key pages not reviewed")
        # A page whose fact quotes were all dropped is unknown, not fact-free.
        judged = [j for j in judged if j.facts or not j.facts_offered]
        if not judged:
            return self.finding("G2.01", St.UNVERIFIABLE, "Fact quotes from the model didn't match the pages")
        none = [j for j in judged if not j.facts]
        few = [j for j in judged if 1 <= len(j.facts) < 3]
        if not none and not few:
            return self.finding("G2.01", St.PASS, "Key pages state specific, checkable facts",
                                confidence=Confidence.LIKELY,
                                evidence=[EvidenceRef(type="html_excerpt", url=j.page.url, excerpt=j.facts[0])
                                          for j in judged[:4]])
        weak = none + few
        return self.finding(
            "G2.01", St.FAIL if none else St.WARN,
            tally((len(none), "key page(s) with no specific facts"),
                  (len(few), "key page(s) with only one or two specific facts")),
            pages=[j.page.url for j in weak], confidence=Confidence.LIKELY,
            key_page=any(j.page is entry for j in (none or few)),
            evidence=[EvidenceRef(type="html_excerpt", url=j.page.url,
                                  excerpt=(f'generic: "{j.generic[0]}"' if j.generic else "no specific facts")
                                  + (f'; facts: "{j.facts[0]}"' if j.facts else "")) for j in weak[:5]],
            impact="AI assistants quote specific facts (counts, distances, prices, named amenities); pages of "
                   "general claims give them nothing to cite.",
            fix="Add the concrete facts customers ask about (numbers, names, places, times, prices) in plain text.",
            verification="Re-run G2: at least three specific facts per key page.", effort=Effort.M)

    def _first_hand(self, judgements: list[Judgement], entry):
        judged = [j for j in judgements if j.first_hand]
        if not judged:
            return self.finding("G2.02", St.UNVERIFIABLE, "First-hand content not reviewed")
        none = [j for j in judged if j.first_hand == "none"]
        some = [j for j in judged if j.first_hand == "some"]
        if not none and not some:
            return self.finding("G2.02", St.PASS, "Key pages include first-hand, local detail",
                                confidence=Confidence.LIKELY,
                                evidence=[EvidenceRef(type="html_excerpt", url=j.page.url, excerpt=j.first_hand_quote)
                                          for j in judged[:4]])
        weak = none + some
        return self.finding(
            "G2.02", St.FAIL if none else St.WARN,
            tally((len(none), "key page(s) read as commodity content"),
                  (len(some), "key page(s) have little first-hand detail")),
            pages=[j.page.url for j in weak], confidence=Confidence.LIKELY,
            key_page=any(j.page is entry for j in (none or some)),
            evidence=[EvidenceRef(type="html_excerpt", url=j.page.url,
                                  excerpt=f'best example: "{j.first_hand_quote}"' if j.first_hand_quote
                                  else "text could describe any competitor") for j in weak[:5]],
            impact="Search engines and AI assistants favour original, first-hand content over text any competitor "
                   "could publish.",
            fix="Add what only you can say: local tips, real guest examples, your own numbers, named staff or "
                "partners.", verification="Re-run G2: first-hand detail on each key page.", effort=Effort.M)

    def _sources(self, judgements: list[Judgement], focus: set[str]):
        judged = [j for j in judgements if j.judged]
        if not judged:
            return self.finding("G2.03", St.UNVERIFIABLE, "Claims not reviewed")
        claims = [(j, q, s) for j in judged for q, s in j.claims]
        unsourced = [(j, q) for j, q, s in claims if not s]
        if not unsourced:
            return self.finding(
                "G2.03", St.PASS, "Statistics and claims name their sources" if claims
                else "No statistics or superlatives that need a source", confidence=Confidence.LIKELY,
                evidence=[EvidenceRef(type="html_excerpt", url=j.page.url, excerpt=f'sourced: "{q}"')
                          for j, q, _ in claims[:3]] or [EvidenceRef(type="html_excerpt",
                                                                     excerpt=f"{len(judged)} key pages checked")])
        key_claims = [(j, q) for j, q in unsourced if j.page.url in focus]
        return self.finding(
            "G2.03", St.FAIL if key_claims else St.WARN,
            f"{len(unsourced)} claim(s) without a source" + (" on the entry page or homepage" if key_claims else ""),
            pages=sorted({j.page.url for j, _ in unsourced}), confidence=Confidence.LIKELY,
            evidence=[EvidenceRef(type="html_excerpt", url=j.page.url, excerpt=f'unsourced: "{q}"')
                      for j, q in unsourced[:5]],
            impact="Unsourced superlatives and statistics are less credible to people and less likely to be "
                   "repeated by AI assistants.",
            fix="Name the source next to each figure or award (platform, report, awarding body, year), or remove it.",
            verification="Re-run G2: claims name their sources.", effort=Effort.S)

    def _entity(self, judgements: list[Judgement], entry, home):
        judged = [j for j in judgements if j.entity]
        if not judged:
            return self.finding("G2.04", St.UNVERIFIABLE, "Entity definition not reviewed")
        explicit = [j for j in judged if j.entity == "explicit"]
        main = next((j for j in judged if j.page is entry), None) or next((j for j in judged if j.page is home), None)
        if not explicit:
            return self.finding(
                "G2.04", St.FAIL, "No key page clearly says who the business is and what it offers",
                pages=[j.page.url for j in judged], confidence=Confidence.LIKELY, key_page=True,
                evidence=[EvidenceRef(type="html_excerpt", url=j.page.url, excerpt=f"entity: {j.entity}")
                          for j in judged[:5]],
                impact="AI assistants need a plain statement of what the business is to describe or recommend it.",
                fix="Open key pages with one sentence naming the business, what it is and where it operates.",
                verification="Re-run G2: entity defined on key pages.", effort=Effort.S)
        if main is not None and main.entity != "explicit":
            return self.finding(
                "G2.04", St.WARN, "The entry page only implies what the business is" if main.page is entry
                else "The homepage only implies what the business is", pages=[main.page.url],
                confidence=Confidence.LIKELY, key_page=True,
                evidence=[EvidenceRef(type="html_excerpt", url=main.page.url, excerpt=f"entity: {main.entity}"),
                          EvidenceRef(type="html_excerpt", url=explicit[0].page.url,
                                      excerpt=f'defined here instead: "{explicit[0].entity_quote}"')],
                impact="AI assistants read pages one at a time; a page that doesn't say what the business is gets "
                       "described vaguely or not at all.",
                fix="Add a first sentence naming the business, what it is and where.",
                verification="Re-run G2.", effort=Effort.S)
        return self.finding("G2.04", St.PASS, "Key pages name the business and say what it offers",
                            confidence=Confidence.LIKELY,
                            evidence=[EvidenceRef(type="html_excerpt", url=j.page.url, excerpt=j.entity_quote)
                                      for j in explicit[:3]])

    def _quotable(self, judgements: list[Judgement], quotable: dict[str, list[str]]):
        if not judgements:
            return self.finding("G2.05", St.NOT_APPLICABLE, "No key pages in the sample")
        without = [j.page.url for j in judgements if not quotable[j.page.url]]
        evidence = [EvidenceRef(type="html_excerpt", url=url, excerpt=f"{len(q)} quotable passage(s): "
                                                                      f"\"{q[0][:160]}…\"" if q
                                else "no self-contained, fact-bearing paragraph of 50–200 words")
                    for url, q in list(quotable.items())[:5]]
        if not without:
            return self.finding("G2.05", St.PASS, "Each key page has self-contained, fact-bearing passages",
                                confidence=Confidence.LIKELY, evidence=evidence)
        return self.finding(
            "G2.05", St.FAIL if len(without) == len(judgements) else St.WARN,
            f"{len(without)} of {len(judgements)} key page(s) have no quotable passage", pages=without,
            confidence=Confidence.LIKELY, evidence=evidence, tags=["research-heuristic"],
            impact="Research on AI answers suggests self-contained paragraphs with a concrete fact are quoted more "
                   "often (a heuristic, weighted low).",
            fix="Write at least one 50–200 word paragraph per key page that stands on its own and states facts.",
            verification="Re-run G2.", effort=Effort.S)

    def _consistency(self, ctx, pairs: list[FigurePair], confirmed: set[str], scanned: int):
        if not pairs:
            return self.finding("G2.06", St.PASS, f"No differing brand figures across {scanned} sampled pages",
                                confidence=Confidence.LIKELY,
                                evidence=[EvidenceRef(type="html_excerpt", excerpt="resorts, destinations, branches, "
                                                                                   "customers and founding year "
                                                                                   "compared across pages")])
        if all(p.verdict is None for p in pairs):
            return self.finding("G2.06", St.UNVERIFIABLE, f"{len(pairs)} differing figure(s) not reviewed")
        contradictions = [p for p in pairs if p.id in confirmed]
        drift = [p for p in pairs if p.verdict == "drift"]
        if not contradictions and not drift:
            return self.finding("G2.06", St.PASS, "Differing figures describe different things; no conflicts",
                                confidence=Confidence.LIKELY,
                                evidence=[EvidenceRef(type="html_excerpt", url=p.a[0],
                                                      excerpt=f"{p.summary()} ({p.verdict})"[:400])
                                          for p in pairs[:3]])
        bad = contradictions + drift
        return self.finding(
            "G2.06", St.FAIL if contradictions else St.WARN,
            f"{tally((len(contradictions), 'contradictory'), (len(drift), 'outdated-looking'))} brand figure(s) "
            "across pages",
            pages=sorted({url for p in bad for url in (p.a[0], p.b[0])}), confidence=Confidence.LIKELY,
            severity=None if contradictions else Sev.MEDIUM,
            evidence=[EvidenceRef(type="html_excerpt", url=p.a[0], excerpt=p.summary()[:400]) for p in bad[:2]]
            + [EvidenceRef(type="html_excerpt", url=url, excerpt=f'"{sentence}"')
               for p in bad[:2] for url, sentence in (p.a, p.b)],
            missing_facts=[f"the current {p.noun} figure" for p in bad],
            impact="AI assistants repeat whichever figure they read; conflicting numbers make the brand look "
                   "unreliable and spread outdated facts.",
            fix="Pick the current figure, update every page that states it, and keep it in one place (the Fact "
                "Sheet) going forward.", verification="Re-run G2: one value per brand figure.", effort=Effort.S)
