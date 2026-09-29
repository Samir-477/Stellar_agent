import { ChevronRight, RotateCcw, UserRound, Wrench } from "lucide-react";
import type { GapWho, RunGaps } from "@/lib/types";

// Why a run finished with gaps, and the checks it couldn't run, each with how to close it and who acts.

const WHO: Record<GapWho, { label: string; tone: string; Icon: typeof RotateCcw }> = {
  rerun: { label: "Run again", tone: "border-signal/30 bg-soft text-signal", Icon: RotateCcw },
  us: { label: "Our team", tone: "border-rule-strong bg-mist text-ink-2", Icon: Wrench },
  you: { label: "Your team", tone: "border-amber/40 bg-amber-bg text-amber", Icon: UserRound },
};

function WhoBadge({ who }: { who: GapWho }) {
  const w = WHO[who];
  return (
    <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-[3px] border px-2 py-0.5 text-2xs font-semibold ${w.tone}`}>
      <w.Icon aria-hidden="true" size={11} /> {w.label}
    </span>
  );
}

function Card({ title, count, who, explanation, fix, children }: {
  title: string; count?: string; who: GapWho; explanation: string; fix: string; children?: React.ReactNode;
}) {
  return (
    <li className="rounded-[6px] border border-rule bg-paper px-5 py-4">
      <div className="flex items-start justify-between gap-4">
        <p className="text-base leading-snug font-semibold">{title}{count && <span className="ml-2 text-sm font-normal text-ink-3">{count}</span>}</p>
        <WhoBadge who={who} />
      </div>
      <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{explanation}</p>
      <p className="mt-2 text-sm leading-relaxed text-ink"><span className="font-semibold">How to close it: </span>{fix}</p>
      {children}
    </li>
  );
}

export function GapsPanel({ gaps }: { gaps: RunGaps }) {
  const checks = gaps.checks.reduce((n, g) => n + g.items.length, 0);
  if (!gaps.steps.length && !checks) return null;
  const summary = [
    gaps.steps.length ? `${gaps.steps.length} step${gaps.steps.length === 1 ? "" : "s"} didn't fully finish` : "",
    checks ? `${checks} check${checks === 1 ? "" : "s"} couldn't run` : "",
  ].filter(Boolean).join(", ");
  return (
    <details id="gaps" open={gaps.steps.length > 0} className="group scroll-mt-28 border border-rule bg-mist [&_summary::-webkit-details-marker]:hidden">
      <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 px-6 py-5">
        <ChevronRight aria-hidden="true" size={16} className="text-ink-3 transition-transform group-open:rotate-90" />
        <span className="text-base font-semibold">What we couldn&apos;t check, and how to close it</span>
        <span className="text-sm text-ink-3">{summary}</span>
      </summary>
      <div className="space-y-8 px-6 pb-7">
        {gaps.steps.length > 0 && (
          <section aria-labelledby="gaps-steps">
            <h3 id="gaps-steps" className="text-sm font-semibold text-ink">Why this run finished with gaps</h3>
            <ul className="mt-3 grid gap-3 lg:grid-cols-2">
              {gaps.steps.map((s, i) => (
                <Card key={`${s.step}-${i}`} title={s.title} who={s.who} explanation={s.what_happened} fix={s.fix}>
                  {s.detail.length > 0 && (
                    <details className="mt-2 [&_summary::-webkit-details-marker]:hidden">
                      <summary className="cursor-pointer text-xs font-medium text-signal hover:underline">Technical detail</summary>
                      <ul className="mt-1.5 space-y-1 font-mono text-2xs break-all text-ink-3">
                        {s.detail.map((d) => <li key={d}>{d}</li>)}
                      </ul>
                    </details>
                  )}
                </Card>
              ))}
            </ul>
          </section>
        )}
        {gaps.checks.length > 0 && (
          <section aria-labelledby="gaps-checks">
            <h3 id="gaps-checks" className="text-sm font-semibold text-ink">Checks we couldn&apos;t run</h3>
            <ul className="mt-3 grid gap-3 lg:grid-cols-2">
              {gaps.checks.map((g) => (
                <Card key={g.cause} title={g.title} count={`${g.items.length} check${g.items.length === 1 ? "" : "s"}`}
                      who={g.who} explanation={g.explanation} fix={g.fix}>
                  <details className="mt-2 [&_summary::-webkit-details-marker]:hidden">
                    <summary className="cursor-pointer text-xs font-medium text-signal hover:underline">Show the checks</summary>
                    <ul className="mt-2 space-y-1.5 text-sm text-ink-2">
                      {g.items.map((item, i) => (
                        <li key={`${item.check_id}-${i}`}>
                          {item.name}
                          <span className="block text-xs text-ink-3"><span className="mr-1.5 font-mono text-2xs text-signal">{item.check_id}</span>{item.title}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                </Card>
              ))}
            </ul>
          </section>
        )}
      </div>
    </details>
  );
}
