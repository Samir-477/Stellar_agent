"""C12 Entity Footprint: how the business exists off its own site, the places AI systems and Google
learn about it from. Four independent parts (one work unit each, so a retry never re-buys a search):

- wiki: Wikidata entity search (free) for the organisation and the property, matched by official
  website; the English Wikipedia article linked from a matched entity.
- platforms: Serper `site:` searches on the archetype pack's core platforms (at most 6 calls).
- places: Serper Places (Google Maps) for the business in its city (1 call).
- kg: the Google Knowledge Graph panel for the brand query, reused from C6's SerpAPI capture; one
  SerpAPI call only if C6 didn't capture that query.
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urlsplit

from engine.collectors.base import Collector
from engine.collectors.search_collectors import _archetype, _facts, business_name
from engine.context import CollectorContext, WorkUnit
from engine.integrations.search import BudgetExhausted, SearchError
from engine.lib.grounding import normalize
from engine.lib.names import names_match
from engine.lib.urls import site_label
from engine.rules.packs import pack
from engine.schemas import EvidenceType

WIKIDATA = "https://www.wikidata.org/w/api.php"
MAX_PLATFORMS = 6
PARTS = ("wiki", "platforms", "places", "kg")


def _domain(url: str | None) -> str:
    return (urlsplit(url or "").hostname or "").removeprefix("www.")


def organisation_name(ctx: CollectorContext) -> str | None:
    """The company behind the property, when the site states it ("Sterling Holiday Resorts Limited")."""
    prop = business_name(ctx)
    names = [n for n in _facts(ctx).get("business_name", []) if normalize(n) != normalize(prop)]
    return re.sub(r"\s+(limited|ltd\.?|pvt\.? ltd\.?|private limited)$", "", names[0], flags=re.I) if names else None


class EntityFootprint(Collector):
    id = "C12"
    name = "Entity Footprint"
    produces = frozenset({EvidenceType.ENTITY_FOOTPRINT})
    requires = frozenset({EvidenceType.FACTS, EvidenceType.ARCHETYPE, EvidenceType.SERP, EvidenceType.QUERY_SET})

    def plan(self, ctx: CollectorContext) -> list[WorkUnit]:
        return [WorkUnit(part) for part in PARTS]

    def run_unit(self, ctx: CollectorContext, unit: WorkUnit) -> list[WorkUnit]:
        # Done in an earlier attempt, unless it was skipped for missing configuration (the latest row wins).
        if any(e.payload.get("part") == unit.kind and not e.payload.get("skipped")
               for e in ctx.snapshot.evidence(EvidenceType.ENTITY_FOOTPRINT)):
            return []
        name, city = business_name(ctx), (_facts(ctx).get("city") or [""])[0]
        payload = {"part": unit.kind, "name": name, "city": city}
        if unit.kind == "wiki" and not ctx.settings.wikimedia_contact:
            payload["skipped"] = ("Wikidata not checked: Wikimedia requires contact details in the User-Agent; "
                                  "set WIKIMEDIA_CONTACT (an email or URL) and refresh C12.")
        elif unit.kind == "wiki":
            payload.update(asyncio.run(self._wiki(ctx, name)))
        elif ctx.search is None:
            payload["error"] = "no search client configured"
        else:
            try:
                payload.update(getattr(self, f"_{unit.kind}")(ctx, name, city))
            except BudgetExhausted as exc:
                payload["error"] = str(exc)
            except SearchError as exc:
                raise RuntimeError(str(exc)) from exc  # transient: let the queue retry
        ctx.snapshot.add_evidence(self.id, EvidenceType.ENTITY_FOOTPRINT, payload, source_label="observed")
        return []

    # ------------------------------------------------------------ parts

    async def _wiki(self, ctx: CollectorContext, name: str) -> dict:
        domain = _domain(ctx.client.primary_url)
        headers = {"User-Agent": f"SiteDiagnosis/0.1 ({ctx.settings.wikimedia_contact}) python-httpx"}
        out: dict = {"entities": []}
        async with ctx.http_client() as client:
            for query in dict.fromkeys(n for n in (organisation_name(ctx), name) if n):
                try:
                    found = (await client.get(WIKIDATA, headers=headers, params={
                        "action": "wbsearchentities", "search": query, "language": "en", "format": "json",
                        "type": "item", "limit": 5})).json().get("search", [])
                    seen = {e["id"] for e in out["entities"]}
                    ids = [f["id"] for f in found if f["id"] not in seen]  # both searches can find one entity
                    entities = (await client.get(WIKIDATA, headers=headers, params={
                        "action": "wbgetentities", "ids": "|".join(ids), "format": "json", "languages": "en",
                        "props": "labels|descriptions|claims|sitelinks"})).json().get("entities", {}) if ids else {}
                except Exception as exc:  # noqa: BLE001 - a Wikimedia hiccup must not fail the run
                    out.setdefault("errors", []).append(f"{query}: {type(exc).__name__}")
                    continue
                for qid in ids:
                    e = entities.get(qid) or {}
                    sites = [(c.get("mainsnak", {}).get("datavalue") or {}).get("value")
                             for c in (e.get("claims") or {}).get("P856", [])]
                    label = ((e.get("labels") or {}).get("en") or {}).get("value", "")
                    inception = [((c.get("mainsnak", {}).get("datavalue") or {}).get("value") or {}).get("time")
                                 for c in (e.get("claims") or {}).get("P571", [])]
                    reason = ("official website" if any(_domain(s) == domain for s in sites if isinstance(s, str))
                              else "label" if normalize(label) == normalize(query) else None)
                    out["entities"].append({
                        "query": query, "id": qid, "label": label,
                        "description": ((e.get("descriptions") or {}).get("en") or {}).get("value"),
                        "websites": [s for s in sites if isinstance(s, str)], "inception": [t for t in inception if t],
                        "wikipedia": ((e.get("sitelinks") or {}).get("enwiki") or {}).get("title"), "match": reason})
        return out

    def _platforms(self, ctx: CollectorContext, name: str, city: str) -> dict:
        """A listing counts on any of the platform's domains (tripadvisor.in or .com). The brand search C6
        already captured is checked first; only platforms missing from it cost a search."""
        the_pack = pack(_archetype(ctx))
        seen = [r for ev in ctx.snapshot.evidence(EvidenceType.SERP)
                if ev.payload.get("intent") == "brand" for r in ev.payload.get("organic") or []]
        results = []
        for platform in (the_pack.platforms if the_pack else ())[:MAX_PLATFORMS]:
            label = site_label(platform)

            def listed(rows: list[dict]) -> dict | None:
                return next((r for r in rows if site_label(_domain(r.get("link"))) == label
                             and names_match(name, r.get("title"))), None)

            hit, query = listed(seen), "C6 brand search"
            organic: list[dict] = []
            if hit is None:
                query = f"{name} {city} {label}".strip()
                organic = ctx.search.organic(query, num=10).get("organic", [])
                hit = listed(organic)
            results.append({"platform": platform, "query": query, "found": hit is not None,
                            "url": (hit or {}).get("link"), "title": (hit or {}).get("title"),
                            "snippet": ((hit or {}).get("snippet") or "")[:300],
                            "top": [{"title": r.get("title"), "link": r.get("link")} for r in organic[:3]]})
        return {"platforms": results}

    def _places(self, ctx: CollectorContext, name: str, city: str) -> dict:
        places = ctx.search.places(f"{name} {city}".strip())
        keep = ("title", "address", "phoneNumber", "category", "rating", "ratingCount", "website", "cid",
                "latitude", "longitude")
        listed = [{k: p.get(k) for k in keep if p.get(k) is not None} for p in places[:3]]
        match = next((p for p in listed if names_match(name, p.get("title"))), None)
        return {"places": listed, "match": match}

    def _kg(self, ctx: CollectorContext, name: str, city: str) -> dict:
        queries = (ctx.snapshot.evidence(EvidenceType.QUERY_SET) or [None])[-1]
        brand = next((q["q"] for q in (queries.payload.get("queries", []) if queries else [])
                      if q["intent"] == "brand"), name.lower())
        for ev in reversed(ctx.snapshot.evidence(EvidenceType.SERP)):
            if ev.payload.get("query") == brand and ev.payload.get("features") and ev.blob_key:
                raw = (ctx.snapshot.blob_json(ev.blob_key) or {}).get("serpapi") or {}
                return {"query": brand, "source": "C6 capture", "knowledge_graph": _kg_summary(raw)}
        raw = ctx.search.google_features(brand)
        return {"query": brand, "source": "SerpAPI", "knowledge_graph": _kg_summary(raw)}


def _kg_summary(raw: dict) -> dict | None:
    kg = raw.get("knowledge_graph")
    if not kg:
        return None
    keep = ("title", "type", "description", "address", "phone", "website", "rating", "review_count", "hours")
    return {k: kg[k] for k in keep if kg.get(k) not in (None, "", [])}
