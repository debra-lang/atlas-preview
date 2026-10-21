#!/usr/bin/env python3
"""Fail the CI job loudly when the weekly AI evaluation did not work. Run AFTER the cycle's results have been committed, so a red run can
never cost scanned items (the cycle itself still exits 0 and commits). Reads data/engine-status.json only; changes nothing.

Exit 1 when: evaluation state is 'failed' or 'blocked-gate'; or 'degraded' with at least half of the attempts failing; or the number of items
awaiting evaluation is at least BACKLOG_LIMIT. Otherwise exit 0 (warnings are printed for milder degradation).
"""
import json, os, sys
from pathlib import Path

BACKLOG_LIMIT = 25
status = json.loads((Path(__file__).resolve().parent.parent / "data" / "engine-status.json").read_text(encoding="utf-8"))
ev = status.get("evaluation")
if not ev:
    print("health: engine-status.json has no 'evaluation' block (older status format) - nothing to check.")
    sys.exit(0)
state, awaiting = ev.get("state"), ev.get("awaitingEvaluation", 0) or 0
attempted, failed = ev.get("attempted", 0) or 0, ev.get("failed", 0) or 0
problems, warnings = [], []
if state in ("failed", "blocked-gate"):
    problems.append(f"AI evaluation state is '{state}' ({ev.get('reason') or 'no reason recorded'}).")
elif state == "degraded":
    (problems if attempted and failed * 2 >= attempted else warnings).append(f"AI evaluation degraded: {failed} of {attempted} attempts failed {ev.get('errorClasses')}.")
if awaiting >= BACKLOG_LIMIT:
    problems.append(f"{awaiting} item(s) are awaiting evaluation (limit {BACKLOG_LIMIT}).")
elif awaiting:
    warnings.append(f"{awaiting} item(s) awaiting evaluation.")
last_ok = ev.get("lastEvaluationSuccess", "never recorded")
lines = [f"AI evaluation: state={state}, attempted={attempted}, succeeded={ev.get('succeeded', 0)}, failed={failed}, awaiting={awaiting}, last fully successful evaluation: {last_ok}"]
lines += [f"PROBLEM: {p}" for p in problems] + [f"warning: {w}" for w in warnings]
print("\n".join(lines))
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a", encoding="utf-8") as f:
        f.write("### Weekly AI evaluation health\n\n" + "\n".join("- " + l for l in lines) + "\n")
for p in problems:
    print(f"::error title=Weekly AI evaluation is not working::{p}")
sys.exit(1 if problems else 0)
