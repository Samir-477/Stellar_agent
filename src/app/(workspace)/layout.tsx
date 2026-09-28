import type { Metadata } from "next";
import { TopBar } from "@/components/workspace/top-bar";
import { requireUser } from "@/lib/session";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export default async function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const email = await requireUser();
  return (
    <div className="flex min-h-screen flex-col bg-paper text-ink">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:bg-paper focus:px-3 focus:py-2">
        Skip to content
      </a>
      <TopBar email={email} />
      <main id="main" className="flex-1">
        {children}
      </main>
    </div>
  );
}
