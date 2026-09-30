"use client";

import { ArrowRight, ChevronRight, CircleAlert, CircleCheck, CodeXml, FileText, Hammer, Lightbulb, Radar, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { CodeDiff, changeTypeLabel } from "@/components/workspace/code-diff";
import { EFFORT_LABEL, OwnerChip, StepList, TermsUsed } from "@/components/workspace/plain-explanation";
import { ConfidenceLabel, SeverityLabel } from "@/components/workspace/status";
import { plural, urlPath } from "@/lib/format";
import type { FixType, IssueCard, PlainExplanation } from "@/lib/types";

export const FIX_TYPES: Record<FixType, { label: string; note: string; tone: string; Icon: typeof CodeXml }> = {
  code: { label: "Code change", note: "A change to the page's HTML, shown before and after.", tone: "border-signal/40 bg-soft text-signal", Icon: CodeXml },
  content: { label: "Content draft", note: "New text drafted by the agent from the site's own facts. Review it before publishing.", tone: "border-signal/40 bg-paper text-signal", Icon: FileText },
  facts: { label: "Needs your facts", note: "The fix needs information only the business can supply.", tone: "border-amber/40 bg-amber-bg text-amber", Icon: CircleAlert },
  action: { label: "Action plan", note: "Fixed outside the page's HTML: in the site's code, hosting, or other platforms.", tone: "border-rule-strong bg-mist text-ink-2", Icon: Hammer },
  observation: { label: "Observation", note: "A dated sample of search results or AI answers to monitor. It is not a defect on the page.", tone: "border-rule bg-paper text-ink-3", Icon: Radar },
};

export function FixTypeBadge({ type }: { type: FixType }) {
  const t = FIX_TYPES[type];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-[3px] border px-2 py-0.5 text-2xs font-semibold ${t.tone}`}>
      <t.Icon aria-hidden="true" size={12} /> {t.label}
    </span>
  );
}

// ------------------------------------------------------------------ plain brief
// For management and clients: the diagnosis, the business consequence, and the decision, each in its own block.

function BriefTitle({ children }: { children: React.ReactNode }) {
  return <h4 className="text-sm font-semibold text-ink-2">{children}</h4>;
}

function Happening({ plain }: { plain: PlainExplanation }) {
  return (
    <section className="rounded-[6px] border border-rule bg-paper px-5 py-4">
      <BriefTitle>What&apos;s happening</BriefTitle>
      <p className="mt-2 text-md leading-relaxed text-ink">{plain.meaning}</p>
      <div className="mt-4">
        <p className="text-xs font-semibold text-ink-3">On your site</p>
        <p className="mt-1.5 border-l-2 border-signal pl-3 text-base leading-relaxed text-ink break-words">{plain.site_case}</p>
        {plain.case_source === "rules" && <p className="mt-1 pl-3.5 text-2xs text-ink-3">Taken directly from the evidence.</p>}
      </div>
    </section>
  );
}

function WhyItMatters({ plain }: { plain: PlainExplanation }) {
  return (
    <section className="flex flex-col rounded-[6px] bg-mist px-5 py-4 ring-1 ring-rule ring-inset">
      <BriefTitle>Why it matters</BriefTitle>
      {plain.why && <p className="mt-2 text-md leading-relaxed text-ink">{plain.why}</p>}
      {plain.analogy && (
        <div className={`${plain.why ? "mt-4" : "mt-2"} flex gap-3 rounded-[4px] bg-amber-bg/70 px-3.5 py-3`}>
          <Lightbulb aria-hidden="true" size={16} className="mt-0.5 shrink-0 text-amber" />
          <p className="text-base leading-relaxed text-ink">
            <span className="block text-xs font-semibold text-amber">Think of it like</span>
            {plain.analogy}
          </p>
        </div>
      )}
    </section>
  );
}

function WhatToDo({ issue, plain }: { issue: IssueCard; plain: PlainExplanation }) {
  return (
    <section className="relative overflow-hidden rounded-[6px] border border-signal/25 bg-soft px-5 py-4 pl-6">
      <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[3px] bg-signal" />
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <BriefTitle>What to do</BriefTitle>
        <span className="flex flex-wrap items-center gap-2">
          <FixTypeBadge type={issue.fix_type} />
          {plain.owner && <OwnerChip owner={plain.owner} />}
          {issue.effort && <span className="rounded-[3px] border border-rule-strong bg-paper px-2 py-0.5 text-2xs font-semibold text-ink-2">{EFFORT_LABEL[issue.effort]}</span>}
        </span>
      </div>
      <p className="mt-2 text-lg leading-relaxed font-medium text-ink">{plain.action || issue.fix}</p>
      {plain.steps && plain.steps.length > 0 && <div className="mt-3"><StepList steps={plain.steps} /></div>}
      {issue.missing_facts.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-amber">We need from you</p>
          <ul className="mt-1.5 grid gap-x-6 gap-y-1 sm:grid-cols-2">
            {issue.missing_facts.map((fact) => (
              <li key={fact} className="flex gap-2 text-sm text-ink"><span aria-hidden="true" className="mt-2 h-1.5 w-1.5 shrink-0 bg-amber" />{fact}</li>
            ))}
          </ul>
        </div>
      )}
      {issue.verification && (
        <p className="mt-3 flex gap-2 border-t border-signal/15 pt-3 text-sm text-ink-2">
          <CircleCheck aria-hidden="true" size={15} className="mt-0.5 shrink-0 text-signal" />
          <span><span className="font-semibold text-ink">Done when: </span>{issue.verification}</span>
        </p>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ technical details
// For the team making the fix: the proof beside the exact fix, then the code change across the full width.

function TechPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="min-w-0 rounded-[6px] border border-rule bg-paper px-5 py-4">
      <h4 className="text-sm font-semibold text-ink-2">{title}</h4>
      <div className="mt-2.5">{children}</div>
    </section>
  );
}

function Technical({ issue, withBrief }: { issue: IssueCard; withBrief: boolean }) {
  const [changeIndex, setChangeIndex] = useState(0);
  const change = issue.changes[Math.min(changeIndex, issue.changes.length - 1)];
  const type = FIX_TYPES[issue.fix_type];
  return (
    <div className="mt-4 space-y-4">
      <div className="grid gap-4 @3xl:grid-cols-2">
        <TechPanel title="Evidence">
          {issue.impact && <p className="mb-3 text-base leading-relaxed text-ink-2">{issue.impact}</p>}
          {issue.evidence.length ? (
            <ul className="space-y-2">
              {issue.evidence.slice(0, 5).map((e, i) => (
                <li key={i} className="border-l-[3px] border-rule-strong bg-mist px-3.5 py-2.5">
                  {e.url && <span className="block font-mono text-2xs break-all text-signal">{urlPath(e.url)}</span>}
                  <span className="mt-0.5 block text-base leading-relaxed break-words text-ink">{e.excerpt}</span>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-ink-3">The agent recorded no excerpt for this issue.</p>}
        </TechPanel>

        <TechPanel title="Exact fix">
          <div className="flex flex-wrap items-start gap-x-3 gap-y-1.5">
            <FixTypeBadge type={issue.fix_type} />
            <p className="text-xs text-ink-3">{type.note}</p>
          </div>
          <p className="mt-3 text-md leading-relaxed text-ink">{issue.fix}</p>
          {/* Without the plain brief, the facts and the check live here instead of in "What to do". */}
          {!withBrief && issue.missing_facts.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {issue.missing_facts.map((fact) => (
                <li key={fact} className="flex gap-2 text-sm text-ink"><span aria-hidden="true" className="mt-2 h-1.5 w-1.5 shrink-0 bg-amber" />{fact}</li>
              ))}
            </ul>
          )}
          {!withBrief && issue.verification && (
            <p className="mt-3 flex gap-2 text-sm text-ink-2">
              <CircleCheck aria-hidden="true" size={15} className="mt-0.5 shrink-0 text-signal" />
              <span><span className="font-semibold text-ink">Done when: </span>{issue.verification}</span>
            </p>
          )}
        </TechPanel>
      </div>

      {change && (
        <TechPanel title={`Code change${issue.changes.length > 1 ? `s (${issue.changes.length})` : ""}`}>
          {issue.changes.length > 1 && (
            <div className="mb-4 flex flex-wrap gap-2">
              {issue.changes.map((c, i) => (
                <button key={c.key} type="button" aria-pressed={i === changeIndex} onClick={() => setChangeIndex(i)}
                        className={`min-h-9 max-w-[280px] truncate rounded-[3px] border px-3 text-xs ${i === changeIndex ? "border-ink bg-ink text-white" : "border-rule text-ink-2 hover:bg-mist"}`}
                        title={c.page_url ?? "Site files"}>
                  <span className="font-mono">{c.page_url ? urlPath(c.page_url) : "Site files"}</span> · {changeTypeLabel(c.type)}
                </button>
              ))}
            </div>
          )}
          <p className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-3">
            <span className="font-mono text-ink-2">{change.page_url ? urlPath(change.page_url) : "Site files"}</span>
            <span>{changeTypeLabel(change.type)}</span>
            {change.placed === false && (
              <span className="inline-flex items-center gap-1 font-medium text-amber"><TriangleAlert aria-hidden="true" size={12} /> Not placed: {change.reason}</span>
            )}
          </p>
          <CodeDiff before={change.before} after={change.after} beforeSegments={change.before_segments}
                    afterSegments={change.after_segments} language={change.language} />
          {(change.rationale || change.note) && (
            <p className="mt-3 text-sm leading-relaxed text-ink-2">{change.rationale || change.note}</p>
          )}
        </TechPanel>
      )}

      {issue.plain && issue.plain.terms.length > 0 && (
        <div className="border-t border-rule pt-4">
          <p className="mb-2.5 text-xs font-semibold text-ink-3">Terms used above</p>
          <TermsUsed terms={issue.plain.terms} />
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ one issue

function IssueDetail({ issue }: { issue: IssueCard }) {
  const plain = issue.plain;
  return (
    <article aria-label={plain?.problem ?? issue.title} className="@container min-w-0">
      <p className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <SeverityLabel severity={issue.severity} />
        <span className={`text-xs font-semibold ${issue.status === "fail" ? "text-red" : "text-amber"}`}>{issue.status === "fail" ? "Fails the check" : "Warning"}</span>
        <ConfidenceLabel confidence={issue.confidence} />
        {!plain && <FixTypeBadge type={issue.fix_type} />}
      </p>
      <h3 className="mt-2.5 font-display text-3xl leading-snug font-semibold tracking-[-0.02em]">{plain?.problem ?? issue.title}</h3>
      <p className="mt-1.5 flex flex-wrap items-baseline gap-x-5 gap-y-1 text-sm text-ink-3">
        {plain && <span><span className="font-mono text-2xs text-signal">{issue.check_id}</span> {issue.title}</span>}
        <span>
          {issue.pages.length ? plural(issue.pages.length, "page") : "Site-wide"}
          {issue.pages.length > 0 && <span className="font-mono text-2xs">: {issue.pages.slice(0, 3).map(urlPath).join("  ")}{issue.pages.length > 3 ? ` +${issue.pages.length - 3}` : ""}</span>}
        </span>
      </p>

      {plain && (
        <div className="mt-5 space-y-4">
          <div className="grid gap-4 @2xl:grid-cols-2">
            <Happening plain={plain} />
            {(plain.why || plain.analogy) && <WhyItMatters plain={plain} />}
          </div>
          <WhatToDo issue={issue} plain={plain} />
        </div>
      )}

      <details className="group mt-5 border-t border-rule pt-4 [&_summary::-webkit-details-marker]:hidden" open={!plain}>
        <summary className="flex min-h-9 cursor-pointer flex-wrap items-center gap-x-2 gap-y-1 text-sm font-semibold text-ink">
          <ChevronRight aria-hidden="true" size={16} className="text-ink-3 transition-transform group-open:rotate-90" />
          Technical details
          <span className="text-xs font-normal text-ink-3">evidence and the exact fix{issue.changes.length ? ", with the code change" : ""}, for the team making it</span>
        </summary>
        <Technical issue={issue} withBrief={!!plain} />
      </details>
    </article>
  );
}

/** An agent's issues: a list on the left, and the chosen issue's plain brief and technical details on the right. */
export function IssueList({ issues, emptyText = "This agent found no issues." }: { issues: IssueCard[]; emptyText?: string }) {
  const [selected, setSelected] = useState(issues[0]?.id);
  const issue = issues.find((i) => i.id === selected) ?? issues[0];
  if (!issue) return <p className="border border-rule bg-mist px-6 py-8 text-base text-ink-2">{emptyText}</p>;

  function choose(id: string) {
    setSelected(id);
    if (window.innerWidth < 1024) document.getElementById("issue-detail")?.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[300px_minmax(0,1fr)] lg:gap-10">
      <ul aria-label="Issues" className="self-start border border-rule lg:sticky lg:top-[152px] lg:max-h-[calc(100vh-170px)] lg:overflow-y-auto">
        {issues.map((i) => {
          const active = i.id === issue.id;
          return (
            <li key={i.id} className="border-b border-rule last:border-b-0">
              <button type="button" onClick={() => choose(i.id)} aria-current={active ? "true" : undefined}
                      className={`relative block w-full px-5 py-4 text-left transition-colors ${active ? "bg-soft" : "hover:bg-mist"}`}>
                {active && <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[3px] bg-signal" />}
                <span className="flex items-center justify-between gap-3">
                  <SeverityLabel severity={i.severity} />
                  <span className="text-2xs text-ink-3">{i.pages.length ? plural(i.pages.length, "page") : "Site-wide"}</span>
                </span>
                <span className="mt-1.5 block text-sm leading-snug font-semibold">{i.plain?.problem ?? i.title}</span>
                <span className="mt-2 flex items-center justify-between gap-2">
                  <FixTypeBadge type={i.fix_type} />
                  {active && <ArrowRight aria-hidden="true" size={14} className="hidden text-signal lg:block" />}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <div id="issue-detail" className="scroll-mt-40">
        <IssueDetail key={issue.id} issue={issue} />
      </div>
    </div>
  );
}
