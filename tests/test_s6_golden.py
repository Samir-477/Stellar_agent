"""Golden tests for S6 SERP Landscape & Competitors (benchmark): planted SERPs and competitor pages."""

import json

from engine.agents.seo.s06_serp_landscape import SerpLandscape, elements
from engine.collectors.c02_parser import parse_page
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St, EvidenceType
from engine.store import MemoryStore, PageRecord, SnapshotReader, SnapshotWriter
from engine.validation import validate_result

B = "https://www.grand.example"
RIVAL = ("<h1>{name}</h1><p>A 60-room hotel 500 m from the Taj Mahal. Rooms from ₹6,500 a night.</p>"
         "<p>Address: Fatehabad Road, Agra 282001.</p>" + "<p>More about our rooms and dining and views here.</p>" * 30
         + "<script type='application/ld+json'>{{\"@type\": \"Hotel\", \"aggregateRating\": {{\"ratingValue\": 4.5}}}}"
           "</script>")


def html(body, title="Page"):
    return f"<!doctype html><html lang='en'><head><title>{title}</title></head><body><main>{body}</main></body></html>"


def build(tmp_path):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    entry = html("<h1>Grand Agra</h1><p>Grand Agra is a 40-room hotel 1.4 km from the Taj Mahal.</p>", "Grand Agra")
    rec = snap.add_page(PageRecord(id="p0", snapshot_id="s", url=f"{B}/agra", final_url=f"{B}/agra", status=200))
    snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=rec.id,
                      blob_key=snap.put_blob("snapshots/s/pages/p0/parsed.json", json.dumps(parse_page(entry, rec.url))))
    snap.add_evidence("C6", EvidenceType.SERP, {"query": "hotels near taj mahal", "intent": "local",
                                                "client_position": None,
                                                "organic": [{"domain": "booking.com"}, {"domain": "rival-a.example"},
                                                            {"domain": "rival-b.example"}],
                                                "features": {"ai_overview": True, "paa": [{"question": "q"}]}})
    snap.add_evidence("C6", EvidenceType.SERP, {"query": "grand agra", "intent": "brand", "client_position": 1,
                                                "organic": [{"domain": "grand.example"}]})
    snap.add_evidence("C8", EvidenceType.COMPETITORS, {"domains": [
        {"domain": "booking.com", "type": "aggregator"}, {"domain": "rival-a.example", "type": "direct"},
        {"domain": "rival-b.example", "type": "direct"}, {"domain": "grand.example", "type": "client"}]})
    for i, name in enumerate(("Rival A", "Rival B")):
        url = f"https://rival-{'ab'[i]}.example/agra"
        key = snap.put_blob(f"snapshots/s/competitors/{i}.json", json.dumps(parse_page(html(RIVAL.format(name=name)), url)))
        snap.add_evidence("C8", EvidenceType.COMPETITOR_PAGES, {"domain": url.split("/")[2], "url": url,
                                                                 "query": "hotels near taj mahal", "position": i + 2},
                          blob_key=key)
    return SnapshotReader(store, blobs, "s"), store


def test_s6_benchmarks_against_top_competitor_pages(tmp_path):
    reader, store = build(tmp_path)
    agent = SerpLandscape()
    ctx = AgentContext(reader, ClientProfile(id="c", name="Grand", primary_url=f"{B}/agra"), None, None)
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    result, errors = validate_result(agent, result, {f"{B}/agra"})
    assert errors == []
    assert check_statuses(agent, result.findings) == {
        "S6.01": St.WARN,  # not in the top 10 for the one non-brand search
        "S6.02": St.PASS,  # 2 direct competitors, 1 aggregator
        "S6.03": St.PASS,  # AI Overview on 1 of 1
        "S6.04": St.WARN,  # both rivals show prices, a PIN-code address and ratings in schema
        "S6.05": St.WARN,  # the entry page is much shorter
    }
    gaps = next(f for f in result.findings if f.check_id == "S6.04").title
    assert all(g in gaps for g in ("prices in the text", "address with PIN code", "ratings in structured data"))
    assert not agent.counts_toward_readiness and all(not c.counts_toward_readiness for c in agent.checks)


def test_elements_are_read_from_text_and_schema():
    model = parse_page(html(RIVAL.format(name="Rival")), "https://rival.example/")
    assert {"prices in the text", "address with PIN code", "ratings in structured data", "schema: Hotel"} <= elements(model)
