"""Integration test: the full orchestrator against the real database.

Opt-in (writes test rows, then deletes them): RUN_DB_TESTS=1 pytest tests/test_orchestrator_db.py
The site is the fake one from the golden test, so no real website is crawled.
"""

import os

import pytest

from engine.core.blobstore import LocalBlobStore
from engine.core.db import connection
from engine.orchestrator import repo
from engine.orchestrator.executor import Env
from engine.orchestrator.planner import plan_run
from engine.orchestrator.runner import run_inline
from engine.store import PostgresStore
from tests.conftest import fake_resolver, site_transport
from tests.test_s1_golden import BASE, ROUTES

pytestmark = pytest.mark.skipif(os.environ.get("RUN_DB_TESTS") != "1", reason="set RUN_DB_TESTS=1")


def test_full_pipeline_through_postgres_queue(settings, tmp_path):
    env = Env(settings=settings, store=PostgresStore(), blobs=LocalBlobStore(tmp_path / "blobs"),
              llm_factory=lambda run_ctx, task: None, http_transport=site_transport(ROUTES), resolver=fake_resolver)
    client = repo.create_client("TEST golden loans site", f"{BASE}/", archetype="loans", crawl_consent_by="pytest")
    try:
        run = repo.create_run(str(client["id"]), "agent", ["S1"], 25, plan_run(["S1"]))
        final = run_inline(str(run["id"]), env, max_seconds=120)

        assert final["status"] == "completed", final
        assert final["task_counts"] == {"succeeded": final["task_counts"]["succeeded"]}  # nothing failed
        fetch_units = [t for t in repo.run_task_statuses(str(run["id"])) if t["kind"] == "collector.unit"]
        assert len(fetch_units) >= 3  # discover + fetch batches + parse batches, spawned dynamically

        report = repo.get_agent_report(str(run["id"]), "S1")
        assert report["scorecard"]["fail"] == 7 and report["scorecard"]["pass"] == 1
        fails = repo.list_findings(str(run["id"]), "S1", "fail")
        assert {f["check_id"] for f in fails} >= {"S1.01", "S1.04", "S1.09"}
    finally:
        with connection() as conn:
            conn.execute("delete from clients where id=%s", (client["id"],))
