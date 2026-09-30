"""Executes one claimed task. Every task kind is idempotent: a retry overwrites
its own output and never duplicates results."""

from __future__ import annotations

import logging
import socket
import traceback
from dataclasses import dataclass
from typing import Any, Callable

from engine.collectors.c03_archetype import AwaitingConfirmation
from engine.context import AgentContext, ClientProfile, CollectorContext, WorkUnit
from engine.core.blobstore import BlobStore
from engine.core.config import Settings
from engine.llm import LLMClient, TokenBudget
from engine.orchestrator import repo
from engine.orchestrator.planner import TaskSpec
from engine.registry import AGENTS, COLLECTORS
from engine.reports import build_agent_report
from engine.schemas import AgentResult
from engine.store import SnapshotReader, SnapshotWriter, Store
from engine.validation import validate_result

log = logging.getLogger("engine.executor")


@dataclass
class Env:
    settings: Settings
    store: Store
    blobs: BlobStore
    llm_factory: Callable[[dict, dict], LLMClient | None]  # (run_context, task) → client
    http_transport: Any = None  # tests inject a mock transport; None = real network
    resolver: Callable = socket.getaddrinfo
    search_factory: Callable[[dict], Any] | None = None  # (run_context) → SearchClient
    pagespeed_factory: Callable[[], Any] | None = None  # () → PageSpeedClient


def default_llm_factory(settings: Settings) -> Callable[[dict, dict], LLMClient | None]:
    def make(run_ctx: dict, task: dict) -> LLMClient | None:
        if settings.llm_mode == "off":
            return None
        budget = TokenBudget(limit=run_ctx["token_budget"]) if run_ctx.get("token_budget") else None
        return LLMClient(settings, budget=budget, cache_get=repo.llm_cache_get, cache_put=repo.llm_cache_put,
                         recorder=lambda call: repo.record_llm_call(str(run_ctx["run_id"]), str(task["id"]), call))
    return make


def default_pagespeed_factory(settings: Settings):
    from engine.integrations.pagespeed import PageSpeedClient
    return lambda: PageSpeedClient(settings.pagespeed_api_key) if settings.pagespeed_api_key else None


def default_search_factory(settings: Settings):
    """A fresh budget per task execution. SerpAPI is only used inside C6's single task, so its
    cap is effectively per run; Serper is used by C6 and C7 (one task each)."""
    from engine.integrations.search import SearchBudget, SearchClient

    def make(run_ctx: dict):
        budget = SearchBudget({"serper": settings.serper_calls_per_run, "serpapi": settings.serpapi_calls_per_run},
                              on_use=repo.add_provider_usage)
        return SearchClient(settings.serper_api_key, settings.serpapi_key, budget)
    return make


def _client(run_ctx: dict) -> ClientProfile:
    return ClientProfile(id=str(run_ctx["client_id"]), name=run_ctx["name"], primary_url=run_ctx["primary_url"],
                         archetype=run_ctx["archetype"], locations=run_ctx["locations"] or [],
                         competitors=run_ctx["competitors"] or [], crawl_cap=run_ctx["crawl_cap"])


def execute_task(task: dict, env: Env) -> str:
    """Run a claimed task and record the outcome. Returns the final task status."""
    kind, ref = task["kind"], task["ref"]
    try:
        # Setup is inside the try: a failure here is recorded on the task like any other.
        run_ctx = repo.run_context(str(task["run_id"]))
        snapshot_id = str(run_ctx["snapshot_id"])
        client = _client(run_ctx)
        llm = env.llm_factory(run_ctx, task)
        if kind.startswith("collector."):
            collector = COLLECTORS[ref]
            ctx = CollectorContext(SnapshotWriter(env.store, env.blobs, snapshot_id), client, env.settings, llm,
                                   env.http_transport, env.resolver,
                                   search=env.search_factory(run_ctx) if env.search_factory else None,
                                   pagespeed=env.pagespeed_factory() if env.pagespeed_factory else None)
            if kind == "collector.plan":
                units = collector.plan(ctx)
                return _done(task, "succeeded", children=[_unit_spec("collector.unit", ref, u) for u in units])
            if kind == "collector.unit":
                follow = collector.run_unit(ctx, WorkUnit(**task["unit"]))
                return _done(task, "succeeded", children=[_unit_spec("collector.unit", ref, u) for u in follow])
            if kind == "collector.done":
                status = _barrier_status(task)
                if status in ("succeeded", "partial"):
                    repo.mark_collector_done(snapshot_id, ref)
                return _done(task, status)

        if kind.startswith("agent."):
            agent = AGENTS[ref]
            ctx = AgentContext(SnapshotReader(env.store, env.blobs, snapshot_id), client, env.settings, llm)
            if kind == "agent.plan":
                units = agent.plan(ctx)
                return _done(task, "succeeded", children=[_unit_spec("agent.unit", ref, u) for u in units])
            if kind == "agent.unit":
                result = agent.run_unit(ctx, WorkUnit(**task["unit"]))
                return _done(task, "succeeded", output=result.model_dump(mode="json"))
            if kind == "agent.reduce":
                return _reduce(task, agent, ctx, run_ctx)

        if kind == "run.intelligence":
            return _intelligence(task, env, run_ctx, snapshot_id, client, llm)
        if kind == "run.finalize":
            return _finalize(task)
        raise ValueError(f"unknown task kind {kind}")
    except AwaitingConfirmation as gate:
        repo.await_archetype(task, gate.proposal)
        return "awaiting"
    except Exception as exc:  # noqa: BLE001 - every failure is recorded on the task
        log.exception("task %s (%s %s) failed", task["id"], kind, ref)
        detail = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}"
        return repo.retry_or_fail(task, detail, env.settings.task_max_attempts)


def _unit_spec(kind: str, ref: str, unit: WorkUnit) -> TaskSpec:
    return TaskSpec(key=f"{kind.split('.')[0]}:{ref}:unit:{unit.kind}", kind=kind, ref=ref,
                    unit={"kind": unit.kind, "params": unit.params})


def _done(task: dict, status: str, **kwargs) -> str:
    return status if repo.finish(task, status, **kwargs) else "lost"


def _barrier_status(task: dict) -> str:
    deps = repo.dep_tasks(task)
    plan = [d for d in deps if d["kind"].endswith(".plan")]
    if any(d["status"] in ("failed", "skipped") for d in plan):
        return "failed"
    return "partial" if any(d["status"] in ("failed", "skipped", "partial") for d in deps) else "succeeded"


def _reduce(task: dict, agent, ctx: AgentContext, run_ctx: dict) -> str:
    status = _barrier_status(task)
    if status == "failed":
        return _done(task, "failed", error="agent plan failed or its evidence is missing")
    units = [d for d in repo.dep_tasks(task) if d["kind"] == "agent.unit" and d["status"] == "succeeded"]
    results = [AgentResult.model_validate(d["output"]) for d in units]
    errors, count = _save_agent(agent, ctx, agent.reduce(ctx, results), str(run_ctx["run_id"]))
    if errors:
        status = "partial"
    return _done(task, status, output={"validation_errors": errors, "findings": count},
                 error="; ".join(errors)[:2000] or None)


def _save_agent(agent, ctx: AgentContext, merged: AgentResult, run_id: str) -> tuple[list[str], int]:
    """Validate an agent's merged result, then replace its findings, patches and report for the run."""
    page_urls = {p.final_url or p.url for p in ctx.snapshot.pages()} | {p.url for p in ctx.snapshot.pages()}
    merged, errors = validate_result(agent, merged, page_urls)
    repo.save_agent_result(run_id, agent.id, merged.findings, merged.patches, build_agent_report(agent, merged))
    return errors, len(merged.findings)


def rerun_agent(env: Env, run_id: str, agent_id: str, llm) -> dict:
    """Run one agent again on a finished run's stored evidence (no crawl, no search calls), replace its
    results, record the outcome on its step and settle the run's status again."""
    run_ctx = repo.run_context(run_id)
    agent = AGENTS[agent_id]
    ctx = AgentContext(SnapshotReader(env.store, env.blobs, str(run_ctx["snapshot_id"])), _client(run_ctx),
                       env.settings, llm)
    merged = agent.reduce(ctx, [agent.run_unit(ctx, unit) for unit in agent.plan(ctx)])
    errors, count = _save_agent(agent, ctx, merged, run_id)
    status = "partial" if errors else "succeeded"
    output = {"validation_errors": errors, "findings": count}
    repo.set_agent_outcome(run_id, agent.id, status, output, "; ".join(errors)[:2000] or None)
    return {"status": status, **output, "run_status": settle_run_status(run_id)}


def build_run_intelligence(env: Env, run_ctx: dict, llm, failed_steps: list[str]) -> dict:
    """The intelligence report from a run's stored findings; also used to rebuild an older run's report."""
    from engine.agents.common import key_page_urls, load_pages
    from engine.intelligence import build_intelligence_report
    from engine.schemas import Finding

    run_id, client = str(run_ctx["run_id"]), _client(run_ctx)
    findings_by_agent: dict[str, list[Finding]] = {}
    for payload in repo.list_findings(run_id):
        findings_by_agent.setdefault(payload["agent_id"], []).append(Finding.model_validate(payload))
    reader_ctx = AgentContext(SnapshotReader(env.store, env.blobs, str(run_ctx["snapshot_id"])), client, env.settings, None)
    keys = key_page_urls(load_pages(reader_ctx), client.primary_url)
    notes = list(failed_steps)
    for agent_id, report in repo.agent_reports(run_id).items():
        notes += [f"{agent_id}: {limit}" for limit in report["scope_and_evidence"]["coverage"].get("limits", [])]
    return build_intelligence_report(findings_by_agent, keys, notes, llm, entry_url=client.primary_url)


def _intelligence(task: dict, env: Env, run_ctx: dict, snapshot_id: str, client, llm) -> str:
    run_id = str(run_ctx["run_id"])
    failed = [f"{d['ref']}: {d['status']}" for d in repo.dep_tasks(task) if d["status"] != "succeeded"]
    report = build_run_intelligence(env, run_ctx, llm, failed)
    repo.save_intelligence_report(run_id, report)
    return _done(task, "succeeded", output={"work_items": sum(len(v) for v in report["what_to_fix_first"].values()),
                                            "summary_source": report["executive_summary"].get("source")})


def run_status_of(rows: list[dict]) -> tuple[str, list[str]]:
    """A run's status from its steps, and the steps that failed or were skipped."""
    reduces = [r for r in rows if r["kind"] == "agent.reduce"]  # run.intelligence counts like any other step
    if reduces and all(r["status"] == "failed" for r in reduces):
        status = "failed"
    elif any(r["status"] in ("failed", "skipped", "partial") for r in rows if r["kind"] != "run.finalize"):
        status = "completed_partial"
    else:
        status = "completed"
    problems = sorted({f"{r['kind']} {r['ref']}: {r['status']}" for r in rows
                       if r["status"] in ("failed", "skipped") and r["kind"] != "run.finalize"})
    return status, problems


def settle_run_status(run_id: str) -> str:
    status, problems = run_status_of(repo.run_task_statuses(run_id))
    repo.set_run_status(run_id, status, note="; ".join(problems)[:2000] or None)
    return status


def _finalize(task: dict) -> str:
    return _done(task, "succeeded", output={"run_status": settle_run_status(str(task["run_id"]))})
