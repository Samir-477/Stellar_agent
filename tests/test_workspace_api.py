"""Workspace endpoints: catalog coverage, the run-progress projection and signed preview links."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from engine import catalog, progress
from engine.output import preview
from engine.registry import AGENTS, COLLECTORS, collectors_for

T0 = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)


def task(kind, ref, status="pending", *, unit=None, minute=None, error=None, findings=None, proposal=None,
         attempts=0):
    finished = T0 + timedelta(minutes=minute) if minute is not None and status in progress.TERMINAL else None
    return {"kind": kind, "ref": ref, "status": status, "is_barrier": kind.endswith((".done", ".reduce"))
            or kind.startswith("run."), "unit": unit, "attempts": attempts, "error": error,
            "started_at": T0 if status != "pending" else None, "finished_at": finished,
            "findings": findings, "proposal": proposal}


def test_every_registered_component_has_catalog_words():
    assert set(catalog.AGENTS) == set(AGENTS)
    assert set(catalog.COLLECTORS) == set(COLLECTORS)
    assert {c["group"] for c in catalog.COLLECTORS.values()} <= set(catalog.COLLECTOR_GROUPS)
    assert all(a["question"].endswith("?") and a["outcome"] and a["how"] and a["example"] for a in catalog.AGENTS.values())


def test_delete_route_removes_the_rows_then_every_file_the_run_owned(monkeypatch):
    """Delete is permanent: the rows go first, then each storage prefix the run owned. A run still in
    progress is refused, so no task writes into a deleted run."""
    from fastapi import HTTPException

    import engine.api.app as app_module
    from engine.orchestrator import retention

    cleared = []

    class Blobs:
        def delete_prefix(self, prefix):
            cleared.append(prefix)
            return 1

    monkeypatch.setattr(app_module, "make_blob_store", lambda settings: Blobs())
    monkeypatch.setattr(app_module.repo, "get_run", lambda run_id: {"id": run_id})
    monkeypatch.setattr(retention.repo, "delete_run", lambda run_id: ["share-bundles/run-1", "snapshots/snap-1"])
    assert app_module.delete_run("run-1") == {"run_id": "run-1", "deleted": True}
    assert cleared == ["share-bundles/run-1", "snapshots/snap-1"]

    monkeypatch.setattr(retention.repo, "delete_run", lambda run_id: None)
    with pytest.raises(HTTPException) as refused:
        app_module.delete_run("run-2")
    assert refused.value.status_code == 409


def test_progress_while_collecting_shows_real_steps_and_a_feed():
    run = {"status": "running", "agents": ["S7"]}
    tasks = [task("collector.plan", "C1", "succeeded", minute=1),
             task("collector.unit", "C1", "succeeded", unit={"kind": "fetch", "params": {"page_ids": [1, 2, 3, 4, 5]}},
                  minute=2),
             task("collector.unit", "C1", "running", unit={"kind": "fetch", "params": {"page_ids": [6, 7]}}),
             task("collector.done", "C1"),
             task("collector.plan", "C2"), task("collector.done", "C2"),
             task("agent.plan", "S7"), task("agent.reduce", "S7"), task("run.finalize", None)]
    view = progress.project(run, tasks)
    c1 = next(c for c in view["collectors"] if c["id"] == "C1")
    assert c1["state"] == "running" and (c1["steps_done"], c1["steps_total"]) == (1, 2)
    assert [s["state"] for s in view["stages"]] == ["running", "waiting", "not_in_run", "waiting"]
    assert view["events"][0]["text"] == "Fetched 5 pages"
    assert view["tasks"] == {"total": 9, "done": 2, "running": 1}


def test_finished_run_reports_findings_failures_and_reused_evidence():
    run = {"status": "completed_partial", "agents": ["S3", "S7"]}
    tasks = [task("agent.plan", "S3", "succeeded", minute=5), task("agent.reduce", "S3", "succeeded", minute=6,
                                                                   findings=12),
             task("agent.plan", "S7", "failed", minute=5, error="TimeoutError: page model missing\nTraceback"),
             task("agent.reduce", "S7", "failed", minute=7),
             task("run.intelligence", None, "succeeded", minute=8), task("run.finalize", None, "succeeded", minute=9)]
    view = progress.project(run, tasks)  # no collector tasks: the snapshot's evidence was reused
    assert {c["state"] for c in view["collectors"]} == {"reused"}
    assert len(view["collectors"]) == len(collectors_for(["S3", "S7"]))
    agents = {a["id"]: a for a in view["agents"]}
    assert agents["S3"]["findings"] == 12 and agents["S3"]["state"] == "done"
    assert agents["S7"]["state"] == "failed" and agents["S7"]["error"] == "TimeoutError: page model missing"
    assert [s["state"] for s in view["stages"]] == ["done", "done", "done", "done"]
    texts = [e["text"] for e in view["events"]]
    assert texts[:2] == ["Run finished", "Intelligence report built"]
    assert "Search Metadata saved its report (12 findings)" in texts


def test_archetype_pause_is_explicit_and_carries_the_proposal():
    run = {"status": "awaiting_confirmation", "agents": ["S10"]}
    proposal = {"archetype": "hospitality", "confidence": 0.55, "signals": ["rooms", "check-in"]}
    tasks = [task("collector.plan", "C1", "succeeded", minute=1), task("collector.done", "C1", "succeeded", minute=2),
             task("collector.plan", "C3", "succeeded", minute=3),
             task("collector.unit", "C3", "pending", unit={"kind": "detect", "params": {}}, proposal=proposal),
             task("collector.done", "C3")]
    view = progress.project(run, tasks)
    assert view["stages"][0]["state"] == "paused"
    assert next(c for c in view["collectors"] if c["id"] == "C3")["state"] == "paused"
    assert view["archetype_proposal"] == proposal


def test_preview_links_are_signed_expiring_and_page_scoped(settings):
    manifest = {"run_id": "r1", "include_proposed": True,
                "pages": [{"index": 0, "url": "https://x/", "original_key": "a", "annotated_key": "b",
                           "fixed_key": "c", "changes": []},
                          {"index": 1, "url": "https://x/old", "annotated_key": "d", "fixed_key": "e",
                           "changes": []}]}
    view = preview.for_workspace(settings, manifest, now=1000)
    assert set(view["pages"][0]["views"]) == {"annotated", "fixed"}  # an old bundle's Before copy is no longer offered
    assert set(view["pages"][1]["views"]) == {"annotated", "fixed"}
    assert not any(k.endswith("_key") for page in view["pages"] for k in page)
    expires = view["links_expire_at"]
    sig = preview.signature(settings, "r1", 0, "fixed", expires)
    assert preview.valid(settings, "r1", 0, "fixed", expires, sig, now=1000)
    assert not preview.valid(settings, "r1", 1, "fixed", expires, sig, now=1000)  # another page
    assert not preview.valid(settings, "r1", 0, "fixed", expires, sig, now=expires + 1)  # expired


@pytest.fixture
def client(settings, monkeypatch):
    import engine.api.app as app_module
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    return TestClient(app_module.app)


def test_preview_page_is_sandboxed_and_rejects_bad_links(client, settings):
    from engine.core.blobstore import make_blob_store
    blobs = make_blob_store(settings)
    blobs.put("share-bundles/r1/p0/fixed.html", b"<html><body>fixed</body></html>")
    blobs.put(preview.manifest_key("r1"), json.dumps(
        {"run_id": "r1", "pages": [{"index": 0, "url": "https://x/", "fixed_key": "share-bundles/r1/p0/fixed.html",
                                    "annotated_key": "share-bundles/r1/p0/fixed.html"}]}).encode())
    expires = 4_000_000_000
    good = f"/api/v1/preview/r1/0/fixed?exp={expires}&sig={preview.signature(settings, 'r1', 0, 'fixed', expires)}"
    response = client.get(good)
    assert response.status_code == 200 and b"fixed" in response.content
    csp = response.headers["content-security-policy"]
    assert csp.startswith("sandbox allow-scripts") and "frame-ancestors http://localhost:3000" in csp
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert client.get(good.replace("sig=", "sig=0")).status_code == 403
    original = f"/api/v1/preview/r1/0/original?exp={expires}&sig=" + preview.signature(settings, "r1", 0, "original",
                                                                                     expires)
    assert client.get(original).status_code == 403  # the Before view was removed


def test_collectors_endpoint_lists_dependencies_in_order(client):
    rows = client.get("/api/v1/collectors").json()
    ids = [r["id"] for r in rows]
    assert set(ids) == set(COLLECTORS) and ids.index("C1") < ids.index("C2")
    c11 = next(r for r in rows if r["id"] == "C11")
    assert c11["used_by"] == ["S2"] and c11["services"] == ["PageSpeed Insights"]
    s3 = next(a for a in client.get("/api/v1/agents").json() if a["id"] == "S3")
    assert s3["question"] == catalog.AGENTS["S3"]["question"] and "C2" in s3["collectors"]
    assert "C1" in s3["collectors"] and "C1" not in s3["reads"]  # reads = direct evidence only
