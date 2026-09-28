"""Before/after snippets for a whole run, computed once from the captured pages and cached
next to the run's preview bundle. Recomputed when a patch is missing from the cache; not
cached when a captured page couldn't be read (so a later engine with access fills it in)."""

from __future__ import annotations

import json

import httpx

from engine.core.blobstore import BlobStore
from engine.lib.urls import norm
from engine.output.diffs import page_snippets
from engine.store import Store


FORMAT = 2  # bump when snippet output changes, so older caches are recomputed


def cache_key(run_id: str) -> str:
    return f"share-bundles/{run_id}/snippets-v{FORMAT}.json"


def _read(blobs: BlobStore, key: str) -> bytes | None:
    try:
        return blobs.get(key)
    except (FileNotFoundError, httpx.HTTPStatusError, ValueError):
        return None


def run_snippets(run_id: str, snapshot_id: str, patches: list[dict], store: Store, blobs: BlobStore) -> dict[str, dict]:
    cached = _read(blobs, cache_key(run_id))
    if cached:
        data = json.loads(cached)
        if all(p["key"] in data for p in patches):
            return data

    pages = {}
    for page in store.list_pages(snapshot_id):
        pages[norm(page.url)] = page
        if page.final_url:
            pages.setdefault(norm(page.final_url), page)
    by_page: dict[str | None, list[dict]] = {}
    for patch in patches:
        by_page.setdefault(patch.get("page_url"), []).append(patch)

    out: dict[str, dict] = {}
    complete = True
    for url, group in by_page.items():
        page = pages.get(norm(url)) if url else None
        raw = _read(blobs, page.raw_html_key) if page and page.raw_html_key else None
        if url and raw is None:
            complete = False
        out.update(page_snippets(raw.decode("utf-8", errors="replace") if raw else None, group))
    if complete:
        blobs.put(cache_key(run_id), json.dumps(out).encode("utf-8"))
    return out
