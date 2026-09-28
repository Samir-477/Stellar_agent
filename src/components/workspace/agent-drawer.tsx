"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { AgentReportView } from "@/components/workspace/agent-report";
import type { AgentReport } from "@/lib/types";

/** Loads one saved report; keyed by agent, so each opening starts from an empty state. */
function ReportLoader({ runId, agentId }: { runId: string; agentId: string }) {
  const [state, setState] = useState<{ report?: AgentReport; error?: string }>({});
  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/workspace/runs/${runId}/agents/${agentId}`, { signal: controller.signal })
      .then(async (response) => {
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "The report couldn't be loaded.");
        setState({ report: data });
      })
      .catch((e) => { if (e.name !== "AbortError") setState({ error: e.message }); });
    return () => controller.abort();
  }, [runId, agentId]);

  if (state.error) return <p role="alert" className="text-base text-red">{state.error}</p>;
  if (!state.report) return <p className="text-base text-ink-3">Loading the report…</p>;
  return <AgentReportView report={state.report} />;
}

/** A side sheet with one agent's saved report, opened from the live run while other agents keep working. */
export function AgentDrawer({ runId, agentId, onClose }: { runId: string; agentId: string | null; onClose: () => void }) {
  const reduce = useReducedMotion();
  const closeRef = useRef<HTMLButtonElement>(null);
  // Parents re-render on every progress poll; keep the latest close handler without re-running effects.
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; }, [onClose]);

  useEffect(() => {
    if (!agentId) return;
    const returnTo = document.activeElement as HTMLElement | null;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") close.current(); };
    window.addEventListener("keydown", onKey);
    const focus = setTimeout(() => closeRef.current?.focus(), 0);
    return () => {
      clearTimeout(focus);
      window.removeEventListener("keydown", onKey);
      returnTo?.focus();
    };
  }, [agentId]);

  return (
    <AnimatePresence>
      {agentId && (
        <div className="fixed inset-0 z-50">
          <motion.div className="absolute inset-0 bg-forest/40" onClick={onClose} aria-hidden="true"
                      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }} />
          <motion.div role="dialog" aria-modal="true" aria-label={`${agentId} report`}
                      className="absolute inset-y-0 right-0 flex w-full max-w-[880px] flex-col bg-paper shadow-[-30px_0_60px_-40px_rgba(7,27,18,0.5)]"
                      initial={reduce ? { opacity: 0 } : { x: 48, opacity: 0 }} animate={{ x: 0, opacity: 1 }}
                      exit={reduce ? { opacity: 0 } : { x: 32, opacity: 0 }} transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}>
            <div className="flex items-center justify-between border-b border-rule px-6 py-3">
              <p className="text-sm text-ink-2">Agent report, saved during this run</p>
              <button ref={closeRef} type="button" onClick={onClose} aria-label="Close report"
                      className="flex min-h-11 min-w-11 items-center justify-center rounded-[3px] text-ink-2 hover:bg-mist hover:text-ink">
                <X size={20} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-6 pt-6 pb-16">
              <ReportLoader key={agentId} runId={runId} agentId={agentId} />
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
