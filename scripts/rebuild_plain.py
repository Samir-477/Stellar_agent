"""Add plain-language site sentences ("On your /gold-loan page, a tap takes about 1.0 s to react") to finished
runs made before they existed. One model call per run; the rest of the intelligence report is kept as is.
Start it with LLM_MODE=live. Runs without an intelligence report (single-agent runs) are skipped: their issues
use the reviewed library and a template sentence.

Usage:
  LLM_MODE=live python scripts/rebuild_plain.py --run <run_id> [--run <run_id> ...]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.core.config import get_settings  # noqa: E402
from engine.llm import LLMClient  # noqa: E402
from engine.orchestrator import repo  # noqa: E402
from engine.plain import site_cases  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="append", required=True)
    args = parser.parse_args()
    settings = get_settings()
    if settings.llm_mode == "off":
        sys.exit("LLM_MODE is off: set LLM_MODE=live to write the sentences.")
    for run_id in args.run:
        report = repo.get_intelligence_report(run_id)
        if report is None:
            print(f"{run_id}: no intelligence report, skipped")
            continue
        llm = LLMClient(settings, cache_get=repo.llm_cache_get, cache_put=repo.llm_cache_put,
                        recorder=lambda call, rid=run_id: repo.record_llm_call(rid, None, call))
        findings = repo.list_findings(run_id)
        cases = site_cases(llm, findings)
        report["plain_cases"] = cases
        repo.save_intelligence_report(run_id, report)
        issues = sum(f["status"] in ("fail", "warn") for f in findings)
        print(f"{run_id}: {len(cases)} of {issues} issues have a site sentence written by the model")


if __name__ == "__main__":
    main()
