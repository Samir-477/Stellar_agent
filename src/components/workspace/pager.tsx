"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

/** Client-side paging over an in-memory list; the page resets when the list changes size below it. */
export function usePaged<T>(rows: T[], size: number) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const current = Math.min(page, pages - 1);
  return { rows: rows.slice(current * size, current * size + size), page: current, pages, setPage, total: rows.length, size };
}

export function Pager({ page, pages, total, size, onPage, noun = "rows" }: {
  page: number; pages: number; total: number; size: number; onPage: (page: number) => void; noun?: string;
}) {
  if (total <= size) return total ? <p className="text-xs text-ink-3">{total} {noun}</p> : null;
  const from = page * size + 1;
  const to = Math.min(total, from + size - 1);
  const numbers = Array.from({ length: pages }, (_, i) => i).filter((i) => pages <= 7 || Math.abs(i - page) <= 2 || i === 0 || i === pages - 1);
  const button = "flex h-8 min-w-8 items-center justify-center rounded-[3px] px-2 text-xs font-medium transition-colors disabled:opacity-35";
  return (
    <nav aria-label="Pages" className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-xs text-ink-3" aria-live="polite">{from}–{to} of {total} {noun}</p>
      <div className="flex items-center gap-1">
        <button type="button" onClick={() => onPage(page - 1)} disabled={page === 0} aria-label="Previous page" className={`${button} text-ink-2 hover:bg-mist`}>
          <ChevronLeft size={15} />
        </button>
        {numbers.map((n, i) => (
          <span key={n} className="flex items-center">
            {i > 0 && n - numbers[i - 1] > 1 && <span className="px-1 text-xs text-ink-3">…</span>}
            <button type="button" onClick={() => onPage(n)} aria-current={n === page ? "page" : undefined}
                    className={`${button} ${n === page ? "bg-ink text-white" : "text-ink-2 hover:bg-mist"}`}>
              {n + 1}
            </button>
          </span>
        ))}
        <button type="button" onClick={() => onPage(page + 1)} disabled={page === pages - 1} aria-label="Next page" className={`${button} text-ink-2 hover:bg-mist`}>
          <ChevronRight size={15} />
        </button>
      </div>
    </nav>
  );
}
