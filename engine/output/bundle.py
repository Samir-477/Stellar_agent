"""Build the share bundle for a run: per page an annotated and a fixed HTML document,
plus a manifest (client summary, readiness, per-page changes, under-the-hood items).

Only approved/edited patches are included, unless include_proposed=True (used for
internal previews before the team has reviewed patches).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from engine.core.blobstore import BlobStore
from engine.core.db import connection
from engine.orchestrator import repo
from engine.output.patcher import apply
from engine.store import Store


def _patches_for_run(run_id: str, include_proposed: bool) -> list[dict]:
    statuses = ("approved", "edited", "proposed") if include_proposed else ("approved", "edited")
    with connection() as conn:
        rows = conn.execute("select payload, review_status from patches where run_id=%s and review_status = any(%s) "
                            "order by agent_id, key", (run_id, list(statuses))).fetchall()
    return [{**r["payload"], "review_status": r["review_status"]} for r in rows]


def _titles_by_patch(run_id: str) -> dict[str, str]:
    titles = {}
    for finding in repo.list_findings(run_id):
        for key in finding.get("patch_keys", []):
            titles.setdefault(key, finding["title"])
    return titles


def build_share_bundle(run_id: str, store: Store, blobs: BlobStore, *, include_proposed: bool = False) -> dict:
    run = repo.get_run(run_id)
    ctx = repo.run_context(run_id)
    snapshot_id = str(run["snapshot_id"])
    patches = _patches_for_run(run_id, include_proposed)
    titles = _titles_by_patch(run_id)
    for patch in patches:
        patch["title"] = titles.get(patch["key"], "Suggested change")

    pages = {p.final_url or p.url: p for p in store.list_pages(snapshot_id)}
    pages.update({p.url: p for p in store.list_pages(snapshot_id)})
    by_page: dict[str, list[dict]] = {}
    site_files = []
    for patch in patches:
        if patch.get("page_url"):
            by_page.setdefault(patch["page_url"], []).append(patch)
        else:
            site_files.append({"key": patch["key"], "type": patch["type"], "before": patch.get("before"),
                               "after": patch["after"], "why": patch.get("rationale", ""),
                               "note": patch.get("client_visible_note", ""), "title": patch["title"]})

    entry_url = ctx["primary_url"]
    ordered_urls = sorted(by_page, key=lambda u: (u.rstrip("/") != entry_url.rstrip("/"), u))
    prefix = f"share-bundles/{run_id}"
    manifest_pages = []
    for index, url in enumerate(ordered_urls):
        page = pages.get(url)
        if page is None or not page.raw_html_key:
            continue
        raw = blobs.get(page.raw_html_key).decode("utf-8", errors="replace")
        result = apply(raw, page.final_url or page.url, by_page[url])
        # The same frozen page with no changes, so the workspace can show the original beside the fix.
        original = apply(raw, page.final_url or page.url, []).fixed_html
        original_key = blobs.put(f"{prefix}/p{index}/original.html", original.encode("utf-8"))
        annotated_key = blobs.put(f"{prefix}/p{index}/annotated.html", result.annotated_html.encode("utf-8"))
        fixed_key = blobs.put(f"{prefix}/p{index}/fixed.html", result.fixed_html.encode("utf-8"))
        manifest_pages.append({
            "index": index, "url": url, "original_key": original_key, "annotated_key": annotated_key,
            "fixed_key": fixed_key,
            "changes": [{"key": p["key"], "title": p["title"], "note": p.get("client_visible_note", ""),
                         "type": p["type"], "placed": p["key"] in result.placed} for p in by_page[url]],
            "not_placed": result.not_placed, "under_the_hood": result.under_the_hood})

    intelligence = repo.get_intelligence_report(run_id) or {}
    manifest = {
        "run_id": run_id, "client": ctx["name"], "entry_url": entry_url,
        "captured_at": (run.get("started_at") or run["created_at"]).isoformat(),
        "built_at": datetime.now(timezone.utc).isoformat(), "include_proposed": include_proposed,
        "readiness": intelligence.get("readiness", {}),
        "client_summary": [s["text"] for s in intelligence.get("executive_summary", {}).get("client", [])],
        "pages": manifest_pages, "site_files": site_files,
    }
    blobs.put(f"{prefix}/manifest.json", json.dumps(manifest).encode("utf-8"))
    return {"prefix": prefix, "manifest": manifest}
