#!/usr/bin/env python3
"""Tinnitus Evidence — weekly editorial digest (local page generated on YOUR computer; nothing is hosted, nothing is decrypted in a browser).

Reads data/engine-status.json (public counts), the encrypted staged and held stores (decrypted in memory with STATE_KEY from your environment) and the usage ledger,
and writes ONE self-contained HTML page: a status line, the week's numbers, what needs you, important findings, what is waiting, cost, health.
Every number is computed here by code from the engine's own records; no AI writes any figure. All text from records is HTML-escaped. The page contains no script,
makes no network request and has no form: decisions are made with the commands it shows (staged_review.py decide ...).

  $env:STATE_KEY = Read-Host "STATE_KEY"        # hidden prompt, the same passphrase as the repository secret
  python engine/weekly_digest.py --out weekly-digest.html          # private: contains unpublished AI output; do not commit or share it

Definitions (week = the last 7 days):
  discovered/screened   items the scan found this run (engine-status 'newItems'); screened = every one went through the free screens and, if needed, the evaluator
  automatic (Level 1)   duplicates + off-topic + archived context + uncited correction notices: handled by deterministic rules or by a validated classification, none published
  awaiting verification items staged with a proposed publish/archive/irrelevant/duplicate outcome: you read or sample them (Level 2)
  needs you (Level 2)   items proposed 'hold' or 'publish-under-evaluation' that carry no Level 3 trigger, and every system problem
  waiting for clinical review (Level 3)   anything with a Level 3 trigger or a model-proposed score/rank/major/safety change, every held item (including correction or
                        retraction notices about cited studies). Shown separately and WITHOUT decision commands: the owner's approval alone does not release them; a qualified
                        clinician decides. The list is always shown in full, with the age of the oldest, so it cannot grow unnoticed.
"""
import argparse, html, json, os, subprocess, sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ITER = {"held.json.enc": None, "staged.json.enc": "600000"}


def _load_enc(path, iters, keyenv="STATE_KEY"):
    if not path.exists():
        return {"items": []}
    if not os.environ.get(keyenv):
        raise RuntimeError(f"{keyenv} is not set (it is the same passphrase as the STATE_KEY repository secret)")
    c = ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2"] + (["-iter", iters] if iters else []) + ["-in", str(path), "-pass", f"env:{keyenv}"]
    p = subprocess.run(c, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"{path.name} cannot be decrypted (wrong STATE_KEY?)")
    return json.loads(p.stdout.decode("utf-8"))


def _read(root, rel, default):
    try:
        return json.loads((Path(root) / rel).read_text(encoding="utf-8"))
    except Exception:
        return default


def load_inputs(root):
    root = Path(root)
    base = root / "data" / "review-queue"
    staged = json.loads((base / "staged.json").read_text(encoding="utf-8")) if (base / "staged.json").exists() else _load_enc(base / "staged.json.enc", ITER["staged.json.enc"])
    held = json.loads((base / "held.json").read_text(encoding="utf-8")) if (base / "held.json").exists() else _load_enc(base / "held.json.enc", ITER["held.json.enc"])
    return _read(root, "data/engine-status.json", {}), staged, held, _read(root, "engine/usage-ledger.json", {"runs": []})


def load_evidence(root):
    return _read(Path(root), "engine/triage-evidence.json", {})


def load_catalogued(root, limit=60):
    """Records archived by triage rule C1 (preserved, not AI-evaluated): the most recent first, with their reason. Public data only."""
    try:
        arch = json.loads((Path(root) / "data" / "review-queue" / "archive.json").read_text(encoding="utf-8")).get("items", [])
    except Exception:
        return []
    return [{"id": (a.get("item") or {}).get("id"), "title": (a.get("item") or {}).get("title"), "reason": a.get("reason"), "archivedAt": a.get("archivedAt")}
            for a in arch if str(a.get("reason", "")).startswith("catalogued")][:limit]


def _recent(ts, today, days=7):
    try:
        return datetime.fromisoformat(ts).date() >= today - timedelta(days=days)
    except (TypeError, ValueError):
        return True


def _age(ts, today):
    try:
        return max(0, (today - datetime.fromisoformat(ts).date()).days)
    except (TypeError, ValueError):
        return None


CLINICAL_STALE_DAYS = 30


def build_digest(status, staged, held, ledger, today=None, budget_usd=10.0, release=None, catalogued=None, evidence=None):
    today = today or date.today()
    ev = status.get("evaluation") or {}
    notices = status.get("notices") or {"cited": 0, "uncited": 0, "unresolved": 0}
    st_items = [e for e in staged.get("items", []) if _recent(e.get("stagedAt"), today, 400)]
    attention, waiting, clinical = [], [], []
    for e in st_items:
        it, evl = e["item"], e["item"].get("evaluation", {})
        trig = [t for t in (evl.get("escalation") or []) if t.get("tier") == "level3"]
        l3 = [f"{t['kind']}: {t['detail']}" for t in trig]
        if evl.get("changeClass") == "major":
            l3.append("the model classed the change as major")
        if evl.get("proposedScoreChange") or evl.get("proposedRankChange"):
            l3.append("the model proposed a score or rank change")
        if evl.get("safetySignal"):
            l3.append("possible safety signal")
        card = {"id": e["id"], "title": it.get("title", e["id"]), "route": e["proposedRoute"], "reason": e.get("reason", ""), "hash": e.get("evalHash"), "level3": l3,
                "importance": evl.get("importance"), "confidence": evl.get("confidence"), "preview": (e.get("weeklyPreview") or {}).get("title"), "ageDays": _age(e.get("stagedAt"), today),
                "release": (release or {}).get(e["id"])}
        if l3:
            clinical.append(card)
        else:
            (attention if e["proposedRoute"] in ("hold", "publish-under-eval") else waiting).append(card)
    for h in held.get("items", []):                                                     # every held item stays listed until it is resolved, not only this week's
        it = h.get("item", {})
        clinical.append({"id": it.get("id"), "title": it.get("title", it.get("id")), "route": "held", "reason": h.get("reason", ""), "hash": None,
                         "level3": (["held for language (rule R4): the abstract is not in English; it needs a person who can read it, not a clinician"] if str(h.get("reason", "")).startswith("R4")
                                    else ["held (could change a conclusion or concerns a cited study)"]),
                         "importance": None, "confidence": None, "preview": None, "ageDays": _age(h.get("heldAt"), today)})
    problems = []
    if ev.get("state") in ("failed", "degraded", "blocked-gate"):
        problems.append(f"AI evaluation is {ev['state']}: {ev.get('reason') or 'see the run log'}")
    if ev.get("recordUnavailable"):
        problems.append(f"{ev['recordUnavailable']} record(s) could not be fetched and were not evaluated (retried next week)")
    problems += [f"source '{s['name']}' did not answer: {s['error']}" for s in status.get("sources", []) if s.get("error")]
    problems += [str(x) for x in status.get("errors", []) if not str(x).startswith("AI evaluation")]
    if not status.get("lastSuccess"):
        problems.append("no successful run is recorded yet")
    auto = (status.get("rejectedDuplicates", 0) + status.get("rejectedIrrelevant", 0) + status.get("archived", 0) + notices.get("uncited", 0))
    month = today.strftime("%Y-%m")
    mtd = round(sum(r.get("estimatedCostUSD", 0) or 0 for r in ledger.get("runs", []) if str(r.get("date", "")).startswith(month)), 2)
    usage = ev.get("usage") or {}
    important = [c for c in waiting if c["route"] == "publish" and c["importance"] in ("Potentially Important", "Negative Result", "Interesting but Early")][:5]
    ages = [c["ageDays"] for c in clinical if c.get("ageDays") is not None]
    oldest = max(ages) if ages else 0
    state = "red" if problems and (ev.get("state") in ("failed", "blocked-gate") or len(problems) > 2) else "amber" if (problems or attention or oldest > CLINICAL_STALE_DAYS) else "green"
    return {"date": today.isoformat(), "state": state, "discovered": status.get("newItems", 0), "screened": status.get("newItems", 0), "automatic": auto, "awaitingVerification": len(waiting),
            "needsYou": len(attention), "clinicalWaiting": clinical, "clinicalWaitingCount": len(clinical), "clinicalOldestDays": oldest, "onHold": status.get("paused", 0), "attention": attention, "waiting": waiting, "important": important, "problems": problems,
            "evaluation": {"state": ev.get("state"), "mode": ev.get("mode"), "attempted": ev.get("attempted", 0), "succeeded": ev.get("succeeded", 0), "failed": ev.get("failed", 0), "screenedWithoutAI": ev.get("screenedWithoutAI", 0)},
            "costWeekUSD": round(usage.get("estimatedCostUSD", 0) or 0, 3), "costMonthToDateUSD": mtd, "budgetUSD": budget_usd, "lastScan": status.get("lastSuccess") or status.get("lastAttempt"),
            "notices": notices, "triage": status.get("triage") or {}, "catalogued": catalogued or [], "triageEvidence": evidence or {}, "notMeasuredYet": ["missed-research check against an independent query", "random audit of automatic decisions", "reviewer-vigilance test with seeded known-bad items"]}


def _e(x):
    return html.escape(str(x if x is not None else ""))


def triage_html(d):
    t, c, ev = d.get("triage") or {}, d.get("catalogued") or [], d.get("triageEvidence") or {}
    if not t and not c and not ev:
        return ""
    audit = ""
    if t.get("auditEvaluated"):
        audit = (f"<p>Audit sample: {t['auditEvaluated']} catalogue candidate(s) were evaluated anyway; the AI would have recommended <b>{t.get('auditWouldFeed', 0)}</b> of them for the public feed. "
                 "Any number above zero means the catalogue rule missed something: tell Claude.</p>")
    rows = "".join(f"<li>{_e(x['title'])} <span class='cmd'>({_e(x['id'])})</span></li>" for x in c[:40]) or "<li>None this run.</li>"
    if ev:
        audit += (f"<p>Prospective evidence so far (all runs): {ev.get('evaluated', 0)} catalogue candidate(s) evaluated anyway; the AI would have recommended <b>{ev.get('wouldFeed', 0)}</b> for the feed "
                  f"and held {ev.get('wouldHold', 0)}. Automatic archiving stays off until you decide, with this number and the list of those records in front of you (engine/triage-evidence.json).</p>")
    return (f"<h2>Catalogued without AI evaluation ({t.get('catalogued', len(c))} this run)</h2><p>Preserved in the archive with their reason, not lost and not judged. They are records in which tinnitus is a passing mention and that carry no trial, review, "
            "tracked-treatment or safety signal (rule C1). To have one evaluated: <span class='cmd'>python engine/triage.py promote &lt;id&gt;</span>.</p>" + audit + f"<ul>{rows}</ul>")


def render_html(d):
    colour = {"green": ("#e4f1ea", "#2f7a56", "Everything ran normally."), "amber": ("#fbefd9", "#a5600a", "Ran, but something needs your eyes."), "red": ("#f8e1df", "#a8322d", "Something is wrong: read the problems first.")}[d["state"]]
    clin = "".join(f"<div class='card clin'><h3>{_e(c['title'])}</h3><p><b>{_e(c['route'])}</b>: {_e(c['reason'])}" + (f" (waiting {c['ageDays']} day(s))" if c.get("ageDays") is not None else "") + "</p>"
                   + (f"<p>{_e('; '.join(c['level3']))}</p>" if c["level3"] else "") + "</div>" for c in d["clinicalWaiting"]) or "<p>Nothing is waiting.</p>"
    cards = lambda items: "".join(  # noqa: E731
        f"<div class='card'><h3>{_e(c['title'])}</h3><p><b>{_e(c['route'])}</b>: {_e(c['reason'])}</p>" + (f"<p>Level 3 triggers: {_e('; '.join(c['level3']))}</p>" if c["level3"] else "")
        + (f"<p class='cmd'>python engine/staged_review.py decide {_e(c['id'])} approve | correct | reject | requeue</p>" if c.get("hash") else "")
        + (("<p>Restricted source-verified release: <b>eligible</b> (editorial check only; the export packet shows the exact text, its hash and the command)</p>" if c["release"][0] else
            "<p>Restricted source-verified release: not eligible (" + _e("; ".join(c["release"][1][:3])) + ")</p>") if c.get("release") else "") + "</div>" for c in items) or "<p>Nothing.</p>"
    prob = "".join(f"<li>{_e(p)}</li>" for p in d["problems"]) or "<li>No errors recorded.</li>"
    ev = d["evaluation"]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tinnitus Evidence weekly digest {_e(d['date'])}</title>
<style>body{{font:16px/1.5 Segoe UI,system-ui,sans-serif;max-width:46rem;margin:1rem auto;padding:0 1rem;background:#f6f7f5;color:#1c2a33}}.b{{background:{colour[0]};color:{colour[1]};border:1px solid {colour[1]};padding:.7rem .9rem;border-radius:6px;font-weight:600}}
.g{{display:grid;grid-template-columns:repeat(4,1fr);gap:.6rem;margin:1rem 0}}.s{{background:#fff;border:1px solid #d9dfdc;border-radius:6px;padding:.6rem}}.s b{{display:block;font-size:1.6rem}}h2{{border-bottom:1px solid #d9dfdc;margin-top:1.6rem}}
.card{{background:#fff;border:1px solid #d9dfdc;border-left:5px solid #a5600a;padding:.5rem .8rem;margin:.5rem 0;border-radius:6px}}.clin{{border-left-color:#5b4a9e}}.cmd{{font-family:Consolas,monospace;font-size:.85rem;color:#5d6b73}}@media(max-width:560px){{.g{{grid-template-columns:repeat(2,1fr)}}}}</style></head><body>
<h1>Weekly digest, {_e(d['date'])}</h1><p>PRIVATE: contains unpublished AI output. Do not commit or share.</p>
<div class="b">{_e(colour[2])} Last scan: {_e(d['lastScan'])}. Evaluation: {_e(ev['state'])} ({_e(ev['mode'])} mode). Waiting for clinical review: {d['clinicalWaitingCount']}.</div>
<div class="g"><div class="s"><b>{d['discovered']}</b>discovered and screened</div><div class="s"><b>{d['automatic']}</b>handled automatically</div><div class="s"><b>{d['awaitingVerification']}</b>awaiting verification</div><div class="s"><b>{d['needsYou']}</b>need you</div></div>
<h2>Needs you ({d['needsYou']})</h2>{cards(d['attention'])}
<h2>Waiting for clinical review ({d['clinicalWaitingCount']})</h2><p>These items could change an evidence rating, concern safety or regulatory status, or affect a cited study. They stay held.
<b>Your approval alone does not release them</b>: a qualified clinician decides. Nothing is asked of you here; the list is shown in full so it cannot grow unnoticed (oldest: {d['clinicalOldestDays']} day(s)).</p>{clin}
<h2>Important new findings ({len(d['important'])})</h2>{cards(d['important'])}
<h2>Awaiting verification ({d['awaitingVerification']})</h2>{cards(d['waiting'])}
{triage_html(d)}
<h2>Cost and health</h2><ul><li>API cost this run: ${d['costWeekUSD']} (month to date ${d['costMonthToDateUSD']} of a ${d['budgetUSD']:.0f} budget); evaluations {ev['succeeded']}/{ev['attempted']} succeeded, {ev['failed']} failed; {ev['screenedWithoutAI']} handled without the AI.</li>
<li>Correction/retraction notices: {d['notices'].get('cited', 0)} about cited studies, {d['notices'].get('uncited', 0)} archived, {d['notices'].get('unresolved', 0)} unresolved. Items on hold by you: {d['onHold']}.</li></ul>
<h3>Problems</h3><ul>{prob}</ul><h3>Not measured yet</h3><ul>{''.join(f'<li>{_e(x)}</li>' for x in d['notMeasuredYet'])}</ul>
<p>Every number on this page is computed by code from the engine's own records.</p></body></html>"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True); ap.add_argument("--root", default=str(ROOT)); ap.add_argument("--json", action="store_true", help="also write the digest data next to the page")
    a = ap.parse_args(argv)
    status, staged, held, ledger = load_inputs(a.root)
    import source_release, staged_review
    settings, tracked = staged_review.release_context(a.root)
    release = {e["id"]: source_release.eligibility(e, tracked, settings) for e in staged.get("items", []) if e.get("proposedRoute") == "hold"} if source_release.settings_on(settings) else {}
    d = build_digest(status, staged, held, ledger, release=release, catalogued=load_catalogued(a.root), evidence=load_evidence(a.root))
    Path(a.out).write_text(render_html(d), encoding="utf-8")
    if a.json:
        Path(a.out).with_suffix(".json").write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"digest written to {a.out}: {d['discovered']} discovered, {d['automatic']} automatic, {d['awaitingVerification']} awaiting, {d['needsYou']} need you, state {d['state']} (private; do not commit)")


if __name__ == "__main__":
    main()
