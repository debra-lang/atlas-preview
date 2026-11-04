"""Release 1: a source that could not be read is never reported as checked, what needs a decision turns the run red after saving, every trial status change is seen, and no run can change a rating.
Run:  python -m unittest discover -s engine/tests -v"""
import io, json, re, shutil, subprocess, sys, tempfile, unittest, urllib.error, urllib.request
from itertools import permutations
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ENGINE, REPO  # noqa: E402
from cycle_sandbox import SOURCES, STATUS, TODAY, TRIALS, Sandbox, W  # noqa: E402

import weekly_cycle, weekly_scan  # noqa: E402

sys.path.insert(0, str(REPO / "tools"))
import rating_lock  # noqa: E402


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


RSS = b'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
HTML = b"<html><body><p>Service unavailable<br></body></html>"


def http_error(code):
    return urllib.error.HTTPError("https://example.invalid", code, "error", {}, None)


class ScannersSayWhatTheyCouldNotRead(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="te-rr-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        W(self.root, "engine/sources.json", {"newsIntel": [{"name": "a", "query": "a"}, {"name": "b", "query": "b"}], "pages": [{"name": "p", "url": "https://example.invalid/p"}, {"name": "q", "url": "https://example.invalid/q"}]})
        patcher = mock.patch.object(weekly_scan, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        weekly_scan.SCAN_PROBLEMS.clear()

    def fda(self, answer):
        with mock.patch.object(weekly_scan, "get_json", side_effect=answer):
            weekly_scan.scan_fda()
        return weekly_scan.SCAN_PROBLEMS["scan_fda"]

    def test_fda_zero_matches_is_a_quiet_period_not_a_failure(self):
        self.assertEqual(self.fda(Exception("HTTP Error 404: Not Found")), (3, []))

    def test_fda_results_are_clean(self):
        self.assertEqual(self.fda(lambda u: {"results": []}), (3, []))

    def test_fda_server_error_is_a_failure(self):
        self.assertEqual(len(self.fda(Exception("HTTP Error 500"))[1]), 3)

    def test_fda_error_body_with_status_200_is_a_failure(self):
        self.assertEqual(len(self.fda(lambda u: {"error": {"code": "SERVER_ERROR"}})[1]), 3)

    def test_fda_html_instead_of_json_is_a_failure(self):
        self.assertEqual(len(self.fda(ValueError("Expecting value"))[1]), 3)

    def test_one_fda_part_failing_names_it(self):
        answers = iter([{"results": []}, Exception("HTTP Error 500"), {"results": []}])

        def next_answer(u):
            a = next(answers)
            if isinstance(a, Exception):
                raise a
            return a
        parts, failed = self.fda(next_answer)
        self.assertEqual((parts, failed), (3, ["PMA decision"]))

    def test_news_answers_and_failures(self):
        with mock.patch("urllib.request.urlopen", side_effect=[Answer(RSS), http_error(503)]):
            weekly_scan.scan_news_intel()
        self.assertEqual(weekly_scan.SCAN_PROBLEMS["scan_news_intel"], (2, ["b"]))

    def test_news_html_is_a_failure_and_an_empty_feed_is_not(self):
        with mock.patch("urllib.request.urlopen", side_effect=[Answer(HTML), Answer(RSS)]):
            weekly_scan.scan_news_intel()
        self.assertEqual(weekly_scan.SCAN_PROBLEMS["scan_news_intel"], (2, ["a"]))

    def test_a_page_that_fails_keeps_its_old_hash_and_is_named(self):
        W(self.root, "engine/page-hashes.json", {"https://example.invalid/q": "old"})
        with mock.patch("urllib.request.urlopen", side_effect=[Answer(b"<p>page</p>"), http_error(403)]):
            weekly_scan.scan_pages()
        self.assertEqual(weekly_scan.SCAN_PROBLEMS["scan_pages"], (2, ["q"]))
        self.assertEqual(json.loads((self.root / "engine/page-hashes.json").read_text(encoding="utf-8"))["https://example.invalid/q"], "old")


def health(root, status):
    """The real last step of the workflow, on this status file."""
    (root / "engine").mkdir(exist_ok=True)
    (root / "data").mkdir(exist_ok=True)
    shutil.copy(ENGINE / "check_evaluation_health.py", root / "engine")
    (root / "data/engine-status.json").write_text(json.dumps(status), encoding="utf-8")
    return subprocess.run([sys.executable, "-X", "utf8", str(root / "engine/check_evaluation_health.py")], capture_output=True, text=True, encoding="utf-8")


class WhatTurnsARunRed(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="te-rr-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def code(self, *errors):
        return health(self.root, {"errors": list(errors), "evaluation": {"state": "disabled", "disabledSince": TODAY}, "listings": {}}).returncode

    def test_a_clean_run_is_green(self):
        self.assertEqual(self.code(), 0)

    def test_red(self):
        for e in ("source 'PubMed' failed: timeout", "listings step failed: KeyError", "retraction check failed: x", "coverage gap: every watched feed failed: a", "source 'x' last succeeded 200 days ago (coverage gap: check by hand)", "something nobody has seen before"):
            self.assertEqual(self.code(e), 1, e)

    def test_not_red_but_shown(self):
        for e in ("2 item(s) failed source verification and were not listed (kept in the queue)", "source 'News' incomplete: a", "trial refresh NCT00000001: timeout", "trial refresh NCT00000001: registry status outside the allowed list, not published", "AI evaluation skipped: x"):
            r = health(self.root, {"errors": [e], "evaluation": {"state": "disabled", "disabledSince": TODAY}, "listings": {}})
            self.assertEqual(r.returncode, 0, e)
            self.assertIn(e[:30], r.stdout + r.stderr)

    def test_many_trials_failing_is_red(self):
        self.assertEqual(self.code(*[f"trial refresh NCT0000000{i}: timeout" for i in range(4)]), 0)
        self.assertEqual(self.code(*[f"trial refresh NCT0000000{i}: timeout" for i in range(5)]), 1)


class ThroughTheRealCycle(Sandbox):
    keep_real = ("scan_fda",)

    def J(self, rel):
        return json.loads((self.root / rel).read_text(encoding="utf-8"))

    def checked(self, report):
        """The list after "Sources checked:", which ends at a full stop followed by a space or the end of the text: "ClinicalTrials.gov" has a dot of its own."""
        return re.search(r"Sources checked: (.*?)\.(?: |\")", report).group(1)

    def fda_run(self, answer):
        with mock.patch.object(weekly_scan, "get_json", side_effect=answer):
            rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-400:])
        src = next(s for s in self.J(STATUS)["sources"] if s["name"].startswith("FDA"))
        return src, json.dumps(self.J(f"data/weekly/{TODAY}.json"), ensure_ascii=False), self.J(STATUS)

    def test_a_source_that_failed_is_not_reported_as_checked(self):
        src, report, status = self.fda_run(Exception("HTTP Error 500"))
        self.assertFalse(src["checked"])
        self.assertIn("3 of 3", src["error"])
        self.assertTrue(any(e.startswith("source 'FDA") and "failed" in e for e in status["errors"]))
        self.assertIn("Could not be fully read: FDA databases", report)
        self.assertNotIn("FDA databases", self.checked(report))
        self.assertIn("PubMed", self.checked(report))

    def test_a_quiet_source_is_reported_as_checked(self):
        src, report, status = self.fda_run(Exception("HTTP Error 404"))
        self.assertTrue(src["checked"])
        self.assertIsNone(src["error"])
        self.assertEqual(status["errors"], [])
        self.assertIn("FDA databases", self.checked(report))
        self.assertNotIn("Could not be fully read", report)

    def test_the_failed_source_turns_the_run_red_after_its_results_are_saved(self):
        self.fda_run(Exception("HTTP Error 500"))
        self.assertIn("A newly scanned tinnitus trial", {i["title"] for i in self.J("data/review-queue/queue.json")["items"]})      # the other sources' records are saved
        self.assertEqual(health(self.root, self.J(STATUS)).returncode, 1)


class EveryStatusChangeIsSeen(unittest.TestCase):
    def test_every_pair_of_statuses_is_a_change(self):
        for a, b in permutations(weekly_cycle.TRIAL_STATUS.values(), 2):
            self.assertNotEqual(weekly_cycle.status_key(b), weekly_cycle.current_status(a), (a, b))

    def test_a_status_is_not_a_change_from_itself(self):
        for a in weekly_cycle.TRIAL_STATUS.values():
            self.assertEqual(weekly_cycle.status_key(a), weekly_cycle.current_status(f"{a} (verified at ClinicalTrials.gov 2026-11-01)"), a)

    def test_the_forms_the_stored_lines_really_take(self):
        for line, want in (("Listed 'Recruiting' — registry stale (not updated since Oct 2024; primary completion date has passed)", "recruiting"), ("Active, not recruiting (verified at ClinicalTrials.gov 2026-11-01)", "activenotrecruiting"),
                           ("Not yet recruiting", "notyetrecruiting"), ("Completed; results posted", "completed"), ("Unknown status", "unknownstatus"), ("Something else entirely", None), ("", None), (None, None)):
            self.assertEqual(weekly_cycle.current_status(line), want, line)

    def test_every_status_on_the_real_tracked_trials_is_understood(self):
        for t in json.loads((REPO / "data/trials.json").read_text(encoding="utf-8")):
            self.assertIsNotNone(weekly_cycle.current_status(t["status"]), t["nctId"])


GOOD = {"data/treatments.json": {"treatments": [{"id": "a", "tier": 1, "evidenceScore": 3, "confidence": "x", "replication": "y", "independence": "z", "safetyLevel": "s", "category": "c", "subtypeTags": ["t"], "loudness": {"level": "limited", "summary": "s"}, "distress": {"level": "none"}, "latest": []}]},
        "data/studies.json": {"studies": [{"id": "s", "independent": True, "title": "t"}]}, "data/rankings.json": {"r": [1]}, "data/claims.json": {"claims": [{"verdict": "x"}]}}


def changed(fn):
    new = json.loads(json.dumps(GOOD))
    fn(new)
    return rating_lock.compare(GOOD, new)


class TheRatingLock(unittest.TestCase):
    def test_no_change_no_stop(self):
        self.assertEqual(rating_lock.compare(GOOD, json.loads(json.dumps(GOOD))), [])

    def test_every_protected_field_stops_it(self):
        for k in ("tier", "evidenceScore", "confidence", "replication", "independence", "safetyLevel", "category", "subtypeTags"):       # written out, so narrowing the lock's own list fails here
            self.assertTrue(changed(lambda d: d["data/treatments.json"]["treatments"][0].__setitem__(k, "other")), k)
        for k in ("loudness", "distress"):
            self.assertTrue(changed(lambda d: d["data/treatments.json"]["treatments"][0][k].__setitem__("level", "moderate")), k)

    def test_a_treatment_added_removed_or_moved_stops_it(self):
        self.assertTrue(changed(lambda d: d["data/treatments.json"]["treatments"].append({"id": "b"})))
        self.assertTrue(changed(lambda d: d["data/treatments.json"]["treatments"].clear()))

    def test_a_study_flag_or_set_stops_it(self):
        self.assertTrue(changed(lambda d: d["data/studies.json"]["studies"][0].__setitem__("independent", False)))
        self.assertTrue(changed(lambda d: d["data/studies.json"]["studies"].clear()))

    def test_rankings_and_claims_stop_it(self):
        self.assertTrue(changed(lambda d: d["data/rankings.json"].__setitem__("r", [2])))
        self.assertTrue(changed(lambda d: d["data/claims.json"]["claims"][0].__setitem__("verdict", "y")))

    def test_what_a_run_may_write_does_not_stop_it(self):
        def run_writes(d):
            d["data/treatments.json"]["treatments"][0]["latest"] = [{"title": "news"}]
            d["data/treatments.json"]["treatments"][0]["loudness"]["summary"] = "other"
            d["data/studies.json"]["studies"][0]["integrityNotice"] = {"severity": "correction"}
        self.assertEqual(changed(run_writes), [])

    def test_plain_lists_work_as_well_as_wrapped_ones(self):
        plain = {**GOOD, "data/treatments.json": GOOD["data/treatments.json"]["treatments"]}
        self.assertEqual(rating_lock.compare(GOOD, plain), [])

    def test_in_a_real_checkout(self):
        root = Path(tempfile.mkdtemp(prefix="te-rr-"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        for f, v in GOOD.items():
            W(root, f, v)
        self.assertEqual(rating_lock.check(root)[0], [])         # no git here: says so, and stops nothing
        self.assertIn("not checked", rating_lock.check(root)[1])
        g = lambda *a: subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
        g("init", "-q")
        g("add", "-A")
        g("commit", "-q", "-m", "x")
        self.assertEqual(rating_lock.check(root)[0], [])
        bad = json.loads(json.dumps(GOOD["data/treatments.json"]))
        bad["treatments"][0]["tier"] = 2
        W(root, "data/treatments.json", bad)
        self.assertTrue(any("tier" in e for e in rating_lock.check(root)[0]))
        g("add", "-A")
        g("commit", "-q", "-m", "an owner's reviewed change moves the baseline")
        self.assertEqual(rating_lock.check(root)[0], [])


if __name__ == "__main__":
    unittest.main()
