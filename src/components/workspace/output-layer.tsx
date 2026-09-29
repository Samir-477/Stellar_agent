"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Check, ExternalLink, Globe, RefreshCw, Send, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { CodeDiff, changeTypeLabel } from "@/components/workspace/code-diff";
import { FixTypeBadge } from "@/components/workspace/issue-list";
import { Pager, usePaged } from "@/components/workspace/pager";
import { MicrositeIssues } from "@/components/microsite/microsite-issues";
import { PreviewFrame } from "@/components/workspace/preview-frame";
import { formatDate, urlPath } from "@/lib/format";
import { ARCHETYPE_LABEL, micrositeHref, pagePath, sameUrl, slugify } from "@/lib/microsite";
import type { CodeChange, IssueCard, MicrositeIssue, MicrositeSummary, Preview } from "@/lib/types";

type PageChange = { issue: IssueCard; change: CodeChange };

/** Approve the preview and publish it as a microsite at /microsites/{archetype}/{client}/{page path}. */
function PublishPanel({ runId, entryUrl, archetype, clientName, live }: {
  runId: string; entryUrl: string; archetype: string | null; clientName: string; live: MicrositeSummary | null;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [clientSlug, setClientSlug] = useState(live?.client_slug ?? slugify(clientName));
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  const [error, setError] = useState("");
  const [published, setPublished] = useState<MicrositeSummary | null>(null);
  const path = pagePath(entryUrl);
  const validSlug = /^[a-z0-9]+(-[a-z0-9]+)*$/.test(clientSlug);
  const address = archetype ? micrositeHref(archetype, clientSlug || "client", path) : null;
  const current = published ?? live;

  async function publish() {
    setState("busy");
    setError("");
    try {
      const response = await fetch(`/api/workspace/runs/${runId}/microsite`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ client_slug: clientSlug }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The microsite couldn't be published.");
      setPublished(data);
      setState("done");
      setOpen(false);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The microsite couldn't be published.");
      setState("idle");
    }
  }

  const liveHref = current ? micrositeHref(current.archetype, current.client_slug, current.page_path) : null;
  return (
    <section aria-labelledby="publish-heading" className="border border-rule bg-canvas">
      <div className="flex flex-wrap items-center justify-between gap-5 px-6 py-5">
        <div className="min-w-0">
          <h2 id="publish-heading" className="flex items-center gap-2 text-base font-semibold">
            <Globe aria-hidden="true" size={17} className="text-signal" />
            {current ? "Published as a microsite" : "Publish this preview as a microsite"}
          </h2>
          {current && liveHref ? (
            <p className="mt-1 text-sm text-ink-2">
              <Link href={liveHref} target="_blank" className="font-mono text-xs text-signal hover:underline">{liveHref}</Link>
              <span className="ml-2 text-ink-3">since {formatDate(current.published_at)}</span>
            </p>
          ) : (
            <p className="mt-1 max-w-[620px] text-sm text-ink-2">
              Approving publishes the fixed page with a view of every fix. The link is public but hidden from search engines.
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {current && liveHref && (
            <Link href={liveHref} target="_blank" className="inline-flex min-h-11 items-center gap-1.5 rounded-[3px] border border-rule-strong bg-paper px-4 text-sm font-semibold hover:border-ink-3">
              Open microsite <ExternalLink aria-hidden="true" size={14} />
            </Link>
          )}
          <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} disabled={!archetype}
                  className="inline-flex min-h-11 items-center gap-2 rounded-[3px] bg-signal px-5 text-sm font-semibold text-white hover:bg-signal-deep disabled:opacity-50">
            <Send aria-hidden="true" size={15} /> {current ? "Republish" : "Approve and publish"}
          </button>
        </div>
      </div>
      {!archetype && <p className="border-t border-rule px-6 py-3 text-sm text-amber">Confirm the client&apos;s business type before publishing; it is the first part of the address.</p>}
      {open && archetype && (
        <div className="grid gap-5 border-t border-rule bg-paper px-6 py-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
          <div>
            <p className="text-xs font-semibold text-ink-2">Microsite address</p>
            <p className="mt-2 flex flex-wrap items-center gap-y-2 font-mono text-sm text-ink">
              <span className="text-ink-3">/microsites/</span>
              <span title={ARCHETYPE_LABEL[archetype]}>{archetype}</span>
              <span className="text-ink-3">/</span>
              <label className="inline-flex">
                <span className="sr-only">Client part of the address</span>
                <input value={clientSlug} onChange={(e) => setClientSlug(e.target.value.toLowerCase())} aria-invalid={!validSlug}
                       className="min-h-9 w-[220px] rounded-[3px] border border-rule-strong bg-mist px-2 font-mono text-sm outline-none focus-visible:border-signal aria-[invalid=true]:border-red" />
              </label>
              <span className="text-ink-3">/</span>
              <span className="break-all">{path}</span>
            </p>
            <p className="mt-2 text-xs text-ink-3">
              The page part mirrors {urlPath(entryUrl)}. {current ? "Publishing again replaces the live version; earlier versions stay listed under Microsites." : "Use lowercase letters, numbers and hyphens for the client part."}
            </p>
            {!validSlug && <p className="mt-1 text-xs font-medium text-red">Use lowercase letters, numbers and single hyphens.</p>}
            {error && <p role="alert" className="mt-2 text-sm font-medium text-red">{error}</p>}
          </div>
          <div className="flex gap-2">
            <button type="button" onClick={() => setOpen(false)} className="min-h-11 rounded-[3px] px-4 text-sm font-medium text-ink-2 hover:bg-mist">Cancel</button>
            <button type="button" onClick={publish} disabled={!validSlug || state === "busy"}
                    className="inline-flex min-h-11 items-center gap-2 rounded-[3px] bg-signal px-5 text-sm font-semibold text-white hover:bg-signal-deep disabled:opacity-60">
              {state === "busy" ? "Publishing…" : `Publish ${address ? "to this address" : ""}`}
            </button>
          </div>
        </div>
      )}
      {state === "done" && published && (
        <p className="flex items-center gap-2 border-t border-rule bg-soft px-6 py-3 text-sm text-signal">
          <Check aria-hidden="true" size={15} /> Published. It is listed under Microsites with this client.
        </p>
      )}
    </section>
  );
}

/** The Output layer for the diagnosed URL: the page with the fixes applied, and every code change before and after. */
export function OutputLayer({ runId, initial, issues, pageIssues, entryUrl, archetype, clientName, live }: {
  runId: string;
  initial: Preview | null;
  issues: IssueCard[];
  pageIssues: MicrositeIssue[] | null; // null: the page review was unavailable
  entryUrl: string;
  archetype: string | null;
  clientName: string;
  live: MicrositeSummary | null;
}) {
  const router = useRouter();
  const [preview, setPreview] = useState(initial);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState("");

  // Page links are signed for an hour; refresh them from the server before they lapse.
  useEffect(() => {
    if (!preview) return;
    const ms = preview.links_expire_at * 1000 - Date.now() - 60_000;
    const timer = setTimeout(() => router.refresh(), Math.max(ms, 5_000));
    return () => clearTimeout(timer);
  }, [preview, router]);

  const changes = useMemo<PageChange[]>(() => issues.flatMap((issue) => issue.changes
    .filter((change) => sameUrl(change.page_url, entryUrl))
    .map((change) => ({ issue, change }))), [issues, entryUrl]);
  const paged = usePaged(changes, 5);

  async function build() {
    setBuilding(true);
    setError("");
    try {
      const response = await fetch(`/api/workspace/runs/${runId}/preview`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "The preview couldn't be built.");
      setPreview(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The preview couldn't be built.");
    } finally {
      setBuilding(false);
    }
  }

  const page = preview?.pages.find((p) => sameUrl(p.url, entryUrl));
  const placed = changes.filter((c) => c.change.placed !== false).length;

  return (
    <div className="space-y-14">
      <section aria-labelledby="preview-heading">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 id="preview-heading" className="font-display text-4xl font-semibold tracking-[-0.02em]">Preview with the fixes</h2>
            <p className="mt-2 max-w-[680px] text-base text-ink-2">
              The diagnosed page, <span className="font-mono text-sm text-ink">{urlPath(entryUrl)}</span>, with every change the agents
              proposed for it. {changes.length ? `${placed} of ${changes.length} changes placed.` : "The agents proposed no code changes for this page."}
            </p>
          </div>
          {preview && (
            <button type="button" onClick={build} disabled={building} className="inline-flex min-h-10 items-center gap-1.5 rounded-[3px] border border-rule px-3 text-sm font-medium text-ink-2 hover:bg-mist disabled:opacity-60">
              <RefreshCw aria-hidden="true" size={14} className={building ? "animate-spin" : ""} /> {building ? "Rebuilding…" : "Rebuild preview"}
            </button>
          )}
        </div>
        {error && <p role="alert" className="mt-3 text-sm font-medium text-red">{error}</p>}
        <div className="mt-6">
          {!preview ? (
            <div className="grid gap-6 border border-rule bg-canvas px-6 py-10 lg:grid-cols-[1fr_auto] lg:items-center">
              <div>
                <h3 className="font-display text-2xl font-semibold">No preview built yet</h3>
                <p className="mt-2 max-w-[600px] text-base leading-relaxed text-ink-2">
                  Building applies the proposed changes to the captured page so you can check them before publishing. Nothing is public yet.
                </p>
              </div>
              <button type="button" onClick={build} disabled={building}
                      className="inline-flex min-h-12 items-center gap-2 rounded-[3px] bg-signal px-6 text-base font-semibold text-white hover:bg-signal-deep disabled:cursor-wait disabled:opacity-70">
                {building ? "Building, up to a minute…" : "Build preview"}
              </button>
            </div>
          ) : page ? (
            <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
              <div className="min-w-0"><PreviewFrame views={page.views} pageUrl={page.url} /></div>
              <aside aria-label="Technical details" className="lg:sticky lg:top-24 lg:max-h-[calc(100vh-120px)] lg:self-start lg:overflow-y-auto">
                {pageIssues
                  ? <MicrositeIssues issues={pageIssues} />
                  : <p className="border border-rule bg-mist px-5 py-6 text-sm text-ink-2">The technical details couldn&apos;t be loaded. The code changes are listed below.</p>}
              </aside>
            </div>
          ) : (
            <p className="border border-rule bg-mist px-6 py-8 text-base text-ink-2">
              The preview has no version of the diagnosed page, because no change was proposed for it. Changes on other sampled pages are in the Agents layer.
            </p>
          )}
        </div>
      </section>

      {preview && page && (
        <PublishPanel runId={runId} entryUrl={entryUrl} archetype={archetype} clientName={clientName} live={live} />
      )}

      <section aria-labelledby="code-heading">
        <h2 id="code-heading" className="font-display text-4xl font-semibold tracking-[-0.02em]">Code changes, before and after</h2>
        <p className="mt-2 max-w-[680px] text-base text-ink-2">
          Each change on this page with the issue it fixes. Copy the new code, or open the issue in the Agents layer for its evidence.
        </p>
        <div className="mt-7 space-y-6">
          {paged.rows.map(({ issue, change }) => (
            <article key={change.key} className="border border-rule">
              <header className="flex flex-wrap items-start justify-between gap-3 border-b border-rule px-5 py-4">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-3">
                    <span className="font-mono text-signal">{issue.agent_id}</span>
                    <span>{issue.agent_name}</span>
                    <span>{changeTypeLabel(change.type)}</span>
                  </p>
                  <h3 className="mt-1 text-md leading-snug font-semibold">{issue.title}</h3>
                </div>
                <span className="flex items-center gap-3">
                  <FixTypeBadge type={issue.fix_type} />
                  {change.placed === false
                    ? <span className="inline-flex items-center gap-1 text-xs font-medium text-amber"><TriangleAlert aria-hidden="true" size={13} /> Not placed</span>
                    : <span className="inline-flex items-center gap-1 text-xs font-medium text-signal"><Check aria-hidden="true" size={13} /> In the preview</span>}
                </span>
              </header>
              <div className="px-5 py-5">
                <CodeDiff before={change.before} after={change.after} beforeSegments={change.before_segments}
                          afterSegments={change.after_segments} language={change.language} compact />
                <p className="mt-3 text-sm leading-relaxed text-ink-2">
                  {change.placed === false && change.reason ? <span className="font-medium text-amber">{change.reason}. </span> : null}
                  {change.rationale || change.note}
                </p>
              </div>
            </article>
          ))}
          {!changes.length && <p className="border border-rule bg-mist px-6 py-8 text-base text-ink-2">No code changes were proposed for this page.</p>}
        </div>
        {changes.length > 5 && (
          <div className="mt-5"><Pager page={paged.page} pages={paged.pages} total={paged.total} size={paged.size} onPage={paged.setPage} noun="changes" /></div>
        )}
      </section>
    </div>
  );
}
