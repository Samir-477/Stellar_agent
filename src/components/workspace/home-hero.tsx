"use client";

import Link from "next/link";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowDown, ArrowUpRight, Check, Diamond, FileText, GitBranch, Pause, Play, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import type { Pillar } from "@/lib/types";

// Home hero: the pitch on the left, and a looping walk-through of one run on the right. Each discipline
// tab shows the evidence it starts from and the question its agents answer; the three steps light in turn.

const TABS: { id: Pillar; label: string; icon: typeof ShieldCheck; source: string; sourceText: string; focus: string; question: string; bars: number[] }[] = [
  { id: "seo", label: "Search", icon: ShieldCheck, source: "Your website", sourceText: "Captured HTML, links, headers and page speed.",
    focus: "Found on Google", question: "Can search engines reach, understand and rank your pages?", bars: [30, 58, 42, 76, 50, 88, 38, 70, 55, 80, 44, 66] },
  { id: "aeo", label: "Answers", icon: FileText, source: "Search results", sourceText: "Dated Google results and the questions people ask.",
    focus: "Answers customers' questions", question: "Does the site answer what people ask, in a form Google can quote?", bars: [62, 40, 84, 52, 70, 34, 90, 48, 64, 38, 74, 56] },
  { id: "geo", label: "AI", icon: Sparkles, source: "AI answers", sourceText: "What AI assistants say about the business, and where they look.",
    focus: "Understood by AI assistants", question: "Can AI assistants read, trust and repeat your facts correctly?", bars: [46, 72, 36, 60, 86, 44, 68, 30, 78, 52, 88, 40] },
];

const STEPS = [
  { title: "Capture", text: "Keep the source" },
  { title: "Diagnose", text: "Rate every check" },
  { title: "Fix", text: "Preview the change" },
];

const STEP_MS = 2000;

export function HomeHero({ agentCount, counts }: { agentCount: number; counts: Record<Pillar, { agents: number; checks: number }> }) {
  const reduced = useReducedMotion();
  // Auto-plays unless the visitor prefers reduced motion; an explicit Play or Pause always wins.
  const [choice, setChoice] = useState<"auto" | "play" | "pause">("auto");
  const playing = choice === "play" || (choice === "auto" && !reduced);
  const [tick, setTick] = useState(0);
  const tab = Math.floor(tick / STEPS.length) % TABS.length;
  const step = tick % STEPS.length;
  const current = TABS[tab];
  const Icon = current.icon;

  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => setTick((t) => t + 1), STEP_MS);
    return () => clearInterval(timer);
  }, [playing]);

  return (
    <section className="relative overflow-hidden border-b border-rule bg-canvas" aria-labelledby="home-title">
      <div aria-hidden="true" className="pointer-events-none absolute -top-40 right-[-8%] h-[640px] w-[640px] rounded-full bg-[radial-gradient(closest-side,rgba(95,214,154,0.2),transparent)]" />
      <div className="relative mx-auto grid max-w-[1200px] gap-14 px-5 py-16 sm:px-8 lg:min-h-[calc(100svh-72px)] lg:grid-cols-[minmax(0,1fr)_minmax(0,1.02fr)] lg:items-center lg:gap-14 lg:py-20">
        <div>
          <p className="flex items-center gap-2.5 text-xs font-semibold tracking-[0.18em] text-signal uppercase">
            <span aria-hidden="true" className="h-2 w-2 rounded-full bg-mint shadow-[0_0_0_4px_rgba(95,214,154,0.22)]" />
            Search, answers and AI, diagnosed
          </p>
          <h1 id="home-title" className="mt-6 max-w-[600px] font-display text-7xl leading-[1.04] font-bold tracking-[-0.045em] lg:text-8xl">
            Know what your site shows <span className="text-signal">to search and AI.</span>
          </h1>
          <p className="mt-7 max-w-[540px] text-lg leading-[1.7] text-ink-2">
            One page. {agentCount} independent agents. See the evidence, understand the gaps and get a prioritised plan with the fixes in place.
          </p>
          <div className="mt-9 flex flex-wrap gap-3">
            <Link href="/runs/new" className="inline-flex min-h-12 items-center gap-2.5 rounded-[8px] bg-linear-to-b from-signal to-signal-deep px-6 text-base font-semibold text-white shadow-[0_14px_28px_-14px_rgba(0,103,58,0.9),inset_0_1px_0_rgba(255,255,255,0.18)] transition-[filter] hover:brightness-110">
              Run all {agentCount} agents <ArrowUpRight aria-hidden="true" size={16} />
            </Link>
            <a href="#collectors" className="inline-flex min-h-12 items-center gap-2 rounded-[8px] border border-rule bg-paper px-5 text-base font-semibold text-ink shadow-[0_2px_6px_rgba(3,22,13,0.06)] transition-colors hover:border-rule-strong">
              Explore the collectors <ArrowDown aria-hidden="true" size={15} />
            </a>
          </div>
          <ul className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm text-ink-3">
            <li className="flex items-center gap-1.5"><Diamond aria-hidden="true" size={12} /> Saved as sessions</li>
            <li className="flex items-center gap-1.5"><ArrowUpRight aria-hidden="true" size={13} /> Run one agent or all</li>
            <li className="flex items-center gap-1.5"><Check aria-hidden="true" size={13} /> Evidence-linked findings</li>
          </ul>
        </div>

        {/* The looping walk-through. It describes the flow only: no scores are invented here. */}
        <div className="rounded-[26px] border border-white/80 bg-white/45 p-2.5 shadow-[0_44px_90px_-52px_rgba(3,22,13,0.5)] backdrop-blur">
          <div className="overflow-hidden rounded-[18px] border border-rule bg-paper">
            <div className="flex items-center justify-between gap-3 px-5 py-3.5 sm:px-6">
              <p className="flex items-center gap-2 text-2xs font-semibold tracking-[0.14em] text-ink uppercase">
                <span aria-hidden="true" className="h-2 w-2 rounded-full bg-signal" /> The diagnosis workspace
              </p>
              <div className="flex items-center gap-2">
                <span className="hidden rounded-[6px] bg-mist px-2.5 py-1 text-2xs font-medium text-ink-3 sm:inline">Interactive overview</span>
                <button type="button" onClick={() => setChoice(playing ? "pause" : "play")} aria-pressed={!playing}
                        className="inline-flex min-h-9 items-center gap-1.5 rounded-[8px] border border-rule px-3 text-xs font-semibold text-ink shadow-[0_1px_2px_rgba(3,22,13,0.06)] hover:border-rule-strong">
                  {playing ? <Pause aria-hidden="true" size={13} /> : <Play aria-hidden="true" size={13} />}{playing ? "Pause" : "Play"}
                </button>
              </div>
            </div>

            <div role="tablist" aria-label="Disciplines" className="grid grid-cols-3 border-y border-rule">
              {TABS.map((t, i) => {
                const active = i === tab;
                const TabIcon = t.icon;
                return (
                  <button key={t.id} type="button" role="tab" aria-selected={active} onClick={() => setTick(i * STEPS.length)}
                          className={`relative flex min-h-13 items-center justify-center gap-2 text-sm font-medium transition-colors ${i ? "border-l border-rule" : ""} ${active ? "text-white" : "text-ink-2 hover:bg-mist"}`}>
                    {active && <motion.span layoutId="hero-tab" aria-hidden="true" className="absolute inset-0 bg-linear-to-b from-signal to-signal-deep"
                                            transition={{ type: "spring", stiffness: 380, damping: 34 }} />}
                    <TabIcon aria-hidden="true" size={16} className="relative" />
                    <span className="relative">{t.label}</span>
                  </button>
                );
              })}
            </div>

            <div className="bg-canvas/70 bg-[linear-gradient(rgba(0,123,70,0.05)_1px,transparent_1px),linear-gradient(90deg,rgba(0,123,70,0.05)_1px,transparent_1px)] bg-size-[28px_28px] p-5 sm:p-6">
              <AnimatePresence mode="wait" initial={false}>
                <motion.div key={current.id} initial={reduced ? false : { opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                            exit={reduced ? undefined : { opacity: 0, y: -8 }} transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
                            className="grid items-center gap-3 sm:grid-cols-[minmax(0,1fr)_44px_minmax(0,1fr)]">
                  <div className="rounded-[14px] border border-rule bg-paper p-5 shadow-[0_2px_8px_rgba(3,22,13,0.04)]">
                    <p className="font-mono text-2xs font-bold tracking-[0.14em] text-signal">01 / SOURCE</p>
                    <p className="mt-3 font-display text-2xl font-semibold tracking-tight">{current.source}</p>
                    <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{current.sourceText}</p>
                    <div aria-hidden="true" className="mt-5 flex h-11 items-end gap-1.5">
                      {current.bars.map((h, i) => (
                        <motion.span key={i} className={`w-full rounded-[2px] ${i % 3 === 1 ? "bg-signal" : "bg-mint/70"}`}
                                     initial={reduced ? false : { height: "12%" }} animate={{ height: `${h}%` }}
                                     transition={{ duration: 0.6, delay: i * 0.03, ease: [0.22, 1, 0.36, 1] }} />
                      ))}
                    </div>
                  </div>
                  <div aria-hidden="true" className="hidden items-center justify-center sm:flex">
                    <span className="flex h-11 w-11 items-center justify-center rounded-full border border-signal/30 bg-paper text-signal shadow-[0_0_0_6px_rgba(95,214,154,0.14)]">
                      <Icon size={18} />
                    </span>
                  </div>
                  <div className="rounded-[14px] border border-signal/25 bg-soft/60 p-5">
                    <p className="font-mono text-2xs font-bold tracking-[0.14em] text-signal">02 / FOCUS</p>
                    <p className="mt-3 font-display text-2xl font-semibold tracking-tight">{current.focus}</p>
                    <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{current.question}</p>
                    <p className="mt-4 inline-flex rounded-[6px] bg-paper/80 px-2.5 py-1 text-2xs font-medium text-ink-2">
                      {counts[current.id].agents} agents, {counts[current.id].checks} checks
                    </p>
                  </div>
                </motion.div>
              </AnimatePresence>

              <ol className="mt-4 grid grid-cols-3 gap-3">
                {STEPS.map((s, i) => {
                  const lit = i <= step;
                  return (
                    <li key={s.title} className={`rounded-[12px] border p-3.5 transition-[border-color,background-color] duration-300 ${i === step ? "border-signal/45 bg-paper shadow-[0_8px_18px_-12px_rgba(0,103,58,0.55)]" : "border-rule bg-paper/80"}`}>
                      <p className={`flex items-center gap-1.5 font-mono text-2xs ${lit ? "text-signal" : "text-ink-3"}`}>
                        0{i + 1}{lit && <GitBranch aria-hidden="true" size={10} className={i === step ? "" : "opacity-50"} />}
                      </p>
                      <p className="mt-1.5 text-sm font-semibold">{s.title}</p>
                      <p className="mt-0.5 text-2xs text-ink-3">{s.text}</p>
                    </li>
                  );
                })}
              </ol>
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-rule px-5 py-3 text-2xs text-ink-3 sm:px-6">
              <span className="flex items-center gap-1.5"><Diamond aria-hidden="true" size={10} /> Every finding links to its evidence</span>
              <span className="hidden sm:inline">Illustrative flow, no sample scores</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
