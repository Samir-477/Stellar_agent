"""Microsites (user decision, 2026-09-28): once the Output preview of a run's diagnosed URL is
approved, the fixed page is published at /microsites/{archetype}/{client_slug}/{page_path}.

A microsite is one immutable version: the fixed page, the page with every change marked, the
original, and the issues found on that page with their before/after code. Publishing the same
slug again supersedes the live version; history is kept. The Next.js app serves it publicly with
noindex (it copies the client's own page, so it must never compete with it in search).
"""

from __future__ import annotations

import re
import uuid
from urllib.parse import urlsplit

from lxml import html as lxml_html

from engine.core.blobstore import BlobStore
from engine.issues import build_issue_cards
from engine.lib.urls import norm
from engine.orchestrator import repo
from engine.output.diffs import page_snippets
from engine.output.patcher import apply
from engine.store import Store

ARCHETYPES = ("hospitality", "loans", "retail", "logistics")
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_ISSUES = 40


class MicrositeError(ValueError):
    """A run that can't be published yet, with a reason a person can act on."""


def slugify(text: str, limit: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].strip("-")


def page_path(url: str) -> str:
    """The URL's full path as a slug path: /resorts-hotels/Shivalik-Chail.html → resorts-hotels/shivalik-chail."""
    segments = [slugify(re.sub(r"\.(html?|php|aspx?)$", "", s, flags=re.I)) for s in urlsplit(url).path.split("/")]
    return "/".join(s for s in segments if s) or "home"


def slug_of(archetype: str, client_slug: str, path: str) -> str:
    return f"{archetype}/{client_slug}/{path}"


def _page_for(store: Store, snapshot_id: str, url: str):
    target = norm(url)
    return next((p for p in store.list_pages(snapshot_id) if target in (norm(p.url), norm(p.final_url or p.url))), None)


def build_microsite(run_id: str, store: Store, blobs: BlobStore, *, client_slug: str | None = None,
                    published_by: str | None = None) -> dict:
    run = repo.get_run(run_id)
    if run is None:
        raise MicrositeError("Run not found.")
    if run["status"] not in ("completed", "completed_partial"):
        raise MicrositeError("The run hasn't finished yet.")
    ctx = repo.run_context(run_id)
    archetype = repo.run_archetype(ctx)
    if archetype not in ARCHETYPES:
        raise MicrositeError("Confirm the business type for this client before publishing.")
    client_slug = client_slug or slugify(ctx["name"])
    if not SLUG.match(client_slug or ""):
        raise MicrositeError("The client part of the address may use only lowercase letters, numbers and hyphens.")

    url = ctx["primary_url"]
    page = _page_for(store, str(run["snapshot_id"]), url)
    if page is None or not page.raw_html_key:
        raise MicrositeError("The diagnosed page wasn't captured in this run, so there is nothing to publish.")
    try:
        raw = blobs.get(page.raw_html_key).decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - storage errors differ by backend
        raise MicrositeError("The captured page isn't in this engine's storage.") from exc

    page_urls = {norm(page.url), norm(page.final_url or page.url)}
    patches = [p for p in repo.list_patches(run_id) if p.get("page_url") and norm(p["page_url"]) in page_urls]
    findings = repo.list_findings(run_id)
    titles = {key: f["title"] for f in findings for key in f.get("patch_keys", [])}
    for patch in patches:
        patch["title"] = titles.get(patch["key"], "Suggested change")
    base = page.final_url or page.url
    result = apply(raw, base, patches)
    original = apply(raw, base, []).fixed_html
    snippets = page_snippets(raw, patches)

    cards = []
    for card in build_issue_cards(findings, patches, snippets):
        on_page = any(norm(p) in page_urls for p in card["pages"]) or bool(card["changes"])
        if not on_page or card["fix_type"] == "observation":
            continue
        changes = [c for c in card["changes"] if c["page_url"] and norm(c["page_url"]) in page_urls]
        cards.append({k: card[k] for k in ("agent_id", "agent_name", "check_id", "status", "severity", "title",
                                           "impact", "fix", "fix_type")}
                     | {"fixed": any(c["key"] in result.placed for c in changes),
                        "changes": [{k: c[k] for k in ("type", "language", "before", "after", "before_segments",
                                                       "after_segments", "note")} for c in changes]})
    cards.sort(key=lambda c: not c["fixed"])

    title = (lxml_html.fromstring(raw).findtext(".//title") or "").strip() or None
    micro_id = str(uuid.uuid4())
    prefix = f"share-bundles/microsites/{micro_id}"
    record = {
        "id": micro_id, "client_id": str(ctx["client_id"]), "run_id": run_id, "archetype": archetype,
        "client_slug": client_slug, "page_path": page_path(url), "client_name": ctx["name"], "source_url": url,
        "page_title": title,
        "fixed_key": blobs.put(f"{prefix}/fixed.html", result.fixed_html.encode("utf-8")),
        "annotated_key": blobs.put(f"{prefix}/annotated.html", result.annotated_html.encode("utf-8")),
        "original_key": blobs.put(f"{prefix}/original.html", original.encode("utf-8")),
        "issues": cards[:MAX_ISSUES], "changes_placed": len(result.placed), "changes_total": len(patches),
        "published_by": published_by,
    }
    return repo.insert_microsite(record)
