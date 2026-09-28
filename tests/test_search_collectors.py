import json

from engine.collectors.search_collectors import SerpCapture
from engine.context import ClientProfile, CollectorContext, WorkUnit
from engine.core.blobstore import LocalBlobStore
from engine.integrations.search import SearchBudget, SearchClient, SearchError
from engine.schemas import EvidenceType
from engine.store import MemoryStore, SnapshotWriter
import httpx
import pytest


def test_search_timeouts_become_search_errors_not_task_failures():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)
    client = SearchClient("k", "k", SearchBudget({"serper": 5, "serpapi": 5}),
                          http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(SearchError):
        client.organic("q")


def test_budget_refuses_calls_beyond_the_cap():
    budget = SearchBudget({"serpapi": 1})
    budget.spend("serpapi")
    with pytest.raises(SearchError):
        budget.spend("serpapi")


def test_c6_units_are_per_query_and_skip_already_captured(settings, tmp_path):
    calls = []

    def handler(req):
        calls.append(json.loads(req.content)["q"])
        return httpx.Response(200, json={"organic": [{"position": 1, "link": "https://h.example/", "title": "t"}]})

    snap = SnapshotWriter(MemoryStore(), LocalBlobStore(tmp_path / "b"), "s")
    snap.add_evidence("C5", EvidenceType.QUERY_SET, {"queries": [
        {"q": "grand agra", "intent": "brand", "priority": 1}, {"q": "hotels agra", "intent": "service", "priority": 2}]})
    search = SearchClient("k", "", SearchBudget({"serper": 10, "serpapi": 0}),
                          http=httpx.Client(transport=httpx.MockTransport(handler)))
    ctx = CollectorContext(snap, ClientProfile(id="c", name="x", primary_url="https://h.example/"),
                           settings.model_copy(update={"serpapi_calls_per_run": 0}), search=search)
    collector = SerpCapture()
    units = collector.plan(ctx)
    assert [u.params["priority"] for u in units] == [1, 2]
    collector.run_unit(ctx, units[0])
    collector.run_unit(ctx, units[0])  # retry of the same unit: no second paid call
    assert calls == ["grand agra"]
    assert snap.evidence(EvidenceType.SERP)[0].payload["client_position"] == 1


def test_c10_checks_whether_printed_urls_exist(settings, tmp_path):
    from engine.collectors.ai_collectors import AIAnswerCapture
    from tests.conftest import FakeLLM, fake_resolver, site_transport
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    snap.add_evidence("C9", EvidenceType.PROMPT_SET, {"prompts": [
        {"id": "P1", "kind": "brand", "text": "Tell me about Grand Agra."}]})
    llm = FakeLLM({"c10.probe:deepseek": "See https://grand.example/rooms and https://grand.example/made-up-page."})
    routes = {"https://grand.example/rooms": (200, {"content-type": "text/html"}, "<h1>Rooms</h1>")}
    ctx = CollectorContext(snap, ClientProfile(id="c", name="Grand", primary_url="https://grand.example/"), settings,
                           llm, http_transport=site_transport(routes), resolver=fake_resolver)
    AIAnswerCapture().run_unit(ctx, WorkUnit("capture", {"surface": "deepseek"}))
    answer = snap.evidence(EvidenceType.AI_ANSWERS)[-1].payload["answers"][0]
    status = {c["url"]: c["resolves"] for c in answer["citations"]}
    # The sentence's full stop isn't part of the URL; the made-up page doesn't exist.
    assert status == {"https://grand.example/rooms": True, "https://grand.example/made-up-page": False}
