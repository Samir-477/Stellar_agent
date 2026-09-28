import pytest

from engine.orchestrator.planner import plan_run
from engine.registry import collectors_for


def test_collectors_resolved_from_evidence_in_dependency_order():
    assert collectors_for(["S1"]) == ["C1", "C2"]


def test_task_graph_links_agents_only_to_collector_barriers():
    specs = {s.key: s for s in plan_run(["S1"])}
    assert specs["collector:C1:plan"].deps == []
    assert specs["collector:C2:plan"].deps == ["collector:C1:done"]
    assert sorted(specs["agent:S1:plan"].deps) == ["collector:C1:done", "collector:C2:done"]
    assert specs["agent:S1:reduce"].is_barrier and specs["agent:S1:plan"].barrier == "agent:S1:reduce"
    assert set(specs["run:finalize"].deps) == {"collector:C1:done", "collector:C2:done", "agent:S1:reduce"}
    assert "run:intelligence" not in specs  # one agent: nothing to merge


def test_multi_agent_runs_get_an_intelligence_step_after_every_agent():
    specs = {s.key: s for s in plan_run(["S1", "S8"])}
    assert set(specs["run:intelligence"].deps) == {"agent:S1:reduce", "agent:S8:reduce"}
    assert "run:intelligence" in specs["run:finalize"].deps
    # no agent depends on another agent
    for spec in specs.values():
        if spec.kind.startswith("agent."):
            assert not any(d.startswith("agent:") and not d.startswith(f"agent:{spec.ref}:") for d in spec.deps)


def test_unknown_or_empty_agent_list_is_rejected():
    with pytest.raises(ValueError):
        plan_run(["Z9"])
    with pytest.raises(ValueError):
        plan_run([])
