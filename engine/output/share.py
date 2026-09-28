"""Share links: 128-bit random tokens stored as SHA-256 hashes, with expiry and revocation."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from engine.core.db import connection


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_share(run_id: str, bundle_prefix: str, *, days: int = 30, created_by: str | None = None) -> str:
    token = secrets.token_urlsafe(16)
    with connection() as conn:
        conn.execute("insert into shares (run_id, token_hash, bundle_prefix, expires_at, created_by) "
                     "values (%s,%s,%s,%s,%s)",
                     (run_id, _hash(token), bundle_prefix, datetime.now(timezone.utc) + timedelta(days=days), created_by))
    return token


def resolve_share(token: str, *, count_view: bool = False) -> dict | None:
    """The share row if the token is valid, unexpired and not revoked; otherwise None."""
    with connection() as conn:
        row = conn.execute("select * from shares where token_hash=%s and revoked_at is null and expires_at > now()",
                           (_hash(token),)).fetchone()
        if row and count_view:
            conn.execute("update shares set view_count = view_count + 1 where id=%s", (row["id"],))
    return row


def revoke_share(share_id: str) -> bool:
    with connection() as conn:
        return conn.execute("update shares set revoked_at=now() where id=%s and revoked_at is null",
                            (share_id,)).rowcount == 1
