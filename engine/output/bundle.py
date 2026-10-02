"""The workspace preview of a run: the diagnosed page with every proposed change applied (fixed) and
the same page with each change marked (annotated), plus a manifest holding the page's issue list.

Only the diagnosed page is built, because that is the only page the Output layer shows. Each build
replaces the previous one's files.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from engine.core.blobstore import BlobStore
from engine.orchestrator import repo
from engine.output.page_review import review_entry_page
from engine.store import Store


def build_preview(run_id: str, store: Store, blobs: BlobStore) -> dict:
    """Build and store the preview; raises ReviewError when the page can't be reviewed."""
    review = review_entry_page(run_id, store, blobs)
    run = repo.get_run(run_id)
    folder = f"share-bundles/{run_id}/preview"
    blobs.delete_prefix(folder)
    result = review.result
    page = {
        "index": 0, "url": review.ctx["primary_url"],
        "fixed_key": blobs.put(f"{folder}/fixed.html", result.fixed_html.encode("utf-8")),
        "annotated_key": blobs.put(f"{folder}/annotated.html", result.annotated_html.encode("utf-8")),
        "changes": [{"key": p["key"], "title": p["title"], "note": p.get("client_visible_note", ""),
                     "type": p["type"], "placed": p["key"] in result.placed,
                     "awaiting_approval": p["key"] in review.waiting} for p in review.patches],
        "not_placed": result.not_placed, "under_the_hood": result.under_the_hood,
    }
    manifest = {
        "run_id": run_id, "client": review.ctx["name"], "entry_url": review.ctx["primary_url"],
        "captured_at": (run.get("started_at") or run["created_at"]).isoformat(),
        "built_at": datetime.now(timezone.utc).isoformat(), "pages": [page], "issues": review.issues,
    }
    blobs.put(f"share-bundles/{run_id}/manifest.json", json.dumps(manifest).encode("utf-8"))
    return manifest
