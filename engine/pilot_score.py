#!/usr/bin/env python3
"""Tinnitus Evidence - scoring of the 24-record pilot (local tool; prints AGGREGATE numbers; ids only on request). Free; no key; decides nothing.

  python pilot_score.py --final <pilot-final.csv> --records <records.json> --results <results.json> [--list-ids]

Pre-registered rule (PILOT-RULE.md): the pilot PASSES only if there are ZERO known unsafe publication recommendations and the run itself is valid.

  FEED     the pipeline recommends the item for the public feed (staged route publish or publish-under-eval).
  UNSAFE   a FEED item for which the checker's FINAL answers (or PubMed's own publication types) show ANY of: it is a notice; it has no abstract; it has explicit safety wording;
           it gives NO sample size, NO design and NO result figures although it is not a review, case report or letter (by PubMed publication type); the checker could not read
           its language; or its abstract text is not clearly English (language screen, rule R4).
  Reported, not gating: how many were recommended, how many clean records were held (and why), notices not handled as notices, safety records that were not escalated to Level 3,
  data-free primary studies not held. Any of those that look wrong is INVESTIGATED by a person; none is re-run automatically.
Verdicts: PASS | PASS WITH INVESTIGATION | FAIL | NOT SCORED (answers incomplete, results missing, or the run invalid)."""
import argparse, csv, json, sys
from math import comb
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import grounding, language_screen  # noqa: E402

KEYS = ["sample_size", "design", "results", "safety", "notice", "abstract"]
FEED = ("feed",)


def upper_bound(k, n, alpha=0.05):
    """Exact one-sided (1-alpha) upper bound for a proportion with k events in n."""
    if n == 0:
        return None
    lo, hi = 0.0, 1.0
    for _ in range(80):
        p = (lo + hi) / 2
        if sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1)) > alpha:
            lo = p
        else:
            hi = p
    return round(hi, 3)


def yes(v):
    return str(v or "").strip().lower() == "yes"


def exempt_by_type(pubtypes):
    return any(str(t).lower() in grounding.EXEMPT_PUBTYPES for t in pubtypes or [])


def score(final_rows, records, results, run_valid=True):
    R = {r["id"]: r for r in records}
    F = {r["id"]: r for r in final_rows}
    incomplete = sorted(i for i in R if i not in F or (not yes(F[i].get("cannot_read")) and not all((F[i].get(k) or "").strip().lower() in ("yes", "no") for k in KEYS)))
    missing = sorted(i for i in R if i not in results)
    feed = [i for i in R if i in results and results[i].get("outcome") in FEED]
    unsafe = []
    for i in feed:
        f, why = F.get(i, {}), []
        if yes(f.get("notice")): why.append("notice")
        if (f.get("abstract") or "").strip().lower() == "no": why.append("no-abstract")
        if yes(f.get("safety")): why.append("safety-wording")
        if all((f.get(k) or "").strip().lower() == "no" for k in ("sample_size", "design", "results")) and not exempt_by_type(R[i].get("pubtypes")):
            why.append("no-verifiable-specifics")
        if yes(f.get("cannot_read")): why.append("language-unverifiable")
        if language_screen.screen(R[i].get("text", ""))["hold"]: why.append("abstract-not-english")
        if why:
            unsafe.append((i, why))
    clean = [i for i in R if i in results and i in F and not yes(F[i].get("cannot_read")) and (F[i].get("abstract") or "").lower() == "yes" and not yes(F[i].get("notice")) and not yes(F[i].get("safety"))
             and sum(yes(F[i].get(k)) for k in ("sample_size", "design", "results")) >= 2 and not language_screen.screen(R[i].get("text", ""))["hold"]]
    unnecessary = [i for i in clean if results[i].get("outcome") != "feed"]
    by_cause = {}
    for i in unnecessary:
        by_cause.setdefault(results[i].get("primaryCause") or results[i].get("outcome") or "other", []).append(i)
    notices_h = [i for i in R if i in F and yes(F[i].get("notice"))]
    notices_bad = [i for i in notices_h if i in results and results[i].get("outcome") == "feed"]
    notices_unhandled = [i for i in notices_h if i in results and results[i].get("outcome") not in ("notice-held", "held", "not-feed", "language-held")]
    safety_h = [i for i in R if i in F and yes(F[i].get("safety"))]
    safety_not_l3 = [i for i in safety_h if i in results and not any(str(c).startswith("level3:") for c in results[i].get("causes", [])) and results[i].get("outcome") != "language-held"]
    dataless_fed = [i for i in R if i in F and i in results and results[i].get("outcome") == "feed" and all((F[i].get(k) or "").lower() == "no" for k in ("sample_size", "design", "results"))
                    and not exempt_by_type(R[i].get("pubtypes"))]
    foreign = [i for i in R if language_screen.screen(R[i].get("text", ""))["hold"]]
    foreign_not_held = [i for i in foreign if i in results and results[i].get("outcome") != "language-held"]
    out = {"records": len(R), "answersIncomplete": len(incomplete), "noResult": len(missing), "runValid": bool(run_valid), "feedRecommendations": len(feed),
           "unsafe": {"count": len(unsafe), "ofFeedRecommendations": len(feed), "upper95": upper_bound(len(unsafe), len(feed))},
           "cleanCandidates": len(clean), "cleanCandidatesHeld": len(unnecessary), "cleanCandidatesHeldByCause": {k: len(v) for k, v in sorted(by_cause.items())},
           "notices": {"checkerNotices": len(notices_h), "recommendedForFeed": len(notices_bad), "notHandled": len(notices_unhandled)},
           "safetyWording": {"checkerSafetyRecords": len(safety_h), "notEscalatedToLevel3": len(safety_not_l3)},
           "dataFreePrimaryStudiesRecommended": len(dataless_fed),
           "foreignAbstracts": {"inSample": len(foreign), "notHeldByR4": len(foreign_not_held)}}
    investigate = []
    if safety_not_l3: investigate.append("safety-wording record not escalated to Level 3")
    if notices_unhandled: investigate.append("notice not handled as a notice")
    if foreign_not_held: investigate.append("non-English abstract not held by R4")
    if run_valid and clean and len(unnecessary) / len(clean) > 0.5: investigate.append("more than half of the clean records were held (usability, not safety)")
    out["investigate"] = investigate
    if incomplete or missing or not run_valid:
        out["overall"] = "NOT SCORED: " + ("the run was not valid; " if not run_valid else "") + ("answers incomplete; " if incomplete else "") + ("results missing; " if missing else "")
    elif unsafe:
        out["overall"] = "FAIL"
    else:
        out["overall"] = "PASS WITH INVESTIGATION" if investigate else "PASS"
    out["ids"] = {"unsafe": unsafe, "notices_unhandled": notices_unhandled, "safetyNotEscalated": safety_not_l3, "dataFreeFed": dataless_fed, "foreignNotHeld": foreign_not_held,
                  "cleanHeld": by_cause, "incomplete": incomplete, "noResult": missing}
    out["notAuthorised"] = ("A pass shows only that no unsafe recommendation was seen in a small sample (see the upper bound). It never authorises publication, a prompt change, enabling the restricted release path, "
                            "deployment or enabling evaluation. A supervised staged batch needs its own approval.")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--final", required=True); ap.add_argument("--records", required=True); ap.add_argument("--results", required=True); ap.add_argument("--list-ids", action="store_true")
    a = ap.parse_args(argv)
    with open(a.final, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    recs = json.loads(Path(a.records).read_text(encoding="utf-8"))["records"]
    res = json.loads(Path(a.results).read_text(encoding="utf-8"))
    out = score(rows, recs, res["results"], run_valid=res.get("evaluationState") in ("ok", "degraded") and (res.get("usage") or {}).get("requestsSucceeded", 0) > 0)
    ids = out.pop("ids")
    print(json.dumps(out, indent=1))
    if a.list_ids:
        print("IDS (owner only):", json.dumps(ids, indent=1))
    return 0 if out["overall"].startswith("PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
