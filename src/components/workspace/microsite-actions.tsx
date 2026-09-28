"use client";

import { useRouter } from "next/navigation";
import { Check, Copy, EyeOff } from "lucide-react";
import { useState } from "react";

/** Copy a microsite's public link, or take it offline. */
export function MicrositeActions({ id, href, live }: { id: string; href: string; live: boolean }) {
  const router = useRouter();
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function copy() {
    try {
      await navigator.clipboard.writeText(new URL(href, window.location.origin).toString());
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setError("Copy failed.");
    }
  }

  async function unpublish() {
    if (!window.confirm("Take this microsite offline? Its link will stop working. You can publish the run again later.")) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/workspace/microsites/${id}/unpublish`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "It couldn't be unpublished.");
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "It couldn't be unpublished.");
      setBusy(false);
    }
  }

  return (
    <span className="flex items-center justify-end gap-1">
      {live && (
        <button type="button" onClick={copy} className="inline-flex min-h-9 items-center gap-1.5 rounded-[3px] px-2.5 text-xs font-medium text-ink-2 hover:bg-mist hover:text-ink">
          {copied ? <Check aria-hidden="true" size={13} className="text-signal" /> : <Copy aria-hidden="true" size={13} />} {copied ? "Copied" : "Copy link"}
        </button>
      )}
      {live && (
        <button type="button" onClick={unpublish} disabled={busy} className="inline-flex min-h-9 items-center gap-1.5 rounded-[3px] px-2.5 text-xs font-medium text-ink-2 hover:bg-red-bg hover:text-red disabled:opacity-60">
          <EyeOff aria-hidden="true" size={13} /> {busy ? "Unpublishing…" : "Unpublish"}
        </button>
      )}
      {error && <span role="alert" className="text-xs text-red">{error}</span>}
    </span>
  );
}
