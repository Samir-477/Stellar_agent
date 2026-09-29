"""Deleting runs for good: the database rows first, then the files they left in storage."""

from __future__ import annotations

import logging

from engine.core.blobstore import BlobStore
from engine.orchestrator import repo

log = logging.getLogger(__name__)


def delete_run(run_id: str, blobs: BlobStore) -> bool:
    """False when the run doesn't exist or is still in progress."""
    prefixes = repo.delete_run(run_id)
    if prefixes is None:
        return False
    for prefix in prefixes:
        try:
            blobs.delete_prefix(prefix)
        except Exception as exc:  # noqa: BLE001 - the rows are gone; a leftover file is only wasted space
            log.warning("could not clear %s after deleting run %s: %s", prefix, run_id, exc)
    return True
