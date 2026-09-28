"""Golden tests for S4 On-Page Content Quality: planted issues → exact check statuses."""

import json

from engine.agents.seo.s04_content import OnPageContent, pick_target
from engine.collectors.c02_parser import parse_page
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St, EvidenceType
from engine.store import MemoryStore, PageRecord, SnapshotReader, SnapshotWriter
from engine.validation import validate_result
from tests.conftest import FakeLLM

B = "https://grand.example"
NAV = f"<header><nav><a href='{B}/rooms'>Rooms</a><a href='{B}/offers'>Offers</a></nav></header>"
ROOMS = ("<p>Our deluxe room sleeps two adults and a child. Each deluxe room has a balcony facing the garden. "
         "Book a deluxe room for quiet nights after a day at the Taj Mahal.</p>"
         "<p>Families like the deluxe room because the sofa opens into a bed. The deluxe room also has a tea "
         "maker, a safe and a rain shower. Breakfast is served in the courtyard from 7 AM.</p>"
         "<p>Ask for a deluxe room on the top floor for the best light. Housekeeping visits twice a day and "
         "fresh towels are always free. Children under five stay free with their parents.</p>"
         "<p>Suites add a separate living room, a larger bathroom and a view across the old city roofs. They "
         "suit longer stays and small groups travelling together with plenty of luggage.</p>")
AGRA = ("<p>Grand Agra is a 40-room hotel 1.4 km from the Taj Mahal's East Gate, with a rooftop pool and a "
        "restaurant serving Mughlai food.</p><h3>Getting here</h3><p>Agra Cantt station is 8 km away; taxis take "
        "about 25 minutes and cost around 300 rupees.</p><p>The airport is 12 km from the hotel and we can arrange "
        "a pickup on request.</p>")


def doc(title, body):
    return f"<!doctype html><html lang='en'><head><title>{title}</title></head><body>{NAV}<main>{body}</main></body></html>"


PAGES = {
    f"{B}/": doc("Grand Hotels", "<h1>Where every moment matters</h1><p>Grand Hotels runs hotels in Agra, Jaipur and "
                                 "Udaipur, each a short walk from the city's main sights.</p>"),
    f"{B}/agra": doc("Grand Agra", f"<h1>Grand Agra near the Taj</h1>{AGRA}"),
    f"{B}/rooms": doc("Rooms | Grand Hotels", f"<h1>Rooms and suites</h1>{ROOMS}"),
    f"{B}/offers": doc("Offers", "<h2>Offers</h2><p>Diwali offer: 20% off all rooms, valid till 31 October 2020.</p>"),
}
LOCAL = [{"position": i, "link": f"https://{d}/agra", "title": t, "snippet": s, "domain": d} for i, (d, t, s) in
         enumerate([("booking.com", "10 best hotels near Taj Mahal", "Prices from ₹2,100; distance from the Taj."),
                    ("makemytrip.com", "Hotels near Taj Mahal", "Compare prices and distance to the Taj Mahal."),
                    ("tripadvisor.in", "Closest hotels to Taj Mahal", "Distance and reviews for hotels near the Taj."),
                    ("agoda.com", "Hotels near Taj Mahal", "Filter by price or distance."),
                    ("oberoihotels.com", "The Oberoi Amarvilas, Agra", "Every room views the Taj Mahal.")], start=1)]


def build(tmp_path, page_query_map=None):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    for i, (url, html) in enumerate(PAGES.items()):
        page = snap.add_page(PageRecord(id=f"p{i}", snapshot_id="s", url=url, final_url=url, status=200))
        key = snap.put_blob(f"snapshots/s/pages/p{i}/parsed.json", json.dumps(parse_page(html, url)))
        snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=page.id, blob_key=key)
    queries = [{"q": "grand agra", "intent": "brand", "priority": 1},
               {"q": "hotels near taj mahal", "intent": "local", "priority": 2}]
    snap.add_evidence("C5", EvidenceType.QUERY_SET, {"queries": queries,
                                                     "page_query_map": page_query_map or {f"{B}/agra": "grand agra"}})
    snap.add_evidence("C6", EvidenceType.SERP, {"query": "grand agra", "intent": "brand", "organic": LOCAL[:1]})
    snap.add_evidence("C6", EvidenceType.SERP, {"query": "hotels near taj mahal", "intent": "local", "organic": LOCAL})
    return SnapshotReader(store, blobs, "s"), store


def answer(v):
    h1_ids = {line.split(" ")[1].strip("():"): line.split(" ")[0] for line in v["h1s"].splitlines()}
    return {"page_type": "single_business",
            "results": [{"id": f"R{i}", "type": "listing" if i < 5 else "single_business"} for i in range(1, 6)],
            "subtopics": [{"topic": "prices", "results": ["R1", "R2", "R4"], "covered": False},
                          {"topic": "distance from the Taj Mahal", "results": ["R1", "R2", "R3"], "covered": True,
                           "quote": "1.4 km from the Taj Mahal's East Gate"},
                          {"topic": "Taj views from the room", "results": ["R5", "R3"], "covered": True,
                           "quote": "every room has a Taj view"}],  # not on the page: unclear, not counted
            "intro": {"verdict": "answers", "quote": "Grand Agra is a 40-room hotel 1.4 km from the Taj Mahal's East Gate"},
            "h1s": [{"id": k, "descriptive": url != f"{B}/", "note": None if url != f"{B}/" else "A slogan."}
                    for url, k in h1_ids.items()]}


def run(tmp_path, llm, **kw):
    reader, store = build(tmp_path, **kw)
    agent = OnPageContent()
    ctx = AgentContext(reader, ClientProfile(id="c", name="Grand", primary_url=f"{B}/agra"), None, llm)
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    result, errors = validate_result(agent, result, {p.final_url for p in store.pages.values()})
    assert errors == []
    return agent, result, ctx


def test_s4_finds_planted_content_issues(tmp_path):
    agent, result, _ = run(tmp_path, FakeLLM({"s4.content": answer}))
    assert check_statuses(agent, result.findings) == {
        "S4.01": St.FAIL,  # /offers has no H1 (the homepage slogan H1 is listed too)
        "S4.02": St.WARN,  # /agra jumps from H1 to H3
        "S4.03": St.PASS,  # the opening states what, where and how far
        "S4.04": St.WARN,  # listings dominate "hotels near taj mahal"; target inferred
        "S4.05": St.WARN,  # prices missing; the unverified "Taj views" claim isn't counted either way
        "S4.06": St.WARN,  # /offers is thin
        "S4.07": St.FAIL,  # Diwali 2020 offer
        "S4.08": St.PASS,
        "S4.09": St.WARN,  # "deluxe room" 6 times in ~150 words
    }
    by_check = {f.check_id: f for f in result.findings}
    assert "(target query inferred)" in by_check["S4.04"].title
    assert by_check["S4.05"].missing_facts == ["prices"]
    assert any("generic H1" in e.excerpt for e in by_check["S4.01"].evidence)
    assert any("quote isn't on the page" in limit for limit in result.coverage.limits)


def test_pick_target_prefers_a_mapped_non_brand_query(tmp_path):
    _, _, ctx = run(tmp_path, None, page_query_map={f"{B}/agra": "hotels near taj mahal"})
    target = pick_target(ctx, f"{B}/agra")
    assert (target.query, target.source) == ("hotels near taj mahal", "mapped")


def test_s4_without_llm_keeps_deterministic_checks(tmp_path):
    agent, result, _ = run(tmp_path, None)
    statuses = check_statuses(agent, result.findings)
    assert {statuses[c] for c in ("S4.03", "S4.04", "S4.05")} == {St.UNVERIFIABLE}
    assert statuses["S4.01"] == St.FAIL and statuses["S4.07"] == St.FAIL


# ---- regressions from the live run on sterlingholidays.com

def test_brand_taglines_and_list_labels_are_not_keyword_stuffing():
    from engine.agents.seo.s04_content import in_brand, templated_share
    brands = [["sterling", "holiday", "resort", "limited"]]
    assert in_brand("holiday resort", brands) and not in_brand("deluxe room", brands)  # "A Sterling Holiday Resort"
    offers = [f"Special offer for {bank} customers: Avail a flat Rs. 1000 off on room rates."
              for bank in ("ICICI bank", "Amex card", "Plutos", "HDFC bank")]
    assert templated_share("special offer", offers) == 1.0  # opens every card
    assert templated_share("customers avail", offers) == 1.0  # same words follow it every time
    rooms = ["Our deluxe room sleeps two.", "Book a deluxe room today.", "Each deluxe room has a balcony."]
    assert templated_share("deluxe room", rooms) < 0.6


def test_card_labels_without_full_stops_are_not_long_sentences():
    from engine.agents.common import PageView
    page = PageView(PageRecord(id="p", snapshot_id="s", url=f"{B}/events"), {})
    cards = [f"Sterling Resort Number {i} A Sterling Holiday Resort" for i in range(40)]
    prose = ["We host weddings for up to 200 guests. Our planners handle decor and food. Rooms are held for guests."]
    finding = OnPageContent()._readability([page], {page.url: cards + prose})
    assert finding.status == St.PASS


def test_text_in_divs_counts_as_the_pages_own_content():
    from engine.agents.common import PageView
    from engine.agents.seo.s04_content import own_words_estimate
    body = "<h1>Corporate+</h1><div>" + "Exclusive holiday savings for corporate employees and teams. " * 25 + "</div>"
    model = parse_page(doc("Corporate", body), f"{B}/corporate")
    own, total = own_words_estimate(PageView(PageRecord(id="p", snapshot_id="s", url=f"{B}/corporate"), model),
                                    [], set())
    assert own == total and own >= 150  # no paragraphs, but it isn't thin


def test_subtopic_alternatives_count_as_mentions():
    assert OnPageContent._mentioned("rooftop or swimming pool", "a fourth-floor swimming pool with Taj views")
    assert not OnPageContent._mentioned("prices and rates", "a fourth-floor swimming pool with Taj views")
