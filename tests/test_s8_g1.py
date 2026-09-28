import json

from engine.agents.geo.g01_ai_access import AICrawlerAccess
from engine.agents.seo.s08_structured_data import StructuredData
from engine.collectors.c02_parser import parse_page
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St, EvidenceType
from engine.store import MemoryStore, PageRecord, SnapshotReader, SnapshotWriter

BASE = "https://hotels.example"


def html(title, h1, body, *entities, raw_jsonld=None):
    scripts = "".join(f'<script type="application/ld+json">{json.dumps(e)}</script>' for e in entities)
    if raw_jsonld:
        scripts += f'<script type="application/ld+json">{raw_jsonld}</script>'
    return (f"<!doctype html><html lang='en'><head><title>{title}</title>{scripts}</head>"
            f"<body><h1>{h1}</h1>{body}</body></html>")


def build(tmp_path, pages: dict[str, str], facts=(), robots=None, probes=None):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    for i, (url, doc) in enumerate(pages.items()):
        page = snap.add_page(PageRecord(id=f"p{i}", snapshot_id="s", url=url, final_url=url, status=200))
        key = snap.put_blob(f"snapshots/s/pages/p{i}/parsed.json", json.dumps(parse_page(doc, url)))
        snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=page.id, blob_key=key)
    snap.add_evidence("C4", EvidenceType.FACTS, {"facts": list(facts)})
    snap.add_evidence("C3", EvidenceType.ARCHETYPE, {"archetype": "hospitality"})
    if robots is not None:
        key = snap.put_blob("snapshots/s/site/robots.txt", robots)
        snap.add_evidence("C1", EvidenceType.SITE_FILES, {"kind": "robots.txt", "status": 200,
                                                          "url": f"{BASE}/robots.txt"}, blob_key=key)
    if probes is not None:
        snap.add_evidence("C1", EvidenceType.AI_UA_PROBES, probes)
    return store, blobs


def run(agent, store, blobs, entry):
    ctx = AgentContext(SnapshotReader(store, blobs, "s"), ClientProfile(id="c", name="x", primary_url=entry), None)
    return agent.run_unit(ctx, agent.plan(ctx)[0])


def test_s8_flags_schema_for_another_property_and_builds_fix_from_page_facts(tmp_path):
    entry = f"{BASE}/agra"
    wrong = {"@context": "https://schema.org", "@type": "LodgingBusiness", "name": "Grand Ayodhya Inn",
             "address": {"@type": "PostalAddress", "addressLocality": "Ayodhya"}}
    listing = {"@context": "https://schema.org", "@graph": [
        {"@type": "Hotel", "name": "Grand Goa", "address": {"addressLocality": "Goa"}},
        {"@type": "Hotel", "name": "Grand Ooty", "address": {"addressLocality": "Ooty"}}]}
    pages = {
        entry: html("Grand Agra Hotel", "Grand Agra Hotel near the Taj", "<p>Grand Agra Hotel has 40 rooms "
                    "near the Taj Mahal in Agra, with a rooftop pool.</p><p>Also visit Ayodhya: Grand Ayodhya Inn.</p>",
                    wrong),
        f"{BASE}/all-hotels": html("All hotels", "Our hotels", "<p>Choose from our hotels in Goa and Ooty today.</p>",
                                   listing, raw_jsonld='{"@type": "Organization", "name": "Grand\nHotels", "url": "x"}'),
    }
    facts = [{"id": "F-001", "key": "property_name", "value": "Grand Agra Hotel", "status": "site-stated",
              "source_url": entry, "quote": "Grand Agra Hotel"},
             {"id": "F-002", "key": "room_count", "value": "40", "status": "site-stated", "source_url": entry,
              "quote": "has 40 rooms"}]
    store, blobs = build(tmp_path, pages, facts)
    result = run(StructuredData(), store, blobs, entry)
    statuses = check_statuses(StructuredData(), result.findings)
    assert statuses["S8.04"] == St.FAIL  # the Ayodhya entity on the Agra page (the listing page is not flagged)
    s804 = [f for f in result.findings if f.check_id == "S8.04"]
    assert [f.scope.pages for f in s804] == [[entry]] and s804[0].severity == "high"
    assert statuses["S8.01"] == St.WARN  # raw newline inside a JSON string: lenient-parseable
    patch = result.patches[0]
    assert '"name": "Grand Agra Hotel"' in patch.after and '"numberOfRooms": "40"' in patch.after
    assert "Ayodhya" not in patch.after and "address" in s804[0].missing_facts


def test_g1_blocked_search_crawlers_placeholders_and_firewall(tmp_path):
    entry = f"{BASE}/"
    widget = "".join(f"<li>{{{{item.name}}}} from {{{{item.price}}}} per night option {i}</li>" for i in range(4))
    pages = {entry: html("Grand", "Grand hotels", f"<ul>{widget}</ul><p>Welcome to Grand hotels in India today.</p>")}
    robots = "User-agent: PerplexityBot\nDisallow: /\n\nUser-agent: GPTBot\nDisallow: /\n"
    probes = {"url": entry, "browser": {"status": 200, "bytes": 50000},
              "agents": [{"agent": "OAI-SearchBot", "status": 403, "bytes": 200},
                         {"agent": "ClaudeBot", "status": 200, "bytes": 49000}]}
    store, blobs = build(tmp_path, pages, robots=robots, probes=probes)
    result = run(AICrawlerAccess(), store, blobs, entry)
    statuses = check_statuses(AICrawlerAccess(), result.findings)
    assert statuses["G1.01"] == St.FAIL and statuses["G1.03"] == St.FAIL and statuses["G1.04"] == St.FAIL
    g101 = next(f for f in result.findings if f.check_id == "G1.01")
    assert g101.severity == "high"  # only 1 of 4 search crawlers blocked; all 4 would be critical
    robots_patch = next(p for p in result.patches if p.key == "G1.01:robots")
    assert "PerplexityBot" in robots_patch.before and "Disallow: /\n\nUser-agent: GPTBot" not in robots_patch.after
    assert statuses["G1.05"] == St.UNVERIFIABLE  # no rendered HTML
