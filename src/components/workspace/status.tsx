import { Check, CircleDashed, CircleQuestionMark, Minus, Pause, RotateCcw, TriangleAlert, X } from "lucide-react";
import type { CheckStatus, ComponentState, Confidence, Severity } from "@/lib/types";

// The status vocabulary. Every state is a word first; the glyph and colour only reinforce it.

const SEVERITY: Record<Severity, { label: string; level: number; tone: string }> = {
  critical: { label: "Critical", level: 4, tone: "text-red" },
  high: { label: "High", level: 3, tone: "text-red" },
  medium: { label: "Medium", level: 2, tone: "text-amber" },
  low: { label: "Low", level: 1, tone: "text-ink-2" },
  info: { label: "Info", level: 0, tone: "text-ink-3" },
};

/** Severity as an ordinal: four steps, filled up to the level, with the word beside it. */
export function SeverityLabel({ severity }: { severity: Severity | null | undefined }) {
  const s = SEVERITY[severity ?? "info"];
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${s.tone}`}>
      <span aria-hidden="true" className="flex items-end gap-[2px]">
        {[1, 2, 3, 4].map((step) => (
          <span key={step} className={`w-[3px] rounded-[1px] ${step <= s.level ? "bg-current" : "bg-rule-strong"}`}
                style={{ height: 4 + step * 2 }} />
        ))}
      </span>
      {s.label}
    </span>
  );
}

const CONFIDENCE: Record<Confidence, { label: string; glyph: string }> = {
  confirmed: { label: "Confirmed", glyph: "bg-ink" },
  likely: { label: "Likely", glyph: "bg-[linear-gradient(90deg,var(--color-ink)_50%,transparent_50%)]" },
  hypothesis: { label: "Hypothesis", glyph: "border border-dashed border-ink-2" },
};

/** The agent's own confidence rating, not an independent verification. */
export function ConfidenceLabel({ confidence }: { confidence: Confidence }) {
  const c = CONFIDENCE[confidence];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-ink-2" title="Confidence reported by the agent">
      <span aria-hidden="true" className={`h-2 w-2 rounded-full ring-1 ring-ink/70 ${c.glyph}`} />
      {c.label}
    </span>
  );
}

const CHECK: Record<CheckStatus, { label: string; tone: string; Icon: typeof Check }> = {
  pass: { label: "Pass", tone: "text-signal", Icon: Check },
  warn: { label: "Warning", tone: "text-amber", Icon: TriangleAlert },
  fail: { label: "Fail", tone: "text-red", Icon: X },
  unverifiable: { label: "Could not check", tone: "text-ink-3", Icon: CircleQuestionMark },
  not_applicable: { label: "Not applicable", tone: "text-ink-3", Icon: Minus },
};

export function CheckLabel({ status }: { status: CheckStatus }) {
  const c = CHECK[status] ?? CHECK.unverifiable;
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium ${c.tone}`}>
      <c.Icon aria-hidden="true" size={14} strokeWidth={2.2} />
      {c.label}
    </span>
  );
}

const STATE: Record<ComponentState, { label: string; tone: string }> = {
  waiting: { label: "Waiting", tone: "text-ink-3" },
  running: { label: "Working", tone: "text-signal" },
  done: { label: "Done", tone: "text-signal" },
  partial: { label: "Partly done", tone: "text-amber" },
  failed: { label: "Failed", tone: "text-red" },
  skipped: { label: "Skipped", tone: "text-ink-3" },
  reused: { label: "Reused", tone: "text-ink-2" },
  paused: { label: "Needs you", tone: "text-amber" },
};

export function stateLabel(state: ComponentState): string {
  return STATE[state]?.label ?? state;
}

/** A small glyph for a collector's or agent's state in the live run. */
export function StateGlyph({ state }: { state: ComponentState }) {
  const base = "flex h-5 w-5 shrink-0 items-center justify-center rounded-full";
  switch (state) {
    case "running":
      return <span aria-hidden="true" className={`${base} node-live bg-signal`}><span className="h-2 w-2 rounded-full bg-white" /></span>;
    case "done":
      return <span aria-hidden="true" className={`${base} bg-signal text-white`}><Check size={12} strokeWidth={3} /></span>;
    case "partial":
      return <span aria-hidden="true" className={`${base} bg-amber-bg text-amber ring-1 ring-amber/40`}><Check size={12} strokeWidth={3} /></span>;
    case "failed":
      return <span aria-hidden="true" className={`${base} bg-red-bg text-red ring-1 ring-red/40`}><X size={12} strokeWidth={3} /></span>;
    case "skipped":
      return <span aria-hidden="true" className={`${base} text-ink-3 ring-1 ring-rule-strong`}><Minus size={12} /></span>;
    case "reused":
      return <span aria-hidden="true" className={`${base} bg-mist text-ink-2 ring-1 ring-rule-strong`}><RotateCcw size={11} /></span>;
    case "paused":
      return <span aria-hidden="true" className={`${base} bg-amber-bg text-amber ring-1 ring-amber/40`}><Pause size={11} /></span>;
    default:
      return <span aria-hidden="true" className={`${base} text-rule-strong`}><CircleDashed size={18} strokeWidth={1.6} /></span>;
  }
}

export function StateText({ state }: { state: ComponentState }) {
  return <span className={`text-xs font-medium ${STATE[state]?.tone ?? "text-ink-3"}`}>{stateLabel(state)}</span>;
}
