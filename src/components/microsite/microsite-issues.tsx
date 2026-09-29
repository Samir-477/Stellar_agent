"use client";

import { Check, ChevronDown, CircleDashed } from "lucide-react";
import { useState } from "react";
import { CodeDiff } from "@/components/workspace/code-diff";
import type { MicrositeIssue } from "@/lib/types";

function IssueItem({ issue, open, onToggle, wide }: { issue: MicrositeIssue; open: boolean; onToggle: () => void; wide: boolean }) {
  return (
    <li className="border-b border-rule last:border-b-0">
      <button type="button" onClick={onToggle} aria-expanded={open}
              className="grid w-full grid-cols-[22px_1fr_16px] gap-3 px-5 py-4 text-left transition-colors hover:bg-mist">
        {issue.fixed
          ? <span className="mt-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-signal text-white"><Check aria-hidden="true" size={12} strokeWidth={3} /></span>
          : <CircleDashed aria-hidden="true" size={20} className="mt-0.5 text-amber" />}
        <span>
          <span className="block text-sm leading-snug font-semibold">{issue.title}</span>
          <span className="mt-1 block text-2xs text-ink-3">Found by {issue.agent_name}</span>
        </span>
        <ChevronDown aria-hidden="true" size={16} className={`mt-1 text-ink-3 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="space-y-4 px-5 pb-6 pl-[54px] text-sm leading-relaxed">
          {issue.impact && <p><span className="font-semibold text-ink">Why it matters: </span><span className="text-ink-2">{issue.impact}</span></p>}
          <p><span className="font-semibold text-ink">{issue.fixed ? "What we changed: " : "What to do: "}</span><span className="text-ink-2">{issue.fix}</span></p>
          {issue.changes.map((change, i) => (
            <div key={i} className="space-y-2">
              <CodeDiff before={change.before} after={change.after} beforeSegments={change.before_segments}
                        afterSegments={change.after_segments} language={change.language} compact={!wide} />
              {change.note && <p className="text-xs text-ink-3">{change.note}</p>}
            </div>
          ))}
        </div>
      )}
    </li>
  );
}

/** The issues on this page: the ones fixed in this preview first, then the ones still to do. `wide` gives the
 *  code diffs full size, for a column wide enough to show before and after side by side. */
export function MicrositeIssues({ issues, wide = false }: { issues: MicrositeIssue[]; wide?: boolean }) {
  const fixed = issues.filter((i) => i.fixed);
  const pending = issues.filter((i) => !i.fixed);
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
          <p className="mt-1 text-xs text-ink-3">These need work outside the page, or facts from you.</p>
          <ul className="mt-3 border border-rule bg-paper">
            {pending.map((issue, i) => (
              <IssueItem key={`${issue.check_id}-p${i}`} issue={issue} open={open === fixed.length + i} onToggle={() => toggle(fixed.length + i)} wide={wide} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
