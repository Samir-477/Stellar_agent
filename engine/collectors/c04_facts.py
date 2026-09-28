"""C4 Fact Sheet: business facts with their source, each backed by an exact quote.

1. Deterministic: tel:/mailto: links (status "site-stated"), and JSON-LD properties
   of business entities only (status "schema-declared": schema can be wrong, e.g.
   copied from another property's page, so it is a claim for S8 to verify, never
   ground truth).
2. LLM (fast tier, one call): the entry page, contact/about pages and homepage.
   Every LLM fact must quote the page word for word; facts whose quote isn't on
   the page are rejected (counted in stats so prompt quality can be tracked).
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from engine.collectors.base import Collector
from engine.collectors.common import parsed_models
from engine.context import CollectorContext, WorkUnit
from engine.lib.grounding import normalize, quote_in_text, value_supported
from engine.lib.jsonld import types_of
from engine.llm import LLMError, load_prompt
from engine.schemas import EvidenceType

MAX_LLM_PAGES = 3
MAX_WORDS_PER_PAGE = 1000
_JSONLD_KEYS = {"name": "business_name", "telephone": "phone", "email": "email", "sameAs": "social_profiles",
                "priceRange": "price_from", "checkinTime": "check_in_time", "checkoutTime": "check_out_time",
                "numberOfRooms": "room_count", "foundingDate": "founded_year", "legalName": "legal_name"}


class ExtractedFact(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    value: str = Field(min_length=1, max_length=500)
    quote: str = Field(min_length=3, max_length=400)
    url: str


class FactsAnswer(BaseModel):
    facts: list[ExtractedFact] = Field(default_factory=list, max_length=60)


BUSINESS_TYPES = {"Organization", "Corporation", "LocalBusiness", "Hotel", "LodgingBusiness", "Resort",
                  "Motel", "Hostel", "BedAndBreakfast", "Restaurant", "FinancialService", "BankOrCreditUnion",
                  "Store", "OnlineStore", "OnlineBusiness", "MovingCompany", "ProfessionalService"}


def jsonld_facts(model: dict) -> list[dict]:
    """Facts declared by business-entity JSON-LD nodes (not WebPage, BreadcrumbList, amenities...)."""
    facts = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        entity_types = types_of(node) & BUSINESS_TYPES
        if entity_types:
            entity = sorted(entity_types)[0]

            def add(key, value, raw):
                if value not in (None, "", []):
                    text = "; ".join(map(str, value)) if isinstance(value, list) else str(value)
                    facts.append({"key": key, "value": text, "quote": raw[:200], "source_url": model["url"],
                                  "method": f"jsonld:{entity}", "status": "schema-declared"})

            for prop, key in _JSONLD_KEYS.items():
                if prop in node and isinstance(node[prop], (str, int, float, list)):
                    add(key, node[prop], json.dumps({prop: node[prop]}, ensure_ascii=False))
            address = node.get("address")
            if isinstance(address, dict):
                parts = [address.get(k) for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode")]
                add("address", ", ".join(str(p) for p in parts if p), json.dumps(address, ensure_ascii=False))
                add("city", address.get("addressLocality"), json.dumps(address, ensure_ascii=False))
            rating = node.get("starRating")
            if isinstance(rating, dict):
                add("star_rating", rating.get("ratingValue"), json.dumps(rating, ensure_ascii=False))
        for value in node.values():
            if isinstance(value, (dict, list)):
                walk(value)

    for block in model.get("jsonld", []):
        walk(block.get("parsed"))
    return facts


def link_facts(model: dict) -> list[dict]:
    return [{"key": "phone" if c["type"] == "tel" else "email", "value": c["value"],
             "quote": f"{c['type']}:{c['value']}", "source_url": model["url"], "method": "link",
             "status": "site-stated"}
            for c in model.get("contacts", []) if c["value"]]


def page_text(model: dict) -> str:
    """H1s + passages, minus unfilled template placeholders like {{item.name}}."""
    parts = [h["text"] for h in model.get("headings", []) if h["level"] <= 3]
    parts += [p["text"] for p in model.get("passages", []) if "{{" not in p["text"]]
    words = " \n".join(parts).split(" ")
    return " ".join(words[:MAX_WORDS_PER_PAGE])


def pick_llm_pages(models: list[dict], entry_url: str) -> list[dict]:
    entry = entry_url.rstrip("/")
    chosen = [m for m in models if m["url"].rstrip("/") == entry][:1]
    for model in models:
        path = urlsplit(model["url"]).path.lower()
        if model not in chosen and any(k in path for k in ("contact", "about")):
            chosen.append(model)
    home = next((m for m in models if urlsplit(m["url"]).path in ("", "/")), None)
    if home and home not in chosen:
        chosen.append(home)
    return chosen[:MAX_LLM_PAGES]


def dedupe(facts: list[dict]) -> list[dict]:
    seen: dict[tuple[str, str, str], dict] = {}
    for fact in facts:
        key = (fact["key"], normalize(fact["value"]), fact["status"])
        if key not in seen:
            seen[key] = fact
    ordered = sorted(seen.values(), key=lambda f: (f["key"], f["source_url"]))
    for index, fact in enumerate(ordered, start=1):
        fact["id"] = f"F-{index:03d}"
    return ordered


class FactSheet(Collector):
    id = "C4"
    name = "Fact Sheet"
    produces = frozenset({EvidenceType.FACTS})
    requires = frozenset({EvidenceType.PAGES_PARSED, EvidenceType.ARCHETYPE})

    def plan(self, ctx: CollectorContext) -> list[WorkUnit]:
        return [WorkUnit("extract")]

    def run_unit(self, ctx: CollectorContext, unit: WorkUnit) -> list[WorkUnit]:
        models = parsed_models(ctx)
        pages = pick_llm_pages(models, ctx.client.primary_url)
        facts = [f for m in pages for f in jsonld_facts(m) + link_facts(m)]
        stats = {"deterministic": len(facts), "llm_proposed": 0, "llm_rejected": 0, "llm_error": None}

        archetype = (ctx.snapshot.evidence(EvidenceType.ARCHETYPE) or [None])[-1]
        archetype_name = archetype.payload["archetype"] if archetype else "other"
        texts = {m["url"]: page_text(m) for m in pages}
        if ctx.llm is not None and texts:
            data = "\n\n".join(f"PAGE: {url}\n{text}" for url, text in texts.items())
            try:
                answer = ctx.llm.complete_json(load_prompt("c4.facts", 2), FactsAnswer,
                                               archetype=archetype_name, pages=data).data
                stats["llm_proposed"] = len(answer.facts)
                for fact in answer.facts:
                    source = texts.get(fact.url) or data
                    if not quote_in_text(fact.quote, source):
                        stats["llm_rejected"] += 1
                    elif not value_supported(fact.value, fact.quote):
                        stats["llm_unsupported"] = stats.get("llm_unsupported", 0) + 1
                    else:
                        facts.append({"key": fact.key, "value": fact.value, "quote": fact.quote,
                                      "source_url": fact.url if fact.url in texts else pages[0]["url"],
                                      "method": "llm", "status": "site-stated"})
            except LLMError as exc:
                stats["llm_error"] = str(exc)
        facts = dedupe(facts)
        ctx.snapshot.add_evidence(self.id, EvidenceType.FACTS,
                                  {"facts": facts, "stats": stats, "pages_read": list(texts)},
                                  source_label="site-stated")
        return []
