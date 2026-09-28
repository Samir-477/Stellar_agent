"""Golden tests for G6 Off-site Entity Footprint: planted footprint → exact check statuses."""

import json

from engine.agents.geo.g06_entity_footprint import OffsiteEntityFootprint
from engine.collectors.c02_parser import parse_page
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St, EvidenceType
from engine.store import MemoryStore, PageRecord, SnapshotReader, SnapshotWriter
from engine.validation import validate_result

B = "https://www.grand.example"


def page(url, same_as):
    ld = json.dumps({"@type": "Hotel", "name": "Grand Agra", "sameAs": same_as})
    return (f"<!doctype html><html lang='en'><head><title>Grand Agra</title>"
            f"<script type='application/ld+json'>{ld}</script></head><body><h1>Grand Agra</h1></body></html>")


def build(tmp_path, wiki):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    pages = {f"{B}/": page(f"{B}/", ["https://www.facebook.com/grandhotels"]),
             f"{B}/agra": page(f"{B}/agra", ["https://facebook.com/grandagra/", "https://www.facebook.com/grandhotels"])}
    for i, (url, html) in enumerate(pages.items()):
        rec = snap.add_page(PageRecord(id=f"p{i}", snapshot_id="s", url=url, final_url=url, status=200))
        snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=rec.id,
                          blob_key=snap.put_blob(f"snapshots/s/pages/p{i}/parsed.json", json.dumps(parse_page(html, url))))
    snap.add_evidence("C12", EvidenceType.ENTITY_FOOTPRINT, {"part": "kg", "query": "grand agra", "source": "C6 capture",
                                                             "knowledge_graph": None})
    snap.add_evidence("C12", EvidenceType.ENTITY_FOOTPRINT, {"part": "wiki", **wiki})
    snap.add_evidence("C12", EvidenceType.ENTITY_FOOTPRINT, {"part": "platforms", "platforms": [
        {"platform": "tripadvisor.in", "found": True, "url": "https://www.tripadvisor.com/grand", "title": "GRAND AGRA"},
        {"platform": "booking.com", "found": False, "url": None, "title": None}]})
    snap.add_evidence("C6", EvidenceType.SERP, {"query": "grand agra", "intent": "brand", "organic": [
        {"link": "https://www.mouthshut.com/grand-agra", "domain": "mouthshut.com",
         "title": "Grand Agra reviews: worst stay, refund not given"}]})
    return SnapshotReader(store, blobs, "s"), store


def run(tmp_path, wiki):
    reader, store = build(tmp_path, wiki)
    agent = OffsiteEntityFootprint()
    ctx = AgentContext(reader, ClientProfile(id="c", name="Grand Agra", primary_url=f"{B}/agra"), None, None)
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    result, errors = validate_result(agent, result, {p.final_url for p in store.pages.values()})
    assert errors == []
    return agent, result


def test_g6_finds_planted_footprint_issues(tmp_path):
    wiki = {"entities": [{"query": "Grand Hospitality", "id": "Q1", "label": "Grand Hospitality",
                          "websites": ["https://grand-old.example"], "match": "label"}]}
    agent, result = run(tmp_path, wiki)
    assert check_statuses(agent, result.findings) == {
        "G6.01": St.FAIL,  # no knowledge panel
        "G6.02": St.FAIL,  # Wikidata lists another website
        "G6.03": St.WARN,  # 1 of 2 platforms
        "G6.04": St.FAIL,  # two Facebook profiles in sameAs
        "G6.05": St.WARN,  # a complaint thread in the brand results
    }
    same = next(f for f in result.findings if f.check_id == "G6.04")
    assert "facebook.com/grandagra" in same.evidence[0].excerpt and "facebook.com/grandhotels" in same.evidence[0].excerpt


def test_g6_wikidata_unverifiable_without_contact(tmp_path):
    agent, result = run(tmp_path, {"skipped": "Wikidata not checked: set WIKIMEDIA_CONTACT"})
    assert check_statuses(agent, result.findings)["G6.02"] == St.UNVERIFIABLE
    assert any("WIKIMEDIA_CONTACT" in s for s in result.coverage.skipped)
