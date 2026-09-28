from engine.collectors.c02_parser import parse_page
from engine.collectors.c03_archetype import ArchetypeDetector, AwaitingConfirmation
from engine.collectors.c04_facts import FactSheet, jsonld_facts
from engine.context import ClientProfile, CollectorContext, WorkUnit
from engine.core.blobstore import LocalBlobStore
from engine.lib.grounding import quote_in_text, value_supported
from engine.schemas import EvidenceType
from engine.store import MemoryStore, PageRecord, SnapshotWriter
import json
import pytest
from tests.conftest import FakeLLM

URL = "https://hotel.example/stay/agra"
PAGE = f"""<!doctype html><html lang="en"><head><title>Regal Stay Agra</title>
<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", "@graph": [
    {"@type": "WebPage", "name": "Regal Stay Agra – Book now"},
    {"@type": "Hotel", "name": "Regal Stay Ayodhya", "telephone": "+91 11111 22222",
     "address": {"@type": "PostalAddress", "addressLocality": "Ayodhya"},
     "amenityFeature": [{"@type": "LocationFeatureSpecification", "name": "Free Wi-Fi"}]}]})}</script>
</head><body><h1>Regal Stay Agra</h1><p>Regal Stay Agra has 36 rooms and is 1.4 km from the Taj Mahal.</p>
<p>Rooms come in three categories for families and couples.</p></body></html>"""


def make_ctx(settings, tmp_path, llm, archetype=None):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s1")
    page = snap.add_page(PageRecord(id="p1", snapshot_id="s1", url=URL, final_url=URL, status=200))
    key = snap.put_blob("snapshots/s1/pages/p1/parsed.json", json.dumps(parse_page(PAGE, URL)))
    snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=page.id, blob_key=key)
    return CollectorContext(snap, ClientProfile(id="c", name="Regal", primary_url=URL, archetype=archetype),
                            settings, llm)


def test_grounding_helpers():
    assert quote_in_text("1.4 KM from the  Taj", "It is 1.4 km from the Taj Mahal.")
    assert not quote_in_text("2 km from the Taj", "It is 1.4 km from the Taj Mahal.")
    assert value_supported("36", "has 36 rooms")
    assert not value_supported("Standard; Deluxe; Junior Suite", "Rooms come in three categories")
    assert not value_supported("40 rooms", "has 36 rooms")


def test_jsonld_facts_only_from_business_entities_and_marked_schema_declared():
    facts = jsonld_facts(parse_page(PAGE, URL))
    names = {f["value"] for f in facts if f["key"] == "business_name"}
    assert names == {"Regal Stay Ayodhya"}  # not the WebPage name, not "Free Wi-Fi"
    assert all(f["status"] == "schema-declared" and f["method"] == "jsonld:Hotel" for f in facts)


def test_c4_keeps_only_grounded_and_supported_llm_facts(settings, tmp_path):
    llm = FakeLLM({"c4.facts": {"facts": [
        {"key": "room_count", "value": "36", "quote": "Regal Stay Agra has 36 rooms", "url": URL},
        {"key": "pool", "value": "rooftop pool", "quote": "a rooftop pool with Taj views", "url": URL},  # not on page
        {"key": "room_types", "value": "Standard; Deluxe", "quote": "Rooms come in three categories", "url": URL},
    ]}})
    ctx = make_ctx(settings, tmp_path, llm, archetype="hospitality")
    ArchetypeDetector().run_unit(ctx, WorkUnit("detect"))
    FactSheet().run_unit(ctx, WorkUnit("extract"))
    payload = ctx.snapshot.evidence(EvidenceType.FACTS)[-1].payload
    stated = [f for f in payload["facts"] if f["status"] == "site-stated"]
    assert [(f["key"], f["value"]) for f in stated] == [("room_count", "36")]
    assert payload["stats"]["llm_rejected"] == 1 and payload["stats"]["llm_unsupported"] == 1


def test_c3_uses_team_archetype_without_llm(settings, tmp_path):
    llm = FakeLLM({})
    ctx = make_ctx(settings, tmp_path, llm, archetype="loans")
    ArchetypeDetector().run_unit(ctx, WorkUnit("detect"))
    assert ctx.snapshot.evidence(EvidenceType.ARCHETYPE)[-1].payload["source"] == "team" and llm.calls == []


def test_c3_low_confidence_llm_answer_pauses_for_confirmation(settings, tmp_path):
    llm = FakeLLM({"c3.archetype": {"archetype": "hospitality", "secondary": None, "confidence": 0.6,
                                    "evidence": ["Regal Stay Agra"]}})
    ctx = make_ctx(settings, tmp_path, llm)
    with pytest.raises(AwaitingConfirmation):
        ArchetypeDetector().run_unit(ctx, WorkUnit("detect"))
    assert ctx.snapshot.evidence(EvidenceType.ARCHETYPE)[-1].payload["source"] == "llm"


def test_c3_ungrounded_llm_evidence_caps_confidence(settings, tmp_path):
    llm = FakeLLM({"c3.archetype": {"archetype": "hospitality", "secondary": None, "confidence": 0.99,
                                    "evidence": ["Five-star beach resort in Goa"]}})
    ctx = make_ctx(settings, tmp_path, llm)
    with pytest.raises(AwaitingConfirmation) as gate:
        ArchetypeDetector().run_unit(ctx, WorkUnit("detect"))
    assert gate.value.proposal["confidence"] == 0.5
