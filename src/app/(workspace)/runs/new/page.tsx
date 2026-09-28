import type { Metadata } from "next";
import { RunSetup } from "@/components/workspace/run-setup";
import { engine } from "@/lib/engine";

export const metadata: Metadata = {
  title: "New run",
  description: "Choose a website and the agents to run on it.",
};

export default async function NewRunPage({ searchParams }: PageProps<"/runs/new">) {
  const [agents, collectors, params] = await Promise.all([engine.agents(), engine.collectors(), searchParams]);
  const requested = typeof params.agents === "string" ? params.agents.split(",") : [];
  const known = new Set(agents.map((a) => a.id));
  const preselected = requested.filter((id) => known.has(id));

  return (
    <div className="mx-auto max-w-[1280px] px-5 pt-14 pb-28 sm:px-8 lg:pt-20">
      <h1 className="font-display text-5xl leading-tight font-semibold tracking-[-0.03em] sm:text-6xl">New run</h1>
      <p className="mt-4 max-w-[600px] text-md leading-relaxed text-ink-2">
        Choose the site and the agents to run. The collectors those agents need are added automatically, and nothing
        starts until you press Start.
      </p>
      <RunSetup agents={agents} collectors={collectors} preselected={preselected.length ? preselected : agents.map((a) => a.id)} />
    </div>
  );
}
