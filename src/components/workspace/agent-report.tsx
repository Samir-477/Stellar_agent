"use client";

import { Check, Minus, X } from "lucide-react";
import { useState } from "react";
import { AgentIcon } from "@/components/workspace/icons";
import { IssueList } from "@/components/workspace/issue-list";
import { CheckLabel } from "@/components/workspace/status";
import { urlPath } from "@/lib/format";
import type { AgentReport, IssueCard, ReportIssue } from "@/lib/types";

// One agent's own findings, with no cross-agent synthesis: what it is responsible for, its verdict,
// each issue with evidence, proposed fix and before/after code, what it collected, and what passed.

const SCORE_PARTS = [
  { key: "pass", label: "pass", className: "bg-signal" },
  { key: "warn", label: "warnings", className: "bg-[#d9a13b]" },
  { key: "fail", label: "fail", className: "bg-red" },
  { key: "unverifiable", label: "could not check", className: "bg-[repeating-linear-gradient(135deg,#c9d6ce_0_3px,#eef3f0_3px_6px)]" },
  { key: "not_applicable", label: "not applicable", className: "bg-rule" },
] as const;

export function Scorecard({ scorecard, compact = false }: { scorecard: AgentReport["scorecard"]; compact?: boolean }) {
  const total = SCORE_PARTS.reduce((sum, p) => sum + (scorecard[p.key] ?? 0), 0) || 1;
  const text = SCORE_PARTS.filter((p) => scorecard[p.key]).map((p) => `${scorecard[p.key]} ${p.label}`).join(", ");
  return (
    <div>
      <div className={`flex overflow-hidden rounded-[2px] ${compact ? "h-1.5" : "h-2.5"}`} role="img" aria-label={`Checks: ${text}`}>
        {SCORE_PARTS.map((p) => (scorecard[p.key] ? <span key={p.key} className={p.className} style={{ width: `${(100 * scorecard[p.key]) / total}%` }} /> : null))}
      </div>
      {!compact && <p className="mt-2 text-sm text-ink-2">{text}</p>}
    </div>
  );
}

const LABELS: Record<string, string> = {
  llm_reviewed_pages: "Pages reviewed by the model", html_pages: "HTML pages", pages_measured: "Pages measured",
  category_answers: "Category answers", observed_questions: "Observed questions",
  wrong_claims_overturned_by_second_opinion: "Wrong claims overturned on a second opinion",
};

function humanize(key: string): string {
  if (LABELS[key]) return LABELS[key];
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function Cell({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") return <span className="text-ink-3">None</span>;
  if (typeof value === "boolean" || value === "yes" || value === "no" || value === "Yes" || value === "No") {
    const yes = value === true || String(value).toLowerCase() === "yes";
    return (
      <span className={`inline-flex items-center gap-1 ${yes ? "text-signal" : "text-ink-2"}`}>
        {yes ? <Check aria-hidden="true" size={13} strokeWidth={2.6} /> : <X aria-hidden="true" size={13} strokeWidth={2.6} />}
        {yes ? "Yes" : "No"}
      </span>
    );
  }
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  if (/^https?:\/\//.test(text)) {
    return <span className="font-mono text-2xs [overflow-wrap:anywhere] text-ink" title={text}>{urlPath(text)}</span>;
  }
  return <span>{text}</span>;
}

/** The agent's signature table, exactly as the agent built it; cells are typed for reading, not reshaped. */
export function SignatureTable({ table }: { table: NonNullable<AgentReport["scope_and_evidence"]["signature_table"]> }) {
  if (!table.rows.length) return <p className="text-sm text-ink-3">The agent had no rows to tabulate in this run.</p>;
  return (
    <div className="max-h-[520px] overflow-auto border border-rule" tabIndex={0} role="region" aria-label="Signature table">
      <table className="w-full min-w-[640px] border-collapse text-left text-sm">
        <thead className="sticky top-0 z-10 bg-mist">
          <tr>
            {table.columns.map((column, index) => (
              <th key={column} scope="col" className={`border-b border-rule px-3 py-2.5 font-semibold whitespace-nowrap text-ink-2 ${index === 0 ? "sticky left-0 bg-mist" : ""}`}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, r) => (
            <tr key={r} className="align-top even:bg-mist/40">
              {row.map((value, c) => (
                <td key={c} className={`max-w-[360px] border-b border-rule px-3 py-2.5 leading-snug ${c === 0 ? "sticky left-0 min-w-[190px] bg-paper font-medium" : ""}`}>
                  <Cell value={value} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="mt-12 first:mt-0">
      <h3 className="flex items-baseline gap-2 font-display text-xl font-semibold tracking-tight">
        {title}
        {count !== undefined && <span className="font-mono text-2xs font-normal text-ink-3">{count}</span>}
      </h3>
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** Without the issues endpoint (a report opened mid-run), build plain cards from the report itself. */
function cardsFromReport(report: AgentReport): IssueCard[] {
  const patches = new Map(report.proposed_changes.map((p) => [p.key, p]));
  const toCard = (issue: ReportIssue, status: "fail" | "warn", index: number): IssueCard => {
    const changes = (issue.patch_keys ?? []).flatMap((key) => {
      const p = patches.get(key);
      return p ? [{
        key, type: p.type, page_url: p.page_url, rationale: p.rationale, note: p.client_visible_note ?? "",
        confidence: p.confidence, language: (p.type === "jsonld_upsert" ? "json" : "html") as "html" | "json",
        before: p.before, after: p.after, before_segments: [], after_segments: [], placed: null, reason: null,
      }] : [];
    });
    return {
      id: `${report.agent_id}:${issue.check_id}:${status}:${index}`, agent_id: report.agent_id, agent_name: report.agent_name,
      pillar: null, check_id: issue.check_id, status, severity: issue.severity, confidence: issue.confidence,
      title: issue.title, impact: issue.impact ?? "", fix: issue.fix ?? "", verification: issue.verification ?? "",
      effort: (issue.effort as IssueCard["effort"]) ?? null, pages: issue.pages, evidence: issue.evidence, missing_facts: [],
      fix_type: changes.length ? "code" : "action", changes,
    };
  };
  return [...report.issues_to_fix.map((i, n) => toCard(i, "fail", n)), ...report.needs_attention.map((i, n) => toCard(i, "warn", n))];
}

export function AgentReportView({ report, question, issues }: { report: AgentReport; question?: string; issues?: IssueCard[] }) {
  const cards = issues ?? cardsFromReport(report);
  const [section, setSection] = useState<"issues" | "collected" | "passed">("issues");
  const scope = report.scope_and_evidence;
  const examined = scope.coverage.examined;
  const withCode = cards.filter((c) => c.changes.length).length;
  return (
    <article>
      <header className="grid gap-8 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:items-end">
        <div className="flex items-start gap-4">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[4px] bg-soft text-signal"><AgentIcon id={report.agent_id} size={20} /></span>
          <div>
            <p className="font-mono text-2xs text-signal">{report.agent_id}</p>
            <h2 className="font-display text-4xl leading-tight font-semibold tracking-[-0.02em]">{report.agent_name}</h2>
            {question && <p className="mt-2 text-base text-ink-2"><span className="font-semibold text-ink">Responsible for: </span>{question}</p>}
          </div>
        </div>
        <div className="border border-rule bg-mist px-5 py-4">
          <p className="text-base leading-relaxed text-ink">{report.verdict}</p>
          <div className="mt-3"><Scorecard scorecard={report.scorecard} /></div>
        </div>
      </header>

      <div role="tablist" aria-label="Report sections" className="mt-10 flex flex-wrap gap-2 border-b border-rule pb-3">
        {([
          ["issues", `Issues ${cards.length}`, withCode ? `${withCode} with code changes` : ""],
          ["collected", "What it collected", ""],
          ["passed", `Passed checks ${report.whats_working.length}`, ""],
        ] as const).map(([id, label, hint]) => (
          <button key={id} type="button" role="tab" aria-selected={section === id} onClick={() => setSection(id)}
                  className={`min-h-11 rounded-[3px] px-4 text-sm font-semibold ${section === id ? "bg-ink text-white" : "border border-rule text-ink-2 hover:bg-mist"}`}>
            {label}{hint && <span className={`ml-2 text-2xs font-normal ${section === id ? "text-white/75" : "text-ink-3"}`}>{hint}</span>}
          </button>
        ))}
      </div>

      <div className="mt-8">
        {section === "issues" && <IssueList issues={cards} emptyText="This agent found no issues. Its passed checks are listed under Passed checks." />}

        {section === "collected" && <>
          <Section title="What it examined">
            {examined && typeof examined === "object" ? (
              <dl className="flex flex-wrap border-t border-l border-rule">
                {Object.entries(examined).map(([key, value]) => (
                  <div key={key} className="min-w-[160px] flex-1 border-r border-b border-rule px-5 py-4">
                    <dt className="text-xs text-ink-3">{humanize(key)}</dt>
                    <dd className="mt-0.5 font-display text-2xl font-semibold">{String(value)}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="text-base text-ink-2">{String(examined ?? "Not recorded")}</p>
            )}
            {scope.coverage.limits.length > 0 && (
              <ul className="mt-3 space-y-1.5">
                {scope.coverage.limits.map((limit) => (
                  <li key={limit} className="flex gap-2 text-sm text-ink-2"><Minus aria-hidden="true" size={14} className="mt-1 shrink-0 text-ink-3" />{limit}</li>
                ))}
              </ul>
            )}
          </Section>
          {scope.signature_table && (
            <Section title="Its evidence table">
              <SignatureTable table={scope.signature_table} />
            </Section>
          )}
          {report.missing_facts_and_next_checks.length > 0 && (
            <Section title="Facts to supply and next checks" count={report.missing_facts_and_next_checks.length}>
              <ul className="space-y-2">
                {report.missing_facts_and_next_checks.map((item) => (
                  <li key={item} className="flex gap-2.5 text-base"><span aria-hidden="true" className="mt-1.5 h-3 w-3 shrink-0 rounded-[2px] border border-ink-3" />{item}</li>
                ))}
              </ul>
            </Section>
          )}
        </>}

        {section === "passed" && (
          report.whats_working.length ? (
            <ul className="grid gap-x-8 sm:grid-cols-2">
              {report.whats_working.map((w) => (
                <li key={w.check_id} className="flex gap-3 border-b border-rule py-3 text-base">
                  <CheckLabel status="pass" />
                  <span><span className="mr-1.5 font-mono text-2xs text-ink-3">{w.check_id}</span>{w.title}</span>
                </li>
              ))}
            </ul>
          ) : <p className="text-base text-ink-2">No notable passes recorded.</p>
        )}
      </div>
    </article>
  );
}
