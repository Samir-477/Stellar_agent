"""Rebuild a finished run's intelligence report from its stored findings.

No crawling and no search calls: one model call per run (the summary and client cards),
so start it with LLM_MODE=live. Use it when the report format or summary prompt changes.

Usage:
  LLM_MODE=live python scripts/rebuild_intelligence.py --run <run_id> [--run <run_id> ...]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.core.config import get_settings  # noqa: E402
from engine.llm import LLMClient  # noqa: E402
from engine.orchestrator import repo  # noqa: E402
from engine.orchestrator.executor import build_run_intelligence  # noqa: E402
from engine.orchestrator.runner import make_env  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="append", required=True)
    args = parser.parse_args()
    settings = get_settings()
    env = make_env(settings)
    for run_id in args.run:
        run_ctx = repo.run_context(run_id)
        if run_ctx is None:
            print(f"{run_id}: not found")
            continue
        llm = None if settings.llm_mode == "off" else LLMClient(
            settings, cache_get=repo.llm_cache_get, cache_put=repo.llm_cache_put,
            recorder=lambda call, rid=run_id: repo.record_llm_call(rid, None, call))
        failed = [f"{t['ref']}: {t['status']}" for t in repo.run_task_statuses(run_id)
                  if t["kind"] == "agent.reduce" and t["status"] != "succeeded"]
        report = build_run_intelligence(env, run_ctx, llm, failed)
        repo.save_intelligence_report(run_id, report)
        summary = report["executive_summary"]
        cards = summary.get("client_priorities", [])
        print(f"{run_id}: summary from {summary.get('source')}, {len(cards)} client cards "
              f"({sum(c['source'] == 'model' for c in cards)} worded by the model)"
              + (f", note: {summary['note']}" if summary.get("note") else ""))


if __name__ == "__main__":
    main()
