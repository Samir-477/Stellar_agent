"""G4 Citation Sources (observation, not scored): which pages do AI answers cite for the client's
searches, and are they the client's, competitors', or third parties' (listing sites, forums)?

Deterministic, from C10 captures: Google AI Overview references (real citations) and the simulated
search's picks (a proxy, labelled separately), classified by domain; URLs that models printed from
memory and whether they resolve (C10 checks them). What cited pages have in common (G4.04) needs
the cited pages themselves, which aren't fetched yet (C8).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlsplit

from engine.agents.base import Agent
from engine.agents.common import archetype
from engine.context import AgentContext, WorkUnit
from engine.lib.urls import site_label
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

REAL = "google_ai_overview"
PROXY = "simulated_search"
PROBES = ("deepseek", "groq")
# Sites that list or review many businesses; the pack adds its archetype's platforms.
LISTING_SITES = {"tripadvisor", "booking", "makemytrip", "goibibo", "agoda", "expedia", "trivago", "hotels",
                 "justdial", "indiamart", "google", "facebook", "instagram", "youtube", "reddit", "quora",
                 "wikipedia", "bankbazaar", "paisabazaar", "amazon", "flipkart", "zomato", "swiggy", "easemytrip"}


@dataclass
class Citation:
    surface: str
    prompt: str
    kind: str
    url: str
    domain: str
    printed: bool = False
    resolves: bool | None = None


def _domain(url: str | None) -> str:
    return (urlsplit(url or "").hostname or "").removeprefix("www.")


def site_type(domain: str, client: str, platforms: set[str]) -> str:
    if domain == client or domain.endswith("." + client):
        return "client"
    if site_label(domain) in LISTING_SITES or any(domain == p or domain.endswith("." + p) for p in platforms):
        return "listing or social site"
    return "other site"


def load_citations(ctx: AgentContext) -> list[Citation]:
    out = []
    for ev in ctx.snapshot.evidence(EvidenceType.AI_ANSWERS):
        for a in ev.payload.get("answers", []):
            surface = a.get("surface") or ev.payload.get("surface")
            for c in a.get("citations") or []:
                url = c.get("url") or c.get("link")
                if url and "google.com/searchviewer" not in url:  # Google's own viewer links, not sources
                    out.append(Citation(surface, a.get("prompt") or "", a.get("prompt_kind") or "", url,
                                        c.get("domain") or _domain(url), bool(c.get("printed")), c.get("resolves")))
    return out


class CitationSources(Agent):
    id = "G4"
    name = "Citation Sources"
    pillar = Pillar.GEO
    counts_toward_readiness = False  # dated, sampled observations (docs/spec/04)
    requires = frozenset({EvidenceType.AI_ANSWERS})
    signature_columns = ["Domain", "Type", "Times cited", "Surfaces", "Verified retrieval?"]
    checks = [
        CheckSpec(id="G4.01", title="Client pages cited", default_severity=Sev.HIGH, method="M",
                  counts_toward_readiness=False),
        CheckSpec(id="G4.02", title="Cited domains", default_severity=Sev.MEDIUM, method="M",
                  counts_toward_readiness=False),
        CheckSpec(id="G4.03", title="Printed URLs (knowledge probes)", default_severity=Sev.MEDIUM, method="M+D",
                  counts_toward_readiness=False),
        CheckSpec(id="G4.04", title="Traits of cited pages", default_severity=Sev.LOW, method="M+L",
                  counts_toward_readiness=False),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        client = _domain(ctx.client.primary_url)
        the_pack = pack(archetype(ctx))
        platforms = set(the_pack.platforms) if the_pack else set()
        cites = load_citations(ctx)
        coverage = Coverage(examined={"citations": len(cites)})
        coverage.limits.append("Google AI Overview references are real citations; simulated-search picks are a "
                               "proxy (DeepSeek choosing among Google's top results), reported separately.")
        typed = {c.domain: site_type(c.domain, client, platforms) for c in cites}
        by_domain: dict[str, list[Citation]] = {}
        for c in cites:
            if not c.printed:
                by_domain.setdefault(c.domain, []).append(c)
        rows = [[d, typed[d], len(group), ", ".join(sorted({c.surface for c in group})),
                 "yes (Google AI Overview)" if any(c.surface == REAL for c in group) else "proxy only"]
                for d, group in sorted(by_domain.items(), key=lambda kv: -len(kv[1]))]
        findings = [self._client_pages(cites, typed), self._domains(cites, typed), self._printed(cites),
                    self.finding("G4.04", St.UNVERIFIABLE, "What cited pages have in common needs the pages "
                                                           "themselves (competitor and cited-page capture, C8)")]
        return AgentResult(findings=findings, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    def _client_pages(self, cites: list[Citation], typed: dict[str, str]):
        real = [c for c in cites if c.surface == REAL]
        if not real:
            return self.finding("G4.01", St.NOT_APPLICABLE, "No Google AI Overview citations captured")
        ours = [c for c in real if typed[c.domain] == "client"]
        category = [c for c in ours if c.kind != "brand"]
        proxy = [c for c in cites if c.surface == PROXY and typed[c.domain] == "client"]
        evidence = [EvidenceRef(type="ai_answer", url=c.url, excerpt=f"AI Overview for \"{c.prompt}\" cites {c.url}")
                    for c in ours[:4]]
        evidence += [EvidenceRef(type="ai_answer", url=c.url, excerpt=f"proxy: simulated search picks {c.url} for "
                                                                      f"\"{c.prompt}\"") for c in proxy[:2]]
        queries = sorted({c.prompt for c in real})
        if category:
            searches = len({c.prompt for c in category})
            return self.finding("G4.01", St.PASS, f"AI Overviews cite the client for {searches} non-brand search(es)",
                                evidence=evidence)
        return self.finding(
            "G4.01", St.WARN, "AI Overviews cite the client only when searched by name" if ours
            else "AI Overviews never cite the client", evidence=evidence or [
                EvidenceRef(type="ai_answer", excerpt="AI Overviews captured for: " + "; ".join(queries)[:300])],
            impact="For searches that don't name you, AI Overviews send readers to other sites.",
            fix="Publish pages that answer these searches directly, and be present on the sites that get cited "
                "(G4.02).",
            verification="Recapture the AI Overviews.", effort=Effort.L)

    def _domains(self, cites: list[Citation], typed: dict[str, str]):
        sourced = [c for c in cites if not c.printed and c.kind != "brand"]
        if not sourced:
            return self.finding("G4.02", St.NOT_APPLICABLE, "No citations for non-brand searches captured")
        counts = Counter(c.domain for c in sourced)
        kinds = Counter(typed[c.domain] for c in sourced)
        evidence = [EvidenceRef(type="ai_answer", excerpt=f"{d} ({typed[d]}): cited {n} time(s) on "
                                                          + ", ".join(sorted({c.surface for c in sourced
                                                                              if c.domain == d})))
                    for d, n in counts.most_common(6)]
        if kinds["client"]:
            return self.finding("G4.02", St.PASS, f"The client is among the sites cited for non-brand searches "
                                                  f"({kinds['client']} of {len(sourced)} citations)", evidence=evidence)
        return self.finding(
            "G4.02", St.WARN, f"All {len(sourced)} citations for non-brand searches go to other sites "
                              f"({kinds['listing or social site']} to listing or social sites)",
            evidence=evidence, confidence=Confidence.CONFIRMED,
            impact="AI answers learn about your category from these sites; if you aren't on them, you aren't in the "
                   "answer.", fix="Claim and complete your listings on the cited listing sites and earn mentions in "
                                  "the other cited sources.", verification="Recapture the AI answers.",
            effort=Effort.M)

    def _printed(self, cites: list[Citation]):
        printed = [c for c in cites if c.printed and c.surface in PROBES]
        if not printed:
            return self.finding("G4.03", St.NOT_APPLICABLE, "The models printed no URLs")
        unchecked = [c for c in printed if c.resolves is None]
        broken = [c for c in printed if c.resolves is False]
        evidence = [EvidenceRef(type="ai_answer", excerpt=f"{c.surface} printed {c.url} (printed, unverified): "
                                                          + ("doesn't resolve" if c.resolves is False
                                                             else "resolves" if c.resolves else "not checked"))
                    for c in (broken + printed)[:5]]
        if broken:
            return self.finding(
                "G4.03", St.WARN, f"{len(broken)} of {len(printed)} URL(s) printed by AI models don't exist",
                evidence=evidence,
                impact="Models that invent links send customers to dead pages under your name.",
                fix="Keep old URLs redirecting to live pages; make key page URLs stable and easy to learn.",
                verification="Recapture the probes.", effort=Effort.S)
        if len(unchecked) == len(printed):
            return self.finding("G4.03", St.UNVERIFIABLE, f"{len(printed)} printed URL(s) weren't checked",
                                evidence=evidence)
        return self.finding("G4.03", St.PASS, "URLs printed by AI models resolve", evidence=evidence)
