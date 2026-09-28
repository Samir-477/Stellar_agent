"""S3.07 Open Graph: patches copy the page's own title, description and declared image, and are placed
under the hood."""

import json

from engine.agents.seo.s03_metadata import SearchMetadata, og_image
from engine.agents.common import PageView
from engine.collectors.c02_parser import parse_page
from engine.context import AgentContext, ClientProfile
from engine.core.blobstore import LocalBlobStore
from engine.output.patcher import apply
from engine.schemas import EvidenceType
from engine.store import MemoryStore, PageRecord, SnapshotReader, SnapshotWriter

B = "https://grand.example"
HTML = ("<!doctype html><html lang='en'><head><title>Grand Agra & Spa | Rooms near the Taj</title>"
        "<meta name='description' content='A 40-room hotel 1.4 km from the Taj Mahal, with a rooftop pool.'>"
        "<meta property='og:title' content='Grand Agra'>"
        "<script type='application/ld+json'>[{\"@type\": \"Organization\", \"image\": \"https://grand.example/brand.jpg\"},"
        " {\"@type\": \"Hotel\", \"image\": \"https://grand.example/hero.jpg\"}]"
        "</script></head><body><img src='/logo.svg'><h1>Grand Agra</h1><p>Rooms near the Taj.</p></body></html>")


def test_open_graph_patches_copy_what_the_page_says(tmp_path):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "b")
    snap = SnapshotWriter(store, blobs, "s")
    rec = snap.add_page(PageRecord(id="p0", snapshot_id="s", url=f"{B}/", final_url=f"{B}/", status=200))
    snap.add_evidence("C2", EvidenceType.PAGES_PARSED, {}, page_id=rec.id,
                      blob_key=snap.put_blob("snapshots/s/pages/p0/parsed.json", json.dumps(parse_page(HTML, rec.url))))
    agent = SearchMetadata()
    ctx = AgentContext(SnapshotReader(store, blobs, "s"), ClientProfile(id="c", name="G", primary_url=f"{B}/"), None,
                       None)
    result = agent.run_unit(ctx, agent.plan(ctx)[0])
    og = {p.key.split(":")[1] + ":" + p.key.split(":")[2]: p for p in result.patches if p.key.startswith("S3:og")}
    assert set(og) == {"og:description", "og:image"}  # og:title already exists: left alone
    assert og["og:image"].after == '<meta property="og:image" content="https://grand.example/hero.jpg">'
    assert "1.4 km from the Taj Mahal" in og["og:description"].after
    finding = next(f for f in result.findings if f.check_id == "S3.07")
    assert set(finding.patch_keys) == {p.key for p in og.values()}
    placed = apply(HTML, f"{B}/", [p.model_dump(mode="json") for p in og.values()])
    assert placed.not_placed == [] and {u["key"] for u in placed.under_the_hood} == {p.key for p in og.values()}
    assert 'property="og:image" content="https://grand.example/hero.jpg"' in placed.fixed_html


def test_og_image_skips_logos_when_no_image_is_declared():
    html = ("<html><head><title>x</title></head><body><img src='/img/logo.png'><img src='/img/pool.jpg'>"
            "</body></html>")
    page = PageView(PageRecord(id="p", snapshot_id="s", url=f"{B}/"), parse_page(html, f"{B}/"))
    assert og_image(page) == f"{B}/img/pool.jpg"


def test_lazy_hero_images_are_seen_and_template_banners_skipped():
    html = ("<html><head><title>x</title></head><body>"
            "<header><img src='/img/menu-banner.jpg'></header>"
            "<img src='https://www.facebook.com/tr?id=1&ev=PageView'>"
            "<img class='hero lazy' data-src='/img/agra-hero.jpg' alt='Hero'>"
            "<img src='/img/membership-banner.jpg'></body></html>")
    model = parse_page(html, f"{B}/agra")
    hero = next(i for i in model["images"] if "agra-hero" in i["src"])
    assert hero["src"] == f"{B}/img/agra-hero.jpg" and hero["lazy"]
    page = PageView(PageRecord(id="p", snapshot_id="s", url=f"{B}/agra"), model)
    assert og_image(page) == f"{B}/img/agra-hero.jpg"  # not the menu banner or the tracking pixel
    assert og_image(page, {f"{B}/img/agra-hero.jpg"}) == f"{B}/img/membership-banner.jpg"  # template skipped


def test_og_image_must_be_an_image_file():
    html = ("<html><head><title>x</title></head><body><img src='/sterling-circle'>"
            "<img src='/img/circle.jpg.imgw.1280.1280.jpeg'></body></html>")
    page = PageView(PageRecord(id="p", snapshot_id="s", url=f"{B}/"), parse_page(html, f"{B}/"))
    assert og_image(page) == f"{B}/img/circle.jpg.imgw.1280.1280.jpeg"
