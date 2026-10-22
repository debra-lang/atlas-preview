"""Regression tests for the C4 benchmark failure of the second paid run (21 Oct 2026, 10:23): the model answered population = "Tinnitus patients; no further detail
reported", which the frozen gold key rejects (it requires 'Not reported'). Offline: no network, no API key.

The model's wording was GROUNDED (the vignette says "in tinnitus patients"); the field's instruction did not say what to do when the record names only a bare
condition. The correction clarifies the field definition for ALL items. The benchmark itself must stay exactly as it was frozen: these tests prove it is untouched.
"""
import hashlib, importlib.util, json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import evaluate_queue  # noqa: E402

FROZEN_SHA256 = "77f02c1073a7434b304b49d4160b5238d8496c33f9ce5749e4fedd9c522e9e69"   # CASES + gold key exactly as committed on production a69020c (frozen 4 Sep 2026)
RUN = fixture("benchmark_run_20261021_1018_c4_failure.json")
OLD_PROMPT_HASH = "0494cdff56d3a929"   # the prompt the failing run used


def load_benchmark():
    spec = importlib.util.spec_from_file_location("run_benchmark_t", ENGINE / "run_benchmark.py")
    m = importlib.util.module_from_spec(spec)
    old = sys.argv
    sys.argv = ["x"]
    try:
        spec.loader.exec_module(m)
    finally:
        sys.argv = old
    return m


class BenchmarkIsUntouched(unittest.TestCase):
    def test_cases_and_gold_key_are_byte_identical_to_the_frozen_version(self):
        src = (ENGINE / "run_benchmark.py").read_text(encoding="utf-8").replace("\r\n", "\n")
        part = src[src.index("# ---- FROZEN CASES"): src.index("def main():")]
        self.assertEqual(hashlib.sha256(part.encode("utf-8")).hexdigest(), FROZEN_SHA256,
                         "the frozen cases or the gold key were edited: that must never be done to obtain a pass")

    def test_the_population_criterion_is_still_the_strict_one(self):
        rb = load_benchmark()
        case = rb.CASES["C4"]
        def fails(pop):
            ev = {"sampleSize": "Not reported", "population": pop, "primaryEndpoint": "Not reported", "numericalResult": "none reported", "factuallyVerified": False}
            return [f for f in rb.score("C4", ev) if f.startswith("population")]
        self.assertTrue(fails("Tinnitus patients; no further detail reported"))              # the failing answer still fails
        self.assertTrue(fails("Patients with tinnitus"))
        self.assertTrue(fails("Adults with chronic tinnitus"))                                # an invented characterisation still fails
        self.assertFalse(fails("Not reported"))
        self.assertFalse(fails("Not reported (record says only: tinnitus patients)"))        # the grounded form the clarified field asks for passes


class ReplayOfTheFailingRun(unittest.TestCase):
    """The stored answers of the failing run, scored by the unchanged gold key: exactly one failure, exactly C4's population."""

    def test_only_c4_population_fails(self):
        rb = load_benchmark()
        fails = {cid: rb.score(cid, ev) for cid, ev in RUN["evaluations"].items()}
        self.assertEqual({k: v for k, v in fails.items() if v}, {"C4": ["population must be 'Not reported' — nothing may be invented"]})
        self.assertEqual(RUN["passed"], 7)
        self.assertEqual(RUN["promptHash"], OLD_PROMPT_HASH)

    def test_the_failing_answer_is_grounded_in_the_vignette(self):
        rb = load_benchmark()
        self.assertIn("tinnitus patients", rb.CASES["C4"])                                    # why this is not a hallucination
        pop = RUN["evaluations"]["C4"]["population"]
        self.assertEqual(pop, "Tinnitus patients; no further detail reported")
        import grounding
        self.assertEqual(grounding.ungrounded_numbers(RUN["evaluations"]["C4"], rb.CASES["C4"], grounding.HARD_NUMBER_FIELDS + grounding.SOFT_NUMBER_FIELDS), [])

    def test_no_check_in_the_gold_key_other_than_population_is_involved(self):
        rb = load_benchmark()
        ev = json.loads(json.dumps(RUN["evaluations"]["C4"])); ev["population"] = "Not reported"
        self.assertEqual(rb.score("C4", ev), [])                                              # with population per the key, the rest of C4's answer passes everything


class PopulationContract(unittest.TestCase):
    def line(self):
        return next(l for l in evaluate_queue.EVAL_FIELDS.splitlines() if l.lstrip().startswith('"population"'))

    def test_the_field_definition_covers_the_bare_condition_case(self):
        l = self.line()
        for phrase in ("bare condition", "tinnitus patients", "Not reported (record says only:"):
            self.assertIn(phrase, l)

    def test_the_prompt_changed_so_the_old_benchmark_pass_cannot_unlock_evaluation(self):
        self.assertNotEqual(evaluate_queue.prompt_hash(), OLD_PROMPT_HASH)
        r = run_scenario({"queue": [pubmed_item(90000001)], "settings": {"enabled": True, "mode": "staged", "limitPerRun": 5}, "benchmark": "stale", "runs": [{}]})["runs"][0]
        self.assertEqual(r["status"]["evaluation"]["state"], "blocked-gate")
        self.assertEqual(r["totalApiCalls"], 0)

    def test_the_clarification_is_general_and_keeps_described_populations(self):
        l = self.line()
        self.assertIn("setting, age or inclusion criteria", l)                                # a described population is still reported as described
        for other in ("C1", "C2", "C6", "C8"):                                                # stored answers that describe participants are not the bare-condition case
            self.assertNotIn("Not reported", RUN["evaluations"][other]["population"][:12])


if __name__ == "__main__":
    unittest.main()
