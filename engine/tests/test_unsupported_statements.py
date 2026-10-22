"""Regression tests for the eight unsupported statements found by hand in the seven PASSING benchmark answers of the second paid run (21 Oct 2026), plus the
conflict-of-interest option-list copy (same defect class as the comparisonType leak) and spelled-out compound numbers found by the retrospective audit.
Offline: no network, no key. The frozen benchmark is not touched (see test_benchmark_c4.BenchmarkIsUntouched).

What the code CAN catch is tested; what it CANNOT catch is tested too (KnownLimits), so nobody mistakes a clean automated check for verification.
"""
import copy, importlib.util, json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import evaluate_queue, grounding  # noqa: E402

RUN = fixture("benchmark_run_20261021_1018_c4_failure.json")["evaluations"]
PREV = {it["id"]: it for it in fixture("phase2_preview_run.json")["items"]}


def cases():
    spec = importlib.util.spec_from_file_location("rb_u", ENGINE / "run_benchmark.py")
    m = importlib.util.module_from_spec(spec)
    old, sys.argv = sys.argv, ["x"]
    try:
        spec.loader.exec_module(m)
    finally:
        sys.argv = old
    return m.CASES


CASES = cases()


def checks(cid):
    ev = copy.deepcopy(RUN[cid])
    grounding.normalise_enums(ev)
    return grounding.source_checks({"id": "benchmark-" + cid, "title": "Benchmark vignette " + cid, "summary": "", "source": "benchmark"}, ev, CASES[cid] + " Benchmark vignette " + cid, {"completeness": "COMPLETE"}, [])


class CoiOptionListCopy(unittest.TestCase):
    def test_the_schema_asks_for_one_label_and_no_longer_lists_the_options_as_a_sentence(self):
        line = next(l for l in evaluate_queue.EVAL_FIELDS.splitlines() if '"conflictOfInterest"' in l)
        self.assertNotIn("manufacturer-funded / author equity / independent / unclear", line)
        for phrase in ("ONE label", "employment is not equity", "not stated"):
            self.assertIn(phrase, line)

    def test_c1_label_is_flagged_both_as_compound_and_as_an_unsupported_equity_claim(self):
        sc = checks("C1")
        self.assertEqual(sc["compoundCoiLabel"], ["manufacturer-funded", "author equity"])
        self.assertIn("equity", [t["term"] for t in sc["unsupportedTerms"]])
        self.assertFalse(sc["ok"])                                                           # it would be held, not published

    def test_the_first_paid_runs_heart_failure_item_had_the_same_defect_and_is_now_caught(self):
        it = PREV["ctgov-NCT06898515-2026-10-13"]
        self.assertTrue(it["evaluation"]["conflictOfInterest"].startswith("manufacturer-funded / author equity"))
        sc = grounding.source_checks({"id": it["id"], "title": it["title"], "summary": ""}, it["evaluation"], "NCT ID: NCT06898515 sponsor Reprieve Cardiovascular (INDUSTRY)", {"completeness": "COMPLETE"}, [])
        self.assertIn("equity", [t["term"] for t in sc["unsupportedTerms"]])

    def test_a_negated_mention_is_not_flagged(self):
        ev = {"conflictOfInterest": "manufacturer-funded / unclear - industry-sponsored; individual author conflicts or equity holdings are not reported."}
        self.assertEqual(grounding.unsupported_terms(ev, "industry sponsored trial"), [])
        self.assertEqual(checks("C5")["unsupportedTerms"], [])                              # C5's real sentence
        self.assertEqual(checks("C5")["compoundCoiLabel"], ["manufacturer-funded", "unclear"])   # still shown to the reviewer as advisory


class EvaluativeJudgementsAndDomains(unittest.TestCase):
    def test_c1_evaluative_adjectives_are_flagged_when_the_record_does_not_use_them(self):
        terms = [t["term"] for t in checks("C1")["unsupportedTerms"]]
        self.assertIn("well-sized", terms); self.assertIn("reassuring", terms)
        self.assertEqual(grounding.unsupported_terms({"whatIsNew": "A reassuring, well-sized trial."}, "the authors call it reassuring and well-sized"), [])   # the record's own words are allowed

    def test_c3_quality_of_life_is_flagged_as_advisory_but_a_negated_mention_is_not(self):
        self.assertEqual([d["term"] for d in checks("C3")["ungroundedDomainTerms"]], ["quality of life"])
        for ok in ("The study did not measure sleep or quality of life.", "No sleep or quality-of-life instruments were used."):
            self.assertEqual(grounding.ungrounded_domain_terms({"whyMatters": ok}, "THI only"), [], ok)
        self.assertEqual(len(grounding.ungrounded_domain_terms({"whyMatters": "It measured distress and quality of life, not how loud it sounds."}, "THI only")), 1)

    def test_the_prompt_forbids_evaluative_judgements_and_product_descriptions(self):
        for phrase in ("evaluative", "well-sized", "whether it is marketed"):
            self.assertIn(phrase, evaluate_queue.RULES)


class SpelledOutNumbers(unittest.TestCase):
    """Retrospective audit: 'Sixty-five', 'Seventy-four', 'Thirty-four' were reported as ungrounded numbers (they are correct)."""

    def test_compound_number_words_are_understood(self):
        vals = grounding.record_numbers("Sixty-five patients; Seventy-four tinnitus patients; thirty four otologists; two hundred sites; ninety-nine; twenty-one")
        for n in (65.0, 74.0, 34.0, 200.0, 99.0, 21.0):
            self.assertIn(n, vals)

    def test_an_invented_number_is_still_caught_and_derived_totals_still_need_a_decision(self):
        rec = "Sixty-five patients were included."
        self.assertEqual(grounding.ungrounded_numbers({"whatIsNew": "65 patients"}, rec, ("whatIsNew",)), [])
        self.assertEqual([n["value"] for n in grounding.ungrounded_numbers({"whatIsNew": "66 patients"}, rec, ("whatIsNew",))], ["66"])
        rec2 = "22 Veterans with tinnitus, 19 with DST and 165 controls"
        self.assertEqual([n["value"] for n in grounding.ungrounded_numbers({"sampleSize": "206 total"}, rec2, ("sampleSize",))], ["206"])   # a computed total is not in the record: the prompt now says not to compute


class KnownLimits(unittest.TestCase):
    """What automated checks do NOT catch. If one of these starts to be caught, update the test and the documentation, not the other way round."""

    def test_c6_and_c8_product_descriptions_are_not_caught_by_code(self):
        self.assertEqual(checks("C6")["unsupportedTerms"], []); self.assertEqual(checks("C8")["unsupportedTerms"], [])
        self.assertIn("electrical", json.dumps(RUN["C6"])); self.assertNotIn("electrical", CASES["C6"])
        self.assertIn("drug candidate", json.dumps(RUN["C8"])); self.assertNotIn("candidate", CASES["C8"])

    def test_c5_registry_label_over_reach_is_not_caught_by_code(self):
        self.assertEqual(RUN["C5"]["regulatorySource"], "authoritative (FDA/EMA/registry record)")
        self.assertNotIn("registry record", CASES["C5"].lower().replace("registered trial", ""))


class CycleHoldsAnEquityLabel(unittest.TestCase):
    def test_a_manufacturer_label_with_an_unsupported_equity_claim_is_held_in_publish_mode(self):
        item = pubmed_item(90000031, "A device trial")
        ev = {item["id"]: {"conflictOfInterest": "manufacturer-funded / author equity - funded by the manufacturer"}}
        r = run_scenario({"queue": [item], "settings": {"enabled": True, "mode": "publish", "limitPerRun": 5}, "evaluations": ev, "runs": [{}]})["runs"][0]
        self.assertEqual(r["held"], [item["id"]])
        self.assertIn("novelty", r["heldReasons"][item["id"]])


if __name__ == "__main__":
    unittest.main()
