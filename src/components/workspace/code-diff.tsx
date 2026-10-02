"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";
import type { Segment } from "@/lib/types";

const TYPE_LABEL: Record<string, string> = {
  text_replace: "Text rewrite", attribute_set: "Attribute change", element_insert: "New content", element_remove: "Removal",
  head_upsert: "Head tag", jsonld_upsert: "Structured data", file_patch: "Site file", header_recommendation: "HTTP header",
  link_insert: "New internal link", element_replace: "Rewrite",
};

export function changeTypeLabel(type: string): string {
  return TYPE_LABEL[type] ?? type;
}

function Runs({ segments, fallback, side }: { segments: Segment[]; fallback: string | null; side: "before" | "after" }) {
  if (!segments.length) return <>{fallback}</>;
  return (
    <>
      {segments.map((seg, i) =>
        seg.k === "eq" ? <span key={i}>{seg.t}</span>
          : <mark key={i} className={side === "before" ? "rounded-[2px] bg-[#f9d6d1] text-[#7c1d17] line-through decoration-[#c4473d]/60" : "rounded-[2px] bg-[#c9eed6] text-[#0b4a2a]"}>{seg.t}</mark>)}
    </>
  );
}

/** Before and after code for one change, with the exact words that changed highlighted. */
export function CodeDiff({ before, after, beforeSegments, afterSegments, language, compact = false }: {
  before: string | null;
  after: string | null;
  beforeSegments: Segment[];
  afterSegments: Segment[];
  language: "html" | "json" | "text";
  compact?: boolean;
}) {
  const [mode, setMode] = useState<"split" | "stacked">("split");
  const [copied, setCopied] = useState(false);
  const pre = `overflow-auto px-4 py-3.5 font-mono text-sm leading-[1.65] break-words whitespace-pre-wrap ${compact ? "max-h-56" : "max-h-80"}`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(after ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  const beforePane = (
    <div className="min-w-0">
      <p className="flex items-center gap-2 border-b border-rule bg-[#fdf1ef] px-4 py-2 text-2xs font-semibold text-red">
        <span aria-hidden="true" className="font-mono">−</span> Before, as captured
      </p>
      <pre className={`${pre} bg-paper text-ink-2`}>
        {before === null || before === "" ? <span className="font-sans text-xs text-ink-3 italic">Not on the page yet</span>
          : <Runs segments={beforeSegments} fallback={before} side="before" />}
      </pre>
    </div>
  );
  const afterPane = (
    <div className="min-w-0">
      <p className="flex items-center gap-2 border-b border-rule bg-soft px-4 py-2 text-2xs font-semibold text-signal">
        <span aria-hidden="true" className="font-mono">+</span> After the fix
      </p>
      <pre className={`${pre} bg-paper text-ink`}>
        {after === null || after === "" ? <span className="font-sans text-xs text-ink-3 italic">Removed</span>
          : <Runs segments={afterSegments} fallback={after} side="after" />}
      </pre>
    </div>
  );

  return (
    <div className="@container border border-rule bg-paper">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule bg-mist px-4 py-2">
        <span className="font-mono text-2xs text-ink-3 uppercase">{language}</span>
        <div className="flex items-center gap-1">
          <div role="group" aria-label="Layout" className="flex rounded-[3px] border border-rule bg-paper p-0.5">
            {([["split", "Side by side"], ["stacked", "Stacked"]] as const).map(([id, label]) => (
              <button key={id} type="button" aria-pressed={mode === id} onClick={() => setMode(id)}
                      className={`min-h-7 rounded-[2px] px-2.5 text-2xs font-semibold ${mode === id ? "bg-ink text-white" : "text-ink-2 hover:bg-mist"}`}>
                {label}
              </button>
            ))}
          </div>
          {after && (
            <button type="button" onClick={copy} className="inline-flex min-h-8 items-center gap-1.5 rounded-[3px] px-2.5 text-2xs font-semibold text-ink-2 hover:bg-paper hover:text-ink">
              {copied ? <Check aria-hidden="true" size={13} className="text-signal" /> : <Copy aria-hidden="true" size={13} />}
              {copied ? "Copied" : "Copy new code"}
            </button>
          )}
        </div>
      </div>
      <div className={mode === "split" ? "grid divide-y divide-rule @xl:grid-cols-2 @xl:divide-x @xl:divide-y-0" : "divide-y divide-rule"}>
        {beforePane}
        {afterPane}
      </div>
    </div>
  );
}
