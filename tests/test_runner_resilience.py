"""The inline runner survives failures to record a task, and stops cleanly when they persist."""

import pytest

from engine.orchestrator import runner


class FakeRepo:
    def __init__(self, tasks):
        self.tasks, self.status = list(tasks), "queued"

    def get_run(self, run_id):
        return {"id": run_id, "status": self.status}

    def set_run_status(self, run_id, status):
        self.status = status

    def run_has_open_tasks(self, run_id):
        return {"open": bool(self.tasks)}


def setup(monkeypatch, outcomes, tasks):
    repo = FakeRepo(tasks)
    monkeypatch.setattr(runner, "repo", repo)
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)

    def claim(env, limit, run_id):
        return repo.tasks[:1]

    def execute(task, env):
        outcome = outcomes.pop(0)
        if outcome == "db-down":
            raise ConnectionError("SSL connection has been closed unexpectedly")
        repo.tasks.pop(0)  # recorded: no longer claimable

    monkeypatch.setattr(runner, "_claim", claim)
    monkeypatch.setattr(runner, "execute_task", execute)
    return repo


def test_a_dropped_connection_is_retried_not_fatal(monkeypatch):
    repo = setup(monkeypatch, ["db-down", "ok", "ok"], [{"id": 1}, {"id": 2}])
    assert runner.run_inline("r1", env=object())["id"] == "r1"
    assert repo.tasks == []


def test_persistent_failures_stop_the_run_with_a_clear_message(monkeypatch):
    setup(monkeypatch, ["db-down"] * runner.MAX_INFRA_FAILURES, [{"id": 1}])
    with pytest.raises(RuntimeError, match="couldn't be recorded"):
        runner.run_inline("r1", env=object())
