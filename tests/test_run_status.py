"""A run's status from its steps: used when a run finishes and again after an agent is re-run."""

from engine.orchestrator.executor import run_status_of


def step(kind, ref, status):
    return {"kind": kind, "ref": ref, "status": status}


def test_a_re_run_that_clears_the_last_partial_step_completes_the_run():
    rows = [step("collector.done", "C1", "succeeded"), step("agent.reduce", "A2", "partial"),
            step("agent.reduce", "G5", "succeeded"), step("run.finalize", None, "succeeded")]
    assert run_status_of(rows) == ("completed_partial", [])  # partial steps aren't listed as problems
    rows[1]["status"] = "succeeded"
    assert run_status_of(rows) == ("completed", [])


def test_failed_steps_are_named_and_all_agents_failing_fails_the_run():
    rows = [step("collector.done", "C11", "failed"), step("agent.reduce", "S2", "failed")]
    assert run_status_of(rows) == ("failed", ["agent.reduce S2: failed", "collector.done C11: failed"])
