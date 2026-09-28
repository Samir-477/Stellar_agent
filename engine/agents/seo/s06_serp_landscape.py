"""S6 SERP Landscape & Competitors (benchmark, not scored): where the client appears for its
searches, who else does (direct competitors, aggregators, publishers), which search features are
shown, and what the top competitor pages have that the client's page lacks.

Deterministic, from C6 (results and SerpAPI features), C8 (domain types and competitors' ranking
pages, parsed) and the client's parsed pages. S6.04 structural gaps are `warn` findings so they
reach the work queue, but no S6 check counts toward readiness (docs/spec/04).
"""

from __future__ import annotations

import re
from collections import Counter
from statistics import median

from engine.agents.base import Agent
from engine.agents.common import entry_page, load_pages
from engine.context import AgentContext, WorkUnit
from engine.lib.content import is_question, sections, template_blocks
from engine.lib.jsonld import page_nodes, page_types, types_of
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

GAP_SHARE = 2  # present on at least this many of the top competitor pages
TOP_COMPETITOR_PAGES = 3
# Schema types that are parts of other entities, not what a page is about.
STRUCTURAL_TYPES = {"WebPage", "WebSite", "BreadcrumbList", "ImageObject", "ListItem", "ItemList", "PostalAddress",
                    "GeoCoordinates", "PropertyValue", "ContactPoint", "Place", "Rating", "AggregateRating", "Brand",
                    "Thing", "SearchAction", "EntryPoint", "SiteNavigationElement", "CreativeWork", "WPHeader",
                    "WPFooter", "OpeningHoursSpecification", "LocationFeatureSpecification", "QuantitativeValue",
                    "MonetaryAmount", "PriceSpecification", "Country", "City", "State", "Audience", "PerformingGroup",
                    "Organization", "Person", "VideoObject"}
PRICE = re.compile(r"(₹|\brs\.?|\binr)\s?\d", re.I)
PIN = re.compile(r"\b[1-9]\d{2}\s?\d{3}\b")


def elements(model: dict) -> set[str]:
    """Structural and trust elements a page shows (compared with the top competitor pages)."""
    text = " ".join(p["text"] for p in model.get("passages", [])) + " " + (model.get("main_text_sample") or "")
    nodes = page_nodes(model)
    found = {f"schema: {t}" for t in page_types(model) if t not in STRUCTURAL_TYPES}
    checks = {
        "ratings in structured data": any(n.get("aggregateRating") or "Review" in types_of(n) for n in nodes),
        "prices in the text": bool(PRICE.search(text)),
        "address with PIN code": bool(PIN.search(text)),
        "question-style headings": sum(is_question(h["text"]) for h in model.get("headings", [])) >= 2,
        "tables": any(p.get("tag") == "td" for p in model.get("passages", [])),
    }
    return found | {name for name, ok in checks.items() if ok}


def depth(model: dict, template: set[str] | None = None) -> tuple[int, int]:
    """(main-content words, sections with text)."""
    return model.get("main_text_words") or 0, sum(1 for s in sections(model, template=template) if s["passages"])


class SerpLandscape(Agent):
    id = "S6"
    name = "SERP Landscape & Competitors"
    pillar = Pillar.SEO
    counts_toward_readiness = False  # a benchmark (docs/spec/04)
    requires = frozenset({EvidenceType.SERP, EvidenceType.COMPETITORS, EvidenceType.COMPETITOR_PAGES,
                          EvidenceType.PAGES_PARSED})
    signature_columns = ["Query", "Client position", "Top results by type", "Features shown"]
    checks = [
        CheckSpec(id="S6.01", title="Client visibility", default_severity=Sev.HIGH, method="S",
                  counts_toward_readiness=False),
        CheckSpec(id="S6.02", title="Competitor classification", default_severity=Sev.LOW, method="S+L",
                  counts_toward_readiness=False),
        CheckSpec(id="S6.03", title="SERP feature map", default_severity=Sev.LOW, method="S",
                  counts_toward_readiness=False),
        CheckSpec(id="S6.04", title="Structural gaps", default_severity=Sev.MEDIUM, method="D+S",
                  counts_toward_readiness=False),
        CheckSpec(id="S6.05", title="Depth comparison", default_severity=Sev.LOW, method="D",
                  counts_toward_readiness=False),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        serps = {}
        for ev in ctx.snapshot.evidence(EvidenceType.SERP):
            if ev.payload.get("organic"):
                serps[ev.payload["query"]] = ev
        typed = ctx.snapshot.evidence(EvidenceType.COMPETITORS)
        types = {d["domain"]: d["type"] for d in (typed[-1].payload["domains"] if typed else [])}
        fetched = ctx.snapshot.evidence(EvidenceType.COMPETITOR_PAGES)
        competitor_pages = [e for e in fetched if e.blob_key]
        coverage = Coverage(examined={"queries": len(serps), "competitor_pages": len(competitor_pages)})
        refused = sorted({e.payload["domain"] for e in fetched if not e.blob_key})
        if refused:
            coverage.limits.append("Competitor pages not compared (robots.txt, blocked or not HTML): "
                                   + ", ".join(refused) + ".")
        coverage.limits.append("Rankings from one capture (India, one day); competitor pages are their top-ranking "
                               "pages for these searches, fetched only where their robots.txt allows.")
        rows = []
        for query, ev in serps.items():
            p = ev.payload
            kinds = Counter(types.get(r.get("domain"), "unclassified") for r in p["organic"][:10])
            feats = p.get("features") or {}
            shown = [name for name, on in (("AI Overview", feats.get("ai_overview")), ("PAA", feats.get("paa")),
                                           ("snippet", feats.get("answer_box")),
                                           ("local pack", feats.get("local_results"))) if on]
            rows.append([query, p.get("client_position") or "not in top 10",
                         ", ".join(f"{n} {k}" for k, n in kinds.most_common()),
                         ", ".join(shown) if p.get("features") is not None else "not captured (organic only)"])
        pages = [p for p in load_pages(ctx) if p.is_html]
        entry = entry_page(pages, ctx.client.primary_url)
        findings = [self._visibility(serps), self._classification(types, serps),
                    self._features(serps), *self._gaps(ctx, entry, pages, competitor_pages)]
        return AgentResult(findings=findings, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    def _visibility(self, serps):
        if not serps:
            return self.finding("S6.01", St.UNVERIFIABLE, "No search results captured")
        non_brand = {q: ev.payload for q, ev in serps.items() if ev.payload.get("intent") != "brand"}
        ranked = {q: p["client_position"] for q, p in non_brand.items() if p.get("client_position")}
        evidence = [EvidenceRef(type="serp", excerpt=f"\"{q}\": " + (f"#{p['client_position']}"
                                                                   if p.get("client_position") else "not in top 10"))
                    for q, p in list(non_brand.items())[:6]]
        if ranked:
            return self.finding("S6.01", St.PASS, f"In the top 10 for {len(ranked)} of {len(non_brand)} non-brand "
                                                  "searches", evidence=evidence)
        return self.finding(
            "S6.01", St.WARN, f"Not in the top 10 for any of {len(non_brand)} non-brand searches", evidence=evidence,
            impact="Customers who don't search the name never see the site in the first page of results.",
            fix="Target searches where a single-business page can rank (see S4.04, S5) and be listed on the sites "
                "that do rank.", verification="Recapture the SERPs.", effort=Effort.L)

    def _classification(self, types, serps):
        if not types:
            return self.finding("S6.02", St.UNVERIFIABLE, "Ranking domains not classified (C8)")
        counts = Counter(t for t in types.values())
        direct = [d for d, t in types.items() if t == "direct"]
        evidence = [EvidenceRef(type="serp", excerpt=", ".join(f"{n} {t}" for t, n in counts.most_common()))]
        evidence += [EvidenceRef(type="serp", excerpt=f"direct competitors: {', '.join(direct[:6])}")] if direct else []
        return self.finding("S6.02", St.PASS, f"{len(types)} ranking domains: {counts.get('direct', 0)} direct "
                                              f"competitors, {counts.get('aggregator', 0)} aggregators",
                            evidence=evidence, confidence=Confidence.LIKELY)

    def _features(self, serps):
        covered = {q: ev.payload["features"] for q, ev in serps.items() if ev.payload.get("features")}
        if not covered:
            return self.finding("S6.03", St.NOT_APPLICABLE, "No SerpAPI feature captures")
        evidence = [EvidenceRef(type="serp", excerpt=f"\"{q}\": AI Overview {'yes' if f.get('ai_overview') else 'no'}, "
                                                     f"PAA {len(f.get('paa') or [])}, snippet "
                                                     f"{'yes' if f.get('answer_box') else 'no'}, local pack "
                                                     f"{f.get('local_results') or 0}")
                    for q, f in list(covered.items())[:5]]
        with_aio = sum(1 for f in covered.values() if f.get("ai_overview"))
        return self.finding("S6.03", St.PASS, f"AI Overviews on {with_aio} of {len(covered)} feature-captured "
                                              "searches", evidence=evidence)

    def _gaps(self, ctx, entry, pages, competitor_pages):
        if entry is None or not competitor_pages:
            reason = "No competitor pages fetched (C8)" if entry is not None else "Entry page not fetched"
            return [self.finding("S6.04", St.UNVERIFIABLE, reason), self.finding("S6.05", St.UNVERIFIABLE, reason)]
        top = sorted(competitor_pages, key=lambda e: e.payload.get("position") or 99)[:TOP_COMPETITOR_PAGES]
        models = [(e.payload, ctx.snapshot.blob_json(e.blob_key)) for e in top]
        mine = elements(entry.model)
        counts = Counter(el for _, m in models for el in elements(m))
        gaps = sorted(el for el, n in counts.items() if n >= min(GAP_SHARE, len(models)) and el not in mine)
        evidence = [EvidenceRef(type="html_excerpt", url=p["url"], excerpt=f"#{p.get('position')} for \"{p['query']}\""
                                                                           f": {', '.join(sorted(elements(m)))[:250]}")
                    for p, m in models]
        gap = (self.finding(
            "S6.04", St.WARN, f"{len(gaps)} element(s) most top competitor pages have and the entry page lacks: "
                              + ", ".join(gaps), pages=[entry.url], evidence=evidence, confidence=Confidence.LIKELY,
            impact="Pages that rank for these searches share these elements.",
            fix="Add the elements that fit your offer (e.g. prices, ratings in structured data, a question-and-answer "
                "section).", verification="Re-run S6.", effort=Effort.M) if gaps
            else self.finding("S6.04", St.PASS, "The entry page has what most top competitor pages have",
                              pages=[entry.url], evidence=evidence))
        template = template_blocks([p.model for p in pages])
        words, secs = depth(entry.model, template)
        theirs = [depth(m) for _, m in models]
        med_words, med_secs = median(w for w, _ in theirs), median(s for _, s in theirs)
        depth_evidence = [EvidenceRef(type="metric", url=entry.url,
                                      excerpt=f"entry page: {words} words, {secs} sections"),
                          EvidenceRef(type="metric", excerpt=f"competitor median: {med_words:.0f} words, "
                                                             f"{med_secs:.0f} sections ({len(theirs)} pages)")]
        if med_words and words < med_words / 2:
            return [gap, self.finding("S6.05", St.WARN, "The entry page has less than half the content of the top "
                                                        "competitor pages", pages=[entry.url], evidence=depth_evidence,
                                      impact="Ranking pages cover more for this search.",
                                      fix="Cover the subtopics searchers expect (see S4.05).",
                                      verification="Re-run S6.", effort=Effort.M)]
        return [gap, self.finding("S6.05", St.PASS, "Content depth is comparable to the top competitor pages",
                                  pages=[entry.url], evidence=depth_evidence)]
