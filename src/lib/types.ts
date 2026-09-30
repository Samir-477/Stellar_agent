// Shapes returned by the diagnosis engine (engine/api/app.py). Only the fields the workspace reads.

export type Pillar = "seo" | "aeo" | "geo";
export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type Confidence = "confirmed" | "likely" | "hypothesis";
export type Lane = "now" | "next" | "later" | "investigate" | "monitor";
export type CheckStatus = "pass" | "warn" | "fail" | "unverifiable" | "not_applicable";

export type CheckSpec = {
  id: string;
  title: string;
  default_severity: Severity;
  counts_toward_readiness: boolean;
  plain?: PlainEntry | null; // the reviewed plain-language entry (engine/plain.py)
};

// Why a run finished with gaps, and the checks it couldn't run, each with how to close it (engine/gaps.py).
export type GapWho = "rerun" | "us" | "you";
export type RunGaps = {
  status: RunStatus;
  model_calls: number;
  steps: { step: string | null; name: string; status: string; title: string; what_happened: string; fix: string; who: GapWho; detail: string[] }[];
  checks: { cause: string; title: string; explanation: string; fix: string; who: GapWho; items: { check_id: string; agent: string; title: string; name: string }[] }[];
};

// Plain-language explanations for management and clients (engine/plain.py).
export type PlainEntry = { name: string; problem: string; meaning: string; why: string; analogy: string; action: string };
export type PlainTerm = { term: string; meaning: string };
export type PlainExplanation = PlainEntry & {
  site_case: string; // this site's own case: written by the model and checked, or a template
  case_source: "model" | "rules";
  terms: PlainTerm[]; // technical terms used in the technical details, explained
  owner?: string; // who does the fix (engine/fix_steps.py); absent in previews built before 2026-09-30
  steps?: string[]; // how to fix it, with the issue's own pages filled in
};

export type AgentInfo = {
  id: string;
  name: string;
  pillar: Pillar;
  counts_toward_readiness: boolean;
  question: string;
  outcome: string;
  how: string;
  example: string; // illustrative, not a finding from any run
  reads: string[]; // collectors whose evidence the agent reads directly
  collectors: string[]; // every collector a run of this agent needs, upstream ones included
  checks: CheckSpec[];
};

export type CollectorInfo = {
  id: string;
  name: string;
  group: "site" | "search" | "ai" | "web";
  group_label: string;
  captures: string;
  services: string[];
  used_by: string[];
};

export type Readiness = Record<string, { score: number | null; coverage: number; band: string; capped_by_critical: boolean }>;

export type RunStatus = "queued" | "running" | "awaiting_confirmation" | "completed" | "completed_partial" | "failed" | "cancelled";

export type RunSummary = {
  id: string;
  type: "full" | "agent";
  agents: string[];
  status: RunStatus;
  note: string | null;
  crawl_cap: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  client_id: string;
  client_name: string;
  primary_url: string;
  archetype: string | null;
  tasks_total: number;
  tasks_done: number;
  readiness: Readiness | null;
  lanes: Record<Lane, number> | null;
};

export type ComponentState = "waiting" | "running" | "done" | "partial" | "failed" | "skipped" | "reused" | "paused";

export type ComponentProgress = {
  id: string;
  name: string;
  state: ComponentState;
  steps_total: number;
  steps_done: number;
  retrying: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  last_activity: string | null;
};

export type Progress = {
  run: {
    id: string;
    type: "full" | "agent";
    agents: string[];
    crawl_cap: number;
    created_at: string;
    started_at: string | null;
    finished_at: string | null;
    client: { name: string; primary_url: string; archetype: string | null };
  };
  status: RunStatus;
  note: string | null;
  tasks: { total: number; done: number; running: number };
  stages: { id: string; label: string; state: string }[];
  collectors: ComponentProgress[];
  agents: (ComponentProgress & { pillar: Pillar; findings: number | null })[];
  intelligence: string;
  events: { at: string; ref: string | null; kind: string; status: string; text: string }[];
  archetype_proposal: { archetype?: string; confidence?: number | string; signals?: string[] } | null;
};

export type Evidence = { type?: string; url?: string; excerpt?: string };

export type WorkItem = {
  id: string;
  title: string;
  action: string;
  severity: Severity;
  confidence: Confidence;
  effort: "S" | "M" | "L" | null;
  pillars: Pillar[];
  agents: string[];
  check_ids: string[];
  pages: string[];
  patch_keys: string[];
  missing_facts: string[];
  priority: number;
  harm: number;
  wave: Lane;
  priority_reason?: string;
  prerequisite_review?: boolean;
  cause: string | null;
  evidence: Evidence[];
  observation: boolean;
  facts: string[];
};

export type Sentence = { text: string; ids: string[] };

export type ClientPriority = {
  id: string;
  headline: string;
  why: string;
  action: string;
  source: "model" | "rules";
  severity: Severity;
  effort: "S" | "M" | "L" | null;
  pages: number;
  agents: string[];
  check_ids: string[];
  wave: Lane;
};

export type IntelligenceReport = {
  readiness: Readiness;
  executive_summary: { internal: Sentence[]; client: Sentence[]; client_priorities?: ClientPriority[]; source: string; note?: string };
  leads?: { blocker: string | null; opportunity: string | null; observation: string | null };
  what_to_fix_first: Partial<Record<Lane, WorkItem[]>>;
  whats_working: { id: string; check_id: string; agent: string; pillar: Pillar; title: string }[];
  what_needs_attention: { id: string; kind: string; check_id: string; agent: string; title: string }[];
  root_causes_and_patterns: {
    id: string; cause: string; title: string; fix: string; items: string[]; pages: number; pillars: Pillar[];
    agents: string[];
  }[];
  coverage: { agents: string[]; notes: string[] };
};

export type ReportIssue = {
  check_id: string;
  title: string;
  severity: Severity | null;
  confidence: Confidence;
  effort?: string | null;
  pages: string[];
  page_count?: number;
  evidence: Evidence[];
  impact?: string;
  fix?: string;
  verification?: string;
  status?: string;
  patch_keys?: string[];
};

export type Patch = {
  key: string;
  agent_id: string;
  type: string;
  page_url: string | null;
  before: string | null;
  after: string;
  rationale: string;
  confidence: Confidence;
  client_visible_note?: string;
};

export type AgentReport = {
  agent_id: string;
  agent_name: string;
  verdict: string;
  scorecard: Record<"pass" | "warn" | "fail" | "unverifiable" | "not_applicable", number>;
  scope_and_evidence: {
    coverage: { examined: Record<string, unknown> | string | null; limits: string[]; skipped: unknown[] };
    check_status: Record<string, CheckStatus>;
    signature_table: { columns: string[]; rows: unknown[][] } | null;
  };
  issues_to_fix: ReportIssue[];
  needs_attention: ReportIssue[];
  whats_working: { check_id: string; title: string; evidence?: Evidence[] }[];
  could_not_check?: { check_id: string; title: string; reason: string }[]; // absent in reports before 2026-09-29
  proposed_changes: Patch[];
  missing_facts_and_next_checks: string[];
};

export type PreviewChange = { key: string; title: string; note: string; type: string; placed: boolean };
export type HoodItem = { key: string; type: string; before: string | null; after: string; why: string; note: string };

export type Preview = {
  run_id: string;
  client: string;
  entry_url: string;
  captured_at: string;
  built_at: string;
  pages: {
    index: number;
    url: string;
    views: Partial<Record<"annotated" | "fixed", string>>;
    changes: PreviewChange[];
    not_placed: { key: string; reason: string }[];
    under_the_hood: HoodItem[];
  }[];
  issues?: MicrositeIssue[]; // the diagnosed page's issues, fixed first (absent in previews built before 2026-09-29)
  links_expire_at: number;
};

export type Client = { id: string; name: string; primary_url: string; archetype: string | null; crawl_consent_by: string | null };

// Issue cards (GET /runs/{id}/issues): evidence, proposed fix and before/after code together.
export type Segment = { k: "eq" | "del" | "ins"; t: string };
export type FixType = "code" | "content" | "facts" | "observation" | "action";

export type CodeChange = {
  key: string;
  type: string;
  page_url: string | null;
  rationale: string;
  note: string;
  confidence: Confidence | null;
  language: "html" | "json" | "text";
  before: string | null;
  after: string | null;
  before_segments: Segment[];
  after_segments: Segment[];
  placed: boolean | null;
  reason: string | null;
};

export type IssueCard = {
  id: string;
  agent_id: string;
  agent_name: string;
  pillar: Pillar | null;
  check_id: string;
  status: "fail" | "warn";
  severity: Severity | null;
  confidence: Confidence;
  title: string;
  impact: string;
  fix: string;
  verification: string;
  effort: "S" | "M" | "L" | null;
  pages: string[];
  evidence: Evidence[];
  missing_facts: string[];
  fix_type: FixType;
  changes: CodeChange[];
  plain?: PlainExplanation;
};

// Microsites: published, approved previews of a run's diagnosed URL.
export type Archetype = "hospitality" | "loans" | "retail" | "logistics";

export type MicrositeSummary = {
  id: string;
  archetype: Archetype;
  client_slug: string;
  page_path: string;
  client_name: string;
  source_url: string;
  page_title: string | null;
  run_id: string;
  changes_placed: number;
  changes_total: number;
  issue_count: number;
  published_by: string | null;
  published_at: string;
  superseded_at: string | null;
  unpublished_at: string | null;
};

export type MicrositeIssue = {
  agent_id: string;
  agent_name: string;
  check_id: string;
  status: "fail" | "warn";
  severity: Severity | null;
  title: string;
  impact: string;
  fix: string;
  fix_type: FixType;
  verification?: string; // absent in previews built before 2026-09-30
  effort?: "S" | "M" | "L" | null;
  fixed: boolean;
  changes: Pick<CodeChange, "type" | "language" | "before" | "after" | "before_segments" | "after_segments" | "note">[];
  plain?: PlainExplanation; // absent in microsites published before 2026-09-29
};

export type MicrositeLive = Omit<MicrositeSummary, "issue_count"> & { issues: MicrositeIssue[] };
