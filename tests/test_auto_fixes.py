"""Prepared fixes (approval required): structured data built only from the site's own facts and verified listings."""

import json

from engine.agents.seo.s08_structured_data import StructuredData
from engine.collectors.c02_parser import parse_page
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.output.patcher import apply
from engine.schemas import EvidenceType
from engine.store import MemoryStore, PageRecord, SnapshotReader, SnapshotWriter
from engine.validation import validate_result

B = "https://www.goldfin.example"
WEBSITE = json.dumps({"@context": "https://schema.org", "@type": "WebSite", "potentialAction": {"@type": "SearchAction"}})
PAGE = (f"<!doctype html><html lang='en'><head><title>GoldFin gold loans</title>"
        f"<script type='application/ld+json'>{WEBSITE}</script></head>"
        "<body><h1>GoldFin gold loans</h1><p>Gold loans from 9.9% a year. Call 1800 100 200.</p></body></html>")


def snapshot(tmp_path, facts):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    rec = snap.add_page(PageRecord(id="p0", snapshot_id="s", url=f"{B}/", final_url=f"{B}/", status=200))
    snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=rec.id,
                      blob_key=snap.put_blob("snapshots/s/pages/p0/parsed.json", json.dumps(parse_page(PAGE, f"{B}/"))))
    snap.add_evidence("C3", EvidenceType.ARCHETYPE, {"archetype": "loans"})
    snap.add_evidence("C4", EvidenceType.FACTS, {"facts": [
        {"id": f"F{i}", "key": k, "value": v, "status": "site-stated", "source_url": f"{B}/"}
        for i, (k, v) in enumerate(facts)]})
    return SnapshotReader(store, blobs, "s"), store


def run_s8(tmp_path, facts):
    reader, store = snapshot(tmp_path, facts)
    agent = StructuredData()
    ctx = AgentContext(reader, ClientProfile(id="c", name="GoldFin", primary_url=f"{B}/"), None, None)
    result, errors = validate_result(agent, agent.run_unit(ctx, agent.plan(ctx)[0]), {f"{B}/"})
    assert errors == []
    return result


def test_s8_prepares_the_missing_business_entity_and_completes_the_website_entity(tmp_path):
    result = run_s8(tmp_path, [("business_name", "GoldFin"), ("phone", "1800 100 200")])
    patches = {p.key.split(":")[0]: p for p in result.patches}
    assert set(patches) == {"S8.02", "S8.03"} and all(p.approval == "required" for p in patches.values())
    entity = json.loads(patches["S8.03"].after.split(">", 1)[1].rsplit("<", 1)[0])
    assert entity == {"@context": "https://schema.org", "@type": "FinancialService", "name": "GoldFin",
                      "url": f"{B}/", "telephone": "1800 100 200"}  # only stated facts; no address invented
    finding = {f.check_id: f for f in result.findings if f.status.value == "fail"}
    assert finding["S8.03"].patch_keys == [patches["S8.03"].key] and finding["S8.03"].missing_facts == ["address"]
    assert finding["S8.02"].patch_keys == [patches["S8.02"].key]
    fixed = apply(PAGE, f"{B}/", [p.model_dump(mode="json") for p in result.patches])
    assert fixed.not_placed == [] and '"FinancialService"' in fixed.fixed_html
    assert '"name": "GoldFin"' in fixed.fixed_html and '"SearchAction"' in fixed.fixed_html  # the block keeps its own data


def test_without_a_stated_name_no_entity_is_prepared_and_only_the_address_is_filled(tmp_path):
    result = run_s8(tmp_path, [("phone", "1800 100 200")])
    assert [p.key.split(":")[0] for p in result.patches] == ["S8.02"]
    assert f'"url": "{B}/"' in result.patches[0].after and '"name"' not in result.patches[0].after
    finding = {f.check_id: f for f in result.findings if f.status.value == "fail"}
    assert finding["S8.03"].patch_keys == [] and finding["S8.03"].missing_facts == ["business name"]


def test_g6_adds_only_listings_titled_with_the_business_name(tmp_path):
    from engine.agents.geo.g06_entity_footprint import OffsiteEntityFootprint

    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    ld = json.dumps({"@type": "Organization", "name": "Grand Agra", "sameAs": ["https://www.facebook.com/grandagra"]})
    html = f"<html><head><script type='application/ld+json'>{ld}</script></head><body><h1>Grand Agra</h1></body></html>"
    url = "https://www.grand.example/"
    rec = snap.add_page(PageRecord(id="p0", snapshot_id="s", url=url, final_url=url, status=200))
    snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=rec.id,
                      blob_key=snap.put_blob("snapshots/s/pages/p0/parsed.json", json.dumps(parse_page(html, url))))
    snap.add_evidence("C12", EvidenceType.ENTITY_FOOTPRINT, {"part": "platforms", "platforms": [
        {"platform": "tripadvisor.in", "found": True, "url": "https://www.tripadvisor.in/grand-agra", "title": "GRAND AGRA"},
        {"platform": "booking.com", "found": True, "url": "https://www.booking.com/grand-mumbai",
         "title": "Grand Residency Mumbai"}]})  # a look-alike: not the business
    agent = OffsiteEntityFootprint()
    ctx = AgentContext(SnapshotReader(store, blobs, "s"), ClientProfile(id="c", name="Grand Agra", primary_url=url),
                       None, None)
    result, errors = validate_result(agent, agent.run_unit(ctx, agent.plan(ctx)[0]), {url})
    assert errors == []
    [prepared] = result.patches
    assert prepared.approval == "required" and "tripadvisor.in/grand-agra" in prepared.after
    assert "booking.com" not in prepared.after and "facebook.com/grandagra" in prepared.after
    assert {f.check_id: f for f in result.findings}["G6.04"].patch_keys == [prepared.key]


def test_two_agents_changing_one_json_ld_block_are_merged_not_overwritten():
    from engine.lib.jsonld import merge3

    base = {"@type": "Organization", "Name": "Flipkart", "sameAs": ["https://x.com/flipkart"]}
    named = {"@type": "Organization", "name": "Flipkart", "url": "https://www.flipkart.com/", "sameAs": ["https://x.com/flipkart"]}
    linked = {"@type": "Organization", "Name": "Flipkart", "sameAs": ["https://x.com/flipkart", "https://in.listing/flipkart"]}
    assert merge3(base, named, linked) == {"@type": "Organization", "name": "Flipkart", "url": "https://www.flipkart.com/",
                                           "sameAs": ["https://x.com/flipkart", "https://in.listing/flipkart"]}
    ld = json.dumps(base)
    page = f"<html><head><script type='application/ld+json'>{ld}</script></head><body><p>x</p></body></html>"
    locator = {"css": 'head > script[type="application/ld+json"]'}
    patches = [{"key": "S8", "type": "jsonld_upsert", "locator": locator, "after": f"<script type='application/ld+json'>{json.dumps(named)}</script>"},
               {"key": "G6", "type": "jsonld_upsert", "locator": locator, "after": f"<script type='application/ld+json'>{json.dumps(linked)}</script>"}]
    result = apply(page, "https://www.flipkart.com/", patches)
    assert sorted(result.placed) == ["G6", "S8"] and result.not_placed == []
    assert '"url": "https://www.flipkart.com/"' in result.fixed_html and "in.listing/flipkart" in result.fixed_html
    assert '"Name"' not in result.fixed_html


def test_listing_pages_exclude_the_own_site_search_pages_and_google():
    from engine.agents.geo.g06_entity_footprint import listing_page

    assert listing_page("https://www.paisabazaar.com/manappuram-finance/", "manappuram")
    assert not listing_page("https://www.flipkart.com/", "flipkart")  # the client's own site
    assert not listing_page("https://www.amazon.in/flipkart-offers/s?k=flipkart", "flipkart")  # a search page
    assert not listing_page("https://www.google.com/finance/quote/MANAPPURAM:NSE", "manappuram")
    assert not listing_page("https://www.tripadvisor.in/", "grand")  # a bare domain
