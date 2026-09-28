"use client";

import { Pager, usePaged } from "@/components/workspace/pager";
import { ConfidenceLabel } from "@/components/workspace/status";
import { urlPath } from "@/lib/format";
import type { Patch } from "@/lib/types";

function humanType(type: string): string {
  return { text_replace: "Text rewrite", attribute_set: "Attribute", element_insert: "New section", element_remove: "Removal",
    head_upsert: "Head tag", jsonld_upsert: "Structured data", file_patch: "Site file", header_recommendation: "HTTP header" }[type] ?? type;
}

/** An agent's proposed changes, five at a time: page and kind of change, then before and after side by side. */
export function ChangesList({ changes }: { changes: Patch[] }) {
  const paged = usePaged(changes, 5);
  return (
    <div>
      <ul className="space-y-4">
        {paged.rows.map((p) => (
          <li key={p.key} className="border border-rule">
            <p className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-rule bg-mist px-5 py-2.5 text-xs">
              <span className="font-mono text-2xs text-signal">{p.page_url ? urlPath(p.page_url) : "Site files"}</span>
              <span className="text-ink-3">{humanType(p.type)}</span>
              <span className="ml-auto"><ConfidenceLabel confidence={p.confidence} /></span>
            </p>
            <div className="grid md:grid-cols-2">
              <div className="border-b border-rule px-5 py-4 md:border-r md:border-b-0">
                <p className="text-2xs font-semibold text-ink-3">Before</p>
                <p className="mt-1.5 text-sm break-words text-ink-2">{p.before || <span className="italic">Nothing there</span>}</p>
              </div>
              <div className="bg-soft/40 px-5 py-4">
                <p className="text-2xs font-semibold text-signal">After</p>
                <p className="mt-1.5 text-sm break-words text-ink">{p.after}</p>
              </div>
            </div>
            {p.rationale && <p className="border-t border-rule px-5 py-3 text-xs leading-relaxed text-ink-2">{p.rationale}</p>}
          </li>
        ))}
      </ul>
      <div className="mt-4">
        <Pager page={paged.page} pages={paged.pages} total={paged.total} size={paged.size} onPage={paged.setPage} noun="changes" />
      </div>
    </div>
  );
}
