"use client";

import Link from "next/link";
import { RotateCcw, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Pager, usePaged } from "@/components/workspace/pager";
import { RunStatusLabel, isFinished } from "@/components/workspace/run-status";
import { formatDate, formatDuration, urlPath } from "@/lib/format";
import { PILLAR_ORDER, PILLARS } from "@/lib/pillars";
import type { RunSummary } from "@/lib/types";

const FILTERS = [
  { id: "all", label: "All" },
  { id: "finished", label: "Finished" },
  { id: "active", label: "In progress" },
  { id: "problem", label: "Failed or partial" },
] as const;
type Filter = (typeof FILTERS)[number]["id"];

const COLUMNS = "lg:grid-cols-[minmax(0,2.2fr)_minmax(0,.8fr)_minmax(0,1.15fr)_minmax(0,1fr)_145px_70px_88px]";

function matches(run: RunSummary, filter: Filter): boolean {
  if (filter === "finished") return run.status === "completed";
  if (filter === "active") return !isFinished(run.status);
  if (filter === "problem") return run.status === "failed" || run.status === "completed_partial" || run.status === "cancelled";
  return true;
}

function ScoreCell({ run }: { run: RunSummary }) {
  if (!run.readiness) return <span className="text-xs text-ink-3">{run.agents.length < 2 ? "One agent" : "Not yet"}</span>;
  return (
    <span className="flex gap-3" aria-label={PILLAR_ORDER.map((p) => `${PILLARS[p].short} ${run.readiness?.[p]?.score ?? "not measured"}`).join(", ")}>
      {PILLAR_ORDER.map((p) => {
        const score = run.readiness?.[p]?.score;
        const tone = score === null || score === undefined ? "" : score < 50 ? "bg-red" : score < 70 ? "bg-[#d9a13b]" : "bg-signal";
        return (
          <span key={p} className="w-10" aria-hidden="true">
            <span className="block text-2xs text-ink-3">{PILLARS[p].short}</span>
            <span className="block font-display text-md font-semibold">{score ?? "–"}</span>
            <span className="mt-0.5 block h-[3px] w-full bg-rule"><span className={`block h-full ${tone}`} style={{ width: `${score ?? 0}%` }} /></span>
          </span>
        );
      })}
    </span>
  );
}

/** Run history as a table: the rows are comparable, so they line up in columns. */
export function SessionsTable({ runs, archived }: { runs: RunSummary[]; archived: RunSummary[] }) {
  const [activeRuns, setActiveRuns] = useState(runs);
  const [hiddenRuns, setHiddenRuns] = useState(archived);
  const [view, setView] = useState<"active" | "archived">("active");
  const [pending, setPending] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const source = view === "active" ? activeRuns : hiddenRuns;
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return source.filter((r) => (view === "archived" || matches(r, filter)) && (!q || r.client_name.toLowerCase().includes(q) || r.primary_url.toLowerCase().includes(q)));
  }, [source, query, filter, view]);
  const paged = usePaged(shown, 10);

  async function changeArchive(run: RunSummary, archive: boolean) {
    setBusy(run.id);
    setError("");
    try {
      const response = await fetch(`/api/workspace/runs/${run.id}/archive`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ archived: archive }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Couldn't update the run.");
      setActiveRuns((rows) => archive ? rows.filter((r) => r.id !== run.id) : [run, ...rows].sort((a, b) => b.created_at.localeCompare(a.created_at)));
      setHiddenRuns((rows) => archive ? [run, ...rows].sort((a, b) => b.created_at.localeCompare(a.created_at)) : rows.filter((r) => r.id !== run.id));
      setPending(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Couldn't update the run.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mt-12">
      <div className="mb-5 flex gap-2" role="group" aria-label="Session visibility">
        <button type="button" aria-pressed={view === "active"} onClick={() => { setView("active"); paged.setPage(0); }} className={`min-h-11 rounded-[3px] px-4 text-sm font-semibold ${view === "active" ? "bg-ink text-white" : "border border-rule text-ink-2"}`}>Current {activeRuns.length}</button>
        <button type="button" aria-pressed={view === "archived"} onClick={() => { setView("archived"); paged.setPage(0); }} className={`min-h-11 rounded-[3px] px-4 text-sm font-semibold ${view === "archived" ? "bg-ink text-white" : "border border-rule text-ink-2"}`}>Hidden {hiddenRuns.length}</button>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="relative min-w-[240px] flex-1 sm:max-w-[380px]">
          <span className="sr-only">Search by client or page</span>
          <Search aria-hidden="true" size={16} className="absolute top-1/2 left-3 -translate-y-1/2 text-ink-3" />
          <input type="search" value={query} onChange={(e) => { setQuery(e.target.value); paged.setPage(0); }} placeholder="Search by client or page"
                 className="min-h-11 w-full rounded-[3px] border border-rule-strong bg-paper pr-3 pl-9 text-base outline-none placeholder:text-ink-3 focus-visible:border-signal focus-visible:shadow-[0_0_0_3px_#d6f2df]" />
        </label>
        {view === "active" && <div role="group" aria-label="Status" className="flex flex-wrap border border-rule-strong">
          {FILTERS.map((f) => (
            <button key={f.id} type="button" aria-pressed={filter === f.id} onClick={() => { setFilter(f.id); paged.setPage(0); }}
                    className={`min-h-11 px-3.5 text-sm font-medium transition-colors [&+&]:border-l [&+&]:border-rule-strong ${filter === f.id ? "bg-ink text-white" : "text-ink-2 hover:bg-mist"}`}>
              {f.label}
            </button>
          ))}
        </div>}
        <p className="ml-auto text-sm text-ink-3" aria-live="polite">{shown.length} of {source.length} runs</p>
      </div>
      {error && <p className="mt-4 border-l-[3px] border-red bg-red-bg px-4 py-3 text-sm text-red" role="alert">{error}</p>}
      <div className="mt-5"><Pager page={paged.page} pages={paged.pages} total={paged.total} size={paged.size} onPage={paged.setPage} noun="runs" /></div>

      <div className="mt-5 border-t border-rule">
        <div className={`hidden gap-6 border-b border-rule px-4 py-3 text-2xs font-semibold text-ink-3 lg:grid ${COLUMNS}`}>
          <span>Client and page</span><span>Agents</span><span>Started</span><span>Status</span><span>Readiness</span><span>Priorities</span><span>Manage</span>
        </div>
        <ul>
          {paged.rows.map((run) => (
            <li key={run.id}>
              <div className={`grid gap-3 border-b border-rule px-4 py-5 lg:items-center lg:gap-6 ${COLUMNS}`}>
                <span className="min-w-0">
                  <Link href={`/runs/${run.id}`} className="block text-base font-semibold hover:text-signal hover:underline">{run.client_name}</Link>
                  <span className="block truncate font-mono text-2xs text-ink-3" title={run.primary_url}>{urlPath(run.primary_url)}</span>
                </span>
                <span className="text-sm text-ink-2">
                  {run.type === "full" ? `All ${run.agents.length}` : run.agents.length > 4 ? `${run.agents.length} agents` : run.agents.join(", ")}
                </span>
                <span className="text-sm text-ink-2">
                  {formatDate(run.started_at ?? run.created_at)}
                  <span className="block font-mono text-2xs text-ink-3">
                    {isFinished(run.status) ? `took ${formatDuration(run.started_at, run.finished_at)}` : `${run.tasks_done} of ${run.tasks_total} tasks`}
                  </span>
                </span>
                <span><RunStatusLabel status={run.status} /></span>
                <ScoreCell run={run} />
                <span className="text-sm">
                  {run.lanes ? (
                    <>
                      <span className="block"><span className="font-semibold">{run.lanes.now}</span> <span className="text-ink-3">now</span></span>
                      <span className="block"><span className="font-semibold">{run.lanes.next}</span> <span className="text-ink-3">next</span></span>
                    </>
                  ) : <span className="text-ink-3">None</span>}
                </span>
                {view === "active" ? (
                  <button type="button" onClick={() => setPending(run.id)} disabled={!isFinished(run.status) || busy === run.id} aria-label={`Hide ${run.client_name} run`} title={isFinished(run.status) ? "Hide run" : "A run can be hidden after it finishes"} className="flex min-h-11 items-center justify-center gap-1.5 rounded-[3px] px-2 text-xs text-ink-3 hover:bg-red-bg hover:text-red disabled:opacity-30"><Trash2 size={15} />Hide</button>
                ) : (
                  <button type="button" onClick={() => changeArchive(run, false)} disabled={busy === run.id} aria-label={`Restore ${run.client_name} run`} title="Restore run" className="flex min-h-11 items-center justify-center gap-1.5 rounded-[3px] px-2 text-xs text-signal hover:bg-soft disabled:opacity-50"><RotateCcw size={15} />Restore</button>
                )}
              </div>
              {pending === run.id && <div className="flex flex-wrap items-center justify-between gap-4 border-b border-rule bg-amber-bg px-4 py-4 text-sm"><p>Hide this run from Sessions? Its reports and preview stay available and you can restore it from Hidden.</p><div className="flex gap-2"><button type="button" onClick={() => setPending(null)} className="min-h-10 rounded-[3px] border border-rule-strong bg-paper px-4">Cancel</button><button type="button" onClick={() => changeArchive(run, true)} disabled={busy === run.id} className="min-h-10 rounded-[3px] bg-ink px-4 font-semibold text-white disabled:opacity-50">{busy === run.id ? "Hiding…" : "Hide run"}</button></div></div>}
            </li>
          ))}
        </ul>
        {!shown.length && <p className="px-4 py-10 text-base text-ink-3">No runs match this search.</p>}
      </div>
      <div className="mt-5">
        <Pager page={paged.page} pages={paged.pages} total={paged.total} size={paged.size} onPage={paged.setPage} noun="runs" />
      </div>
    </div>
  );
}
