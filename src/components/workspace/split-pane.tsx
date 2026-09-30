"use client";

import { GripVertical } from "lucide-react";
import { useId, useRef, useState, useSyncExternalStore } from "react";

// Two panes side by side with a draggable divider (desktop only; they stack below 1024px). The chosen width is a
// per-viewer convenience kept in localStorage, so it survives reloads and works without it.

const MIN = 30; // % of the row the left pane can shrink to
const MAX = 75;
const RIGHT_MIN_PX = 300; // the right pane never gets narrower than this
const HANDLE_PX = 32;

const listeners = new Set<() => void>();
const subscribe = (cb: () => void) => { listeners.add(cb); return () => { listeners.delete(cb); }; };

function readStored(key: string): number | null {
  try {
    const v = Number(localStorage.getItem(key));
    return v >= MIN && v <= MAX ? v : null;
  } catch { return null; }
}

function store(key: string, value: number | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, String(Math.round(value * 10) / 10));
  } catch { /* storage blocked: the width just isn't remembered */ }
  listeners.forEach((l) => l());
}

export function SplitPane({ left, right, storageKey, initial = 48, label = "Resize the panes" }: {
  left: React.ReactNode; right: React.ReactNode; storageKey: string; initial?: number; label?: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const leftId = useId();
  const stored = useSyncExternalStore(subscribe, () => readStored(storageKey), () => null);
  const [drag, setDrag] = useState<number | null>(null);
  const pct = drag ?? stored ?? initial;

  function clamp(value: number) {
    const width = box.current?.getBoundingClientRect().width ?? 0;
    const max = width ? Math.min(MAX, ((width - RIGHT_MIN_PX - HANDLE_PX) / width) * 100) : MAX;
    return Math.min(Math.max(value, MIN), Math.max(max, MIN));
  }

  function fromPointer(clientX: number) {
    const rect = box.current?.getBoundingClientRect();
    return rect ? clamp(((clientX - rect.left - HANDLE_PX / 2) / rect.width) * 100) : pct;
  }

  function onKeyDown(e: React.KeyboardEvent) {
    const step = e.shiftKey ? 10 : 2;
    const next = e.key === "ArrowLeft" ? pct - step : e.key === "ArrowRight" ? pct + step
      : e.key === "Home" ? MIN : e.key === "End" ? MAX : null;
    if (next === null) return;
    e.preventDefault();
    store(storageKey, clamp(next));
  }

  return (
    <div ref={box} style={{ "--split": `${pct}%` } as React.CSSProperties}
         className={`grid gap-8 lg:grid-cols-[minmax(0,var(--split))_32px_minmax(0,1fr)] lg:gap-0 ${drag !== null ? "cursor-col-resize select-none [&_iframe]:pointer-events-none" : ""}`}>
      <div id={leftId} className="min-w-0">{left}</div>
      <div role="separator" aria-orientation="vertical" aria-controls={leftId} aria-label={label}
           aria-valuemin={MIN} aria-valuemax={MAX} aria-valuenow={Math.round(pct)} tabIndex={0}
           title="Drag to resize. Double-click to reset."
           onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); setDrag(fromPointer(e.clientX)); }}
           onPointerMove={(e) => { if (drag !== null) setDrag(fromPointer(e.clientX)); }}
           onPointerUp={() => { if (drag !== null) store(storageKey, drag); setDrag(null); }}
           onPointerCancel={() => setDrag(null)}
           onDoubleClick={() => store(storageKey, null)}
           onKeyDown={onKeyDown}
           className="group relative hidden cursor-col-resize touch-none outline-none lg:block">
        <span aria-hidden="true" className={`absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors ${drag !== null ? "bg-signal" : "bg-rule group-hover:bg-signal/60"}`} />
        <span aria-hidden="true"
              className={`sticky top-[45vh] mx-auto flex h-12 w-5 items-center justify-center rounded-[4px] border bg-paper shadow-sm transition-colors group-focus-visible:ring-2 group-focus-visible:ring-signal ${drag !== null ? "border-signal text-signal" : "border-rule-strong text-ink-3 group-hover:border-signal/60 group-hover:text-signal"}`}>
          <GripVertical size={14} />
        </span>
      </div>
      <div className="min-w-0">{right}</div>
    </div>
  );
}
