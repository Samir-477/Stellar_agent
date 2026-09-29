"""REST API (v1). A plain FastAPI app: runs on Vercel via api/index.py and under
uvicorn when self-hosted."""

from __future__ import annotations

import hmac
from typing import Literal

import httpx

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field, HttpUrl

from engine import catalog, progress
from engine.issues import build_issue_cards
from engine.core.blobstore import make_blob_store
from engine.core.config import get_settings
from engine.core.net import UnsafeURLError, check_url
from engine.orchestrator import repo
from engine.orchestrator.planner import plan_run
from engine.orchestrator.runner import dispatch, make_env, run_inline, trigger_dispatch, verify
from engine.orchestrator.executor import execute_task
from engine.output import preview
from engine.output.bundle import build_share_bundle
from engine.output.microsite import MAX_ISSUES, MicrositeError, build_microsite, review_entry_page
from engine.output.snippet_cache import run_snippets
from engine.output.viewer import router as share_router
from engine.registry import AGENTS, COLLECTORS, agent_collectors, collectors_for
from engine.store import PostgresStore

app = FastAPI(title="Site Diagnosis Engine", version="0.1.0", docs_url="/api/v1/docs",
              openapi_url="/api/v1/openapi.json")


app.include_router(share_router)  # /r/{token}: public share links (token-checked, noindex)


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
def list_runs(limit: int = Query(50, ge=1, le=200), archived: bool = False) -> list[dict]:
    return repo.list_runs(limit, archived=archived)


@app.patch("/api/v1/runs/{run_id}/archive", dependencies=[api])
def archive_run(run_id: str, body: dict) -> dict:
    archived = body.get("archived")
    if not isinstance(archived, bool):
        raise HTTPException(422, "archived must be true or false")
    try:
        updated = repo.set_run_archived(run_id, archived)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    if not updated:
        raise HTTPException(409, "run not found or still in progress")
    return {"run_id": run_id, "archived": archived}


@app.get("/api/v1/runs/{run_id}", dependencies=[api])
def get_run(run_id: str) -> dict:
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return run


@app.get("/api/v1/runs/{run_id}/progress", dependencies=[api])
def run_progress(run_id: str) -> dict:
    """Stages, per-component state and a feed of finished work, from the task table."""
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    ctx = repo.run_context(run_id)
    head = {k: run[k] for k in ("id", "type", "agents", "crawl_cap", "created_at", "started_at", "finished_at")}
    head["client"] = {"name": ctx["name"], "primary_url": ctx["primary_url"], "archetype": repo.run_archetype(ctx)}
    return {"run": head, **progress.project(run, repo.run_tasks(run_id))}


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
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    patches = repo.list_patches(run_id)
    snippets = run_snippets(run_id, str(run["snapshot_id"]), patches, PostgresStore(), make_blob_store(get_settings()))
    return {"issues": build_issue_cards(repo.list_findings(run_id), patches, snippets)}


@app.get("/api/v1/runs/{run_id}/page-issues", dependencies=[api])
def page_issues(run_id: str) -> dict:
    """The diagnosed page's issues, fixed first, exactly as a microsite of this run would list them."""
    try:
        review = review_entry_page(run_id, PostgresStore(), make_blob_store(get_settings()))
    except MicrositeError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"issues": review.issues[:MAX_ISSUES], "changes_placed": len(review.result.placed),
            "changes_total": len(review.patches)}


class MicrositeIn(BaseModel):
    client_slug: str | None = Field(default=None, max_length=60)
    published_by: str | None = Field(default=None, max_length=200)


@app.post("/api/v1/runs/{run_id}/microsite", dependencies=[api], status_code=201)
def publish_microsite(run_id: str, body: MicrositeIn) -> dict:
    """Publish the run's diagnosed URL, with every placeable change applied, as a microsite version."""
    try:
        return build_microsite(run_id, PostgresStore(), make_blob_store(get_settings()),
                               client_slug=body.client_slug, published_by=body.published_by)
    except MicrositeError as exc:
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
    if view not in ("fixed", "annotated", "original"):
        raise HTTPException(404, "unknown view")
    body = make_blob_store(get_settings()).get(_live(slug)[f"{view}_key"])
    headers = {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer", "Cache-Control": "public, max-age=60",
               "Content-Security-Policy": "sandbox allow-scripts allow-popups"}
    return Response(body, media_type="text/html; charset=utf-8", headers=headers)


@app.get("/api/v1/runs/{run_id}/preview", dependencies=[api])
def get_preview(run_id: str) -> dict:
    settings = get_settings()
    manifest = preview.load_manifest(make_blob_store(settings), run_id)
    if manifest is None:
        raise HTTPException(404, "no preview has been built for this run")
    return preview.for_workspace(settings, manifest)


@app.post("/api/v1/runs/{run_id}/preview", dependencies=[api])
def build_preview(run_id: str) -> dict:
    """Build the internal preview: every proposed change applied, including unreviewed ones."""
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    if run["status"] not in ("completed", "completed_partial"):
        raise HTTPException(409, "the run has not finished")
    settings = get_settings()
    try:
        bundle = build_share_bundle(run_id, PostgresStore(), make_blob_store(settings), include_proposed=True)
    except (FileNotFoundError, httpx.HTTPStatusError) as exc:
        # The run's captured pages live in another blob store (e.g. a run captured with BLOB_STORE=local).
        raise HTTPException(424, f"The captured pages for this run aren't in this engine's storage "
                                 f"({settings.blob_store}). Build the preview where the run was captured.") from exc
    return preview.for_workspace(settings, bundle["manifest"])


@app.get("/api/v1/preview/{run_id}/{index}/{variant}", include_in_schema=False)
def preview_page(run_id: str, index: int, variant: str, exp: int = 0, sig: str = "") -> Response:
    """One captured page for the workspace preview, behind a signed, expiring link. Sandboxed:
    the page gets an opaque origin, and only the dashboard origins may frame it."""
    settings = get_settings()
    if variant not in preview.VARIANTS or not preview.valid(settings, run_id, index, variant, exp, sig):
        raise HTTPException(403, "This preview link is invalid or has expired.")
    blobs = make_blob_store(settings)
    manifest = preview.load_manifest(blobs, run_id) or {}
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
