"""Text the cycle generates and publishes must not describe the cadence as weekly (owner decision, 21 Oct 2026: updates run on the 1st and 15th). Offline."""
import ast, re, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401

CADENCE = re.compile(r"\bweek(?:s|ly)?\b|\bmonday\b", re.I)
ALLOWED = ("data/weekly", "weekly.yml", "TinnitusEvidence-weekly")      # file paths, the workflow name, the HTTP user-agent token


class GeneratedText(unittest.TestCase):
    def test_no_string_in_the_cycle_describes_the_cadence_as_weekly(self):
        tree = ast.parse((ENGINE / "weekly_cycle.py").read_text(encoding="utf-8"))
        bad = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and CADENCE.search(n.value) and not any(a in n.value for a in ALLOWED):
                bad.append(n.value[:100])
        self.assertEqual(bad, [])

    def test_the_published_reports_in_every_situation_say_nothing_about_weeks(self):
        queue = [pubmed_item(90300001)]
        situations = {"evaluation off": {"enabled": False, "mode": "staged"}, "quiet scan": None, "evaluated, staged": {"enabled": True, "mode": "staged", "limitPerRun": 5}}
        for name, settings in situations.items():
            spec = {"queue": [] if name == "quiet scan" else queue, "settings": settings or {"enabled": True, "mode": "staged", "limitPerRun": 5}, "runs": [{}]}
            r = run_scenario(spec)["runs"][0]
            texts = [x.get(k) or "" for x in r["reportItems"] for k in ("title", "why")]
            self.assertTrue(texts, name)
            for t in texts:
                self.assertIsNone(CADENCE.search(t), (name, t[:120]))

    def test_the_status_schedule_text_names_the_new_cadence(self):
        import weekly_cycle
        self.assertIn("1st and 15th", weekly_cycle.SCHEDULE_TEXT)


if __name__ == "__main__":
    unittest.main()
