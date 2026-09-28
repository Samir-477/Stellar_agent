"""Regression tests for false positives found on the first real client crawl (2026-09-27)."""

from engine.agents.seo.s01_crawl_index import CrawlIndexHealth
from engine.collectors.c01_crawler import SiteCrawler
from engine.collectors.c02_parser import PageParser, parse_page
from engine.context import AgentContext, ClientProfile, CollectorContext
from engine.core.blobstore import LocalBlobStore
from engine.lib.content import jaccard, own_text, shingles, template_blocks
from engine.reports import check_statuses
from engine.schemas import CheckStatus as St
from engine.store import MemoryStore, SnapshotReader, SnapshotWriter
from tests.conftest import fake_resolver, site_transport
from tests.test_s1_golden import run_collector

BASE = "https://hotel.example"
HTML = {"content-type": "text/html"}
WIDGET = "".join(f"<li>Book a holiday option {i}: single city, multi city, corporate booking, pet friendly resorts</li>"
                 for i in range(12))


def doc(title, body, footer='<footer><a href="/privacy-policy">Privacy</a></footer>'):
    return (f'<!doctype html><html lang="en"><head><title>{title}</title>'
            f'<link rel="canonical" href="{BASE}/{title.lower()}"></head><body>'
            f'<header><nav><a href="/rooms">Rooms</a></nav></header>'
            f'<div class="booking-modal"><ul>{WIDGET}</ul></div><main>{body}</main>{footer}</body></html>')


def test_shared_widget_text_is_not_counted_as_page_content():
    awards = parse_page(doc("awards", "<p>" + "Travellers' Choice award winner for five straight years. " * 12 + "</p>"),
                        f"{BASE}/awards")
    media = parse_page(doc("media", "<p>" + "Press releases and news coverage from national newspapers. " * 12 + "</p>"),
                       f"{BASE}/media")
    rooms = parse_page(doc("rooms", "<p>" + "Deluxe rooms with a view of the Taj Mahal and a private balcony. " * 12 + "</p>"),
                       f"{BASE}/rooms")
    template = template_blocks([awards, media, rooms])
    assert template  # the booking widget
    a, m = own_text(awards, template), own_text(media, template)
    assert "Book a holiday" not in a
    assert jaccard(shingles(a), shingles(m)) < 0.2


def test_footer_links_are_not_key_pages_and_cdn_cgi_is_not_crawled(settings, tmp_path):
    routes = {
        f"{BASE}/": (200, HTML, doc("home", "<p>Heritage hotel near the Taj Mahal in Agra with rooftop dining. " * 5
                                    + '</p><a href="/cdn-cgi/l/email-protection">email</a>')),
        f"{BASE}/robots.txt": (200, {"content-type": "text/plain"}, "User-agent: *\nDisallow: /privacy-policy\n"),
        f"{BASE}/rooms": (200, HTML, doc("rooms", "<p>Deluxe rooms with a view of the Taj Mahal. " * 10 + "</p>")),
        f"{BASE}/privacy-policy": (200, HTML, doc("privacy", "<p>We protect your personal data carefully. " * 10 + "</p>")),
    }
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "blobs")
    client = ClientProfile(id="c", name="Hotel", primary_url=f"{BASE}/")
    cctx = CollectorContext(SnapshotWriter(store, blobs, "s"), client, settings,
                            http_transport=site_transport(routes), resolver=fake_resolver)
    run_collector(SiteCrawler(), cctx)
    run_collector(PageParser(), cctx)
    assert not any("/cdn-cgi/" in p.url for p in store.pages.values())

    agent = CrawlIndexHealth()
    actx = AgentContext(SnapshotReader(store, blobs, "s"), client, settings)
    result = agent.run_unit(actx, agent.plan(actx)[0])
    statuses = check_statuses(agent, result.findings)
    assert statuses["S1.05"] == St.PASS  # blocking a footer-only privacy page is a normal choice
    assert statuses["S1.09"] == St.PASS  # shared booking widget ≠ duplicate content


def test_parser_keeps_footer_text_and_separates_block_elements():
    from engine.collectors.c02_parser import parse_page
    html = ("<html><body><main><h1>How to get a home loan</h1><p>By Priya Sharma</p></main>"
            "<footer><p>Grand Finance Ltd, CIN U65910MH1995PLC012345</p><footer><p>nested</p></footer>"
            "<div class='modal'><h4>Cancellation Policy</h4><li>More than {{r.days}} days</li></div>"
            "<script>var x = 1;</script></footer></body></html>")
    model = parse_page(html, "https://grand.example/blog/guide")
    assert "home loan By Priya Sharma" in model["main_text_sample"]  # not "loanBy"
    assert model["footer_text"] == ("Grand Finance Ltd, CIN U65910MH1995PLC012345 nested Cancellation Policy "
                                    "More than {{r.days}} days")
