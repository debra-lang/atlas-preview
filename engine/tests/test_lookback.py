"""After a skipped or failed run the next run looks back to the time since each source last succeeded (up to 180 days), result lists are paged, and a gap that cannot be covered is reported. Offline."""
import json, sys, tempfile, unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import weekly_cycle, weekly_scan  # noqa: E402

TODAY = date(2026, 11, 15)


def cycle_with_state(state=None):
    root = Path(tempfile.mkdtemp(prefix="te-lb-"))
    (root / "data" / "review-queue").mkdir(parents=True); (root / "engine").mkdir()
    (root / "data/review-queue/queue.json").write_text(json.dumps({"items": []}), encoding="utf-8")
    (root / "engine/known_ids.json").write_text("[]", encoding="utf-8")
    if state is not None:
        (root / "engine/scan-state.json").write_text(json.dumps(state), encoding="utf-8")
    return weekly_cycle.Cycle(root)


def ago(n):
    return (TODAY - timedelta(days=n)).isoformat()


class Window(unittest.TestCase):
    def days(self, last, key="pubmed"):
        c = cycle_with_state()
        return c.lookback_days(key, {key: last} if last is not None else {}, "PubMed", today=TODAY)

    def test_normal_gaps_use_the_standard_window(self):
        for gap in (14, 15, 16, 17):
            self.assertEqual(self.days(ago(gap)), (20, None), gap)

    def test_a_skipped_run_lengthens_the_window_to_cover_the_whole_gap_plus_an_overlap(self):
        self.assertEqual(self.days(ago(28)), (31, None))                  # one skipped run
        self.assertEqual(self.days(ago(34)), (37, None))
        self.assertEqual(self.days(ago(62)), (65, None))                  # several skipped runs
        self.assertEqual(self.days(ago(177)), (180, None))

    def test_a_gap_beyond_the_maximum_is_reported_not_hidden(self):
        d, msg = self.days(ago(200))
        self.assertEqual(d, 180); self.assertIn("coverage gap", msg); self.assertIn("200 days", msg)

    def test_no_or_unusable_state_uses_the_standard_window(self):
        for bad in (None, "garbage", "2099-01-01", 5):
            self.assertEqual(self.days(bad), (20, None), bad)


class Scan(unittest.TestCase):
    def run_scan(self, state, fail=()):
        c = cycle_with_state(state)
        seen = {}
        orig = {n: getattr(weekly_scan, n) for n in ("scan_pubmed", "scan_ctgov", "scan_feeds", "scan_fda", "scan_news_intel", "scan_pages")}

        def mk(name):
            def f():
                seen[name] = weekly_scan.DAYS
                if name in fail:
                    raise RuntimeError("source down")
                return []
            return f
        for n in orig:
            setattr(weekly_scan, n, mk(n))
        real_date = weekly_cycle.date
        try:
            class D(real_date):
                @classmethod
                def today(cls):
                    return TODAY
            weekly_cycle.date = D
            c.scan(); c.commit()
        finally:
            weekly_cycle.date = real_date
            for n, f in orig.items():
                setattr(weekly_scan, n, f)
        return c, seen, json.loads((c.root / "engine/scan-state.json").read_text(encoding="utf-8"))

    def test_each_source_advances_its_own_clock_only_when_it_succeeds(self):
        c, seen, st = self.run_scan({"pubmed": ago(30), "ctgov": ago(30)}, fail=("scan_ctgov",))
        self.assertEqual(seen["scan_pubmed"], 33); self.assertEqual(seen["scan_ctgov"], 33)         # both looked back over the gap
        self.assertEqual(st["pubmed"], TODAY.isoformat()); self.assertEqual(st["ctgov"], ago(30))   # ctgov failed: its clock did not move, so the next run looks back further still
        self.assertTrue(any("ClinicalTrials.gov" in e and "failed" in e for e in c.status["errors"]))
        self.assertEqual(weekly_scan.DAYS, 20)                                                      # the global is restored

    def test_the_other_sources_keep_the_standard_window(self):
        c, seen, st = self.run_scan({"pubmed": ago(60), "ctgov": ago(60)})
        for n in ("scan_feeds", "scan_fda", "scan_news_intel", "scan_pages"):
            self.assertEqual(seen[n], 20, n)
        self.assertNotIn("feeds", st)

    def test_a_gap_over_the_maximum_appears_in_the_run_errors(self):
        c, seen, st = self.run_scan({"pubmed": ago(300), "ctgov": ago(14)})
        self.assertEqual(seen["scan_pubmed"], 180)
        self.assertTrue(any("coverage gap" in e for e in c.status["errors"]))

    def test_fixtures_do_not_touch_the_state(self):
        c = cycle_with_state({"pubmed": ago(300)})
        c.scan(fixtures=[("PubMed (title/abstract + MeSH)", lambda: [])]); c.commit()
        self.assertEqual(json.loads((c.root / "engine/scan-state.json").read_text(encoding="utf-8")), {"pubmed": ago(300)})


class Paging(unittest.TestCase):
    def setUp(self):
        self.orig = (weekly_scan.get_json, weekly_scan.time.sleep)
        weekly_scan.time.sleep = lambda s: None

    def tearDown(self):
        weekly_scan.get_json, weekly_scan.time.sleep = self.orig

    def test_pubmed_results_beyond_100_are_paged_not_cut(self):
        allids = [str(1000 + i) for i in range(250)]

        def fake(url):
            if "esearch" in url:
                start = int(url.split("retstart=")[1].split("&")[0])
                return {"esearchresult": {"count": "250", "idlist": allids[start:start + 100]}}
            ids = url.split("id=")[1].split("&")[0].split("%2C")
            return {"result": {i: {"title": "t" + i, "pubtype": []} for i in ids}}
        weekly_scan.get_json = fake
        self.assertEqual(len(weekly_scan.scan_pubmed()), 250)

    def test_pubmed_that_cannot_be_fully_paged_raises_instead_of_pretending(self):
        weekly_scan.get_json = lambda url: {"esearchresult": {"count": "9999", "idlist": ["1"]}} if "esearch" in url else {"result": {"uids": ["1"], "1": {"title": "t", "pubtype": []}}}
        old = weekly_scan.PAGE_CAP
        weekly_scan.PAGE_CAP = 2
        try:
            with self.assertRaises(RuntimeError):
                weekly_scan.scan_pubmed()
        finally:
            weekly_scan.PAGE_CAP = old

    def test_ctgov_follows_page_tokens_and_a_failed_pass_raises(self):
        pages = {None: ("p1", [{"protocolSection": {"identificationModule": {"nctId": f"NCT0000000{i}", "briefTitle": "t"}, "statusModule": {"lastUpdatePostDateStruct": {"date": "2026-10-01"}}}} for i in range(1, 4)]),
                 "p1": (None, [{"protocolSection": {"identificationModule": {"nctId": "NCT00000009", "briefTitle": "t"}, "statusModule": {"lastUpdatePostDateStruct": {"date": "2026-10-02"}}}}])}

        def fake(url):
            tok = url.split("pageToken=")[1].split("&")[0] if "pageToken=" in url else None
            nxt, studies = pages[tok]
            return {"studies": studies, **({"nextPageToken": nxt} if nxt else {})}
        weekly_scan.get_json = fake
        self.assertEqual(len(weekly_scan.scan_ctgov()), 4)                     # 3 + 1 from the second page; the second query pass returns the same ids
        calls = []

        def broken(url):
            calls.append(url)
            if "query.term" in url:
                raise OSError("down")
            return {"studies": []}
        weekly_scan.get_json = broken
        with self.assertRaises(RuntimeError):
            weekly_scan.scan_ctgov()


if __name__ == "__main__":
    unittest.main()
