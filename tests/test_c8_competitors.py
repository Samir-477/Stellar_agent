"""C8 Competitor Capture: domain typing, follow-up fetches, robots.txt obeyed, no repeat spending."""

from engine.collectors.c08_competitors import CompetitorCapture
from engine.context import ClientProfile, CollectorContext
from engine.core.blobstore import LocalBlobStore
from engine.schemas import EvidenceType
from engine.store import MemoryStore, SnapshotWriter
from tests.conftest import FakeLLM, fake_resolver, site_transport

B = "https://www.grand.example"


def build(settings, tmp_path, llm):
    snap = SnapshotWriter(MemoryStore(), LocalBlobStore(tmp_path / "b"), "s")
    snap.add_evidence("C3", EvidenceType.ARCHETYPE, {"archetype": "hospitality"})
    snap.add_evidence("C4", EvidenceType.FACTS, {"facts": [{"key": "property_name", "value": "Grand Agra",
                                                            "status": "site-stated"}]})
    organic = [{"position": 1, "link": "https://www.booking.com/agra", "domain": "booking.com", "title": "10 best hotels"},
               {"position": 2, "link": "https://rival.example/agra", "domain": "rival.example", "title": "Rival Agra"},
               {"position": 3, "link": "https://rival.example/private", "domain": "rival.example", "title": "Rival X"},
               {"position": 4, "link": f"{B}/agra", "domain": "grand.example", "title": "Grand Agra"},
               {"position": 5, "link": "https://travelblog.example/agra", "domain": "travelblog.example",
                "title": "3 days in Agra"}]
    snap.add_evidence("C6", EvidenceType.SERP, {"query": "hotels near taj mahal", "intent": "local", "organic": organic})
    snap.add_evidence("C6", EvidenceType.SERP, {"query": "grand agra", "intent": "brand", "organic": organic[:1]})
    routes = {"https://rival.example/robots.txt": (200, {"content-type": "text/plain"},
                                                   "User-agent: *\nDisallow: /private"),
              "https://rival.example/agra": (200, {"content-type": "text/html"},
                                             "<html><head><title>Rival Agra</title></head><body><h1>Rival Agra</h1>"
                                             "<p>A 60-room hotel 500 m from the Taj Mahal.</p></body></html>")}
    ctx = CollectorContext(snap, ClientProfile(id="c", name="Grand", primary_url=f"{B}/agra"), settings, llm,
                           http_transport=site_transport(routes), resolver=fake_resolver)
    return ctx, snap


def test_c8_types_domains_and_fetches_competitors_politely(settings, tmp_path):
    llm = FakeLLM({"c8.domains": lambda v: {"domains": [
        {"id": line.split(" ", 1)[0], "type": "direct" if "rival" in line else "publisher"}
        for line in v["domains"].splitlines()]}})
    ctx, snap = build(settings, tmp_path, llm)
    collector = CompetitorCapture()
    follow = collector.run_unit(ctx, collector.plan(ctx)[0])
    assert [u.params["domain"] for u in follow] == ["rival.example"]
    for unit in follow * 2:  # a retry mustn't fetch again
        collector.run_unit(ctx, unit)
    types = {d["domain"]: (d["type"], d["source"]) for d in snap.evidence(EvidenceType.COMPETITORS)[0].payload["domains"]}
    assert types["booking.com"] == ("aggregator", "rule") and types["grand.example"] == ("client", "rule")
    assert types["rival.example"] == ("direct", "llm") and types["travelblog.example"] == ("publisher", "llm")
    pages = {e.payload["url"]: e for e in snap.evidence(EvidenceType.COMPETITOR_PAGES)}
    assert len(pages) == 2 and pages["https://rival.example/agra"].blob_key
    blocked = pages["https://rival.example/private"].payload
    assert blocked["robots_allowed"] is False and "status" not in blocked  # disallowed: never fetched
    collector.run_unit(ctx, collector.plan(ctx)[0])
    assert len(llm.calls) == 1  # classification isn't paid for twice
