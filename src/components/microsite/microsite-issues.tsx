"use client";

import { Check, ChevronDown, ChevronRight, CircleDashed, Sparkles } from "lucide-react";
import { useState } from "react";
import { CodeDiff } from "@/components/workspace/code-diff";
import { FixPlan, PlainExplanation, TermsUsed } from "@/components/workspace/plain-explanation";
import type { MicrositeIssue } from "@/lib/types";

function IssueItem({ issue, open, onToggle, wide, showReady = false }: {
  issue: MicrositeIssue; open: boolean; onToggle: () => void; wide: boolean; showReady?: boolean;
}) {
  const plain = issue.plain;
  const ready = showReady && !issue.fixed && (issue.awaiting_approval?.length ?? 0) > 0;
  return (
    <li className="border-b border-rule last:border-b-0">
      <button type="button" onClick={onToggle} aria-expanded={open}
              className="grid w-full grid-cols-[22px_1fr_16px] gap-3 px-5 py-4 text-left transition-colors hover:bg-mist">
        {issue.fixed
          ? <span className="mt-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-signal text-white"><Check aria-hidden="true" size={12} strokeWidth={3} /></span>
          : <CircleDashed aria-hidden="true" size={20} className="mt-0.5 text-amber" />}
        <span>
          <span className="block text-sm leading-snug font-semibold">{plain?.problem ?? issue.title}</span>
          <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-ink-3">
            Found by {issue.agent_name}
            {ready && (
              <span className="inline-flex items-center gap-1 rounded-[3px] border border-signal/40 bg-soft px-1.5 py-px font-semibold text-signal">
                <Sparkles aria-hidden="true" size={10} /> Ready to apply
              </span>
            )}
          </span>
        </span>
        <ChevronDown aria-hidden="true" size={16} className={`mt-1 text-ink-3 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="space-y-4 px-5 pb-6 pl-[54px] text-sm leading-relaxed">
          {ready && (
            <p className="rounded-[6px] border border-signal/30 bg-soft px-4 py-3 text-sm text-ink">
              <span className="font-semibold">We&apos;ve prepared this change.</span> Approve it to apply it to the page;
              the code is under Technical details.
            </p>
          )}
          {plain && issue.fixed ? (
            <PlainExplanation plain={{ ...plain, action: `Done in this preview: ${lowerFirst(plain.action)}` }} compact />
          ) : plain ? (
            <>
              <PlainExplanation plain={plain} compact hideAction={!!plain.steps?.length} />
              {plain.steps?.length ? (
                <FixPlan action={plain.action} steps={plain.steps} owner={plain.owner} effort={issue.effort} verification={issue.verification} />
              ) : null}
            </>
          ) : (
            // No plain words for this check: the agent's own explanation, in the same box.
            <PlainExplanation compact plain={{
              name: issue.title, problem: issue.title, meaning: "", why: issue.impact, analogy: "",
              action: issue.fixed ? `Done in this preview: ${lowerFirst(issue.fix)}` : issue.fix,
              site_case: "", case_source: "rules", terms: [],
            }} />
          )}
          {(plain || issue.changes.length > 0) && (
            <details className="group [&_summary::-webkit-details-marker]:hidden">
              <summary className="flex cursor-pointer items-center gap-2 text-sm font-semibold text-ink">
                <ChevronRight aria-hidden="true" size={15} className="text-ink-3 transition-transform group-open:rotate-90" />
                Technical details
              </summary>
              <div className="mt-3 space-y-4">
                {plain && <p className="text-ink-2"><span className="font-semibold text-ink">{issue.title}. </span>{issue.fix}</p>}
                {issue.changes.map((change, i) => (
                  <div key={i} className="space-y-2">
                    <CodeDiff before={change.before} after={change.after} beforeSegments={change.before_segments}
                              afterSegments={change.after_segments} language={change.language} compact={!wide} />
                    {change.note && <p className="text-xs text-ink-3">{change.note}</p>}
                  </div>
                ))}
                {plain && plain.terms.length > 0 && <TermsUsed terms={plain.terms} />}
              </div>
            </details>
          )}
        </div>
      )}
    </li>
  );
}

function lowerFirst(text: string): string {
  return text ? text.charAt(0).toLowerCase() + text.slice(1) : text;
}

/** The issues on this page: the ones fixed in this preview first, then the ones still to do. `wide` gives the
 *  code diffs full size, for a column wide enough to show before and after side by side. In the workspace,
 *  `showReady` marks still-to-do items with a prepared change (listed first), and `todoTop`/`todoBottom`
 *  hold the approval and hand-off controls; the public microsite shows none of these. */
export function MicrositeIssues({ issues, wide = false, showReady = false, todoTop, todoBottom }: {
  issues: MicrositeIssue[]; wide?: boolean; showReady?: boolean; todoTop?: React.ReactNode; todoBottom?: React.ReactNode;
}) {
  const fixed = issues.filter((i) => i.fixed);
  const isReady = (i: MicrositeIssue) => showReady && (i.awaiting_approval?.length ?? 0) > 0;
  const pending = issues.filter((i) => !i.fixed).sort((a, b) => Number(isReady(b)) - Number(isReady(a)));
  const readyCount = pending.filter(isReady).length;
  const [open, setOpen] = useState<number | null>(fixed.length ? 0 : null);
  const toggle = (index: number) => setOpen((current) => (current === index ? null : index));
  return (
    <div className="space-y-8">
      <section aria-labelledby="fixed-heading">
        <h2 id="fixed-heading" className="flex items-baseline justify-between gap-3 font-display text-xl font-semibold tracking-tight">
          What we fixed <span className="font-mono text-xs font-normal text-ink-3">{fixed.length}</span>
        </h2>
        {fixed.length ? (
          <ul className="mt-3 border border-rule bg-paper">
            {fixed.map((issue, i) => <IssueItem key={`${issue.check_id}-${i}`} issue={issue} open={open === i} onToggle={() => toggle(i)} wide={wide} />)}
          </ul>
        ) : <p className="mt-3 text-sm text-ink-2">No fix could be applied to this page automatically.</p>}
      </section>
      {pending.length > 0 && (
        <section aria-labelledby="pending-heading">
          <h2 id="pending-heading" className="flex items-baseline justify-between gap-3 font-display text-xl font-semibold tracking-tight">
            Still to do <span className="font-mono text-xs font-normal text-ink-3">{pending.length}</span>
          </h2>
          <p className="mt-1 text-xs text-ink-3">
            {readyCount
              ? `${readyCount} can be applied by us once approved; the rest need work outside the page, or facts from you.`
              : "These need work outside the page, or facts from you."}
          </p>
          {todoTop && <div className="mt-3">{todoTop}</div>}
          <ul className="mt-3 border border-rule bg-paper">
            {pending.map((issue, i) => (
              <IssueItem key={`${issue.check_id}-p${i}`} issue={issue} open={open === fixed.length + i} onToggle={() => toggle(fixed.length + i)}
                         wide={wide} showReady={showReady} />
            ))}
          </ul>
          {todoBottom && <div className="mt-4">{todoBottom}</div>}
        </section>
      )}
    </div>
  );
}
