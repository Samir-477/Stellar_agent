"use client";

export default function WorkspaceError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto max-w-[720px] px-4 py-20 sm:px-6">
      <p className="text-sm font-semibold text-red">Something stopped this page</p>
      <h1 className="mt-3 font-display text-5xl leading-tight font-semibold tracking-[-0.03em]">The workspace couldn&apos;t load this data.</h1>
      <p className="mt-4 text-md leading-relaxed text-ink-2">{error.message || "The diagnosis engine returned an error."}</p>
      <p className="mt-2 text-sm text-ink-3">
        In local development the engine runs separately: start it with uvicorn on port 8000, then try again.
      </p>
      <button type="button" onClick={reset} className="mt-8 inline-flex min-h-11 items-center rounded-[3px] bg-signal px-5 text-base font-semibold text-white hover:bg-signal-deep">
        Try again
      </button>
    </div>
  );
}
