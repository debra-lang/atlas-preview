"""Offline tests for the monthly retraction / correction check as the cycle applies it (weekly_cycle.retraction_check). The network part (check_retractions.run) is replaced by canned findings."""
import json, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402,F401
import check_retractions, weekly_cycle  # noqa: E402


def finding(ident, severity, study_ids, source="PubMed CommentsCorrections/PublicationType"):
    return {"identifier": ident, "severity": severity, "notices": [f"{severity} — notice text"], "studyIds": study_ids, "source": source}


class RetractionStep(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="te-ret-"))
        (self.root / "engine").mkdir(); (self.root / "data").mkdir()
        studies = [{"id": "s1", "title": "One", "pmid": "1"}, {"id": "s2", "title": "Two", "pmid": "2"}, {"id": "s3", "title": "Three", "pmid": "3"}]
        (self.root / "data" / "studies.json").write_text(json.dumps({"studies": studies}), encoding="utf-8")
        self._due, self._run = check_retractions.due, check_retractions.run
        check_retractions.due = lambda *a, **k: True

    def tearDown(self):
        check_retractions.due, check_retractions.run = self._due, self._run
        shutil.rmtree(self.root, ignore_errors=True)

    def apply(self, findings, held=None):
        check_retractions.run = lambda studies, state=None: findings
        c = weekly_cycle.Cycle(self.root)
        held = held if held is not None else {"items": []}
        c.retraction_check(held)
        return c, held

    def studies(self, c):
        d = c.staged.get("data/studies.json")
        return {s["id"]: s for s in (d["studies"] if d else [])}

    def test_a_retraction_gets_a_public_factual_notice_and_a_truthful_audit_record_without_changing_any_rating(self):
        c, held = self.apply([finding("PMID 1", "retracted", ["s1"])])
        n = self.studies(c)["s1"]["integrityNotice"]
        self.assertEqual(n["severity"], "retracted")
        self.assertIn("(source: PubMed CommentsCorrections/PublicationType)", n["text"])
        self.assertIn("No rating has been changed because of this notice", n["text"])
        self.assertNotIn("under review", n["text"])
        self.assertEqual(len(held["items"]), 1)
        self.assertIn("handled automatically", held["items"][0]["resolution"]); self.assertNotIn("unresolved", held["items"][0]["resolution"])
        self.assertNotIn("data/treatments.json", c.staged)                                         # no rating or treatment record is touched
        self.assertNotIn("data/rankings.json", c.staged)

    def test_partial_retractions_and_expressions_of_concern_are_treated_the_same(self):
        c, held = self.apply([finding("PMID 2", "partially-retracted", ["s2"]), finding("PMID 3", "expression-of-concern", ["s3"])])
        st = self.studies(c)
        self.assertEqual((st["s2"]["integrityNotice"]["severity"], st["s3"]["integrityNotice"]["severity"]), ("partially-retracted", "expression-of-concern"))

    def test_an_erratum_is_recorded_and_counted_but_never_queued_or_shown(self):
        c, held = self.apply([finding("PMID 1", "erratum", ["s1"]), finding("PMID 2", "erratum", ["s2"])])
        self.assertEqual(held["items"], [])
        self.assertNotIn("data/studies.json", c.staged)                                            # no notice on any study
        self.assertEqual(c.status["retractionErrata"], 2); self.assertEqual(c.status["retractionFindings"], 2)
        self.assertEqual(c.status["held"], 0)
        self.assertEqual([e for e in c.audit if e.get("severity") == "erratum"][0]["note"], "correction notice (erratum): recorded; no review item and no public change")

    def test_a_mixed_batch_queues_only_the_consequential_findings(self):
        c, held = self.apply([finding("PMID 1", "erratum", ["s1"]), finding("PMID 2", "retracted", ["s2"])])
        self.assertEqual([h["item"]["id"] for h in held["items"]], ["retraction-PMID 2"])
        self.assertEqual(list(self.studies(c)), ["s1", "s2", "s3"])
        self.assertNotIn("integrityNotice", self.studies(c)["s1"]); self.assertIn("integrityNotice", self.studies(c)["s2"])

    def test_the_same_finding_next_month_is_not_queued_or_noticed_twice(self):
        c, held = self.apply([finding("PMID 1", "retracted", ["s1"])])
        studies = c.staged["data/studies.json"]
        (self.root / "data" / "studies.json").write_text(json.dumps(studies), encoding="utf-8")
        c2, held2 = self.apply([finding("PMID 1", "retracted", ["s1"])], held=held)
        self.assertEqual(len(held2["items"]), 1)
        self.assertNotIn("data/studies.json", c2.staged)                                           # notice already there: nothing to rewrite

    def test_no_findings_is_logged_and_a_failed_check_is_reported_not_raised(self):
        c, held = self.apply([])
        self.assertEqual(held["items"], []); self.assertEqual(c.status["retractionFindings"], 0)
        def boom(studies, state=None):
            raise RuntimeError("network down")
        check_retractions.run = boom
        c = weekly_cycle.Cycle(self.root); c.retraction_check({"items": []})
        self.assertTrue(any("retraction check failed" in e for e in c.status["errors"]))


if __name__ == "__main__":
    unittest.main()
