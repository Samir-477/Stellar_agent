"""G6 Off-site Entity Footprint: is the business present, and consistent, on the sources AI systems and
Google learn about it from: the Knowledge Graph, Wikidata, the archetype's listing platforms and the
profiles its own structured data points to?

Deterministic, from C12 (Wikidata, platform listings, Maps, Knowledge Graph), C6 (the brand search)
and the site's JSON-LD `sameAs`.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from engine.agents.base import Agent
from engine.agents.common import archetype, business_name, entry_page, load_pages
from engine.collectors.c04_facts import BUSINESS_TYPES
from engine.context import AgentContext, WorkUnit
from engine.lib.jsonld import page_nodes, types_of
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

COMPLAINT = re.compile(r"\b(complain\w*|scam|fraud|cheat\w*|refund not|worst|consumer court|mouthshut|voxya|"
                       r"consumercomplaints)\b", re.I)


def footprint(ctx: AgentContext) -> dict[str, dict]:
    return {e.payload["part"]: e.payload for e in ctx.snapshot.evidence(EvidenceType.ENTITY_FOOTPRINT)}


def entity_types(ctx: AgentContext) -> str:
    """The structured data types a fix names for the business: Organization, plus its own type if it has one."""
    the_pack = pack(archetype(ctx))
    own = the_pack.entity_type if the_pack else "Organization"
    return "Organization" if own == "Organization" else f"Organization or {own}"


def profile_key(url: str) -> str:
    """A profile URL without scheme, www, query or trailing slash: facebook.com/sterlingholidays."""
    parts = urlsplit(url.strip())
    return f"{(parts.hostname or '').removeprefix('www.')}{parts.path.rstrip('/')}".lower()


def same_as(pages) -> dict[str, set[str]]:
    """sameAs URLs from business entities in JSON-LD, grouped by site (facebook, instagram…)."""
    out: dict[str, set[str]] = {}
    for page in pages:
        for node in page_nodes(page.model):
            if not types_of(node) & BUSINESS_TYPES:
                continue
            links = node.get("sameAs") or []
            for link in [links] if isinstance(links, str) else links:
                if isinstance(link, str) and link.startswith("http"):
                    out.setdefault(site_label(urlsplit(link).hostname or ""), set()).add(profile_key(link))
    return out


class OffsiteEntityFootprint(Agent):
    id = "G6"
    name = "Off-site Entity Footprint"
    pillar = Pillar.GEO
    requires = frozenset({EvidenceType.ENTITY_FOOTPRINT, EvidenceType.PAGES_PARSED, EvidenceType.SERP})
    signature_columns = ["Source", "Present?", "Where", "Consistent with the site?"]
    checks = [
        CheckSpec(id="G6.01", title="Knowledge Graph panel for brand query", default_severity=Sev.MEDIUM,
                  method="S"),
        CheckSpec(id="G6.02", title="Wikidata / Wikipedia", default_severity=Sev.LOW, method="D"),
        CheckSpec(id="G6.03", title="Presence on archetype platforms", default_severity=Sev.MEDIUM, method="S"),
        CheckSpec(id="G6.04", title="sameAs ↔ profiles", default_severity=Sev.MEDIUM, method="D+S"),
        CheckSpec(id="G6.05", title="Brand query results", default_severity=Sev.LOW, method="S",
                  counts_toward_readiness=False),  # reported, not scored
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        parts = footprint(ctx)
        pages = [p for p in load_pages(ctx) if p.is_html]
        entry = entry_page(pages, ctx.client.primary_url)
        home = next((p for p in pages if p.is_home), None)
        coverage = Coverage(examined={"footprint_parts": len(parts)})
        coverage.limits.append("One capture on one day; listing searches match the business name in result titles.")
        rows: list[list] = []
        findings = [self._kg(parts.get("kg"), ctx, rows), self._wiki(parts.get("wiki"), ctx, rows, coverage),
                    self._platforms(parts.get("platforms"), rows),
                    self._same_as(ctx, [p for p in (entry, home) if p is not None], parts, rows),
                    self._brand_results(ctx)]
        return AgentResult(findings=findings, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    def _kg(self, part, ctx, rows):
        if part is None or part.get("error"):
            return self.finding("G6.01", St.UNVERIFIABLE, "Knowledge Graph not captured")
        kg = part.get("knowledge_graph")
        rows.append(["Knowledge Graph", "yes" if kg else "no", part.get("query"), "—"])
        if not kg:
            return self.finding(
                "G6.01", St.FAIL, f"No Knowledge Graph panel for \"{part.get('query')}\"", confidence=Confidence.LIKELY,
                evidence=[EvidenceRef(type="serp", excerpt=f"brand search \"{part.get('query')}\" "
                                                           f"({part.get('source')}): no knowledge panel")],
                impact="The knowledge panel is where Google (and AI Overviews) show who a business is; without it, "
                       "facts come from other sites.",
                fix="Complete and verify the Google Business Profile, keep name, address and website identical "
                    f"everywhere, and add {entity_types(ctx)} JSON-LD with sameAs links.",
                verification="Recapture the brand search.", effort=Effort.M)
        client = (urlsplit(ctx.client.primary_url).hostname or "").removeprefix("www.")
        wrong = [f"website {kg['website']}" for k in ("website",) if kg.get(k)
                 and (urlsplit(kg[k]).hostname or "").removeprefix("www.") != client]
        name = business_name(ctx)
        if kg.get("title") and name.lower() not in kg["title"].lower():
            wrong.append(f"title \"{kg['title']}\"")
        evidence = [EvidenceRef(type="serp", excerpt=f"panel: {kg.get('title')} ({kg.get('type') or '—'}), "
                                                     f"website {kg.get('website') or '—'}")]
        if wrong:
            return self.finding("G6.01", St.WARN, "The knowledge panel shows details that don't match the site: "
                                + ", ".join(wrong), evidence=evidence, confidence=Confidence.LIKELY,
                                impact="Wrong panel details spread to AI answers.",
                                fix="Correct them through the Google Business Profile.",
                                verification="Recapture the brand search.", effort=Effort.S)
        return self.finding("G6.01", St.PASS, "A knowledge panel appears for the brand search and matches the site",
                            evidence=evidence)

    def _wiki(self, part, ctx, rows, coverage):
        if part is None:
            return self.finding("G6.02", St.UNVERIFIABLE, "Wikidata not checked")
        if part.get("skipped"):
            coverage.skipped.append(part["skipped"])
            return self.finding("G6.02", St.UNVERIFIABLE, "Wikidata not checked (Wikimedia contact not configured)")
        matched = [e for e in part.get("entities", []) if e.get("match")]
        client = (urlsplit(ctx.client.primary_url).hostname or "").removeprefix("www.")
        for e in matched:
            rows.append(["Wikidata", "yes", e["id"], "website matches" if e["match"] == "official website"
                         else "name only"])
        if not matched:
            rows.append(["Wikidata", "no", "—", "—"])
            return self.finding(
                "G6.02", St.WARN, "No Wikidata entry for the business", confidence=Confidence.LIKELY,
                evidence=[EvidenceRef(type="serp", excerpt=f"searched Wikidata for: "
                                      + ", ".join(dict.fromkeys(e["query"] for e in part.get("entities", [])))
                                      if part.get("entities") else "searched Wikidata: no candidates")],
                impact="Wikidata is a source AI systems use to identify organisations.",
                fix="If the organisation is notable, an independent editor can add a Wikidata item with its "
                    "official website. Don't create Wikipedia pages artificially.",
                verification="Re-run C12.", effort=Effort.M)
        wrong = [e for e in matched if e["websites"] and not any(
            (urlsplit(w).hostname or "").removeprefix("www.") == client for w in e["websites"])]
        evidence = [EvidenceRef(type="serp", url=f"https://www.wikidata.org/wiki/{e['id']}",
                                excerpt=f"{e['id']} {e['label']}: {e.get('description') or ''}; website "
                                        f"{', '.join(e['websites']) or '—'}") for e in matched[:3]]
        if wrong:
            return self.finding("G6.02", St.FAIL, "The Wikidata entry lists a different official website",
                                evidence=evidence, impact="AI systems link the brand to the wrong site.",
                                fix="Correct the official website (P856) on Wikidata, citing the site.",
                                verification="Re-run C12.", effort=Effort.S)
        return self.finding("G6.02", St.PASS, "A Wikidata entry exists and points to the site", evidence=evidence)

    def _platforms(self, part, rows):
        if part is None or part.get("error"):
            return self.finding("G6.03", St.UNVERIFIABLE, "Listing platforms not checked")
        listed = part.get("platforms") or []
        if not listed:
            return self.finding("G6.03", St.NOT_APPLICABLE, "No core platforms for this archetype")
        for p in listed:
            rows.append([p["platform"], "yes" if p["found"] else "no", p.get("url") or "—", "—"])
        found = [p for p in listed if p["found"]]
        evidence = [EvidenceRef(type="serp", url=p.get("url"), excerpt=f"{p['platform']}: "
                                + (f"\"{p['title']}\"" if p["found"] else "no listing found"))
                    for p in ([p for p in listed if not p["found"]] + found)[:6]]
        if len(found) == len(listed):
            return self.finding("G6.03", St.PASS, f"Listed on all {len(listed)} core platforms", evidence=evidence)
        return self.finding(
            "G6.03", St.FAIL if not found else St.WARN,
            f"Listed on {len(found)} of {len(listed)} core platforms", evidence=evidence, confidence=Confidence.LIKELY,
            impact="These platforms are where customers compare options and where AI answers get their facts.",
            fix="Create or claim the missing listings with the same name, address, phone and website.",
            verification="Re-run C12.", effort=Effort.M)

    def _same_as(self, ctx, pages, parts, rows):
        declared = same_as(pages)
        if not pages:
            return self.finding("G6.04", St.UNVERIFIABLE, "Entry page and homepage not in the sample")
        conflicts = {site: urls for site, urls in declared.items() if len(urls) > 1}
        listings = [p for p in (parts.get("platforms") or {}).get("platforms", []) if p["found"] and p.get("url")]
        missing = [p for p in listings if site_label(urlsplit(p["url"]).hostname or "") not in declared]
        for site, urls in declared.items():
            rows.append([f"sameAs: {site}", "yes", "; ".join(sorted(urls))[:120],
                         "conflicting" if site in conflicts else "—"])
        evidence = [EvidenceRef(type="html_excerpt", excerpt=(f"sameAs lists {len(urls)} different {site} profiles: "
                                                              + ", ".join(sorted(urls)))[:400])
                    for site, urls in list(conflicts.items())[:3]]
        evidence += [EvidenceRef(type="serp", url=p["url"], excerpt=f"{p['platform']} listing not in sameAs")
                     for p in missing[:3]]
        if conflicts:
            return self.finding(
                "G6.04", St.FAIL, f"Structured data points to {len(conflicts)} site(s) with conflicting profiles: "
                + ", ".join(conflicts), evidence=evidence, pages=[p.url for p in pages],
                impact="Two profiles for one business split its reviews and confuse systems that merge entities.",
                fix="Pick the official profile per site, list only it in sameAs on every page, and merge or retire "
                    "the other.", verification="One profile per site in sameAs.", effort=Effort.S)
        if not declared or missing:
            return self.finding(
                "G6.04", St.WARN, "No sameAs links in the structured data" if not declared
                else f"{len(missing)} listing(s) found off-site aren't in sameAs", pages=[p.url for p in pages],
                evidence=evidence or [EvidenceRef(type="html_excerpt", excerpt="no sameAs on business entities")],
                impact="sameAs tells search engines and AI systems which profiles belong to the business.",
                fix=f"Add the official profiles and main listings to sameAs in the {entity_types(ctx)} JSON-LD.",
                verification="sameAs lists the official profiles.", effort=Effort.S)
        return self.finding("G6.04", St.PASS, "sameAs lists one profile per site, matching the listings found",
                            evidence=[EvidenceRef(type="html_excerpt", excerpt=", ".join(sorted(declared))[:300])])

    def _brand_results(self, ctx):
        brand = [ev.payload for ev in ctx.snapshot.evidence(EvidenceType.SERP)
                 if ev.payload.get("intent") == "brand" and ev.payload.get("organic")]
        if not brand:
            return self.finding("G6.05", St.UNVERIFIABLE, "No brand search captured")
        results = {r.get("link"): (p["query"], r) for p in brand for r in p["organic"][:10]}
        flagged = [(q, r) for q, r in results.values() if COMPLAINT.search(f"{r.get('title')} {r.get('snippet')}")]
        domains = sorted({site_label(r.get("domain") or urlsplit(r.get("link") or "").hostname or "")
                          for _, r in results.values()})
        evidence = [EvidenceRef(type="serp", url=r.get("link"), excerpt=f"\"{q}\": {r.get('title')}")
                    for q, r in flagged[:4]] + [EvidenceRef(type="serp", excerpt="sites in the brand results: "
                                                                                + ", ".join(domains)[:300])]
        if flagged:
            return self.finding("G6.05", St.WARN, f"{len(flagged)} complaint or warning result(s) in the brand "
                                                  "search", evidence=evidence,
                                impact="Complaint threads in brand results shape what customers and AI answers "
                                       "say about the business.",
                                fix="Respond to and resolve the complaints publicly.", verification="Recapture.",
                                effort=Effort.M)
        return self.finding("G6.05", St.PASS, "No complaint threads in the brand search results", evidence=evidence)
