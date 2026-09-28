import Link from "next/link";
import { ArrowRight, Check, ChevronRight, Radar } from "lucide-react";
import { PILLARS, PILLAR_ORDER } from "@/lib/pillars";
import type { ClientPriority, IntelligenceReport, Lane, Pillar, WorkItem } from "@/lib/types";

// The Intelligence layer is the client's summary: what the site's state is, the few fixes that
// matter most, what already works and what AI says. The technical detail lives in Agents.

const PLAIN_NAME: Record<Pillar, { name: string; meaning: string }> = {
  seo: { name: "Found on Google", meaning: "Can search engines reach, understand and rank your pages?" },
  aeo: { name: "Answers customers' questions", meaning: "Does the site answer what people ask, in a form Google can quote?" },
  geo: { name: "Understood by AI assistants", meaning: "Can AI assistants read, trust and repeat your facts correctly?" },
};

const BANDS = [
  { from: 0, to: 50, label: "Poor", tone: "bg-red-bg" },
  { from: 50, to: 70, label: "Needs work", tone: "bg-amber-bg" },
  { from: 70, to: 85, label: "Solid", tone: "bg-soft" },
  { from: 85, to: 100, label: "Strong", tone: "bg-[#c8ecd6]" },
];

const EFFORT: Record<string, string> = { S: "Quick fix", M: "Moderate", L: "Larger project" };

function bandName(band: string): string {
  return { "blocked or poor": "Poor", "needs work": "Needs work", solid: "Solid", strong: "Strong", "not measured": "Not measured" }[band] ?? band;
}

/** Reports built before the client cards existed: the same five picks, in the agents' own words. */
function legacyCards(report: IntelligenceReport): ClientPriority[] {
  const fixes = (["now", "next", "later"] as Lane[]).flatMap((l) => report.what_to_fix_first[l] ?? []);
  const lead = [report.leads?.blocker, report.leads?.opportunity];
  const ordered = [...fixes.filter((i) => lead.includes(i.id)), ...fixes.filter((i) => !lead.includes(i.id))].slice(0, 5);
  return ordered.map((i: WorkItem): ClientPriority => ({
    id: i.id, headline: i.title, why: "", action: i.action, source: "rules", severity: i.severity, effort: i.effort,
    pages: i.pages.length, agents: i.agents, check_ids: i.check_ids, wave: i.wave,
  }));
}

export function IntelligenceLayer({ runId, report, agentNames }: {
  runId: string; report: IntelligenceReport; agentNames: Record<string, string>;
}) {
  const summary = report.executive_summary.client ?? [];
  const cards = report.executive_summary.client_priorities?.length ? report.executive_summary.client_priorities : legacyCards(report);
  const strengths = report.whats_working.slice(0, 5);
  const observations = (report.what_to_fix_first.monitor ?? []).slice(0, 4);
  const unchecked = report.what_needs_attention.filter((a) => a.kind === "unverifiable");

  return (
    <div className="space-y-20">
      <section aria-labelledby="glance-heading">
        <h2 id="glance-heading" className="text-sm font-semibold text-signal">At a glance</h2>
        <div className="mt-4 max-w-[880px] space-y-3">
          {summary.length ? summary.map((s, i) => (
            <p key={i} className={i === 0 ? "font-display text-3xl leading-[1.3] font-medium tracking-[-0.015em]" : "text-lg leading-relaxed text-ink-2"}>{s.text}</p>
          )) : <p className="text-lg text-ink-2">No summary was written for this run.</p>}
        </div>
        <div className="mt-8 grid gap-3 md:grid-cols-3">
          {PILLAR_ORDER.filter((p) => report.readiness[p]).map((pillar) => {
            const r = report.readiness[pillar];
            return (
              <div key={pillar} className="flex flex-col border border-rule bg-paper px-6 py-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-base font-semibold">{PLAIN_NAME[pillar].name}</p>
                    <p className="mt-0.5 text-xs text-ink-3">{PILLARS[pillar].short}: {PLAIN_NAME[pillar].meaning}</p>
                  </div>
                  <p className="shrink-0 text-right">
                    <span className="font-display text-5xl leading-none font-semibold tracking-[-0.03em]">{r.score ?? "–"}</span>
                    <span className="ml-1 font-mono text-2xs text-ink-3">/100</span>
                  </p>
                </div>
                <div className="mt-auto pt-5">
                  <div className="relative" aria-hidden="true">
                    <div className="flex h-1.5 overflow-hidden rounded-[1px]">
                      {BANDS.map((b) => <span key={b.label} className={b.tone} style={{ width: `${b.to - b.from}%` }} />)}
                    </div>
                    {r.score !== null && <span className="absolute -top-1 h-3.5 w-[3px] -translate-x-1/2 rounded-full bg-ink" style={{ left: `${r.score}%` }} />}
                  </div>
                  <p className="mt-2 flex justify-between text-2xs text-ink-3">
                    <span className="font-semibold text-ink">{bandName(r.band)}</span>
                    <span>Based on {r.coverage}% of the checks</span>
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section aria-labelledby="fixes-heading">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 id="fixes-heading" className="font-display text-4xl font-semibold tracking-[-0.02em]">The {cards.length} things to fix first</h2>
            <p className="mt-2 max-w-[640px] text-base text-ink-2">In order of what it costs the business. Each one links to the agent&apos;s evidence and the exact change.</p>
          </div>
        </div>
        <ol className="mt-8 border-t border-rule">
          {cards.map((card, index) => (
            <li key={card.id} className="grid gap-5 border-b border-rule py-7 md:grid-cols-[56px_minmax(0,1.3fr)_minmax(0,1fr)] md:gap-8">
              <span className="font-display text-4xl leading-none font-semibold text-signal">{index + 1}</span>
              <div>
                <h3 className="font-display text-2xl leading-snug font-semibold tracking-[-0.01em]">{card.headline}</h3>
                {card.why && <p className="mt-2 text-base leading-relaxed text-ink-2">{card.why}</p>}
                <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
                  {card.effort && <span className="font-semibold text-ink-2">{EFFORT[card.effort] ?? card.effort}</span>}
                  <span>{card.pages ? `${card.pages} page${card.pages === 1 ? "" : "s"}` : "Site-wide"}</span>
                  <span>Found by {card.agents.map((a) => agentNames[a] ?? a).join(", ")}</span>
                </p>
              </div>
              <div className="border-l-[3px] border-signal bg-soft/50 px-5 py-4">
                <p className="text-2xs font-semibold text-signal">What we&apos;ll do</p>
                <p className="mt-1.5 text-base leading-relaxed text-ink">{card.action}</p>
                <Link href={`/runs/${runId}?layer=agents&agent=${card.agents[0]}`} className="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-signal hover:underline">
                  See the evidence and code <ArrowRight aria-hidden="true" size={14} />
                </Link>
              </div>
            </li>
          ))}
          {!cards.length && <li className="py-8 text-base text-ink-2">The agents found nothing to fix in this run.</li>}
        </ol>
      </section>

      <section className="grid gap-12 lg:grid-cols-2">
        <div>
          <h2 className="font-display text-3xl font-semibold tracking-[-0.02em]">What&apos;s already working</h2>
          <p className="mt-2 text-base text-ink-2">Keep these intact while the fixes go in.</p>
          <ul className="mt-6 space-y-3">
            {strengths.map((s) => (
              <li key={s.id} className="flex gap-3 text-base leading-snug">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-soft text-signal"><Check aria-hidden="true" size={12} strokeWidth={3} /></span>
                {s.title}
              </li>
            ))}
            {!strengths.length && <li className="text-base text-ink-3">No high-impact passes in this run.</li>}
          </ul>
        </div>
        <div>
          <h2 className="font-display text-3xl font-semibold tracking-[-0.02em]">What AI assistants say about you</h2>
          <p className="mt-2 text-base text-ink-2">From the searches and AI answers we sampled on the day of the run. These change over time.</p>
          <ul className="mt-6 space-y-3">
            {observations.map((o) => (
              <li key={o.id} className="flex gap-3 text-base leading-snug">
                <Radar aria-hidden="true" size={18} className="mt-0.5 shrink-0 text-ink-3" />
                {o.title}
              </li>
            ))}
            {!observations.length && <li className="text-base text-ink-3">No AI answers were sampled in this run.</li>}
          </ul>
        </div>
      </section>

      {unchecked.length > 0 && (
        <details className="group border border-rule bg-mist [&_summary::-webkit-details-marker]:hidden">
          <summary className="flex cursor-pointer items-center gap-3 px-6 py-5">
            <ChevronRight aria-hidden="true" size={16} className="text-ink-3 transition-transform group-open:rotate-90" />
            <span className="text-base font-semibold">What we couldn&apos;t check</span>
            <span className="text-sm text-ink-3">{unchecked.length} checks had too little evidence in this run</span>
          </summary>
          <ul className="grid gap-x-10 gap-y-2 px-6 pb-6 pl-14 text-sm text-ink-2 md:grid-cols-2">
            {unchecked.map((a) => <li key={a.id}>{a.title}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}
