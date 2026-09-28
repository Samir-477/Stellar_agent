"""A4 Snippet & PAA Opportunities (observation, not scored): which search features appear for the
client's queries, who holds them, and where the client could win one.

Deterministic, from C6 SerpAPI captures (top priority queries only): the featured snippet's holder
and format (A4.01), People Also Ask questions and whether the client holds them or has a section
answering them (A4.02), and whether the client's best section for a snippet query has the format
Google shows (A4.03). Opportunities are reported only where the client ranks in the top 10.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from engine.agents.base import Agent
from engine.agents.common import load_pages
from engine.context import AgentContext, WorkUnit
from engine.lib.content import is_question, sections, template_blocks
from engine.lib.retrieval import BM25, tokens
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

QUESTION_MATCH = 0.6  # share of a PAA question's words found in one of the site's question headings


@dataclass
class Snippet:
    query: str
    holder: str | None  # domain
    link: str | None
    format: str  # paragraph | list | table
    text: str


@dataclass
class Capture:
    query: str
    client_position: int | None
    snippet: Snippet | None = None
    paa: list[dict] = field(default_factory=list)


def _domain(url: str | None) -> str | None:
    return (urlsplit(url).hostname or "").removeprefix("www.") if url else None


def snippet_of(query: str, box: dict | None) -> Snippet | None:
    """SerpAPI's answer box as a featured snippet: holder, format and text."""
    if not box or not (box.get("snippet") or box.get("list") or box.get("table") or box.get("answer")):
        return None
    fmt = "table" if box.get("table") else "list" if box.get("list") else "paragraph"
    text = box.get("snippet") or box.get("answer") or " / ".join(map(str, box.get("list") or []))
    return Snippet(query, _domain(box.get("link")), box.get("link"), fmt, str(text)[:300])


def captures(ctx: AgentContext) -> list[Capture]:
    """The latest SerpAPI capture per query (queries without features weren't sent to SerpAPI)."""
    latest: dict[str, tuple] = {}
    for ev in ctx.snapshot.evidence(EvidenceType.SERP):
        if ev.payload.get("features"):
            latest[ev.payload["query"]] = (ev.payload, ev.blob_key)
    out = []
    for query, (payload, blob_key) in latest.items():
        raw = (ctx.snapshot.blob_json(blob_key) or {}).get("serpapi", {}) if blob_key else {}
        out.append(Capture(query, payload.get("client_position"), snippet_of(query, raw.get("answer_box")),
                           payload["features"].get("paa") or []))
    return out


def section_format(section: dict) -> str:
    tags = [b.get("tag") for b in section["passages"]]
    if tags.count("td") >= 2:
        return "table"
    return "list" if tags.count("li") >= 2 else "paragraph"


class SnippetOpportunities(Agent):
    id = "A4"
    name = "Snippet & PAA Opportunities"
    pillar = Pillar.AEO
    counts_toward_readiness = False  # observations of a dated SERP sample (docs/spec/04)
    requires = frozenset({EvidenceType.PAGES_PARSED, EvidenceType.SERP})
    signature_columns = ["Query", "Feature", "Holder", "Format", "Client rank", "Eligible?"]
    checks = [
        CheckSpec(id="A4.01", title="Featured snippets", default_severity=Sev.MEDIUM, method="S+D",
                  counts_toward_readiness=False),
        CheckSpec(id="A4.02", title="People Also Ask", default_severity=Sev.LOW, method="S+D",
                  counts_toward_readiness=False),
        CheckSpec(id="A4.03", title="Format mismatch", default_severity=Sev.LOW, method="S+D",
                  counts_toward_readiness=False),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        caps = captures(ctx)
        client = _domain(ctx.client.primary_url)
        pages = [p for p in load_pages(ctx) if p.is_html]
        template = template_blocks([p.model for p in pages])
        units = [(p, sec) for p in pages for sec in sections(p.model, template=template) if sec["passages"]]
        coverage = Coverage(examined={"queries_with_features": len(caps), "sections": len(units)})
        coverage.limits.append("Search features come from the SerpAPI captures of the top-priority queries on one "
                               "day; they change often.")
        if not caps:
            coverage.skipped.append("No SerpAPI captures in this snapshot.")
            return AgentResult(findings=[self.finding(c.id, St.UNVERIFIABLE, "No search-feature captures")
                                         for c in self.checks], coverage=coverage)
        question_heads = [(p, s["heading"]) for p, s in units if is_question(s["heading"])]
        rows = []
        for cap in caps:
            rank = cap.client_position or "not in top 10"
            if cap.snippet:
                rows.append([cap.query, "featured snippet", cap.snippet.holder or "—", cap.snippet.format, rank,
                             "yes" if cap.client_position else "no"])
            for q in cap.paa:
                rows.append([cap.query, f"PAA: {q.get('question')}", _domain(q.get("link")) or "Google (AI answer)",
                             "—", rank, "yes" if cap.client_position else "no"])
        findings = [self._snippets(caps, client), self._paa(caps, client, question_heads),
                    self._formats(caps, client, units)]
        return AgentResult(findings=findings, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    # ------------------------------------------------------------ A4.01

    def _snippets(self, caps: list[Capture], client: str):
        shown = [c for c in caps if c.snippet]
        if not shown:
            noun = "query" if len(caps) == 1 else "queries"
            return self.finding("A4.01", St.NOT_APPLICABLE, f"No featured snippets on the {len(caps)} captured {noun}",
                                evidence=[EvidenceRef(type="serp", excerpt=", ".join(c.query for c in caps)[:300])])
        held = [c for c in shown if c.snippet.holder == client]
        eligible = [c for c in shown if c.snippet.holder != client and c.client_position]
        evidence = [EvidenceRef(type="serp", url=c.snippet.link,
                                excerpt=f"\"{c.query}\": held by {c.snippet.holder} ({c.snippet.format}); client "
                                        f"{'#' + str(c.client_position) if c.client_position else 'not in top 10'}")
                    for c in held + eligible + [c for c in shown if c not in held + eligible]][:5]
        if eligible:
            return self.finding(
                "A4.01", St.WARN, f"{len(eligible)} featured snippet(s) held by others where the client ranks top 10",
                confidence=Confidence.CONFIRMED, evidence=evidence,
                impact="The snippet sits above the first result; ranking pages can win it with a direct answer in "
                       "the format Google shows.",
                fix="Add a direct answer (40–60 words, or a list/table matching the snippet) near the top of the "
                    "ranking page.", verification="Recapture the SERP.", effort=Effort.S)
        if held:
            return self.finding("A4.01", St.PASS, f"The client holds {len(held)} featured snippet(s)",
                                evidence=evidence)
        return self.finding("A4.01", St.NOT_APPLICABLE, "Featured snippets exist but the client isn't in the top 10 "
                                                        "for those queries", evidence=evidence)

    # ------------------------------------------------------------ A4.02

    def _paa(self, caps: list[Capture], client: str, question_heads: list):
        asked = {}
        for cap in caps:
            for q in cap.paa:
                if q.get("question"):
                    asked.setdefault(q["question"], (cap, q))
        if not asked:
            return self.finding("A4.02", St.NOT_APPLICABLE, "No People Also Ask questions on the captured queries")
        held, answered, open_ = [], [], []
        for question, (cap, q) in asked.items():
            if _domain(q.get("link")) == client:
                held.append((question, None))
                continue
            words = {w for w in tokens(question) if len(w) > 2}
            match = next(((p, h) for p, h in question_heads
                          if words and len(words & set(tokens(h))) / len(words) >= QUESTION_MATCH), None)
            (answered if match else open_).append((question, match))
        holders = sorted({_domain(q.get("link")) or "Google (AI answer, no source page)" for _, q in asked.values()})
        evidence = ([EvidenceRef(type="serp", excerpt=f"held by the client: \"{q}\"") for q, _ in held[:2]]
                    + [EvidenceRef(type="serp", url=m[0].url, excerpt=f"\"{q}\" answered under \"{m[1]}\"")
                       for q, m in answered[:2]]
                    + [EvidenceRef(type="serp", excerpt=f"no section for: \"{q}\"") for q, _ in open_[:3]]
                    + [EvidenceRef(type="serp", excerpt="answered by: " + ", ".join(holders)[:250])])
        if not open_:
            return self.finding("A4.02", St.PASS, f"The site answers or holds all {len(asked)} People Also Ask "
                                                  "question(s)", evidence=evidence, confidence=Confidence.LIKELY)
        eligible = [(q, m) for q, m in open_ if asked[q][0].client_position]
        if not eligible:  # opportunities count only where the client already ranks (docs/spec/12)
            return self.finding(
                "A4.02", St.NOT_APPLICABLE, f"{len(open_)} People Also Ask question(s) without a matching section, "
                                            "all on queries where the client isn't in the top 10 (content ideas)",
                confidence=Confidence.LIKELY, evidence=evidence)
        return self.finding(
            "A4.02", St.WARN, f"{len(eligible)} People Also Ask question(s) on queries where the client ranks have no "
                              "matching section on the site", confidence=Confidence.LIKELY, evidence=evidence,
            impact="People Also Ask questions show what searchers want next; a section that answers one can be "
                   "shown there or quoted by AI answers.",
            fix="Answer these questions under question-style headings on the most relevant page.",
            verification="Recapture the SERP.", effort=Effort.S)

    # ------------------------------------------------------------ A4.03

    def _formats(self, caps: list[Capture], client: str, units: list):
        eligible = [c for c in caps if c.snippet and c.snippet.holder != client and c.client_position]
        if not eligible or not units:
            return self.finding("A4.03", St.NOT_APPLICABLE, "No featured snippet the client could win on the "
                                                            "captured queries")
        index = BM25([f"{s['heading']} {s['heading']} {' '.join(b['text'] for b in s['passages'])}"
                      for _, s in units])
        mismatched, matched = [], []
        for cap in eligible:
            best = index.top(cap.query, 1)
            if not best:
                continue
            page, sec = units[best[0][0]]
            fmt = section_format(sec)
            (matched if fmt == cap.snippet.format else mismatched).append((cap, page, sec, fmt))
        if not mismatched:
            return self.finding("A4.03", St.PASS, "The client's best sections match the snippet formats",
                                evidence=[EvidenceRef(type="serp", url=p.url,
                                                      excerpt=f"\"{c.query}\": {f} under \"{s['heading']}\"")
                                          for c, p, s, f in matched[:3]])
        return self.finding(
            "A4.03", St.WARN, f"{len(mismatched)} snippet quer{'y' if len(mismatched) == 1 else 'ies'} where the "
                              "client's best section has a different format",
            pages=sorted({p.url for _, p, _, _ in mismatched}), evidence=[
                EvidenceRef(type="serp", url=p.url, excerpt=f"\"{c.query}\": Google shows a {c.snippet.format}; the "
                                                             f"client's section \"{s['heading']}\" is a {f}")
                for c, p, s, f in mismatched[:5]],
            impact="Google picks snippets that already have the right shape.",
            fix="Rework the section into the snippet's format (numbered steps, a bullet list or a table).",
            verification="Recapture the SERP.", effort=Effort.S)
