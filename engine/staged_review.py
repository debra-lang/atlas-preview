#!/usr/bin/env python3
"""Tinnitus Evidence — staged (owner-approved) publication of AI-evaluated items.

In STAGED mode (the default whenever evaluation is enabled; see engine/eval_settings.json "mode") the weekly cycle evaluates items but publishes
NOTHING from them. Each evaluated item is written to a private review store instead:

  data/review-queue/staged.json.enc   AES-256 encrypted with the STATE_KEY repository secret (the repo is public, like held.json.enc; 600,000 PBKDF2 iterations).
                                      Use a LONG RANDOM STATE_KEY: ciphertext in a public repository can be attacked offline, so passphrase strength is the only protection.
  data/review-queue/decisions.json    the owner's decisions (public file: only ids, decisions, hash and any text the owner chooses to correct)

The owner reads the staged items locally, then records one decision per item. A decision is bound to a hash of the exact evaluation that was
reviewed, so a later or different evaluation of the same item can never be published by an old approval.

  approve   apply the proposed outcome (publish / hold / archive / irrelevant)
  correct   approve after replacing wording fields (allowlist below; ratings, rankings, safety flags and evidence fields cannot be edited here)
  reject    never publish; the item leaves the review store (its id stays in known_ids, so it is not scanned again)
  requeue   discard the evaluation and send the item back to the queue for a fresh evaluation
  release   (restricted, OFF by default; see engine/source_release.py) publish a clean low-risk item the model declined to verify, after DOCUMENTED verification against the source;
            can never override a Level 3 hold, a safety flag, an unsupported claim, inadequate evidence or any other mandatory hold

Owner use (PowerShell, the key never leaves your machine):
  $env:STATE_KEY = Read-Host "STATE_KEY"          # or set it however you set it before
  python engine/staged_review.py export --out staged-review.md
  python engine/staged_review.py decide <item-id> approve
  python engine/staged_review.py decide <item-id> correct --set weeklyTitle="..." --set whyMatters="..."
  python engine/staged_review.py decide <item-id> reject --note "reason"
then commit data/review-queue/decisions.json; the next cycle applies it (Actions > Weekly research cycle > Run workflow).
"""
import argparse, hashlib, json, os, subprocess, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGED_REL = "data/review-queue/staged.json"
DECISIONS_REL = "data/review-queue/decisions.json"
STAGEABLE = ("publish", "publish-under-eval", "hold", "archive", "irrelevant", "dup")
OVERRIDES = {   # proposed outcome -> outcomes the owner may change it to (downgrades only; there is no upgrade to publish)
    "publish": ("hold", "archive", "irrelevant"), "publish-under-eval": ("hold", "archive", "irrelevant"),
    "hold": (), "archive": ("hold",), "irrelevant": ("hold", "archive"), "dup": ("hold",)}
ENUM_CORRECTIONS = {
    "importance": ["Potentially Important", "Interesting but Early", "Confirms Previous Evidence", "Negative Result", "Does Not Change Current Evidence"],
    "comparisonType": ["between-group", "within-group only", "none", "Not reported"],
    "studyQuality": ["high", "moderate", "low", "not-a-study"],
    "controlQuality": ["sham/placebo-controlled", "active-control", "no-control", "n/a"],
    "blinded": ["double", "single", "none", "unclear", "n/a"],
}
TEXT_CORRECTIONS = ("weeklyTitle", "whyMatters", "whatIsNew", "numericalResult", "population", "sampleSize", "conflictOfInterest",
                    "summaryForAdmin", "safetyObservations", "primaryEndpoint", "secondaryEndpoints", "otherOutcomes", "clinicalSignificance", "affectedTreatment")
LIST_CORRECTIONS = ("mainLimitations",)
# deliberately NOT editable here: proposedScoreChange, proposedRankChange, changeClass, safetySignal, evidenceDirection, relevanceCategory,
# notRelevant, duplicateOf, confidence, factuallyVerified, sourceChecks


def eval_hash(entry):
    """Hash of exactly what the owner reviews: the evaluation, what the model was given, and the proposed outcome."""
    item = entry.get("item") or {}
    blob = json.dumps({"id": item.get("id"), "evaluation": item.get("evaluation"), "evalInput": item.get("evalInput"),
                       "proposedRoute": entry.get("proposedRoute")}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def make_entry(item, route, reason, weekly_preview, now=None):
    e = {"id": item["id"], "stagedAt": now or datetime.now().isoformat(timespec="seconds"), "proposedRoute": route, "reason": reason,
         "weeklyPreview": weekly_preview, "item": item}
    e["evalHash"] = eval_hash(e)
    return e


def validate_corrections(corr):
    """-> (clean dict, list of error strings). Anything outside the allowlist is an error and nothing is applied."""
    clean, errors = {}, []
    for k, v in (corr or {}).items():
        if k in ENUM_CORRECTIONS:
            match = next((o for o in ENUM_CORRECTIONS[k] if isinstance(v, str) and o.lower() == v.strip().lower()), None)
            if match is None:
                errors.append(f"{k}: must be one of {ENUM_CORRECTIONS[k]}")
            else:
                clean[k] = match
        elif k in TEXT_CORRECTIONS:
            if not isinstance(v, str) or not v.strip() or len(v) > 2000:
                errors.append(f"{k}: must be non-empty text of at most 2000 characters")
            else:
                clean[k] = v.strip()
        elif k in LIST_CORRECTIONS:
            if not isinstance(v, list) or not v or len(v) > 12 or not all(isinstance(x, str) and x.strip() and len(x) <= 400 for x in v):
                errors.append(f"{k}: must be a list of 1-12 short texts")
            else:
                clean[k] = [x.strip() for x in v]
        else:
            errors.append(f"{k}: not editable through a correction (ratings, rankings, safety flags and evidence fields can only change through a separate reviewed change)")
    return clean, errors


def resolve(decision, entry, blocked_reason=None, release_check=None):
    """Pure decision logic. Returns {'status': applied|stale|blocked|invalid, 'action': publish|publish-under-eval|hold|archive|irrelevant|dup|reject|requeue|None,
    'message': str, 'item': item-with-corrections-applied}."""
    d = (decision.get("decision") or "").lower()
    if entry is None:
        return {"status": "invalid", "action": None, "message": "no staged item with this id", "item": None}
    if decision.get("evalHash") != entry.get("evalHash"):
        return {"status": "stale", "action": None, "message": "the decision does not match the staged evaluation (hash differs); not applied", "item": None}
    if d not in ("approve", "correct", "reject", "requeue", "release"):
        return {"status": "invalid", "action": None, "message": f"unknown decision '{d}'", "item": None}
    if d in ("reject", "requeue"):
        return {"status": "applied", "action": d, "message": d, "item": entry["item"]}
    if blocked_reason:
        return {"status": "blocked", "action": None, "message": blocked_reason, "item": None}
    if d == "release":
        ok, problems, rel_item = release_check(decision, entry) if release_check else (False, ["the source-verified release path is not available here"], None)
        if not ok:
            return {"status": "invalid", "action": None, "message": "release refused: " + "; ".join(problems), "item": None}
        return {"status": "applied", "action": "publish", "message": "published after documented source verification (editorial check, not clinical review)", "item": rel_item}
    item = json.loads(json.dumps(entry["item"]))
    if d == "correct":
        clean, errors = validate_corrections(decision.get("corrections"))
        if errors or not clean:
            return {"status": "invalid", "action": None, "message": "; ".join(errors) or "no corrections supplied", "item": None}
        item["evaluation"].update(clean)
        item["ownerCorrected"] = sorted(clean)
    action = entry["proposedRoute"]
    ov = decision.get("routeOverride")
    if ov:
        if ov not in OVERRIDES.get(action, ()):
            return {"status": "invalid", "action": None, "message": f"cannot change '{action}' to '{ov}' (allowed: {list(OVERRIDES.get(action, ())) or 'none'})", "item": None}
        action = ov
    if action not in STAGEABLE:
        return {"status": "invalid", "action": None, "message": f"proposed outcome '{action}' cannot be approved here", "item": None}
    return {"status": "applied", "action": action, "message": action, "item": item}


# ------------------------------------------------------------------ encryption (same format as the workflow's held.json.enc)
ITER = "600000"   # PBKDF2 iterations for the staged store (a NEW file, so it can be stronger than held.json.enc's default); the workflow uses the same value


def _openssl():
    return os.environ.get("OPENSSL", "openssl")


def decrypt_bytes(enc_path, key_env="STATE_KEY"):
    if not os.environ.get(key_env):
        raise RuntimeError(f"environment variable {key_env} is not set (it is the same passphrase as the STATE_KEY repository secret)")
    p = subprocess.run([_openssl(), "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", ITER, "-in", str(enc_path), "-pass", f"env:{key_env}"], capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("could not decrypt (wrong STATE_KEY?): " + p.stderr.decode("utf-8", "replace")[:200])
    return p.stdout


def encrypt_file(plain_path, enc_path, key_env="STATE_KEY"):
    p = subprocess.run([_openssl(), "enc", "-aes-256-cbc", "-pbkdf2", "-iter", ITER, "-salt", "-in", str(plain_path), "-out", str(enc_path), "-pass", f"env:{key_env}"], capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("could not encrypt: " + p.stderr.decode("utf-8", "replace")[:200])


def load_staged(root=ROOT, key_env="STATE_KEY"):
    root = Path(root)
    plain, enc = root / STAGED_REL, root / (STAGED_REL + ".enc")
    if plain.exists():
        return json.loads(plain.read_text(encoding="utf-8"))
    if enc.exists():
        return json.loads(decrypt_bytes(enc, key_env).decode("utf-8"))
    return {"items": []}


# ------------------------------------------------------------------ review packet (markdown, local only)
def _fmt(v):
    if isinstance(v, list):
        return "\n".join("  - " + str(x) for x in v)
    return str(v)


def release_context(root):
    """Settings and tracked treatment ids for the restricted release path, read from the repository."""
    root = Path(root)
    try:
        settings = json.loads((root / "engine" / "eval_settings.json").read_text(encoding="utf-8"))
    except Exception:
        settings = {}
    try:
        tracked = {t["id"] for t in json.loads((root / "data" / "treatments.json").read_text(encoding="utf-8"))}
    except Exception:
        tracked = set()
    return settings, tracked


def render_review(staged, root=None):
    import source_release
    settings, tracked = release_context(root or ROOT)
    out = ["# Staged AI evaluations awaiting your decision", "",
           "PRIVATE: this file contains unpublished AI output. Do not commit or share it. Nothing here is public until you approve it.", ""]
    for e in staged.get("items", []):
        it, ev = e["item"], e["item"].get("evaluation", {})
        sc = ev.get("sourceChecks") or {}
        w = e.get("weeklyPreview") or {}
        out += [f"## {it.get('title', e['id'])}", f"`{e['id']}`  |  proposed outcome: **{e['proposedRoute'].upper()}**  |  reason: {e['reason']}  |  staged {e['stagedAt']}",
                f"Source: {it.get('url', '')}", f"Evaluation hash (decisions are bound to it): `{e['evalHash']}`", ""]
        if w:
            out += ["### What would become public if approved", f"**{w.get('title', '')}**  ({w.get('importance', '')})", w.get("summary", ""), "",
                    "Why it matters: " + w.get("whyMatters", ""), ""]
            d = w.get("detail", {})
            for k in ("studyType", "population", "sampleSize", "control", "primaryEndpoint", "comparisonType", "loudnessOutcome", "distressOutcome", "safety", "limitations", "funding"):
                if k in d:
                    out.append(f"- {k}: {_fmt(d[k])}")
            out.append("")
        ei = it.get("evalInput") or {}
        out += ["### Automated source checks (code, independent of the AI)",
                f"- primary record retrieved: {sc.get('recordFetched')}; completeness: {sc.get('completeness')}; critical sections missing: {sc.get('criticalOmitted')}",
                f"- record carries this item's identifier: {sc.get('identifierMatchesItem')}; registry results posted: {sc.get('hasResults')}; record text hash: {ei.get('recordHash')}",
                f"- numbers not found in the record: {sc.get('ungroundedNumbers') or 'none'}",
                f"- novelty/authority claims not made by the record: {sc.get('unsupportedTerms') or 'none'}",
                f"- advisory (names not found in record/database): {[n['name'] for n in sc.get('ungroundedNames', [])] or 'none'}; advisory numbers: {sc.get('advisoryNumbers') or 'none'}",
                f"- advisory (outcome domains named but absent from the record): {sc.get('ungroundedDomainTerms') or 'none'}; compound conflict-of-interest label: {sc.get('compoundCoiLabel') or 'none'}",
                f"- Level 3 triggers / flags: {ev.get('escalation') or 'none'}; article not in English (the abstract shown is an English translation supplied with the record; read it as you would any abstract): {sc.get('nonEnglishAbstract')}",
                f"- enumerated fields repaired: {sc.get('enumFixes') or 'none'}",
                f"- adequacy of the EVIDENCE in the record (a separate question from whether the report is faithful to it): {(sc.get('evidenceAdequacy') or {}).get('level', 'not assessed')}"
                + (f" ({'; '.join((sc.get('evidenceAdequacy') or {}).get('reasons') or [])})" if (sc.get('evidenceAdequacy') or {}).get('reasons') else "")
                + (f"; the model's own 'verified' answer ({ev.get('factuallyVerifiedModel')}) was overridden to false" if ev.get("factuallyVerifiedModel") is not None else ""), "",
                "### Model self-assessment (NOT verification: the model checked nothing outside its input)",
                f"- factuallyVerified: {ev.get('factuallyVerified')} - {ev.get('factuallyVerifiedReason', '')}",
                f"- confidence: model said {ev.get('confidenceModel')}, working value {ev.get('confidence')}", "",
                "### Evaluator's own notes",
                f"- admin summary: {ev.get('summaryForAdmin', '')}", f"- relevance category: {ev.get('relevanceCategory')}; change class: {ev.get('changeClass')}; proposed score/rank change: {ev.get('proposedScoreChange')}/{ev.get('proposedRankChange')}",
                f"- limitations: {_fmt(ev.get('mainLimitations', []))}", "",
                *release_block(e, tracked, settings),
                "### Decide", "```", f"python engine/staged_review.py decide {e['id']} approve", f"python engine/staged_review.py decide {e['id']} correct --set whyMatters=\"...\"",
                f"python engine/staged_review.py decide {e['id']} reject --note \"...\"", f"python engine/staged_review.py decide {e['id']} requeue", "```", ""]
    if not staged.get("items"):
        out.append("(nothing is staged)")
    return "\n".join(out)


def release_block(e, tracked, settings):
    """Shown only for plain holds. When the path is off it says so; when on, it shows eligibility and, if eligible, the exact text, its hash and the command."""
    import source_release
    if e.get("proposedRoute") != "hold":
        return []
    ok, why = source_release.eligibility(e, tracked, settings)
    if not source_release.settings_on(settings):
        return ["### Restricted source-verified release: switched off", ""]
    if not ok:
        return ["### Restricted source-verified release: NOT eligible", *[f"- {w}" for w in why], ""]
    t = source_release.public_text(e["item"])
    return ["### Restricted source-verified release: ELIGIBLE (editorial check, never a clinical review)",
            "The code accepts everything about this item except that the model declined to call it verified. If you publish it, you document that YOU checked it against the source:",
            f"- public text that would appear: {json.dumps({k: t[k] for k in ('title', 'importance', 'whyMatters', 'summary')}, ensure_ascii=False)}",
            f"- text hash: `{source_release.text_hash(e['item'])}`", *[f"- check: {source_release.CHECK_TEXT[c]}" for c in source_release.REQUIRED_CHECKS],
            "```", f"python engine/staged_review.py decide {e['id']} release --pmid {e['id'].split('-', 1)[-1]} --text-hash {source_release.text_hash(e['item'])} " + " ".join(f"--checked {c}" for c in source_release.REQUIRED_CHECKS) + " --not-clinical-review --reviewer \"site editor\"", "```", ""]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export"); ex.add_argument("--out", required=True); ex.add_argument("--key-env", default="STATE_KEY"); ex.add_argument("--root", default=str(ROOT))
    de = sub.add_parser("decide"); de.add_argument("id"); de.add_argument("decision", choices=["approve", "correct", "reject", "requeue", "release"])
    de.add_argument("--pmid"); de.add_argument("--text-hash"); de.add_argument("--checked", action="append", default=[]); de.add_argument("--not-clinical-review", action="store_true"); de.add_argument("--reviewer", default="")
    de.add_argument("--hash"); de.add_argument("--set", action="append", default=[], metavar="field=value"); de.add_argument("--route", choices=["hold", "archive", "irrelevant"])
    de.add_argument("--note", default=""); de.add_argument("--key-env", default="STATE_KEY"); de.add_argument("--root", default=str(ROOT))
    a = ap.parse_args(argv)
    root = Path(a.root)
    staged = load_staged(root, a.key_env)
    if a.cmd == "export":
        Path(a.out).write_text(render_review(staged, root), encoding="utf-8")
        print(f"{len(staged.get('items', []))} staged item(s) written to {a.out} (private; do not commit it)")
        return 0
    entry = next((e for e in staged.get("items", []) if e["id"] == a.id), None)
    if entry is None:
        print(f"no staged item with id {a.id}", file=sys.stderr); return 2
    if a.hash and a.hash != entry["evalHash"]:
        print("the hash you gave does not match the staged evaluation; re-export and review again", file=sys.stderr); return 2
    corr = {}
    for kv in a.set:
        k, _, v = kv.partition("=")
        corr[k.strip()] = [x.strip() for x in v.split("||")] if k.strip() in LIST_CORRECTIONS else v
    dec = {"id": a.id, "decision": a.decision, "evalHash": entry["evalHash"], "decidedAt": datetime.now().isoformat(timespec="seconds")}
    if corr:
        dec["corrections"] = corr
    if a.route:
        dec["routeOverride"] = a.route
    if a.note:
        dec["note"] = a.note[:300]
    check = None
    if a.decision == "release":
        import source_release
        dec.update({"pmid": a.pmid or "", "textHash": a.text_hash or "", "checked": a.checked, "notClinicalReview": bool(a.not_clinical_review), "reviewer": a.reviewer})
        settings, tracked = release_context(root)
        check = lambda d, e: source_release.release(d, e, tracked, settings)   # noqa: E731
    r = resolve(dec, entry, release_check=check)
    if r["status"] != "applied":
        print(f"not recorded: {r['message']}", file=sys.stderr); return 2
    p = root / DECISIONS_REL
    cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"decisions": []}
    cur["decisions"] = [d for d in cur["decisions"] if d.get("id") != a.id] + [dec]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"recorded: {a.decision} for {a.id} -> outcome '{r['action']}'. Commit {DECISIONS_REL} to apply it at the next cycle.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
