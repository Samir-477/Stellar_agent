"use client";

import { ExternalLink, Lock } from "lucide-react";
import { useState } from "react";

export type FrameView = "fixed" | "annotated" | "original";

const VIEW_COPY: Record<FrameView, { label: string; hint: string }> = {
  fixed: { label: "Fixed page", hint: "Every placed fix applied" },
  annotated: { label: "What changed", hint: "Each fix marked; click one to see it" },
  original: { label: "Before", hint: "The page as captured" },
};

/** A captured page in a sandboxed frame, with the fixed, marked and original versions one click apart. */
export function PreviewFrame({ views, pageUrl, initial = "fixed", height = "h-[78vh] min-h-[560px]" }: {
  views: Partial<Record<FrameView, string>>;
  pageUrl: string;
  initial?: FrameView;
  height?: string;
}) {
  const available = (["fixed", "annotated", "original"] as FrameView[]).filter((v) => views[v]);
  const [view, setView] = useState<FrameView>(available.includes(initial) ? initial : available[0]);
  const src = views[view];
  return (
    <div>
      <div role="tablist" aria-label="Page version" className="grid border border-rule" style={{ gridTemplateColumns: `repeat(${available.length}, minmax(0, 1fr))` }}>
        {available.map((v, i) => (
          <button key={v} role="tab" type="button" aria-selected={view === v} onClick={() => setView(v)}
                  className={`min-h-14 px-4 py-2 text-left transition-colors ${i ? "border-l border-rule" : ""} ${view === v ? "bg-ink text-white" : "hover:bg-mist"}`}>
            <span className="block text-sm font-semibold">{VIEW_COPY[v].label}</span>
            <span className={`hidden text-2xs sm:block ${view === v ? "text-white/75" : "text-ink-3"}`}>{VIEW_COPY[v].hint}</span>
          </button>
        ))}
      </div>
      <div className="mt-3 border border-rule bg-paper">
        <div className="flex items-center gap-3 border-b border-rule bg-mist px-3 py-2">
          <span aria-hidden="true" className="flex gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-rule-strong" /><span className="h-2.5 w-2.5 rounded-full bg-rule-strong" /><span className="h-2.5 w-2.5 rounded-full bg-rule-strong" /></span>
          <span className="flex min-w-0 flex-1 items-center gap-1.5 rounded-[3px] border border-rule bg-paper px-2.5 py-1">
            <Lock aria-hidden="true" size={12} className="shrink-0 text-ink-3" />
            <span className="truncate font-mono text-2xs text-ink-2">{pageUrl}</span>
          </span>
          {src && (
            <a href={src} target="_blank" rel="noreferrer noopener" className="inline-flex min-h-9 items-center gap-1 text-xs font-medium text-signal hover:underline">
              New tab <ExternalLink aria-hidden="true" size={12} />
            </a>
          )}
        </div>
        {src ? (
          <iframe key={src} src={src} title={`${VIEW_COPY[view].label}: ${pageUrl}`} sandbox="allow-scripts allow-popups"
                  referrerPolicy="no-referrer" loading="lazy" className={`block w-full bg-white ${height}`} />
        ) : <p className="px-5 py-10 text-base text-ink-3">This version isn&apos;t available.</p>}
      </div>
      <p className="mt-2 text-xs text-ink-3">Captured pages are frozen: booking engines, menus and other scripts don&apos;t run.</p>
    </div>
  );
}
