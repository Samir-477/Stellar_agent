"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { useState } from "react";
import { Brand } from "@/components/brand";

const NAV = [
  { href: "/home", label: "Home" },
  { href: "/sessions", label: "Sessions" },
  { href: "/microsites", label: "Microsites" },
];

// A run's own page belongs to Sessions: it is one saved session.
function activeHref(pathname: string): string | null {
  if (pathname.startsWith("/runs/new")) return "/runs/new";
  if (pathname.startsWith("/runs/") || pathname.startsWith("/sessions")) return "/sessions";
  if (pathname.startsWith("/microsites")) return "/microsites";
  if (pathname.startsWith("/home")) return "/home";
  return null;
}

export function TopBar({ email }: { email: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);
  const active = activeHref(pathname);

  async function signOut() {
    setSigningOut(true);
    try {
      await fetch("/api/demo-auth", { method: "DELETE" });
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <header className="sticky top-0 z-40 border-b border-rule bg-paper/95 shadow-[0_4px_20px_rgba(3,22,13,0.04)] backdrop-blur supports-[backdrop-filter]:bg-paper/90">
      <div className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-x-8 px-5 sm:px-8 lg:flex-nowrap">
        <Link href="/home" className="flex h-[72px] shrink-0 items-center rounded-sm" aria-label="Stellar Agents home">
          <Brand />
        </Link>
        <nav aria-label="Workspace" className="order-3 -mx-5 flex w-[calc(100%+2.5rem)] items-center gap-3 border-t border-rule px-5 py-2 sm:-mx-8 sm:w-[calc(100%+4rem)] sm:px-8 lg:order-none lg:mx-0 lg:w-auto lg:border-0 lg:px-0 lg:py-0">
          <ul className="flex items-center gap-1 rounded-[6px] border border-rule bg-canvas p-1">
            {NAV.map((item) => {
              const isActive = item.href === active;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={isActive ? "page" : undefined}
                    className={`flex min-h-10 items-center rounded-[4px] px-4 text-sm font-semibold transition-colors ${isActive ? "bg-paper text-ink shadow-[0_1px_5px_rgba(3,22,13,0.09)]" : "text-ink-2 hover:bg-paper/70 hover:text-ink"}`}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
          <Link href="/runs/new" aria-current={active === "/runs/new" ? "page" : undefined}
            className={`inline-flex min-h-11 items-center gap-2 rounded-[4px] px-4 text-sm font-semibold text-white transition-colors ${active === "/runs/new" ? "bg-signal-deep" : "bg-signal hover:bg-signal-deep"}`}>
            <Plus aria-hidden="true" size={16} strokeWidth={2.2} /> New run
          </Link>
        </nav>
        <div className="order-2 ml-auto flex items-center gap-4 lg:order-none">
          <span className="hidden max-w-[220px] truncate text-sm text-ink-3 md:inline" title={email}>{email}</span>
          <button
            type="button"
            onClick={signOut}
            disabled={signingOut}
            className="min-h-11 rounded-[3px] border-l border-rule pl-4 text-sm font-medium text-ink-2 transition-colors hover:text-ink disabled:opacity-60"
          >
            {signingOut ? "Signing out…" : "Sign out"}
          </button>
        </div>
      </div>
    </header>
  );
}
