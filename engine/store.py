"""Evidence storage: pages and evidence rows, plus read-only snapshot access.

`Store` is the interface. `PostgresStore` is used in production; `MemoryStore`
backs unit tests so collectors and agents can be tested without a database.
Agents only ever receive a `SnapshotReader`, which has no way to read other
agents' findings (the independence contract, docs/spec/01-agent-review.md).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from engine.core.blobstore import BlobStore
from engine.schemas import EvidenceType


@dataclass
class PageRecord:
    id: str
    snapshot_id: str
    url: str
    final_url: str | None = None
    status: int | None = None
    template_id: str | None = None
    raw_html_key: str | None = None
    rendered_html_key: str | None = None
    render_status: str = "not_requested"
    fetch: dict[str, Any] = field(default_factory=dict)  # headers, redirects, timing, error


@dataclass
class EvidenceRecord:
    id: str
    snapshot_id: str
    collector_id: str
    type: str
    payload: dict[str, Any]
    page_id: str | None = None
    blob_key: str | None = None
    source_label: str | None = None


class Store(Protocol):
    def add_page(self, page: PageRecord) -> PageRecord: ...
    def update_page(self, page: PageRecord) -> None: ...
    def list_pages(self, snapshot_id: str) -> list[PageRecord]: ...
    def add_evidence(self, ev: EvidenceRecord) -> EvidenceRecord: ...
    def list_evidence(self, snapshot_id: str, type: str, page_id: str | None = None) -> list[EvidenceRecord]: ...


def new_id() -> str:
    return str(uuid.uuid4())


class MemoryStore:
    def __init__(self) -> None:
        self.pages: dict[str, PageRecord] = {}
        self.evidence: list[EvidenceRecord] = []

    def add_page(self, page: PageRecord) -> PageRecord:
        self.pages[page.id] = page
        return page

    def update_page(self, page: PageRecord) -> None:
        self.pages[page.id] = page

    def list_pages(self, snapshot_id: str) -> list[PageRecord]:
        return [p for p in self.pages.values() if p.snapshot_id == snapshot_id]

    def add_evidence(self, ev: EvidenceRecord) -> EvidenceRecord:
        self.evidence.append(ev)
        return ev

    def list_evidence(self, snapshot_id: str, type: str, page_id: str | None = None) -> list[EvidenceRecord]:
        return [e for e in self.evidence
                if e.snapshot_id == snapshot_id and e.type == type and (page_id is None or e.page_id == page_id)]


class PostgresStore:
    _page_cols = ("id, snapshot_id, url, final_url, status, template_id, raw_html_key, "
                  "rendered_html_key, render_status, fetch_meta")

    def add_page(self, page: PageRecord) -> PageRecord:
        from engine.core.db import connection, json as pgjson
        with connection() as conn:
            conn.execute(
                f"insert into pages ({self._page_cols}) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (page.id, page.snapshot_id, page.url, page.final_url, page.status, page.template_id,
                 page.raw_html_key, page.rendered_html_key, page.render_status, pgjson(page.fetch)),
            )
        return page

    def update_page(self, page: PageRecord) -> None:
        from engine.core.db import connection, json as pgjson
        with connection() as conn:
            conn.execute(
                "update pages set final_url=%s, status=%s, template_id=%s, raw_html_key=%s, "
                "rendered_html_key=%s, render_status=%s, fetch_meta=%s where id=%s",
                (page.final_url, page.status, page.template_id, page.raw_html_key,
                 page.rendered_html_key, page.render_status, pgjson(page.fetch), page.id),
            )

    def list_pages(self, snapshot_id: str) -> list[PageRecord]:
        from engine.core.db import connection
        with connection() as conn:
            rows = conn.execute(f"select {self._page_cols.replace('fetch_meta', 'fetch_meta as fetch')} "
                                "from pages where snapshot_id=%s order by created_at", (snapshot_id,)).fetchall()
        return [PageRecord(**{k: (str(v) if k in ("id", "snapshot_id") else v) for k, v in r.items()})
                for r in rows]

    def add_evidence(self, ev: EvidenceRecord) -> EvidenceRecord:
        from engine.core.db import connection, json as pgjson
        with connection() as conn:
            conn.execute(
                "insert into evidence (id, snapshot_id, collector_id, type, page_id, payload, blob_key, source_label) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s)",
                (ev.id, ev.snapshot_id, ev.collector_id, ev.type, ev.page_id, pgjson(ev.payload),
                 ev.blob_key, ev.source_label),
            )
        return ev

    def list_evidence(self, snapshot_id: str, type: str, page_id: str | None = None) -> list[EvidenceRecord]:
        from engine.core.db import connection
        sql = ("select id, snapshot_id, collector_id, type, page_id, payload, blob_key, source_label "
               "from evidence where snapshot_id=%s and type=%s")
        params: list[Any] = [snapshot_id, type]
        if page_id:
            sql += " and page_id=%s"
            params.append(page_id)
        with connection() as conn:
            rows = conn.execute(sql + " order by captured_at", params).fetchall()
        return [EvidenceRecord(**{k: (str(v) if k in ("id", "snapshot_id", "page_id") and v else v)
                                  for k, v in r.items()}) for r in rows]


class SnapshotReader:
    """Read-only evidence access handed to agents."""

    def __init__(self, store: Store, blobs: BlobStore, snapshot_id: str):
        self._store, self._blobs, self.snapshot_id = store, blobs, snapshot_id

    def pages(self) -> list[PageRecord]:
        return self._store.list_pages(self.snapshot_id)

    def evidence(self, type: EvidenceType | str, page_id: str | None = None) -> list[EvidenceRecord]:
        return self._store.list_evidence(self.snapshot_id, str(type), page_id)

    def blob_text(self, key: str) -> str:
        return self._blobs.get(key).decode("utf-8", errors="replace")

    def blob_json(self, key: str) -> Any:
        return json.loads(self._blobs.get(key))


class SnapshotWriter(SnapshotReader):
    """Read + write access handed to collectors (never to agents)."""

    def add_page(self, page: PageRecord) -> PageRecord:
        return self._store.add_page(page)

    def update_page(self, page: PageRecord) -> None:
        self._store.update_page(page)

    def put_blob(self, key: str, data: bytes | str) -> str:
        return self._blobs.put(key, data.encode("utf-8") if isinstance(data, str) else data)

    def add_evidence(self, collector_id: str, type: EvidenceType | str, payload: dict[str, Any], *,
                     page_id: str | None = None, blob_key: str | None = None,
                     source_label: str | None = None) -> EvidenceRecord:
        return self._store.add_evidence(EvidenceRecord(new_id(), self.snapshot_id, collector_id, str(type),
                                                       payload, page_id, blob_key, source_label))
