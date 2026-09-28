"use client";

import { ArrowRight, CircleAlert, CodeXml, FileText, Hammer, Radar, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { CodeDiff, changeTypeLabel } from "@/components/workspace/code-diff";
import { ConfidenceLabel, SeverityLabel } from "@/components/workspace/status";
import { plural, urlPath } from "@/lib/format";
import type { FixType, IssueCard } from "@/lib/types";

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

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-rule pt-6">
      <h4 className="text-xs font-semibold tracking-wide text-ink-3">{title}</h4>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function IssueDetail({ issue }: { issue: IssueCard }) {
  const [changeIndex, setChangeIndex] = useState(0);
  const change = issue.changes[Math.min(changeIndex, issue.changes.length - 1)];
  const type = FIX_TYPES[issue.fix_type];
  return (
    <article aria-label={issue.title} className="min-w-0">
      <p className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <SeverityLabel severity={issue.severity} />
        <span className={`text-xs font-semibold ${issue.status === "fail" ? "text-red" : "text-amber"}`}>{issue.status === "fail" ? "Fails the check" : "Warning"}</span>
        <ConfidenceLabel confidence={issue.confidence} />
        <span className="font-mono text-2xs text-ink-3">{issue.check_id}</span>
      </p>
      <h3 className="mt-3 font-display text-3xl leading-snug font-semibold tracking-[-0.02em]">{issue.title}</h3>
      <p className="mt-2 text-sm text-ink-3">
        {issue.pages.length ? `Found on ${plural(issue.pages.length, "page")}` : "Site-wide"}
        {issue.pages.length > 0 && <span className="font-mono text-2xs">: {issue.pages.slice(0, 3).map(urlPath).join("  ")}{issue.pages.length > 3 ? ` +${issue.pages.length - 3}` : ""}</span>}
      </p>

      <div className="mt-7 space-y-7">
        {issue.impact && (
          <Block title="What's wrong and why it matters">
            <p className="max-w-[720px] text-md leading-relaxed text-ink">{issue.impact}</p>
          </Block>
        )}

        <Block title="Evidence">
          {issue.evidence.length ? (
            <ul className="space-y-2.5">
              {issue.evidence.slice(0, 5).map((e, i) => (
                <li key={i} className="border-l-[3px] border-rule-strong bg-mist/70 px-4 py-3">
                  {e.url && <span className="block font-mono text-2xs break-all text-signal">{urlPath(e.url)}</span>}
                  <span className="mt-0.5 block text-base leading-relaxed text-ink">{e.excerpt}</span>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-ink-3">The agent recorded no excerpt for this issue.</p>}
        </Block>

        <Block title="Proposed fix">
          <div className="flex flex-wrap items-start gap-3">
            <FixTypeBadge type={issue.fix_type} />
            <p className="text-xs text-ink-3">{type.note}</p>
          </div>
          <p className="mt-3 max-w-[720px] text-md leading-relaxed text-ink">{issue.fix}</p>
          {issue.missing_facts.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {issue.missing_facts.map((fact) => (
                <li key={fact} className="flex gap-2 text-sm text-ink"><span aria-hidden="true" className="mt-2 h-1.5 w-1.5 shrink-0 bg-amber" />{fact}</li>
              ))}
            </ul>
          )}
          {issue.verification && <p className="mt-3 text-sm text-ink-2"><span className="font-semibold text-ink">How to confirm it worked: </span>{issue.verification}</p>}
        </Block>

        {change && (
          <Block title={`Code change${issue.changes.length > 1 ? `s (${issue.changes.length})` : ""}`}>
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
          </Block>
        )}
      </div>
    </article>
  );
}

/** An agent's issues: a list on the left, and the chosen issue's evidence, fix and code change on the right. */
export function IssueList({ issues, emptyText = "This agent found no issues." }: { issues: IssueCard[]; emptyText?: string }) {
  const [selected, setSelected] = useState(issues[0]?.id);
  const issue = issues.find((i) => i.id === selected) ?? issues[0];
  if (!issue) return <p className="border border-rule bg-mist px-6 py-8 text-base text-ink-2">{emptyText}</p>;

  function choose(id: string) {
    setSelected(id);
    if (window.innerWidth < 1024) document.getElementById("issue-detail")?.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[320px_minmax(0,1fr)] lg:gap-12">
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
                <span className="mt-1.5 block text-sm leading-snug font-semibold">{i.title}</span>
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
