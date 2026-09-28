"""Golden test for S7 Internal Linking: planted issues → exact check statuses."""

import json

from engine.agents.seo.s07_internal_linking import InternalLinking, phrases
from engine.collectors.c02_parser import parse_page
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St, EvidenceType
from engine.store import MemoryStore, PageRecord, SnapshotReader, SnapshotWriter
from engine.validation import validate_result
from tests.conftest import FakeLLM

B = "https://grand.example"
NAV = f'<header><nav><a href="{B}/rooms">Rooms</a><a href="{B}/dining">Dining</a></nav></header>'


def doc(title, h1, body):
    return (f"<!doctype html><html lang='en'><head><title>{title}</title></head><body>{NAV}<main><h1>{h1}</h1>"
            f"{body}</main><footer>© Grand</footer></body></html>")


PAGES = {
    f"{B}/": doc("Grand Hotels", "Welcome to Grand Hotels",
                 f'<p>Plan your stay with us. <a href="{B}/old-offer">Know more</a></p>'
                 f'<p><a href="{B}/gallery"><img src="/g.jpg"></a> Photos of the property and grounds.</p>'),
    f"{B}/rooms": doc("Deluxe Rooms | Grand Hotels", "Deluxe Rooms",
                      f"<p>Every deluxe room has a balcony. After a long day, head up to the rooftop dining area for "
                      f"dinner with a view of the river.</p><p>See our <a href='{B}/offers'>current room offers</a>.</p>"),
    f"{B}/dining": doc("Rooftop Dining | Grand Hotels", "Rooftop Dining",
                       f"<p>The rooftop dining area serves North Indian food. Guests staying in our "
                       f"<a href='{B}/rooms'>deluxe rooms</a> get priority seating.</p>"),
    f"{B}/offers": doc("Offers | Grand Hotels", "Room offers", "<p>Save 10% on stays of three nights or more.</p>"),
    f"{B}/gallery": doc("Gallery | Grand Hotels", "Gallery", "<p>Pictures of the rooms, pool and restaurant.</p>"),
    f"{B}/agra": doc("Grand Agra | Grand Hotels", "Grand Agra near the Taj",
                     f"<p>Grand Agra is 2 km from the Taj Mahal, with <a href='{B}/rooms'>deluxe rooms</a>.</p>"),
}


def build(tmp_path):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    records = [(u, u, {}) for u in PAGES]
    records.append((f"{B}/old-offer", f"{B}/offers",
                    {"redirects": [{"url": f"{B}/old-offer", "status": 301, "location": f"{B}/offers"}]}))
    for i, (url, final, fetch) in enumerate(records):
        page = snap.add_page(PageRecord(id=f"p{i}", snapshot_id="s", url=url, final_url=final, status=200, fetch=fetch))
        key = snap.put_blob(f"snapshots/s/pages/p{i}/parsed.json", json.dumps(parse_page(PAGES[final], final)))
        snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=page.id, blob_key=key)
    snap.add_evidence("C1", EvidenceType.SITE_FILES, {"kind": "sample", "sitemap_url_count": 8})
    return store, blobs


def test_s7_finds_planted_linking_issues(tmp_path):
    store, blobs = build(tmp_path)
    llm = FakeLLM({"s7.links": lambda v: {"links": [
        {"id": f"L{i}", "useful": "rooftop dining" in block, "anchor": "rooftop dining area" if "rooftop dining" in block
         else None} for i, block in enumerate(v["candidates"].split("CANDIDATE ")[1:], start=1)]}})
    agent = InternalLinking()
    ctx = AgentContext(SnapshotReader(store, blobs, "s"), ClientProfile(id="c", name="x", primary_url=f"{B}/agra"),
                       None, llm)
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    result, errors = validate_result(agent, result, {p.final_url for p in store.pages.values()})
    assert errors == []
    assert check_statuses(agent, result.findings) == {
        "S7.01": St.WARN,   # /agra (the entry page) has no inlinks in the sample
        "S7.02": St.PASS,   # nav pages are 1 click from home
        "S7.03": St.FAIL,   # /agra isn't in the nav and has no body inlinks
        "S7.04": St.WARN,   # "Know more" + an image link without alt text
        "S7.05": St.WARN,   # the homepage links to /old-offer, which redirects to /offers
        "S7.06": St.PASS,   # every key page links out from its body text
        "S7.07": St.WARN,   # /rooms mentions "rooftop dining" without linking /dining
    }
    by_type = {p.type.value: p for p in result.patches}
    assert by_type["attribute_set"].after == f'href="{B}/offers"'
    link = by_type["link_insert"]
    assert link.page_url == f"{B}/rooms" and link.after == f'<a href="{B}/dining">rooftop dining area</a>'


def test_phrases_skip_brand_and_stop_words():
    got = phrases("Sterling Regalia Agra – Stay Close to the Taj | Sterling Holidays", {"sterling", "holidays"})
    assert "regalia agra" in got and "sterling holidays" not in got and not any(p.startswith("the ") for p in got)
