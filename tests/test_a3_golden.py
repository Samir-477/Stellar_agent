"""Golden tests for A3 Journey Coverage: planted issues → exact check statuses."""

import json

from engine.agents.aeo.a03_journey import JourneyCoverage
from engine.collectors.c02_parser import parse_page
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St, EvidenceType, Severity
from engine.store import MemoryStore, PageRecord, SnapshotReader, SnapshotWriter
from engine.validation import validate_result
from tests.conftest import FakeLLM

B = "https://grand.example"
NAV = (f"<header><nav><a href='{B}/book'>Book now</a><a href='{B}/manage'>Manage booking</a></nav></header>")
AGRA = ("<h1>Grand Agra near the Taj</h1><p>Grand Agra is a 40-room hotel 1.4 km from the Taj Mahal's East Gate.</p>"
        "<h2>Rooms</h2><p>Deluxe rooms have a balcony and a rain shower; suites add a living room.</p>"
        "<h2>How to get there</h2><p>Agra Cantt station is 8 km away; taxis take about 25 minutes.</p>"
        '<script type="application/ld+json">{"@type": "Hotel", "name": "Grand Agra", '
        '"priceRange": "INR 4500 - INR 9000"}</script>')
BOOK = ("<h1>Book your stay</h1><form action='/search'><input name='checkin' type='date'>"
        "<input name='checkout' type='date'><button>Check availability</button></form>")


def doc(title, body):
    return f"<!doctype html><html lang='en'><head><title>{title}</title></head><body>{NAV}<main>{body}</main></body></html>"


PAGES = {f"{B}/": doc("Grand Hotels", "<h1>Grand Hotels</h1><p>Hotels in Agra, Jaipur and Udaipur.</p>"),
         f"{B}/agra": doc("Grand Agra", AGRA), f"{B}/book": doc("Book | Grand Hotels", BOOK)}
QUESTIONS = [
    {"id": "q1", "text": "hotels near taj mahal", "question": "Which hotels are near the Taj Mahal?",
     "source": "observed-paa", "stage": "discover"},
    {"id": "q2", "text": "grand agra reviews", "question": "Is Grand Agra good?", "source": "observed-autocomplete",
     "stage": "evaluate"},
    {"id": "q3", "text": "grand agra check in time", "source": "framework-generated", "stage": "plan"},  # not observed
]


def build(tmp_path, pages=PAGES):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    for i, (url, html) in enumerate(pages.items()):
        page = snap.add_page(PageRecord(id=f"p{i}", snapshot_id="s", url=url, final_url=url, status=200))
        key = snap.put_blob(f"snapshots/s/pages/p{i}/parsed.json", json.dumps(parse_page(html, url)))
        snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=page.id, blob_key=key)
    snap.add_evidence("C3", EvidenceType.ARCHETYPE, {"archetype": "hospitality"})
    snap.add_evidence("C7", EvidenceType.QUESTIONS, {"questions": QUESTIONS})
    return SnapshotReader(store, blobs, "s"), store


def id_of(block: str, text: str) -> str:
    return next(line.split(" ", 1)[0] for line in block.splitlines() if text in line)


def run(tmp_path, llm, pages=PAGES):
    reader, store = build(tmp_path, pages)
    agent = JourneyCoverage()
    ctx = AgentContext(reader, ClientProfile(id="c", name="Grand Agra", primary_url=f"{B}/agra"), None, llm)
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    result, errors = validate_result(agent, result, {p.final_url for p in store.pages.values()})
    assert errors == []
    return agent, result


def test_a3_maps_the_journey_and_finds_planted_gaps(tmp_path):
    def answer(v):
        return {"stages": [
            {"stage": "discover", "status": "covered", "ids": [id_of(v["sections"], "Grand Agra near")]},
            {"stage": "evaluate", "status": "thin", "ids": [id_of(v["sections"], "Rooms")], "note": "No reviews."},
            {"stage": "plan", "status": "covered", "ids": [id_of(v["sections"], "How to get there")]},
            {"stage": "book", "status": "covered", "ids": [id_of(v["tools"], "booking engine")]},
            {"stage": "manage", "status": "covered", "ids": [id_of(v["links"], "Manage booking")]}]}

    agent, result = run(tmp_path, FakeLLM({"a3.journey": answer}))
    assert check_statuses(agent, result.findings) == {
        "A3.01": St.WARN,  # evaluate is thin
        "A3.02": St.WARN,  # booking form is on /book and linked; rates only in JSON-LD
        "A3.03": St.WARN,  # the only way to book is the menu link
        "A3.04": St.WARN,  # customers ask evaluate-stage questions; that stage is thin
    }
    tools = next(f for f in result.findings if f.check_id == "A3.02")
    assert "room rates or price guidance" in tools.title and "booking engine" not in tools.title
    assert any("only in structured data" in e.excerpt for e in tools.evidence)


def test_a3_book_stage_gaps_are_high_and_uncited_verdicts_are_dropped(tmp_path):
    pages = {f"{B}/": PAGES[f"{B}/"],
             f"{B}/agra": f"<!doctype html><html><head><title>Grand Agra</title></head><body><main>{AGRA}</main>"
                          "</body></html>"}  # no menu, no booking page
    answer = {"stages": [{"stage": "discover", "status": "covered", "ids": ["S1"]},
                         {"stage": "evaluate", "status": "covered", "ids": ["S99"]},  # cites nothing that exists
                         {"stage": "book", "status": "absent", "ids": [], "note": "No booking or enquiry."}]}
    agent, result = run(tmp_path, FakeLLM({"a3.journey": answer}), pages)
    statuses = check_statuses(agent, result.findings)
    assert statuses["A3.01"] == St.FAIL and statuses["A3.02"] == St.FAIL and statuses["A3.03"] == St.FAIL
    presence = next(f for f in result.findings if f.check_id == "A3.01")
    assert presence.severity == Severity.HIGH and "evaluate" not in presence.title
    assert any("cited nothing on the site" in limit for limit in result.coverage.limits)


def test_a3_without_llm_keeps_the_deterministic_checks(tmp_path):
    agent, result = run(tmp_path, None)
    statuses = check_statuses(agent, result.findings)
    assert statuses["A3.01"] == St.UNVERIFIABLE and statuses["A3.04"] == St.UNVERIFIABLE
    assert statuses["A3.02"] == St.WARN and statuses["A3.03"] == St.WARN


# ---- regressions from the live run on sterlingholidays.com

def _view(url, html):
    from engine.agents.common import PageView
    return PageView(PageRecord(id=url, snapshot_id="s", url=url, final_url=url, status=200), parse_page(html, url))


def test_a_tool_counts_only_if_the_linked_page_has_it():
    from engine.agents.aeo.a03_journey import tool_state
    from engine.rules.packs import PACKS
    booking, rates = PACKS["hospitality"].critical_tools
    entry = _view(f"{B}/agra", doc("Grand Agra", AGRA))  # menu "Book now" goes to /book
    widget_elsewhere = _view(f"{B}/awards", doc("Awards", BOOK))  # the form lives on an unrelated page
    js_only = _view(f"{B}/book", doc("Book", "<h1>Book</h1><div id='app'></div>"))  # no form in the HTML
    state = tool_state(booking, entry, [entry, widget_elsewhere, js_only])
    assert state.status == St.WARN and "likely loads with JavaScript" in state.detail and "/awards" in state.detail
    assert tool_state(booking, entry, [entry, _view(f"{B}/book", doc("Book", BOOK))]).status == St.PASS
    # Prices on other pages describe other offers: rates are judged on the entry page (here: JSON-LD only).
    offers = _view(f"{B}/circle", doc("Circle", "<p>Member stays starting at ₹7,600 per night.</p>"))
    rate_state = tool_state(rates, entry, [entry, offers])
    assert rate_state.status == St.WARN and "only in structured data" in rate_state.detail


def test_headings_without_text_are_grouped_so_sections_with_text_are_seen(tmp_path):
    empty = "".join(f"<h3>Tab {i}</h3>" for i in range(25))
    pages = dict(PAGES, **{f"{B}/agra": doc("Grand Agra", empty + AGRA)})
    seen = {}

    def answer(v):
        seen["sections"] = v["sections"]
        return {"stages": []}

    run(tmp_path, FakeLLM({"a3.journey": answer}), pages)
    assert "Rooms: Deluxe rooms have a balcony" in seen["sections"]  # not pushed out by 25 empty tabs
    assert "headings with no text of their own: Tab 0, Tab 1" in seen["sections"]
