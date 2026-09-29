"""Golden tests for S9 Local & Entity Consistency: planted NAP issues → exact check statuses."""

import json

from engine.agents.seo.s09_local import LocalConsistency, digits
from engine.collectors.c02_parser import parse_page
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St, EvidenceType
from engine.store import MemoryStore, PageRecord, SnapshotReader, SnapshotWriter
from engine.validation import validate_result

B = "https://www.grand.example"
PAGES = {
    f"{B}/agra": ("<h1>Grand Agra</h1><p>Grand Agra is 2 km from the Taj Mahal's East Gate, in Tajganj.</p>"
                  "<p>Call <a href='tel:9812345678'>98123 45678</a> or <a href='https://maps.google.com/?q=grand'>"
                  "get directions</a>.</p>"),
    f"{B}/contact": "<h1>Contact</h1><p>Reservations: <a href='tel:+919812345678'>+91 98123 45678</a></p>",
}


def fact(key, value, status, method="llm"):
    return {"key": key, "value": value, "quote": value, "source_url": f"{B}/agra", "status": status, "method": method}


def build(tmp_path, archetype="hospitality", places=None, facts=None):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    for i, (url, body) in enumerate(PAGES.items()):
        html = f"<!doctype html><html lang='en'><head><title>Grand Agra</title></head><body>{body}</body></html>"
        rec = snap.add_page(PageRecord(id=f"p{i}", snapshot_id="s", url=url, final_url=url, status=200))
        snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=rec.id,
                          blob_key=snap.put_blob(f"snapshots/s/pages/p{i}/parsed.json", json.dumps(parse_page(html, url))))
    snap.add_evidence("C4", EvidenceType.FACTS, {"facts": facts if facts is not None else [
        fact("property_name", "Grand Agra", "site-stated"), fact("city", "Agra", "site-stated"),
        fact("business_name", "Grand Ayodhya", "schema-declared", "jsonld:Hotel"),  # copied from another property
        fact("city", "Ayodhya", "schema-declared", "jsonld:Hotel"),
        fact("phone", "+91 9812345678", "schema-declared", "jsonld:Hotel"),
        fact("business_name", "Grand Hospitality Ltd", "schema-declared", "jsonld:Organization")]})
    snap.add_evidence("C3", EvidenceType.ARCHETYPE, {"archetype": archetype})
    snap.add_evidence("C12", EvidenceType.ENTITY_FOOTPRINT, {"part": "places", "match": places, "places": [places] if places else []})
    snap.add_evidence("C12", EvidenceType.ENTITY_FOOTPRINT, {"part": "kg", "knowledge_graph": None})
    raw = snap.put_blob("snapshots/s/serp/02.json", json.dumps({"serpapi": {"local_results": {"places": [
        {"title": "The Oberoi Amarvilas"}, {"title": "ITC Mughal"}]}}}))
    snap.add_evidence("C6", EvidenceType.SERP, {"query": "hotels near taj mahal", "features": {"paa": []}}, blob_key=raw)
    return SnapshotReader(store, blobs, "s"), store


def run(tmp_path, **kw):
    reader, store = build(tmp_path, **kw)
    agent = LocalConsistency()
    ctx = AgentContext(reader, ClientProfile(id="c", name="Grand Agra", primary_url=f"{B}/agra"), None, None)
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    result, errors = validate_result(agent, result, {p.final_url for p in store.pages.values()})
    assert errors == []
    return agent, result


def test_s9_finds_planted_nap_and_local_issues(tmp_path):
    agent, result = run(tmp_path, places={"title": "Grand Agra", "category": "Hotel", "rating": 4.3})
    assert check_statuses(agent, result.findings) == {
        "S9.01": St.FAIL,           # the Hotel schema names another property in another city
        "S9.02": St.WARN,           # no address or hours on the location page
        "S9.03": St.WARN,           # Maps listing has no website link
        "S9.04": St.WARN,           # a local pack without the business
        "S9.05": St.FAIL,           # no PIN code
        "S9.06": St.NOT_APPLICABLE,  # hotels don't state service areas
    }
    nap = next(f for f in result.findings if f.check_id == "S9.01")
    assert "names and addresses" in nap.title and "Organization" not in nap.title  # the parent company isn't compared
    rows = {r[0]: r for r in result.signature_table["rows"]}
    assert rows["schema (Hotel)"][2] == "Ayodhya" and rows["contact page"][3] == "9812345678"


def test_phone_formats_compare_equal_and_missing_maps_fails(tmp_path):
    assert digits("+91 98123 45678") == digits("098123-45678") == "9812345678"
    agent, result = run(tmp_path, places=None)
    assert check_statuses(agent, result.findings)["S9.03"] == St.FAIL


def test_an_online_shop_homepage_is_not_asked_for_an_address_or_hours(tmp_path):
    """Regression (Flipkart run, 2026-09-29): a retail homepage was told it lacked a PIN code, a map and
    check-in times. Location checks apply to hotel pages and to store, branch or office pages only."""
    agent, result = run(tmp_path, archetype="retail", places=None,
                        facts=[fact("business_name", "Grand Agra", "site-stated")])
    statuses = check_statuses(agent, result.findings)
    assert statuses["S9.02"] == statuses["S9.05"] == St.NOT_APPLICABLE
