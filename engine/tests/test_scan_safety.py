"""A source's successful-scan clock moves only after a COMPLETE, well-formed scan; interruptions never leave a clock ahead of its records; duplicates stay prevented after a long look-back;
a gap beyond the maximum is visibly reported. Offline (owner request, 22 Oct 2026)."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import weekly_cycle, weekly_scan, weekly_digest as wd  # noqa: E402

TODAY = date(2026, 11, 15)
REAL_PUBMED, REAL_CTGOV = weekly_scan.scan_pubmed, weekly_scan.scan_ctgov      # the genuine scanners, captured before any test replaces them
OLD = (TODAY - timedelta(days=30)).isoformat()


class D(date):
    @classmethod
    def today(cls):
        return TODAY


def new_cycle(state=None, known=(), queue_items=()):
    root = Path(tempfile.mkdtemp(prefix="te-ss-"))
    (root / "data" / "review-queue").mkdir(parents=True); (root / "engine").mkdir()
    (root / "data/review-queue/queue.json").write_text(json.dumps({"items": list(queue_items)}), encoding="utf-8")
    (root / "engine/known_ids.json").write_text(json.dumps(list(known)), encoding="utf-8")
    (root / "engine/scan-state.json").write_text(json.dumps(state if state is not None else {"pubmed": OLD, "ctgov": OLD}), encoding="utf-8")
    return weekly_cycle.Cycle(root)


class Patched:
    """Replace the six real scanners and the date, restore afterwards."""
    NAMES = ("scan_pubmed", "scan_ctgov", "scan_feeds", "scan_fda", "scan_news_intel", "scan_pages")

    def __init__(self, **fns):
        self.fns = fns

    def __enter__(self):
        self.orig = {n: getattr(weekly_scan, n) for n in self.NAMES}
        self.gj, self.sl, self.cd = weekly_scan.get_json, weekly_scan.time.sleep, weekly_cycle.date
        for n in self.NAMES:
            setattr(weekly_scan, n, self.fns.get(n, lambda: []))
        weekly_scan.time.sleep = lambda s: None
        weekly_cycle.date = D
        return self

    def __exit__(self, *a):
        for n, f in self.orig.items():
            setattr(weekly_scan, n, f)
        weekly_scan.get_json, weekly_scan.time.sleep, weekly_cycle.date = self.gj, self.sl, self.cd


def clock(c, key="pubmed"):
    return json.loads((c.root / "engine/scan-state.json").read_text(encoding="utf-8")).get(key)


def pubmed_with(get_json):
    """The REAL scan_pubmed on a scripted PubMed."""
    def f():
        weekly_scan.get_json = get_json
        return REAL_PUBMED()
    return f


def ctgov_with(get_json):
    def f():
        weekly_scan.get_json = get_json
        return REAL_CTGOV()
    return f


IDS = [str(5000 + i) for i in range(230)]


def good_pubmed(url):
    if "esearch" in url:
        start = int(url.split("retstart=")[1].split("&")[0])
        return {"esearchresult": {"count": str(len(IDS)), "idlist": IDS[start:start + 100]}}
    ids = url.split("id=")[1].split("&")[0].split("%2C")
    return {"result": {"uids": ids, **{i: {"title": "T" + i, "pubtype": []} for i in ids}}}


class OneCompleteScanAdvancesTheClock(unittest.TestCase):
    def test_a_complete_paginated_scan_advances_it(self):
        c = new_cycle()
        with Patched(scan_pubmed=pubmed_with(good_pubmed)):
            c.scan(); c.commit()
        self.assertEqual(clock(c), TODAY.isoformat()); self.assertEqual(c.status["errors"], [])
        self.assertEqual(len(json.loads((c.root / "data/review-queue/queue.json").read_text(encoding="utf-8"))["items"]), 230)


class PartialAndFailedScansNeverAdvanceIt(unittest.TestCase):
    def assert_kept(self, scanner, key="pubmed", error_fragment=""):
        c = new_cycle()
        with Patched(**{("scan_pubmed" if key == "pubmed" else "scan_ctgov"): scanner}):
            c.scan(); c.commit()
        self.assertEqual(clock(c, key), OLD, "the previous successful-scan timestamp must be preserved")
        self.assertTrue(any(error_fragment in e for e in c.status["errors"]), c.status["errors"])
        return c

    def test_a_scan_that_dies_on_the_second_page_of_pubmed(self):
        def gj(url):
            if "esearch" in url and "retstart=100" in url:
                raise OSError("connection reset")
            return good_pubmed(url)
        c = self.assert_kept(pubmed_with(gj), error_fragment="PubMed")
        self.assertEqual(json.loads((c.root / "data/review-queue/queue.json").read_text(encoding="utf-8"))["items"], [])      # nothing from a half-finished scan is kept either

    def test_a_scan_that_dies_between_summary_chunks(self):
        n = {"i": 0}

        def gj(url):
            if "esummary" in url:
                n["i"] += 1
                if n["i"] == 2:
                    raise TimeoutError("slow")
            return good_pubmed(url)
        self.assert_kept(pubmed_with(gj), error_fragment="PubMed")

    def test_pubmed_malformed_or_error_responses(self):
        cases = {
            "no count": lambda u: {"esearchresult": {"idlist": ["1"]}} if "esearch" in u else good_pubmed(u),
            "error field": lambda u: {"esearchresult": {"ERROR": "Invalid query", "count": "0", "idlist": []}} if "esearch" in u else good_pubmed(u),
            "idlist not a list": lambda u: {"esearchresult": {"count": "1", "idlist": "1"}} if "esearch" in u else good_pubmed(u),
            "no esearchresult": lambda u: {"header": {}} if "esearch" in u else good_pubmed(u),
            "not json": lambda u: (_ for _ in ()).throw(ValueError("Expecting value")),
            "summary missing records": lambda u: ({"result": {"uids": []}} if "esummary" in u else good_pubmed(u)),
            "summary record with an error": lambda u: ({"result": {"uids": ["5000"], "5000": {"error": "cannot get document summary"}}} if "esummary" in u else {"esearchresult": {"count": "1", "idlist": ["5000"]}}),
            "summary without result": lambda u: ({"error": "x"} if "esummary" in u else good_pubmed(u)),
        }
        for name, gj in cases.items():
            with self.subTest(name):
                self.assert_kept(pubmed_with(gj), error_fragment="malformed" if name in ("no count", "error field", "idlist not a list") else "")

    def test_ctgov_second_page_failure_and_malformed_responses(self):
        studies = [{"protocolSection": {"identificationModule": {"nctId": "NCT00000001", "briefTitle": "t"}, "statusModule": {"lastUpdatePostDateStruct": {"date": "2026-11-01"}}}}]

        def two_pages_then_fail(url):
            if "pageToken=p2" in url:
                raise OSError("down")
            return {"studies": studies, "nextPageToken": "p2"}
        cases = {"second page fails": two_pages_then_fail, "no studies key": lambda u: {"totalCount": 0}, "studies not a list": lambda u: {"studies": "x"},
                 "not an object": lambda u: [1, 2], "error object": lambda u: {"error": "bad request"}}
        for name, gj in cases.items():
            with self.subTest(name):
                self.assert_kept(ctgov_with(gj), key="ctgov", error_fragment="ClinicalTrials.gov" if name == "second page fails" else "malformed response")

    def test_an_empty_window_is_a_real_success_not_a_failure(self):
        c = new_cycle()
        with Patched(scan_pubmed=pubmed_with(lambda u: {"esearchresult": {"count": "0", "idlist": []}}), scan_ctgov=ctgov_with(lambda u: {"studies": []})):
            c.scan(); c.commit()
        self.assertEqual((clock(c), clock(c, "ctgov")), (TODAY.isoformat(), TODAY.isoformat())); self.assertEqual(c.status["errors"], [])      # both APIs answer an empty window explicitly (verified live)


class InterruptionsKeepThePreviousTimestamp(unittest.TestCase):
    def test_an_interrupt_during_a_scan_propagates_and_changes_nothing_on_disk(self):
        c = new_cycle()
        before = (c.root / "engine/scan-state.json").read_text(encoding="utf-8")

        def boom():
            raise KeyboardInterrupt()
        with Patched(scan_pubmed=boom):
            with self.assertRaises(KeyboardInterrupt):
                c.scan()
        self.assertEqual((c.root / "engine/scan-state.json").read_text(encoding="utf-8"), before)

    def test_an_interrupt_during_the_commit_never_leaves_the_clock_ahead_of_its_records(self):
        for kill_at in (1, 2, 3):
            with self.subTest(kill_at=kill_at):
                c = new_cycle()
                with Patched(scan_pubmed=pubmed_with(good_pubmed)):
                    c.scan()
                    n = {"i": 0}
                    real = Path.replace

                    def flaky(self_, target):
                        n["i"] += 1
                        if n["i"] == kill_at:
                            raise KeyboardInterrupt()
                        return real(self_, target)
                    Path.replace = flaky
                    try:
                        with self.assertRaises(KeyboardInterrupt):
                            c.commit()
                    finally:
                        Path.replace = real
                queue = json.loads((c.root / "data/review-queue/queue.json").read_text(encoding="utf-8"))["items"]
                known = json.loads((c.root / "engine/known_ids.json").read_text(encoding="utf-8"))
                if clock(c) != OLD:                                          # the clock may advance only if the records and the known-id register were already written
                    self.assertEqual(len(queue), 230); self.assertEqual(len(known), 230)

    def test_the_clock_is_staged_after_the_records(self):
        c = new_cycle()
        with Patched(scan_pubmed=pubmed_with(good_pubmed)):
            c.scan()
        keys = list(c.staged)
        self.assertEqual(keys[-1], "engine/scan-state.json"); self.assertLess(keys.index("data/review-queue/queue.json"), keys.index("engine/scan-state.json"))
        self.assertLess(keys.index("engine/known_ids.json"), keys.index("engine/scan-state.json"))


class DuplicatesStayPreventedAfterALongLookBack(unittest.TestCase):
    def test_a_90_day_gap_returns_old_and_new_records_and_each_is_queued_once(self):
        gap_state = {"pubmed": (TODAY - timedelta(days=90)).isoformat(), "ctgov": (TODAY - timedelta(days=90)).isoformat()}
        seen_before = [f"pubmed-{i}" for i in IDS[:80]]                           # evaluated / staged / held / archived / published long ago: only their ids remain
        queued = [{"id": f"pubmed-{IDS[i]}", "kind": "study", "title": f"Queued {i}", "source": "J", "date": "", "url": "u"} for i in range(80, 110)]
        c = new_cycle(gap_state, known=seen_before + [q["id"] for q in queued], queue_items=queued)
        with Patched(scan_pubmed=pubmed_with(good_pubmed)):
            q1 = c.scan(); c.commit()
        ids = [i["id"] for i in q1["items"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(c.status["newItems"], 230 - 110)                        # only the 120 records never seen before
        self.assertFalse(set(seen_before) & set(ids))                            # nothing already processed is queued again
        self.assertEqual(c.status["sources"][0]["lookbackDays"], 93)
        c2 = weekly_cycle.Cycle(c.root)
        with Patched(scan_pubmed=pubmed_with(good_pubmed)):
            q2 = c2.scan(); c2.commit()                                           # an immediate second scan over the same long window adds nothing
        self.assertEqual(c2.status["newItems"], 0); self.assertEqual(len(q2["items"]), len(ids))

    def test_the_same_story_from_two_sources_still_collapses_in_a_long_window(self):
        c = new_cycle({"pubmed": (TODAY - timedelta(days=120)).isoformat(), "ctgov": OLD})
        a = lambda: [{"id": "pubmed-1", "kind": "study", "title": "Same Title", "source": "J", "date": "", "url": "u"}]
        b = lambda: [{"id": "ctgov-NCT1-2026-10-01", "kind": "trial", "title": "Same   title!", "source": "S", "date": "", "url": "u"}]
        with Patched(scan_pubmed=a, scan_ctgov=b):
            q = c.scan()
        self.assertEqual(len(q["items"]), 1)


class AGapBeyondTheMaximumIsVisible(unittest.TestCase):
    def test_reported_in_the_run_the_digest_and_a_red_health_check(self):
        c = new_cycle({"pubmed": (TODAY - timedelta(days=260)).isoformat(), "ctgov": OLD})
        with Patched(scan_pubmed=pubmed_with(good_pubmed)):
            c.scan(); c.commit()
        gap = [e for e in c.status["errors"] if "coverage gap" in e]
        self.assertEqual(len(gap), 1); self.assertIn("260 days", gap[0]); self.assertEqual(c.status["sources"][0]["lookbackDays"], 180)
        self.assertEqual(clock(c), TODAY.isoformat())                              # the scan did complete over the 180 days it could cover; the earlier part is what is reported
        status = {"newItems": 0, "errors": c.status["errors"], "lastSuccess": "2026-11-15T06:00:00", "sources": [{"name": "PubMed", "error": None}], "evaluation": {"state": "disabled"}}
        d = wd.build_digest(status, {"items": []}, {"items": []}, {"runs": []}, today=TODAY)
        self.assertTrue(any("coverage gap" in p for p in d["problems"])); self.assertNotEqual(d["state"], "green")
        self.assertIn("coverage gap", wd.render_html(d))
        h = Path(tempfile.mkdtemp(prefix="te-hc-")); (h / "engine").mkdir(); (h / "data").mkdir()
        shutil.copy(ENGINE / "check_evaluation_health.py", h / "engine")
        (h / "data/engine-status.json").write_text(json.dumps({"errors": c.status["errors"], "evaluation": {"state": "disabled", "disabledSince": TODAY.isoformat(), "awaitingEvaluation": 0}}), encoding="utf-8")
        p = subprocess.run([sys.executable, str(h / "engine/check_evaluation_health.py")], capture_output=True, text=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(p.returncode, 1); self.assertIn("coverage gap", p.stdout)
        shutil.rmtree(h, ignore_errors=True)

    def test_a_normal_run_is_not_flagged(self):
        c = new_cycle()
        with Patched(scan_pubmed=pubmed_with(good_pubmed)):
            c.scan()
        self.assertFalse(any("coverage gap" in e for e in c.status["errors"]))


if __name__ == "__main__":
    unittest.main()
