"""Postgres access (synchronous psycopg + a small pool).

Synchronous on purpose: psycopg's async mode doesn't work on Windows' default
event loop, and serverless functions gain nothing from async DB access.
prepare_threshold=None keeps it compatible with Supabase's transaction pooler.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from engine.core.config import get_settings

_pool: ConnectionPool | None = None
RECENT_S = 20.0  # a connection used this recently is still open; skip the extra round trip that tests it
_last_used: dict[int, float] = {}


def _check(conn: Connection) -> None:
    """Supabase's pooler drops idle connections, so test one before reuse, unless it was just used."""
    if time.monotonic() - _last_used.get(id(conn), 0.0) < RECENT_S:
        return
    ConnectionPool.check_connection(conn)


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        if not settings.database_url:
            raise RuntimeError("DATABASE_SESSION_POOL_URL is not set")
        _pool = ConnectionPool(
            settings.database_url,
            min_size=0,
            max_size=5,
            kwargs={"prepare_threshold": None, "row_factory": dict_row, "connect_timeout": 15},
            # Supabase's pooler drops idle connections: test each one before use and retire idle ones early.
            check=_check,
            max_idle=120,
            open=True,
        )
    return _pool


@contextmanager
def connection() -> Iterator[Connection]:
    """A pooled connection; commits on success, rolls back on error."""
    with _get_pool().connection() as conn:
        yield conn
        _last_used[id(conn)] = time.monotonic()


def json(value: Any) -> Jsonb:
    return Jsonb(value)
