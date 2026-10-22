"""Tests for engine/gold_score.py (scoring of the one-time 60-record validation). Synthetic labels and results; offline."""
import contextlib, csv, io, json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import gold_score as gsc  # noqa: E402


def row(i, rel="1", st="cohort", abstract="yes", notice="none", s="yes", d="yes", r="yes", safety="no", lang="eng"):
    x = {"id": f"pubmed-{i}", "language": lang}
    for k, v in (("relevance_1to6", rel), ("study_type", st), ("abstract_present", abstract), ("notice_type", notice), ("has_sample_size", s), ("has_design", d), ("has_result_figures", r), ("safety_wording", safety)):
        x[f"adjudicated_{k}"] = v
    return x


def res(i, outcome, cause="none", causes=()):
    return f"pubmed-{i}", {"outcome": outcome, "primaryCause": cause, "causes": list(causes)}


def world(n_clean=24, **kw):
    """A healthy world: 24 clean candidates fed; 6 context records archived; 3 notices held as notices; 4 safety records escalated; 3 data-free records held."""
    rows, results, k = [], {}, 0

    def add(rw, rs):
        nonlocal k
        rows.append(rw); a, b = rs; results[a] = b

    for _ in range(n_clean):
        k += 1; add(row(k), res(k, "feed"))
    for _ in range(6):
        k += 1; add(row(k, rel="3"), res(k, "not-feed"))
    for _ in range(3):
        k += 1; add(row(k, rel="6", notice="retraction"), res(k, "notice-held"))
    for _ in range(4):
        k += 1; add(row(k, safety="yes"), res(k, "held", "level3", ["level3:safety-term"]))
    for _ in range(3):
        k += 1; add(row(k, s="no", d="no", r="no"), res(k, "held", "evidence-adequacy", ["evidence-adequacy"]))
    return rows, results


class Measures(unittest.TestCase):
    def test_a_healthy_world_passes_with_zero_unsafe_recommendations(self):
        rows, results = world(); o = gsc.score(rows, results)
        self.assertEqual(o["overall"], "PASS"); self.assertEqual(o["measures"]["unsafe"]["count"], 0)
        self.assertEqual(o["measures"]["unsafe"]["upper95"], gsc.upper_bound(0, 24)); self.assertEqual(o["measures"]["notices"]["verdict"], "PASS")
        self.assertEqual(o["measures"]["safetyWording"]["verdict"], "PASS"); self.assertEqual(o["measures"]["dataFreeRecall"]["verdict"], "PASS")

    def test_each_kind_of_unsafe_recommendation_fails_the_whole_validation(self):
        base_rows, base_res = world()
        for name, rw in (("notice", row(900, notice="correction")), ("no abstract", row(901, abstract="no")), ("safety wording", row(902, safety="yes")),
                         ("data-free primary study", row(903, s="no", d="no", r="no", st="rct"))):
            rows = base_rows + [rw]; results = dict(base_res); k, v = res(int(rw["id"].split("-")[1]), "feed"); results[k] = v
            o = gsc.score(rows, results)
            self.assertEqual(o["overall"], "FAIL", name); self.assertEqual(o["measures"]["unsafe"]["count"], 1, name); self.assertIn("unsafe", o["failedMeasures"])
            self.assertEqual(o["ids"]["unsafe"][0][0], rw["id"])

    def test_a_data_free_review_or_case_report_in_the_feed_is_not_unsafe(self):
        rows, results = world()
        for i, st in ((910, "review-other"), (911, "case-or-letter"), (912, "systematic-review")):
            rows.append(row(i, s="no", d="no", r="no", st=st)); k, v = res(i, "feed"); results[k] = v
        self.assertEqual(gsc.score(rows, results)["measures"]["unsafe"]["count"], 0)

    def test_mis_sorting_into_the_feed_is_counted_apart_from_unsafe_and_has_its_own_allowance(self):
        rows, results = world()
        for i in (920, 921):
            rows.append(row(i, rel="4")); k, v = res(i, "feed"); results[k] = v
        o = gsc.score(rows, results); self.assertEqual(o["measures"]["misSortedIntoFeed"]["count"], 2); self.assertEqual(o["measures"]["misSortedIntoFeed"]["verdict"], "PASS"); self.assertEqual(o["measures"]["unsafe"]["count"], 0)
        rows.append(row(922, rel="5")); k, v = res(922, "feed"); results[k] = v
        self.assertEqual(gsc.score(rows, results)["measures"]["misSortedIntoFeed"]["verdict"], "FAIL")

    def test_relevant_records_sent_to_irrelevant_or_archive(self):
        rows, results = world()
        rows.append(row(930)); k, v = res(930, "not-feed"); results[k] = v
        self.assertEqual(gsc.score(rows, results)["measures"]["relevantMissed"]["verdict"], "PASS")           # one is allowed (and listed for review)
        rows.append(row(931)); k, v = res(931, "not-feed"); results[k] = v
        o = gsc.score(rows, results); self.assertEqual(o["measures"]["relevantMissed"]["verdict"], "FAIL"); self.assertEqual(o["overall"], "FAIL")

    def test_notices_safety_and_data_free_records_must_all_be_caught(self):
        rows, results = world()
        rows.append(row(940, rel="6", notice="retraction")); k, v = res(940, "held"); results[k] = v
        self.assertEqual(gsc.score(rows, results)["measures"]["notices"]["verdict"], "PASS")                    # held counts as handled
        rows.append(row(941, safety="yes")); k, v = res(941, "held", "other", ["model-not-verified"]); results[k] = v    # held, but not by a Level 3 rule
        o = gsc.score(rows, results); self.assertEqual(o["measures"]["safetyWording"]["verdict"], "FAIL"); self.assertEqual(o["ids"]["safetyNotEscalated"], ["pubmed-941"])
        rows2, results2 = world(); rows2.append(row(942, s="no", d="no", r="no", st="rct")); k, v = res(942, "feed"); results2[k] = v
        self.assertEqual(gsc.score(rows2, results2)["measures"]["dataFreeRecall"]["verdict"], "FAIL")

    def test_too_few_records_of_a_kind_is_reported_as_not_measurable_never_as_a_pass(self):
        rows, results = [], {}
        for i in range(1, 21):
            rows.append(row(i)); k, v = res(i, "feed"); results[k] = v
        o = gsc.score(rows, results)
        self.assertEqual(o["overall"], "PASS"); self.assertTrue(o["measures"]["notices"]["verdict"].startswith("NOT MEASURABLE")); self.assertIn("safetyWording", o["notMeasurable"]); self.assertIn("dataFreeRecall", o["notMeasurable"])

    def test_the_backstop_false_hold_rate_and_the_model_caution_rate_are_separate(self):
        rows, results = world(n_clean=0)
        k = 0
        def clean(cause, outcome="held", causes=()):
            nonlocal k
            k += 100; rows.append(row(k)); a, b = res(k, outcome, cause, causes); results[a] = b
        for _ in range(22): clean("none", "feed")
        for _ in range(3): clean("evidence-adequacy", "held", ["evidence-adequacy"])                              # 3 of 30 clean = 10%: allowed
        for _ in range(5): clean("model-not-verified-only", "held", ["model-not-verified"])                       # 5 of 30 = 16.7%: below the 25% trigger
        o = gsc.score(rows, results); m = o["measures"]
        self.assertEqual(m["backstopFalseHolds"]["verdict"], "PASS"); self.assertEqual(m["modelCautionHolds"]["verdict"], "OK"); self.assertEqual(o["overall"], "PASS")
        for _ in range(4): clean("model-not-verified-only", "held", ["model-not-verified"])                       # 9 of 34 = 26.5%: above 25%
        clean("evidence-adequacy", "held", ["evidence-adequacy"])                                                 # 4 of 35 = 11.4%: above 10%
        o = gsc.score(rows, results); m = o["measures"]
        self.assertTrue(m["modelCautionHolds"]["verdict"].startswith("INVESTIGATE")); self.assertEqual(m["backstopFalseHolds"]["verdict"], "FAIL"); self.assertEqual(o["overall"], "FAIL")
        self.assertIn("authorises", o["notAuthorised"])

    def test_the_model_caution_flag_alone_gives_pass_with_investigation_and_authorises_nothing(self):
        rows, results = world(n_clean=0); k = 0
        for j in range(24):
            k += 100; rows.append(row(k)); a, b = (res(k, "feed") if j < 16 else res(k, "held", "model-not-verified-only", ["model-not-verified"])); results[a] = b     # 8 of 24 = 33%
        o = gsc.score(rows, results)
        self.assertEqual(o["overall"], "PASS WITH INVESTIGATION"); self.assertEqual(o["investigate"], ["modelCautionHolds"]); self.assertIn("No outcome of this scoring authorises", o["notAuthorised"])

    def test_clean_candidates_exclude_non_english_notices_safety_and_thin_records(self):
        rows, results = world(n_clean=0)
        for i, rw in enumerate((row(1, lang="chi"), row(2, notice="correction"), row(3, safety="yes"), row(4, s="no", d="yes", r="no"), row(5, rel="3"), row(6, abstract="no")), start=1000):
            rw["id"] = f"pubmed-{i}"; rows.append(rw); k, v = res(i, "held", "model-not-verified-only", ["model-not-verified"]); results[k] = v
        self.assertEqual(gsc.score(rows, results)["measures"]["modelCautionHolds"]["cleanCandidates"], 0)

    def test_incomplete_labels_or_missing_results_are_not_scored(self):
        rows, results = world(); rows[0]["adjudicated_has_design"] = ""
        o = gsc.score(rows, results); self.assertTrue(o["overall"].startswith("NOT SCORED")); self.assertEqual(o["labelsIncomplete"], 1)
        rows, results = world(); results.pop(rows[1]["id"])
        o = gsc.score(rows, results); self.assertTrue(o["overall"].startswith("NOT SCORED")); self.assertEqual(o["noResult"], 1)


class CausesAndBounds(unittest.TestCase):
    def ev(self, **kw):
        e = {"factuallyVerified": True, "confidence": "moderate", "confidenceModel": "moderate", "sourceChecks": {"recordFetched": True, "criticalOmitted": False, "identifierMatchesItem": True, "ungroundedNumbers": [], "ungroundedDates": [],
             "unsupportedTerms": [], "evidenceAdequacy": {"adequate": True, "level": "adequate"}}, "escalation": [], "changeClass": "routine"}
        e.update(kw)
        return e

    def test_causes_and_the_primary_cause(self):
        self.assertEqual(gsc.causes(self.ev()), [])
        e = self.ev(factuallyVerified=False); self.assertEqual(gsc.causes(e), ["model-not-verified"]); self.assertEqual(gsc.primary_cause(gsc.causes(e)), "model-not-verified-only")
        e = self.ev(factuallyVerified=False, factuallyVerifiedModel=True); self.assertNotIn("model-not-verified", gsc.causes(e))                        # a code override is not the model's caution
        e = self.ev(factuallyVerified=False, escalation=[{"tier": "level3", "kind": "safety-term"}]); self.assertEqual(gsc.primary_cause(gsc.causes(e)), "level3")
        e = self.ev(); e["sourceChecks"]["evidenceAdequacy"] = {"adequate": False}; self.assertEqual(gsc.primary_cause(gsc.causes(e)), "evidence-adequacy")
        e = self.ev(); e["sourceChecks"]["unsupportedTerms"] = [{"term": "first"}]; self.assertEqual(gsc.primary_cause(gsc.causes(e)), "unsupported-claim")
        e = self.ev(); e["sourceChecks"]["recordFetched"] = False; self.assertEqual(gsc.primary_cause(gsc.causes(e)), "record-problem")
        self.assertEqual(gsc.primary_cause(gsc.causes(self.ev(confidence="low", confidenceModel="low"))), "low-confidence")
        self.assertEqual(gsc.primary_cause(gsc.causes(self.ev(changeClass="major"))), "possible-major-change")
        self.assertEqual(gsc.primary_cause(gsc.causes(self.ev(escalation=[{"tier": "flag", "kind": "weak-safety-term"}]))), "flag")

    def test_exact_upper_bounds(self):
        self.assertEqual(gsc.upper_bound(0, 60), 0.049); self.assertEqual(gsc.upper_bound(0, 10), 0.259); self.assertEqual(gsc.upper_bound(2, 60), 0.101); self.assertIsNone(gsc.upper_bound(0, 0))


class Cli(unittest.TestCase):
    def test_the_command_line_prints_aggregates_and_ids_only_on_request(self):
        rows, results = world()
        d = Path(tempfile.mkdtemp()); lab = d / "labels.csv"; rf = d / "results.json"
        with open(lab, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
        rf.write_text(json.dumps({"results": results}), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = gsc.main(["--labels", str(lab), "--results", str(rf)])
        self.assertEqual(rc, 0); self.assertNotIn("pubmed-1", buf.getvalue()); self.assertIn('"overall": "PASS"', buf.getvalue())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            gsc.main(["--labels", str(lab), "--results", str(rf), "--list-ids"])
        self.assertIn("IDS (owner only)", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
