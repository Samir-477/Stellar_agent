"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ChevronRight } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Pager, usePaged } from "@/components/workspace/pager";
import { ConfidenceLabel, SeverityLabel } from "@/components/workspace/status";
import { plural, urlPath } from "@/lib/format";
import { PILLARS, PILLAR_ORDER } from "@/lib/pillars";
import type { Lane, Pillar, WorkItem } from "@/lib/types";

// Lanes and their reader actions, from docs/priority-matrix.md. Lanes suggest order, not deadlines.
const LANES: { id: Lane; label: string; action: string }[] = [
  { id: "now", label: "Now", action: "Verified high-impact issues to address first" },
  { id: "next", label: "Next", action: "Important, but less certain or medium impact" },
  { id: "later", label: "Later", action: "Low-impact improvements after higher-value work" },
  { id: "investigate", label: "Investigate", action: "Gather evidence before recommending a fix" },
  { id: "monitor", label: "Monitor", action: "Dated search and AI observations, not site defects" },
];

function Row({ item, open, onToggle, cause }: { item: WorkItem; open: boolean; onToggle: () => void; cause?: string }) {
  const reduce = useReducedMotion();
  return (
    <li id={item.id} className={`scroll-mt-28 border-b border-rule last:border-b-0 ${open ? "bg-mist/60" : ""}`}>
      <button type="button" onClick={onToggle} aria-expanded={open}
              className="grid w-full grid-cols-[18px_1fr] gap-3 px-6 py-5 text-left transition-colors hover:bg-mist sm:grid-cols-[18px_52px_1fr_auto] sm:items-start sm:gap-4">
        <ChevronRight aria-hidden="true" size={16} className={`mt-1 text-ink-3 transition-transform ${open ? "rotate-90" : ""}`} />
        <span className="hidden pt-0.5 font-mono text-2xs text-signal sm:block">{item.id}</span>
        <span className="min-w-0">
          <span className="block text-base leading-snug font-semibold">
            <span className="mr-2 font-mono text-2xs font-normal text-signal sm:hidden">{item.id}</span>
            {item.title}
          </span>
          <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-3">
            <span>{item.pages.length ? plural(item.pages.length, "page") : "Site-wide"}</span>
            <span className="font-mono text-2xs">{item.agents.join(" ")}</span>
            {item.patch_keys.length > 0 && <span>{plural(item.patch_keys.length, "proposed change")}</span>}
            {item.facts.length > 0 && <span className="text-signal">Found by {item.agents.length} agents</span>}
            {item.prerequisite_review && <span className="text-amber">Review prerequisites</span>}
            {cause && <span>Part of {cause}</span>}
          </span>
        </span>
        <span className="col-start-2 flex gap-4 sm:col-start-auto sm:flex-col sm:items-end sm:gap-1">
          <SeverityLabel severity={item.severity} />
          <ConfidenceLabel confidence={item.confidence} />
        </span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={reduce ? false : { height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
                      exit={reduce ? undefined : { height: 0, opacity: 0 }} transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
                      className="overflow-hidden">
            <div className="grid gap-8 px-6 pb-7 text-base leading-relaxed sm:pl-[112px] lg:grid-cols-[1.2fr_1fr]">
              <div className="space-y-4">
                <div>
                  <p className="text-xs font-semibold text-ink-2">Proposed action</p>
                  <p className="mt-0.5 text-ink">{item.action}</p>
                </div>
                {item.priority_reason && (
                  <div>
                    <p className="text-xs font-semibold text-ink-2">Why it is in this lane</p>
                    <p className="mt-0.5 text-ink-2">{item.priority_reason}</p>
                  </div>
                )}
                {item.missing_facts.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-amber">Prerequisites to review</p>
                    <ul className="mt-1 space-y-1">
                      {item.missing_facts.map((f) => <li key={f} className="flex gap-2"><span aria-hidden="true" className="mt-2 h-1.5 w-1.5 shrink-0 bg-amber" />{f}</li>)}
                    </ul>
                  </div>
                )}
                <p className="text-xs text-ink-3">Checks: <span className="font-mono text-2xs">{item.check_ids.join(" ")}</span></p>
              </div>
              <div>
                <p className="text-xs font-semibold text-ink-2">Evidence</p>
                <ul className="mt-1.5 space-y-2">
                  {item.evidence.map((e, index) => (
                    <li key={index} className="border-l-2 border-rule-strong bg-paper px-3 py-2">
                      {e.url && <span className="block font-mono text-2xs break-all text-signal">{urlPath(e.url)}</span>}
                      <span className="block text-sm">{e.excerpt}</span>
                    </li>
                  ))}
                  {!item.evidence.length && <li className="text-sm text-ink-3">The agents recorded no excerpt for this item.</li>}
                </ul>
                {item.pages.length > 0 && (
                  <p className="mt-3 text-xs text-ink-3">
                    Pages: <span className="font-mono text-2xs break-all">{item.pages.slice(0, 5).map(urlPath).join("  ")}</span>
                    {item.pages.length > 5 && ` and ${item.pages.length - 5} more`}
                  </p>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}

const PAGE_SIZE = 8;

/** The priority list: five lanes across the top, then that lane's items, eight at a time. */
export function PriorityLedger({ lanes, causeOf }: { lanes: Partial<Record<Lane, WorkItem[]>>; causeOf: Record<string, string> }) {
  const firstLane = LANES.find((l) => lanes[l.id]?.length)?.id ?? "now";
  const [lane, setLane] = useState<Lane>(firstLane);
  const [pillar, setPillar] = useState<Pillar | "all">("all");
  const [open, setOpen] = useState<string | null>(null);
  const current = (lanes[lane] ?? []).filter((i) => pillar === "all" || i.pillars.includes(pillar));
  const paged = usePaged(current, PAGE_SIZE);
  const { setPage } = paged;

  const laneOf = useMemo(() => {
    const map = new Map<string, Lane>();
    LANES.forEach((l) => (lanes[l.id] ?? []).forEach((i) => map.set(i.id, l.id)));
    return map;
  }, [lanes]);

  // Summary citations link here by item id: open that item in its lane, on its page.
  const openFromHash = useCallback(() => {
    const id = decodeURIComponent(window.location.hash.slice(1));
    const target = laneOf.get(id);
    if (!target) return;
    setLane(target);
    setPillar("all");
    setOpen(id);
    setPage(Math.floor((lanes[target] ?? []).findIndex((i) => i.id === id) / PAGE_SIZE));
    requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ block: "start" }));
  }, [laneOf, lanes, setPage]);

  useEffect(() => {
    const frame = requestAnimationFrame(openFromHash); // a link may arrive with a hash already set
    window.addEventListener("hashchange", openFromHash);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("hashchange", openFromHash);
    };
  }, [openFromHash]);

  const pillarCount = (p: Pillar) => (lanes[lane] ?? []).filter((i) => i.pillars.includes(p)).length;

  return (
    <section aria-labelledby="ledger-heading" className="mt-16">
      <h2 id="ledger-heading" className="font-display text-4xl font-semibold tracking-[-0.02em]">What to fix, in order</h2>
      <p className="mt-2 max-w-[680px] text-base leading-relaxed text-ink-2">
        Impact and the agents&apos; confidence choose the lane; reach, key pages and effort order items within it.
        Lanes suggest order, not deadlines, and confidence is the agent&apos;s own rating.
      </p>

      <div className="mt-7 border border-rule">
        <div role="tablist" aria-label="Priority lanes" className="scrollbar-hidden flex gap-2 overflow-x-auto border-b border-rule p-3">
          {LANES.map((l) => {
            const count = lanes[l.id]?.length ?? 0;
            const selected = l.id === lane;
            return (
              <button key={l.id} role="tab" type="button" aria-selected={selected}
                      onClick={() => { setLane(l.id); setPillar("all"); setOpen(null); setPage(0); }}
                      className={`relative min-w-[130px] shrink-0 rounded-[3px] border border-rule px-4 py-3 text-left transition-colors ${selected ? "bg-soft" : "hover:bg-mist"}`}>
                {selected && <span aria-hidden="true" className="absolute inset-x-0 bottom-0 h-[3px] bg-signal" />}
                <span className="flex items-baseline justify-between gap-3">
                  <span className={`font-display text-lg font-semibold ${count ? "" : "text-ink-3"}`}>{l.label}</span>
                  <span className={`font-display text-2xl font-semibold ${selected ? "text-signal" : count ? "text-ink" : "text-ink-3"}`}>{count}</span>
                </span>
                <span className="sr-only">{l.action}</span>
              </button>
            );
          })}
        </div>

        <div role="tabpanel" aria-label={`${LANES.find((l) => l.id === lane)?.label} lane`} className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 border-b border-rule px-6 py-4">
            <span className="mr-1 text-xs text-ink-3">Show</span>
            {(["all", ...PILLAR_ORDER] as const).map((p) => {
              const count = p === "all" ? lanes[lane]?.length ?? 0 : pillarCount(p);
              return (
                <button key={p} type="button" aria-pressed={pillar === p} onClick={() => { setPillar(p); setPage(0); }} disabled={!count}
                        className={`min-h-9 rounded-full border px-3 text-xs font-medium transition-colors disabled:opacity-40 ${pillar === p ? "border-ink bg-ink text-white" : "border-rule-strong text-ink-2 hover:border-ink-3"}`}>
                  {p === "all" ? "All" : PILLARS[p].short} <span className="font-mono text-2xs opacity-80">{count}</span>
                </button>
              );
            })}
          </div>
          <ul>
            {paged.rows.map((item) => (
              <Row key={item.id} item={item} cause={causeOf[item.id]} open={open === item.id}
                   onToggle={() => setOpen((o) => (o === item.id ? null : item.id))} />
            ))}
          </ul>
          {!current.length && (
            <p className="px-6 py-10 text-base text-ink-3">
              {lane === "investigate" ? "No hypotheses needed checking in this run." : lane === "monitor" ? "No dated observations in this run." : "Nothing in this lane."}
            </p>
          )}
          {current.length > PAGE_SIZE && (
            <div className="border-t border-rule px-6 py-3.5">
              <Pager page={paged.page} pages={paged.pages} total={paged.total} size={paged.size} onPage={setPage} noun="items" />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
