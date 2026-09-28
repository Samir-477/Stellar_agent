"""Golden tests for A4 Snippet & PAA Opportunities (observation): planted SERP features → statuses."""

import json

from engine.agents.aeo.a04_snippets import SnippetOpportunities
from engine.collectors.c02_parser import parse_page
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St, EvidenceType
from engine.store import MemoryStore, PageRecord, SnapshotReader, SnapshotWriter
from engine.validation import validate_result

B = "https://grand.example"
AGRA = ("<h1>Grand Agra</h1><h2>How do I get to Grand Agra from the station?</h2>"
        "<p>Take a taxi from Agra Cantt station; the 8 km ride takes about 25 minutes and costs 300 rupees.</p>"
        "<p>From the airport, the hotel is 12 km away and can arrange a pickup on request.</p>")


def serp(snap, i, query, position, answer_box=None, paa=()):
    key = snap.put_blob(f"snapshots/s/serp/{i:02d}.json", json.dumps({"serpapi": {"answer_box": answer_box or {}}}))
    snap.add_evidence("C6", EvidenceType.SERP, {"query": query, "intent": "question", "client_position": position,
                                                "organic": [], "features": {"paa": list(paa)}}, blob_key=key)


def build(tmp_path, with_features=True):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    html = f"<!doctype html><html lang='en'><head><title>Grand Agra</title></head><body><main>{AGRA}</main></body></html>"
    page = snap.add_page(PageRecord(id="p0", snapshot_id="s", url=f"{B}/agra", final_url=f"{B}/agra", status=200))
    snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=page.id,
                      blob_key=snap.put_blob("snapshots/s/pages/p0/parsed.json", json.dumps(parse_page(html, page.url))))
    if with_features:
        serp(snap, 1, "how to reach grand agra from agra cantt", 3,
             answer_box={"type": "featured_snippet", "link": "https://travelguide.example/agra",
                         "list": ["Take a prepaid taxi", "Ask for Tajganj", "Pay about 300 rupees"]},
             paa=[{"question": "How do I get to Grand Agra from the station?", "link": "https://travelguide.example/a"},
                  {"question": "Is Grand Agra pet friendly?", "link": None}])
        serp(snap, 2, "grand agra", 1, paa=[{"question": "Does Grand Agra have a pool?", "link": f"{B}/agra"}])
    else:
        snap.add_evidence("C6", EvidenceType.SERP, {"query": "grand agra", "organic": [], "features": None})
    return SnapshotReader(store, blobs, "s"), store


def run(tmp_path, **kw):
    reader, store = build(tmp_path, **kw)
    agent = SnippetOpportunities()
    ctx = AgentContext(reader, ClientProfile(id="c", name="Grand Agra", primary_url=f"{B}/agra"), None, None)
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    result, errors = validate_result(agent, result, {p.final_url for p in store.pages.values()})
    assert errors == []
    return agent, result


def test_a4_reports_snippet_and_paa_opportunities(tmp_path):
    agent, result = run(tmp_path)
    assert check_statuses(agent, result.findings) == {
        "A4.01": St.WARN,  # a list snippet held by a travel guide while the client ranks #3
        "A4.02": St.WARN,  # "pet friendly" has no section; the station question has one; the pool one is held
        "A4.03": St.WARN,  # Google shows a list; the client's best section is paragraphs
    }
    paa = next(f for f in result.findings if f.check_id == "A4.02")
    assert any("Is Grand Agra pet friendly?" in e.excerpt for e in paa.evidence)
    assert not agent.counts_toward_readiness and all(not c.counts_toward_readiness for c in agent.checks)


def test_a4_without_serpapi_captures_is_unverifiable(tmp_path):
    agent, result = run(tmp_path, with_features=False)
    assert set(check_statuses(agent, result.findings).values()) == {St.UNVERIFIABLE}


def test_paa_on_queries_where_the_client_does_not_rank_are_content_ideas_not_opportunities(tmp_path):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    serp(snap, 1, "hotels near taj mahal", None, paa=[{"question": "Which hotels have a view of the Taj Mahal?"}])
    agent = SnippetOpportunities()
    ctx = AgentContext(SnapshotReader(store, blobs, "s"), ClientProfile(id="c", name="G", primary_url=f"{B}/agra"),
                       None, None)
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    paa = next(f for f in result.findings if f.check_id == "A4.02")
    assert paa.status == St.NOT_APPLICABLE
    assert any("Which hotels have a view of the Taj Mahal?" in e.excerpt for e in paa.evidence)
