"""Golden tests for G2 Citable Facts & Evidence: planted issues → exact check statuses."""

import json

from engine.agents.geo.g02_citable_facts import PAGE_WORDS, CitableFacts, figure_pairs, page_text
from engine.agents.common import load_pages
from engine.collectors.c02_parser import parse_page
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St, EvidenceType
from engine.store import MemoryStore, PageRecord, SnapshotReader, SnapshotWriter
from engine.validation import validate_result
from tests.conftest import FakeLLM

B = "https://grand.example"
AGRA_TEXT = ("Grand Agra is a 40-room hotel in Tajganj, 1.4 km from the Taj Mahal's East Gate. Our rooftop pool "
             "looks straight at the dome, and the chef's Mughlai thali uses spices from Kinari Bazaar, a ten-minute "
             "walk away. Guests who wake at 5:30 AM can join our free sunrise walk to the East Gate ticket counter, "
             "which opens at 6 AM. Rated 4.6 on Google by 1,200 guests.")


def doc(title, body):
    return (f"<!doctype html><html lang='en'><head><title>{title}</title></head><body>"
            f"<header><nav><a href='{B}/about'>About</a></nav></header><main>{body}</main></body></html>")


PAGES = {
    f"{B}/": doc("Grand Hotels", "<h1>Welcome to Grand Hotels</h1><p>The best hotels in India with world-class "
                                 "service and unforgettable stays. Voted India's favourite hotel chain.</p>"),
    f"{B}/agra": doc("Grand Agra", f"<h1>Grand Agra near the Taj</h1><p>{AGRA_TEXT}</p>"),
    f"{B}/about": doc("About", "<h1>About</h1><p>Grand Hotels runs 12 hotels across India, in 40 destinations.</p>"),
    f"{B}/loyalty": doc("Loyalty", "<h1>Grand Circle</h1><p>One card, 15 hotels, 35+ destinations.</p>"),
    f"{B}/offers": doc("Offers", "<h1>Offers</h1><p>Save 10% at any of our 38 destinations this monsoon.</p>"),
}


def build(tmp_path):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    for i, (url, html) in enumerate(PAGES.items()):
        page = snap.add_page(PageRecord(id=f"p{i}", snapshot_id="s", url=url, final_url=url, status=200))
        key = snap.put_blob(f"snapshots/s/pages/p{i}/parsed.json", json.dumps(parse_page(html, url)))
        snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=page.id, blob_key=key)
    snap.add_evidence("C4", EvidenceType.FACTS, {"facts": []})
    return SnapshotReader(store, blobs, "s"), store


def page_id(pages_text: str, url: str) -> str:
    return next(line.split(" ", 2)[1] for line in pages_text.splitlines() if f"({url})" in line)


def run(tmp_path, llm):
    reader, store = build(tmp_path)
    agent = CitableFacts()
    ctx = AgentContext(reader, ClientProfile(id="c", name="Grand", primary_url=f"{B}/agra"), None, llm)
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    result, errors = validate_result(agent, result, {p.final_url for p in store.pages.values()})
    assert errors == []
    return agent, result


def facts_answer(home_facts=(), home_entity=("implied", None)):
    def answer(v):
        agra, home = page_id(v["pages"], f"{B}/agra"), page_id(v["pages"], f"{B}/")
        figures = [line.split(":")[0].split()[1] for line in v["figures"].splitlines()]  # F1 hotels, F2 destinations
        return {"pages": [
            {"id": agra, "facts": ["a 40-room hotel in Tajganj, 1.4 km from the Taj Mahal's East Gate",
                                   "the chef's Mughlai thali uses spices from Kinari Bazaar",
                                   "East Gate ticket counter, which opens at 6 AM"],
             "generic": [], "first_hand": "strong",
             "first_hand_quote": "join our free sunrise walk to the East Gate ticket counter",
             "claims": [{"quote": "Rated 4.6 on Google by 1,200 guests", "sourced": True}],
             "entity": "explicit", "entity_quote": "Grand Agra is a 40-room hotel in Tajganj"},
            {"id": home, "facts": list(home_facts), "generic": ["The best hotels in India with world-class service"],
             "first_hand": "none", "first_hand_quote": None,
             "claims": [{"quote": "Voted India's favourite hotel chain", "sourced": False}],
             "entity": home_entity[0], "entity_quote": home_entity[1]},
        ], "figures": [{"id": f, "verdict": "contradiction" if f == "F1" else "drift"} for f in figures]}
    return answer


def test_figure_pairs_find_differing_brand_figures(tmp_path):
    reader, _ = build(tmp_path)
    pages = [p for p in load_pages(AgentContext(reader, ClientProfile(id="c", name="G", primary_url=B), None, None))]
    pairs = {p.noun: (p.a[1], p.b[1]) for p in figure_pairs(pages, [])}
    assert set(pairs) == {"hotel", "destination"}
    assert "12 hotels" in pairs["hotel"][0] and "15 hotels" in pairs["hotel"][1]
    destination = next(p for p in figure_pairs(pages, []) if p.noun == "destination")
    assert [v for v, _ in destination.values] == ["35+", "38", "40"]  # every value is reported, not just two


def test_g2_generic_homepage_and_contradictory_figures(tmp_path):
    llm = FakeLLM({"g2.facts": facts_answer(),
                   "g2.verify": lambda v: {"pairs": [{"id": line.split()[1].rstrip(":"), "contradicts": True}
                                                     for line in v["pairs"].splitlines()]}})
    agent, result = run(tmp_path, llm)
    assert check_statuses(agent, result.findings) == {
        "G2.01": St.FAIL,  # homepage: generic marketing only
        "G2.02": St.FAIL,  # homepage: could be any hotel chain
        "G2.03": St.FAIL,  # "Voted India's favourite hotel chain" unsourced on the homepage
        "G2.04": St.PASS,  # the entry page defines the business
        "G2.05": St.WARN,  # the entry page has a quotable paragraph, the homepage none
        "G2.06": St.FAIL,  # 12 vs 15 hotels, confirmed by the second model
    }
    assert [c[0] for c in llm.calls] == ["g2.facts", "g2.verify"]
    consistency = next(f for f in result.findings if f.check_id == "G2.06")
    assert "1 contradictory and 1 outdated-looking" in consistency.title


def test_g2_does_not_fail_on_hallucinated_quotes_or_overturned_contradictions(tmp_path):
    llm = FakeLLM({"g2.facts": facts_answer(home_facts=["a 200-room flagship in Mumbai"],  # not on the page
                                            home_entity=("explicit", "unforgettable stays")),  # a slogan
                   "g2.verify": {"pairs": [{"id": "F1", "contradicts": False}, {"id": "F2", "contradicts": False}]}})
    agent, result = run(tmp_path, llm)
    statuses = check_statuses(agent, result.findings)
    assert statuses["G2.01"] == St.PASS  # the homepage's facts are unknown, not missing; the entry page has three
    assert statuses["G2.06"] == St.WARN  # the contradiction was overturned; the drift remains
    assert any("overturned by a second model" in limit for limit in result.coverage.limits)
    assert any("weren't found on the page" in limit for limit in result.coverage.limits)
    home_row = next(r for r in result.signature_table["rows"] if r[0] == f"{B}/")
    assert home_row[4] == "—"  # an "explicit" definition that doesn't name the business isn't accepted


def test_g2_without_llm_is_unverifiable_except_deterministic_checks(tmp_path):
    agent, result = run(tmp_path, None)
    statuses = check_statuses(agent, result.findings)
    assert {statuses[c] for c in ("G2.01", "G2.02", "G2.03", "G2.04", "G2.06")} == {St.UNVERIFIABLE}
    assert statuses["G2.05"] == St.WARN


def test_page_text_samples_long_pages_to_the_bottom():
    body = "".join(f"<h2>Section {i}</h2><p>{'Words about section number %d. ' % i * 12}</p>" for i in range(40))
    body += "<h2>Testimonials</h2><p>Ravi Menon, Pune: our team offsite at Grand Agra was flawless.</p>"
    model = parse_page(doc("Long", body), f"{B}/long")
    from engine.agents.common import PageView
    text = page_text(PageView(PageRecord(id="p", snapshot_id="s", url=f"{B}/long"), model), set())
    assert "Ravi Menon, Pune" in text and "Section 0:" in text
    assert len(text.split()) <= PAGE_WORDS + 60  # headings on top of the word budget
