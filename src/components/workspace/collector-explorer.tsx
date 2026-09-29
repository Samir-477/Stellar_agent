"use client";

import Link from "next/link";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  ArrowUpRight, Braces, Building2, Check, ClipboardList, Crosshair, FingerprintPattern, Gauge, Globe, MessageCircleQuestion,
  MessageSquareText, Pause, Play, Search, Sparkles, TextSearch, type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import type { CollectorInfo } from "@/lib/types";

// The evidence collectors, one at a time: a list on the left and the selected collector on the right.
// It cycles on its own; choosing a collector stops the cycle so it can be read.

const ICONS: Record<string, LucideIcon> = {
  C1: Globe, C2: Braces, C3: Building2, C4: ClipboardList, C5: TextSearch, C6: Search, C7: MessageCircleQuestion,
  C8: Crosshair, C9: MessageSquareText, C10: Sparkles, C11: Gauge, C12: FingerprintPattern,
};

const CYCLE_MS = 5000;
const SHOWN_AGENTS = 5;

export function CollectorExplorer({ collectors, agentNames }: { collectors: CollectorInfo[]; agentNames: Record<string, string> }) {
  const reduced = useReducedMotion();
  // Auto-plays unless the visitor prefers reduced motion; an explicit Play or Pause always wins.
  const [choice, setChoice] = useState<"auto" | "play" | "pause">("auto");
  const playing = choice === "play" || (choice === "auto" && !reduced);
  const [index, setIndex] = useState(0);
  const current = collectors[index];

  useEffect(() => {
    if (!playing) return;
    const timer = setTimeout(() => setIndex((i) => (i + 1) % collectors.length), CYCLE_MS);
    return () => clearTimeout(timer);
  }, [playing, index, collectors.length]);

  if (!current) return null;
  const Icon = ICONS[current.id] ?? Globe;
  const readers = current.used_by;
  const extra = readers.length - SHOWN_AGENTS;

  return (
    <section id="collectors" className="mx-auto max-w-[1200px] scroll-mt-24 px-5 py-24 sm:px-8" aria-labelledby="collectors-title">
      <div className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <p className="text-xs font-semibold tracking-[0.18em] text-signal uppercase">Explore the {collectors.length} evidence collectors</p>
          <h2 id="collectors-title" className="mt-4 font-display text-6xl leading-[1.08] font-bold tracking-[-0.04em]">
            Go deeper. <span className="text-[#6f8b7c]">One collector at a time.</span>
          </h2>
          <p className="mt-3 max-w-[620px] text-md text-ink-2">
            Agents never read each other&apos;s results. They read this evidence, so every finding traces back to a page, a search result or an AI answer.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => setChoice(playing ? "pause" : "play")} aria-pressed={!playing}
                  className="inline-flex min-h-11 items-center gap-1.5 rounded-[8px] border border-rule bg-paper px-4 text-sm font-semibold text-signal shadow-[0_1px_3px_rgba(3,22,13,0.06)] hover:border-rule-strong">
            {playing ? <Pause aria-hidden="true" size={14} /> : <Play aria-hidden="true" size={14} />}{playing ? "Pause" : "Play"}
          </button>
          <Link href="/runs/new" className="inline-flex min-h-11 items-center gap-1.5 rounded-[8px] border border-rule bg-paper px-4 text-sm font-semibold text-ink shadow-[0_1px_3px_rgba(3,22,13,0.06)] hover:border-rule-strong">
            Run everything together <ArrowUpRight aria-hidden="true" size={14} />
          </Link>
        </div>
      </div>

      <div className="mt-10 grid overflow-hidden rounded-[20px] border border-rule bg-paper shadow-[0_40px_80px_-56px_rgba(3,22,13,0.45)] lg:grid-cols-[300px_minmax(0,1fr)]">
        <ul aria-label="Collectors" className="space-y-1 border-b border-rule p-3 lg:border-r lg:border-b-0">
          {collectors.map((c, i) => {
            const active = i === index;
            const ItemIcon = ICONS[c.id] ?? Globe;
            return (
              <li key={c.id}>
                <button type="button" aria-current={active ? "true" : undefined} onClick={() => { setIndex(i); setChoice("pause"); }}
                        className={`relative flex w-full items-center gap-3 overflow-hidden rounded-[12px] border px-3.5 py-2.5 text-left text-sm transition-colors ${active ? "border-signal/25 bg-soft font-semibold text-ink" : "border-transparent text-ink-2 hover:bg-mist"}`}>
                  <ItemIcon aria-hidden="true" size={16} className={active ? "text-signal" : "text-ink-3"} />
                  <span className="w-7 font-mono text-2xs text-signal">{c.id}</span>
                  <span className="min-w-0 flex-1 truncate">{c.name}</span>
                  <ArrowUpRight aria-hidden="true" size={13} className={active ? "text-signal" : "text-ink-3/70"} />
                  {active && playing && (
                    <motion.span key={`${c.id}-progress`} aria-hidden="true" className="absolute bottom-0 left-0 h-[2px] bg-signal"
                                 initial={{ width: "0%" }} animate={{ width: "100%" }} transition={{ duration: CYCLE_MS / 1000, ease: "linear" }} />
                  )}
                </button>
              </li>
            );
          })}
        </ul>

        <div className="relative bg-canvas/60 bg-[linear-gradient(rgba(0,123,70,0.045)_1px,transparent_1px),linear-gradient(90deg,rgba(0,123,70,0.045)_1px,transparent_1px)] bg-size-[32px_32px] p-7 sm:p-10 lg:min-h-[640px]">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={current.id} initial={reduced ? false : { opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
                        exit={reduced ? undefined : { opacity: 0, y: -8 }} transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}>
              <span className="flex h-16 w-16 items-center justify-center rounded-[18px] bg-linear-to-b from-signal to-signal-deep text-white shadow-[0_16px_30px_-14px_rgba(0,103,58,0.8),inset_0_1px_0_rgba(255,255,255,0.18)]">
                <Icon aria-hidden="true" size={28} />
              </span>
              <p className="mt-7 text-xs font-semibold tracking-[0.18em] text-signal uppercase">{current.group_label} / {current.id}</p>
              <h3 className="mt-3 font-display text-5xl leading-tight font-semibold tracking-[-0.03em]">{current.name}</h3>
              <p className="mt-3 max-w-[680px] text-md leading-relaxed text-ink-2">{current.captures}</p>

              <p className="mt-8 text-2xs font-semibold tracking-[0.16em] text-ink-3 uppercase">Read by {readers.length} agent{readers.length === 1 ? "" : "s"}</p>
              <ul className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {readers.slice(0, SHOWN_AGENTS).map((id) => (
                  <li key={id} className="rounded-[14px] border border-rule bg-paper p-4 shadow-[0_2px_8px_rgba(3,22,13,0.04)]">
                    <Check aria-hidden="true" size={16} className="text-signal" strokeWidth={2.4} />
                    <p className="mt-3 text-sm font-semibold"><span className="mr-1.5 font-mono text-2xs text-signal">{id}</span>{agentNames[id] ?? id}</p>
                  </li>
                ))}
                {extra > 0 && (
                  <li className="flex items-center rounded-[14px] border border-dashed border-rule-strong bg-paper/60 p-4 text-sm font-medium text-ink-2">
                    and {extra} more agent{extra === 1 ? "" : "s"}
                  </li>
                )}
              </ul>

              <div className="mt-8 flex flex-wrap items-end justify-between gap-5 border-t border-rule pt-6">
                <div>
                  <p className="text-2xs font-semibold tracking-[0.16em] text-signal uppercase">What it uses</p>
                  <p className="mt-2 text-sm text-ink-2">
                    {current.services.length ? current.services.join(", ") : "No outside service: it works from the pages it captures."}
                  </p>
                </div>
                <Link href={`/runs/new?agents=${readers.join(",")}`}
                      className="inline-flex min-h-11 items-center gap-1.5 rounded-[8px] bg-linear-to-b from-signal to-signal-deep px-5 text-sm font-semibold text-white shadow-[0_12px_24px_-12px_rgba(0,103,58,0.85),inset_0_1px_0_rgba(255,255,255,0.16)] hover:brightness-110">
                  Run the agents that read it <ArrowUpRight aria-hidden="true" size={14} />
                </Link>
              </div>
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}
