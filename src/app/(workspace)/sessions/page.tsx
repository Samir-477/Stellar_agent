import type { Metadata } from "next";
import Link from "next/link";
import { SessionsTable } from "@/components/workspace/sessions-table";
import { engine } from "@/lib/engine";

export const metadata: Metadata = {
  title: "Sessions",
  description: "Every diagnosis run, with its readiness, priorities and results.",
};

export default async function SessionsPage() {
  const runs = await engine.runs(200);
  return (
    <div className="mx-auto max-w-[1200px] px-5 pt-14 pb-28 sm:px-8 lg:pt-20">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-5xl leading-tight font-semibold tracking-[-0.03em] sm:text-6xl">Sessions</h1>
          <p className="mt-4 max-w-[600px] text-md leading-relaxed text-ink-2">
            Every run, newest first. Open one to read its intelligence summary, each agent&apos;s findings and the page preview.
          </p>
        </div>
        <Link href="/runs/new" className="inline-flex min-h-11 items-center rounded-[3px] bg-signal px-5 text-base font-semibold text-white hover:bg-signal-deep">
          New run
        </Link>
      </div>
      {runs.length ? (
        <SessionsTable runs={runs} />
      ) : (
        <div className="mt-10 border border-rule bg-canvas px-6 py-12">
          <h2 className="font-display text-2xl font-semibold tracking-tight">No runs yet</h2>
          <p className="mt-2 max-w-[560px] text-base text-ink-2">
            Start a run to diagnose a site. It appears here as soon as it starts, and stays here with its results.
          </p>
          <Link href="/runs/new" className="mt-5 inline-flex min-h-11 items-center rounded-[3px] bg-signal px-5 text-base font-semibold text-white hover:bg-signal-deep">
            Start a run
          </Link>
        </div>
      )}
    </div>
  );
}
