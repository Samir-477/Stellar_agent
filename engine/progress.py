"""Run progress for the workspace: a projection of the task table into stages,
components and a feed of finished work.

Pure functions over task rows (repo.run_tasks), so they are tested without a
database. Nothing here estimates time or invents a percentage: counts are of
tasks that exist now, and the planner adds tasks as collectors discover work.
"""

from __future__ import annotations

from typing import Any

from engine.registry import AGENTS, COLLECTORS, collectors_for

TERMINAL = ("succeeded", "partial", "failed", "skipped")
BARRIER_STATE = {"succeeded": "done", "partial": "partial", "failed": "failed", "skipped": "skipped"}
SURFACES = {"google_ai_overview": "Google AI Overview", "deepseek": "DeepSeek knowledge probe",
            "groq": "Groq knowledge probe", "simulated_search": "simulated AI search"}
C12_PARTS = {"wiki": "Checked Wikipedia and Wikidata", "platforms": "Checked industry platforms",
             "places": "Checked the Google Maps listing", "kg": "Checked Google's Knowledge Graph"}


def _count(params: dict, key: str) -> int:
    return len(params.get(key) or [])


def unit_text(ref: str, kind: str, params: dict) -> str:
    """What one finished collector unit did, in plain words."""
    texts = {
        ("C1", "discover"): "Read robots.txt, sitemaps and llms.txt, and chose the pages to fetch",
        ("C1", "fetch"): f"Fetched {_count(params, 'page_ids')} pages",
        ("C2", "parse"): f"Parsed {_count(params, 'page_ids')} pages",
        ("C3", "detect"): "Identified the type of business",
        ("C4", "extract"): "Extracted the facts the site states",
        ("C5", "build"): "Built the search queries",
        ("C6", "capture"): "Captured search results for a query",
        ("C7", "build"): "Built the question library",
        ("C8", "classify"): "Classified the competing domains",
        ("C8", "fetch"): f"Fetched competitor pages from {params.get('domain', 'a competitor')}",
        ("C9", "build"): "Built the AI prompt set",
        ("C10", "capture"): f"Captured answers from {SURFACES.get(params.get('surface'), 'an AI surface')}",
        ("C11", "measure"): f"Measured speed of {params.get('url', 'a page')}",
    }
    if ref == "C12":
        return C12_PARTS.get(kind, "Checked an off-site source")
    return texts.get((ref, kind), f"Finished a {kind} step")


def describe(task: dict) -> str | None:
    """A feed line for a finished task, or None for bookkeeping steps a person needn't see."""
    kind, ref = task["kind"], task["ref"]
    unit = task.get("unit") or {}
    if kind == "collector.unit":
        text = unit_text(ref, unit.get("kind", ""), unit.get("params") or {})
    elif kind == "collector.done":
        text = f"{COLLECTORS[ref].name}: evidence ready"
    elif kind == "agent.reduce":
        found = task.get("findings")
        text = f"{AGENTS[ref].name} saved its report" + (f" ({found} findings)" if found is not None else "")
    elif kind == "run.intelligence":
        text = "Intelligence report built"
    elif kind == "run.finalize":
        text = "Run finished"
    else:
        return None
    if task["status"] == "failed":
        reason = (task.get("error") or "").strip().splitlines()
        return f"{text}: failed" + (f" ({reason[0][:140]})" if reason else "")
    if task["status"] == "skipped":
        return f"{text}: skipped because an earlier step failed"
    return text


def component_state(tasks: list[dict]) -> str:
    """waiting → running → done / partial / failed / skipped, from a component's plan, units and barrier."""
    barrier = next((t for t in tasks if t["is_barrier"]), None)
    if barrier and barrier["status"] in TERMINAL:
        return BARRIER_STATE[barrier["status"]]
    if any(t["status"] == "running" or t["status"] in TERMINAL for t in tasks):
        return "running"
    return "waiting"


def _component(tasks: list[dict]) -> dict:
    units = [t for t in tasks if t["kind"].endswith(".unit")]
    started = [t["started_at"] for t in tasks if t.get("started_at")]
    finished = [t["finished_at"] for t in tasks if t.get("finished_at")]
    errors = [t["error"] for t in tasks if t["status"] == "failed" and t.get("error")]
    barrier = next((t for t in tasks if t["is_barrier"]), None)
    return {"state": component_state(tasks), "steps_total": len(units),
            "steps_done": sum(t["status"] in TERMINAL for t in units),
            "retrying": sum(t["status"] == "pending" and t.get("attempts", 0) > 0 for t in tasks),
            "started_at": min(started) if started else None,
            "finished_at": barrier["finished_at"] if barrier and barrier["status"] in TERMINAL else None,
            "error": errors[0].strip().splitlines()[0][:200] if errors else None,
            "last_activity": max(finished) if finished else None}


def _stage(states: list[str]) -> str:
    if not states:
        return "not_in_run"
    if all(s in ("done", "partial", "failed", "skipped", "reused") for s in states):
        return "failed" if all(s in ("failed", "skipped") for s in states) else "done"
    if any(s != "waiting" for s in states):
        return "running"
    return "waiting"


def project(run: dict, tasks: list[dict], limit_events: int = 40) -> dict[str, Any]:
    """The whole progress view for one run."""
    by_component: dict[tuple[str, str], list[dict]] = {}
    for task in tasks:
        family = task["kind"].split(".")[0]
        if family in ("collector", "agent"):
            by_component.setdefault((family, task["ref"]), []).append(task)

    agent_ids = list(run["agents"])
    paused = run["status"] == "awaiting_confirmation"
    collectors = []
    for cid in collectors_for(agent_ids):
        own = by_component.get(("collector", cid))
        entry = {"id": cid, "name": COLLECTORS[cid].name,
                 **(_component(own) if own else {"state": "reused", "steps_total": 0, "steps_done": 0, "retrying": 0,
                                                 "started_at": None, "finished_at": None, "error": None,
                                                 "last_activity": None})}
        if paused and cid == "C3" and entry["state"] not in ("done", "partial", "failed", "skipped"):
            entry["state"] = "paused"
        collectors.append(entry)

    agents = []
    for aid in agent_ids:
        own = by_component.get(("agent", aid), [])
        reduce = next((t for t in own if t["kind"] == "agent.reduce"), None)
        agents.append({"id": aid, "name": AGENTS[aid].name, "pillar": AGENTS[aid].pillar.value,
                       "findings": reduce.get("findings") if reduce and reduce["status"] in TERMINAL else None,
                       **_component(own)})

    run_steps = {t["kind"]: t for t in tasks if t["kind"] in ("run.intelligence", "run.finalize")}
    intelligence = run_steps.get("run.intelligence")
    intel_state = (BARRIER_STATE.get(intelligence["status"], "running" if intelligence["status"] == "running"
                                     else "waiting") if intelligence else "not_in_run")
    finalize = run_steps.get("run.finalize")
    final_state = BARRIER_STATE.get(finalize["status"], "waiting") if finalize else "waiting"

    stages = [
        {"id": "collect", "label": "Collect evidence", "state": _stage([c["state"] for c in collectors])},
        {"id": "diagnose", "label": "Diagnose", "state": _stage([a["state"] for a in agents])},
        {"id": "synthesize", "label": "Synthesize", "state": "not_in_run" if intel_state == "not_in_run"
         else _stage([intel_state])},
        {"id": "report", "label": "Report ready", "state": _stage([final_state])},
    ]
    if paused:
        stages[0]["state"] = "paused"

    finished = sorted((t for t in tasks if t["status"] in TERMINAL and t.get("finished_at")),
                      key=lambda t: t["finished_at"], reverse=True)
    events = []
    for task in finished:
        text = describe(task)
        if text:
            events.append({"at": task["finished_at"], "ref": task["ref"], "kind": task["kind"],
                           "status": task["status"], "text": text})
        if len(events) >= limit_events:
            break

    proposal = next((t.get("proposal") for t in tasks if t["ref"] == "C3" and t.get("proposal")), None)
    return {
        "status": run["status"], "note": run.get("note"),
        "tasks": {"total": len(tasks), "done": sum(t["status"] in TERMINAL for t in tasks),
                  "running": sum(t["status"] == "running" for t in tasks)},
        "stages": stages, "collectors": collectors, "agents": agents,
        "intelligence": intel_state, "events": events,
        "archetype_proposal": proposal if paused else None,
    }
