"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { AgentReportView } from "@/components/workspace/agent-report";
import { AgentIcon } from "@/components/workspace/icons";
import { PILLARS, PILLAR_ORDER } from "@/lib/pillars";
import type { AgentInfo, AgentReport, IssueCard, Pillar } from "@/lib/types";

/** Compact discipline picker and agent slider keep the full report width for evidence. */
export function AgentsLayer({ runId, reports, agents, issues, initial }: {
  runId: string;
  reports: Record<string, AgentReport>;
  agents: AgentInfo[];
  issues: IssueCard[] | null; // null: the issues endpoint was unavailable, so cards come from the report itself
  initial?: string;
}) {
  const ran = agents.filter((a) => reports[a.id]);
  const [selected, setSelected] = useState(initial && reports[initial] ? initial : ran[0]?.id);
  const [pillar, setPillar] = useState<Pillar>(ran.find((a) => a.id === selected)?.pillar ?? "seo");
  const pickerRef = useRef<HTMLElement>(null);
  const reduced = useReducedMotion();
  const own = ran.filter((a) => a.pillar === pillar);
  const current = own.findIndex((a) => a.id === selected);
  const info = ran.find((a) => a.id === selected);

  useEffect(() => {
    const chip = Array.from(pickerRef.current?.querySelectorAll<HTMLButtonElement>("button") ?? [])
      .find((button) => button.dataset.agent === selected);
    chip?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }, [selected, pillar]);

  function choose(id: string) {
    setSelected(id);
    window.history.replaceState(null, "", `/runs/${runId}?layer=agents&agent=${id}`);
  }

  if (!ran.length) return <p className="text-base text-ink-3">No agent saved a report in this run.</p>;

  return (
    <div>
      <div className="sticky top-[64px] z-20 border-y border-rule bg-paper/95 py-4 backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div role="group" aria-label="Agent discipline" className="flex gap-2">
            {PILLAR_ORDER.filter((p) => ran.some((a) => a.pillar === p)).map((p) => (
              <button key={p} type="button" aria-pressed={pillar === p} onClick={() => { setPillar(p); choose(ran.find((a) => a.pillar === p)!.id); }}
                      className={`min-h-11 rounded-[3px] px-4 text-sm font-semibold ${pillar === p ? "bg-ink text-white" : "border border-rule text-ink-2 hover:bg-mist"}`}>
                {PILLARS[p].short} <span className="opacity-70">{ran.filter((a) => a.pillar === p).length}</span>
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-ink-3">{current + 1} / {own.length}</span>
            <button type="button" disabled={current <= 0} onClick={() => choose(own[current - 1].id)} aria-label="Previous agent" className="flex h-11 w-11 items-center justify-center rounded-[3px] border border-rule hover:bg-mist disabled:opacity-30"><ChevronLeft size={18} /></button>
            <button type="button" disabled={current >= own.length - 1} onClick={() => choose(own[current + 1].id)} aria-label="Next agent" className="flex h-11 w-11 items-center justify-center rounded-[3px] border border-rule hover:bg-mist disabled:opacity-30"><ChevronRight size={18} /></button>
          </div>
        </div>
        <nav ref={pickerRef} aria-label="Agents in selected discipline" className="scrollbar-hidden mt-3 flex gap-2 overflow-x-auto pb-1">
          {own.map((agent) => {
            const active = agent.id === selected;
            return <button key={agent.id} data-agent={agent.id} type="button" onClick={() => choose(agent.id)} aria-current={active ? "true" : undefined}
                           className={`flex min-h-11 shrink-0 items-center gap-2 rounded-[3px] border px-3 text-sm ${active ? "border-signal bg-soft font-semibold text-ink" : "border-rule text-ink-2 hover:bg-mist"}`}>
              <AgentIcon id={agent.id} size={15} /><span className="font-mono text-xs text-signal">{agent.id}</span>{agent.name}
            </button>;
          })}
        </nav>
      </div>
      <AnimatePresence mode="wait" initial={false}>
        {selected && reports[selected] && <motion.div key={selected} id="agent-report" className="min-w-0 pt-10"
          initial={reduced ? false : { opacity: 0, x: 14 }} animate={{ opacity: 1, x: 0 }} exit={reduced ? undefined : { opacity: 0, x: -10 }}
          transition={{ duration: 0.18 }}>
          <AgentReportView report={reports[selected]} question={info?.question} issues={issues?.filter((i) => i.agent_id === selected)} />
          {info && !info.counts_toward_readiness && <p className="mt-8 border-l-[3px] border-amber bg-amber-bg px-4 py-3 text-sm text-ink">This observation agent reports a dated sample of search results or AI answers. It does not affect readiness scores.</p>}
        </motion.div>}
      </AnimatePresence>
    </div>
  );
}
