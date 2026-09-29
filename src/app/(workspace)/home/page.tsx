import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { AgentCard } from "@/components/workspace/agent-card";
import { CollectorExplorer } from "@/components/workspace/collector-explorer";
import { HomeHero } from "@/components/workspace/home-hero";
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
      <HomeHero agentCount={agents.length} counts={counts} />

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

      <CollectorExplorer collectors={tiles} agentNames={Object.fromEntries(agents.map((a) => [a.id, a.name]))} />

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
