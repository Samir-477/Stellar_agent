import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { AgentCard } from "@/components/workspace/agent-card";
import { FocusMap } from "@/components/workspace/focus-map";
import { SOURCE_ICONS } from "@/components/workspace/icons";
import { RunStatusLabel } from "@/components/workspace/run-status";
import { engine } from "@/lib/engine";
import { formatDate, urlPath } from "@/lib/format";
import { PILLARS, PILLAR_ORDER } from "@/lib/pillars";
import type { Pillar } from "@/lib/types";

export const metadata: Metadata = {
  title: "Home",
  description: "What the Stellar Agents collectors and SEO, AEO and GEO agents examine, and what each run produces.",
};

const container = "mx-auto max-w-[1200px] px-5 sm:px-8";

const STEPS = [
  { title: "Collect evidence", text: "Collectors capture the site, dated search results, AI answers and the wider web. Only the ones your agents need run.", see: "Live progress" },
  { title: "Diagnose", text: "Each agent reads that evidence on its own and rates its checks. No agent reads another agent's output.", see: "Agents tab" },
  { title: "Synthesize", text: "The intelligence layer merges the findings into readiness scores and one priority list, and names shared causes.", see: "Intelligence tab" },
  { title: "Preview fixes", text: "The output layer applies the proposed changes to the captured pages, so you can see each fix in place.", see: "Output tab" },
];

function SectionIntro({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_1.15fr] lg:items-end">
      <h2 id={id} className="font-display text-5xl leading-[1.1] font-semibold tracking-[-0.03em]">{title}</h2>
      <p className="max-w-[560px] text-md leading-relaxed text-ink-2">{children}</p>
    </div>
  );
}

export default async function HomePage() {
  const [agents, collectors, runs] = await Promise.all([engine.agents(), engine.collectors(), engine.runs(3)]);
  const latest = runs[0];
  const collectorNames = Object.fromEntries(collectors.map((c) => [c.id, c.name]));
  // Show collectors grouped by source (site, search, AI, web), then by number, rather than in run order.
  const groupOrder = ["site", "search", "ai", "web"];
  const tiles = [...collectors].sort((a, b) => groupOrder.indexOf(a.group) - groupOrder.indexOf(b.group)
    || Number(a.id.slice(1)) - Number(b.id.slice(1)));
  const counts = Object.fromEntries(PILLAR_ORDER.map((p) => {
    const own = agents.filter((a) => a.pillar === p);
    return [p, { agents: own.length, checks: own.reduce((sum, a) => sum + a.checks.length, 0) }];
  })) as Record<Pillar, { agents: number; checks: number }>;

  return (
    <>
      {/* Home opens with a real choice: run one discipline or all three, or reopen the latest run. */}
      <section className="relative overflow-hidden border-b border-rule bg-canvas" aria-labelledby="home-title">
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_1px_1px,rgba(0,123,70,0.13)_1px,transparent_0)] bg-size-[24px_24px] mask-[radial-gradient(ellipse_at_30%_45%,black_20%,transparent_72%)]" />
        <div aria-hidden="true" className="pointer-events-none absolute -top-48 right-[-12%] h-[720px] w-[720px] rounded-full bg-[radial-gradient(closest-side,rgba(95,214,154,0.22),transparent)]" />
        <div className={`${container} relative grid min-h-[calc(100svh-134px)] gap-12 py-16 lg:min-h-[calc(100svh-72px)] lg:grid-cols-[minmax(0,1fr)_minmax(0,.95fr)] lg:items-center lg:gap-16 lg:py-20`}>
          <div>
            <p className="text-sm font-semibold text-signal">Stellar Agents workspace</p>
            <h1 id="home-title" className="mt-5 max-w-[640px] font-display text-6xl leading-[1.08] font-semibold tracking-[-0.035em] sm:text-7xl">
              Know what your site shows to search and AI.
            </h1>
            <p className="mt-7 max-w-[570px] text-lg leading-[1.7] text-ink-2">
              Capture the evidence, let independent agents examine it, then review a prioritised diagnosis and a preview of proposed fixes.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <Link href="/runs/new" className="inline-flex min-h-12 items-center gap-2.5 rounded-[4px] bg-linear-to-b from-signal to-signal-deep px-6 text-base font-semibold text-white shadow-[0_12px_24px_-12px_rgba(0,103,58,0.85),inset_0_1px_0_rgba(255,255,255,0.16)] transition-[filter] hover:brightness-110">
                Run all {agents.length} agents <ArrowRight aria-hidden="true" size={16} />
              </Link>
              <Link href="/sessions" className="inline-flex min-h-12 items-center rounded-[4px] border border-rule-strong bg-paper px-5 text-base font-medium text-ink shadow-[0_1px_2px_rgba(3,22,13,0.06)] transition-colors hover:border-ink-3">
                View sessions
              </Link>
            </div>
            {latest && (
              <Link href={`/runs/${latest.id}`} className="group mt-10 block max-w-[560px] rounded-[8px] border border-rule bg-paper/90 px-5 py-4 shadow-[0_18px_40px_-28px_rgba(3,22,13,0.45)] backdrop-blur transition-[border-color,box-shadow] hover:border-rule-strong hover:shadow-[0_22px_44px_-26px_rgba(3,22,13,0.5)]">
                <span className="flex items-center justify-between gap-4 text-2xs text-ink-3">
                  <span>Latest run, {formatDate(latest.created_at)}</span>
                  <RunStatusLabel status={latest.status} />
                </span>
                <span className="mt-2 flex items-end justify-between gap-6">
                  <span className="min-w-0">
                    <span className="block truncate text-md font-semibold">{latest.client_name}</span>
                    <span className="block truncate font-mono text-2xs text-ink-3">{urlPath(latest.primary_url)}</span>
                  </span>
                  {latest.readiness && (
                    <span className="flex shrink-0 gap-4">
                      {PILLAR_ORDER.filter((p) => latest.readiness?.[p]).map((p) => (
                        <span key={p} className="text-right">
                          <span className="block text-2xs text-ink-3">{PILLARS[p].short}</span>
                          <span className="block font-display text-xl leading-tight font-semibold">{latest.readiness![p].score ?? "–"}</span>
                        </span>
                      ))}
                      <ArrowRight aria-hidden="true" size={16} className="self-center text-signal transition-transform group-hover:translate-x-1" />
                    </span>
                  )}
                </span>
              </Link>
            )}
            <p className="mt-6 max-w-[520px] text-sm leading-relaxed text-ink-3">
              Search results and AI answers are sampled in India and dated. Every finding points back to its source.
            </p>
          </div>
          <FocusMap options={PILLAR_ORDER.map((pillar) => ({
            id: pillar, short: PILLARS[pillar].short, name: PILLARS[pillar].name, outcome: PILLARS[pillar].outcome,
            agentIds: agents.filter((agent) => agent.pillar === pillar).map((agent) => agent.id), checks: counts[pillar].checks,
          }))} />
        </div>
      </section>

      {/* Each stage moves the same evidence toward a reviewable change. */}
      <section className="bg-forest text-white" aria-labelledby="run-steps">
        <div className={`${container} py-20 lg:py-24`}>
          <div className="grid gap-5 lg:grid-cols-[1fr_.75fr] lg:items-end lg:gap-20">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-mint">The run, from source to change</p>
              <h2 id="run-steps" className="mt-4 max-w-[690px] font-display text-5xl leading-[1.12] font-semibold tracking-[-0.03em]">
                From one page to a plan you can inspect.
              </h2>
            </div>
            <p className="max-w-[440px] text-md leading-relaxed text-white/70">
              Four stages connect captured evidence to an agent finding, a priority, and a proposed change. Follow each step as the run progresses.
            </p>
          </div>
          <ol className="mt-12 grid gap-4 md:grid-cols-2 lg:mt-16 lg:grid-cols-4 lg:gap-3">
            {STEPS.map((step, index) => (
              <li key={step.title} className="relative flex min-w-0 flex-col border border-white/20 bg-white/[0.06] p-6 lg:min-h-[310px] lg:p-7">
                <div className="flex items-center justify-between gap-3">
                  <span className="flex size-10 items-center justify-center rounded-full border border-mint/60 font-mono text-sm font-semibold text-mint">0{index + 1}</span>
                  {index < STEPS.length - 1 && <ArrowRight aria-hidden="true" size={20} className="text-mint/80" />}
                </div>
                <h3 className="mt-10 font-display text-2xl font-semibold tracking-tight">{step.title}</h3>
                <p className="mt-3 flex-1 text-sm leading-[1.7] text-white/70">{step.text}</p>
                <p className="mt-7 border-t border-white/20 pt-4 text-xs font-medium text-mint">See it in {step.see}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Collectors: twelve equal tiles, grouped in order by where the evidence comes from. */}
      <section className={`${container} py-24`} aria-labelledby="collectors">
        <SectionIntro id="collectors" title={`${collectors.length} evidence collectors`}>
          Agents never read each other&apos;s results. They read this evidence, captured for the run, so every finding
          can be traced to a page, a search result or an AI answer.
        </SectionIntro>
        <ul className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {tiles.map((c) => {
            const Icon = SOURCE_ICONS[c.group];
            return (
              <li key={c.id} className="flex flex-col border border-rule bg-paper p-6 transition-colors hover:border-rule-strong">
                <div className="flex items-center justify-between gap-3">
                  <span className="flex items-center gap-2 text-2xs font-medium text-ink-3">
                    <span className="flex h-7 w-7 items-center justify-center rounded-[4px] bg-soft text-signal">
                      {Icon && <Icon aria-hidden="true" size={14} strokeWidth={1.8} />}
                    </span>
                    {c.group_label}
                  </span>
                  <span className="font-mono text-2xs text-signal">{c.id}</span>
                </div>
                <h3 className="mt-5 font-display text-xl font-semibold tracking-tight">{c.name}</h3>
                <p className="mt-2 flex-1 text-sm leading-relaxed text-ink-2">{c.captures}</p>
                <div className="mt-6 flex items-center justify-between gap-3 border-t border-rule pt-3.5 text-2xs text-ink-3">
                  <span className="truncate" title={c.services.join(", ")}>{c.services.length ? c.services.join(", ") : "No external service"}</span>
                  <span className="shrink-0">Read by {c.used_by.length}</span>
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      {/* Agents: one band per discipline; hover a card for how it works and an example. */}
      <section className="border-t border-rule bg-canvas" aria-labelledby="agents">
        <div className={`${container} py-24`}>
          <SectionIntro id="agents" title={`${agents.length} diagnosis agents`}>
            Each agent answers one question with its own checks. Hover an agent to see how it works and an example of
            what it finds. Observation agents report dated samples and don&apos;t change readiness scores.
          </SectionIntro>

          <div className="mt-16 space-y-20">
            {PILLAR_ORDER.map((pillar) => {
              const own = agents.filter((a) => a.pillar === pillar);
              return (
                <div key={pillar} className="grid gap-8 lg:grid-cols-[240px_1fr] lg:gap-14">
                  <div className="lg:sticky lg:top-24 lg:self-start">
                    <p className="font-display text-6xl leading-none font-semibold tracking-[-0.04em] text-signal">{PILLARS[pillar].short}</p>
                    <h3 className="mt-4 font-display text-xl font-semibold tracking-tight">{PILLARS[pillar].name}</h3>
                    <p className="mt-3 text-base leading-relaxed text-ink-2">{PILLARS[pillar].definition}</p>
                    <p className="mt-5 border-t border-rule-strong pt-4 text-sm leading-relaxed text-ink-2">
                      <span className="font-semibold text-ink">{own.length} agents, {counts[pillar].checks} checks.</span> {PILLARS[pillar].outcome}
                    </p>
                  </div>
                  <ul className="grid gap-5 md:grid-cols-2">
                    {own.map((agent) => <AgentCard key={agent.id} agent={agent} collectorNames={collectorNames} />)}
                  </ul>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {runs.length > 0 && (
        <section className={`${container} py-20`} aria-labelledby="recent">
          <div className="flex items-end justify-between gap-4">
            <h2 id="recent" className="font-display text-3xl font-semibold tracking-[-0.02em]">Pick up where you left off</h2>
            <Link href="/sessions" className="text-base font-medium text-signal hover:underline">All sessions</Link>
          </div>
          <ul className="mt-7 border-t border-rule">
            {runs.map((run) => (
              <li key={run.id}>
                <Link href={`/runs/${run.id}`} className="grid gap-1 border-b border-rule py-5 transition-colors hover:bg-mist sm:grid-cols-[1.4fr_1fr_auto] sm:items-center sm:gap-8 sm:px-3">
                  <span>
                    <span className="block text-md font-semibold">{run.client_name}</span>
                    <span className="block truncate font-mono text-2xs text-ink-3">{urlPath(run.primary_url)}</span>
                  </span>
                  <span className="text-sm text-ink-2">
                    {run.type === "full" ? "All agents" : `${run.agents.length} agents`}, {formatDate(run.created_at)}
                  </span>
                  <RunStatusLabel status={run.status} />
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
