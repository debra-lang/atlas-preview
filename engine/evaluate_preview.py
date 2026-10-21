#!/usr/bin/env python3
"""Local PREVIEW of what the AI evaluation + routing would do with queued items. Nothing is published, held, archived or committed.

Runs the production evaluator on a TEMPORARY COPY of the queue (so the repo's queue.json is never modified), then applies the real routing rules to each
result and writes a report to --out. Needs ANTHROPIC_API_KEY in your environment and spends API credits (one call per item, plus a 1-token preflight).
The report contains raw AI evaluation output: keep it local, do not commit it (the repo is public).

Usage:  python engine/evaluate_preview.py --limit 5 --out preview.json
        python engine/evaluate_preview.py --ids pubmed-42894823,ctgov-NCT07877701-2026-10-16 --out preview.json
"""
import json, shutil, sys, tempfile
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE))
import evaluate_queue, weekly_cycle  # noqa: E402


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


limit = int(arg("--limit", "5"))
ids = [i for i in (arg("--ids", "") or "").split(",") if i]
out = arg("--out", "evaluation-preview.json")
root = ENGINE.parent
queue = json.loads((root / "data" / "review-queue" / "queue.json").read_text(encoding="utf-8"))
if ids:
    queue["items"] = [it for it in queue["items"] if it["id"] in ids]
tmp = Path(tempfile.mkdtemp(prefix="te-preview-"))
tq = tmp / "queue.json"
tq.write_text(json.dumps(queue), encoding="utf-8")
evaluate_queue.QUEUE = tq                       # the evaluator reads/writes THIS copy only
done, reason = evaluate_queue.main(limit=limit)
evaluated = json.loads(tq.read_text(encoding="utf-8"))["items"]
c = weekly_cycle.Cycle(root)
register = c.published_register()
study_ids = {s["id"] for s in c.load("data/studies.json", [])}
rows = []
for it in evaluated:
    if not it.get("evaluation"):
        continue
    r, why = c.route(it, register, study_ids)
    rows.append({"id": it["id"], "title": it["title"], "url": it.get("url"), "wouldRoute": r, "because": why, "evaluation": it["evaluation"]})
counts = {}
for r in rows:
    counts[r["wouldRoute"]] = counts.get(r["wouldRoute"], 0) + 1
Path(out).write_text(json.dumps({"evaluator": dict(evaluate_queue.LAST_RUN), "reason": reason, "wouldRouteCounts": counts, "items": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
shutil.rmtree(tmp, ignore_errors=True)
print(f"Preview written to {out}: {len(rows)} item(s) evaluated; would route: {counts}. Repo files were not modified.")
if reason:
    print("Evaluator note:", reason)
sys.exit(0 if rows else 1)
