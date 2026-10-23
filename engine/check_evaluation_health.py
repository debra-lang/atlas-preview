#!/usr/bin/env python3
"""Fail the CI job loudly when the weekly AI evaluation did not work. Run AFTER the cycle's results have been committed, so a red run can
never cost scanned items (the cycle itself still exits 0 and commits). Reads data/engine-status.json only; changes nothing.

Exit 1 when: evaluation state is 'failed' or 'blocked-gate'; or 'degraded' with at least half of the attempts failing; or the number of items
awaiting evaluation is at least BACKLOG_LIMIT. Otherwise exit 0 (warnings are printed for milder degradation).
"""
import json, os, sys
from pathlib import Path

BACKLOG_LIMIT = 25
MAX_DISABLED_DAYS = 45   # three missed runs on the 1st/15th schedule (was 21 days = three weekly runs)
status = json.loads((Path(__file__).resolve().parent.parent / "data" / "engine-status.json").read_text(encoding="utf-8"))
ev = status.get("evaluation")
if not ev:
    print("health: engine-status.json has no 'evaluation' block (older status format) - nothing to check.")
    sys.exit(0)
state, awaiting = ev.get("state"), ev.get("awaitingEvaluation", 0) or 0
attempted, failed = ev.get("attempted", 0) or 0, ev.get("failed", 0) or 0
problems, warnings = [], []
if state == "disabled":
    # Deliberately switched off by the owner: expected, so not a failure and the backlog is expected too. A safety net still fails the run if it stays off too long.
    since = ev.get("disabledSince")
    try:
        from datetime import date
        days = (date.today() - date.fromisoformat(str(since))).days if since else None
    except ValueError:
        days = None
    warnings.append(f"AI evaluation is SWITCHED OFF (engine/eval_settings.json, since {since or 'unknown'}); {awaiting} item(s) are waiting. Scanning continues.")
    if days is not None and days > MAX_DISABLED_DAYS and status.get("listings") is None:   # with automatic listings running, "AI off" is a deliberate steady state, not something forgotten
        problems.append(f"AI evaluation has been switched off for {days} days (limit {MAX_DISABLED_DAYS}); re-enable it or extend the limit deliberately.")
    awaiting = 0   # backlog is expected while disabled
elif state in ("failed", "blocked-gate"):
    problems.append(f"AI evaluation state is '{state}' ({ev.get('reason') or 'no reason recorded'}).")
elif state == "degraded":
    (problems if attempted and failed * 2 >= attempted else warnings).append(f"AI evaluation degraded: {failed} of {attempted} attempts failed {ev.get('errorClasses')}"
                                                                          + (f"; {ev.get('parseErrors')} answer(s) unusable {ev.get('failureKinds') or ''}" if ev.get("parseErrors") else "") + ".")
# Cost and answer-quality alerts (a run is red only for things that need a decision; everything else is a warning in the log and the digest)
kinds = ev.get("failureKinds") or {}
if kinds.get("truncated"):
    problems.append(f"{kinds['truncated']} AI answer(s) were cut off at the output ceiling; see the plan: raise the ceiling once, or investigate if two or more in one cycle.")
others = sum(n for k, n in kinds.items() if k != "truncated")
if others >= 2:
    problems.append(f"{others} AI answers were unusable in one cycle {kinds}.")
elif others == 1:
    warnings.append(f"1 AI answer was unusable {kinds}; it was held and not retried.")
if ev.get("nearMisses"):
    warnings.append(f"{ev['nearMisses']} AI answer(s) used over 75 % of the output ceiling (largest {ev.get('maxOutputTokens')} tokens).")
bud = ev.get("budget") or {}
if bud.get("fraction") is not None:
    if bud["fraction"] >= 1.0:
        problems.append(f"The monthly AI budget is used up: ${bud.get('spentUSD')} of ${bud.get('monthlyUSD')} estimated. Evaluation stays paused until next month or the budget is raised in eval_settings.json.")
    elif bud["fraction"] >= 0.6:
        warnings.append(f"{round(bud['fraction'] * 100)} % of the monthly AI budget is used (${bud.get('spentUSD')} of ${bud.get('monthlyUSD')}).")
for e in status.get("errors") or []:
    if "coverage gap" in str(e):      # a source was not scanned for longer than the maximum look-back: records may have been missed, so this is a red run, not a footnote
        problems.append(str(e))
if awaiting >= BACKLOG_LIMIT:
    problems.append(f"{awaiting} item(s) are awaiting evaluation (limit {BACKLOG_LIMIT}).")
elif awaiting:
    warnings.append(f"{awaiting} item(s) awaiting evaluation.")
nt = status.get("notices") or {}
if nt.get("cited"):
    warnings.append(f"{nt['cited']} correction/retraction notice(s) concern studies cited on this site - see the private held items (no record was changed).")
if nt.get("unresolved"):
    warnings.append(f"{nt['unresolved']} correction/retraction notice(s) could not be matched to an article - check manually (held privately).")
stg = status.get("staged") or {}
if stg.get("pending"):
    warnings.append(f"{stg['pending']} evaluated item(s) are staged for the owner's decision (oldest {stg.get('oldestDays', '?')} day(s)); nothing from them is public.")
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
