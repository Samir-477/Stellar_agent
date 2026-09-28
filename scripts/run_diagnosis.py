"""Run a diagnosis from the command line (no dashboard needed).

Usage:
  python scripts/run_diagnosis.py --url https://example.com/page --name "Client" \
      --archetype hospitality --consent "who approved the crawl" [--agents S1] [--cap 25]

Creates the client (or reuses one with the same URL), runs the chosen agents
inline, and prints each agent's report summary. LLM usage follows LLM_MODE.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.core.db import connection  # noqa: E402
from engine.orchestrator import repo  # noqa: E402
from engine.orchestrator.planner import plan_run  # noqa: E402
from engine.orchestrator.runner import run_inline  # noqa: E402
from engine.registry import AGENTS  # noqa: E402


def main() -> None:
    # Task failures are logged by the runner; without this they'd be invisible from the command line.
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--archetype", choices=["hospitality", "loans", "retail", "logistics"])
    parser.add_argument("--consent", required=True, help="who confirmed the client allowed crawling")
    parser.add_argument("--agents", nargs="*", default=None, help="default: all registered agents")
    parser.add_argument("--cap", type=int, default=25)
    parser.add_argument("--reuse-snapshot", action="store_true",
                        help="reuse the client's latest snapshot; only missing collectors run")
    parser.add_argument("--refresh", nargs="*", default=[],
                        help="with --reuse-snapshot: collectors to re-run anyway (e.g. C2 after a parser change)")
    args = parser.parse_args()

    with connection() as conn:
        client = conn.execute("select * from clients where primary_url=%s order by created_at limit 1",
                              (args.url,)).fetchone()
    client = client or repo.create_client(args.name, args.url, archetype=args.archetype,
                                          crawl_consent_by=args.consent)
    agents = args.agents or sorted(AGENTS)
    snapshot = repo.latest_snapshot(str(client["id"])) if args.reuse_snapshot else None
    done = frozenset(snapshot["collectors_done"]) - set(args.refresh) if snapshot else frozenset()
    run = repo.create_run(str(client["id"]), "agent" if args.agents else "full", agents, args.cap,
                          plan_run(agents, done), snapshot_id=str(snapshot["id"]) if snapshot else None)
    if snapshot:
        print(f"reusing snapshot {snapshot['id']} (collectors already done: {sorted(done)})")
    print(f"client {client['id']}  run {run['id']}  agents {agents}")
    final = run_inline(str(run["id"]))
    print(f"run status: {final['status']}  tasks: {final['task_counts']}  tokens used: {final['tokens_used']}")
    if final.get("note"):
        print(f"note: {final['note']}")
    for agent_id in agents:
        report = repo.get_agent_report(str(run["id"]), agent_id)
        if not report:
            print(f"\n{agent_id}: no report")
            continue
        print(f"\n== {agent_id} {report['agent_name']}\n{report['verdict']}\nscorecard: {report['scorecard']}")
        for item in report["issues_to_fix"]:
            print(f"  FIX  [{item['severity']}] {item['check_id']} {item['title']}")
        for item in report["needs_attention"]:
            print(f"  ATTN [{item['severity'] or '-'}] {item['check_id']} {item['title']}")
        for item in report["whats_working"]:
            print(f"  OK   {item['check_id']} {item['title']}")


if __name__ == "__main__":
    main()
