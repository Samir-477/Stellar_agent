"""Helpers shared by collectors."""

from __future__ import annotations

from engine.context import CollectorContext
from engine.schemas import EvidenceType


def parsed_models(ctx: CollectorContext) -> list[dict]:
    """Parsed page models for the snapshot, the client's entry page first."""
    parsed = {e.page_id: e for e in ctx.snapshot.evidence(EvidenceType.PAGES_PARSED)}
    entry = ctx.client.primary_url.rstrip("/")
    models = []
    for page in ctx.snapshot.pages():
        if page.id in parsed and parsed[page.id].blob_key:
            model = ctx.snapshot.blob_json(parsed[page.id].blob_key)
            if not model.get("parse_error"):
                models.append(model)
    models.sort(key=lambda m: m["url"].rstrip("/") != entry)
    return models
