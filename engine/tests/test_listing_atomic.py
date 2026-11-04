"""A record is never marked listed unless its listing is saved. A failure at any point during processing, writing or saving leaves records eligible for retry, reports a failure, and keeps holds and pauses effective. The REAL cycle runs on a sandbox.
Run:  python -m unittest discover -s engine/tests -v"""
import json, pathlib, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ENGINE, pubmed_item   # noqa: E402
from cycle_sandbox import FACTS, HISTORY, ITEM, KNOWN, LENIRE, LISTINGS, PAUSED, QUEUE, STATUS, TODAY, Sandbox, W, record   # noqa: E402

import listings, state_files, triage, weekly_cycle   # noqa: E402

NEW = [pubmed_item(n, f"Tinnitus study number {n}", source="J Audiol", triage=FACTS) for n in (990011, 990012, 990013)]
NEW_KEYS = {f"PMID {i['id'].split('-')[1]}" for i in NEW}
HELD_KEY, PAUSED_KEY = "PMID 990003", "PMID 990001"
EARLIER = {"key": "PMID 111", "listedOn": "2026-10-01", "title": "An earlier listing", "kind": "study", "date": "2026", "source": "J", "url": "u", "tier": 2, "articleTypes": [], "treatments": [], "highImpact": False, "verification": {}}


class Base(Sandbox):
    def setUp(self):
        super().setUp()
        W(self.root, LISTINGS, {"version": 1, "updated": "2026-10-01", "count": 1, "items": [EARLIER]})
        W(self.root, QUEUE, {"items": [ITEM, LENIRE]})
        W(self.root, KNOWN, [ITEM["id"], LENIRE["id"]])
        W(self.root, STATUS, {"lastSuccess": "BEFORE"})

    def scanner(self):
        self.scans += 1
        return [dict(x) for x in NEW] if self.scans == 1 else []

    def J(self, rel):
        return json.loads((self.root / rel).read_text(encoding="utf-8"))

    def listed_keys(self):
        return {e["key"] for e in self.J(LISTINGS)["items"]}

    def marks(self):
        return {i["id"]: i.get("listed", {}).get("outcome") for i in self.J(QUEUE)["items"] if isinstance(i.get("listed"), dict)}

    def health(self):
        d = Path(tempfile.mkdtemp(prefix="te-la-"))
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (d / "engine").mkdir(); (d / "data").mkdir()
        shutil.copy(ENGINE / "check_evaluation_health.py", d / "engine")
        shutil.copy(self.root / STATUS, d / "data" / "engine-status.json")
        return subprocess.run([sys.executable, str(d / "engine/check_evaluation_health.py")], capture_output=True, text=True, encoding="utf-8", errors="replace").returncode

    def assertConsistent(self):
        """The rule itself: every record marked listed has its listing, and neither protected record is listed."""
        state_files.preflight(self.root, scan_files=True)
        keys = self.listed_keys()
        for i in self.J(QUEUE)["items"]:
            m = i.get("listed")
            if isinstance(m, dict) and m.get("outcome") == "listed":
                self.assertIn(m["key"], keys, i["id"])
        self.assertNotIn(HELD_KEY, keys)
        self.assertNotIn(PAUSED_KEY, keys)
        q = {i["id"] for i in self.J(QUEUE)["items"]}
        self.assertTrue({ITEM["id"], LENIRE["id"]} <= q)
        self.assertIn("PMID 111", keys)

    def assertRecoversAndListsEachOnce(self):
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-400:])
        self.assertConsistent()
        all_keys = [e["key"] for e in self.J(LISTINGS)["items"]]
        self.assertEqual(len(all_keys), len(set(all_keys)), "a record was listed twice")
        self.assertTrue(NEW_KEYS <= set(all_keys), "a record was not retried")
        self.assertNotEqual(self.J(STATUS)["lastSuccess"], "BEFORE")
        self.assertFalse(self.J(STATUS).get("listingsFailed"))
        self.assertEqual(self.health(), 0)


class SoundRun(Base):
    def test_a_sound_run_lists_marks_and_stays_green(self):
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-400:])
        self.assertConsistent()
        self.assertTrue(NEW_KEYS <= self.listed_keys())
        self.assertEqual(self.marks(), {i["id"]: "listed" for i in NEW}, "the marks must reach the saved queue, or every record is reprocessed on every run")
        self.assertFalse(self.J(STATUS).get("listingsFailed"))
        self.assertNotEqual(self.J(STATUS)["lastSuccess"], "BEFORE")
        self.assertEqual(self.health(), 0)

    def test_a_second_run_lists_nothing_again(self):
        self.run_main()
        before = self.J(LISTINGS)["items"]
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-300:])
        self.assertEqual(self.J(LISTINGS)["items"], before)
        self.assertEqual(self.J(STATUS)["listings"].get("listed", 0), 0)

    def test_pausing_a_record_listed_earlier_the_same_day_is_not_an_error(self):
        self.run_main()
        W(self.root, PAUSED, {"ids": [ITEM["id"], NEW[0]["id"]]})
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-300:])
        self.assertFalse(self.J(STATUS).get("listingsFailed"), "a same-day rerun after a pause must not go red")
        self.assertEqual(self.health(), 0)
        self.assertIn(f"PMID {NEW[0]['id'].split('-')[1]}", self.listed_keys())      # an existing listing stays, by policy

    def test_a_record_listed_earlier_and_held_later_is_not_an_error(self):
        listings.check_result([{"id": "a", "topicHold": "h", "listed": {"on": TODAY, "outcome": "listed", "key": "k"}}], {"items": [{"key": "k"}]}, {"count": 1, "items": [{"key": "k"}]}, already={"a"}, excluded=lambda it: True, before=[{"id": "a", "topicHold": "h", "listed": {"on": TODAY, "outcome": "listed", "key": "k"}}])


class DuringProcessing(Base):
    def failing(self, fault, undo=None):
        """A fault inside the step: the scan is saved, the run reports failure, nothing is marked, and the next run lists every record once."""
        fault()
        rc, out = self.run_main()
        if undo:
            undo()
        self.assertEqual(rc, 0, out[-400:])
        st = self.J(STATUS)
        self.assertTrue(st.get("listingsFailed"))
        self.assertTrue(any("listings step failed" in e for e in st["errors"]))
        self.assertEqual(st["lastSuccess"], "BEFORE", "a failed listing step must not claim success")
        self.assertEqual(self.health(), 1, "the run must end red")
        self.assertEqual(self.marks(), {}, "no record may keep a mark")
        self.assertEqual(self.listed_keys(), {"PMID 111"}, "the listings must be unchanged")
        self.assertTrue(all(i["id"] in {x["id"] for x in self.J(QUEUE)["items"]} for i in NEW), "scanned records must be kept")
        self.assertConsistent()
        self.assertRecoversAndListsEachOnce()

    def test_failure_on_the_first_middle_and_last_record(self):
        real = listings.verify
        for n in (1, 2, 3):
            with self.subTest(call=n):
                self.setUp()
                calls = [0]

                def verify(*a, **k):
                    calls[0] += 1
                    if calls[0] == n:
                        raise RuntimeError("an unexpected error on one record")
                    return real(*a, **k)

                def undo():
                    listings.verify = real
                self.failing(lambda: setattr(listings, "verify", verify), undo)
                listings.verify = real

    def test_failure_while_classifying(self):
        real = triage.classify
        self.failing(lambda: setattr(triage, "classify", lambda it: (_ for _ in ()).throw(RuntimeError("boom"))), lambda: setattr(triage, "classify", real))

    def test_failure_while_enriching(self):
        real = triage.enrich
        self.failing(lambda: setattr(triage, "enrich", lambda pm: (_ for _ in ()).throw(RuntimeError("boom"))), lambda: setattr(triage, "enrich", real))

    def test_failure_while_building_an_entry(self):
        real, calls = listings.entry_for, [0]

        def entry_for(*a, **k):
            calls[0] += 1
            if calls[0] == 2:
                raise KeyError("listedOn")
            return real(*a, **k)
        self.failing(lambda: setattr(listings, "entry_for", entry_for), lambda: setattr(listings, "entry_for", real))

    def wrap_process(self, change):
        real = listings.process

        def process(items, existing, **k):
            new, counts = real(items, existing, **k)
            change(items, new)
            return new, counts
        self.failing(lambda: setattr(listings, "process", process), lambda: setattr(listings, "process", real))

    def test_a_result_that_loses_a_new_listing_is_rejected(self):
        def change(items, new):
            new["items"] = [e for e in new["items"] if e["key"] != "PMID 990012"]
            new["count"] = len(new["items"])
        self.wrap_process(change)

    def test_a_result_that_loses_an_earlier_listing_is_rejected(self):
        def change(items, new):
            new["items"] = [e for e in new["items"] if e["key"] != "PMID 111"]
            new["count"] = len(new["items"])
        self.wrap_process(change)

    def test_a_result_with_a_repeated_key_is_rejected(self):
        def change(items, new):
            new["items"].append(dict(new["items"][0]))
            new["count"] = len(new["items"])
        self.wrap_process(change)

    def test_a_result_that_lists_a_held_record_is_rejected(self):
        def change(items, new):
            lenire = next(i for i in items if i["id"] == LENIRE["id"])
            lenire["listed"] = {"on": TODAY, "outcome": "listed", "key": HELD_KEY}
            new["items"].append({**EARLIER, "key": HELD_KEY, "listedOn": TODAY})
            new["count"] = len(new["items"])
        self.wrap_process(change)

    def test_a_result_that_lists_a_paused_record_is_rejected(self):
        def change(items, new):
            p = next(i for i in items if i["id"] == ITEM["id"])
            p["listed"] = {"on": TODAY, "outcome": "listed", "key": PAUSED_KEY}
            new["items"].append({**EARLIER, "key": PAUSED_KEY, "listedOn": TODAY})
            new["count"] = len(new["items"])
        self.wrap_process(change)

    def test_a_record_held_by_its_mark_alone_cannot_be_listed_by_this_run(self):
        with self.assertRaises(ValueError):
            listings.check_result([{"id": "a", "topicHold": "h", "listed": {"on": TODAY, "outcome": "listed", "key": "k"}}], {"items": []}, {"count": 1, "items": [{"key": "k"}]}, already=set(), excluded=lambda it: False, before=[{"id": "a", "topicHold": "h"}])

    def test_a_hold_found_in_the_record_survives_a_failed_step(self):
        """The evaluator's own check reads less of a record than the listing step does, so this mark must not be lost with the rest."""
        def fetch(item):
            text = record(item)
            return text + "\nLocation: Neuromod Devices clinic" if item["id"] == NEW[0]["id"] else text
        self.fetch = fetch
        real, calls = listings.verify, [0]

        def verify(*a, **k):
            calls[0] += 1
            if calls[0] == 2:
                raise RuntimeError("an unexpected error on a later record")
            return real(*a, **k)
        listings.verify = verify
        try:
            rc, out = self.run_main()
        finally:
            listings.verify = real
        self.assertEqual(rc, 0, out[-300:])
        self.assertTrue(self.J(STATUS).get("listingsFailed"))
        q = {i["id"]: i for i in self.J(QUEUE)["items"]}
        self.assertEqual(q[NEW[0]["id"]].get("topicHold"), "lenire-neuromod")
        self.assertEqual(self.marks(), {}, "only the hold mark is kept")

    def test_a_mark_kept_by_a_failed_step_is_on_disk_for_the_evaluator_and_the_cycle_to_read_back(self):
        """The evaluator reads the queue from disk, and the cycle reads it back after: a mark kept only in memory is lost there, and the record could reach the AI."""
        def fetch(item):
            text = record(item)
            return text + "\nLocation: Neuromod Devices clinic" if item["id"] == NEW[0]["id"] else text
        real_fetch, real_verify, calls = weekly_cycle.evaluate_queue.fetch_context, listings.verify, [0]

        def verify(*a, **k):
            calls[0] += 1
            if calls[0] == 2:
                raise RuntimeError("an unexpected error on a later record")
            return real_verify(*a, **k)
        weekly_cycle.evaluate_queue.fetch_context, listings.verify = fetch, verify
        self.addCleanup(setattr, triage, "fetch_xml", triage.fetch_xml)
        triage.fetch_xml = lambda ids: None     # no network from a test
        W(self.root, QUEUE, {"items": [ITEM, LENIRE, *NEW]})
        c = weekly_cycle.Cycle(self.root)
        try:
            c.phase1(c.load(QUEUE, None))
        finally:
            weekly_cycle.evaluate_queue.fetch_context, listings.verify = real_fetch, real_verify
        self.assertTrue(c.status.get("listingsFailed"))
        self.assertEqual({i["id"]: i for i in self.J(QUEUE)["items"]}[NEW[0]["id"]].get("topicHold"), "lenire-neuromod")
        self.assertEqual(self.marks(), {}, "only the hold mark is kept")

    def test_a_result_that_drops_a_hold_mark_is_rejected_and_the_mark_stays(self):
        W(self.root, QUEUE, {"items": [ITEM, LENIRE, {**NEW[0], "topicHold": "lenire-neuromod"}]})
        W(self.root, KNOWN, [ITEM["id"], LENIRE["id"], NEW[0]["id"]])
        real = listings.process

        def process(items, existing, **k):
            new, counts = real(items, existing, **k)
            next(i for i in items if i["id"] == NEW[0]["id"]).pop("topicHold")
            return new, counts
        listings.process = process
        self.addCleanup(setattr, listings, "process", real)
        rc, out = self.run_main()
        listings.process = real
        self.assertEqual(rc, 0, out[-300:])
        self.assertTrue(self.J(STATUS).get("listingsFailed"))
        self.assertEqual({i["id"]: i for i in self.J(QUEUE)["items"]}[NEW[0]["id"]].get("topicHold"), "lenire-neuromod")

    def test_emptied_listings_are_still_caught_after_a_failed_step(self):
        real = listings.verify
        listings.verify = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            self.run_main()
        finally:
            listings.verify = real
        self.assertEqual(self.J(STATUS)["listings"]["total"], 1)
        W(self.root, LISTINGS, {"version": 1, "count": 0, "items": []})
        self.scans = 0
        self.assertStopsWholeAndNamesIt(LISTINGS, "emptied after a failed step")

    def test_a_failed_step_does_not_hide_the_ai_off_too_long_warning(self):
        d = Path(tempfile.mkdtemp(prefix="te-la-"))
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (d / "engine").mkdir(); (d / "data").mkdir()
        shutil.copy(ENGINE / "check_evaluation_health.py", d / "engine")
        (d / "data/engine-status.json").write_text(json.dumps({"listingsFailed": True, "listings": {"total": 1, "failed": True}, "evaluation": {"state": "disabled", "disabledSince": "2026-01-01"}}), encoding="utf-8")
        out = subprocess.run([sys.executable, str(d / "engine/check_evaluation_health.py")], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        self.assertIn("switched off for", out)

    def test_a_copy_means_earlier_marks_on_the_same_items_are_kept(self):
        W(self.root, QUEUE, {"items": [ITEM, LENIRE, {**pubmed_item(111, "An earlier listed record", source="J", triage=FACTS), "listed": {"on": "2026-10-01", "outcome": "listed", "key": "PMID 111"}}]})
        W(self.root, KNOWN, [ITEM["id"], LENIRE["id"], "pubmed-111"])
        real = listings.verify
        listings.verify = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            rc, out = self.run_main()
        finally:
            listings.verify = real
        self.assertEqual(rc, 0)
        self.assertEqual(self.marks(), {"pubmed-111": "listed"})


class DuringWriting(Base):
    def fail_replace(self, name, nth=1):
        """The nth atomic replace of a file with this name raises, as a full disk or a lost volume would."""
        real, seen = pathlib.Path.replace, [0]

        def replace(p, target):
            if Path(target).name == name:
                seen[0] += 1
                if seen[0] == nth:
                    raise OSError("simulated write failure")
            return real(p, target)
        pathlib.Path.replace = replace
        self.addCleanup(setattr, pathlib.Path, "replace", real)
        return lambda: setattr(pathlib.Path, "replace", real)

    def assertWriteFailureIsSafe(self, name, nth=1):
        restore = self.fail_replace(name, nth)
        rc, out = self.run_main()
        restore()
        self.assertEqual(rc, 1, f"{name} write {nth}: the step must fail. {out[-300:]}")   # on Actions a failed step commits nothing; here the disk shows the worst case of a run by hand
        self.assertConsistent()
        self.scans = 0
        self.assertRecoversAndListsEachOnce()

    def test_writing_the_listings_fails(self):
        self.assertWriteFailureIsSafe("listings.json")

    def test_writing_the_queue_fails_after_the_listings_were_written(self):
        self.assertWriteFailureIsSafe("queue.json", 2)     # write 1 is the scan's own save; write 2 follows the listings

    def test_the_final_write_of_the_queue_fails(self):
        self.assertWriteFailureIsSafe("queue.json", 3)

    def test_writing_the_update_history_fails(self):
        self.assertWriteFailureIsSafe("update-history.json")

    def test_writing_the_report_index_fails(self):
        self.assertWriteFailureIsSafe("index.json")

    def test_writing_the_published_register_fails(self):
        self.assertWriteFailureIsSafe("published_ids.json")

    def test_the_listings_are_saved_before_the_marks(self):
        order, real = [], pathlib.Path.replace

        def replace(p, target):
            order.append(Path(target).name)
            return real(p, target)
        pathlib.Path.replace = replace
        try:
            rc, out = self.run_main()
        finally:
            pathlib.Path.replace = real
        self.assertEqual(rc, 0, out[-300:])
        first_listing = order.index("listings.json")
        self.assertIn("queue.json", order[first_listing:], "the queue holding the marks must be written after the listings")
        self.assertEqual(order[:first_listing].count("queue.json"), 1, "only the scan's own save, which has no marks, comes before the listings")


class AcrossFiles(Base):
    def test_a_mark_without_its_listing_stops_the_next_run_whatever_caused_it(self):
        W(self.root, QUEUE, {"items": [ITEM, LENIRE, {**pubmed_item(990099, "A record", source="J", triage=FACTS), "listed": {"on": "2026-11-01", "outcome": "listed", "key": "PMID 990099"}}]})
        W(self.root, KNOWN, [ITEM["id"], LENIRE["id"], "pubmed-990099"])
        self.assertStopsWholeAndNamesIt(QUEUE, "mark without a listing")

    def test_clearing_the_mark_is_the_way_to_list_it_again(self):
        W(self.root, QUEUE, {"items": [ITEM, LENIRE, pubmed_item(990099, "A record to list again", source="J", triage=FACTS)]})
        W(self.root, KNOWN, [ITEM["id"], LENIRE["id"], "pubmed-990099"])
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-300:])
        self.assertIn("PMID 990099", self.listed_keys())

    def test_other_outcomes_need_no_listing(self):
        for outcome in ("screened-out", "notice", "superseded", "unverifiable", "failed-verification"):
            W(self.root, QUEUE, {"items": [ITEM, LENIRE, {**pubmed_item(990098, "Other", source="J"), "listed": {"on": "2026-11-01", "outcome": outcome}}]})
            W(self.root, KNOWN, [ITEM["id"], LENIRE["id"], "pubmed-990098"])
            state_files.preflight(self.root)

    def test_a_listing_entry_missing_listedOn_stops_before_anything_is_marked(self):
        d = self.J(LISTINGS)
        d["items"][0].pop("listedOn")
        W(self.root, LISTINGS, d)
        self.assertStopsWholeAndNamesIt(LISTINGS, "no listedOn")

    def test_a_damaged_rules_file_inside_the_step_is_not_swallowed(self):
        real = triage.classify
        triage.classify = lambda it: (_ for _ in ()).throw(state_files.DamagedFile("triage_rules.json: damaged"))
        try:
            rc, out = self.run_main()
        finally:
            triage.classify = real
        self.assertEqual(rc, 1)
        self.assertIn("CYCLE STOPPED", out)

    def test_the_history_row_says_the_step_failed_and_a_good_row_says_nothing(self):
        real = listings.verify
        listings.verify = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            self.run_main()
        finally:
            listings.verify = real
        self.assertEqual(self.J(HISTORY)["entries"][0].get("listingStep"), "failed")
        self.scans = 0
        self.run_main()
        self.assertNotIn("listingStep", self.J(HISTORY)["entries"][0])


if __name__ == "__main__":
    unittest.main()
