"""Guards the committed (trimmed) benchmark report: it must pass the launch gate for the CURRENT evaluator prompt and must not carry raw model answers."""
import json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import evaluate_queue  # noqa: E402


class CommittedBenchmarkReport(unittest.TestCase):
    def report(self):
        return json.loads((REPO / "engine" / "benchmark-report.json").read_text(encoding="utf-8"))

    def test_the_report_passes_the_launch_gate_for_the_current_prompt(self):
        r = self.report()
        self.assertEqual((r["passed"], r["cases"]), (8, 8))
        self.assertEqual(r["promptHash"], evaluate_queue.prompt_hash(), "the evaluator prompt changed after the benchmark: a new benchmark is required")
        self.assertTrue(r["passed"] == r["cases"] and r["cases"])     # the exact condition weekly_cycle uses

    def test_no_raw_model_answers_are_committed(self):
        r = self.report()
        self.assertNotIn("evaluations", r); self.assertTrue(r.get("rawAnswersOmitted"))
        self.assertLess(len(json.dumps(r)), 3000)
        self.assertEqual(sorted(k for k, v in r["failures"].items() if v), [])


if __name__ == "__main__":
    unittest.main()
