"use client";

import { useRouter } from "next/navigation";
import { ArrowRight, Check, Minus } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { AgentIcon } from "@/components/workspace/icons";
import { PILLARS, PILLAR_ORDER } from "@/lib/pillars";
import type { AgentInfo, CollectorInfo, Pillar } from "@/lib/types";

const ARCHETYPES = [
  { value: "", label: "Detect automatically" },
  { value: "hospitality", label: "Hotels and resorts" },
  { value: "loans", label: "Loans and lending" },
  { value: "retail", label: "Retail" },
  { value: "logistics", label: "Logistics" },
];

type Errors = Partial<Record<"url" | "name" | "consent" | "cap" | "agents" | "form", string>>;

function Checkbox({ state }: { state: "on" | "off" | "some" }) {
  return (
    <span aria-hidden="true" className={`flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[3px] border transition-colors ${state === "off" ? "border-ink-3 bg-paper" : "border-signal bg-signal text-white"}`}>
      {state === "on" && <Check size={13} strokeWidth={3} />}
      {state === "some" && <Minus size={13} strokeWidth={3} />}
    </span>
  );
}

function Field({ id, label, help, error, children }: { id: string; label: string; help?: string; error?: string; children: React.ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-semibold">{label}</label>
      {help && <p id={`${id}-help`} className="mt-1 text-xs leading-snug text-ink-3">{help}</p>}
      <div className="mt-2">{children}</div>
      {error && <p id={`${id}-error`} className="mt-1.5 text-xs font-medium text-red">{error}</p>}
    </div>
  );
}

const input = "block min-h-11 w-full rounded-[3px] border border-rule-strong bg-paper px-3.5 text-base text-ink outline-none transition-[border-color,box-shadow] placeholder:text-ink-3 hover:border-ink-3 focus-visible:border-signal focus-visible:shadow-[0_0_0_3px_#d6f2df] aria-[invalid=true]:border-red";

export function RunSetup({ agents, collectors, preselected }: { agents: AgentInfo[]; collectors: CollectorInfo[]; preselected: string[] }) {
  const router = useRouter();
  const [selected, setSelected] = useState<Set<string>>(new Set(preselected));
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);

  const plan = useMemo(() => {
    const chosen = agents.filter((a) => selected.has(a.id));
    const needed = new Set(chosen.flatMap((a) => a.collectors));
    const planned = collectors.filter((c) => needed.has(c.id));
    const services = Array.from(new Set(planned.flatMap((c) => c.services)));
    return { chosen, planned, services };
  }, [agents, collectors, selected]);

  const all = selected.size === agents.length;

  function toggle(ids: string[], on: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      ids.forEach((id) => (on ? next.add(id) : next.delete(id)));
      return next;
    });
    setErrors((e) => ({ ...e, agents: undefined }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const url = String(form.get("url") || "").trim();
    const name = String(form.get("name") || "").trim();
    const consent = String(form.get("consent") || "").trim();
    const cap = Number(form.get("cap"));
    const next: Errors = {};
    try {
      const parsed = new URL(url);
      if (!/^https?:$/.test(parsed.protocol)) throw new Error();
    } catch {
      next.url = "Enter the full address, starting with https://";
    }
    if (!name) next.name = "Enter the client's name, as it should appear in reports.";
    if (!consent) next.consent = "Enter who authorized crawling this site.";
    if (!Number.isInteger(cap) || cap < 1 || cap > 100) next.cap = "Choose between 1 and 100 pages.";
    if (!selected.size) next.agents = "Choose at least one agent.";
    setErrors(next);
    if (Object.keys(next).length) {
      document.getElementById(next.url ? "run-url" : next.name ? "run-name" : next.consent ? "run-consent" : next.cap ? "run-cap" : "agents-heading")?.focus();
      return;
    }
    setBusy(true);
    try {
      const response = await fetch("/api/workspace/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, name, consent_by: consent, archetype: form.get("archetype") || null, crawl_cap: cap, agents: Array.from(selected) }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The run couldn't be started.");
      router.push(`/runs/${result.run_id}`);
    } catch (error) {
      setErrors({ form: error instanceof Error ? error.message : "The run couldn't be started." });
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="mt-10">
      <div className="mb-10 flex flex-wrap items-center justify-between gap-5 border-y border-rule py-5">
        <p className="text-sm text-ink-2"><span className="font-semibold text-ink">{selected.size} agents</span> selected · {plan.planned.length} collectors planned · Intelligence {selected.size >= 2 ? "included" : "needs two agents"}</p>
        <button type="submit" disabled={busy} className="inline-flex min-h-12 items-center gap-2.5 rounded-[3px] bg-signal px-6 text-base font-semibold text-white transition-colors hover:bg-signal-deep disabled:cursor-wait disabled:opacity-70">
          {busy ? "Starting…" : "Start diagnosis"} {!busy && <ArrowRight aria-hidden="true" size={17} />}
        </button>
      </div>
      {errors.form && <p role="alert" className="mb-8 border-l-[3px] border-red bg-red-bg px-4 py-3 text-sm font-medium text-red">{errors.form}</p>}
      <div className="grid gap-12 lg:grid-cols-[minmax(280px,0.8fr)_minmax(0,1.7fr)] lg:gap-14">
      <section aria-labelledby="site-heading" className="self-start rounded-[4px] border border-rule bg-mist p-6 sm:p-8 lg:sticky lg:top-24 lg:max-h-[calc(100svh-120px)] lg:overflow-y-auto lg:overscroll-contain">
        <h2 id="site-heading" className="font-display text-2xl font-semibold tracking-tight">Site</h2>
        <div className="mt-6 space-y-8 border-t border-rule pt-7">
          <Field id="run-url" label="Page to diagnose" help="The run centres on this page and samples others from the same site." error={errors.url}>
            <input id="run-url" name="url" type="url" inputMode="url" autoComplete="url" placeholder="https://www.example.com/page"
                   className={`${input} font-mono text-sm`} aria-invalid={!!errors.url} aria-describedby={`run-url-help${errors.url ? " run-url-error" : ""}`} />
          </Field>
          <Field id="run-name" label="Client name" error={errors.name}>
            <input id="run-name" name="name" type="text" autoComplete="organization" maxLength={200} placeholder="Business name" className={input}
                   aria-invalid={!!errors.name} aria-describedby={errors.name ? "run-name-error" : undefined} />
          </Field>
          <Field id="run-consent" label="Crawl authorized by" help="Who confirmed the site owner allows this crawl. It is recorded with the run." error={errors.consent}>
            <input id="run-consent" name="consent" type="text" maxLength={200} placeholder="Name and role" className={input}
                   aria-invalid={!!errors.consent} aria-describedby={`run-consent-help${errors.consent ? " run-consent-error" : ""}`} />
          </Field>
          <div className="grid grid-cols-[1fr_88px] gap-4">
            <Field id="run-archetype" label="Business type">
              <select id="run-archetype" name="archetype" defaultValue="" className={`${input} pr-8`}>
                {ARCHETYPES.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
              </select>
            </Field>
            <Field id="run-cap" label="Pages" error={errors.cap}>
              <input id="run-cap" name="cap" type="number" min={1} max={100} defaultValue={25} className={`${input} font-mono`}
                     aria-invalid={!!errors.cap} aria-describedby={errors.cap ? "run-cap-error" : undefined} />
            </Field>
          </div>
          <p className="text-xs leading-snug text-ink-3">
            If the business type is unclear, the run pauses and asks you to confirm it before the agents start.
          </p>
        </div>
      </section>

      <section aria-labelledby="agents-heading" className="min-w-0">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 id="agents-heading" tabIndex={-1} className="font-display text-2xl font-semibold tracking-tight outline-none">Agents</h2>
            <p className="mt-1 text-sm text-ink-2">Pick any mix. Two or more agents also produce the intelligence report.</p>
          </div>
          <div role="group" aria-label="Quick selection" className="flex flex-wrap border border-rule-strong">
            <button type="button" onClick={() => toggle(agents.map((a) => a.id), !all)} aria-pressed={all}
                    className={`min-h-11 px-4 text-sm font-semibold transition-colors ${all ? "bg-signal text-white" : "text-ink hover:bg-mist"}`}>
              All {agents.length}
            </button>
            {PILLAR_ORDER.map((pillar) => {
              const ids = agents.filter((a) => a.pillar === pillar).map((a) => a.id);
              const only = !all && ids.length === selected.size && ids.every((id) => selected.has(id));
              return (
                <button key={pillar} type="button" aria-pressed={only}
                        onClick={() => { setSelected(new Set(ids)); setErrors((e) => ({ ...e, agents: undefined })); }}
                        className={`min-h-11 border-l border-rule-strong px-4 text-sm font-medium transition-colors ${only ? "bg-soft text-signal" : "text-ink-2 hover:bg-mist hover:text-ink"}`}>
                  {PILLARS[pillar].short} only
                </button>
              );
            })}
            <button type="button" onClick={() => toggle(agents.map((a) => a.id), false)}
                    className="min-h-11 border-l border-rule-strong px-4 text-sm font-medium text-ink-2 hover:bg-mist hover:text-ink">
              Clear
            </button>
          </div>
        </div>
        {errors.agents && <p className="mt-3 text-sm font-medium text-red" role="alert">{errors.agents}</p>}

        <div className="mt-9 space-y-8">
          {PILLAR_ORDER.map((pillar: Pillar) => {
            const own = agents.filter((a) => a.pillar === pillar);
            const count = own.filter((a) => selected.has(a.id)).length;
            const state = count === 0 ? "off" : count === own.length ? "on" : "some";
            return (
              <fieldset key={pillar} className="overflow-hidden rounded-[4px] border border-rule bg-paper">
                <legend className="sr-only">{PILLARS[pillar].name}</legend>
                <button type="button" onClick={() => toggle(own.map((a) => a.id), state !== "on")} aria-pressed={state === "on"}
                        className="flex w-full items-center gap-3 border-b border-rule bg-mist px-6 py-4 text-left hover:bg-soft/60">
                  <Checkbox state={state} />
                  <span className="font-display text-lg font-semibold tracking-tight">{PILLARS[pillar].short}</span>
                  <span className="text-sm text-ink-2">{PILLARS[pillar].name}</span>
                  <span className="ml-auto font-mono text-2xs text-ink-3">{count}/{own.length}</span>
                </button>
                <ul className="grid gap-3 p-3 sm:grid-cols-2 sm:p-4">
                  {own.map((agent) => {
                    const on = selected.has(agent.id);
                    return (
                      <li key={agent.id} className="rounded-[3px] border border-rule">
                        <label className={`flex min-h-full cursor-pointer gap-3.5 px-5 py-5 transition-colors ${on ? "bg-soft/50" : "hover:bg-mist"}`}>
                          <input type="checkbox" className="sr-only" checked={on} onChange={(e) => toggle([agent.id], e.target.checked)} />
                          <span className="pt-0.5"><Checkbox state={on ? "on" : "off"} /></span>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-2">
                              <span className="text-signal"><AgentIcon id={agent.id} size={15} /></span>
                              <span className="text-base font-semibold">{agent.name}</span>
                              <span className="ml-auto font-mono text-2xs text-ink-3">{agent.id}</span>
                            </span>
                            <span className="mt-1.5 block text-sm leading-relaxed text-ink-2">{agent.question}</span>
                            <span className="mt-2 block text-xs text-ink-3">
                              {agent.checks.length} checks{!agent.counts_toward_readiness && ", observation only"}
                            </span>
                          </span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              </fieldset>
            );
          })}
        </div>
      </section>

      </div>
      {/* Plan remains visible below selection without covering the form. */}
      <div className="mt-12 rounded-[4px] border border-rule bg-canvas p-6 sm:p-8">
        <h2 className="font-display text-xl font-semibold">Run plan</h2>
          <dl className="mt-5 grid gap-x-10 gap-y-5 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-ink-3">Agents</dt>
              <dd className="font-semibold">{selected.size} of {agents.length}</dd>
            </div>
            <div>
              <dt className="text-ink-3">Collectors that will run</dt>
              <dd className="font-mono text-xs font-semibold" title={plan.planned.map((c) => c.name).join(", ")}>
                {plan.planned.length ? plan.planned.map((c) => c.id).join(" ") : "None"}
              </dd>
            </div>
            <div>
              <dt className="text-ink-3">External services</dt>
              <dd className="font-semibold">{plan.services.length ? plan.services.join(", ") : "None"}</dd>
            </div>
            <div>
              <dt className="text-ink-3">Intelligence report</dt>
              <dd className="font-semibold">{selected.size >= 2 ? "Included" : "Needs 2 or more agents"}</dd>
            </div>
          </dl>
      </div>
    </form>
  );
}
