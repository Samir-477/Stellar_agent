"""File storage behind one interface: Supabase Storage now, local disk later.

Payloads are gzip-compressed before upload to stay inside Supabase Free's 1 GB.
Keys look like "snapshots/<snapshot_id>/pages/<page_id>/raw.html"; the first
path segment is the bucket.
"""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import Protocol

import httpx

from engine.core.config import Settings


class BlobStore(Protocol):
    def put(self, key: str, data: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...
    def delete_prefix(self, prefix: str) -> int: ...


class LocalBlobStore:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        path = (self.root / f"{key}.gz").resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError(f"key escapes blob root: {key}")
        return path

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(data))
        return key

    def get(self, key: str) -> bytes:
        return gzip.decompress(self._path(key).read_bytes())

    def delete_prefix(self, prefix: str) -> int:
        base = self.root / prefix
        files = list(base.rglob("*.gz")) if base.exists() else []
        for file in files:
            file.unlink()
        return len(files)


class SupabaseBlobStore:
    def __init__(self, url: str, service_role_key: str, client: httpx.Client | None = None):
        self.base = url.rstrip("/") + "/storage/v1"
        self.headers = {"apikey": service_role_key, "Authorization": f"Bearer {service_role_key}"}
        self.client = client or httpx.Client(timeout=60)

    @staticmethod
    def _split(key: str) -> tuple[str, str]:
        bucket, _, path = key.partition("/")
        if not bucket or not path:
            raise ValueError(f"key must be '<bucket>/<path>': {key}")
        return bucket, path + ".gz"

    def put(self, key: str, data: bytes) -> str:
        bucket, path = self._split(key)
        resp = self.client.post(
            f"{self.base}/object/{bucket}/{path}",
            headers={**self.headers, "Content-Type": "application/gzip", "x-upsert": "true"},
            content=gzip.compress(data),
        )
        resp.raise_for_status()
        return key

    def get(self, key: str) -> bytes:
        bucket, path = self._split(key)
        resp = self.client.get(f"{self.base}/object/authenticated/{bucket}/{path}", headers=self.headers)
        resp.raise_for_status()
        return gzip.decompress(resp.content)

    def delete_prefix(self, prefix: str) -> int:
        bucket, _, path = prefix.partition("/")
        listed = self.client.post(
            f"{self.base}/object/list/{bucket}",
            headers=self.headers,
            json={"prefix": path, "limit": 1000},
        )
        listed.raise_for_status()
        names = [f"{path.rstrip('/')}/{item['name']}" for item in listed.json() if item.get("id")]
        if names:
            self.client.request("DELETE", f"{self.base}/object/{bucket}", headers=self.headers,
                                json={"prefixes": names}).raise_for_status()
        return len(names)


def make_blob_store(settings: Settings) -> BlobStore:
    if settings.blob_store == "supabase":
        return SupabaseBlobStore(settings.supabase_url, settings.supabase_service_role_key)
    return LocalBlobStore(settings.local_blob_dir)
