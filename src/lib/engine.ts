import "server-only";
import type {
  AgentInfo, AgentReport, Client, CollectorInfo, IntelligenceReport, IssueCard, MicrositeLive, MicrositeSummary, Preview,
  Progress, RunGaps, RunSummary,
} from "@/lib/types";

// Server-side client for the diagnosis engine. The browser never sees ENGINE_API_KEY:
// pages and route handlers call the engine after checking the workspace session.
const BASE = (process.env.ENGINE_API_URL ?? (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : "http://127.0.0.1:8000")).replace(/\/$/, "");

export class EngineError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const AGENT_ID = /^[SAG]\d{1,2}$/;

export function isRunId(value: string): boolean {
  return RUN_ID.test(value);
}

export function isAgentId(value: string): boolean {
  return AGENT_ID.test(value);
}

function runPath(runId: string, rest = ""): string {
  if (!isRunId(runId)) throw new EngineError(404, "run not found");
  return `/runs/${runId}${rest}`;
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  return (await (await send(path, init)).json()) as T;
}

/** The raw engine response, for bodies that aren't JSON (published microsite HTML). */
export async function send(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const key = process.env.ENGINE_API_KEY;
  if (key) headers.set("Authorization", `Bearer ${key}`);
  const bypass = process.env.VERCEL_AUTOMATION_BYPASS_SECRET;
  if (bypass) headers.set("x-vercel-protection-bypass", bypass);
  if (init.body) headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    // Live data is never cached; calls that pass `next.revalidate` (the static catalog) are.
    response = await fetch(`${BASE}/api/v1${path}`, { ...init, headers, ...(init.next ? {} : { cache: "no-store" as const }) });
  } catch {
    throw new EngineError(503, `The diagnosis engine isn't reachable at ${BASE}. Start it, then reload this page.`);
  }
  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      // keep the status text
    }
    throw new EngineError(response.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response;
}

const SLUG_PART = /^[a-z0-9]+(-[a-z0-9]+)*$/;

/** archetype/client/page-path, each part lowercase letters, numbers and hyphens. */
export function isMicrositeSlug(parts: string[]): boolean {
  return parts.length >= 3 && parts.length <= 12 && parts.every((p) => SLUG_PART.test(p));
}

/** Returns null for a 404, so pages can show an explicit empty state instead of an error. */
async function optional<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch (error) {
    if (error instanceof EngineError && error.status === 404) return null;
    throw error;
  }
}

// Bump when the catalog's shape changes, so a new deploy doesn't serve an hour-old cached copy.
const CATALOG_VERSION = 2;

export const engine = {
  // The agent and collector catalog only changes with a deploy, so it is cached for an hour.
  agents: () => call<AgentInfo[]>(`/agents?catalog=${CATALOG_VERSION}`, { next: { revalidate: 3600 } }),
  collectors: () => call<CollectorInfo[]>("/collectors", { next: { revalidate: 3600 } }),
  runs: (limit = 50) => call<RunSummary[]>(`/runs?limit=${limit}`),
  deleteRun: (runId: string) => call<{ run_id: string; deleted: boolean }>(runPath(runId), { method: "DELETE" }),
  progress: (runId: string) => call<Progress>(runPath(runId, "/progress")),
  report: (runId: string) => optional(call<IntelligenceReport>(runPath(runId, "/report"))),
  agentReports: (runId: string) => call<Record<string, AgentReport>>(runPath(runId, "/agents")),
  agentReport: (runId: string, agentId: string) => {
    if (!isAgentId(agentId)) throw new EngineError(404, "agent not found");
    return optional(call<AgentReport>(runPath(runId, `/agents/${agentId}`)));
  },
  gaps: (runId: string) => call<RunGaps>(runPath(runId, "/gaps")),
  issues: (runId: string) => call<{ issues: IssueCard[] }>(runPath(runId, "/issues")).then((r) => r.issues),
  publishMicrosite: (runId: string, body: { client_slug?: string; published_by?: string }) =>
    call<MicrositeSummary>(runPath(runId, "/microsite"), { method: "POST", body: JSON.stringify(body) }),
  microsites: () => call<MicrositeSummary[]>("/microsites"),
  unpublishMicrosite: (id: string) => {
    if (!RUN_ID.test(id)) throw new EngineError(404, "microsite not found");
    return call<{ id: string }>(`/microsites/${id}/unpublish`, { method: "POST" });
  },
  liveMicrosite: (parts: string[]) => {
    if (!isMicrositeSlug(parts)) throw new EngineError(404, "microsite not found");
    return optional(call<MicrositeLive>(`/microsites/live?slug=${encodeURIComponent(parts.join("/"))}`));
  },
  liveMicrositeHtml: (parts: string[], view: "fixed" | "annotated") => {
    if (!isMicrositeSlug(parts)) throw new EngineError(404, "microsite not found");
    return send(`/microsites/live/html?slug=${encodeURIComponent(parts.join("/"))}&view=${view}`);
  },
  preview: (runId: string) => optional(call<Preview>(runPath(runId, "/preview"))),
  buildPreview: (runId: string) => call<Preview>(runPath(runId, "/preview"), { method: "POST" }),
  clients: () => call<Client[]>("/clients"),
  createClient: (body: { name: string; primary_url: string; archetype: string | null; crawl_consent_by: string }) =>
    call<Client>("/clients", { method: "POST", body: JSON.stringify(body) }),
  createRun: (body: { client_id: string; type: "full" | "agent"; agents: string[]; crawl_cap: number }) =>
    call<{ run_id: string; status: string; agents: string[] }>("/runs", { method: "POST", body: JSON.stringify(body) }),
  confirmArchetype: (runId: string, archetype: string) =>
    call<{ run_id: string }>(runPath(runId, "/archetype"), { method: "POST", body: JSON.stringify({ archetype }) }),
};
