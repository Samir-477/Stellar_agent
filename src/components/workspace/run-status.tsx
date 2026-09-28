import type { RunStatus } from "@/lib/types";

const RUN: Record<RunStatus, { label: string; tone: string; dot: string }> = {
  queued: { label: "Queued", tone: "text-ink-2", dot: "bg-rule-strong" },
  running: { label: "Running", tone: "text-signal", dot: "bg-signal node-live" },
  awaiting_confirmation: { label: "Needs confirmation", tone: "text-amber", dot: "bg-amber" },
  completed: { label: "Finished", tone: "text-ink", dot: "bg-signal" },
  completed_partial: { label: "Finished, with gaps", tone: "text-amber", dot: "bg-amber" },
  failed: { label: "Failed", tone: "text-red", dot: "bg-red" },
  cancelled: { label: "Cancelled", tone: "text-ink-3", dot: "bg-ink-3" },
};

export function runStatusLabel(status: RunStatus): string {
  return RUN[status]?.label ?? status;
}

export function isFinished(status: RunStatus): boolean {
  return status === "completed" || status === "completed_partial" || status === "failed" || status === "cancelled";
}

export function RunStatusLabel({ status }: { status: RunStatus }) {
  const s = RUN[status] ?? RUN.queued;
  return (
    <span className={`inline-flex items-center gap-2 text-sm font-medium ${s.tone}`}>
      <span aria-hidden="true" className={`h-2 w-2 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}
