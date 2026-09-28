"""Golden test: a small loans site with planted issues → C1 → C2 → S1.

Each planted issue must produce exactly the expected check status.
"""

from engine.agents.seo.s01_crawl_index import CrawlIndexHealth
from engine.collectors.c01_crawler import SiteCrawler
from engine.collectors.c02_parser import PageParser
from engine.context import AgentContext, ClientProfile, CollectorContext
from engine.core.blobstore import LocalBlobStore
from engine.reports import build_agent_report, check_statuses
from engine.schemas import CheckStatus as St
from engine.store import MemoryStore, SnapshotReader, SnapshotWriter
from engine.validation import validate_result
from tests.conftest import fake_resolver, site_transport

BASE = "https://example.in"
HTML = {"content-type": "text/html; charset=utf-8"}
LOAN_TEXT = ("Personal loans from Example Finance start at 10.5% per annum for salaried applicants in Pune. "
             "You can borrow between 50,000 and 25 lakh rupees for up to 60 months with no collateral. " * 3)


def page(title, body, *, lang="en", canonical=None, robots=None, head=""):
    lang_attr = f' lang="{lang}"' if lang else ""
    tags = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    tags += f'<meta name="robots" content="{robots}">' if robots else ""
    nav = ('<header><nav><a href="/about">About</a> <a href="/contact">Contact</a> '
           '<a href="/loans/personal">Personal loans</a></nav></header>')
    return (f"<!doctype html><html{lang_attr}><head><title>{title}</title>{tags}{head}</head>"
            f"<body>{nav}<main>{body}</main><footer>© Example</footer></body></html>")


ROUTES = {
    f"{BASE}/": (200, HTML, page("Example Finance | Loans in Pune",
                                 '<h1>Loans in Pune</h1><p>Example Finance offers personal and home loans across '
                                 'Pune with quick approval and transparent fees for salaried and self-employed '
                                 'customers.</p><a href="/old">Old offer</a> <a href="/loans/home">Home loans</a>',
                                 canonical=f"{BASE}/", head='<script src="http://cdn.example.in/app.js"></script>')),
    f"{BASE}/robots.txt": (200, {"content-type": "text/plain"},
                           "User-agent: *\nDisallow: /private\nSitemap: https://example.in/sitemap.xml\n"),
    f"{BASE}/sitemap.xml": (200, {"content-type": "application/xml"},
                            '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                            + "".join(f"<url><loc>{BASE}{p}</loc></url>"
                                      for p in ["/", "/about", "/loans/personal", "/loans/home", "/contact", "/thin"])
                            + "</urlset>"),
    f"{BASE}/about": (200, HTML, page("About Example Finance", "<h1>About us</h1><p>" + "We are a lender. " * 20 + "</p>",
                                      lang=None, canonical=f"{BASE}/about", robots="noindex, follow")),
    f"{BASE}/loans/personal": (200, HTML, page("Personal Loans in Pune", f"<h1>Personal loans</h1><p>{LOAN_TEXT}</p>",
                                               canonical=f"{BASE}/loans/personal")),
    f"{BASE}/loans/home": (200, HTML, page("Home Loans in Pune", f"<h1>Personal loans</h1><p>{LOAN_TEXT}</p>")),
    f"{BASE}/thin": (200, HTML, page("Page not found", "<h1>Sorry</h1><p>This page no longer exists.</p>",
                                     canonical=f"{BASE}/thin")),
    f"{BASE}/old": (301, {"location": f"{BASE}/older"}, ""),
    f"{BASE}/older": (301, {"location": f"{BASE}/oldest"}, ""),
    f"{BASE}/oldest": (301, {"location": f"{BASE}/loans/personal"}, ""),
    "http://example.in/": (301, {"location": f"{BASE}/"}, ""),
    "http://www.example.in/": (301, {"location": f"{BASE}/"}, ""),
    "https://www.example.in/": (200, HTML, page("Example Finance | Loans in Pune", "<h1>Loans</h1>")),
}


def run_collector(collector, ctx):
    queue = collector.plan(ctx)
    while queue:
        queue.extend(collector.run_unit(ctx, queue.pop(0)))


def test_s1_finds_planted_issues(settings, tmp_path):
    store, blobs = MemoryStore(), LocalBlobStore(tmp_path / "blobs")
    client = ClientProfile(id="c1", name="Example Finance", primary_url=f"{BASE}/")
    cctx = CollectorContext(snapshot=SnapshotWriter(store, blobs, "snap-1"), client=client, settings=settings,
                            http_transport=site_transport(ROUTES), resolver=fake_resolver)
    run_collector(SiteCrawler(), cctx)
    run_collector(PageParser(), cctx)

    agent = CrawlIndexHealth()
    actx = AgentContext(snapshot=SnapshotReader(store, blobs, "snap-1"), client=client, settings=settings)
    result = agent.reduce(actx, [agent.run_unit(actx, unit) for unit in agent.plan(actx)])
    page_urls = {p.final_url or p.url for p in store.pages.values()}
    result, errors = validate_result(agent, result, page_urls)
    assert errors == []

    assert check_statuses(agent, result.findings) == {
        "S1.01": St.FAIL,   # /contact is 404
        "S1.02": St.FAIL,   # /thin says "Page not found" with 200
        "S1.03": St.FAIL,   # /old → /older → /oldest → /loans/personal
        "S1.04": St.FAIL,   # /about (a nav/key page) is noindex
        "S1.05": St.PASS,   # robots.txt only blocks /private
        "S1.06": St.WARN,   # /loans/home has no canonical
        "S1.07": St.FAIL,   # 1 of 6 sampled sitemap URLs is a 404 (≥10%)
        "S1.08": St.WARN,   # https://www.example.in/ serves 200 without redirecting
        "S1.09": St.FAIL,   # /loans/home duplicates /loans/personal without a shared canonical
        "S1.10": St.FAIL,   # http:// script on an https page
        "S1.11": St.WARN,   # /about has no lang
    }

    by_check = {f.check_id: f for f in result.findings}
    assert by_check["S1.01"].severity == "high"  # key page, but a 404 doesn't block the site: never escalated to critical
    assert by_check["S1.04"].scope.pages == [f"{BASE}/about"]
    assert {p.type.value for p in result.patches} == {"head_upsert", "attribute_set"}

    report = build_agent_report(agent, result)
    assert (report.scorecard["fail"], report.scorecard["warn"], report.scorecard["pass"]) == (7, 3, 1)
    assert report.issues_to_fix[0]["severity"] == "critical"  # S1.04: key page noindex is explicitly critical
    assert len(report.proposed_changes) == len(result.patches)
    assert report.scope_and_evidence["signature_table"]["columns"][0] == "URL"
