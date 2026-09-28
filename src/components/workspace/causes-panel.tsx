"use client";

import { ArrowRight } from "lucide-react";
import { useState } from "react";
import { plural } from "@/lib/format";
import type { IntelligenceReport, Lane } from "@/lib/types";

type Cause = IntelligenceReport["root_causes_and_patterns"][number];
const LANE_WORD: Record<Lane, string> = { now: "Now", next: "Next", later: "Later", investigate: "Investigate", monitor: "Monitor" };

/** Shared causes as compact tiles; the chosen cause opens below with the items it groups and the one fix to try. */
export function CausesPanel({ causes, items }: { causes: Cause[]; items: Record<string, { title: string; wave: Lane }> }) {
  const [selected, setSelected] = useState(causes[0]?.id);
  const [all, setAll] = useState(false);
  const cause = causes.find((c) => c.id === selected) ?? causes[0];
  if (!cause) return null;
  // Causes arrive largest first; the first six fill two full rows, the rest wait behind one control.
  const shown = all ? causes : causes.slice(0, 6);

  return (
    <div>
      <div role="tablist" aria-label="Shared causes" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {shown.map((c) => {
          const active = c.id === cause.id;
          return (
            <button key={c.id} id={c.id} type="button" role="tab" aria-selected={active} onClick={() => setSelected(c.id)}
                    className={`flex items-start justify-between gap-4 border px-5 py-4 text-left transition-colors ${active ? "border-signal/50 bg-soft" : "border-rule bg-paper hover:border-rule-strong hover:bg-mist"}`}>
              <span>
                <span className="block text-base leading-snug font-semibold">{c.title}</span>
                <span className="mt-1 block text-xs text-ink-3">{c.pages ? `Across ${plural(c.pages, "page")}` : "Site-wide"}</span>
              </span>
              <span className={`shrink-0 font-display text-2xl font-semibold ${active ? "text-signal" : "text-ink-3"}`} aria-label={plural(c.items.length, "item")}>
                {c.items.length}
              </span>
            </button>
          );
        })}
      </div>
      {causes.length > 6 && (
        <button type="button" onClick={() => setAll((v) => !v)} aria-expanded={all}
                className="mt-3 min-h-9 text-sm font-medium text-signal hover:underline">
          {all ? "Show the six largest" : `Show ${causes.length - 6} smaller causes`}
        </button>
      )}

      <div role="tabpanel" aria-label={cause.title} className="mt-5 grid gap-7 border border-rule bg-paper p-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,.8fr)] lg:p-7">
        <div>
          <p className="text-2xs font-semibold text-ink-3">{cause.id}, found by {cause.agents.join(", ")}</p>
          <h3 className="mt-2 font-display text-2xl leading-snug font-semibold tracking-tight">{cause.title}</h3>
          <p className="mt-2 text-sm text-ink-2">
            {plural(cause.items.length, "item")} {cause.pages ? `on ${plural(cause.pages, "page")}` : "across the site"} may share this cause.
          </p>
          <ul className="mt-5 space-y-2">
            {cause.items.map((id) => (
              <li key={id}>
                <a href={`#${id}`} className="flex items-baseline gap-3 border border-rule px-4 py-3 transition-colors hover:border-signal/50 hover:bg-soft/40">
                  <span className="font-mono text-2xs text-signal">{id}</span>
                  <span className="flex-1 text-sm leading-snug">{items[id]?.title ?? id}</span>
                  {items[id] && <span className="shrink-0 text-2xs text-ink-3">{LANE_WORD[items[id].wave]}</span>}
                </a>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex flex-col">
          <p className="flex items-center gap-2 text-2xs font-semibold text-signal"><ArrowRight aria-hidden="true" size={13} /> One change to try first</p>
          <p className="mt-3 border-l-[3px] border-signal bg-soft/50 px-5 py-4 text-md leading-relaxed">{cause.fix}</p>
          <p className="mt-4 text-xs leading-relaxed text-ink-3">
            Check whether this one change clears the grouped items before fixing each on its own. The grouping is a pattern
            across agents, not a verified cause.
          </p>
        </div>
      </div>
    </div>
  );
}
