"""SQL for clients, runs and the task queue.

The `tasks` table is the queue. Workers claim ready tasks with
FOR UPDATE SKIP LOCKED and a lease; an expired lease makes the task claimable
again (up to max attempts). Plain Postgres, so it moves to self-hosting as-is.

Readiness: a normal task runs when every dependency succeeded (or was partial);
a barrier task runs when every dependency has finished in any state.
"""

from __future__ import annotations

import uuid
from typing import Any

from engine.core.db import connection, json
from engine.orchestrator.planner import TaskSpec
from engine.schemas import AgentReport, Finding, Patch

TERMINAL = ("succeeded", "partial", "failed", "skipped")


# ------------------------------------------------------------------- clients

def create_client(name: str, primary_url: str, *, archetype: str | None = None,
                  crawl_consent_by: str | None = None) -> dict:
    with connection() as conn:
        return conn.execute(
            "insert into clients (name, primary_url, archetype, crawl_consent_by, crawl_consent_at) "
            "values (%s, %s, %s, %s, case when %s::text is null then null else now() end) returning *",
            (name, primary_url, archetype, crawl_consent_by, crawl_consent_by)).fetchone()


def list_clients() -> list[dict]:
    with connection() as conn:
        return conn.execute("select * from clients order by created_at desc").fetchall()


# ---------------------------------------------------------------------- runs

def create_run(client_id: str, run_type: str, agent_ids: list[str], crawl_cap: int,
               specs: list[TaskSpec], *, snapshot_id: str | None = None) -> dict:
    ids = {spec.key: str(uuid.uuid4()) for spec in specs}
    with connection() as conn:
        if snapshot_id:
            snapshot = {"id": snapshot_id}
        else:
            snapshot = conn.execute("insert into snapshots (client_id, crawl_cap) values (%s, %s) returning id",
                                    (client_id, crawl_cap)).fetchone()
        run = conn.execute(
            "insert into runs (client_id, snapshot_id, type, agents, crawl_cap) values (%s,%s,%s,%s,%s) returning *",
            (client_id, snapshot["id"], run_type, agent_ids, crawl_cap)).fetchone()
        with conn.cursor() as cur:
            cur.executemany(
                "insert into tasks (id, run_id, key, kind, ref, unit, deps, barrier_id, is_barrier) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(ids[s.key], run["id"], s.key, s.kind, s.ref, json(s.unit) if s.unit else None,
                  [ids[d] for d in s.deps], ids.get(s.barrier) if s.barrier else None, s.is_barrier)
                 for s in specs])
    return run


def get_run(run_id: str) -> dict | None:
    with connection() as conn:
        run = conn.execute("select * from runs where id=%s", (run_id,)).fetchone()
        if run is None:
            return None
        counts = conn.execute("select status, count(*) as n from tasks where run_id=%s group by status",
                              (run_id,)).fetchall()
    run["task_counts"] = {row["status"]: row["n"] for row in counts}
    return run


def run_context(run_id: str) -> dict:
    with connection() as conn:
        return conn.execute(
            "select r.id as run_id, r.snapshot_id, r.crawl_cap, r.token_budget, c.id as client_id, c.name, "
            "c.primary_url, c.archetype, c.locations, c.competitors "
            "from runs r join clients c on c.id = r.client_id where r.id=%s", (run_id,)).fetchone()


def run_archetype(ctx: dict) -> str | None:
    """The business type a run's agents used. C3 records it as evidence and agents read it from there
    (engine/agents/common.archetype); a confident detection never reaches the client record, so the
    client record is only the fallback. `ctx` is a run_context row."""
    from engine.collectors.c03_archetype import CONFIRM_THRESHOLD  # C3 imports the queue; avoid a cycle

    with connection() as conn:
        row = conn.execute("select payload from evidence where snapshot_id=%s and type='archetype' "
                           "order by captured_at desc limit 1", (ctx["snapshot_id"],)).fetchone()
    found = row["payload"] if row else {}
    if found.get("archetype") and (found.get("source") == "team" or found.get("confidence", 0) >= CONFIRM_THRESHOLD):
        return found["archetype"]
    return ctx["archetype"]


def set_run_status(run_id: str, status: str, *, note: str | None = None) -> None:
    with connection() as conn:
        conn.execute(
            "update runs set status=%s, note=coalesce(%s, note), "
            "started_at=coalesce(started_at, case when %s <> 'queued' then now() end), "
            "finished_at=case when %s in ('completed','completed_partial','failed','cancelled') then now() "
            "else finished_at end where id=%s",
            (status, note, status, status, run_id))


def latest_snapshot(client_id: str) -> dict | None:
    with connection() as conn:
        return conn.execute("select * from snapshots where client_id=%s order by created_at desc limit 1",
                            (client_id,)).fetchone()


def mark_collector_done(snapshot_id: str, collector_id: str) -> None:
    with connection() as conn:
        conn.execute("update snapshots set collectors_done = array_append(collectors_done, %s) "
                     "where id=%s and not (%s = any(collectors_done))", (collector_id, snapshot_id, collector_id))


def await_archetype(task: dict, proposal: dict) -> None:
    """Pause a run for archetype confirmation: the C3 task waits indefinitely."""
    with connection() as conn:
        conn.execute("update tasks set status='pending', lease_until=null, not_before='infinity', "
                     "attempts=greatest(attempts-1, 0), output=%s where id=%s and lease_token=%s",
                     (json({"proposal": proposal}), task["id"], task["lease_token"]))
        conn.execute("update runs set archetype_gate='awaiting', status='awaiting_confirmation', note=%s "
                     "where id=%s", (f"archetype proposal: {proposal.get('archetype')} "
                                     f"({proposal.get('confidence')})", task["run_id"]))


def confirm_archetype(run_id: str, archetype: str) -> bool:
    with connection() as conn:
        run = conn.execute("select client_id from runs where id=%s", (run_id,)).fetchone()
        if run is None:
            return False
        conn.execute("update clients set archetype=%s, archetype_source='confirmed' where id=%s",
                     (archetype, run["client_id"]))
        conn.execute("update runs set archetype_gate='confirmed', status='running', note=null where id=%s", (run_id,))
        conn.execute("update tasks set not_before=now() where run_id=%s and not_before='infinity'", (run_id,))
    return True


# --------------------------------------------------------------------- queue

def sweep(max_attempts: int) -> None:
    """Skip tasks whose upstream failed; fail tasks whose lease expired too often."""
    with connection() as conn:
        conn.execute(
            "update tasks set status='failed', error=coalesce(error, 'lease expired'), finished_at=now() "
            "where status='running' and lease_until < now() and attempts >= %s", (max_attempts,))
        while True:
            skipped = conn.execute(
                "update tasks t set status='skipped', error='an upstream step failed', finished_at=now() "
                "where t.status='pending' and not t.is_barrier and exists ("
                "  select 1 from tasks d where d.id = any(t.deps) and d.status in ('failed','skipped'))").rowcount
            if not skipped:
                break


def claim(limit: int, *, run_id: str | None, lease_s: int, max_attempts: int, run_cap: int) -> list[dict]:
    with connection() as conn:
        return conn.execute(
            """
            with ready as (
              select t.id from tasks t
              where ((t.status='pending' and t.not_before <= now())
                     or (t.status='running' and t.lease_until < now() and t.attempts < %(max)s))
                and (%(run)s::uuid is null or t.run_id = %(run)s::uuid)
                and not exists (
                  select 1 from tasks d where d.id = any(t.deps)
                  and case when t.is_barrier then d.status not in ('succeeded','partial','failed','skipped')
                           else d.status not in ('succeeded','partial') end)
                and (select count(*) from tasks r where r.run_id = t.run_id and r.status='running'
                     and r.lease_until >= now()) < %(cap)s
              order by t.created_at, t.key
              limit %(limit)s
              for update skip locked)
            update tasks t set status='running', attempts=t.attempts+1,
                   lease_until=now() + make_interval(secs => %(lease)s),
                   lease_token=gen_random_uuid(), started_at=now()
            from ready where t.id = ready.id
            returning t.*
            """,
            {"max": max_attempts, "run": run_id, "cap": run_cap, "limit": limit, "lease": lease_s}).fetchall()


def get_task(task_id: str) -> dict | None:
    with connection() as conn:
        return conn.execute("select * from tasks where id=%s", (task_id,)).fetchone()


def dep_tasks(task: dict) -> list[dict]:
    with connection() as conn:
        return conn.execute("select * from tasks where id = any(%s)", (task["deps"],)).fetchall()


def finish(task: dict, status: str, *, output: Any = None, error: str | None = None,
           children: list[TaskSpec] | None = None) -> bool:
    """Complete a claimed task; children attach to the task's barrier. Returns False
    if the lease was lost (another worker took over), in which case nothing changes."""
    with connection() as conn:
        owned = conn.execute("select 1 from tasks where id=%s and lease_token=%s and status='running' for update",
                             (task["id"], task["lease_token"])).fetchone()
        if not owned:
            return False
        if children:
            child_ids = [str(uuid.uuid4()) for _ in children]
            with conn.cursor() as cur:
                cur.executemany(
                    "insert into tasks (id, run_id, key, kind, ref, unit, deps, barrier_id, is_barrier) "
                    "values (%s,%s,%s,%s,%s,%s,%s,%s,false)",
                    [(cid, task["run_id"], child.key, child.kind, child.ref, json(child.unit), [],
                      task["barrier_id"]) for cid, child in zip(child_ids, children)])
            conn.execute("update tasks set deps = deps || %s::uuid[] where id=%s",
                         (child_ids, task["barrier_id"]))
        conn.execute("update tasks set status=%s, output=%s, error=%s, finished_at=now(), lease_until=null "
                     "where id=%s", (status, json(output) if output is not None else None, error, task["id"]))
    return True


def retry_or_fail(task: dict, error: str, max_attempts: int) -> str:
    with connection() as conn:
        row = conn.execute(
            "update tasks set status = case when attempts < %s then 'pending' else 'failed' end, "
            "error=%s, lease_until=null, not_before = now() + make_interval(secs => 5 * power(2, attempts)), "
            "finished_at = case when attempts < %s then null else now() end "
            "where id=%s and lease_token=%s returning status",
            (max_attempts, error[:2000], max_attempts, task["id"], task["lease_token"])).fetchone()
    return row["status"] if row else "lost"


def run_task_statuses(run_id: str) -> list[dict]:
    with connection() as conn:
        return conn.execute("select kind, ref, status, error from tasks where run_id=%s", (run_id,)).fetchall()


def run_tasks(run_id: str) -> list[dict]:
    """Task rows for the progress view, without bulky outputs: only an agent's finding count
    and C3's archetype proposal are read from `output`."""
    with connection() as conn:
        return conn.execute(
            "select kind, ref, status, is_barrier, unit, attempts, error, started_at, finished_at, "
            "case when kind = 'agent.reduce' then (output->>'findings')::int end as findings, "
            "case when ref = 'C3' then output->'proposal' end as proposal "
            "from tasks where run_id=%s order by created_at", (run_id,)).fetchall()


def list_runs(limit: int = 50, *, archived: bool = False) -> list[dict]:
    """Recent runs with their client, task totals, readiness and priority-lane sizes (one row each)."""
    with connection() as conn:
        return conn.execute(
            "select r.id, r.type, r.agents, r.status, r.note, r.crawl_cap, r.created_at, r.started_at, "
            "to_jsonb(r)->>'archived_at' as archived_at, "
            "r.finished_at, c.id as client_id, c.name as client_name, c.primary_url, c.archetype, "
            "t.total as tasks_total, t.done as tasks_done, i.body->'readiness' as readiness, "
            "case when i.body is not null then jsonb_build_object("
            "  'now', jsonb_array_length(coalesce(i.body->'what_to_fix_first'->'now', '[]')),"
            "  'next', jsonb_array_length(coalesce(i.body->'what_to_fix_first'->'next', '[]')),"
            "  'later', jsonb_array_length(coalesce(i.body->'what_to_fix_first'->'later', '[]')),"
            "  'investigate', jsonb_array_length(coalesce(i.body->'what_to_fix_first'->'investigate', '[]')),"
            "  'monitor', jsonb_array_length(coalesce(i.body->'what_to_fix_first'->'monitor', '[]'))) end as lanes "
            "from runs r join clients c on c.id = r.client_id "
            "left join lateral (select count(*) as total, count(*) filter (where status in "
            "  ('succeeded','partial','failed','skipped')) as done from tasks where run_id = r.id) t on true "
            "left join lateral (select body from reports where run_id = r.id and kind = 'intelligence' "
            "  order by created_at desc limit 1) i on true "
            "where (to_jsonb(r)->>'archived_at' is not null) = %s "
            "order by r.created_at desc limit %s", (archived, limit)).fetchall()


def set_run_archived(run_id: str, archived: bool) -> bool:
    """Only finished runs can be hidden; a running diagnosis must remain visible."""
    with connection() as conn:
        ready = conn.execute(
            "select 1 from information_schema.columns "
            "where table_name='runs' and column_name='archived_at'"
        ).fetchone()
        if not ready:
            raise RuntimeError("Run archive needs migration 0005_run_archive.sql before Hide or Restore can be used.")
        row = conn.execute(
            "update runs set archived_at=case when %s then now() else null end "
            "where id=%s and status in ('completed','completed_partial','failed','cancelled') "
            "returning id", (archived, run_id)).fetchone()
    return row is not None


def run_has_open_tasks(run_id: str) -> dict:
    with connection() as conn:
        return conn.execute(
            "select count(*) filter (where status in ('pending','running')) as open, "
            "min(not_before) filter (where status='pending') as next_at from tasks where run_id=%s",
            (run_id,)).fetchone()


# ------------------------------------------------------------------ results

def save_agent_result(run_id: str, agent_id: str, findings: list[Finding], patches: list[Patch],
                      report: AgentReport) -> None:
    with connection() as conn:
        conn.execute("delete from findings where run_id=%s and agent_id=%s", (run_id, agent_id))
        conn.execute("delete from patches where run_id=%s and agent_id=%s", (run_id, agent_id))
        conn.execute("delete from reports where run_id=%s and agent_id=%s and kind='agent'", (run_id, agent_id))
        with conn.cursor() as cur:
            cur.executemany(
                "insert into patches (run_id, agent_id, key, page_url, type, locator, before, after, rationale, "
                "confidence, payload) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(run_id, agent_id, p.key, p.page_url, p.type.value,
                  json(p.locator.model_dump()) if p.locator else None, p.before, p.after, p.rationale,
                  p.confidence.value, json(p.model_dump(mode="json"))) for p in patches])
            cur.executemany(
                "insert into findings (run_id, agent_id, agent_version, check_id, pillar, status, severity, "
                "confidence, title, pages, fingerprint, payload) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(run_id, agent_id, f.agent_version, f.check_id, f.pillar.value, f.status.value,
                  f.severity.value if f.severity else None, f.confidence.value, f.title, f.scope.pages,
                  f.fingerprint, json(f.model_dump(mode="json"))) for f in findings])
        conn.execute("insert into reports (run_id, kind, agent_id, body) values (%s,'agent',%s,%s)",
                     (run_id, agent_id, json(report.model_dump(mode="json"))))


def save_intelligence_report(run_id: str, body: dict) -> None:
    with connection() as conn:
        conn.execute("delete from reports where run_id=%s and kind='intelligence'", (run_id,))
        conn.execute("insert into reports (run_id, kind, body) values (%s,'intelligence',%s)", (run_id, json(body)))


def get_intelligence_report(run_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute("select body from reports where run_id=%s and kind='intelligence' "
                           "order by created_at desc limit 1", (run_id,)).fetchone()
    return row["body"] if row else None


def agent_reports(run_id: str) -> dict[str, dict]:
    with connection() as conn:
        rows = conn.execute("select agent_id, body from reports where run_id=%s and kind='agent'", (run_id,)).fetchall()
    return {r["agent_id"]: r["body"] for r in rows}


def list_findings(run_id: str, agent_id: str | None = None, status: str | None = None) -> list[dict]:
    sql, params = "select payload from findings where run_id=%s", [run_id]
    if agent_id:
        sql += " and agent_id=%s"
        params.append(agent_id)
    if status:
        sql += " and status=%s"
        params.append(status)
    with connection() as conn:
        return [row["payload"] for row in conn.execute(sql + " order by agent_id, check_id", params).fetchall()]


# ---------------------------------------------------------------- microsites

MICROSITE_LIST_COLUMNS = (
    "id, archetype, client_slug, page_path, client_name, source_url, page_title, run_id, changes_placed, "
    "changes_total, jsonb_array_length(issues) as issue_count, published_by, published_at, superseded_at, unpublished_at")


def insert_microsite(record: dict) -> dict:
    """Publish a version; the live version at the same address is superseded in the same transaction."""
    with connection() as conn:
        conn.execute("update microsites set superseded_at=now() where archetype=%s and client_slug=%s and "
                     "page_path=%s and superseded_at is null and unpublished_at is null",
                     (record["archetype"], record["client_slug"], record["page_path"]))
        return conn.execute(
            "insert into microsites (id, client_id, run_id, archetype, client_slug, page_path, client_name, source_url, "
            "page_title, fixed_key, annotated_key, original_key, issues, changes_placed, changes_total, published_by) "
            f"values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning {MICROSITE_LIST_COLUMNS}",
            (record["id"], record["client_id"], record["run_id"], record["archetype"], record["client_slug"],
             record["page_path"], record["client_name"], record["source_url"], record["page_title"],
             record["fixed_key"], record["annotated_key"], record["original_key"], json(record["issues"]),
             record["changes_placed"], record["changes_total"], record["published_by"])).fetchone()


def list_microsites() -> list[dict]:
    with connection() as conn:
        return conn.execute(f"select {MICROSITE_LIST_COLUMNS} from microsites "
                            "order by client_slug, published_at desc").fetchall()


def get_live_microsite(archetype: str, client_slug: str, page_path: str) -> dict | None:
    with connection() as conn:
        return conn.execute("select * from microsites where archetype=%s and client_slug=%s and page_path=%s and "
                            "superseded_at is null and unpublished_at is null", (archetype, client_slug, page_path)
                            ).fetchone()


def unpublish_microsite(microsite_id: str) -> bool:
    with connection() as conn:
        row = conn.execute("update microsites set unpublished_at=now() where id=%s and unpublished_at is null and "
                           "superseded_at is null returning id", (microsite_id,)).fetchone()
    return row is not None


def list_patches(run_id: str) -> list[dict]:
    """Every proposed change in the run, as stored (payload includes the locator)."""
    with connection() as conn:
        return [row["payload"] for row in conn.execute(
            "select payload from patches where run_id=%s order by agent_id, key", (run_id,)).fetchall()]


def get_agent_report(run_id: str, agent_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute("select body from reports where run_id=%s and agent_id=%s and kind='agent' "
                           "order by created_at desc limit 1", (run_id, agent_id)).fetchone()
    return row["body"] if row else None


# ---------------------------------------------------------------- LLM usage

def add_provider_usage(provider: str, units: int) -> None:
    with connection() as conn:
        conn.execute("insert into provider_usage (provider, units) values (%s, %s) on conflict (provider, day) "
                     "do update set units = provider_usage.units + excluded.units", (provider, units))


def llm_cache_get(key: str) -> str | None:
    with connection() as conn:
        row = conn.execute("select response from llm_cache where key=%s", (key,)).fetchone()
    return row["response"] if row else None


def llm_cache_put(key: str, provider: str, model: str, response: str) -> None:
    with connection() as conn:
        conn.execute("insert into llm_cache (key, provider, model, response) values (%s,%s,%s,%s) "
                     "on conflict (key) do nothing", (key, provider, model, response))


def record_llm_call(run_id: str | None, task_id: str | None, call: dict) -> None:
    with connection() as conn:
        conn.execute(
            "insert into llm_calls (run_id, task_id, prompt_ref, cache_key, provider, model, tokens_in, "
            "tokens_out, fallback_used, error) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (run_id, task_id, call["prompt_ref"], call["cache_key"], call["provider"], call["model"],
             call["tokens_in"], call["tokens_out"], call["fallback_used"], call["error"]))
        if run_id and (call["tokens_in"] or call["tokens_out"]):
            conn.execute("update runs set tokens_used = tokens_used + %s where id=%s",
                         (call["tokens_in"] + call["tokens_out"], run_id))
