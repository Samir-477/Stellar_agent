"""S8 Structured Data: is the JSON-LD valid, complete, appropriate and truthful?

Deterministic only. Truthfulness (S8.04) compares business-entity JSON-LD with the
page's visible text; a corrected block (S8 patch) is built only from site-stated
facts (never from other schema), and missing facts are listed rather than guessed.

Two more fixes are prepared for the team to approve (Patch.approval = "required"): the
business entity the entry page lacks (S8.03), and the name and address a WebSite or
Organization entity is missing (S8.02). Both use only the site's own facts and address.
"""

from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit

from engine.agents.base import Agent
from engine.agents.common import PageView, archetype, entry_page, fact_sheet, key_page_urls, load_pages
from engine.collectors.c04_facts import BUSINESS_TYPES
from engine.context import AgentContext, WorkUnit
from engine.lib.grounding import normalize
from engine.lib.jsonld import nodes, script_tag, types_of, updated
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
    Finding,
    Locator,
    Patch,
    PatchType,
    Pillar,
    Severity as Sev,
)

RETIRED = {"HowTo", "SpecialAnnouncement", "CourseInfo", "EstimatedSalary", "LearningVideo", "ClaimReview",
           "VehicleListing"}
REQUIRED = {
    "Organization": ("name", "url"),
    "LocalBusiness": ("name", "address"),
    "Hotel": ("name", "address"),
    "LodgingBusiness": ("name", "address"),
    "Resort": ("name", "address"),
    "Restaurant": ("name", "address"),
    "BreadcrumbList": ("itemListElement",),
    "Article": ("headline",),
    "BlogPosting": ("headline",),
    "Product": ("name",),
    "Offer": ("price", "priceCurrency"),
    "WebSite": ("name", "url"),
}
RECOMMENDED = {
    "Organization": ("logo", "sameAs", "contactPoint"),
    "LocalBusiness": ("telephone", "geo", "image", "url"),
    "Hotel": ("telephone", "geo", "image", "url", "priceRange", "checkinTime", "checkoutTime"),
    "LodgingBusiness": ("telephone", "geo", "image", "url", "priceRange"),
    "Resort": ("telephone", "geo", "image", "url", "priceRange"),
    "Article": ("author", "datePublished", "dateModified", "image"),
    "BlogPosting": ("author", "datePublished", "dateModified", "image"),
    "Product": ("image", "offers", "brand"),
}
LOCAL_TYPES = {"LocalBusiness", "Hotel", "LodgingBusiness", "Resort", "Motel", "Hostel", "BedAndBreakfast",
               "Restaurant", "Store", "FinancialService", "BankOrCreditUnion"}
# Required properties a prepared fix can fill from the site itself: its name (a stated fact) and its address.
FILLABLE = {"WebSite": ("name", "url"), "Organization": ("name", "url"), "Corporation": ("name", "url")}
# Facts a new business entity carries, as schema.org properties.
ENTITY_FACTS = (("legal_name", "legalName"), ("phone", "telephone"), ("email", "email"), ("address", "address"),
                ("founded_year", "foundingDate"))


def site_root(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/"


def stated_facts(facts: list[dict], prefer_url: str | None = None) -> dict[str, dict]:
    """The first site-stated (or team-confirmed) fact per key, taking the given page's own facts first."""
    usable = [f for f in facts if f["status"] in ("site-stated", "team-confirmed")]
    prefer = (prefer_url or "").rstrip("/")
    usable.sort(key=lambda f: f["source_url"].rstrip("/") != prefer)
    out: dict[str, dict] = {}
    for fact in usable:
        out.setdefault(fact["key"], fact)
    return out


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", normalize(text)) if len(w) > 2}


class StructuredData(Agent):
    id = "S8"
    name = "Structured Data"
    pillar = Pillar.SEO
    requires = frozenset({EvidenceType.PAGES_PARSED, EvidenceType.FACTS, EvidenceType.ARCHETYPE})
    signature_columns = ["Page", "Types found", "Valid", "Missing required", "Truthfulness mismatches"]
    checks = [
        CheckSpec(id="S8.01", title="JSON-LD syntax", default_severity=Sev.HIGH, method="D"),
        CheckSpec(id="S8.02", title="Required and recommended properties", default_severity=Sev.MEDIUM, method="D"),
        CheckSpec(id="S8.03", title="Archetype-appropriate types", default_severity=Sev.MEDIUM, method="D"),
        CheckSpec(id="S8.04", title="Schema matches visible content", default_severity=Sev.HIGH, method="D"),
        CheckSpec(id="S8.05", title="Retired or deprecated types", default_severity=Sev.LOW, method="D"),
        CheckSpec(id="S8.06", title="Entity graph consistency", default_severity=Sev.MEDIUM, method="D"),
        CheckSpec(id="S8.07", title="Review markup policy", default_severity=Sev.MEDIUM, method="D"),
    ]

    def run_unit(self, ctx: AgentContext, unit: WorkUnit) -> AgentResult:
        pages = [p for p in load_pages(ctx) if p.is_html]
        keys = key_page_urls(pages, ctx.client.primary_url)
        entry = entry_page(pages, ctx.client.primary_url)
        facts = fact_sheet(ctx)
        arch = pack(archetype(ctx))
        findings: list[Finding] = []
        patches: list[Patch] = []
        rows = []

        syntax_errors, strict_warnings = [], []
        missing_required, missing_recommended, retired, faq, graph_names = [], [], [], [], {}
        mismatches, self_reviews = [], []
        for page in pages:
            page_types, page_missing, page_mismatch = set(), [], []
            local_nodes = [(n, b) for b in page.model.get("jsonld", []) if "parsed" in b
                           for n in nodes(b["parsed"]) if types_of(n) & LOCAL_TYPES]
            for block in page.model.get("jsonld", []):
                if "error" in block:
                    syntax_errors.append((page, block))
                    continue
                if "warning" in block:
                    strict_warnings.append((page, block))
                for node in nodes(block.get("parsed")):
                    node_types = types_of(node)
                    page_types |= node_types
                    for t in node_types:
                        missing = [prop for prop in REQUIRED.get(t, ()) if not node.get(prop)]
                        if missing:
                            missing_required.append((page, t, missing, block))
                            page_missing.append(f"{t}: {', '.join(missing)}")
                        weak = [prop for prop in RECOMMENDED.get(t, ()) if not node.get(prop)]
                        if weak and page.url in keys:
                            missing_recommended.append((page, t, weak))
                    retired += [(page, t) for t in node_types & RETIRED]
                    if "FAQPage" in node_types:
                        faq.append(page)
                    if node_types & BUSINESS_TYPES:
                        if node_types & {"Organization", "Corporation"} and node.get("name"):
                            graph_names.setdefault(str(node["name"]), []).append(page.url)
                        if node_types & LOCAL_TYPES and len(local_nodes) == 1:
                            problem = self._truthfulness(page, node, block)
                            if problem:
                                mismatches.append((page, node, block, problem))
                                page_mismatch.append(problem)
                            if node.get("aggregateRating") or node.get("review"):
                                self_reviews.append((page, sorted(node_types & LOCAL_TYPES)[0]))
            rows.append([page.url, ", ".join(sorted(page_types)) or "none",
                         "no" if any(p is page for p, _ in syntax_errors) else "yes",
                         "; ".join(page_missing)[:200] or "—", "; ".join(page_mismatch)[:200] or "—"])

        findings += self._syntax(syntax_errors, strict_warnings)
        truth_findings, truth_patches = self._truth(mismatches, entry, facts, arch, ctx)
        # A block S8.04 replaces whole isn't also patched to fill properties.
        replaced = {(p.locator.xpath or p.locator.css) for p in truth_patches if p.locator}
        fills = self._fill_required(missing_required, facts, ctx, replaced)
        findings += self._properties(missing_required, missing_recommended, fills)
        patches += fills
        type_findings, type_patches = self._archetype_types(pages, entry, arch, facts, ctx)
        findings += type_findings
        patches += type_patches
        findings += truth_findings
        patches += truth_patches
        findings += self._retired(retired, faq)
        findings += self._graph(graph_names)
        findings += self._reviews(self_reviews)
        coverage = Coverage(examined={"pages": len(pages)},
                            limits=["JSON-LD only; Microdata and RDFa are not evaluated."])
        return AgentResult(findings=findings, patches=patches, coverage=coverage,
                           signature_table={"columns": self.signature_columns, "rows": rows})

    # --------------------------------------------------------------- S8.04 core

    @staticmethod
    def _truthfulness(page: PageView, node: dict, block: dict) -> str | None:
        """Does the page's single business entity describe the page's main subject?

        Compared with the title, H1 and opening passages (the page's subject), not the
        whole page: a property page often lists other properties further down.
        """
        h1 = " / ".join(h["text"] for h in page.model.get("headings", []) if h["level"] == 1)
        lead = " ".join(p["text"] for p in page.model.get("passages", [])[:3] if "{{" not in p["text"])
        subject = normalize(" ".join([page.model.get("title") or "", h1, lead]))
        problems = []
        name = str(node.get("name") or "")
        name_words = _words(name)
        if name_words and len(name_words & _words(subject)) / len(name_words) < 0.6:
            problems.append(f"schema name \"{name}\" doesn't match the page's subject (H1: \"{h1[:80]}\")")
        address = node.get("address")
        locality = address.get("addressLocality") if isinstance(address, dict) else None
        if locality and normalize(str(locality)) not in subject:
            problems.append(f"schema city \"{locality}\" isn't the city in the page's title, H1 or opening text")
        return "; ".join(problems) or None

    def _truth(self, mismatches, entry: PageView | None, facts: list[dict], arch, ctx: AgentContext):
        if not mismatches:
            return [self.finding("S8.04", St.PASS, "Business schema matches the visible content",
                                 evidence=[EvidenceRef(type="html_excerpt",
                                                       excerpt="entity names and cities found in page text")])], []
        findings, patches = [], []
        by_page: dict[str, list] = {}
        for page, node, block, problem in mismatches:
            by_page.setdefault(page.url, []).append((page, node, block, problem))
        for url, items in by_page.items():
            page, node, block, _ = items[0]
            is_entry = entry is not None and page is entry
            patch_keys, missing = [], []
            if is_entry and arch is not None:
                patch, missing = self._corrected_block(page, block, facts, arch, ctx)
                if patch:
                    patches.append(patch)
                    patch_keys.append(patch.key)
            findings.append(self.finding(
                "S8.04", St.FAIL, "Structured data describes a different business than the page shows",
                pages=[url], key_page=is_entry, severity=Sev.HIGH, patch_keys=patch_keys, missing_facts=missing,
                locator=Locator(**block["locator"]) if block.get("locator") else None,
                evidence=[EvidenceRef(type="html_excerpt", url=url, excerpt=problem) for _, _, _, problem in items[:3]]
                + [EvidenceRef(type="html_excerpt", url=url,
                               excerpt=json.dumps({k: node.get(k) for k in ("@type", "name", "address")
                                                   if node.get(k)}, ensure_ascii=False)[:300])],
                impact="Search engines and AI systems read this markup as facts about the page. Here it describes "
                       "another business or location, so they may show wrong details or distrust the page.",
                fix="Replace the markup with an entity that describes this page's business, using facts shown on "
                    "the page.",
                verification="Schema name and city match the page's visible content; validate at "
                             "https://validator.schema.org.",
                effort=Effort.S))
        return findings, patches

    def _corrected_block(self, page: PageView, block: dict, facts: list[dict], arch, ctx: AgentContext):
        stated = {}
        for fact in facts:
            if fact["status"] in ("site-stated", "team-confirmed") and fact["source_url"].rstrip("/") == page.url.rstrip("/"):
                stated.setdefault(fact["key"], []).append(fact)
        core_type = arch.entity_type
        name = (stated.get("property_name") or stated.get("business_name") or [{}])[0].get("value")
        entity: dict = {"@context": "https://schema.org", "@type": core_type, "url": page.url}
        used = []
        if name:
            entity["name"] = name
            used += [f["id"] for f in (stated.get("property_name") or stated.get("business_name"))[:1]]
        if stated.get("room_count"):
            entity["numberOfRooms"] = stated["room_count"][0]["value"]
            used.append(stated["room_count"][0]["id"])
        amenities = [a.strip() for f in stated.get("amenities", []) for a in f["value"].split(";") if a.strip()]
        if amenities:
            entity["amenityFeature"] = [{"@type": "LocationFeatureSpecification", "name": a, "value": True}
                                        for a in amenities[:10]]
            used += [f["id"] for f in stated["amenities"]]
        for key, prop in (("phone", "telephone"), ("email", "email"), ("check_in_time", "checkinTime"),
                          ("check_out_time", "checkoutTime")):
            if stated.get(key):
                entity[prop] = stated[key][0]["value"]
                used.append(stated[key][0]["id"])
        missing = [label for key, label in (("address", "address"), ("phone", "phone"), ("geo", "geo coordinates"),
                                            ("image", "image")) if key not in stated]
        if "name" not in entity:
            return None, missing + ["business name"]
        after = json.dumps(entity, ensure_ascii=False, indent=2)
        return Patch(key=f"S8.04:jsonld:{page.record.id}", agent_id=self.id, page_url=page.url,
                     type=PatchType.JSONLD_UPSERT, locator=Locator(**block["locator"]) if block.get("locator") else None,
                     before=(block.get("raw") or "")[:4000], after=f'<script type="application/ld+json">\n{after}\n</script>',
                     rationale=f"Built only from facts shown on this page ({', '.join(used)}); fields the page "
                               f"doesn't state are left out: {', '.join(missing)}.",
                     fact_ids=used,
                     client_visible_note="Corrects the page's structured data so search engines and AI "
                                         "assistants read the right business details."), missing

    # ------------------------------------------------------------ other checks

    def _syntax(self, errors, strict_warnings):
        if not errors and strict_warnings:
            return [self.finding(
                "S8.01", St.WARN, f"{len(strict_warnings)} JSON-LD block(s) aren't strict JSON",
                pages=sorted({p.url for p, _ in strict_warnings}), confidence=Confidence.LIKELY, severity=Sev.MEDIUM,
                evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt=b["warning"])
                          for p, b in strict_warnings[:5]],
                impact="The blocks contain raw line breaks inside text values. Lenient parsers accept this, "
                       "but strict parsers may reject the whole block.",
                fix="Escape line breaks inside JSON strings (or remove them) when generating the markup.",
                verification="Blocks pass a strict JSON parser and validator.schema.org.", effort=Effort.S)]
        if not errors:
            return [self.finding("S8.01", St.PASS, "All JSON-LD blocks parse")]
        return [self.finding(
            "S8.01", St.FAIL, f"{len(errors)} JSON-LD block(s) contain syntax errors",
            pages=sorted({p.url for p, _ in errors}),
            evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt=f"{b['error']}: {b['raw'][:120]}")
                      for p, b in errors[:5]],
            impact="Invalid JSON-LD is ignored entirely by search engines.",
            fix="Fix the JSON syntax (validate at https://validator.schema.org).",
            verification="Every block parses.", effort=Effort.S)]

    def _fill_required(self, required, facts: list[dict], ctx: AgentContext, replaced: set) -> list[Patch]:
        """A prepared fix per JSON-LD block whose WebSite or Organization entity lacks its name or address."""
        name = stated_facts(facts).get("business_name")
        values = {"name": name["value"] if name else None, "url": site_root(ctx.client.primary_url)}
        by_block: dict[tuple, dict] = {}
        for page, t, missing, block in required:
            ident = (block.get("locator") or {}).get("xpath") or (block.get("locator") or {}).get("css")
            fill = {prop: values[prop] for prop in missing if t in FILLABLE and prop in FILLABLE[t] and values.get(prop)}
            if not fill or not ident or ident in replaced or "parsed" not in block:
                continue
            entry = by_block.setdefault((page.record.id, ident), {"page": page, "block": block, "fills": []})
            entry["fills"].append((t, fill))
        patches = []
        for (page_id, ident), item in list(by_block.items())[:5]:
            parsed = item["block"]["parsed"]
            for t, fill in item["fills"]:
                def add(node, fill=fill):
                    for prop, value in fill.items():
                        miscased = next((k for k in node if k.lower() == prop and k != prop), None)
                        node[prop] = node.pop(miscased) if miscased and node.get(miscased) else value
                    return True
                parsed = updated(parsed, lambda n, t=t, fill=fill: t in types_of(n)
                                 and not any(n.get(p) for p in fill), add) or parsed
            if parsed is item["block"]["parsed"]:
                continue
            added = sorted({prop for _, fill in item["fills"] for prop in fill})
            used = [name["id"]] if name and "name" in added else []
            patches.append(Patch(
                key=f"S8.02:fill:{page_id}:{hashlib.sha1(ident.encode()).hexdigest()[:8]}", agent_id=self.id,
                page_url=item["page"].url, type=PatchType.JSONLD_UPSERT, locator=Locator(**item["block"]["locator"]),
                before=(item["block"].get("raw") or "")[:4000], after=script_tag(parsed), fact_ids=used,
                rationale=f"Adds the missing {' and '.join(added)} (a property written with the wrong capitals, such as "
                          f"\"Name\", is renamed and keeps its value; otherwise from the site itself: "
                          + "; ".join(f"{prop} = {values[prop]}" for prop in added) + ").",
                client_visible_note="Completes the structured data search engines read about the site.",
                approval="required"))
        return patches

    def _properties(self, required, recommended, fills: list[Patch] = ()):
        out = []
        if required:
            out.append(self.finding(
                "S8.02", St.FAIL, f"{len(required)} schema entities miss required properties",
                pages=sorted({p.url for p, _, _, _ in required}), severity=Sev.HIGH,
                patch_keys=[p.key for p in fills],
                evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt=f"{t} missing {', '.join(m)}")
                          for p, t, m, _ in required[:5]],
                impact="Entities without required properties aren't eligible for rich results.",
                fix="Add the missing required properties.", verification="Validator shows no missing required "
                                                                          "properties.", effort=Effort.S))
        if recommended:
            out.append(self.finding(
                "S8.02", St.WARN, f"Key-page entities miss recommended properties",
                pages=sorted({p.url for p, _, _ in recommended}),
                evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt=f"{t} missing {', '.join(m)}")
                          for p, t, m in recommended[:5]],
                impact="Fuller entities give search engines and AI systems more reliable facts.",
                fix="Add the recommended properties where the facts are available.",
                verification="Validator shows recommended properties present."))
        if not out:
            out.append(self.finding("S8.02", St.PASS, "Entities have their required and recommended properties"))
        return out

    def _new_entity(self, entry: PageView, facts: list[dict], arch, ctx: AgentContext):
        """The business entity the entry page lacks, built only from the site's stated facts."""
        stated = stated_facts(facts, entry.url)
        name = stated.get("property_name") or stated.get("business_name")
        if not name:
            return None, ["business name"]
        entity: dict = {"@context": "https://schema.org", "@type": arch.entity_type, "name": name["value"],
                        "url": site_root(ctx.client.primary_url)}
        used = [name["id"]]
        for key, prop in ENTITY_FACTS:
            if stated.get(key):
                entity[prop] = stated[key]["value"]
                used.append(stated[key]["id"])
        profiles = [u.strip() for u in (stated.get("social_profiles") or {}).get("value", "").split(";")
                    if u.strip().startswith("http")]
        if profiles:
            entity["sameAs"] = profiles
            used.append(stated["social_profiles"]["id"])
        missing = [label for key, label in (("address", "address"), ("phone", "phone")) if key not in stated]
        return Patch(
            key=f"S8.03:entity:{entry.record.id}", agent_id=self.id, page_url=entry.url, type=PatchType.HEAD_UPSERT,
            locator=Locator(css='head > script[type="application/ld+json"]'), before=None, after=script_tag(entity),
            fact_ids=used, approval="required",
            rationale=f"{'An' if arch.entity_type[0] in 'AEIOU' else 'A'} {arch.entity_type} entity built only from facts "
                      f"the site states ({', '.join(used)})"
                      + (f"; not stated, so left out: {', '.join(missing)}." if missing else "."),
            client_visible_note="Tells search engines and AI assistants what kind of business this is."), missing

    def _archetype_types(self, pages: list[PageView], entry: PageView | None, arch, facts: list[dict],
                         ctx: AgentContext):
        if arch is None or entry is None:
            return [self.finding("S8.03", St.UNVERIFIABLE, "Archetype or entry page unknown")], []
        entry_types = {t for b in entry.model.get("jsonld", []) for n in nodes(b.get("parsed")) for t in types_of(n)}
        site_types = {t for p in pages for b in p.model.get("jsonld", []) for n in nodes(b.get("parsed"))
                      for t in types_of(n)}
        missing = []
        if not entry_types & set(arch.core_schema_types) and not entry_types & LOCAL_TYPES:
            missing.append(f"entry page has none of {', '.join(arch.core_schema_types)}")
        if not site_types & {"Organization", "Corporation"}:
            missing.append("no Organization entity anywhere in the sample")
        if missing:
            patch, facts_needed = (self._new_entity(entry, facts, arch, ctx) if "entry" in missing[0]
                                   else (None, []))
            return [self.finding("S8.03", St.FAIL if "entry" in missing[0] else St.WARN,
                                 "Archetype schema types are missing", pages=[entry.url],
                                 patch_keys=[patch.key] if patch else [], missing_facts=facts_needed,
                                 evidence=[EvidenceRef(type="html_excerpt", url=entry.url, excerpt=m) for m in missing],
                                 impact="Search engines understand the business type from these entities.",
                                 fix=f"Add a {arch.entity_type} entity to the entry page.",
                                 verification="Validator shows the entity.", effort=Effort.S)], [patch] if patch else []
        return [self.finding("S8.03", St.PASS, "Archetype-appropriate schema types are present",
                             evidence=[EvidenceRef(type="html_excerpt", url=entry.url,
                                                   excerpt=", ".join(sorted(entry_types))[:200])])], []

    def _retired(self, retired, faq):
        if retired:
            return [self.finding(
                "S8.05", St.FAIL, "Retired schema types in use", pages=sorted({p.url for p, _ in retired}),
                evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt=t) for p, t in retired[:5]],
                impact="Google no longer uses these types; they add weight without benefit.",
                fix="Remove the retired types.", verification="No retired types remain.", effort=Effort.S)]
        if faq:
            return [self.finding(
                "S8.05", St.WARN, "FAQPage markup present (no Google rich result since May 2026)",
                pages=sorted({p.url for p in faq}), severity=Sev.LOW,
                evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt="FAQPage") for p in faq[:3]],
                impact="Harmless, but it no longer earns a search feature. Don't remove it just for this.",
                fix="No action needed; don't add new FAQPage markup expecting rich results.",
                verification="—")]
        return [self.finding("S8.05", St.PASS, "No retired schema types")]

    def _graph(self, names: dict[str, list[str]]):
        if len(names) > 1:
            return [self.finding(
                "S8.06", St.WARN, f"Organization is described with {len(names)} different names",
                pages=sorted({u for urls in names.values() for u in urls}),
                evidence=[EvidenceRef(type="html_excerpt", excerpt=f"\"{n}\" on {len(u)} page(s)")
                          for n, u in list(names.items())[:5]],
                impact="Inconsistent entity names make it harder for search engines and AI to recognise the brand.",
                fix="Use one Organization name everywhere, linked with a shared @id.",
                verification="One Organization name across pages.", effort=Effort.S)]
        return [self.finding("S8.06", St.PASS, "Organization entity is consistent")]

    def _reviews(self, self_reviews):
        if self_reviews:
            return [self.finding(
                "S8.07", St.FAIL, "Self-serving review markup on the business's own entity",
                pages=sorted({p.url for p, _ in self_reviews}), confidence=Confidence.LIKELY,
                evidence=[EvidenceRef(type="html_excerpt", url=p.url, excerpt=f"aggregateRating/review on {t}")
                          for p, t in self_reviews[:5]],
                impact="Google doesn't show review snippets for businesses rating themselves, and it can be "
                       "treated as a policy violation.",
                fix="Remove self-served ratings, or source them from a third-party review platform.",
                verification="No aggregateRating on the business's own entity.", effort=Effort.S)]
        return [self.finding("S8.07", St.PASS, "No self-serving review markup")]
