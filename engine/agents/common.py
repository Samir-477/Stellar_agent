"""Evidence loading helpers shared by agents (read-only; no agent outputs)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from engine.context import AgentContext
from engine.lib.urls import norm
from engine.schemas import EvidenceType
from engine.store import PageRecord


@dataclass
class PageView:
    record: PageRecord
    model: dict[str, Any] | None  # parsed page model from C2, if parsed

    @property
    def url(self) -> str:
        return self.record.final_url or self.record.url

    @property
    def status(self) -> int | None:
        return self.record.status

    @property
    def headers(self) -> dict[str, str]:
        return self.record.fetch.get("headers", {}) or {}

    @property
    def is_home(self) -> bool:
        return urlsplit(self.url).path in ("", "/")

    @property
    def is_html(self) -> bool:
        return self.status == 200 and bool(self.model) and not self.model.get("parse_error")

    def visible_text(self) -> str:
        """Title, headings and passages: what a reader sees (template placeholders removed)."""
        if not self.model:
            return ""
        parts = [self.model.get("title") or ""] + [h["text"] for h in self.model.get("headings", [])]
        parts += [p["text"] for p in self.model.get("passages", []) if "{{" not in p["text"]]
        return " \n".join(parts)


def load_pages(ctx: AgentContext, with_models: bool = True) -> list[PageView]:
    views = []
    parsed = {e.page_id: e for e in ctx.snapshot.evidence(EvidenceType.PAGES_PARSED)} if with_models else {}
    for record in ctx.snapshot.pages():
        model = None
        if record.id in parsed and parsed[record.id].blob_key:
            model = ctx.snapshot.blob_json(parsed[record.id].blob_key)
        views.append(PageView(record, model))
    views.sort(key=lambda v: (not v.is_home, v.url))
    return views


def key_page_urls(pages: list[PageView], entry_url: str | None = None) -> set[str]:
    """Key pages: the client's entry page, the homepage, and pages linked from the
    homepage's header/nav (a proxy for the site's top pages). Footer links (privacy,
    terms, careers) are deliberately not key pages."""
    keys: set[str] = set()
    if entry_url:
        entry = norm(entry_url)
        keys.update(p.url for p in pages if norm(p.record.url) == entry or norm(p.url) == entry)
    home = next((p for p in pages if p.is_home), None)
    if home is not None:
        keys.add(home.url)
        if home.model:
            keys.update(link["href"] for link in home.model.get("links", [])
                        if link.get("internal") and link.get("in_nav"))
    return keys


def entry_page(pages: list[PageView], entry_url: str) -> PageView | None:
    entry = norm(entry_url)
    return next((p for p in pages if norm(p.record.url) == entry or norm(p.url) == entry), None)


_norm = norm  # backwards-compatible alias


def site_file(ctx: AgentContext, kind: str) -> tuple[dict[str, Any] | None, str | None]:
    """(fetch summary, text) for a site file captured by C1, e.g. 'robots.txt'."""
    for ev in ctx.snapshot.evidence(EvidenceType.SITE_FILES):
        if ev.payload.get("kind") == kind:
            text = ctx.snapshot.blob_text(ev.blob_key) if ev.blob_key else None
            return ev.payload, text
    return None, None


def sample_info(ctx: AgentContext) -> dict[str, Any]:
    info, _ = site_file(ctx, "sample")
    return info or {}


def fact_sheet(ctx: AgentContext) -> list[dict]:
    """Latest C4 facts (both site-stated and schema-declared; check `status`)."""
    evidence = ctx.snapshot.evidence(EvidenceType.FACTS)
    return evidence[-1].payload.get("facts", []) if evidence else []


def business_name(ctx: AgentContext) -> str:
    """The property or business name as the site states it (C4), else the client's name."""
    for key in ("property_name", "business_name"):
        for fact in fact_sheet(ctx):
            if fact["key"] == key and fact["status"] == "site-stated":
                return fact["value"]
    return ctx.client.name


GENERIC_NAME_WORDS = {"hotel", "hotels", "resort", "resorts", "holiday", "holidays", "limited", "private", "group",
                      "india", "the", "and", "pvt", "ltd", "services", "company", "finance", "logistics"}


def name_tokens(*names: str) -> set[str]:
    """Distinctive words of the business's names ("sterling", "regalia"): for checking that a
    definition names the business, and for ignoring the name when counting repeated phrases."""
    return {w for name in names for w in re.findall(r"[a-z0-9]+", (name or "").lower())
            if len(w) >= 4 and w not in GENERIC_NAME_WORDS}


def place_words(ctx: AgentContext) -> set[str]:
    """Words of the places the business states or declares: city, locations and the landmarks it
    is near ("taj", "mahal"). Street addresses are left out: they often contain the business's own
    name ("Sterling Rampath, Ayodhya"), which would stop it counting as a brand word."""
    words: set[str] = set()
    for fact in fact_sheet(ctx):
        if fact["key"] in ("city", "locations_served", "distance_to_landmark", "nearby_attractions"):
            words |= set(re.findall(r"[a-z]+", fact["value"].lower()))
    return words


def brand_tokens(ctx: AgentContext, *extra_names: str) -> set[str]:
    """Distinctive words of the business's names without place names: "sterling", "regalia", not
    "agra". A place word would make every search about the city look like a brand search."""
    return name_tokens(business_name(ctx), ctx.client.name, *extra_names) - place_words(ctx)


def tally(*parts: tuple[int, str]) -> str:
    """Counts as client-facing prose, leaving out zeros: tally((2, "pages without an H1"),
    (0, "pages with competing H1s")) → "2 pages without an H1"."""
    items = [f"{n} {text}" for n, text in parts if n]
    return " and ".join(items) if len(items) <= 2 else ", ".join(items[:-1]) + " and " + items[-1]


def archetype(ctx: AgentContext) -> str | None:
    evidence = ctx.snapshot.evidence(EvidenceType.ARCHETYPE)
    return evidence[-1].payload.get("archetype") if evidence else ctx.client.archetype
