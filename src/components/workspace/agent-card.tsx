"use client";

import Link from "next/link";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowRight, Info } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { AgentIcon } from "@/components/workspace/icons";
import type { AgentInfo } from "@/lib/types";

type Side = "right" | "left" | "below";

/** One agent on Home. Hover or focus opens its detail: how it works, an example finding and what it reads. */
export function AgentCard({ agent, collectorNames }: { agent: AgentInfo; collectorNames: Record<string, string> }) {
  const reduce = useReducedMotion();
  const id = useId();
  const ref = useRef<HTMLLIElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const [open, setOpen] = useState(false);
  const [side, setSide] = useState<Side>("right");

  useEffect(() => () => window.clearTimeout(timer.current), []);

  function place() {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect || window.innerWidth < 1024) return setSide("below");
    setSide(rect.right + 400 > window.innerWidth ? "left" : "right");
  }
  function show(delay = 160) {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { place(); setOpen(true); }, delay);
  }
  function hide() {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(false), 140);
  }

  const position = side === "right" ? "top-0 left-[calc(100%+12px)]" : side === "left" ? "top-0 right-[calc(100%+12px)]" : "top-[calc(100%+8px)] inset-x-0";

  return (
    <li ref={ref} className={`group relative flex flex-col border border-rule bg-paper p-6 transition-[border-color,box-shadow] duration-200 ${open ? "z-30 border-signal/40 shadow-[0_18px_40px_-28px_rgba(7,27,18,0.5)]" : "hover:border-rule-strong"}`}
        onMouseEnter={() => show()} onMouseLeave={hide}
        onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}>
      <div className="flex items-start justify-between gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-[4px] bg-soft text-signal"><AgentIcon id={agent.id} size={17} /></span>
        <span className="text-right">
          <span className="block font-mono text-2xs text-signal">{agent.id}</span>
          {!agent.counts_toward_readiness && <span className="mt-0.5 block text-2xs text-ink-3">Observation</span>}
        </span>
      </div>
      <h4 className="mt-5 font-display text-xl font-semibold tracking-tight">{agent.name}</h4>
      <p className="mt-2 flex-1 text-base leading-relaxed text-ink-2">{agent.question}</p>
      <div className="mt-6 flex items-center justify-between gap-3 text-xs">
        <button type="button" aria-expanded={open} aria-controls={`${id}-detail`}
                onClick={() => (open ? setOpen(false) : show(0))} onFocus={() => show(0)} onBlur={hide}
                className="inline-flex min-h-8 items-center gap-1.5 text-ink-3 hover:text-ink">
          <Info aria-hidden="true" size={13} /> How it works
        </button>
        <span className="text-ink-3">{agent.checks.length} checks</span>
      </div>

      <AnimatePresence>
        {open && (
          <motion.div id={`${id}-detail`} role="region" aria-label={`${agent.name}: how it works`}
                      onMouseEnter={() => show(0)} onMouseLeave={hide}
                      initial={reduce ? { opacity: 0 } : { opacity: 0, y: 6, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={reduce ? { opacity: 0 } : { opacity: 0, y: 4 }} transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
                      className={`absolute ${position} z-40 w-full border border-rule-strong bg-paper p-6 text-left shadow-[0_30px_60px_-30px_rgba(7,27,18,0.45)] lg:w-[380px]`}>
            <p className="flex items-center gap-2 text-sm font-semibold"><span className="text-signal"><AgentIcon id={agent.id} size={15} /></span>{agent.name}</p>
            <dl className="mt-4 space-y-4 text-sm leading-relaxed">
              <div>
                <dt className="text-2xs font-semibold tracking-wide text-ink-3">How it works</dt>
                <dd className="mt-1 text-ink">{agent.how}</dd>
              </div>
              <div>
                <dt className="text-2xs font-semibold tracking-wide text-ink-3">Example finding</dt>
                <dd className="mt-1 border-l-2 border-signal bg-soft/50 px-3 py-2 text-ink">{agent.example}</dd>
              </div>
              <div>
                <dt className="text-2xs font-semibold tracking-wide text-ink-3">You get</dt>
                <dd className="mt-1 text-ink-2">{agent.outcome}</dd>
              </div>
              <div>
                <dt className="text-2xs font-semibold tracking-wide text-ink-3">Reads</dt>
                <dd className="mt-1 text-ink-2">{agent.reads.map((c) => collectorNames[c] ?? c).join(", ")}</dd>
              </div>
            </dl>
            <Link href={`/runs/new?agents=${agent.id}`} className="mt-5 inline-flex min-h-9 items-center gap-1.5 text-sm font-semibold text-signal hover:underline">
              Run this agent on its own <ArrowRight aria-hidden="true" size={14} />
            </Link>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}
