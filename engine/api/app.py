"""REST API (v1). A plain FastAPI app: runs on Vercel via api/index.py and under
uvicorn when self-hosted."""

from __future__ import annotations

import hmac
import threading
from collections import OrderedDict
from typing import Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field, HttpUrl

from engine import catalog, progress
from engine.issues import build_issue_cards
from engine.core.blobstore import make_blob_store
from engine.core.config import get_settings
from engine.core.net import UnsafeURLError, check_url
from engine.orchestrator import repo
from engine.orchestrator.planner import plan_run
from engine.orchestrator.retention import delete_run as delete_run_everywhere
from engine.orchestrator.runner import dispatch, make_env, run_inline, trigger_dispatch, verify
from engine.orchestrator.executor import execute_task
from engine.output import preview
from engine.output.bundle import build_preview as build_preview_bundle
from engine.output.microsite import build_microsite
from engine.output.page_review import ReviewError
from engine.output.snippet_cache import run_snippets
from engine.registry import AGENTS, COLLECTORS, agent_collectors, collectors_for
from engine.store import PostgresStore

app = FastAPI(title="Site Diagnosis Engine", version="0.1.0", docs_url="/api/v1/docs",
              openapi_url="/api/v1/openapi.json")



def require_api_key(authorization: str = Header(default="")) -> None:
    settings = get_settings()
    if not settings.engine_api_key:
        if settings.deploy_target == "local":
            return  # local development without a key
        raise HTTPException(503, "ENGINE_API_KEY is not configured")
    token = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, settings.engine_api_key):
        raise HTTPException(401, "invalid API key")


api = Depends(require_api_key)

FINISHED = ("completed", "completed_partial", "failed", "cancelled")

# Results that can't change once a run has finished (its progress, issue cards and preview manifest),
# kept in this process so a warm instance answers without the database or storage. Rebuilding a
# preview or deleting a run clears them.
_MEMO: OrderedDict[tuple[str, str], Any] = OrderedDict()
_MEMO_MAX = 96
_MEMO_LOCK = threading.Lock()


def _recall(kind: str, run_id: str) -> Any:
    with _MEMO_LOCK:
        value = _MEMO.get((kind, run_id))
        if value is not None:
            _MEMO.move_to_end((kind, run_id))
        return value


def _remember(kind: str, run_id: str, value: Any) -> Any:
    with _MEMO_LOCK:
        _MEMO[(kind, run_id)] = value
        _MEMO.move_to_end((kind, run_id))
        while len(_MEMO) > _MEMO_MAX:
            _MEMO.popitem(last=False)
    return value


def _forget(run_id: str) -> None:
    with _MEMO_LOCK:
        for key in [k for k in _MEMO if k[1] == run_id]:
            del _MEMO[key]


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    primary_url: HttpUrl
    archetype: Literal["hospitality", "loans", "retail", "logistics"] | None = None
    crawl_consent_by: str = Field(min_length=1, description="Who confirmed the client allowed crawling")


class RunIn(BaseModel):
    client_id: str
    type: Literal["full", "agent"] = "agent"
    agents: list[str] | None = None
    crawl_cap: int | None = Field(default=None, ge=1, le=100)


@app.get("/api/v1/health")
def health() -> dict:
    s = get_settings()
    return {"status": "ok", "deploy_target": s.deploy_target, "runner": s.runner, "llm_mode": s.llm_mode,
            "blob_store": s.blob_store, "agents": sorted(AGENTS)}


@app.get("/api/v1/agents", dependencies=[api])
def agents() -> list[dict]:
    return [{"id": a.id, "name": a.name, "pillar": a.pillar, "version": a.version,
             "requires": sorted(a.requires), "counts_toward_readiness": a.counts_toward_readiness,
             **catalog.AGENTS[a.id],  # question, outcome, how, example
             "reads": agent_collectors(a.id), "collectors": collectors_for([a.id]),
             "checks": [c.model_dump() for c in a.checks]} for a in AGENTS.values()]


@app.get("/api/v1/collectors", dependencies=[api])
def collectors() -> list[dict]:
    """Evidence collectors in dependency order, with the agents that read each one."""
    order = collectors_for(sorted(AGENTS))
    used_by = {cid: sorted(aid for aid in AGENTS if cid in collectors_for([aid])) for cid in COLLECTORS}
    return [{"id": cid, "name": COLLECTORS[cid].name, **catalog.COLLECTORS[cid],
             "group_label": catalog.COLLECTOR_GROUPS[catalog.COLLECTORS[cid]["group"]],
             "used_by": used_by[cid]} for cid in order]


@app.post("/api/v1/clients", dependencies=[api], status_code=201)
def create_client(body: ClientIn) -> dict:
    try:
        check_url(str(body.primary_url))
    except UnsafeURLError as exc:
        raise HTTPException(422, f"URL not allowed: {exc}") from exc
    return repo.create_client(body.name, str(body.primary_url), archetype=body.archetype,
                              crawl_consent_by=body.crawl_consent_by)


@app.get("/api/v1/clients", dependencies=[api])
def list_clients() -> list[dict]:
    return repo.list_clients()


@app.post("/api/v1/runs", dependencies=[api], status_code=202)
def create_run(body: RunIn, background: BackgroundTasks) -> dict:
    settings = get_settings()
    agent_ids = sorted(AGENTS) if body.type == "full" else (body.agents or [])
    try:
        specs = plan_run(agent_ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    run = repo.create_run(body.client_id, body.type, agent_ids, body.crawl_cap or settings.crawl_cap_default, specs)
    run_id = str(run["id"])
    if settings.runner == "inline":
        background.add_task(run_inline, run_id)
    elif settings.runner == "http":
        background.add_task(trigger_dispatch, settings)
    return {"run_id": run_id, "status": run["status"], "agents": agent_ids}


@app.get("/api/v1/runs", dependencies=[api])
def list_runs(limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    return repo.list_runs(limit)


@app.delete("/api/v1/runs/{run_id}", dependencies=[api])
def delete_run(run_id: str) -> dict:
    """Delete a finished run for good: its reports, previews and microsites, and its snapshot and client
    when nothing else uses them."""
    if repo.get_run(run_id) is None:
        raise HTTPException(404, "run not found")
    if not delete_run_everywhere(run_id, make_blob_store(get_settings())):
        raise HTTPException(409, "the run is still in progress; delete it after it finishes")
    _forget(run_id)
    return {"run_id": run_id, "deleted": True}


@app.get("/api/v1/runs/{run_id}", dependencies=[api])
def get_run(run_id: str) -> dict:
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return run


@app.get("/api/v1/runs/{run_id}/progress", dependencies=[api])
def run_progress(run_id: str) -> dict:
    """Stages, per-component state and a feed of finished work, from the task table."""
    cached = _recall("progress", run_id)
    if cached is not None:
        return cached
    overview = repo.run_overview(run_id)
    if overview is None:
        raise HTTPException(404, "run not found")
    run, ctx = overview["run"], overview["ctx"]
    head = {k: run[k] for k in ("id", "type", "agents", "crawl_cap", "created_at", "started_at", "finished_at")}
    head["client"] = {"name": ctx["name"], "primary_url": ctx["primary_url"], "archetype": overview["archetype"]}
    result = {"run": head, **progress.project(run, overview["tasks"])}
    return _remember("progress", run_id, result) if run["status"] in FINISHED else result


class ArchetypeIn(BaseModel):
    archetype: Literal["hospitality", "loans", "retail", "logistics"]


@app.post("/api/v1/runs/{run_id}/archetype", dependencies=[api])
def confirm_archetype(run_id: str, body: ArchetypeIn, background: BackgroundTasks) -> dict:
    if not repo.confirm_archetype(run_id, body.archetype):
        raise HTTPException(404, "run not found")
    settings = get_settings()
    if settings.runner == "inline":
        background.add_task(run_inline, run_id)
    elif settings.runner == "http":
        background.add_task(trigger_dispatch, settings)
    return {"run_id": run_id, "archetype": body.archetype, "status": "running"}


@app.get("/api/v1/runs/{run_id}/report", dependencies=[api])
def intelligence_report(run_id: str) -> dict:
    report = repo.get_intelligence_report(run_id)
    if report is None:
        raise HTTPException(404, "no intelligence report yet (runs with 2+ agents produce one)")
    return report


@app.get("/api/v1/runs/{run_id}/findings", dependencies=[api])
def findings(run_id: str, agent: str | None = None, status: str | None = None) -> list[dict]:
    return repo.list_findings(run_id, agent, status)


@app.get("/api/v1/runs/{run_id}/agents", dependencies=[api])
def agent_reports(run_id: str) -> dict[str, dict]:
    """Every saved agent report for the run, keyed by agent id."""
    return repo.agent_reports(run_id)


@app.get("/api/v1/runs/{run_id}/issues", dependencies=[api])
def run_issues(run_id: str) -> dict:
    """Every reported issue as a card: evidence, proposed fix and before/after code where a change exists."""
    cached = _recall("issues", run_id)
    if cached is not None:
        return cached
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    patches = repo.list_patches(run_id)
    snippets = run_snippets(run_id, str(run["snapshot_id"]), patches, PostgresStore(), make_blob_store(get_settings()))
    result = {"issues": build_issue_cards(repo.list_findings(run_id), patches, snippets)}
    return _remember("issues", run_id, result) if run["status"] in FINISHED else result


class MicrositeIn(BaseModel):
    client_slug: str | None = Field(default=None, max_length=60)
    published_by: str | None = Field(default=None, max_length=200)


@app.post("/api/v1/runs/{run_id}/microsite", dependencies=[api], status_code=201)
def publish_microsite(run_id: str, body: MicrositeIn) -> dict:
    """Publish the run's diagnosed URL, with every placeable change applied, as a microsite version."""
    try:
        return build_microsite(run_id, PostgresStore(), make_blob_store(get_settings()),
                               client_slug=body.client_slug, published_by=body.published_by)
    except ReviewError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/v1/microsites", dependencies=[api])
def microsites() -> list[dict]:
    """Every published version, newest first per client; live ones have no superseded or unpublished time."""
    return repo.list_microsites()


@app.post("/api/v1/microsites/{microsite_id}/unpublish", dependencies=[api])
def unpublish(microsite_id: str) -> dict:
    if not repo.unpublish_microsite(microsite_id):
        raise HTTPException(404, "no live microsite with that id")
    return {"id": microsite_id, "unpublished": True}


def _live(slug: str) -> dict:
    parts = slug.strip("/").split("/")
    if len(parts) < 3:
        raise HTTPException(404, "microsite not found")
    row = repo.get_live_microsite(parts[0], parts[1], "/".join(parts[2:]))
    if row is None:
        raise HTTPException(404, "microsite not found")
    return row


@app.get("/api/v1/microsites/live", dependencies=[api])
def live_microsite(slug: str) -> dict:
    """The live version at an address, without storage keys (the page HTML is fetched separately)."""
    return {k: v for k, v in _live(slug).items() if not k.endswith("_key")}


@app.get("/api/v1/microsites/live/html", dependencies=[api])
def live_microsite_html(slug: str, view: str = "fixed") -> Response:
    if view not in ("fixed", "annotated"):
        raise HTTPException(404, "unknown view")
    body = make_blob_store(get_settings()).get(_live(slug)[f"{view}_key"])
    headers = {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer", "Cache-Control": "public, max-age=60",
               "Content-Security-Policy": "sandbox allow-scripts allow-popups"}
    return Response(body, media_type="text/html; charset=utf-8", headers=headers)


@app.get("/api/v1/runs/{run_id}/preview", dependencies=[api])
def get_preview(run_id: str) -> dict:
    settings = get_settings()
    manifest = _manifest(run_id)
    if manifest is None:
        raise HTTPException(404, "no preview has been built for this run")
    return preview.for_workspace(settings, manifest)


def _manifest(run_id: str) -> dict | None:
    manifest = _recall("manifest", run_id) or preview.load_manifest(make_blob_store(get_settings()), run_id)
    return _remember("manifest", run_id, manifest) if manifest else None


@app.post("/api/v1/runs/{run_id}/preview", dependencies=[api])
def build_preview(run_id: str) -> dict:
    """Build the preview of the diagnosed page: every proposed change applied, including unreviewed ones,
    with the page's issue list (what was fixed and what is left)."""
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    if run["status"] not in ("completed", "completed_partial"):
        raise HTTPException(409, "the run has not finished")
    settings = get_settings()
    try:
        manifest = build_preview_bundle(run_id, PostgresStore(), make_blob_store(settings))
    except ReviewError as exc:
        raise HTTPException(422, str(exc)) from exc
    return preview.for_workspace(settings, _remember("manifest", run_id, manifest))


@app.get("/api/v1/preview/{run_id}/{index}/{variant}", include_in_schema=False)
def preview_page(run_id: str, index: int, variant: str, exp: int = 0, sig: str = "") -> Response:
    """One captured page for the workspace preview, behind a signed, expiring link. Sandboxed:
    the page gets an opaque origin, and only the dashboard origins may frame it."""
    settings = get_settings()
    if variant not in preview.VARIANTS or not preview.valid(settings, run_id, index, variant, exp, sig):
        raise HTTPException(403, "This preview link is invalid or has expired.")
    blobs = make_blob_store(settings)
    manifest = _manifest(run_id) or {}
    page = next((p for p in manifest.get("pages", []) if p["index"] == index), None)
    if page is None or not page.get(f"{variant}_key"):
        raise HTTPException(404, "page not found")
    headers = {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer",
               "Cache-Control": "private, max-age=300",
               "Content-Security-Policy": "sandbox allow-scripts allow-popups; "
                                          f"frame-ancestors {' '.join(settings.dashboard_origins.split())}"}
    return Response(blobs.get(page[f"{variant}_key"]), media_type="text/html; charset=utf-8", headers=headers)


@app.get("/api/v1/runs/{run_id}/agents/{agent_id}", dependencies=[api])
def agent_report(run_id: str, agent_id: str) -> dict:
    report = repo.get_agent_report(run_id, agent_id)
    if report is None:
        raise HTTPException(404, "no report for this agent in this run yet")
    return report


# ---------------------------------------------------------- internal (HMAC)

@app.post("/api/v1/internal/dispatch", include_in_schema=False)
def internal_dispatch(x_signature: str = Header(default="")) -> dict:
    settings = get_settings()
    if not verify("dispatch", x_signature, settings.internal_secret):
        raise HTTPException(401, "bad signature")
    return {"dispatched": dispatch(make_env(settings))}


@app.post("/api/v1/internal/execute/{task_id}", include_in_schema=False)
def internal_execute(task_id: str, x_lease_token: str = Header(default=""),
                     x_signature: str = Header(default="")) -> dict:
    settings = get_settings()
    if not verify(f"{task_id}:{x_lease_token}", x_signature, settings.internal_secret):
        raise HTTPException(401, "bad signature")
    task = repo.get_task(task_id)
    if task is None or str(task["lease_token"]) != x_lease_token or task["status"] != "running":
        return {"status": "ignored"}  # lease moved on; another invocation owns it
    status = execute_task(task, make_env(settings))
    trigger_dispatch(settings)  # self-chaining: keep the run flowing
    return {"status": status}
