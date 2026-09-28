import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AppWindow, Bot, ExternalLink, Sparkles } from "lucide-react";
import { AgentsLayer } from "@/components/workspace/agents-layer";
import { IntelligenceLayer } from "@/components/workspace/intelligence-layer";
import { LiveRun } from "@/components/workspace/live-run";
import { OutputLayer } from "@/components/workspace/output-layer";
import { RunStatusLabel, isFinished } from "@/components/workspace/run-status";
import { EngineError, engine, isRunId } from "@/lib/engine";
import { formatDate, formatDuration, plural } from "@/lib/format";
import { sameUrl } from "@/lib/microsite";
import type { IntelligenceReport, IssueCard, MicrositeSummary, Progress } from "@/lib/types";

const LAYERS = [
  { id: "intelligence", label: "Intelligence", hint: "The business summary across all agents", icon: Sparkles },
  { id: "agents", label: "Agents", hint: "What each agent checked, found and proposes", icon: Bot },
  { id: "output", label: "Output", hint: "The fixed page and its code changes", icon: AppWindow },
] as const;
type LayerId = (typeof LAYERS)[number]["id"] | "log";

const ARCHETYPE_LABEL: Record<string, string> = {
  hospitality: "Hotels and resorts", loans: "Loans and lending", retail: "Retail", logistics: "Logistics",
};

async function load(runId: string): Promise<Progress> {
  if (!isRunId(runId)) notFound();
  try {
    return await engine.progress(runId);
  } catch (error) {
    if (error instanceof EngineError && error.status === 404) notFound();
    throw error;
  }
}

export async function generateMetadata({ params }: PageProps<"/runs/[runId]">): Promise<Metadata> {
  const { runId } = await params;
  if (!isRunId(runId)) return { title: "Run" };
  try {
    return { title: `${(await engine.progress(runId)).run.client.name} run` };
  } catch {
    return { title: "Run" };
  }
}

export default async function RunPage({ params, searchParams }: PageProps<"/runs/[runId]">) {
  const [{ runId }, query] = await Promise.all([params, searchParams]);
  const progress = await load(runId);
  const { run } = progress;
  const finished = isFinished(progress.status);
  const agentCount = run.agents.length;

  const report = finished && agentCount >= 2 ? await engine.report(runId) : null;
  const requested = typeof query.layer === "string" ? query.layer : "";
  const layer: LayerId = requested === "log" || LAYERS.some((l) => l.id === requested) ? (requested as LayerId)
    : report ? "intelligence" : "agents";

  return (
    <div className="mx-auto max-w-[1200px] px-5 pt-12 pb-28 sm:px-8">
      <nav aria-label="Breadcrumb" className="text-sm text-ink-3">
        <Link href="/sessions" className="hover:text-ink hover:underline">Sessions</Link>
        <span className="mx-2" aria-hidden="true">/</span>
        <span className="text-ink-2">{run.client.name}</span>
      </nav>

      <header className="mt-5 border-b border-rule pb-8">
        <div className="min-w-0">
          <h1 className="max-w-[900px] font-display text-5xl leading-tight font-semibold tracking-[-0.03em] sm:text-6xl">{run.client.name}</h1>
          <a href={run.client.primary_url} target="_blank" rel="noreferrer noopener"
             className="mt-2 inline-flex max-w-full items-center gap-1.5 font-mono text-xs break-all text-signal hover:underline">
            {run.client.primary_url} <ExternalLink aria-hidden="true" size={13} className="shrink-0" />
          </a>
        </div>
        <dl className="mt-7 grid grid-cols-2 gap-x-8 gap-y-3 border-t border-rule pt-5 text-sm sm:flex sm:flex-wrap sm:gap-x-14">
          <div><dt className="text-ink-3">Status</dt><dd className="mt-0.5"><RunStatusLabel status={progress.status} /></dd></div>
          <div><dt className="text-ink-3">Started</dt><dd className="mt-0.5 font-medium">{formatDate(run.started_at ?? run.created_at)}</dd></div>
          <div><dt className="text-ink-3">{finished ? "Took" : "Running for"}</dt><dd className="mt-0.5 font-mono text-xs font-medium">{formatDuration(run.started_at ?? run.created_at, run.finished_at)}</dd></div>
          <div><dt className="text-ink-3">Agents</dt><dd className="mt-0.5 font-medium">{run.type === "full" ? `All ${agentCount}` : plural(agentCount, "agent")}</dd></div>
          <div><dt className="text-ink-3">Business type</dt><dd className="mt-0.5 font-medium">{run.client.archetype ? ARCHETYPE_LABEL[run.client.archetype] ?? run.client.archetype : "Detecting"}</dd></div>
          <div><dt className="text-ink-3">Pages sampled</dt><dd className="mt-0.5 font-medium">Up to {run.crawl_cap}</dd></div>
          {finished && (
            <div className="sm:ml-auto sm:self-end">
              <Link href={`/runs/${runId}?layer=log`} scroll={false} className="text-sm font-medium text-signal hover:underline">
                {layer === "log" ? "Viewing the run log" : "View the run log"}
              </Link>
            </div>
          )}
        </dl>
      </header>

      {!finished ? (
        <LiveRun runId={runId} initial={progress} />
      ) : (
        <>
          <nav aria-label="Result layers" className="mt-10 grid grid-cols-3 gap-1.5 rounded-[8px] border border-rule bg-canvas p-1.5 shadow-[inset_0_1px_3px_rgba(3,22,13,0.05)]">
            {LAYERS.map((item) => {
              const active = item.id === layer;
              const Icon = item.icon;
              return (
                <Link key={item.id} href={`/runs/${runId}?layer=${item.id}`} aria-current={active ? "page" : undefined} scroll={false}
                      className={`group flex min-h-16 items-center gap-3.5 rounded-[5px] px-4 py-3 transition-[background-color,box-shadow,color] duration-200 sm:px-5 ${active
                        ? "bg-linear-to-b from-signal to-signal-deep text-white shadow-[0_12px_24px_-14px_rgba(0,103,58,0.9),inset_0_1px_0_rgba(255,255,255,0.16)]"
                        : "bg-paper text-ink shadow-[0_1px_2px_rgba(3,22,13,0.07)] hover:shadow-[0_8px_20px_-12px_rgba(3,22,13,0.28)]"}`}>
                  <span aria-hidden="true" className={`hidden h-9 w-9 shrink-0 items-center justify-center rounded-[5px] transition-colors sm:flex ${active ? "bg-white/15 text-white" : "bg-soft text-signal group-hover:bg-[#d3eedd]"}`}>
                    <Icon size={17} strokeWidth={2.1} />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-base font-semibold">{item.label}</span>
                    <span className={`hidden text-xs sm:block ${active ? "text-white/80" : "text-ink-3"}`}>{item.hint}</span>
                  </span>
                </Link>
              );
            })}
          </nav>

          <div className="mt-12">
            {layer === "intelligence" && (report ? (
              <IntelligenceSection runId={runId} report={report} />
            ) : (
              <div className="border border-rule bg-mist px-6 py-10">
                <h2 className="font-display text-2xl font-semibold tracking-tight">No intelligence report for this run</h2>
                <p className="mt-2 max-w-[620px] text-base leading-relaxed text-ink-2">
                  {agentCount < 2
                    ? "This run had one agent. The intelligence layer merges findings across two or more agents, so read this agent's report directly."
                    : "The agents finished but the intelligence report wasn't saved. The agent reports are still complete."}
                </p>
                <Link href={`/runs/${runId}?layer=agents`} className="mt-5 inline-flex min-h-11 items-center rounded-[3px] bg-signal px-5 text-base font-semibold text-white hover:bg-signal-deep">
                  Open agent reports
                </Link>
              </div>
            ))}
            {layer === "agents" && <AgentsSection runId={runId} selected={typeof query.agent === "string" ? query.agent : undefined} />}
            {layer === "output" && <OutputSection runId={runId} client={run.client} />}
            {layer === "log" && <LiveRun runId={runId} initial={progress} live={false} />}
          </div>
        </>
      )}
    </div>
  );
}

async function IntelligenceSection({ runId, report }: { runId: string; report: IntelligenceReport }) {
  const agents = await engine.agents();
  return <IntelligenceLayer runId={runId} report={report} agentNames={Object.fromEntries(agents.map((a) => [a.id, a.name]))} />;
}

/** Optional data: if it can't load, the layer still renders from what it has instead of failing the page. */
async function settle<T>(promise: Promise<T>, fallback: T): Promise<T> {
  try {
    return await promise;
  } catch (error) {
    console.error("optional engine data unavailable:", error instanceof Error ? error.message : error);
    return fallback;
  }
}

async function AgentsSection({ runId, selected }: { runId: string; selected?: string }) {
  const [reports, agents, issues] = await Promise.all([
    engine.agentReports(runId), engine.agents(), settle<IssueCard[] | null>(engine.issues(runId), null),
  ]);
  return <AgentsLayer runId={runId} reports={reports} agents={agents} issues={issues} initial={selected} />;
}

async function OutputSection({ runId, client }: { runId: string; client: Progress["run"]["client"] }) {
  const [preview, issues, microsites] = await Promise.all([
    engine.preview(runId), settle<IssueCard[]>(engine.issues(runId), []), settle<MicrositeSummary[]>(engine.microsites(), []),
  ]);
  const live = microsites.find((m) => !m.superseded_at && !m.unpublished_at && sameUrl(m.source_url, client.primary_url)) ?? null;
  // Remount when the server hands over freshly signed links.
  return <OutputLayer key={preview?.links_expire_at ?? "none"} runId={runId} initial={preview} issues={issues}
                      entryUrl={client.primary_url} archetype={client.archetype} clientName={client.name} live={live} />;
}
