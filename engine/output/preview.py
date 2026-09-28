"""Internal previews for the workspace (docs/spec/06): a run's bundle with signed,
short-lived page links.

The dashboard never receives the engine API key, and client HTML never runs in the
dashboard's origin: the browser loads each page straight from the engine, which serves
it with a sandbox CSP (opaque origin) and allows framing only by the dashboard origins.
A link is valid for one run, page and view until it expires.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time

import httpx

from engine.core.blobstore import BlobStore
from engine.core.config import Settings

PREVIEW_TTL_S = 3600
VARIANTS = ("original", "annotated", "fixed")
_PROCESS_SECRET = secrets.token_hex(32)  # local development without a configured secret


def _secret(settings: Settings) -> str:
    return settings.preview_secret or settings.internal_secret or _PROCESS_SECRET


def signature(settings: Settings, run_id: str, index: int, variant: str, expires: int) -> str:
    message = f"preview:{run_id}:{index}:{variant}:{expires}"
    return hmac.new(_secret(settings).encode(), message.encode(), hashlib.sha256).hexdigest()


def valid(settings: Settings, run_id: str, index: int, variant: str, expires: int, sig: str,
          now: float | None = None) -> bool:
    if expires < (now if now is not None else time.time()):
        return False
    return hmac.compare_digest(signature(settings, run_id, index, variant, expires), sig or "")


def manifest_key(run_id: str) -> str:
    return f"share-bundles/{run_id}/manifest.json"


def load_manifest(blobs: BlobStore, run_id: str) -> dict | None:
    try:
        return json.loads(blobs.get(manifest_key(run_id)))
    except (FileNotFoundError, httpx.HTTPStatusError):
        return None


def for_workspace(settings: Settings, manifest: dict, now: float | None = None) -> dict:
    """The manifest without storage keys, with a signed link for each view of each page."""
    expires = int((now if now is not None else time.time()) + PREVIEW_TTL_S)
    base = settings.app_base_url.rstrip("/")
    run_id = manifest["run_id"]
    pages = []
    for page in manifest["pages"]:
        views = {}
        for variant in VARIANTS:
            if page.get(f"{variant}_key"):
                sig = signature(settings, run_id, page["index"], variant, expires)
                views[variant] = f"{base}/api/v1/preview/{run_id}/{page['index']}/{variant}?exp={expires}&sig={sig}"
        pages.append({k: v for k, v in page.items() if not k.endswith("_key")} | {"views": views})
    return {k: v for k, v in manifest.items() if k != "pages"} | {"pages": pages, "links_expire_at": expires}
