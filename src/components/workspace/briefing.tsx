"use client";

import { useState } from "react";
import type { IntelligenceReport, Lane } from "@/lib/types";

type ItemBrief = { title: string; wave: Lane; agents: string[]; facts: string[] };

const LANE_WORD: Record<Lane, string> = { now: "Now", next: "Next", later: "Later", investigate: "Investigate", monitor: "Monitor" };

const LEADS = [
  { key: "blocker", label: "Fix first", note: "The costliest issue in the earliest lane" },
  { key: "opportunity", label: "Biggest opportunity", note: "The gap whose fix helps most" },
  { key: "observation", label: "Watch", note: "The most important dated observation" },
] as const;

/** The executive summary in two wordings over the same cited items, beside the three rule-chosen leads. */
export function Briefing({ summary, leads, items, causes, firstLane }: {
  summary: IntelligenceReport["executive_summary"];
  firstLane: Lane | null;
  leads: IntelligenceReport["leads"] | null;
  items: Record<string, ItemBrief>;
  causes: Record<string, string>;
}) {
  const [audience, setAudience] = useState<"internal" | "client">("internal");
  const sentences = summary[audience] ?? [];
  const model = summary.source && summary.source !== "deterministic" ? summary.source.split(":").pop() : null;

  return (
    <section aria-labelledby="briefing-heading" className="mt-14">
      <div>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h2 id="briefing-heading" className="font-display text-4xl font-semibold tracking-[-0.02em]">Executive summary</h2>
          <div role="radiogroup" aria-label="Wording" className="flex border border-rule-strong text-sm">
            {([["internal", "For the team"], ["client", "For the client"]] as const).map(([value, label]) => (
              <button key={value} type="button" role="radio" aria-checked={audience === value} onClick={() => setAudience(value)}
                      className={`min-h-10 px-3.5 font-medium transition-colors [&+&]:border-l [&+&]:border-rule-strong ${audience === value ? "bg-ink text-white" : "text-ink-2 hover:bg-mist"}`}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <ol className="mt-7 max-w-[850px] space-y-5">
          {sentences.map((sentence, index) => (
            <li key={index} className="grid grid-cols-[28px_1fr] gap-2">
              <span aria-hidden="true" className="pt-1 font-mono text-2xs text-ink-3">{String(index + 1).padStart(2, "0")}</span>
              <p className="text-lg leading-[1.6] text-ink">
                {sentence.text}
                {audience === "internal" && sentence.ids.filter((id) => id !== "READINESS").map((id) => (
                  <a key={id} href={`#${id}`} className="ml-1.5 inline-block rounded-[3px] bg-soft px-1.5 py-px align-[2px] font-mono text-2xs text-signal hover:bg-signal hover:text-white">
                    {id}
                  </a>
                ))}
              </p>
            </li>
          ))}
          {!sentences.length && <li className="text-base text-ink-3">No summary was written for this wording.</li>}
        </ol>
        <p className="mt-5 text-xs text-ink-3">
          {model
            ? `Worded by ${model} from items the rules chose. Sentences citing unknown items or unsupported numbers are dropped.`
            : "Written from the data by rule; no model wording was used."}
          {audience === "client" && " The client wording has no item codes and no jargon."}
        </p>
      </div>

      <aside aria-label="Leads" className="mt-8 grid gap-4 border-t-[3px] border-ink pt-4 md:grid-cols-3">
        {LEADS.map((lead) => {
          const id = leads?.[lead.key] ?? null;
          const item = id ? items[id] : undefined;
          const cause = id && !item ? causes[id] : undefined;
          return (
            <div key={lead.key} className="border border-rule bg-mist px-5 py-4">
              <p className="text-xs font-semibold text-ink-2">{lead.label}</p>
              {id ? (
                <a href={`#${id}`} className="group mt-1 block">
                  <span className="text-md leading-snug font-semibold group-hover:text-signal">{item?.title ?? cause ?? id}</span>
                  <span className="mt-1 block text-xs text-ink-3">
                    <span className="font-mono text-2xs text-signal">{id}</span>
                    {item && <> in {LANE_WORD[item.wave]}, found by {item.agents.join(", ")}</>}
                    {cause && " shared cause"}
                  </span>
                </a>
              ) : (
                <p className="mt-1 text-base text-ink-3">None in this run.</p>
              )}
              <p className="mt-1.5 text-xs text-ink-3">{lead.note}</p>
              {lead.key === "blocker" && item && firstLane && item.wave !== firstLane && (
                <p className="mt-2 border-l-2 border-amber bg-amber-bg px-2.5 py-1.5 text-xs text-ink">
                  This report predates the current rule, which leads with the {LANE_WORD[firstLane]} lane. The summary above
                  was written from the older choice.
                </p>
              )}
            </div>
          );
        })}
      </aside>
    </section>
  );
}
