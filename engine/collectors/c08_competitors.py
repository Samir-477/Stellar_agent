"""C8 Competitor Capture: who ranks for the client's non-brand searches, and what their ranking
pages look like.

classify: the domains in C6's organic results (non-brand queries), typed by rules first (the client,
listing and social sites) and one LLM call for the rest (direct competitor, aggregator, directory,
publisher). Then one follow-up `fetch` unit per direct competitor (at most 3): its ranking pages (at
most 3), fetched through the SSRF guard, only where the competitor's robots.txt allows us, and
parsed with the same parser as the client's pages.
"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import urljoin, urlsplit

from pydantic import BaseModel, Field

from engine.collectors.base import Collector
from engine.collectors.c02_parser import parse_page
from engine.collectors.search_collectors import _archetype, business_name
from engine.context import CollectorContext, WorkUnit
from engine.core.net import safe_fetch
from engine.lib.locators import text_hash
from engine.lib.robots import parse_robots
from engine.lib.urls import site_label
from engine.llm import LLMError, load_prompt
from engine.rules.packs import pack
from engine.schemas import EvidenceType

MAX_COMPETITORS = 3
PAGES_PER_COMPETITOR = 3
MAX_DOMAINS = 25
BOT_TOKEN = "SiteDiagnosisBot"
LISTING = {"tripadvisor", "booking", "makemytrip", "goibibo", "agoda", "expedia", "trivago", "hotels", "trip",
           "easemytrip", "cleartrip", "yatra", "bankbazaar", "paisabazaar", "amazon", "flipkart", "myntra",
           "indiamart", "tradeindia", "zomato", "swiggy", "hoteles", "hostelworld", "airbnb"}
DIRECTORY = {"justdial", "sulekha", "yellowpages", "asklaila"}
SOCIAL = {"facebook", "instagram", "youtube", "twitter", "x", "linkedin", "reddit", "quora", "pinterest"}
TYPES = {"direct", "aggregator", "directory", "publisher", "social", "other"}


class DomainType(BaseModel):
    id: str
    type: str


class DomainTypes(BaseModel):
    domains: list[DomainType] = Field(default_factory=list)


def _domain(url: str | None) -> str:
    return (urlsplit(url or "").hostname or "").removeprefix("www.")


def rule_type(domain: str, client: str, platforms: set[str]) -> str | None:
    label = site_label(domain)
    if domain == client or domain.endswith("." + client):
        return "client"
    if label in LISTING or label in {site_label(p) for p in platforms}:
        return "aggregator"
    if label in DIRECTORY:
        return "directory"
    if label in SOCIAL:
        return "social"
    return None


def ranking_domains(ctx: CollectorContext) -> dict[str, dict]:
    """Domains in the latest organic results of every non-brand query, with where they ranked."""
    latest: dict[str, dict] = {}
    for ev in ctx.snapshot.evidence(EvidenceType.SERP):
        if ev.payload.get("organic") and ev.payload.get("intent") != "brand":
            latest[ev.payload["query"]] = ev.payload
    out: dict[str, dict] = {}
    for query, payload in latest.items():
        for r in payload["organic"][:10]:
            domain = r.get("domain") or _domain(r.get("link"))
            entry = out.setdefault(domain, {"domain": domain, "count": 0, "best_position": 99, "pages": []})
            entry["count"] += 1
            entry["best_position"] = min(entry["best_position"], r.get("position") or 99)
            entry["pages"].append({"url": r.get("link"), "title": r.get("title"), "query": query,
                                   "position": r.get("position")})
    return out


class CompetitorCapture(Collector):
    id = "C8"
    name = "Competitor Capture"
    produces = frozenset({EvidenceType.COMPETITORS, EvidenceType.COMPETITOR_PAGES})
    requires = frozenset({EvidenceType.SERP, EvidenceType.QUERY_SET, EvidenceType.FACTS, EvidenceType.ARCHETYPE})

    def plan(self, ctx: CollectorContext) -> list[WorkUnit]:
        return [WorkUnit("classify")]

    def run_unit(self, ctx: CollectorContext, unit: WorkUnit) -> list[WorkUnit]:
        if unit.kind == "classify":
            return self._classify(ctx)
        if unit.kind == "fetch":
            asyncio.run(self._fetch(ctx, unit.params["domain"], unit.params["pages"]))
            return []
        raise ValueError(f"unknown unit kind {unit.kind}")

    # ------------------------------------------------------------ classify

    def _classify(self, ctx: CollectorContext) -> list[WorkUnit]:
        existing = ctx.snapshot.evidence(EvidenceType.COMPETITORS)
        if existing:  # a retry: don't pay for the classification twice
            domains = existing[-1].payload["domains"]
        else:
            the_pack = pack(_archetype(ctx))
            client = _domain(ctx.client.primary_url)
            stats = sorted(ranking_domains(ctx).values(), key=lambda d: (-d["count"], d["best_position"]))
            domains = stats[:MAX_DOMAINS]
            for d in domains:
                d["type"] = rule_type(d["domain"], client, set(the_pack.platforms) if the_pack else set())
                d["source"] = "rule" if d["type"] else None
            unknown = [d for d in domains if d["type"] is None]
            note = None
            if unknown and ctx.llm is not None:
                lines = "\n".join(f"D{i} {d['domain']}: " + " | ".join(dict.fromkeys(p["title"] or "" for p in
                                                                                     d["pages"]))[:240]
                                  for i, d in enumerate(unknown, start=1))
                try:
                    answer = ctx.llm.complete_json(load_prompt("c8.domains", 1), DomainTypes, domains=lines,
                                                   business=f"{business_name(ctx)} ({_archetype(ctx)})").data
                    by_id = {t.id: t.type for t in answer.domains if t.type in TYPES}
                    for i, d in enumerate(unknown, start=1):
                        d["type"], d["source"] = by_id.get(f"D{i}", "other"), "llm"
                except LLMError as exc:
                    note = f"classification failed: {exc}"
            for d in domains:
                if d["type"] is None:
                    d["type"], d["source"] = "unclassified", "none"
            ctx.snapshot.add_evidence(self.id, EvidenceType.COMPETITORS, {"domains": domains, "note": note},
                                      source_label="observed")
        # Pages ranking for the client's most important searches first (C5 priority), so the comparison is
        # like for like (a rival's property page, not its banquet-hall page).
        sets = ctx.snapshot.evidence(EvidenceType.QUERY_SET)
        priority = {q["q"]: q.get("priority", 99) for q in (sets[-1].payload.get("queries", []) if sets else [])}
        direct = [d for d in domains if d["type"] == "direct"][:MAX_COMPETITORS]
        return [WorkUnit("fetch", {"domain": d["domain"], "pages": sorted(
            d["pages"], key=lambda p: (priority.get(p["query"], 99), p["position"] or 99))[:PAGES_PER_COMPETITOR]})
            for d in direct]

    # ------------------------------------------------------------ fetch

    async def _fetch(self, ctx: CollectorContext, domain: str, pages: list[dict]) -> None:
        done = {e.payload.get("url") for e in ctx.snapshot.evidence(EvidenceType.COMPETITOR_PAGES)}
        pages = [p for p in dict((p["url"], p) for p in pages).values() if p["url"] not in done]
        if not pages:
            return
        ua = ctx.settings.crawl_user_agent
        async with ctx.http_client() as client:
            origin = f"{urlsplit(pages[0]['url']).scheme}://{urlsplit(pages[0]['url']).netloc}"
            robots_result = await safe_fetch(client, urljoin(origin, "/robots.txt"), user_agent=ua,
                                             max_bytes=500_000, resolver=ctx.resolver)
            robots = parse_robots(robots_result.body.decode("utf-8", "replace")) \
                if robots_result.status == 200 else None
            for p in pages:
                allowed = robots.is_allowed(BOT_TOKEN, p["url"]) if robots else True
                payload = {"domain": domain, "url": p["url"], "query": p["query"], "position": p["position"],
                           "title": p["title"], "robots_allowed": allowed}
                if not allowed:
                    ctx.snapshot.add_evidence(self.id, EvidenceType.COMPETITOR_PAGES, payload)
                    continue
                result = await safe_fetch(client, p["url"], user_agent=ua, max_bytes=ctx.settings.crawl_max_bytes,
                                          resolver=ctx.resolver)
                payload.update(status=result.status, final_url=result.final_url, error=result.error)
                key = None
                if result.status == 200 and result.body and "html" in (result.content_type or ""):
                    model = parse_page(result.body.decode("utf-8", "replace"), result.final_url)
                    key = ctx.snapshot.put_blob(f"snapshots/{ctx.snapshot.snapshot_id}/competitors/"
                                                f"{text_hash(p['url'])}.json", json.dumps(model))
                ctx.snapshot.add_evidence(self.id, EvidenceType.COMPETITOR_PAGES, payload, blob_key=key,
                                          source_label="observed")
