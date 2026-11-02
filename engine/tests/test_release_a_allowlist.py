"""Release A's data guards (owner decisions, 23 Oct 2026): every difference from the baseline under data/ matches one allowlist entry exactly, every
entry is applied, and protected fields are locked independently of the list. Offline. Run:  python -m unittest discover -s engine/tests -v"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_allowlist as ra  # noqa: E402

TREATMENT_LOCKED = ("tier", "evidenceScore", "confidence", "replication", "independence", "safetyLevel", "category")
STUDY_LOCKED = ("independent", "randomized", "sham", "n", "design", "primaryOutcome", "url")


class ReleaseAAllowlist(unittest.TestCase):
    def setUp(self):
        self.base = ra.merge_base()
        if not self.base:
            self.skipTest("no origin/main in this checkout to compare against")
        self.state = ra.state(self.base)
        if self.state == "retired":
            self.skipTest("Release A is in production: this allowlist is retired")

    def test_the_branch_is_built_on_the_allowlist_baseline(self):
        self.assertEqual(self.state, "active", f"base {self.base[:7]} is not the allowlist's baseline {ra.BASELINE[:7]}: re-measure the allowlist against it")

    def test_every_data_difference_is_an_allowlist_entry_and_every_entry_is_applied(self):
        names = ra.git("diff", "--name-only", self.base, "--", "data/").stdout.split()
        self.assertEqual(sorted(names), ra.FILES)
        self.assertEqual(ra.problems(self.base), [])

    def test_undoing_the_list_gives_the_baseline_exactly(self):
        for rel in ra.FILES:
            self.assertEqual(ra.undo(rel, ra.now(rel)), ra.at(self.base, rel), rel)

    def test_protected_treatment_fields_are_locked_whatever_the_list_says(self):
        old, new = ra.at(self.base, "data/treatments.json"), ra.now("data/treatments.json")
        self.assertEqual([t["id"] for t in new], [t["id"] for t in old])
        for a, b in zip(old, new):
            for f in TREATMENT_LOCKED:
                self.assertEqual(b.get(f), a.get(f), f"{a['id']}.{f}")
            for o in ("loudness", "distress"):
                self.assertEqual(b[o]["level"], a[o]["level"], f"{a['id']}.{o}.level")

    def test_study_flags_are_locked_with_one_exact_exception(self):
        old, new = ra.at(self.base, "data/studies.json"), ra.now("data/studies.json")
        self.assertEqual([s["id"] for s in new], [s["id"] for s in old])
        exc = ra.EXCEPTION
        for a, b in zip(old, new):
            for f in STUDY_LOCKED:
                if a["id"] == exc["id"] and f == "independent":
                    self.assertIs(a[f], exc["before"]); self.assertIs(b[f], exc["after"])   # the exception must actually be exercised
                else:
                    self.assertEqual(b.get(f), a.get(f), f"{a['id']}.{f}")

    def test_rankings_and_trials_are_untouched(self):
        for rel in ("data/rankings.json", "data/trials.json"):
            self.assertEqual(ra.now(rel), ra.at(self.base, rel), rel)

    def test_every_changed_record_has_a_new_history_entry(self):
        for rel, rid in sorted({(e["file"], e["id"]) for e in ra.ENTRIES}):
            old = [r for r in ra.at(self.base, rel) if r["id"] == rid][0]; new = [r for r in ra.now(rel) if r["id"] == rid][0]
            self.assertGreater(len(new.get("history", [])), len(old.get("history", [])), rid)      # required, but only as an extra check: a history entry never authorises a change


if __name__ == "__main__":
    unittest.main()
