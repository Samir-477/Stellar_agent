import { BookOpen, CircleCheck, Lightbulb, UserRound } from "lucide-react";
import type { PlainExplanation as Plain, PlainTerm } from "@/lib/types";

// The plain-words view of an issue, for management and clients: what it means, why it matters, an everyday
// comparison, what was found on this site, and what to do. The technical detail sits below it, closed.

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 @md:grid-cols-[150px_minmax(0,1fr)] @md:gap-5">
      <dt className="text-xs font-semibold text-ink-3 @md:pt-0.5">{label}</dt>
      <dd className="text-base leading-relaxed text-ink">{children}</dd>
    </div>
  );
}

export function PlainExplanation({ plain, compact = false, hideAction = false }: {
  plain: Plain; compact?: boolean; hideAction?: boolean; // hideAction: a FixPlan below says what to do
}) {
  return (
    <section aria-label="In plain words" className={`@container rounded-[6px] border border-signal/20 bg-soft/40 ${compact ? "px-4 py-4" : "px-6 py-5"}`}>
      <p className="flex items-center gap-2 text-xs font-semibold text-signal"><BookOpen aria-hidden="true" size={14} /> In plain words</p>
      <dl className={`mt-3 ${compact ? "space-y-3" : "space-y-3.5"}`}>
        <Row label="What this means">{plain.meaning}</Row>
        {plain.why && <Row label="Why it matters">{plain.why}</Row>}
        {plain.analogy && (
          <Row label="Think of it like">
            <span className="inline-flex gap-2"><Lightbulb aria-hidden="true" size={16} className="mt-1 shrink-0 text-amber" />{plain.analogy}</span>
          </Row>
        )}
        <Row label="On your site">
          {plain.site_case}
          {plain.case_source === "rules" && <span className="mt-0.5 block text-2xs text-ink-3">Taken directly from the evidence below.</span>}
        </Row>
        {plain.action && !hideAction && <Row label="What to do">{plain.action}</Row>}
      </dl>
    </section>
  );
}

export const EFFORT_LABEL = { S: "Small job", M: "Medium job", L: "Large job" } as const;

/** Who does the fix, as a small chip. */
export function OwnerChip({ owner }: { owner: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-[3px] border border-rule-strong bg-paper px-2 py-0.5 text-2xs font-semibold text-ink-2">
      <UserRound aria-hidden="true" size={11} /> {owner}
    </span>
  );
}

/** The steps to fix an issue, in order. */
export function StepList({ steps }: { steps: string[] }) {
  return (
    <ol className="space-y-2">
      {steps.map((step, i) => (
        <li key={i} className="grid grid-cols-[22px_minmax(0,1fr)] gap-2.5 text-base leading-relaxed text-ink">
          <span aria-hidden="true" className="mt-0.5 flex h-[22px] w-[22px] items-center justify-center rounded-full bg-signal text-2xs font-semibold text-white">{i + 1}</span>
          <span className="break-words">{step}</span>
        </li>
      ))}
    </ol>
  );
}

/** How to fix an issue that is still open: the aim, the steps, who does them and how to know it worked. */
export function FixPlan({ action, steps, owner, effort, verification }: {
  action?: string; steps: string[]; owner?: string; effort?: "S" | "M" | "L" | null; verification?: string;
}) {
  return (
    <section aria-label="How to fix it" className="relative overflow-hidden rounded-[6px] border border-signal/25 bg-soft px-5 py-4 pl-6">
      <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[3px] bg-signal" />
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <p className="text-sm font-semibold text-ink">How to fix it</p>
        <span className="flex flex-wrap gap-2">
          {owner && <OwnerChip owner={owner} />}
          {effort && <span className="rounded-[3px] border border-rule-strong bg-paper px-2 py-0.5 text-2xs font-semibold text-ink-2">{EFFORT_LABEL[effort]}</span>}
        </span>
      </div>
      {action && <p className="mt-2 text-base leading-relaxed font-medium text-ink">{action}</p>}
      {steps.length > 0 && <div className="mt-3"><StepList steps={steps} /></div>}
      {verification && (
        <p className="mt-3 flex gap-2 border-t border-signal/15 pt-3 text-sm text-ink-2">
          <CircleCheck aria-hidden="true" size={15} className="mt-0.5 shrink-0 text-signal" />
          <span><span className="font-semibold text-ink">Done when: </span>{verification}</span>
        </p>
      )}
    </section>
  );
}

/** The technical terms an issue uses, each explained in a line. */
export function TermsUsed({ terms }: { terms: PlainTerm[] }) {
  if (!terms.length) return null;
  return (
    <div className="@container"><dl className="grid gap-x-8 gap-y-2.5 @lg:grid-cols-2">
      {terms.map((t) => (
        <div key={t.term} className="text-sm leading-snug">
          <dt className="inline font-semibold text-ink">{t.term}: </dt>
          <dd className="inline text-ink-2">{t.meaning}</dd>
        </div>
      ))}
    </dl></div>
  );
}
