"""Tests for engine/weekly_digest.py (the local weekly editorial page) and the usage ledger. Offline; no key, no network."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import staged_review, weekly_digest as wd  # noqa: E402

TODAY = date(2026, 10, 26)


def entry(iid, route, title="A study", escalation=None, importance="Interesting but Early"):
    ev = {"importance": importance, "confidence": "high", "escalation": escalation or [], "weeklyTitle": title}
    e = staged_review.make_entry({"id": iid, "title": title, "evaluation": ev, "evalInput": {}}, route, "because", {"title": title}, now="2026-10-26T06:10:00")
    return e


STATUS = {"newItems": 31, "rejectedDuplicates": 3, "rejectedIrrelevant": 10, "archived": 4, "paused": 2, "notices": {"cited": 1, "uncited": 1, "unresolved": 0}, "lastSuccess": "2026-10-26T06:05:00",
          "sources": [{"name": "PubMed", "error": None}, {"name": "openFDA", "error": "timeout"}], "errors": [],
          "evaluation": {"state": "ok", "mode": "staged", "attempted": 13, "succeeded": 13, "failed": 0, "screenedWithoutAI": 5, "usage": {"estimatedCostUSD": 0.62, "inputTokens": 100, "outputTokens": 50, "model": "claude-opus-5"}}}


class DigestNumbers(unittest.TestCase):
    def digest(self, status=STATUS, staged=None, held=None, ledger=None):
        return wd.build_digest(status, staged or {"items": []}, held or {"items": []}, ledger or {"runs": []}, today=TODAY)

    def test_counts_are_computed_from_the_records(self):
        st = {"items": [entry("pubmed-1", "publish", importance="Negative Result"), entry("pubmed-2", "publish"), entry("pubmed-3", "hold"),
                        entry("pubmed-4", "publish", escalation=[{"tier": "level3", "kind": "safety-term", "detail": ["seizure"]}]), entry("pubmed-5", "irrelevant")]}
        held = {"items": [{"heldAt": "2026-10-26T06:00:00", "reason": "correction notice concerns a cited study", "item": {"id": "pubmed-9", "title": "Correction: X"}}]}
        d = self.digest(staged=st, held=held)
        self.assertEqual((d["discovered"], d["automatic"], d["onHold"]), (31, 3 + 10 + 4 + 1, 2))
        self.assertEqual(d["awaitingVerification"], 3)                                   # pubmed-1, -2, -5
        self.assertEqual(d["needsYou"], 1)                                               # only the plain hold (Level 2) needs the owner
        self.assertEqual(sorted(c["id"] for c in d["clinicalWaiting"]), ["pubmed-4", "pubmed-9"])   # the Level 3 trigger and the held cited notice wait for a clinician
        self.assertEqual(d["clinicalWaitingCount"], 2)
        self.assertEqual(sorted(c["id"] for c in d["important"]), ["pubmed-1", "pubmed-2"])      # proposed-irrelevant pubmed-5 is not an "important finding"
        self.assertEqual(d["evaluation"]["screenedWithoutAI"], 5)

    def test_cost_and_month_to_date(self):
        led = {"runs": [{"date": "2026-10-05", "estimatedCostUSD": 0.9}, {"date": "2026-10-19", "estimatedCostUSD": 0.5}, {"date": "2026-09-28", "estimatedCostUSD": 9.0}]}
        d = self.digest(ledger=led)
        self.assertEqual((d["costWeekUSD"], d["costMonthToDateUSD"]), (0.62, 1.4))       # the September run is not in October's total

    def test_state_green_amber_red_and_problems_are_listed(self):
        quiet = dict(STATUS, sources=[{"name": "PubMed", "error": None}])
        self.assertEqual(self.digest(quiet)["state"], "green")
        self.assertEqual(self.digest(quiet, staged={"items": [entry("pubmed-3", "hold")]})["state"], "amber")
        bad = dict(quiet, evaluation=dict(quiet["evaluation"], state="failed", reason="credit balance too low"))
        d = self.digest(bad)
        self.assertEqual(d["state"], "red"); self.assertTrue(any("credit balance" in p for p in d["problems"]))
        d = self.digest(STATUS)
        self.assertTrue(any("openFDA" in p for p in d["problems"]))                      # a source that did not answer is shown, not hidden

    def test_level3_items_get_no_decision_command_and_the_page_says_the_owners_approval_does_not_release_them(self):
        l3 = entry("pubmed-4", "hold", escalation=[{"tier": "level3", "kind": "safety-term", "detail": ["seizure"]}], title="Seizure report")
        plain = entry("pubmed-3", "hold", title="Plain hold")
        d = self.digest(staged={"items": [l3, plain]})
        page = wd.render_html(d)
        section = page.split("Waiting for clinical review (1)")[1].split("<h2>Important")[0]
        self.assertIn("Seizure report", section); self.assertNotIn("staged_review.py decide", section)          # no way to decide it from the page
        self.assertIn("Your approval alone does not release them", page)
        self.assertIn("staged_review.py decide pubmed-3", page.split("Waiting for clinical review (1)")[0])       # the plain hold keeps its commands, above the clinical section
        self.assertNotIn("Plain hold", section)

    def test_model_proposed_score_rank_major_or_safety_changes_are_clinical_waiting_even_without_a_lexical_trigger(self):
        def e(iid, **ev):
            x = entry(iid, "hold"); x["item"]["evaluation"].update(ev); return x
        d = self.digest(staged={"items": [e("a", changeClass="major"), e("b", proposedScoreChange="+1"), e("c", proposedRankChange="up"), e("d", safetySignal=True), e("e", changeClass="routine")]})
        self.assertEqual(sorted(c["id"] for c in d["clinicalWaiting"]), ["a", "b", "c", "d"]); self.assertEqual([c["id"] for c in d["attention"]], ["e"])

    def test_a_language_hold_is_labelled_as_such_not_as_a_clinical_matter(self):
        held = {"items": [{"heldAt": "2026-10-25T06:00:00", "reason": "R4 - the abstract text is not in English: held for a person to read", "item": {"id": "pubmed-7", "title": "Acouphenes"}},
                          {"heldAt": "2026-10-25T06:00:00", "reason": "retraction of a cited study", "item": {"id": "pubmed-8", "title": "Retracted"}}]}
        d = self.digest(held=held)
        labels = {c["id"]: c["level3"][0] for c in d["clinicalWaiting"]}
        self.assertIn("rule R4", labels["pubmed-7"]); self.assertNotIn("conclusion", labels["pubmed-7"])
        self.assertIn("conclusion", labels["pubmed-8"])

    def test_every_held_item_stays_listed_with_its_age_and_an_old_one_turns_the_page_amber(self):
        quiet = dict(STATUS, sources=[{"name": "PubMed", "error": None}])
        held = {"items": [{"heldAt": "2026-08-01T06:00:00", "reason": "retraction of a cited study", "item": {"id": "pubmed-8", "title": "Old notice"}}]}
        d = self.digest(quiet, held=held)
        self.assertEqual(d["clinicalWaitingCount"], 1); self.assertEqual(d["clinicalOldestDays"], 86); self.assertEqual(d["state"], "amber")     # waited more than 30 days
        fresh = {"items": [{"heldAt": "2026-10-20T06:00:00", "reason": "x", "item": {"id": "pubmed-8", "title": "New notice"}}]}
        d2 = self.digest(quiet, held=fresh)
        self.assertEqual((d2["clinicalWaitingCount"], d2["clinicalOldestDays"], d2["state"]), (1, 6, "green"))      # a recent one alone needs nothing from the owner
        self.assertEqual(self.digest(quiet)["clinicalWaitingCount"], 0)

    def test_measurements_that_do_not_exist_yet_are_declared(self):
        self.assertEqual(len(self.digest()["notMeasuredYet"]), 3)


class DigestReleaseLine(unittest.TestCase):
    def test_a_plain_hold_shows_release_eligibility_only_when_supplied_and_level3_cards_never_do(self):
        plain = entry("pubmed-3", "hold", title="Plain hold")
        d = wd.build_digest(STATUS, {"items": [plain]}, {"items": []}, {"runs": []}, today=TODAY, release={"pubmed-3": (True, [])})
        page = wd.render_html(d)
        self.assertIn("source-verified release: <b>eligible</b>", page)
        d2 = wd.build_digest(STATUS, {"items": [plain]}, {"items": []}, {"runs": []}, today=TODAY, release={"pubmed-3": (False, ["a Level 3 trigger or reviewer flag is present: x", "second", "third", "fourth"])})
        p2 = wd.render_html(d2); self.assertIn("not eligible", p2); self.assertNotIn("fourth", p2)
        self.assertNotIn("source-verified release", wd.render_html(wd.build_digest(STATUS, {"items": [plain]}, {"items": []}, {"runs": []}, today=TODAY)))     # path off: no line
        l3 = entry("pubmed-4", "hold", escalation=[{"tier": "level3", "kind": "safety-term", "detail": ["seizure"]}], title="Seizure report")
        p3 = wd.render_html(wd.build_digest(STATUS, {"items": [l3]}, {"items": []}, {"runs": []}, today=TODAY, release={"pubmed-4": (True, [])}))
        self.assertNotIn("source-verified release", p3.split("Waiting for clinical review")[1].split("<h2>Important")[0])      # Level 3 cards never offer it


class DigestPageSafety(unittest.TestCase):
    def test_record_text_is_escaped_and_the_page_has_no_script_form_or_network_reference(self):
        evil = "<script>alert(1)</script><img src=x onerror=alert(2)>"
        st = {"items": [entry("pubmed-7", "hold", title=evil)]}
        page = wd.render_html(wd.build_digest(STATUS, st, {"items": []}, {"runs": []}, today=TODAY))
        self.assertNotIn("<script", page.lower()); self.assertNotIn("<img", page.lower()); self.assertNotIn("<form", page.lower())
        self.assertNotIn("http://", page); self.assertNotIn("https://", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("PRIVATE", page)


class DigestCli(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="te-digest-"))
        (self.root / "data" / "review-queue").mkdir(parents=True)
        (self.root / "data" / "engine-status.json").write_text(json.dumps(STATUS), encoding="utf-8")
        self.staged = {"items": [entry("pubmed-1", "publish"), entry("pubmed-3", "hold")]}

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_plain_files_produce_a_page(self):
        (self.root / "data/review-queue/staged.json").write_text(json.dumps(self.staged), encoding="utf-8")
        out = self.root / "d.html"
        wd.main(["--out", str(out), "--root", str(self.root)])
        self.assertIn("Weekly digest", out.read_text(encoding="utf-8"))

    @unittest.skipUnless(shutil.which("openssl"), "openssl not available")
    def test_the_encrypted_store_is_decrypted_in_memory_with_the_key_from_the_environment(self):
        plain = self.root / "p.json"; plain.write_text(json.dumps(self.staged), encoding="utf-8")
        os.environ["STATE_KEY"] = "fake-digest-test-key-1234567890"
        try:
            staged_review.encrypt_file(plain, self.root / "data/review-queue/staged.json.enc")
            plain.unlink()
            out = self.root / "d.html"
            wd.main(["--out", str(out), "--root", str(self.root), "--json"])
            self.assertEqual(json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["needsYou"], 1)
            os.environ["STATE_KEY"] = "wrong-key-wrong-key-wrong-key-00"
            with self.assertRaises(RuntimeError):
                wd.main(["--out", str(out), "--root", str(self.root)])
        finally:
            os.environ.pop("STATE_KEY", None)


class UsageLedger(unittest.TestCase):
    def test_a_run_that_calls_the_model_appends_one_ledger_line(self):
        r = run_scenario({"queue": [pubmed_item(90000061), pubmed_item(90000062)], "tokensIn": 11000, "tokensOut": 2300, "settings": {"enabled": True, "mode": "staged", "limitPerRun": 5}, "runs": [{}, {}]})
        runs = r["runs"][0]["ledger"]["runs"]
        self.assertEqual(len(runs), 1)
        self.assertEqual((runs[0]["attempted"], runs[0]["inputTokens"], runs[0]["outputTokens"]), (2, 22000, 4600))
        self.assertEqual(len(r["runs"][1]["ledger"]["runs"]), 1)                       # the second run evaluated nothing: no new line

    def test_no_ledger_line_when_evaluation_is_off(self):
        r = run_scenario({"queue": [pubmed_item(90000063)], "settings": {"enabled": False, "mode": "staged"}, "runs": [{}]})["runs"][0]
        self.assertEqual(r["ledger"]["runs"], [])


if __name__ == "__main__":
    unittest.main()
