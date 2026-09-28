"use client";

import { useMemo, useState } from "react";
import { Pager, usePaged } from "@/components/workspace/pager";
import { CheckLabel } from "@/components/workspace/status";

type Row = { id: string; check_id: string; agent: string; title: string };

const TABS = [
  { id: "working", label: "What's working", note: "High-impact checks that passed. Keep them intact while fixing the rest." },
  { id: "unchecked", label: "Couldn't be checked", note: "Checks without enough evidence in this run. Absence here is not a pass." },
] as const;

/** Passed and unchecked checks in one paged table, filterable by agent. */
export function CheckOutcomes({ working, unchecked }: { working: Row[]; unchecked: Row[] }) {
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>(working.length ? "working" : "unchecked");
  const [agent, setAgent] = useState("all");
  const source = tab === "working" ? working : unchecked;
  const agents = useMemo(() => Array.from(new Set(source.map((r) => r.agent))).sort(), [source]);
  const rows = useMemo(() => source.filter((r) => agent === "all" || r.agent === agent), [source, agent]);
  const paged = usePaged(rows, 8);
  const current = TABS.find((t) => t.id === tab)!;

  return (
    <div className="border border-rule">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-rule px-6 pt-4">
        <div role="tablist" aria-label="Check outcomes" className="flex gap-6">
          {TABS.map((t) => {
            const count = t.id === "working" ? working.length : unchecked.length;
            const active = t.id === tab;
            return (
              <button key={t.id} role="tab" type="button" aria-selected={active}
                      onClick={() => { setTab(t.id); setAgent("all"); paged.setPage(0); }}
                      className={`-mb-px border-b-2 pb-3.5 text-base font-semibold transition-colors ${active ? "border-signal text-ink" : "border-transparent text-ink-3 hover:text-ink"}`}>
                {t.label} <span className="ml-1 font-mono text-2xs font-normal text-ink-3">{count}</span>
              </button>
            );
          })}
        </div>
        <label className="mb-3 flex items-center gap-2 text-xs text-ink-3">
          Agent
          <select value={agent} onChange={(e) => { setAgent(e.target.value); paged.setPage(0); }}
                  className="min-h-9 rounded-[3px] border border-rule-strong bg-paper px-2.5 text-sm text-ink">
            <option value="all">All agents</option>
            {agents.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>
      </div>
      <p className="px-6 pt-4 text-sm text-ink-2">{current.note}</p>
      <div className="px-6 pt-3">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="text-2xs text-ink-3">
              <th scope="col" className="w-[150px] py-2.5 font-medium">Status</th>
              <th scope="col" className="w-[90px] py-2.5 font-medium">Check</th>
              <th scope="col" className="py-2.5 font-medium">What was checked</th>
              <th scope="col" className="w-[70px] py-2.5 text-right font-medium">Agent</th>
            </tr>
          </thead>
          <tbody>
            {paged.rows.map((row) => (
              <tr key={row.id} id={row.id} className="border-t border-rule align-top">
                <td className="py-3.5"><CheckLabel status={tab === "working" ? "pass" : "unverifiable"} /></td>
                <td className="py-3.5 font-mono text-2xs text-ink-3">{row.check_id}</td>
                <td className="py-3.5 pr-4 text-sm leading-snug">{row.title}</td>
                <td className="py-3.5 text-right font-mono text-2xs text-ink-2">{row.agent}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <p className="py-8 text-sm text-ink-3">{tab === "working" ? "No high-impact passes in this run." : "Every applicable check had evidence."}</p>}
      </div>
      <div className="border-t border-rule px-6 py-3.5">
        <Pager page={paged.page} pages={paged.pages} total={paged.total} size={paged.size} onPage={paged.setPage} noun="checks" />
      </div>
    </div>
  );
}
