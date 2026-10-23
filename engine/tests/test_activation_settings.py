"""The shipped Phase 1 switches (engine/automation_settings.json), as activated on the owner's approval: exact values, and the paused-record allow-list names only paused guideline records."""
import json, sys, unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))
import listings  # noqa: E402


class Shipped(unittest.TestCase):
    def test_the_shipped_switches(self):
        cfg = json.loads((ENGINE / "automation_settings.json").read_text(encoding="utf-8"))
        s = listings.load_settings(cfg)
        self.assertEqual((s["listings"], s["updateHistory"]), (True, True))
        self.assertEqual(s["includePaused"], ["pubmed-42861423", "pubmed-42861475", "pubmed-42861486"])

    def test_only_paused_pubmed_records_are_on_the_allow_list_and_the_pause_is_untouched(self):
        paused = json.loads((ENGINE / "paused_ids.json").read_text(encoding="utf-8"))["ids"]
        allow = listings.load_settings(json.loads((ENGINE / "automation_settings.json").read_text(encoding="utf-8")))["includePaused"]
        self.assertTrue(set(allow) <= set(paused))
        self.assertEqual(sorted(i for i in paused if i.startswith("pubmed-")), allow)       # the pause list itself is unchanged: still all three, still paused

    def test_the_ai_evaluation_switch_is_still_off(self):
        ev = json.loads((ENGINE / "eval_settings.json").read_text(encoding="utf-8"))
        self.assertIs(ev["enabled"], False)
        self.assertIs(ev.get("sourceVerifiedRelease"), False)


if __name__ == "__main__":
    unittest.main()
