"""S9 Local & Entity Consistency: are the business's name, address and phone (NAP) the same on the
site, in its structured data, on Google Maps and in the Knowledge Graph; do its location pages
carry the local basics; and are contact details in Indian formats?

Deterministic, from the parsed pages (C2), the Fact Sheet (C4: site-stated facts and JSON-LD
facts, which record the schema entity type), C12 (Maps listing, Knowledge Graph) and C6 (local
packs). `not_applicable` when the business has no physical location or service area.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from engine.agents.base import Agent
from engine.agents.common import archetype, business_name, entry_page, fact_sheet, load_pages, norm
from engine.context import AgentContext, WorkUnit
from engine.lib.content import own_text, template_blocks
from engine.lib.names import names_match
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

# Schema types that describe a place a customer visits (not the parent organisation).
PLACE_TYPES = ("Hotel", "LodgingBusiness", "Resort", "Motel", "Hostel", "BedAndBreakfast", "LocalBusiness",
               "Restaurant", "Store", "BankOrCreditUnion", "FinancialService", "MovingCompany")
PIN = re.compile(r"\b[1-9]\d{2}\s?\d{3}\b")
HOURS = re.compile(r"\b\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm)\b|\b24\s*[x×/]\s*7\b|check-?in|check-?out|open(?:ing)? hours",
                   re.I)
DISTANCE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:km|kms|kilomet\w+|minutes?|mins?)\b", re.I)
MAPS = re.compile(r"google\.[a-z.]+/maps|maps\.google|goo\.gl/maps|maps\.app\.goo\.gl|get directions|directions",
                  re.I)
MAPS_CATEGORY = {"hospitality": re.compile(r"hotel|resort|lodg|inn|guest ?house|homestay|villa", re.I),
                 "loans": re.compile(r"loan|financ|bank|credit", re.I),
                 "retail": re.compile(r"store|shop|retail|boutique|outlet", re.I),
                 "logistics": re.compile(r"courier|logistic|freight|shipping|transport|cargo", re.I)}
SERVICE_AREA = re.compile(r"\b(we (?:serve|deliver|operate)|serviceable|service areas?|branches in|available in|"
                          r"pin ?codes?)\b", re.I)


def digits(phone: str) -> str:
    """The last 10 digits: +91 98123 45678, 098123 45678 and 9812345678 compare equal."""
    return re.sub(r"\D", "", phone or "")[-10:]


@dataclass
class Source:
    name: str  # where the details come from
    business: str | None = None
    city: str | None = None
    phones: set[str] = field(default_factory=set)
    url: str | None = None


class LocalConsistency(Agent):
    id = "S9"
    name = "Local & Entity Consistency"
    pillar = Pillar.SEO
    requires = frozenset({EvidenceType.PAGES_PARSED, EvidenceType.FACTS, EvidenceType.ENTITY_FOOTPRINT,
                          EvidenceType.SERP, EvidenceType.ARCHETYPE})
    signature_columns = ["Source", "Name", "City / address", "Phone"]
    checks = [
        CheckSpec(id="S9.01", title="NAP consistency", default_severity=Sev.HIGH, method="D+S"),
        CheckSpec(id="S9.02", title="Location pages", default_severity=Sev.HIGH, method="D"),
        CheckSpec(id="S9.03", title="Google Maps listing", default_severity=Sev.MEDIUM, method="S"),
        CheckSpec(id="S9.04", title="Local pack presence", default_severity=Sev.LOW, method="S",
                  counts_toward_readiness=False),  # observation per local query
        CheckSpec(id="S9.05", title="India contact formats", default_severity=Sev.LOW, method="D"),
        CheckSpec(id="S9.06", title="Service area stated", default_severity=Sev.MEDIUM, method="D"),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        pages = [p for p in load_pages(ctx) if p.is_html]
        entry = entry_page(pages, ctx.client.primary_url)
        arch = archetype(ctx)
        parts = {e.payload["part"]: e.payload for e in ctx.snapshot.evidence(EvidenceType.ENTITY_FOOTPRINT)}
        coverage = Coverage(examined={"pages": len(pages)})
        if entry is None:
            coverage.skipped.append("The entry page wasn't fetched.")
            return AgentResult(findings=[self.finding(c.id, St.UNVERIFIABLE, "No entry page") for c in self.checks],
                               coverage=coverage)
        sources = self._sources(ctx, entry, pages, parts)
        name = business_name(ctx)
        findings = [self._nap(sources, name, ctx), self._location_pages(entry, pages),
                    self._maps(parts.get("places"), arch, ctx), self._local_pack(ctx, name),
                    self._formats(entry), self._service_area(arch, pages)]
        rows = [[s.name, s.business or "—", s.city or "—", ", ".join(sorted(s.phones)) or "—"] for s in sources]
        return AgentResult(findings=findings, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    # ------------------------------------------------------------ sources

    @staticmethod
    def _sources(ctx, entry, pages, parts) -> list[Source]:
        facts = fact_sheet(ctx)
        site_city = next((f["value"] for f in facts if f["key"] == "city" and f["status"] == "site-stated"), None)
        contact = next((p for p in pages if re.search(r"/contact", urlsplit(p.url).path)), None)
        out = [Source("entry page", business_name(ctx), site_city,
                      {digits(c["value"]) for c in entry.model.get("contacts", []) if c["type"] == "tel"}, entry.url)]
        if contact is not None:
            out.append(Source("contact page", None, None,
                              {digits(c["value"]) for c in contact.model.get("contacts", []) if c["type"] == "tel"},
                              contact.url))
        schema = [f for f in facts if f["status"] == "schema-declared" and norm(f["source_url"]) == norm(entry.url)
                  and f.get("method", "").removeprefix("jsonld:") in PLACE_TYPES]
        if schema:
            first: dict[str, str] = {}
            for f in schema:
                first.setdefault(f["key"], f["value"])
            out.append(Source(f"schema ({schema[0]['method'].removeprefix('jsonld:')})", first.get("business_name"),
                              first.get("city") or first.get("address"),
                              {digits(f["value"]) for f in schema if f["key"] == "phone"}, entry.url))
        place = (parts.get("places") or {}).get("match")
        if place:
            out.append(Source("Google Maps", place.get("title"), place.get("address"),
                              {digits(place["phoneNumber"])} if place.get("phoneNumber") else set()))
        kg = (parts.get("kg") or {}).get("knowledge_graph")
        if kg:
            out.append(Source("Knowledge Graph", kg.get("title"), kg.get("address"),
                              {digits(kg["phone"])} if kg.get("phone") else set()))
        return out

    # ------------------------------------------------------------ checks

    def _nap(self, sources: list[Source], name: str, ctx):
        site = sources[0]
        site_phones = set().union(*(s.phones for s in sources if s.name in ("entry page", "contact page")))
        others = [s for s in sources if s.name not in ("entry page", "contact page")]
        if not others:
            return self.finding("S9.01", St.UNVERIFIABLE, "Only the site's own details were found (no schema, Maps "
                                                          "or Knowledge Graph entry to compare)")
        names = [s for s in others if s.business and not names_match(name, s.business)]
        cities = [s for s in others if s.city and site.city and site.city.lower() not in s.city.lower()]
        phones = [s for s in others if s.phones and site_phones and not s.phones & site_phones]
        evidence = [EvidenceRef(type="html_excerpt", url=s.url, excerpt=f"{s.name}: name \"{s.business}\" vs "
                                                                        f"\"{name}\"") for s in names[:2]]
        evidence += [EvidenceRef(type="html_excerpt", url=s.url, excerpt=f"{s.name}: \"{s.city}\" vs the site's "
                                                                         f"{site.city}") for s in cities[:2]]
        evidence += [EvidenceRef(type="html_excerpt", url=s.url, excerpt=f"{s.name}: phone {', '.join(s.phones)} "
                                                                         "isn't on the site") for s in phones[:2]]
        if names or cities:
            return self.finding(
                "S9.01", St.FAIL, "Conflicting " + " and ".join(k for k, v in (("names", names), ("addresses", cities))
                                                                if v) + " across " + ", ".join(
                    sorted({s.name for s in names + cities})),
                pages=[site.url], key_page=True, evidence=evidence,
                impact="Search engines and AI systems merge sources by name, address and phone; conflicts split or "
                       "mix up the business.",
                fix="Make the name, address and phone identical on the page, in its JSON-LD and on Google Maps.",
                verification="Re-run S9: one name, address and phone everywhere.", effort=Effort.S)
        if phones:
            return self.finding(
                "S9.01", St.WARN, "Phone numbers differ between the site and " + ", ".join(s.name for s in phones),
                pages=[site.url], evidence=evidence, confidence=Confidence.LIKELY,
                impact="Different numbers look like different businesses (or a central line vs the property).",
                fix="List the same main number everywhere, or both numbers with labels.",
                verification="Re-run S9.", effort=Effort.S)
        return self.finding("S9.01", St.PASS, "Name, city and phone agree across the site, schema and listings",
                            evidence=[EvidenceRef(type="html_excerpt", excerpt=f"{s.name}: {s.business or '—'}, "
                                                                               f"{s.city or '—'}")
                                      for s in sources[:4]])

    def _location_pages(self, entry, pages):
        template = template_blocks([p.model for p in pages])
        text = entry.visible_text() + " " + own_text(entry.model, template)
        links = " ".join(f"{l['text']} {l['href']}" for l in entry.model.get("links", []))
        resources = " ".join(r.get("src") or "" for r in entry.model.get("resources", []))
        present = {"address": bool(PIN.search(text)), "hours or check-in times": bool(HOURS.search(text)),
                   "map or directions": bool(MAPS.search(links + " " + resources + " " + text)),
                   "local detail (distances)": bool(DISTANCE.search(text))}
        missing = [k for k, ok in present.items() if not ok]
        evidence = [EvidenceRef(type="html_excerpt", url=entry.url,
                                excerpt=", ".join(f"{k}: {'yes' if ok else 'no'}" for k, ok in present.items()))]
        if not missing:
            return self.finding("S9.02", St.PASS, "The location page has address, hours, map and local detail",
                                pages=[entry.url], evidence=evidence)
        return self.finding(
            "S9.02", St.WARN, "The location page is missing: " + ", ".join(missing), pages=[entry.url],
            key_page=True, evidence=evidence, confidence=Confidence.LIKELY,
            impact="Location pages without the basics don't rank for local searches or answer 'where/when' "
                   "questions.",
            fix="Add the full address with PIN code, opening or check-in hours, and a map link to the page text.",
            verification="Re-run S9.", effort=Effort.S)

    def _maps(self, part, arch, ctx):
        if part is None or part.get("error"):
            return self.finding("S9.03", St.UNVERIFIABLE, "Google Maps not checked")
        match = part.get("match")
        if not match:
            return self.finding(
                "S9.03", St.FAIL, "No Google Maps listing found for the business", confidence=Confidence.LIKELY,
                evidence=[EvidenceRef(type="serp", excerpt="Maps results: " + "; ".join(
                    p.get("title", "") for p in part.get("places", []))[:300] or "none")],
                impact="The Maps listing drives local search, directions and the knowledge panel.",
                fix="Create and verify a Google Business Profile.", verification="Re-run C12.", effort=Effort.M)
        client = (urlsplit(ctx.client.primary_url).hostname or "").removeprefix("www.")
        category_ok = bool(MAPS_CATEGORY.get(arch or "", re.compile(".")).search(match.get("category") or ""))
        website = match.get("website")
        issues = ([] if category_ok else [f"category \"{match.get('category')}\" doesn't fit the business"]) + (
            ["no website link in the listing data"] if not website
            else [] if (urlsplit(website).hostname or "").removeprefix("www.") == client
            else [f"website points to {website}"])
        evidence = [EvidenceRef(type="serp", excerpt=f"{match.get('title')}: {match.get('category') or '—'}, rating "
                                                     f"{match.get('rating') or '—'} ({match.get('ratingCount') or 0} "
                                                     f"reviews), website {website or '—'}")]
        if issues:
            return self.finding("S9.03", St.WARN, "The Maps listing is found but " + "; ".join(issues),
                                evidence=evidence, confidence=Confidence.LIKELY,
                                impact="An incomplete listing sends fewer visitors to the site and to the right page.",
                                fix="Complete the Google Business Profile: category, hours, phone and the property "
                                    "page as the website.", verification="Re-run C12.", effort=Effort.S)
        return self.finding("S9.03", St.PASS, "The Maps listing is found, categorised correctly and links to the site",
                            evidence=evidence)

    def _local_pack(self, ctx, name: str):
        packs = []
        for ev in ctx.snapshot.evidence(EvidenceType.SERP):
            if not ev.payload.get("features") or not ev.blob_key:
                continue
            raw = (ctx.snapshot.blob_json(ev.blob_key) or {}).get("serpapi") or {}
            places = (raw.get("local_results") or {}).get("places") or []
            if places:
                packs.append((ev.payload["query"], [p.get("title", "") for p in places]))
        if not packs:
            return self.finding("S9.04", St.NOT_APPLICABLE, "No local packs on the captured searches")
        shown = [(q, t) for q, t in packs if any(names_match(name, x) for x in t)]
        evidence = [EvidenceRef(type="serp", excerpt=f"\"{q}\": " + "; ".join(t[:3])) for q, t in packs[:4]]
        if shown:
            return self.finding("S9.04", St.PASS, f"The business appears in {len(shown)} of {len(packs)} local pack(s)",
                                evidence=evidence)
        return self.finding("S9.04", St.WARN, f"The business isn't in any of the {len(packs)} local pack(s) captured",
                            evidence=evidence, impact="Local packs sit above the organic results for local searches.",
                            fix="Strengthen the Maps listing: reviews, photos, category and consistent details.",
                            verification="Recapture.", effort=Effort.M)

    def _formats(self, entry):
        tels = [c["value"] for c in entry.model.get("contacts", []) if c["type"] == "tel"]
        has_pin = bool(PIN.search(entry.visible_text()))
        international = [t for t in tels if t.replace(" ", "").startswith(("+91", "0091"))]
        evidence = [EvidenceRef(type="html_excerpt", url=entry.url,
                                excerpt=f"tel: links {', '.join(sorted(set(tels))[:3]) or 'none'}; PIN code in the "
                                        f"page text: {'yes' if has_pin else 'no'}")]
        if not tels or not has_pin:
            return self.finding(
                "S9.05", St.FAIL, "The location page has no " + " and no ".join(
                    k for k, v in (("clickable phone", not tels), ("PIN code", not has_pin)) if v),
                pages=[entry.url], evidence=evidence,
                impact="Phone links and PIN codes are how Indian customers and local search read a location.",
                fix="Add the address with its PIN code and the phone as a tel: link in +91 format.",
                verification="Re-run S9.", effort=Effort.S)
        if len(international) < len(tels):
            return self.finding("S9.05", St.WARN, "Phone links don't use the +91 format", pages=[entry.url],
                                evidence=evidence, impact="Numbers without +91 fail for visitors calling from abroad.",
                                fix="Write tel: links as tel:+91XXXXXXXXXX.", verification="Re-run S9.",
                                effort=Effort.S)
        return self.finding("S9.05", St.PASS, "Phone links use +91 and the address has a PIN code",
                            pages=[entry.url], evidence=evidence)

    def _service_area(self, arch, pages):
        if arch not in ("logistics", "loans"):
            return self.finding("S9.06", St.NOT_APPLICABLE, "Service area applies to logistics and lenders")
        text = " ".join(p.visible_text() for p in pages)
        pins = set(PIN.findall(text))
        stated = SERVICE_AREA.search(text)
        evidence = [EvidenceRef(type="html_excerpt", excerpt=f"{len(pins)} PIN code(s); service-area wording: "
                                                              f"{stated.group(0) if stated else 'none'}")]
        if len(pins) >= 3 or (stated and re.search(r"(?:[A-Z][a-z]+,\s*){2,}[A-Z][a-z]+", text)):
            return self.finding("S9.06", St.PASS, "The service area is listed", evidence=evidence)
        if stated or re.search(r"pan[- ]india|across india|all over india", text, re.I):
            return self.finding("S9.06", St.WARN, "The service area is stated only vaguely", evidence=evidence,
                                impact="Customers and AI assistants can't tell whether you serve their area.",
                                fix="List the cities, regions or PIN codes you serve.", verification="Re-run S9.",
                                effort=Effort.S)
        return self.finding("S9.06", St.FAIL, "No service area stated", evidence=evidence,
                            impact="Customers and AI assistants can't tell whether you serve their area.",
                            fix="Add a service-area section listing cities, regions or PIN codes.",
                            verification="Re-run S9.", effort=Effort.S)
