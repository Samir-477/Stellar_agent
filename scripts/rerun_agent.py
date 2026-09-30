"""Run agents again on a finished run, from its stored evidence: no crawl and no search calls.

Use it after an agent is fixed, so an existing run shows the corrected result. Model calls follow
LLM_MODE (an agent that needs the model makes its usual calls), so start it with LLM_MODE=live.
The intelligence summary is not rebuilt; run scripts/rebuild_intelligence.py for that.

Usage:
  LLM_MODE=live python scripts/rerun_agent.py --run <run_id> --agent G5 [--agent A2] [--run <run_id> ...]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.core.config import get_settings  # noqa: E402
from engine.llm import LLMClient  # noqa: E402
from engine.orchestrator import repo  # noqa: E402
from engine.orchestrator.executor import rerun_agent  # noqa: E402
from engine.orchestrator.runner import make_env  # noqa: E402


def statuses(run_id: str, agent_id: str) -> dict[str, str]:
    return {f["check_id"]: f["status"] for f in repo.list_findings(run_id, agent_id)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="append", required=True)
    parser.add_argument("--agent", action="append", required=True)
    args = parser.parse_args()
    settings = get_settings()
    env = make_env(settings)
    for run_id in args.run:
        if repo.get_run(run_id) is None:
            print(f"{run_id}: not found")
            continue
        llm = None if settings.llm_mode == "off" else LLMClient(
            settings, cache_get=repo.llm_cache_get, cache_put=repo.llm_cache_put,
            recorder=lambda call, rid=run_id: repo.record_llm_call(rid, None, call))
        for agent_id in args.agent:
            before = statuses(run_id, agent_id)
            outcome = rerun_agent(env, run_id, agent_id, llm)
            after = statuses(run_id, agent_id)
            changed = {k: f"{before.get(k)} -> {v}" for k, v in after.items() if before.get(k) != v}
            print(f"{run_id} {agent_id}: {outcome['status']}, {outcome['findings']} findings, run "
                  f"{outcome['run_status']}; changed: {changed or 'none'}"
                  + (f"; validation: {outcome['validation_errors']}" if outcome["validation_errors"] else ""))


if __name__ == "__main__":
    main()
