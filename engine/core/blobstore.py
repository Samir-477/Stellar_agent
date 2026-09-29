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

    def _files_under(self, bucket: str, folder: str) -> list[str]:
        """Every object below a folder. Storage lists one level at a time: folders come back without an id."""
        files: list[str] = []
        offset = 0
        while True:
            listed = self.client.post(f"{self.base}/object/list/{bucket}", headers=self.headers,
                                      json={"prefix": folder, "limit": 1000, "offset": offset})
            listed.raise_for_status()
            items = listed.json()
            for item in items:
                path = f"{folder.rstrip('/')}/{item['name']}"
                files.extend([path] if item.get("id") else self._files_under(bucket, path))
            if len(items) < 1000:
                return files
            offset += len(items)

    def delete_prefix(self, prefix: str) -> int:
        bucket, _, path = prefix.partition("/")
        names = self._files_under(bucket, path)
        for start in range(0, len(names), 1000):
            self.client.request("DELETE", f"{self.base}/object/{bucket}", headers=self.headers,
                                json={"prefixes": names[start:start + 1000]}).raise_for_status()
        return len(names)


def make_blob_store(settings: Settings) -> BlobStore:
    if settings.blob_store == "supabase":
        return SupabaseBlobStore(settings.supabase_url, settings.supabase_service_role_key)
    return LocalBlobStore(settings.local_blob_dir)
