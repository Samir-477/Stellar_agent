"""Golden tests for S5 Keyword Themes & Cannibalization: planted issues → exact check statuses."""

import json

from engine.agents.common import brand_tokens
from engine.agents.seo.s05_themes import KeywordThemes, cluster, Signal
from engine.collectors.c02_parser import parse_page
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St, EvidenceType
from engine.store import MemoryStore, PageRecord, SnapshotReader, SnapshotWriter
from engine.validation import validate_result
from tests.conftest import FakeLLM

B = "https://grand.example"
NAV = f"<header><nav><a href='{B}/rooms-near-taj'>Rooms</a><a href='{B}/blog/agra-guide'>Guide</a></nav></header>"


def doc(title, h1, body=""):
    return (f"<!doctype html><html lang='en'><head><title>{title}</title></head><body>{NAV}<main><h1>{h1}</h1>"
            f"{body}</main></body></html>")


PAGES = {
    f"{B}/": doc("Grand Hotels", "Grand Hotels", "<p>Hotels in Agra, Jaipur and Udaipur near the main sights.</p>"),
    f"{B}/agra": doc("Grand Agra | Hotel near Taj Mahal", "Grand Agra near the Taj Mahal",
                     "<p>A 40-room hotel 1.4 km from the Taj Mahal with a rooftop pool.</p>"),
    f"{B}/rooms-near-taj": doc("Rooms near Taj Mahal | Grand Agra", "Hotel rooms near the Taj Mahal",
                               "<p>Book deluxe rooms a short walk from the Taj Mahal.</p>"),
    f"{B}/blog/agra-guide": doc("Agra travel guide", "Things to do in Agra",
                                "<p>See the Taj Mahal at sunrise, then book our Agra package with dinner.</p>"),
}


def build(tmp_path):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    for i, (url, html) in enumerate(PAGES.items()):
        page = snap.add_page(PageRecord(id=f"p{i}", snapshot_id="s", url=url, final_url=url, status=200))
        key = snap.put_blob(f"snapshots/s/pages/p{i}/parsed.json", json.dumps(parse_page(html, url)))
        snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=page.id, blob_key=key)
    snap.add_evidence("C4", EvidenceType.FACTS, {"facts": [
        {"key": "city", "value": "Agra", "quote": "Agra", "source_url": f"{B}/agra", "status": "site-stated"}]})
    snap.add_evidence("C5", EvidenceType.QUERY_SET, {"queries": [
        {"q": "grand agra", "intent": "brand", "priority": 1},
        {"q": "hotels near taj mahal", "intent": "local", "priority": 2},
        {"q": "hotel with pool near taj mahal", "intent": "service", "priority": 3}]})
    snap.add_evidence("C7", EvidenceType.QUESTIONS, {"questions": [
        {"id": "q1", "text": "which hotels are close to the taj mahal", "source": "observed-paa", "stage": "discover"}]})
    raw = snap.put_blob("snapshots/s/serp/02.json", json.dumps({"serpapi": {"related_searches": [
        {"query": "budget hotels in agra"}, {"query": "best budget hotels agra"}]}}))
    snap.add_evidence("C6", EvidenceType.SERP, {
        "query": "hotels near taj mahal", "intent": "local", "client_position": 4,
        "organic": [{"link": f"{B}/agra", "domain": "grand.example"},
                    {"link": f"{B}/rooms-near-taj", "domain": "grand.example"}],
        "features": {"paa": [{"question": "Is Agra Fort open on Friday?"}]}}, blob_key=raw)
    return SnapshotReader(store, blobs, "s"), store


def pid(pages: str, url: str) -> str:
    return next(line.split(" ", 1)[0] for line in pages.splitlines() if f"({url})" in line)


def cid(clusters: str, text: str) -> str:
    return next(line.split(" ", 1)[0] for line in clusters.splitlines() if text in line)


def answer(v):
    p, c = v["pages"], v["clusters"]
    return {"clusters": [
        {"id": cid(c, "grand agra"), "name": "Grand Agra (brand)", "owner": pid(p, f"{B}/agra"), "core": True},
        {"id": cid(c, "hotels near taj mahal"), "name": "hotels near the Taj Mahal", "owner": pid(p, f"{B}/agra"),
         "competing": [pid(p, f"{B}/rooms-near-taj")], "core": True},
        {"id": cid(c, "budget hotels"), "name": "budget hotels in Agra", "owner": None, "core": False},
        {"id": cid(c, "Agra Fort"), "name": "Agra Fort opening days", "owner": None, "core": False}],
        "pages": [{"id": pid(p, f"{B}/agra"), "intent": "transactional"},
                  {"id": pid(p, f"{B}/rooms-near-taj"), "intent": "transactional"},
                  {"id": pid(p, f"{B}/blog/agra-guide"), "intent": "mixed"},
                  {"id": pid(p, f"{B}/"), "intent": "navigational"}]}


def run(tmp_path, llm):
    reader, store = build(tmp_path)
    agent = KeywordThemes()
    ctx = AgentContext(reader, ClientProfile(id="c", name="Grand Agra", primary_url=f"{B}/agra"), None, llm)
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    result, errors = validate_result(agent, result, {p.final_url for p in store.pages.values()})
    assert errors == []
    return agent, result, ctx


def test_s5_maps_themes_and_finds_planted_conflicts(tmp_path):
    agent, result, _ = run(tmp_path, FakeLLM({"s5.themes": answer}))
    assert check_statuses(agent, result.findings) == {
        "S5.01": St.WARN,  # two non-core themes have no page
        "S5.02": St.FAIL,  # /agra and /rooms-near-taj both rank for "hotels near taj mahal"
        "S5.03": St.FAIL,  # the guide informs and sells
        "S5.04": St.WARN,  # 2 of 3 Agra themes have no page
        "S5.05": St.WARN,  # "budget hotels in agra" recurs in related searches; the site never says budget/cheap
    }
    cannibal = next(f for f in result.findings if f.check_id == "S5.02")
    assert "both rank for the same search" in cannibal.evidence[0].excerpt


def test_shared_place_words_do_not_merge_different_topics():
    places = {"taj", "mahal", "agra"}
    signals = [Signal(t, "query:local") for t in ("hotels near taj mahal", "pet friendly hotel near taj mahal agra",
                                                  "banquet hall hotel near taj mahal agra",
                                                  "which hotels in agra are close to the taj mahal")]
    themes = cluster(signals, set(), places)
    assert sorted(len(t.signals) for t in themes) == [1, 1, 2]  # place-only searches together; pets, banquets apart


def test_the_city_is_not_a_brand_word(tmp_path):
    _, _, ctx = run(tmp_path, None)
    assert brand_tokens(ctx) == {"grand"}  # "agra" is the city (Fact Sheet), not the brand
    themes = cluster([Signal("grand agra", "query:brand"), Signal("hotels in agra", "query:local")], {"grand"},
                     {"agra"})
    assert [t.brand for t in themes] == [True, False]


def test_s5_without_llm_is_unverifiable_where_judgement_is_needed(tmp_path):
    agent, result, _ = run(tmp_path, None)
    statuses = check_statuses(agent, result.findings)
    assert statuses["S5.01"] == St.UNVERIFIABLE and statuses["S5.03"] == St.UNVERIFIABLE


# ---- regressions from the live run on sterlingholidays.com

def test_an_owner_that_never_mentions_the_topic_is_rejected(tmp_path):
    def answer_with_bad_owner(v):
        data = answer(v)
        for c in data["clusters"]:
            if c["name"] == "budget hotels in Agra":
                c["owner"] = pid(v["pages"], f"{B}/agra")  # /agra never says "budget"
        return data

    agent, result, _ = run(tmp_path, FakeLLM({"s5.themes": answer_with_bad_owner}))
    owners = {row[0]: row[3] for row in result.signature_table["rows"]}
    assert owners["budget hotels in Agra"] == "—"
    assert any("were not accepted: budget hotels in Agra" in limit for limit in result.coverage.limits)


def test_section_hints_need_every_topic_word():
    from engine.agents.common import PageView
    from engine.agents.seo.s05_themes import section_covering
    html = doc("Grand Agra", "Grand Agra", "<h2>Pool</h2><p>A rooftop swimming pool with Taj views.</p>")
    page = PageView(PageRecord(id="p", snapshot_id="s", url=f"{B}/agra"), parse_page(html, f"{B}/agra"))
    assert section_covering(page, {"private", "pool"}) is None  # a pool, but not a private one
    assert section_covering(page, {"swimming", "pool"}) == "Pool"



def test_an_address_holding_the_business_name_does_not_strip_brand_words(tmp_path):
    from engine.agents.common import place_words
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    SnapshotWriter(store, blobs, "s").add_evidence("C4", EvidenceType.FACTS, {"facts": [
        {"key": "city", "value": "Agra", "quote": "Agra", "source_url": f"{B}/agra", "status": "site-stated"},
        {"key": "address", "value": "Grand Rampath, Ayodhya", "quote": "x", "source_url": f"{B}/agra",
         "status": "schema-declared"}]})
    ctx = AgentContext(SnapshotReader(store, blobs, "s"), ClientProfile(id="c", name="Grand Agra",
                                                                        primary_url=f"{B}/agra"), None, None)
    assert "grand" not in place_words(ctx) and brand_tokens(ctx) == {"grand"}
