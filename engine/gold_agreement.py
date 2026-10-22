#!/usr/bin/env python3
"""Tinnitus Evidence — agreement between the two human labellers of the hidden gold set (local tool; you run it on your computer, on the labelled candidates.csv).

It reads the labelled CSV written by gold_sampler.py (labeller1_*, labeller2_*, adjudicated_* columns) and prints AGGREGATE numbers only: how many records each labeller
completed, raw agreement and Cohen's kappa (with a bootstrap interval) for the technical labels, how many disagreements still need adjudication, and whether the set
reaches the pre-set readiness bar. With --list-disagreements it prints the ids that need adjudication (ids only, no titles, for you).

TECHNICAL labels only (relevance category 1-6, study type, abstract present, notice type). The CLINICIAN_ONLY_* columns are counted but never used for any number here:
technical labelling is NOT clinical validation, and nothing in this report may be described as clinically validated.

  python engine/gold_agreement.py --labels D:\\te-gold\\candidates.csv [--list-disagreements]
Readiness bar (set before looking at any labels): kappa >= 0.80 for relevance grouped as feed-level (1-2 / 3-4 / 5-6) and for study type, every record labelled by both,
and every disagreement adjudicated. Separately, the three evidence-cue labels and the safety-wording label need kappa >= 0.70 ("cueLabelsInterpretable") before the backstop and the safety triggers are measured against them.
"""
import argparse, csv, json, random, sys
from collections import Counter
from pathlib import Path

GROUP = {"1": "feed", "2": "feed", "3": "context", "4": "context", "5": "dropped", "6": "dropped"}   # 1-2 reach the public feed, 3-4 are archived context, 5-6 never reach the feed
CUES = ("has_sample_size", "has_design", "has_result_figures")
CUE_BAR = 0.70   # agreement needed on the three evidence cues (and the safety-wording label) before the backstop can be measured against them
FIELDS = {"relevance_1to6": "relevance (1-6)", "relevance_group": "relevance grouped (feed / context / dropped)", "study_type": "study type", "abstract_present": "abstract present", "notice_type": "notice type"}
BAR = 0.80


def kappa(a, b):
    """Cohen's kappa for two equal-length label lists. Returns (kappa, observed agreement); kappa is None when it is undefined (one category only on both sides)."""
    n = len(a)
    if n == 0:
        return None, None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb.get(k, 0) for k in ca) / (n * n)
    return (None if pe == 1 else (po - pe) / (1 - pe)), po


def boot_ci(a, b, reps=2000, seed=12345):
    """95% bootstrap interval for kappa (fixed seed so the report is reproducible; the seed is not secret and is unrelated to the draw seed)."""
    rng, n, vals = random.Random(seed), len(a), []
    for _ in range(reps):
        idx = [rng.randrange(n) for _ in range(n)]
        k, _ = kappa([a[i] for i in idx], [b[i] for i in idx])
        if k is not None:
            vals.append(k)
    vals.sort()
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]) if len(vals) >= 50 else (None, None)


def norm(v):
    return (v or "").strip().lower()


def analyse(rows):
    out = {"records": len(rows), "labeller1_complete": 0, "labeller2_complete": 0, "both_complete": 0, "fields": {}, "disagreements": {}, "adjudicated_complete": 0, "clinician_columns_filled": 0}
    tech = ["relevance_1to6", "study_type", "abstract_present", "notice_type", "has_sample_size", "has_design", "has_result_figures", "safety_wording"]
    for r in rows:
        c1, c2 = all(norm(r.get(f"labeller1_{f}")) for f in tech), all(norm(r.get(f"labeller2_{f}")) for f in tech)
        out["labeller1_complete"] += c1; out["labeller2_complete"] += c2; out["both_complete"] += c1 and c2
        out["clinician_columns_filled"] += any(norm(v) for k, v in r.items() if k.startswith("CLINICIAN_ONLY") and v)
    for f in ("relevance_1to6", "relevance_group", "study_type", "abstract_present", "notice_type", "has_sample_size", "has_design", "has_result_figures", "safety_wording"):
        a, b, ids = [], [], []
        for r in rows:
            if f == "relevance_group":
                x, y = GROUP.get(norm(r.get("labeller1_relevance_1to6"))), GROUP.get(norm(r.get("labeller2_relevance_1to6")))
            else:
                x, y = norm(r.get(f"labeller1_{f}")), norm(r.get(f"labeller2_{f}"))
            if x and y:
                a.append(x); b.append(y)
                if x != y:
                    ids.append(r["id"])
        k, po = kappa(a, b)
        lo, hi = boot_ci(a, b) if len(a) >= 10 and k is not None else (None, None)
        out["fields"][f] = {"pairs": len(a), "observedAgreement": None if po is None else round(po, 3), "kappa": None if k is None else round(k, 3),
                            "kappa95CI": None if lo is None else [round(lo, 3), round(hi, 3)], "disagreements": len(ids)}
        out["disagreements"][f] = ids
    unresolved = set()
    for f in ("relevance_1to6", "study_type", "abstract_present", "notice_type", "has_sample_size", "has_design", "has_result_figures", "safety_wording"):
        for r in rows:
            x, y = norm(r.get(f"labeller1_{f}")), norm(r.get(f"labeller2_{f}"))
            if x and y and x != y and not norm(r.get(f"adjudicated_{f}")):
                unresolved.add(r["id"])
    out["adjudicated_complete"] = sum(all(norm(r.get(f"adjudicated_{f}")) for f in tech) for r in rows)
    out["unresolved_disagreement_records"] = len(unresolved)
    out["unresolved_ids"] = sorted(unresolved)
    kr, ks = out["fields"]["relevance_group"]["kappa"], out["fields"]["study_type"]["kappa"]
    reasons = []
    if out["both_complete"] < out["records"]:
        reasons.append(f"{out['records'] - out['both_complete']} record(s) not yet labelled by both labellers")
    if kr is None or kr < BAR:
        reasons.append(f"relevance (grouped) kappa {kr} is below {BAR}")
    if ks is None or ks < BAR:
        reasons.append(f"study-type kappa {ks} is below {BAR}")
    if unresolved:
        reasons.append(f"{len(unresolved)} record(s) with an unadjudicated disagreement")
    ck = {f: out["fields"][f]["kappa"] for f in CUES + ("safety_wording",)}
    # kappa is undefined when both labellers used one category throughout; perfect observed agreement then counts
    out["cueLabelsInterpretable"] = all((v is not None and v >= CUE_BAR) or (v is None and out["fields"][f]["observedAgreement"] == 1.0) for f, v in ck.items())
    out["cueKappas"] = ck
    out["ready"] = not reasons
    out["notReadyBecause"] = reasons
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", required=True); ap.add_argument("--list-disagreements", action="store_true")
    a = ap.parse_args(argv)
    with open(a.labels, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    res = analyse(rows)
    printable = {k: v for k, v in res.items() if k not in ("disagreements", "unresolved_ids")}
    print(json.dumps(printable, indent=1))
    print("READY to be used as a technical-label reference set." if res["ready"] else "NOT READY: " + "; ".join(res["notReadyBecause"]))
    print("These are technical labels. They do not establish clinical validity; the CLINICIAN_ONLY columns are not used here.")
    if a.list_disagreements:
        print("ids with an unadjudicated disagreement:", ", ".join(res["unresolved_ids"]) or "none")
    return 0 if res["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
