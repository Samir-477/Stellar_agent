import type { NextRequest } from "next/server";
import { engine } from "@/lib/engine";
import { failure, guard, ok } from "@/lib/workspace-api";

const ARCHETYPES = new Set(["hospitality", "loans", "retail", "logistics"]);

function sameSite(a: string, b: string): boolean {
  const clean = (u: string) => u.trim().replace(/\/+$/, "").toLowerCase();
  return clean(a) === clean(b);
}

/** Start a run: reuse the client record only when URL, name and crawl authorization all match. */
export async function POST(request: NextRequest) {
  const denied = await guard(request, { write: true });
  if (denied) return denied;
  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return failure(new Error("Send the run details as JSON."));
  }
  const url = typeof body.url === "string" ? body.url.trim() : "";
  const name = typeof body.name === "string" ? body.name.trim().slice(0, 200) : "";
  const consent = typeof body.consent_by === "string" ? body.consent_by.trim().slice(0, 200) : "";
  const archetype = typeof body.archetype === "string" && ARCHETYPES.has(body.archetype) ? body.archetype : null;
  const cap = Number(body.crawl_cap);
  const agents = Array.isArray(body.agents) ? body.agents.filter((a): a is string => typeof a === "string") : [];
  if (!/^https?:\/\//i.test(url) || !name || !consent || !Number.isInteger(cap) || cap < 1 || cap > 100 || !agents.length) {
    return Response.json({ error: "Check the site details and choose at least one agent." }, { status: 422 });
  }
  try {
    const registry = await engine.agents();
    const known = new Set(registry.map((a) => a.id));
    if (agents.some((id) => !known.has(id))) return Response.json({ error: "Unknown agent in the selection." }, { status: 422 });
    const existing = (await engine.clients()).find(
      (c) => sameSite(c.primary_url, url) && c.name === name && c.crawl_consent_by === consent,
    );
    const client = existing ?? (await engine.createClient({ name, primary_url: url, archetype, crawl_consent_by: consent }));
    const full = agents.length === registry.length;
    const run = await engine.createRun({ client_id: client.id, type: full ? "full" : "agent", agents, crawl_cap: cap });
    return ok({ run_id: run.run_id });
  } catch (error) {
    return failure(error);
  }
}
