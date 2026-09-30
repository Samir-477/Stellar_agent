import { RotateCcw, UserRound, Wrench } from "lucide-react";
import type { GapWho, RunGaps } from "@/lib/types";

// What the run couldn't check, always open: why the run finished with gaps (if it did), then one table row per
// check with the agent's own reason, how to close it and who acts. Rows are grouped by cause.

const WHO: Record<GapWho, { label: string; tone: string; Icon: typeof RotateCcw }> = {
  rerun: { label: "Run again", tone: "border-signal/30 bg-soft text-signal", Icon: RotateCcw },
  us: { label: "Our team", tone: "border-rule-strong bg-mist text-ink-2", Icon: Wrench },
  you: { label: "Your team", tone: "border-amber/40 bg-amber-bg text-amber", Icon: UserRound },
};

function WhoBadge({ who }: { who: GapWho }) {
  const w = WHO[who];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-[3px] border px-2 py-0.5 text-2xs font-semibold whitespace-nowrap ${w.tone}`}>
      <w.Icon aria-hidden="true" size={11} /> {w.label}
    </span>
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
    <section id="gaps" aria-labelledby="gaps-heading" className="scroll-mt-28 border border-rule bg-paper">
      <div className="border-b border-rule bg-mist px-6 py-5">
        <h2 id="gaps-heading" className="font-display text-2xl font-semibold tracking-[-0.01em]">What we couldn&apos;t check</h2>
        <p className="mt-1 text-sm text-ink-2">{summary}. Each one says why, how to close it and who acts.</p>
      </div>

      {gaps.steps.length > 0 && (
        <div className="border-b border-rule px-6 py-5">
          <h3 className="text-base font-semibold text-ink">Why this run finished with gaps</h3>
          <ul className="mt-3 divide-y divide-rule border-y border-rule">
            {gaps.steps.map((s, i) => (
              <li key={`${s.step}-${i}`} className="grid gap-x-6 gap-y-2 py-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_auto]">
                <div>
                  <p className="text-base font-semibold text-ink">{s.title}</p>
                  <p className="mt-1 text-sm leading-relaxed text-ink-2">{s.what_happened}</p>
                  {s.detail.length > 0 && (
                    <p className="mt-1.5 font-mono text-2xs break-all text-ink-3">{s.detail.join("  ·  ")}</p>
                  )}
                </div>
                <p className="text-sm leading-relaxed text-ink"><span className="font-semibold">How to close it: </span>{s.fix}</p>
                <div><WhoBadge who={s.who} /></div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {checks > 0 && (
        <div className="px-6 py-5">
          <h3 className="text-base font-semibold text-ink">Checks we couldn&apos;t run</h3>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-rule-strong text-xs text-ink-3">
                  <th scope="col" className="w-[26%] py-2.5 pr-4 font-semibold">Check</th>
                  <th scope="col" className="w-[32%] py-2.5 pr-4 font-semibold">Why it couldn&apos;t run</th>
                  <th scope="col" className="py-2.5 pr-4 font-semibold">How to close it</th>
                  <th scope="col" className="w-[110px] py-2.5 font-semibold">Who</th>
                </tr>
              </thead>
              {gaps.checks.map((g) => (
                <tbody key={g.cause} className="border-b border-rule last:border-b-0">
                  <tr className="bg-mist">
                    <th scope="colgroup" colSpan={4} className="px-3 py-2.5 text-left font-normal">
                      <span className="text-sm font-semibold text-ink">{g.title}</span>
                      <span className="ml-2 text-xs text-ink-3">{g.items.length} check{g.items.length === 1 ? "" : "s"}</span>
                      <span className="mt-0.5 block text-xs leading-relaxed text-ink-2">{g.explanation}</span>
                    </th>
                  </tr>
                  {g.items.map((item, i) => (
                    <tr key={`${item.check_id}-${i}`} className="border-t border-rule align-top">
                      <td className="py-3 pr-4">
                        <span className="block text-sm leading-snug font-medium text-ink">{item.name}</span>
                        <span className="mt-0.5 block font-mono text-2xs text-signal">{item.check_id} · {item.agent}</span>
                      </td>
                      <td className="py-3 pr-4 leading-relaxed text-ink-2">{item.title}</td>
                      {i === 0 && (
                        <>
                          <td rowSpan={g.items.length} className="border-l border-rule py-3 pr-4 pl-4 leading-relaxed text-ink">{g.fix}</td>
                          <td rowSpan={g.items.length} className="py-3"><WhoBadge who={g.who} /></td>
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              ))}
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
