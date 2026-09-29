"""C1 Site Crawler: raw HTML, fetch metadata, site files, URL variants, AI user-agent probes.

Units:
  discover  robots.txt, sitemaps, llms.txt, homepage, URL-variant probes, AI UA probes,
            then choose the page sample and fan out `fetch` batches
  fetch     fetch a batch of sampled pages (default 5 per unit)

Rendering (browser DOM) is delegated to the renderer service when RENDERER_URL is
set; otherwise pages are marked render_status="skipped".

The client's own site is crawled with recorded consent, so its robots.txt is
recorded and diagnosed (S1, G1) rather than obeyed. Competitor crawling (C8)
obeys robots.txt.
"""

from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

from lxml import html as lxml_html

from engine.collectors.base import Collector
from engine.context import CollectorContext, WorkUnit
from engine.core.net import FetchResult, safe_fetch
from engine.schemas import EvidenceType
from engine.store import PageRecord, new_id

FETCH_BATCH = 5
MAX_SITEMAPS = 5
MAX_SITEMAP_URLS = 2000

# AI crawler user agents probed by G1 (search crawlers first).
AI_USER_AGENTS = {
    "OAI-SearchBot": "Mozilla/5.0 (compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)",
    "ChatGPT-User": "Mozilla/5.0 (compatible; ChatGPT-User/1.0; +https://openai.com/bot)",
    "Claude-SearchBot": "Mozilla/5.0 (compatible; Claude-SearchBot/1.0; +https://www.anthropic.com)",
    "PerplexityBot": "Mozilla/5.0 (compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)",
    "GPTBot": "Mozilla/5.0 (compatible; GPTBot/1.1; +https://openai.com/gptbot)",
    "ClaudeBot": "Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)",
}

_SKIP_PATH = re.compile(r"^/cdn-cgi/")  # Cloudflare internals (email protection, challenges)
_SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|webp|avif|svg|zip|rar|mp4|mp3|docx?|xlsx?|pptx?|css|js|json|xml)$",
                       re.I)
# Screens nobody reaches from a search: sign-in, account, cart, checkout, settings and site search. Sampling
# them wastes the crawl cap on pages with nothing to diagnose, and their (correct) noindex reads as a problem.
_UTILITY_SEGMENTS = {
    "login", "logout", "signin", "sign-in", "signup", "sign-up", "register", "account", "my-account", "myaccount",
    "profile", "orders", "cart", "viewcart", "basket", "checkout", "wishlist", "favourites", "favorites",
    "preferences", "communication-preferences", "settings", "password", "forgot-password", "reset-password",
    "auth", "oauth", "sso", "search", "searchsuggestion", "unsubscribe", "notifications",
}
_TRACKING_PARAM = re.compile(r"^(utm_[a-z]+|gclid|fbclid|msclkid|srsltid|otracker\d*)$", re.I)


def normalize_url(url: str) -> str:
    """Lowercase scheme and host, no fragment, and no tracking parameters (so one page isn't sampled twice)."""
    parts = urlsplit(url.strip())
    path = parts.path or "/"
    query = "&".join(p for p in parts.query.split("&") if p and not _TRACKING_PARAM.match(p.split("=", 1)[0]))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def is_utility(url: str) -> bool:
    return any(segment.lower() in _UTILITY_SEGMENTS for segment in urlsplit(url).path.split("/") if segment)


def _host(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


def template_group(url: str) -> str:
    """Rough template key from the URL shape: first path segment + depth."""
    segments = [s for s in urlsplit(url).path.split("/") if s]
    if not segments:
        return "home"
    return f"{segments[0]}/{len(segments)}"


def _round_robin(urls: list[str]) -> list[str]:
    """Interleave URL template groups so every template appears before any repeats."""
    groups: OrderedDict[str, list[str]] = OrderedDict()
    for url in urls:
        groups.setdefault(template_group(url), []).append(url)
    ordered = []
    while any(groups.values()):
        for key in list(groups):
            if groups[key]:
                ordered.append(groups[key].pop(0))
    return ordered


def choose_sample(entry: str, candidates: list[str], cap: int, *, entry_links: list[str] | None = None,
                  site_home: str | None = None) -> list[str]:
    """Pick up to `cap` pages, closest to the client's entry page first:

    1. the entry page (the URL the client gave us, often a deep page)
    2. the site homepage (site-wide checks need it)
    3. pages in the entry page's section (same path prefix)
    4. pages linked from the entry page
    5. everything else
    Within each tier, URL template groups are interleaved.
    """
    prefix = urlsplit(entry).path.rstrip("/") + "/"
    linked = set(entry_links or [])
    seen = {entry}
    section, near, rest = [], [], []
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        path = urlsplit(url).path
        if prefix != "/" and path.startswith(prefix):
            section.append(url)
        elif url in linked:
            near.append(url)
        else:
            rest.append(url)
    head = [entry] + ([site_home] if site_home and site_home != entry else [])
    ordered = head + _round_robin(section) + _round_robin(near) + _round_robin(rest)
    return list(dict.fromkeys(ordered))[:cap]


def parse_robots_sitemaps(robots_txt: str) -> list[str]:
    return [line.split(":", 1)[1].strip() for line in robots_txt.splitlines()
            if line.lower().startswith("sitemap:")]


def parse_sitemap(xml_bytes: bytes) -> tuple[list[str], list[str]]:
    """Return (page_urls, child_sitemap_urls)."""
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return [], []
    tag = root.tag.split("}")[-1]
    locs = [el.text.strip() for el in root.iter() if el.tag.split("}")[-1] == "loc" and el.text]
    return ([], locs) if tag == "sitemapindex" else (locs, [])


def extract_links(page_html: str, base_url: str) -> list[str]:
    try:
        doc = lxml_html.fromstring(page_html)
    except (ValueError, lxml_html.etree.ParserError):
        return []
    links = []
    for href in doc.xpath("//a/@href"):
        absolute = urljoin(base_url, href)
        if absolute.startswith(("http://", "https://")):
            links.append(normalize_url(absolute))
    return links


def _fetch_summary(result: FetchResult) -> dict:
    return {
        "url": result.url,
        "final_url": result.final_url,
        "status": result.status,
        "headers": result.headers,
        "redirects": result.redirects,
        "elapsed_ms": result.elapsed_ms,
        "error": result.error,
        "truncated": result.truncated,
        "bytes": len(result.body),
    }


class SiteCrawler(Collector):
    id = "C1"
    name = "Site Crawler"
    produces = frozenset({EvidenceType.PAGES_RAW, EvidenceType.SITE_FILES, EvidenceType.URL_VARIANTS,
                          EvidenceType.AI_UA_PROBES})

    def plan(self, ctx: CollectorContext) -> list[WorkUnit]:
        return [WorkUnit("discover")]

    def run_unit(self, ctx: CollectorContext, unit: WorkUnit) -> list[WorkUnit]:
        if unit.kind == "discover":
            return asyncio.run(self._discover(ctx))
        if unit.kind == "fetch":
            asyncio.run(self._fetch_batch(ctx, unit.params["page_ids"]))
            return []
        raise ValueError(f"unknown unit kind {unit.kind}")

    # ------------------------------------------------------------ discover

    async def _get(self, ctx: CollectorContext, client, url: str, ua: str | None = None) -> FetchResult:
        return await safe_fetch(client, url, user_agent=ua or ctx.settings.crawl_user_agent,
                                max_bytes=ctx.settings.crawl_max_bytes, resolver=ctx.resolver)

    async def _discover(self, ctx: CollectorContext) -> list[WorkUnit]:
        snap, base = ctx.snapshot, normalize_url(ctx.client.primary_url)
        site_root = urlunsplit(urlsplit(base)[:2] + ("/", "", ""))
        async with ctx.http_client() as client:
            home = await self._get(ctx, client, base)
            if home.status is None:
                raise RuntimeError(f"homepage unreachable: {home.error}")
            origin = urlunsplit(urlsplit(home.final_url)[:2] + ("/", "", ""))

            robots, llms = await asyncio.gather(self._get(ctx, client, urljoin(origin, "/robots.txt")),
                                                self._get(ctx, client, urljoin(origin, "/llms.txt")))
            self._store_site_file(ctx, "robots.txt", robots)
            self._store_site_file(ctx, "llms.txt", llms)

            sitemap_urls = parse_robots_sitemaps(robots.text) if robots.status == 200 else []
            sitemap_urls = sitemap_urls or [urljoin(origin, "/sitemap.xml")]
            page_urls = await self._read_sitemaps(ctx, client, sitemap_urls)

            await self._probe_variants(ctx, client, home.final_url)
            await self._probe_ai_agents(ctx, client, home)

        self._record_page(ctx, base, home)
        site_host = _host(home.final_url)
        entry_links = extract_links(home.text, home.final_url)
        candidates = [u for u in entry_links + page_urls
                      if _host(u) == site_host and not _SKIP_EXT.search(urlsplit(u).path)
                      and not _SKIP_PATH.match(urlsplit(u).path) and not is_utility(u)]
        sample = choose_sample(normalize_url(home.final_url), candidates, ctx.client.crawl_cap,
                               entry_links=entry_links, site_home=normalize_url(origin))
        snap.add_evidence(self.id, EvidenceType.SITE_FILES,
                          {"kind": "sample", "site_root": site_root, "origin": origin,
                           "sitemap_url_count": len(page_urls), "candidate_count": len(candidates),
                           "sample": sample, "sample_in_sitemap": [u for u in sample if u in set(page_urls)]},
                          source_label="derived")

        pending = []
        for url in sample[1:]:
            page = snap.add_page(PageRecord(id=new_id(), snapshot_id=snap.snapshot_id, url=url))
            pending.append(page.id)
        return [WorkUnit("fetch", {"page_ids": pending[i:i + FETCH_BATCH]})
                for i in range(0, len(pending), FETCH_BATCH)]

    def _store_site_file(self, ctx: CollectorContext, name: str, result: FetchResult) -> None:
        key = None
        if result.status == 200 and result.body:
            key = ctx.snapshot.put_blob(f"snapshots/{ctx.snapshot.snapshot_id}/site/{name}", result.body)
        ctx.snapshot.add_evidence(self.id, EvidenceType.SITE_FILES,
                                  {"kind": name, **_fetch_summary(result)}, blob_key=key, source_label="observed")

    async def _read_sitemaps(self, ctx: CollectorContext, client, roots: list[str]) -> list[str]:
        queue, seen, pages = list(roots), set(), []
        while queue and len(seen) < MAX_SITEMAPS and len(pages) < MAX_SITEMAP_URLS:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            result = await self._get(ctx, client, url)
            found, children = parse_sitemap(result.body) if result.status == 200 else ([], [])
            key = None
            if result.status == 200 and result.body:
                key = ctx.snapshot.put_blob(
                    f"snapshots/{ctx.snapshot.snapshot_id}/site/sitemap-{len(seen)}.xml", result.body)
            ctx.snapshot.add_evidence(self.id, EvidenceType.SITE_FILES,
                                      {"kind": "sitemap", "url_count": len(found), "child_count": len(children),
                                       **_fetch_summary(result)}, blob_key=key, source_label="observed")
            pages.extend(normalize_url(u) for u in found)
            queue.extend(children)
        return pages[:MAX_SITEMAP_URLS]

    async def _probe_variants(self, ctx: CollectorContext, client, final_home: str) -> None:
        host = _host(final_home)
        variants = [f"{scheme}://{prefix}{host}/" for scheme in ("http", "https") for prefix in ("", "www.")]
        results = await asyncio.gather(*(self._get(ctx, client, v) for v in variants))
        ctx.snapshot.add_evidence(
            self.id, EvidenceType.URL_VARIANTS,
            {"canonical_home": final_home,
             "variants": [{"variant": v, "final_url": r.final_url, "status": r.status, "error": r.error,
                           "redirects": r.redirects} for v, r in zip(variants, results)]},
            source_label="observed")

    async def _probe_ai_agents(self, ctx: CollectorContext, client, browser_home: FetchResult) -> None:
        names = list(AI_USER_AGENTS)
        results = await asyncio.gather(*(self._get(ctx, client, browser_home.final_url, AI_USER_AGENTS[n])
                                         for n in names))
        ctx.snapshot.add_evidence(
            self.id, EvidenceType.AI_UA_PROBES,
            {"url": browser_home.final_url,
             "browser": {"status": browser_home.status, "bytes": len(browser_home.body)},
             "agents": [{"agent": n, "status": r.status, "bytes": len(r.body), "error": r.error,
                         "final_url": r.final_url} for n, r in zip(names, results)]},
            source_label="observed")

    # --------------------------------------------------------------- fetch

    def _record_page(self, ctx: CollectorContext, url: str, result: FetchResult,
                     page: PageRecord | None = None) -> PageRecord:
        snap = ctx.snapshot
        page = page or snap.add_page(PageRecord(id=new_id(), snapshot_id=snap.snapshot_id, url=url))
        page.final_url, page.status, page.fetch = result.final_url, result.status, _fetch_summary(result)
        is_html = "html" in result.content_type or result.body.lstrip()[:15].lower().startswith(b"<!doctype html")
        if result.body and is_html:
            page.raw_html_key = snap.put_blob(f"snapshots/{snap.snapshot_id}/pages/{page.id}/raw.html", result.body)
        page.render_status = "skipped" if not ctx.settings.renderer_url else "pending"
        snap.update_page(page)
        snap.add_evidence(self.id, EvidenceType.PAGES_RAW, {"is_html": is_html, **_fetch_summary(result)},
                          page_id=page.id, blob_key=page.raw_html_key, source_label="observed")
        return page

    async def _fetch_batch(self, ctx: CollectorContext, page_ids: list[str]) -> None:
        pages = {p.id: p for p in ctx.snapshot.pages() if p.id in set(page_ids)}
        semaphore = asyncio.Semaphore(ctx.settings.crawl_concurrency)
        async with ctx.http_client() as client:
            async def one(page: PageRecord) -> tuple[PageRecord, FetchResult]:
                async with semaphore:
                    return page, await self._get(ctx, client, page.url)
            results = await asyncio.gather(*(one(p) for p in pages.values()))
        for page, result in results:
            self._record_page(ctx, page.url, result, page)
