import type { Metadata } from "next";
import Link from "next/link";
import { ArrowUpRight, Globe } from "lucide-react";
import { MicrositeActions } from "@/components/workspace/microsite-actions";
import { engine } from "@/lib/engine";
import { formatDate, plural, urlPath } from "@/lib/format";
import { ARCHETYPE_LABEL, micrositeHref } from "@/lib/microsite";
import type { MicrositeSummary } from "@/lib/types";

export const metadata: Metadata = {
  title: "Microsites",
  description: "Published previews of fixed pages, arranged by client.",
};

function status(m: MicrositeSummary): { label: string; tone: string; live: boolean } {
  if (m.unpublished_at) return { label: "Unpublished", tone: "text-ink-3", live: false };
  if (m.superseded_at) return { label: "Replaced", tone: "text-ink-3", live: false };
  return { label: "Live", tone: "text-signal", live: true };
}

export default async function MicrositesPage() {
  const all = await engine.microsites();
  const clients = Array.from(new Set(all.map((m) => m.client_slug)));

  return (
    <div className="mx-auto max-w-[1200px] px-5 pt-14 pb-28 sm:px-8 lg:pt-20">
      <h1 className="font-display text-5xl leading-tight font-semibold tracking-[-0.03em] sm:text-6xl">Microsites</h1>
      <p className="mt-4 max-w-[640px] text-md leading-relaxed text-ink-2">
        Approved previews, published for clients. Each shows the fixed page and every issue we fixed on it. Links are public
        but hidden from search engines, so they never compete with the client&apos;s own pages.
      </p>

      {!all.length ? (
        <div className="mt-12 grid gap-6 border border-rule bg-canvas px-7 py-10 lg:grid-cols-[1fr_auto] lg:items-center">
          <div>
            <h2 className="font-display text-2xl font-semibold tracking-tight">No microsites yet</h2>
            <p className="mt-2 max-w-[560px] text-base text-ink-2">
              Open a finished run, check its Output layer, then choose Approve and publish. The microsite appears here under its client.
            </p>
          </div>
          <Link href="/sessions" className="inline-flex min-h-11 items-center rounded-[3px] bg-signal px-5 text-sm font-semibold text-white hover:bg-signal-deep">Go to sessions</Link>
        </div>
      ) : (
        <div className="mt-14 space-y-14">
          {clients.map((slug) => {
            const rows = all.filter((m) => m.client_slug === slug);
            const live = rows.filter((m) => status(m).live);
            const earlier = rows.filter((m) => !status(m).live);
            return (
              <section key={slug} aria-labelledby={`client-${slug}`}>
                <div className="flex flex-wrap items-end justify-between gap-3 border-b-[3px] border-ink pb-4">
                  <div>
                    <h2 id={`client-${slug}`} className="font-display text-3xl font-semibold tracking-[-0.02em]">{rows[0].client_name}</h2>
                    <p className="mt-1 font-mono text-xs text-ink-3">/microsites/{rows[0].archetype}/{slug}</p>
                  </div>
                  <p className="text-sm text-ink-2">
                    <span className="font-semibold text-ink">{plural(live.length, "live page")}</span>
                    <span className="mx-2 text-ink-3">/</span>{ARCHETYPE_LABEL[rows[0].archetype] ?? rows[0].archetype}
                  </p>
                </div>
                <ul>
                  {[...live, ...earlier].map((m) => {
                    const s = status(m);
                    const href = micrositeHref(m.archetype, m.client_slug, m.page_path);
                    return (
                      <li key={m.id} className={`grid gap-3 border-b border-rule px-2 py-5 md:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_120px_auto] md:items-center md:gap-6 ${s.live ? "" : "opacity-70"}`}>
                        <div className="min-w-0">
                          <p className="flex items-center gap-2 text-md font-semibold">
                            <Globe aria-hidden="true" size={15} className={s.live ? "text-signal" : "text-ink-3"} />
                            <span className="truncate">{m.page_title || urlPath(m.source_url)}</span>
                          </p>
                          {s.live ? (
                            <Link href={href} target="_blank" className="mt-1 inline-flex max-w-full items-center gap-1 font-mono text-2xs break-all text-signal hover:underline">
                              {href} <ArrowUpRight aria-hidden="true" size={12} className="shrink-0" />
                            </Link>
                          ) : <p className="mt-1 font-mono text-2xs break-all text-ink-3">{href}</p>}
                        </div>
                        <div className="text-sm text-ink-2">
                          <p>{m.changes_placed} of {m.changes_total} fixes applied, {plural(m.issue_count, "issue")} listed</p>
                          <p className="mt-0.5 text-xs text-ink-3">
                            Published {formatDate(m.published_at)}{m.published_by ? ` by ${m.published_by}` : ""},{" "}
                            <Link href={`/runs/${m.run_id}?layer=output`} className="hover:underline">from this run</Link>
                          </p>
                        </div>
                        <p className={`text-sm font-semibold ${s.tone}`}>{s.label}</p>
                        <MicrositeActions id={m.id} href={href} live={s.live} />
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
