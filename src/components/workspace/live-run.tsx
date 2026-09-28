"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { AgentDrawer } from "@/components/workspace/agent-drawer";
import { AgentIcon, SOURCE_ICONS } from "@/components/workspace/icons";
import { isFinished } from "@/components/workspace/run-status";
import { StateGlyph, stateLabel } from "@/components/workspace/status";
import { formatClock, formatDuration } from "@/lib/format";
import { PILLARS, PILLAR_ORDER } from "@/lib/pillars";
import type { ComponentProgress, ComponentState, Progress } from "@/lib/types";

const POLL_MS = 2500;
const GROUP_OF: Record<string, { id: string; label: string }> = {
  C1: { id: "site", label: "Site" }, C2: { id: "site", label: "Site" }, C3: { id: "site", label: "Site" },
  C4: { id: "site", label: "Site" }, C11: { id: "site", label: "Site" }, C5: { id: "search", label: "Search" },
  C6: { id: "search", label: "Search" }, C7: { id: "search", label: "Search" }, C8: { id: "search", label: "Search" },
  C9: { id: "ai", label: "AI answers" }, C10: { id: "ai", label: "AI answers" }, C12: { id: "web", label: "Wider web" },
};
const GROUP_ORDER = ["site", "search", "ai", "web"];
const FINISHED: ComponentState[] = ["done", "partial", "failed", "skipped", "reused"];

function detail(c: ComponentProgress): string {
  if (c.state === "reused") return "Reused from an earlier capture";
  if (c.state === "failed") return c.error ? `Failed: ${c.error}` : "Failed";
  if (c.state === "paused") return "Waiting for you to confirm";
  if (c.state === "running") {
    const steps = c.steps_total ? `${c.steps_done} of ${c.steps_total} steps` : "Planning its steps";
    return c.retrying ? `${steps}, retrying ${c.retrying}` : steps;
  }
  if (FINISHED.includes(c.state)) return `Done in ${formatDuration(c.started_at, c.finished_at)}`;
  return "Waiting for evidence";
}

function stageCaption(stage: Progress["stages"][number], p: Progress): string {
  const done = (list: ComponentProgress[]) => list.filter((c) => FINISHED.includes(c.state)).length;
  if (stage.state === "not_in_run") return "Needs 2 or more agents";
  if (stage.id === "collect") return stage.state === "paused" ? "Paused: confirm the business type" : `${done(p.collectors)} of ${p.collectors.length} collectors`;
  if (stage.id === "diagnose") return `${done(p.agents)} of ${p.agents.length} agents`;
  if (stage.id === "synthesize") return stage.state === "done" ? "Report written" : stage.state === "running" ? "Merging findings" : "After the agents";
  return stage.state === "done" ? "Ready to read" : "When every step ends";
}

function tileTone(state: ComponentState): string {
  if (state === "running") return "border-signal/40 bg-soft/40";
  if (state === "failed") return "border-red/40 bg-red-bg/40";
  if (state === "paused") return "border-amber/40 bg-amber-bg/50";
  return "border-rule bg-paper";
}

/** The live route board: stage route and live activity on top, then the collectors and agents as tiles. */
export function LiveRun({ runId, initial, live = true }: { runId: string; initial: Progress; live?: boolean }) {
  const router = useRouter();
  const reduce = useReducedMotion();
  const [progress, setProgress] = useState(initial);
  const [lastPoll, setLastPoll] = useState<Date>(() => new Date());
  const [pollError, setPollError] = useState("");
  const [openAgent, setOpenAgent] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [announcement, setAnnouncement] = useState("");
  const previous = useRef(initial);

  useEffect(() => {
    if (!live) return;
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    async function poll() {
      if (document.visibilityState === "visible") {
        try {
          const response = await fetch(`/api/workspace/runs/${runId}/progress`, { cache: "no-store" });
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || "Progress couldn't be loaded.");
          setProgress(data);
          setLastPoll(new Date());
          setPollError("");
          if (isFinished(data.status)) {
            router.refresh();
            return;
          }
        } catch (error) {
          setPollError(error instanceof Error ? error.message : "Progress couldn't be loaded.");
        }
      }
      if (!stopped) timer = setTimeout(poll, POLL_MS);
    }
    timer = setTimeout(poll, POLL_MS);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [runId, router, live]);

  useEffect(() => {
    if (!live) return;
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, [live]);

  // One calm announcement when a stage changes or an agent finishes, never for every count.
  useEffect(() => {
    const before = previous.current;
    const changed = progress.stages.find((s, i) => s.state !== before.stages[i]?.state);
    const doneNow = progress.agents.filter((a) => a.state === "done").length;
    const doneBefore = before.agents.filter((a) => a.state === "done").length;
    if (changed) setAnnouncement(`${changed.label}: ${stageLabel(changed.state)}.`);
    else if (doneNow > doneBefore) setAnnouncement(`${doneNow} of ${progress.agents.length} agents finished.`);
    previous.current = progress;
  }, [progress]);

  const bars = useMemo(() => [...progress.events].reverse().slice(-48), [progress.events]);
  const collectors = useMemo(() => [...progress.collectors].sort((a, b) =>
    GROUP_ORDER.indexOf(GROUP_OF[a.id]?.id) - GROUP_ORDER.indexOf(GROUP_OF[b.id]?.id) || Number(a.id.slice(1)) - Number(b.id.slice(1))),
  [progress.collectors]);
  const agents = useMemo(() => PILLAR_ORDER.flatMap((p) => progress.agents.filter((a) => a.pillar === p)
    .sort((a, b) => Number(a.id.slice(1)) - Number(b.id.slice(1)))), [progress.agents]);
  const elapsed = formatDuration(progress.run.started_at ?? progress.run.created_at, live ? new Date(now).toISOString() : progress.run.finished_at);
  const collectorsDone = progress.collectors.filter((c) => FINISHED.includes(c.state)).length;
  const agentsDone = progress.agents.filter((a) => FINISHED.includes(a.state)).length;
  const working = live && !isFinished(progress.status);
  const findings = progress.agents.reduce((sum, a) => sum + (a.findings ?? 0), 0);
  const failed = [...progress.collectors, ...progress.agents].filter((c) => c.state === "failed").length;
  const totals: [string, string][] = [
    ["Collectors done", `${collectorsDone} of ${progress.collectors.length}`],
    ["Agents done", `${agentsDone} of ${progress.agents.length}`],
    ["Findings saved", String(findings)],
    ["Failed steps", String(failed)],
  ];

  return (
    <div className="mt-10">
      <p className="sr-only" aria-live="polite">{announcement}</p>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        {/* Stage route: the order is real, so it is drawn as a route. */}
        <section aria-label="Run stages" className="relative flex flex-col border border-rule bg-paper">
          <div className="grid-field absolute inset-0 opacity-40" aria-hidden="true" />
          <ol className="relative grid flex-1 grid-cols-2 gap-8 px-8 pt-9 pb-8 sm:grid-cols-4 sm:gap-0">
            {progress.stages.map((stage, index) => {
              const next = progress.stages[index + 1];
              const lineDone = stage.state === "done";
              const lineLive = lineDone && next && (next.state === "running" || next.state === "paused");
              return (
                <li key={stage.id} className="relative sm:pr-6">
                  {next && (
                    <span aria-hidden="true" className={`absolute top-[11px] left-[30px] hidden h-[2px] sm:block ${lineLive ? "route-live" : lineDone ? "bg-signal" : "bg-rule-strong"}`}
                          style={{ width: "calc(100% - 30px)" }} />
                  )}
                  <StageNode state={stage.state} />
                  <p className="mt-5 font-mono text-2xs text-ink-3">0{index + 1}</p>
                  <p className="mt-1 font-display text-xl font-semibold tracking-tight">{stage.label}</p>
                  <p className={`mt-1.5 text-sm ${stage.state === "paused" ? "font-medium text-amber" : stage.state === "failed" ? "text-red" : "text-ink-2"}`}>
                    {stageCaption(stage, progress)}
                  </p>
                </li>
              );
            })}
          </ol>
          <dl className="relative grid grid-cols-2 border-t border-rule bg-paper sm:grid-cols-4">
            {totals.map(([label, value], i) => (
              <div key={label} className={`px-8 py-4 ${i ? "sm:border-l sm:border-rule" : ""} ${i % 2 ? "border-l border-rule sm:border-l" : ""}`}>
                <dt className="text-2xs text-ink-3">{label}</dt>
                <dd className={`mt-1 font-display text-2xl font-semibold ${label === "Failed steps" && failed ? "text-red" : ""}`}>{value}</dd>
              </div>
            ))}
          </dl>
          <div className="relative flex flex-wrap items-center gap-x-8 gap-y-1 border-t border-rule bg-mist/80 px-8 py-4 text-sm text-ink-2">
            <span><span className="font-semibold text-ink">{progress.tasks.done}</span> of {progress.tasks.total} planned tasks finished</span>
            {working && <span>{progress.tasks.running} working now</span>}
            <span>{live ? "Running for" : "Took"} <span className="font-mono text-xs text-ink">{elapsed}</span></span>
          </div>
        </section>

        {/* Live activity sits beside the route, so progress is readable without scrolling. */}
        <section aria-labelledby="activity-heading" className="flex min-h-[300px] flex-col border border-rule bg-paper">
          <div className="flex items-center justify-between gap-4 border-b border-rule px-6 py-4">
            <h2 id="activity-heading" className="flex items-center gap-2.5 text-sm font-semibold">
              <span aria-hidden="true" className={`h-2 w-2 rounded-full ${working ? "node-live bg-signal" : "bg-rule-strong"}`} />
              {working ? "Live activity" : "Activity"}
            </h2>
            <span className="text-2xs text-ink-3">
              {pollError ? <span className="text-red">{pollError} Retrying.</span> : working ? `Updated ${formatClock(lastPoll.toISOString())}` : `${progress.events.length} recent steps`}
            </span>
          </div>
          <div aria-hidden="true" className="flex h-12 items-end gap-[3px] border-b border-rule px-6 pb-3">
            {bars.map((event, index) => (
              <span key={`${event.at}-${index}`} className={`w-[4px] rounded-[1px] ${event.status === "failed" ? "bg-red" : event.kind.startsWith("agent") ? "bg-signal" : event.kind.startsWith("run") ? "bg-ink" : "bg-mint"}`}
                    style={{ height: event.kind.endsWith(".unit") ? 12 : event.kind.startsWith("run") ? 30 : 22 }} />
            ))}
            {!bars.length && <span className="text-2xs text-ink-3">Each finished step adds a bar.</span>}
          </div>
          <ul className="flex-1 overflow-y-auto px-6 py-2" style={{ maxHeight: 232 }}>
            <AnimatePresence initial={false}>
              {progress.events.slice(0, 12).map((event) => (
                <motion.li key={`${event.at}-${event.text}`} layout={!reduce}
                           initial={reduce ? false : { opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
                           transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
                           className="grid grid-cols-[64px_1fr] gap-3 border-b border-rule/70 py-2.5 text-sm last:border-b-0">
                  <span className="font-mono text-2xs leading-5 text-ink-3">{formatClock(event.at)}</span>
                  <span className={event.status === "failed" ? "text-red" : "text-ink"}>
                    {event.ref && <span className="mr-1.5 font-mono text-2xs text-signal">{event.ref}</span>}
                    {event.text}
                  </span>
                </motion.li>
              ))}
            </AnimatePresence>
            {!progress.events.length && <li className="py-3 text-sm text-ink-3">The first step is starting.</li>}
          </ul>
        </section>
      </div>
      {working && <p className="mt-3 text-xs text-ink-3">The plan grows as collectors discover pages and queries, so the task total can rise while the run works.</p>}

      {progress.archetype_proposal && <ArchetypeGate runId={runId} proposal={progress.archetype_proposal} onConfirmed={() => router.refresh()} />}
      {progress.status === "failed" && (
        <div role="alert" className="mt-8 border-l-[3px] border-red bg-red-bg px-6 py-5 text-md text-ink">
          <p className="font-semibold text-red">This run stopped.</p>
          <p className="mt-1 text-ink-2">{progress.note || "A step failed after its retries. Completed agent reports are still available below."}</p>
        </div>
      )}

      {/* Evidence tiles */}
      <section aria-labelledby="evidence-heading" className="mt-16">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="evidence-heading" className="font-display text-3xl font-semibold tracking-tight">Evidence</h2>
            <p className="mt-1.5 text-base text-ink-2">Collectors capture what the agents will read.</p>
          </div>
          <p className="text-sm text-ink-2"><span className="font-semibold text-ink">{collectorsDone}</span> of {progress.collectors.length} collectors done</p>
        </div>
        <ul className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {collectors.map((c) => {
            const group = GROUP_OF[c.id];
            const Icon = group ? SOURCE_ICONS[group.id] : undefined;
            return (
              <li key={c.id} className={`flex flex-col border p-5 transition-colors duration-300 ${tileTone(c.state)}`}>
                <div className="flex items-center justify-between gap-3">
                  <StateGlyph state={c.state} />
                  <span className="flex items-center gap-1.5 text-2xs text-ink-3">
                    {Icon && <Icon aria-hidden="true" size={12} />}{group?.label}
                  </span>
                </div>
                <p className="mt-4 flex items-baseline gap-2">
                  <span className="font-mono text-2xs text-signal">{c.id}</span>
                  <span className="text-md font-semibold">{c.name}</span>
                  <span className="sr-only">{stateLabel(c.state)}</span>
                </p>
                <p className={`mt-1 text-xs ${c.state === "failed" ? "text-red" : "text-ink-3"}`}>{detail(c)}</p>
                {c.state === "running" && c.steps_total > 0 && (
                  <span className="mt-4 block h-1 overflow-hidden bg-rule" aria-hidden="true">
                    <span className="block h-full bg-signal transition-[width] duration-500" style={{ width: `${(100 * c.steps_done) / c.steps_total}%` }} />
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      {/* Agent tiles, ordered SEO, AEO, GEO */}
      <section aria-labelledby="agents-live-heading" className="mt-16">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="agents-live-heading" className="font-display text-3xl font-semibold tracking-tight">Agents</h2>
            <p className="mt-1.5 text-base text-ink-2">Open any report as soon as its agent saves it.</p>
          </div>
          <p className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-ink-2">
            {PILLAR_ORDER.map((p) => {
              const own = progress.agents.filter((a) => a.pillar === p);
              return own.length ? (
                <span key={p}><span className="font-semibold text-ink">{PILLARS[p].short}</span> {own.filter((a) => FINISHED.includes(a.state)).length}/{own.length}</span>
              ) : null;
            })}
            <span><span className="font-semibold text-ink">{agentsDone}</span> of {progress.agents.length} done</span>
          </p>
        </div>
        <ul className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
          {agents.map((agent) => {
            const ready = agent.state === "done" || agent.state === "partial";
            return (
              <li key={agent.id}>
                <button type="button" disabled={!ready} onClick={() => setOpenAgent(agent.id)}
                        className={`group flex h-full w-full flex-col border p-5 text-left transition-colors duration-300 ${tileTone(agent.state)} ${ready ? "hover:border-signal/50 hover:bg-soft/40" : "cursor-default"}`}>
                  <span className="flex items-center justify-between gap-3">
                    <StateGlyph state={agent.state} />
                    <span className="font-mono text-2xs text-ink-3">{PILLARS[agent.pillar].short} {agent.id}</span>
                  </span>
                  <span className="mt-4 flex flex-1 items-start gap-2 text-md leading-snug font-semibold">
                    <span className="mt-0.5 text-signal"><AgentIcon id={agent.id} size={14} /></span>
                    {agent.name}
                  </span>
                  <span className={`mt-3 flex items-center gap-1 text-xs ${agent.state === "failed" ? "text-red" : ready ? "font-medium text-signal" : "text-ink-3"}`}>
                    {ready ? <>{agent.findings ?? 0} findings, open report <ArrowUpRight aria-hidden="true" size={13} /></>
                      : agent.state === "failed" ? (agent.error ?? "Failed") : stateLabel(agent.state)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      <AgentDrawer runId={runId} agentId={openAgent} onClose={() => setOpenAgent(null)} />
    </div>
  );
}

function stageLabel(state: string): string {
  return { done: "done", running: "in progress", waiting: "waiting", paused: "waiting for you", failed: "failed", not_in_run: "not part of this run" }[state] ?? state;
}

function StageNode({ state }: { state: string }) {
  const base = "relative z-10 flex h-6 w-6 items-center justify-center rounded-full";
  if (state === "done") return <span className={`${base} bg-signal text-white`} aria-label="Done"><svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 6.2 5 8.5l4.5-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg></span>;
  if (state === "running") return <span className={`${base} node-live bg-signal`} aria-label="In progress"><span className="h-2.5 w-2.5 rounded-full bg-white" /></span>;
  if (state === "paused") return <span className={`${base} bg-amber-bg ring-2 ring-amber`} aria-label="Waiting for you"><span className="h-2 w-2 rounded-full bg-amber" /></span>;
  if (state === "failed") return <span className={`${base} bg-red-bg ring-2 ring-red`} aria-label="Failed"><span className="h-2 w-2 rounded-full bg-red" /></span>;
  if (state === "not_in_run") return <span className={`${base} border-2 border-dashed border-rule-strong bg-paper`} aria-label="Not part of this run" />;
  return <span className={`${base} border-2 border-rule-strong bg-paper`} aria-label="Waiting" />;
}

function ArchetypeGate({ runId, proposal, onConfirmed }: { runId: string; proposal: NonNullable<Progress["archetype_proposal"]>; onConfirmed: () => void }) {
  const [choice, setChoice] = useState(proposal.archetype ?? "hospitality");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const options = [["hospitality", "Hotels and resorts"], ["loans", "Loans and lending"], ["retail", "Retail"], ["logistics", "Logistics"]];

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/workspace/runs/${runId}/archetype`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ archetype: choice }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The business type couldn't be saved.");
      onConfirmed();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The business type couldn't be saved.");
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="gate-heading" className="mt-8 border border-amber/40 bg-amber-bg px-7 py-6">
      <h2 id="gate-heading" className="font-display text-2xl font-semibold tracking-tight">Confirm the business type</h2>
      <p className="mt-2 max-w-[680px] text-base text-ink-2">
        The run paused because it wasn&apos;t sure what kind of business this is. The agents use it to choose the right
        checks, so confirm or correct it to continue.
      </p>
      <dl className="mt-4 grid gap-2 text-sm sm:grid-cols-[160px_1fr]">
        <dt className="text-ink-3">Suggested</dt>
        <dd className="font-semibold">{options.find(([v]) => v === proposal.archetype)?.[1] ?? proposal.archetype ?? "No suggestion"}{proposal.confidence !== undefined && <span className="font-normal text-ink-2">, confidence {String(proposal.confidence)}</span>}</dd>
        {proposal.signals?.length ? (<><dt className="text-ink-3">Signals found</dt><dd>{proposal.signals.slice(0, 6).join(", ")}</dd></>) : null}
      </dl>
      <div className="mt-5 flex flex-wrap items-end gap-3">
        <label className="text-sm font-semibold">
          Business type
          <select value={choice} onChange={(e) => setChoice(e.target.value)} className="mt-1.5 block min-h-11 rounded-[3px] border border-rule-strong bg-paper px-3 text-base font-normal">
            {options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <button type="button" onClick={confirm} disabled={busy} className="min-h-11 rounded-[3px] bg-signal px-5 text-base font-semibold text-white hover:bg-signal-deep disabled:opacity-70">
          {busy ? "Saving…" : "Confirm and continue"}
        </button>
        {error && <p role="alert" className="text-sm font-medium text-red">{error}</p>}
      </div>
    </section>
  );
}
