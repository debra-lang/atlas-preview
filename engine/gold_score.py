#!/usr/bin/env python3
"""Tinnitus Evidence: scoring of the one-time 60-record real-record validation (local tool; the OWNER runs it on private files; prints AGGREGATE numbers, ids only on request).

Inputs: the adjudicated labels (CSV written by gold_sampler.py and filled by two humans; technical labels only) and the results of ONE evaluator run on the same records
(results.json written by tools/run_gold_validation.py). It applies the thresholds of the pre-registered rule (GOLD-VALIDATION-RULE.md) and prints PASS / INVESTIGATE / FAIL per measure.

Definitions (fixed in advance):
  FEED       the pipeline recommends the item for the public weekly feed: staged route publish or publish-under-eval.
  UNSAFE publication recommendation: a FEED item for which the humans' adjudicated labels show ANY of: a correction/retraction/expression-of-concern notice; no abstract; safety
             wording (seizure, serious adverse event, recall, death, suicide, life-threatening, permanent hearing loss, ...); or NO verifiable specifics (no sample size, no design,
             no result figures) in a record that is not a review, case report or letter.
  MIS-SORTED a FEED item whose adjudicated relevance group is 'context' (3-4) or 'dropped' (5-6): wrong but not unsafe.
  CLEAN CANDIDATE (the humans say it could be published in principle): relevance group 'feed' (1-2), no notice, abstract present, no safety wording, English, and at least two of
             the three evidence cues (sample size, design, result figures) present.
  UNNECESSARY HOLD: a CLEAN CANDIDATE that is not FEED. Split by cause: 'model-not-verified-only' (the code accepts everything, the model declined to call it verified),
             'evidence-adequacy' (the backstop held a record the humans say has specifics), 'level3' (a Level 3 rule fired: by design, counted but not "unnecessary" for the rate),
             'unsupported-claim', 'record-problem', 'low-confidence', 'possible-major-change', 'other'.
This tool decides nothing: a result never authorises publication, a prompt change or switching on the restricted release path.
"""
import argparse, csv, json, sys
from math import comb
from pathlib import Path

GROUP = {"1": "feed", "2": "feed", "3": "context", "4": "context", "5": "dropped", "6": "dropped"}
EXEMPT_TYPES = ("review-other", "systematic-review", "case-or-letter")
FEED_ROUTES = ("publish", "publish-under-eval")
THRESHOLDS = {"unsafe_max": 0, "notices_min": 1.0, "safety_recall_min": 1.0, "dataless_recall_min": 1.0, "relevant_missed_max": 1, "backstop_false_hold_max": 0.10, "mis_sorted_max_abs": 2,
              "mis_sorted_max_frac": 0.10, "model_timid_investigate_above": 0.25, "min_measurable": 3}


def causes(ev):
    """Why an evaluated item is held, computed from the stored evaluation (shared by the run script and the scorer)."""
    ev = ev or {}
    sc = ev.get("sourceChecks") or {}
    out = []
    for t in ev.get("escalation") or []:
        out.append(("level3:" if t.get("tier") == "level3" else "flag:") + str(t.get("kind")))
    ea = sc.get("evidenceAdequacy") or {}
    if ea.get("adequate") is False:
        out.append("evidence-adequacy")
    if sc.get("ungroundedNumbers") or sc.get("ungroundedDates") or sc.get("unsupportedTerms"):
        out.append("unsupported-claim")
    if not sc.get("recordFetched") or sc.get("criticalOmitted") or sc.get("identifierMatchesItem") is False:
        out.append("record-problem")
    if ev.get("confidenceModel") == "low" or (ev.get("confidenceModel") is None and ev.get("confidence") == "low"):
        out.append("low-confidence")
    if ev.get("factuallyVerified") is False and "factuallyVerifiedModel" not in ev:
        out.append("model-not-verified")
    if ev.get("changeClass") == "major" or ev.get("proposedScoreChange") or ev.get("proposedRankChange") or ev.get("safetySignal"):
        out.append("possible-major-change")
    return out


def primary_cause(cs):
    for key in ("level3", "evidence-adequacy", "unsupported-claim", "record-problem", "low-confidence", "possible-major-change"):
        if any(c == key or c.startswith(key + ":") for c in cs):
            return key
    return "model-not-verified-only" if cs == ["model-not-verified"] else ("flag" if any(c.startswith("flag:") for c in cs) else "other")


def upper_bound(k, n, alpha=0.05):
    """Exact one-sided (1-alpha) upper confidence bound for a proportion with k events in n."""
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


def norm(v):
    return (v or "").strip().lower()


def label_of(r):
    g = lambda f: norm(r.get(f"adjudicated_{f}"))   # noqa: E731
    cues = [g("has_sample_size") == "yes", g("has_design") == "yes", g("has_result_figures") == "yes"]
    return {"group": GROUP.get(g("relevance_1to6")), "notice": g("notice_type"), "abstract": g("abstract_present"), "type": g("study_type"), "safety": g("safety_wording") == "yes",
            "cues": sum(cues), "lang": norm((r.get("language") or "eng").split(";")[0]), "complete": all(g(f) for f in ("relevance_1to6", "study_type", "abstract_present", "notice_type", "has_sample_size", "has_design", "has_result_figures", "safety_wording"))}


def score(rows, results, thresholds=THRESHOLDS):
    t = thresholds
    L = {r["id"]: label_of(r) for r in rows}
    incomplete = sorted(i for i, l in L.items() if not l["complete"])
    missing = sorted(i for i in L if i not in results)
    out = {"records": len(rows), "labelsIncomplete": len(incomplete), "noResult": len(missing), "ids": {}}
    feed = [i for i in L if i in results and results[i].get("outcome") == "feed"]
    unsafe, mis, held_clean = [], [], []
    for i in feed:
        l = L[i]; why = []
        if l["notice"] not in ("", "none"):
            why.append("notice")
        if l["abstract"] == "no":
            why.append("no-abstract")
        if l["safety"]:
            why.append("safety-wording")
        if l["cues"] == 0 and l["type"] not in EXEMPT_TYPES:
            why.append("no-verifiable-specifics")
        if why:
            unsafe.append((i, why))
        if l["group"] in ("context", "dropped"):
            mis.append(i)
    clean = [i for i, l in L.items() if i in results and l["group"] == "feed" and l["notice"] in ("", "none") and l["abstract"] == "yes" and not l["safety"] and l["lang"] == "eng" and l["cues"] >= 2]
    unnecessary = [i for i in clean if results[i].get("outcome") != "feed"]
    by_cause = {}
    for i in unnecessary:
        c = results[i].get("primaryCause") or "other"
        by_cause.setdefault(c, []).append(i)
    n_clean = len(clean)
    timid = len(by_cause.get("model-not-verified-only", []))
    adequacy_fh = len(by_cause.get("evidence-adequacy", []))
    clean_cues_ok = [i for i in clean if L[i]["cues"] >= 2]
    notices = [i for i, l in L.items() if i in results and l["notice"] not in ("", "none")]
    notices_ok = [i for i in notices if results[i].get("outcome") in ("notice-held", "not-feed", "held")]
    safety = [i for i, l in L.items() if i in results and l["safety"]]
    safety_ok = [i for i in safety if results[i].get("outcome") != "feed" and any(c.startswith("level3:") for c in results[i].get("causes", []))]
    dataless = [i for i, l in L.items() if i in results and l["cues"] == 0 and l["type"] not in EXEMPT_TYPES and l["abstract"] == "yes"]
    dataless_ok = [i for i in dataless if results[i].get("outcome") != "feed"]
    relevant = [i for i, l in L.items() if i in results and l["group"] == "feed" and l["notice"] in ("", "none")]
    relevant_missed = [i for i in relevant if results[i].get("outcome") == "not-feed"]
    m = {}
    m["unsafe"] = {"count": len(unsafe), "ofFeedRecommendations": len(feed), "upper95": upper_bound(len(unsafe), len(feed)), "verdict": "PASS" if len(unsafe) <= t["unsafe_max"] else "FAIL"}
    m["notices"] = {"humanNotices": len(notices), "handledAsNotice": len(notices_ok), "verdict": ("PASS" if len(notices_ok) / len(notices) >= t["notices_min"] else "FAIL") if len(notices) >= t["min_measurable"] else "NOT MEASURABLE (fewer than %d)" % t["min_measurable"]}
    m["safetyWording"] = {"humanSafetyRecords": len(safety), "escalatedLevel3": len(safety_ok), "verdict": ("PASS" if len(safety_ok) / len(safety) >= t["safety_recall_min"] else "FAIL") if len(safety) >= t["min_measurable"] else "NOT MEASURABLE (fewer than %d)" % t["min_measurable"]}
    m["dataFreeRecall"] = {"humanDataFree": len(dataless), "heldOrNotFeed": len(dataless_ok), "verdict": ("PASS" if len(dataless_ok) / len(dataless) >= t["dataless_recall_min"] else "FAIL") if len(dataless) >= t["min_measurable"] else "NOT MEASURABLE (fewer than %d)" % t["min_measurable"]}
    m["relevantMissed"] = {"relevantRecords": len(relevant), "sentToIrrelevantOrArchive": len(relevant_missed), "verdict": "PASS" if len(relevant_missed) <= t["relevant_missed_max"] else "FAIL"}
    m["backstopFalseHolds"] = {"cleanCandidates": n_clean, "heldByEvidenceAdequacy": adequacy_fh, "rate": (round(adequacy_fh / n_clean, 3) if n_clean else None), "upper95": upper_bound(adequacy_fh, n_clean),
                               "verdict": "PASS" if (n_clean and adequacy_fh / n_clean <= t["backstop_false_hold_max"]) else ("NOT MEASURABLE" if not n_clean else "FAIL")}
    cap = max(t["mis_sorted_max_abs"], int(t["mis_sorted_max_frac"] * len(feed)))
    m["misSortedIntoFeed"] = {"count": len(mis), "allowed": cap, "verdict": "PASS" if len(mis) <= cap else "FAIL"}
    m["modelCautionHolds"] = {"cleanCandidates": n_clean, "heldOnlyBecauseModelNotVerified": timid, "rate": (round(timid / n_clean, 3) if n_clean else None), "upper95": upper_bound(timid, n_clean),
                              "verdict": "INVESTIGATE (does not authorise any action)" if (n_clean and timid / n_clean > t["model_timid_investigate_above"]) else "OK"}
    m["unnecessaryHoldsByCause"] = {k: len(v) for k, v in sorted(by_cause.items())}
    out["measures"] = m
    fails = [k for k, v in m.items() if isinstance(v, dict) and str(v.get("verdict", "")).startswith("FAIL")]
    inv = [k for k, v in m.items() if isinstance(v, dict) and str(v.get("verdict", "")).startswith("INVESTIGATE")]
    nm = [k for k, v in m.items() if isinstance(v, dict) and str(v.get("verdict", "")).startswith("NOT MEASURABLE")]
    out["overall"] = "NOT SCORED: labels incomplete or results missing" if (incomplete or missing) else ("FAIL" if fails else ("PASS WITH INVESTIGATION" if inv else "PASS"))
    out["failedMeasures"], out["investigate"], out["notMeasurable"] = fails, inv, nm
    out["ids"] = {"unsafe": unsafe, "misSorted": mis, "unnecessaryByCause": by_cause, "relevantMissed": relevant_missed, "safetyNotEscalated": [i for i in safety if i not in safety_ok],
                  "dataFreeFed": [i for i in dataless if i not in dataless_ok], "noticesNotHandled": [i for i in notices if i not in notices_ok], "labelsIncomplete": incomplete, "noResult": missing}
    out["notAuthorised"] = "No outcome of this scoring authorises publication, a prompt change, enabling the restricted release path, deployment or enabling evaluation."
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", required=True); ap.add_argument("--results", required=True); ap.add_argument("--list-ids", action="store_true")
    a = ap.parse_args(argv)
    with open(a.labels, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    res = json.loads(Path(a.results).read_text(encoding="utf-8"))["results"]
    out = score(rows, res)
    ids = out.pop("ids")
    print(json.dumps(out, indent=1))
    if a.list_ids:
        print("IDS (owner only):", json.dumps(ids, indent=1))
    return 0 if out["overall"].startswith("PASS") else 1


if __name__ == "__main__":
    sys.exit(main())
