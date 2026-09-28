"""C12 Entity Footprint: each part once, matches by name/website, no repeat spending."""

import json

import httpx

from engine.collectors.c12_entity import EntityFootprint, organisation_name
from engine.lib.names import names_match
from engine.context import ClientProfile, CollectorContext, WorkUnit
from engine.core.blobstore import LocalBlobStore
from engine.schemas import EvidenceType
from engine.store import MemoryStore, SnapshotWriter

B = "https://www.grand.example"


class FakeSearch:
    def __init__(self):
        self.calls = []

    def organic(self, query, num=10):
        self.calls.append(("organic", query))
        if "tripadvisor" in query:
            return {"organic": [{"title": "GRAND AGRA - Updated 2026 Prices", "link": "https://tripadvisor.in/h1"}]}
        return {"organic": [{"title": "Hotels in Agra - Best Price", "link": "https://booking.com/agra"}]}

    def places(self, query):
        self.calls.append(("places", query))
        return [{"title": "Grand Agra", "address": "Tajganj, Agra 282001", "phoneNumber": "098123 45678",
                 "category": "Hotel", "rating": 4.3, "website": f"{B}/agra"}]

    def google_features(self, query):
        self.calls.append(("serpapi", query))
        return {"knowledge_graph": {"title": "Grand Agra", "type": "Hotel"}}


def wikidata(request: httpx.Request) -> httpx.Response:
    params = dict(request.url.params)
    if params["action"] == "wbsearchentities":
        return httpx.Response(200, json={"search": [{"id": "Q1"}, {"id": "Q2"}]})
    return httpx.Response(200, json={"entities": {
        "Q1": {"labels": {"en": {"value": "Grand Hospitality"}}, "descriptions": {"en": {"value": "hotel chain"}},
               "claims": {"P856": [{"mainsnak": {"datavalue": {"value": "https://grand.example"}}}]},
               "sitelinks": {"enwiki": {"title": "Grand Hospitality"}}},
        "Q2": {"labels": {"en": {"value": "Grand Canyon"}}, "claims": {}}}})


def build(settings, tmp_path, search):
    snap = SnapshotWriter(MemoryStore(), LocalBlobStore(tmp_path / "b"), "s")
    snap.add_evidence("C4", EvidenceType.FACTS, {"facts": [
        {"key": "property_name", "value": "Grand Agra", "status": "site-stated"},
        {"key": "business_name", "value": "Grand Hospitality Limited", "status": "site-stated"},
        {"key": "city", "value": "Agra", "status": "site-stated"}]})
    snap.add_evidence("C3", EvidenceType.ARCHETYPE, {"archetype": "hospitality"})
    snap.add_evidence("C5", EvidenceType.QUERY_SET, {"queries": [{"q": "grand agra", "intent": "brand"}]})
    raw = snap.put_blob("snapshots/s/serp/01.json", json.dumps({"serpapi": {"knowledge_graph": None}}))
    snap.add_evidence("C6", EvidenceType.SERP, {"query": "grand agra", "features": {"paa": []}}, blob_key=raw)
    ctx = CollectorContext(snap, ClientProfile(id="c", name="Grand", primary_url=f"{B}/agra"),
                           settings.model_copy(update={"wikimedia_contact": "ops@grand.example"}),
                           http_transport=httpx.MockTransport(wikidata), search=search)
    return ctx, snap


def test_c12_parts_run_once_and_match_the_business(settings, tmp_path):
    search = FakeSearch()
    ctx, snap = build(settings, tmp_path, search)
    collector = EntityFootprint()
    for unit in collector.plan(ctx) * 2:  # every unit twice: a retry must not repeat a search
        collector.run_unit(ctx, unit)
    parts = {e.payload["part"]: e.payload for e in snap.evidence(EvidenceType.ENTITY_FOOTPRINT)}
    assert set(parts) == {"wiki", "platforms", "places", "kg"} and len(snap.evidence(EvidenceType.ENTITY_FOOTPRINT)) == 4
    matched = [e for e in parts["wiki"]["entities"] if e["match"]]
    assert [(e["id"], e["match"], e["wikipedia"]) for e in matched] == [("Q1", "official website", "Grand Hospitality")]
    found = {p["platform"]: p["found"] for p in parts["platforms"]["platforms"]}
    assert found["tripadvisor.in"] and not found["booking.com"]
    assert parts["places"]["match"]["category"] == "Hotel"
    assert parts["kg"] == {"part": "kg", "name": "Grand Agra", "city": "Agra", "query": "grand agra",
                           "source": "C6 capture", "knowledge_graph": None}  # no panel, and no SerpAPI spend
    assert not any(kind == "serpapi" for kind, _ in search.calls)
    assert len([c for c in search.calls if c[0] == "organic"]) == 5  # one per pack platform, once


def test_name_helpers():
    assert names_match("Sterling Regalia Agra", "STERLING REGALIA AGRA - 2026 Reviews")
    assert not names_match("Sterling Regalia Agra", "Hotels in Agra")
    snap = SnapshotWriter(MemoryStore(), LocalBlobStore("."), "x")
    snap.add_evidence("C4", EvidenceType.FACTS, {"facts": [
        {"key": "property_name", "value": "Grand Agra", "status": "site-stated"},
        {"key": "business_name", "value": "Grand Hospitality Pvt. Ltd.", "status": "site-stated"}]})
    ctx = CollectorContext(snap, ClientProfile(id="c", name="G", primary_url=B), None)
    assert organisation_name(ctx) == "Grand Hospitality"


def test_wikidata_is_skipped_without_a_contact(settings, tmp_path):
    ctx, snap = build(settings, tmp_path, FakeSearch())
    ctx.settings = settings  # no WIKIMEDIA_CONTACT
    EntityFootprint().run_unit(ctx, WorkUnit("wiki"))
    assert "WIKIMEDIA_CONTACT" in snap.evidence(EvidenceType.ENTITY_FOOTPRINT)[0].payload["skipped"]
    ctx.settings = settings.model_copy(update={"wikimedia_contact": "ops@grand.example"})
    EntityFootprint().run_unit(ctx, WorkUnit("wiki"))  # configured later: the skipped part runs
    latest = snap.evidence(EvidenceType.ENTITY_FOOTPRINT)[-1].payload
    assert "skipped" not in latest and latest["entities"]


def test_platforms_seen_in_the_brand_search_cost_nothing(settings, tmp_path):
    search = FakeSearch()
    ctx, snap = build(settings, tmp_path, search)
    snap.add_evidence("C6", EvidenceType.SERP, {"query": "grand agra", "intent": "brand", "organic": [
        {"title": "Grand Agra, Agra (updated prices 2026)", "link": "https://www.booking.com/hotel/in/grand-agra.html"},
        {"title": "GRAND AGRA - 2026 Reviews", "link": "https://www.tripadvisor.com/Hotel_Review-grand"}]})
    EntityFootprint().run_unit(ctx, WorkUnit("platforms"))
    rows = {p["platform"]: p for p in snap.evidence(EvidenceType.ENTITY_FOOTPRINT)[-1].payload["platforms"]}
    assert rows["booking.com"]["found"] and rows["booking.com"]["query"] == "C6 brand search"
    assert rows["tripadvisor.in"]["found"]  # the .com listing counts for the platform
    searched = [q for kind, q in search.calls if kind == "organic"]
    assert not any("booking" in q or "tripadvisor" in q for q in searched) and len(searched) == 3
