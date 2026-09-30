import { BookOpen, Lightbulb } from "lucide-react";
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

export function PlainExplanation({ plain, compact = false }: { plain: Plain; compact?: boolean }) {
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
        {plain.action && <Row label="What to do">{plain.action}</Row>}
      </dl>
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
