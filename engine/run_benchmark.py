#!/usr/bin/env python3
"""Tinnitus Evidence — PRODUCTION AI-evaluator benchmark (launch gate).

Runs the FROZEN 8-case gold benchmark (Baseline V1, 2026-09-04 — cases and pass criteria
preserved in audit-baseline-v1/benchmark.md; the case texts below are verbatim and must
NEVER be edited to make performance look better) against the PRODUCTION evaluator:
the same model, prompt rules and field contract that engine/evaluate_queue.py uses.

Policy (Phase 15 of the improvement brief): this must pass BEFORE the first auto-published
evaluated batch. If production performance is materially worse than the proxy benchmark
(8/8 material agreement, 0 hallucinated fields), HOLD launch.

Usage:  python engine/run_benchmark.py            (needs ANTHROPIC_API_KEY)
Exit codes: 0 = all material criteria pass · 1 = material failure (HOLD) · 2 = cannot run.
Report: engine/benchmark-report.json
"""
import json, re, sys
from datetime import datetime
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE))
import evaluate_queue  # production RULES + EVAL_FIELDS — benchmark what actually runs

# ---- FROZEN CASES (Baseline V1 — verbatim; do not edit) ----
CASES = {
 "C1": "Randomized double-blind trial, N=180 adults with chronic subjective tinnitus, neuromodulation device X versus identical-appearing sham, 12 weeks. THI change: device −15.2 points, sham −13.8 points; between-group difference 1.4 points (95% CI −2.1 to 4.9), p=0.43. Funded by the device manufacturer; two authors are employees. Published in a peer-reviewed otology journal; PMID available.",
 "C2": "Randomized placebo-controlled trial of oral drug Y, N=90, chronic tinnitus. Pre-specified primary endpoint: TFI change at week 8 — p=0.21 (not significant). A secondary loudness VAS showed p=0.03 in a post-hoc subgroup of participants with high-frequency hearing loss. Independent academic funding. Peer-reviewed, PMID available.",
 "C3": "Open-label single-arm study, N=45, novel sound therapy program, 10 weeks. THI improved by a mean of 18 points from baseline (p<0.001). No control group. Authors conclude the program 'is effective for tinnitus'. University clinic, no industry funding disclosed.",
 "C4": "Conference abstract (no full paper): 'A new neuromodulation approach shows promise in tinnitus patients, with meaningful improvements observed after treatment.' No sample size given, no design details, no numerical results, no registration number located.",
 "C5": "Sham-controlled randomized trial, N=120, wearable device Z, 8 weeks, double-blind. THI: active −11 points vs sham −4 points, between-group p=0.01. No psychoacoustic measurements were performed. The authors' abstract concludes 'tinnitus was significantly reduced'. Registered trial, peer-reviewed, industry-sponsored.",
 "C6": "Case series and regulator notice: three patients experienced first-time seizures within hours of using consumer neurostimulation device Q for tinnitus; the national regulator states it 'is aware of the reports and is evaluating'. No controlled data. Source: regulator safety-communication page.",
 "C7": "Company press release: 'Our pivotal trial of treatment W met its endpoints. We expect FDA approval next year and believe W will become the standard of care for tinnitus.' No data tables, no journal publication, no registry results posted yet.",
 "C8": "Preclinical study in a mouse noise-exposure model: compound R eliminated behavioral evidence of tinnitus in treated animals versus controls (n=12 per group). No human data. University lab, published in a neuroscience journal.",
}

def _lvl(v):  # leading qualitative level out of "none, sentence…"
    return (str(v or "").strip().lower().split(",")[0].split(" ")[0]) or "missing"

# ---- GOLD KEY (pre-committed 2026-09-04; material pass criteria — do not weaken) ----
def score(case, ev):
    f = []  # material failures
    def need(cond, msg):
        if not cond:
            f.append(msg)
    if case == "C1":
        need(_lvl(ev.get("distressEffect")) == "none", "null RCT (both arms improve) must yield distress=none")
        need(_lvl(ev.get("loudnessEffect")) == "none", "no loudness outcomes -> loudness=none")
        need(ev.get("importance") == "Negative Result", "importance must be Negative Result")
        need(ev.get("evidenceDirection") != "strengthens", "a null trial never strengthens")
        need("manufactur" in str(ev.get("conflictOfInterest", "")).lower() or "employee" in str(ev.get("conflictOfInterest", "")).lower(), "COI (manufacturer/employees) must be flagged")
    elif case == "C2":
        need(_lvl(ev.get("loudnessEffect")) in ("none", "limited"), "post-hoc subgroup loudness must be <= limited")
        blob = str(ev.get("loudnessEffect", "")) + str(ev.get("clinicalSignificance", "")) + str(ev.get("secondaryEndpoints", ""))
        need("post" in blob.lower() or "subgroup" in blob.lower(), "post-hoc/subgroup caveat must be stated")
        need(_lvl(ev.get("distressEffect")) == "none", "failed pre-specified primary -> distress=none")
        need(ev.get("evidenceDirection") != "strengthens", "primary failure dominates — never 'strengthens'")
    elif case == "C3":
        need("within" in str(ev.get("comparisonType", "")).lower(), "comparisonType must be within-group only")
        need(_lvl(ev.get("distressEffect")) in ("none", "limited"), "uncontrolled study -> distress <= limited")
        need(ev.get("evidenceDirection") == "no-meaningful-change", "single-arm study never endorses efficacy")
    elif case == "C4":
        for k in ("sampleSize", "population", "primaryEndpoint"):
            v = str(ev.get(k, "")).lower()
            need("not reported" in v or v in ("", "n/a", "none", "unable to verify"), f"{k} must be 'Not reported' — nothing may be invented")
        need("none" in str(ev.get("numericalResult", "")).lower() or "not reported" in str(ev.get("numericalResult", "")).lower(), "numericalResult must be 'none reported'")
        need(ev.get("factuallyVerified") is False, "unverifiable abstract -> factuallyVerified=false")
        need(not re.search(r"\d", str(ev.get("numericalResult", ""))), "no numbers may be hallucinated")
    elif case == "C5":
        need(_lvl(ev.get("loudnessEffect")) == "none", "THI benefit with no psychoacoustics -> loudness=none despite authors' claim")
        need(_lvl(ev.get("distressEffect")) in ("limited", "moderate"), "controlled distress benefit should be limited/moderate")
    elif case == "C6":
        need(ev.get("safetySignal") is True, "seizure reports -> safetySignal=true")
        need(str(ev.get("changeClass", "")).startswith("major"), "safety signal -> changeClass=major")
    elif case == "C7":
        need(ev.get("regulatorySource") == "company announcement", "press release -> regulatorySource=company announcement")
        need(str(ev.get("studyType", "")).lower() in ("press release", "other"), "studyType must reflect press release")
        need(ev.get("importance") in ("Interesting but Early", "Does Not Change Current Evidence"), "PR importance <= Interesting but Early")
        need(ev.get("evidenceDirection") == "no-meaningful-change", "undisclosed data changes nothing")
        need("approv" not in str(ev.get("weeklyTitle", "")).lower(), "headline must not echo approval expectations")
    elif case == "C8":
        need(_lvl(ev.get("loudnessEffect")) == "none", "mouse data -> no human loudness claim")
        need(_lvl(ev.get("distressEffect")) == "none", "mouse data -> no human distress claim")
        need(ev.get("importance") in ("Interesting but Early", "Does Not Change Current Evidence"), "preclinical <= Interesting but Early")
        need(str(ev.get("changeClass", "")).startswith("routine"), "preclinical is routine")
    return f


def main():
    import os
    try:
        import anthropic
    except ImportError:
        print("BENCHMARK CANNOT RUN: pip install anthropic", file=sys.stderr)
        sys.exit(2)
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("BENCHMARK CANNOT RUN: ANTHROPIC_API_KEY not set. This is a LAUNCH GATE — "
              "it must pass before the first auto-published evaluated batch.", file=sys.stderr)
        sys.exit(2)
    client = anthropic.Anthropic()
    results, failures = {}, {}
    for cid, text in CASES.items():
        prompt = (f"{evaluate_queue.RULES}\n\nNEW ITEM METADATA:\n" +
                  json.dumps({"id": f"benchmark-{cid}", "kind": "study", "title": f"Benchmark vignette {cid}",
                              "source": "benchmark", "url": ""}) +
                  f"\n\nPRIMARY RECORD:\n{text}\n\n"
                  f"Respond with ONLY a JSON object exactly matching this shape (no markdown fences):\n{evaluate_queue.EVAL_FIELDS}")
        resp = client.messages.create(model=evaluate_queue.MODEL, max_tokens=4000,
                                      thinking={"type": "adaptive"},
                                      messages=[{"role": "user", "content": prompt}])
        t = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            ev = json.loads(t[t.index("{"):t.rindex("}") + 1])
        except Exception as e:
            results[cid], failures[cid] = {"parseError": str(e)}, [f"unparseable output: {e}"]
            continue
        results[cid] = ev
        failures[cid] = score(cid, ev)
        print(f"{cid}: {'PASS' if not failures[cid] else 'FAIL — ' + '; '.join(failures[cid])}")
    n_fail = sum(1 for v in failures.values() if v)
    report = {"ranAt": datetime.now().isoformat(timespec="seconds"), "model": evaluate_queue.MODEL,
              "cases": len(CASES), "passed": len(CASES) - n_fail, "failures": failures,
              "verdict": "PASS — production evaluator meets the frozen gold benchmark" if n_fail == 0
                         else "HOLD LAUNCH — production evaluator materially worse than the gold benchmark",
              "evaluations": results}
    (ENGINE / "benchmark-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{report['verdict']}  ({report['passed']}/{report['cases']})")
    print(f"Report: engine/benchmark-report.json")
    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
