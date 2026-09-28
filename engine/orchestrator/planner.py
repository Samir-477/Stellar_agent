"""Turns a run request into a task graph (pure function, no database).

Every collector and agent gets a `plan` task and a barrier task (`done` for
collectors, `reduce` for agents). Work units spawned later attach to their
component's barrier, so downstream steps wait for all of them. Agents depend
only on collector barriers, never on other agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.registry import AGENTS, agent_collectors, collectors_for, upstream_collectors


@dataclass
class TaskSpec:
    key: str
    kind: str  # collector.plan|collector.unit|collector.done|agent.plan|agent.unit|agent.reduce|run.finalize
    ref: str | None
    unit: dict[str, Any] | None = None
    deps: list[str] = field(default_factory=list)
    barrier: str | None = None  # key of the barrier this task's children attach to
    is_barrier: bool = False


def plan_run(agent_ids: list[str], done_collectors: frozenset[str] = frozenset()) -> list[TaskSpec]:
    """`done_collectors` are collectors whose evidence already exists in a reused snapshot;
    they get no tasks, and nothing waits on them."""
    unknown = [a for a in agent_ids if a not in AGENTS]
    if unknown:
        raise ValueError(f"unknown agents: {unknown}")
    if not agent_ids:
        raise ValueError("a run needs at least one agent")

    specs: list[TaskSpec] = []
    for cid in collectors_for(agent_ids):
        if cid in done_collectors:
            continue
        done = f"collector:{cid}:done"
        specs.append(TaskSpec(f"collector:{cid}:plan", "collector.plan", cid, barrier=done,
                              deps=[f"collector:{up}:done" for up in upstream_collectors(cid)
                                    if up not in done_collectors]))
        specs.append(TaskSpec(done, "collector.done", cid, deps=[f"collector:{cid}:plan"], is_barrier=True))
    for aid in agent_ids:
        reduce = f"agent:{aid}:reduce"
        specs.append(TaskSpec(f"agent:{aid}:plan", "agent.plan", aid, barrier=reduce,
                              deps=[f"collector:{cid}:done" for cid in agent_collectors(aid)
                                    if cid not in done_collectors]))
        specs.append(TaskSpec(reduce, "agent.reduce", aid, deps=[f"agent:{aid}:plan"], is_barrier=True))
    barriers = [s.key for s in specs if s.is_barrier]
    if len(agent_ids) >= 2:
        # Intelligence merges all agents' results, so it waits for every agent (and runs even if some failed).
        specs.append(TaskSpec("run:intelligence", "run.intelligence", None, is_barrier=True,
                              deps=[s.key for s in specs if s.kind == "agent.reduce"]))
        barriers.append("run:intelligence")
    specs.append(TaskSpec("run:finalize", "run.finalize", None, is_barrier=True, deps=barriers))
    return specs
