"""Runners call the same `execute_task` in different environments (docs/spec/10):

  inline  local development: execute a run's tasks in this process until it finishes
  worker  self-hosted: a long-running loop pulling from the task queue
  http    Vercel: dispatch claims tasks and invokes one function call per task
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from engine.core.blobstore import make_blob_store
from engine.core.config import Settings, get_settings
from engine.orchestrator import repo
from engine.orchestrator.executor import (Env, default_llm_factory, default_pagespeed_factory,
                                          default_search_factory, execute_task)
from engine.store import PostgresStore

log = logging.getLogger("engine.runner")
MAX_INFRA_FAILURES = 5  # consecutive tasks that couldn't even be recorded: the database is likely down


def _execute_safely(task: dict, env: Env) -> bool:
    """Run a task. execute_task records every task error itself; what can still escape is an
    infrastructure failure while recording (e.g. the database connection dropping). That is logged,
    not fatal: the task's lease expires and the queue hands it out again."""
    try:
        execute_task(task, env)
        return True
    except Exception:  # noqa: BLE001 - see docstring
        log.exception("task %s (%s %s) could not be completed or recorded; it will be retried when its lease "
                      "expires", task.get("id"), task.get("kind"), task.get("ref"))
        return False


def make_env(settings: Settings | None = None) -> Env:
    settings = settings or get_settings()
    return Env(settings, PostgresStore(), make_blob_store(settings), default_llm_factory(settings),
               search_factory=default_search_factory(settings),
               pagespeed_factory=default_pagespeed_factory(settings))


def _claim(env: Env, limit: int, run_id: str | None) -> list[dict]:
    s = env.settings
    repo.sweep(s.task_max_attempts)
    return repo.claim(limit, run_id=run_id, lease_s=s.task_lease_s, max_attempts=s.task_max_attempts,
                      run_cap=s.run_max_concurrency)


def run_inline(run_id: str, env: Env | None = None, *, max_seconds: float = 1800) -> dict:
    """Execute every task of one run in this process, sequentially."""
    env = env or make_env()
    if repo.get_run(run_id)["status"] != "awaiting_confirmation":
        repo.set_run_status(run_id, "running")
    deadline = time.monotonic() + max_seconds
    failures = 0
    while time.monotonic() < deadline:
        tasks = _claim(env, 1, run_id)
        if tasks:
            if _execute_safely(tasks[0], env):
                failures = 0
                continue
            failures += 1
            if failures >= MAX_INFRA_FAILURES:
                raise RuntimeError(f"stopping run {run_id}: {failures} tasks in a row couldn't be recorded "
                                   "(database unavailable?); run it again to resume")
            time.sleep(min(2 ** failures, 30))
            continue
        state = repo.run_has_open_tasks(run_id)
        if not state["open"] or repo.get_run(run_id)["status"] == "awaiting_confirmation":
            break
        time.sleep(1)  # waiting for a retry backoff
    return repo.get_run(run_id)


def worker_loop(env: Env | None = None, *, concurrency: int = 4, idle_sleep: float = 1.0) -> None:
    """Long-running worker for self-hosting (RUNNER=worker)."""
    env = env or make_env()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        while True:
            tasks = _claim(env, concurrency, None)
            if not tasks:
                time.sleep(idle_sleep)
                continue
            list(pool.map(lambda t: _execute_safely(t, env), tasks))


# ------------------------------------------------------------ http (Vercel)

def sign(message: str, secret: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify(message: str, signature: str, secret: str) -> bool:
    return bool(secret) and hmac.compare_digest(sign(message, secret), signature or "")


def dispatch(env: Env | None = None, *, limit: int = 8) -> int:
    """Claim ready tasks and invoke /internal/execute for each (one function call per task)."""
    env = env or make_env()
    s = env.settings
    if not s.internal_secret:
        raise RuntimeError("INTERNAL_SECRET must be set for RUNNER=http")
    tasks = _claim(env, limit, None)
    with httpx.Client(timeout=httpx.Timeout(2.0, read=1.0)) as client:
        for task in tasks:
            message = f"{task['id']}:{task['lease_token']}"
            try:
                headers = {"X-Lease-Token": str(task["lease_token"]),
                           "X-Signature": sign(message, s.internal_secret)}
                if s.vercel_automation_bypass_secret:
                    headers["x-vercel-protection-bypass"] = s.vercel_automation_bypass_secret
                client.post(f"{s.app_base_url}/api/v1/internal/execute/{task['id']}", headers=headers)
            except httpx.ReadTimeout:
                pass  # expected: we don't wait for the task to finish
            except httpx.HTTPError as exc:
                log.warning("could not invoke task %s: %s (lease will expire and it will be retried)",
                            task["id"], exc)
    return len(tasks)


def trigger_dispatch(settings: Settings) -> None:
    """Fire-and-forget call to /internal/dispatch (self-chaining after each task)."""
    try:
        headers = {"X-Signature": sign("dispatch", settings.internal_secret)}
        if settings.vercel_automation_bypass_secret:
            headers["x-vercel-protection-bypass"] = settings.vercel_automation_bypass_secret
        httpx.post(f"{settings.app_base_url}/api/v1/internal/dispatch",
                   headers=headers,
                   timeout=httpx.Timeout(2.0, read=0.5))
    except httpx.HTTPError:
        pass  # pg_cron's heartbeat will dispatch anyway
