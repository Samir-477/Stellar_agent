"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";
import type { Pillar } from "@/lib/types";

// The home page's focus chooser, drawn like the brand mark: each discipline is a constellation of its
// agents (one star per agent) orbiting the diagnosis they feed. Hovering or focusing a discipline lights
// its constellation; choosing it starts a run with those agents.

export type FocusOption = { id: Pillar; short: string; name: string; outcome: string; agentIds: string[]; checks: number };

const HUB = { x: 220, y: 138 };
const CENTERS: Record<Pillar, { x: number; y: number; r: number }> = {
  seo: { x: 220, y: 50, r: 40 },
  aeo: { x: 362, y: 196, r: 32 },
  geo: { x: 78, y: 196, r: 34 },
};

/** Deterministic star positions around a cluster centre, in angle order so the chain reads as a shape. */
function stars(pillar: Pillar, count: number) {
  const { x, y, r } = CENTERS[pillar];
  const offset = { seo: 0.4, aeo: 1.1, geo: 2.3 }[pillar];
  return Array.from({ length: count }, (_, i) => {
    const angle = offset + (i / count) * Math.PI * 2;
    const reach = r * (0.74 + 0.26 * (((i * 7 + 3) % 10) / 10));
    // Rounded: server and browser trig can differ in the last digit, which would break hydration.
    const round = (n: number) => Math.round(n * 10) / 10;
    return { x: round(x + reach * Math.cos(angle)), y: round(y + reach * Math.sin(angle) * 0.72), big: i % 4 === 0 };
  });
}

export function FocusMap({ options }: { options: FocusOption[] }) {
  const [active, setActive] = useState<Pillar | null>(null);
  const reduced = useReducedMotion();
  const groups = options.map((o) => {
    const points = stars(o.id, o.agentIds.length);
    const nearest = [...points].sort((a, b) => Math.hypot(a.x - HUB.x, a.y - HUB.y) - Math.hypot(b.x - HUB.x, b.y - HUB.y))[0];
    return { ...o, points, nearest };
  });

  return (
    <section aria-labelledby="choose-scope"
             className="relative min-w-0 overflow-hidden rounded-[10px] bg-forest text-white shadow-[0_40px_80px_-40px_rgba(3,22,13,0.75)] ring-1 ring-white/10">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_50%_38%,rgba(95,214,154,0.16),transparent_62%)]" />
      <div className="relative px-6 pt-6 sm:px-7">
        <h2 id="choose-scope" className="font-display text-2xl font-semibold tracking-tight">Choose a focus</h2>
        <p className="mt-1 text-sm text-white/60">Each star is an agent. Start with one discipline, or run them together.</p>
      </div>

      <svg viewBox="0 0 440 250" className="relative mx-auto mt-2 block h-auto w-full max-w-[520px] px-4" role="img"
           aria-label={groups.map((g) => `${g.short}: ${g.agentIds.length} agents`).join(", ")}>
        <ellipse cx={HUB.x} cy={HUB.y} rx="148" ry="84" stroke="#5FD69A" strokeOpacity="0.14" strokeDasharray="2 6" fill="none" />
        {groups.map((g, gi) => {
          const lit = active === null || active === g.id;
          return (
            <g key={g.id} style={{ opacity: lit ? 1 : 0.28, transition: "opacity 240ms ease" }}>
              <motion.line x1={g.nearest.x} y1={g.nearest.y} x2={HUB.x} y2={HUB.y} stroke="#5FD69A"
                           strokeOpacity={active === g.id ? 0.7 : 0.22} strokeWidth="1" strokeDasharray={active === g.id ? undefined : "3 4"}
                           initial={reduced ? false : { pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.9, delay: 0.5 + gi * 0.12 }} />
              <motion.polyline points={g.points.map((p) => `${p.x},${p.y}`).join(" ")} fill="none" stroke="#5FD69A"
                               strokeOpacity={active === g.id ? 0.75 : 0.4} strokeWidth="1.2" strokeLinejoin="round"
                               initial={reduced ? false : { pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.1, delay: gi * 0.12, ease: [0.22, 1, 0.36, 1] }} />
              {g.points.map((p, i) => (
                <circle key={i} cx={p.x} cy={p.y} r={p.big ? 3.4 : 2.4} fill={active === g.id ? "#8EF0BD" : "#5FD69A"} />
              ))}
              <text x={CENTERS[g.id].x} y={g.id === "seo" ? CENTERS.seo.y - CENTERS.seo.r * 0.72 - 12 : CENTERS[g.id].y + CENTERS[g.id].r * 0.72 + 22}
                    textAnchor="middle" className="fill-white/70 font-mono text-[10px] tracking-[0.12em]">
                {g.short} {g.agentIds.length}
              </text>
            </g>
          );
        })}
        <circle cx={HUB.x} cy={HUB.y} r="26" fill="url(#hub-glow)" />
        <path d={`M${HUB.x} ${HUB.y - 15}L${HUB.x + 3.6} ${HUB.y - 3.6}L${HUB.x + 15} ${HUB.y}L${HUB.x + 3.6} ${HUB.y + 3.6}L${HUB.x} ${HUB.y + 15}L${HUB.x - 3.6} ${HUB.y + 3.6}L${HUB.x - 15} ${HUB.y}L${HUB.x - 3.6} ${HUB.y - 3.6}Z`} fill="#F2FBF5" />
        <defs>
          <radialGradient id="hub-glow">
            <stop stopColor="#5FD69A" stopOpacity="0.45" />
            <stop offset="1" stopColor="#5FD69A" stopOpacity="0" />
          </radialGradient>
        </defs>
      </svg>

      <div className="relative mt-2 border-t border-white/10">
        {groups.map((g) => (
          <Link key={g.id} href={`/runs/new?agents=${g.agentIds.join(",")}`}
                onMouseEnter={() => setActive(g.id)} onMouseLeave={() => setActive(null)}
                onFocus={() => setActive(g.id)} onBlur={() => setActive(null)}
                className="group grid grid-cols-[56px_minmax(0,1fr)_20px] items-center gap-3 border-b border-white/10 px-6 py-4 transition-colors last:border-b-0 hover:bg-white/[0.05] focus-visible:bg-white/[0.07] sm:px-7">
            <span className="font-display text-xl font-semibold tracking-[-0.02em] text-mint">{g.short}</span>
            <span className="min-w-0">
              <span className="block text-base font-semibold">{g.name}</span>
              <span className="mt-0.5 block text-sm leading-snug text-white/60">{g.outcome}</span>
              <span className="mt-1.5 block font-mono text-2xs text-white/45">{g.agentIds.length} agents, {g.checks} checks</span>
            </span>
            <ArrowRight aria-hidden="true" size={18} className="text-mint transition-transform group-hover:translate-x-1" />
          </Link>
        ))}
      </div>
    </section>
  );
}
