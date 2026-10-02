"use client";

import { Check, ClipboardCopy, Download, Sparkles } from "lucide-react";
import { useState } from "react";
import { OwnerChip } from "@/components/workspace/plain-explanation";
import { handoffFileName, handoffGroups, handoffMarkdown } from "@/lib/handoff";
import type { MicrositeIssue } from "@/lib/types";

// Workspace-only controls under "Still to do": approve the changes we prepared (applied in the preview, then
// shown to the client on the next publish), and hand the rest to the people who do them.

/** Approve every prepared change at once, with an inline confirmation (a bulk action shouldn't be one click). */
export function ApprovalBar({ issues, onApprove }: {
  issues: MicrositeIssue[];
  onApprove: (keys: string[]) => Promise<void>;
}) {
  const ready = issues.filter((i) => !i.fixed && (i.awaiting_approval?.length ?? 0) > 0);
  const keys = ready.flatMap((i) => i.awaiting_approval ?? []);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [applied, setApplied] = useState(0);

  async function approve() {
    setBusy(true);
    setError("");
    try {
      await onApprove(keys);
      setApplied(keys.length);
      setConfirming(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The changes couldn't be approved.");
    } finally {
      setBusy(false);
    }
  }

  if (!keys.length) {
    return applied ? (
      <p role="status" className="flex gap-2 rounded-[6px] border border-signal/30 bg-soft px-4 py-3 text-sm text-ink">
        <Check aria-hidden="true" size={16} className="mt-0.5 shrink-0 text-signal" />
        <span>Applied {applied} change{applied === 1 ? "" : "s"} to the preview; they&apos;re now under What we fixed.
          Republish the microsite below to show the client.</span>
      </p>
    ) : null;
  }
  const label = `${keys.length} change${keys.length === 1 ? "" : "s"}`;
  return (
    <div className="rounded-[6px] border border-signal/30 bg-soft px-4 py-3.5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex min-w-0 gap-2 text-sm text-ink">
          <Sparkles aria-hidden="true" size={16} className="mt-0.5 shrink-0 text-signal" />
          <span><span className="font-semibold">{label} ready to apply</span> for {ready.length} item{ready.length === 1 ? "" : "s"} below.
            {" "}They go into the preview first; the client sees them when you republish.</span>
        </p>
        {!confirming && (
          <button type="button" onClick={() => setConfirming(true)}
                  className="inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-[3px] bg-signal px-4 text-sm font-semibold text-white hover:bg-signal-deep">
            Approve all {keys.length}
          </button>
        )}
      </div>
      {confirming && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-signal/20 pt-3">
          <p className="text-sm text-ink-2">Apply {label} to the preview? You can review each one under Technical details first.</p>
          <div className="flex gap-2">
            <button type="button" onClick={() => setConfirming(false)} disabled={busy}
                    className="min-h-10 rounded-[3px] px-3 text-sm font-medium text-ink-2 hover:bg-paper">Cancel</button>
            <button type="button" onClick={approve} disabled={busy}
                    className="inline-flex min-h-10 items-center gap-1.5 rounded-[3px] bg-signal px-4 text-sm font-semibold text-white hover:bg-signal-deep disabled:opacity-60">
              {busy ? "Applying…" : `Apply ${label}`}
            </button>
          </div>
        </div>
      )}
      {error && <p role="alert" className="mt-2 text-sm font-medium text-red">{error}</p>}
    </div>
  );
}

/** What's left after approval, grouped by who does it, to copy or download as one hand-off document. */
export function HandoffPanel({ issues, client, pageUrl }: { issues: MicrositeIssue[]; client: string; pageUrl: string }) {
  const groups = handoffGroups(issues);
  const [copied, setCopied] = useState(false);
  if (!groups.length) return null;
  const text = () => handoffMarkdown(issues, { client, pageUrl, date: new Date().toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" }) });

  async function copy() {
    try {
      await navigator.clipboard.writeText(text());
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  function download() {
    const url = URL.createObjectURL(new Blob([text()], { type: "text/markdown;charset=utf-8" }));
    const link = Object.assign(document.createElement("a"), { href: url, download: handoffFileName(client, pageUrl) });
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section aria-labelledby="handoff-heading" className="rounded-[6px] border border-rule bg-mist px-4 py-4">
      <h3 id="handoff-heading" className="text-sm font-semibold text-ink">Hand off the rest</h3>
      <p className="mt-1 text-xs text-ink-3">Each item with its steps, pages, how to confirm it worked and any code, grouped by who does it.</p>
      <ul className="mt-3 flex flex-wrap gap-2">
        {groups.map((g) => (
          <li key={g.owner} className="inline-flex items-center gap-1.5">
            <OwnerChip owner={g.owner} /><span className="text-xs text-ink-2">{g.issues.length}</span>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" onClick={copy}
                className="inline-flex min-h-10 items-center gap-1.5 rounded-[3px] border border-rule-strong bg-paper px-3 text-sm font-semibold text-ink hover:border-ink-3">
          {copied ? <Check aria-hidden="true" size={14} className="text-signal" /> : <ClipboardCopy aria-hidden="true" size={14} />}
          {copied ? "Copied" : "Copy hand-off"}
        </button>
        <button type="button" onClick={download}
                className="inline-flex min-h-10 items-center gap-1.5 rounded-[3px] border border-rule-strong bg-paper px-3 text-sm font-semibold text-ink hover:border-ink-3">
          <Download aria-hidden="true" size={14} /> Download (.md)
        </button>
      </div>
    </section>
  );
}
