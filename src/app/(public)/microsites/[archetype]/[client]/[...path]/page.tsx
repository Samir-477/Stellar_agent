import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Brand } from "@/components/brand";
import { MicrositeIssues } from "@/components/microsite/microsite-issues";
import { PreviewFrame } from "@/components/workspace/preview-frame";
import { SplitPane } from "@/components/workspace/split-pane";
import { engine } from "@/lib/engine";
import { formatDate, urlPath } from "@/lib/format";
import { site } from "@/lib/site";

// Public, and never indexed (see generateMetadata): a microsite copies the client's own page.
type Params = { archetype: string; client: string; path: string[] };

async function load(params: Promise<Params>) {
  const { archetype, client, path } = await params;
  const parts = [archetype, client, ...path];
  try {
    return { parts, microsite: await engine.liveMicrosite(parts) };
  } catch {
    return { parts, microsite: null };
  }
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { microsite } = await load(params);
  return {
    title: { absolute: microsite ? `${microsite.page_title || urlPath(microsite.source_url)}, reviewed` : "Microsite" },
    robots: { index: false, follow: false },
  };
}

export default async function MicrositePage({ params }: { params: Promise<Params> }) {
  const { parts, microsite } = await load(params);
  if (!microsite) notFound();
  const slug = encodeURIComponent(parts.join("/"));
  const views = {
    fixed: `/api/public/microsites/html?slug=${slug}&view=fixed`,
    annotated: `/api/public/microsites/html?slug=${slug}&view=annotated`,
  };
  const fixed = microsite.issues.filter((i) => i.fixed).length;

  return (
    <div className="min-h-screen bg-paper text-ink">
      <header className="bg-forest text-white">
        <div className="mx-auto flex max-w-[1320px] flex-wrap items-center justify-between gap-4 px-5 py-4 sm:px-8">
          <Brand tone="dark" />
          <p className="text-xs text-[#9fb5a8]">Prepared for {microsite.client_name}. A preview, not the live site.</p>
        </div>
      </header>

      <section className="border-b border-rule bg-canvas">
        <div className="mx-auto grid max-w-[1320px] gap-8 px-5 py-12 sm:px-8 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] lg:items-end">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-signal">Page review</p>
            <h1 className="mt-3 font-display text-5xl leading-[1.1] font-semibold tracking-[-0.03em] sm:text-6xl">
              {microsite.page_title || urlPath(microsite.source_url)}
            </h1>
            <a href={microsite.source_url} target="_blank" rel="noreferrer noopener" className="mt-3 inline-block font-mono text-xs break-all text-ink-2 hover:text-signal hover:underline">
              {microsite.source_url}
            </a>
          </div>
          <dl className="grid grid-cols-3 border border-rule bg-paper">
            {[
              ["Issues on this page", String(microsite.issues.length)],
              ["Fixed here", String(fixed)],
              ["Reviewed", formatDate(microsite.published_at, false)],
            ].map(([label, value], i) => (
              <div key={label} className={`px-5 py-4 ${i ? "border-l border-rule" : ""}`}>
                <dt className="text-2xs text-ink-3">{label}</dt>
                <dd className="mt-1 font-display text-2xl font-semibold">{value}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <main className="mx-auto max-w-[1320px] px-5 py-10 sm:px-8">
        <SplitPane storageKey="stellar.microsite-split" initial={64} label="Resize the preview"
          left={<PreviewFrame views={views} pageUrl={microsite.source_url} height="h-[80vh] min-h-[600px]" />}
          right={
            <aside aria-label="Issues on this page" className="lg:sticky lg:top-6 lg:max-h-[calc(100vh-48px)] lg:overflow-y-auto">
              <MicrositeIssues issues={microsite.issues} />
            </aside>
          } />
      </main>

      <footer className="border-t border-rule">
        <p className="mx-auto max-w-[1320px] px-5 py-6 text-xs text-ink-3 sm:px-8">
          Reviewed by {site.name}. Captured pages are frozen copies: booking engines and other scripts don&apos;t run here.
        </p>
      </footer>
    </div>
  );
}
