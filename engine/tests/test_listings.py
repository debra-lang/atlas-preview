"""Offline tests for Phase 1: automatic research listings (engine/listings.py), the cycle wiring, the update history, and the integrity-notice wording.
No network, no API key. Run:  python -m unittest discover -s engine/tests -v"""
import copy, json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402,F401
import listings, registry_record  # noqa: E402
from common import run_scenario, pubmed_item, ctgov_item, news_item  # noqa: E402

TODAY = "2026-11-01"
FACTS_IN = {"tinAbs": 5, "tinMesh": True, "tracked": [], "safety": [], "safetyWeak": [], "animalOnly": False, "hasAbstract": True}
FACTS_PASSING = {"tinAbs": 1, "tinMesh": False, "tracked": [], "safety": [], "safetyWeak": [], "animalOnly": False, "hasAbstract": True}


def pm(n, title="Cognitive behavioural therapy for tinnitus: a randomised trial", facts=FACTS_IN, **kw):
    it = pubmed_item(n, title, source="Journal of Tinnitus Research", date="2026 Oct 12", **kw)
    if facts is not None:
        it["triage"] = dict(facts)
    return it


def pubmed_text(it, extra=""):
    raw = f"1. J Tinnitus Res. 2026 Oct;12(3):1-9.\n\n{it['title']}\n\nAbstract text here.{extra}\n\nPMID: {it['id'].split('-')[1]}\n"
    return registry_record.finish_pubmed_record(raw, it["id"].split("-")[1])


class Env:
    """fetch_context / record_meta doubles: records[id] = (text, meta) or None (unavailable)."""
    def __init__(self, records):
        self.records, self.meta, self.fetched = records, {}, []

    def fetch(self, it):
        self.fetched.append(it["id"])
        rec = self.records.get(it["id"])
        text, meta = rec if rec else registry_record.unavailable_record("could not fetch")
        self.meta[it["id"]] = meta
        return text

    def record_meta(self, iid):
        return self.meta.pop(iid, None)


def run(items, records, existing=None, excluded=lambda it: False, enrich=None):
    env = Env(records)
    out, counts = listings.process(items, existing or {"items": []}, today=TODAY, fetch_context=env.fetch, record_meta=env.record_meta, excluded=excluded, enrich=enrich)
    return out, counts, env


class Settings(unittest.TestCase):
    def test_only_the_json_value_true_turns_a_switch_on(self):
        self.assertEqual(listings.load_settings({"listings": True, "updateHistory": True}), {"listings": True, "updateHistory": True})
        for bad in (None, {}, [], "true", {"listings": "true"}, {"listings": 1}, {"listings": "yes"}, {"updateHistory": 1}):
            self.assertEqual(listings.load_settings(bad), {"listings": False, "updateHistory": False}, bad)


class Verify(unittest.TestCase):
    def test_a_matching_record_passes(self):
        it = pm(1); text, meta = pubmed_text(it)
        self.assertTrue(listings.verify(it, text, meta)["ok"])

    def test_each_check_can_fail_on_its_own(self):
        it = pm(1); text, meta = pubmed_text(it)
        other = pm(2, "A completely different title about hearing aids and noise exposure in workers")
        self.assertFalse(listings.verify(other, text, meta)["titleMatchesRecord"])                                   # wrong title
        wrong_id = pm(3); self.assertFalse(listings.verify(wrong_id, text, meta)["identifierMatchesRecord"])          # record is for PMID 1
        t2, m2 = registry_record.unavailable_record("down")
        self.assertFalse(listings.verify(it, t2, m2)["recordFetched"])
        for pt in ("Retracted Publication", "Retraction of Publication", "Published Erratum", "Expression of Concern"):
            self.assertFalse(listings.verify(it, text, {**meta, "pubtypes": ["Journal Article", pt]})["notANotice"], pt)
        self.assertTrue(listings.verify(it, text, {**meta, "pubtypes": ["Journal Article", "Randomized Controlled Trial"]})["ok"])

    def test_title_match_ignores_case_punctuation_and_line_wraps(self):
        it = pm(1, "Tinnitus: a 'sound' therapy trial (phase 2) of notched music")
        raw = "1. J. 2026.\n\nTINNITUS - A SOUND THERAPY\n   TRIAL (PHASE 2) OF NOTCHED MUSIC\n\nPMID: 1\n"
        text, meta = registry_record.finish_pubmed_record(raw, "1")
        self.assertTrue(listings.verify(it, text, meta)["titleMatchesRecord"])


class Process(unittest.TestCase):
    def test_a_verified_pubmed_item_is_listed_with_source_facts_only(self):
        it = pm(11, "Rhythmic bimodal Lenire stimulation for tinnitus")
        text, meta = pubmed_text(it); meta["pubtypes"] = ["Journal Article", "Randomized Controlled Trial"]
        out, counts, _ = run([it], {it["id"]: (text, meta)})
        self.assertEqual(counts, {"listed": 1})
        e = out["items"][0]
        self.assertEqual((e["key"], e["kind"], e["title"], e["source"], e["url"], e["listedOn"]), ("PMID 11", "study", it["title"], "Journal of Tinnitus Research", it["url"], TODAY))
        self.assertEqual((e["articleTypes"], e["highImpact"], e["treatments"]), (["Journal Article", "Randomized Controlled Trial"], True, ["lenire"]))
        self.assertEqual(e["verification"], {"identifierMatchesRecord": True, "titleMatchesRecord": True, "notANotice": True, "checkedOn": TODAY})
        self.assertEqual(it["listed"], {"on": TODAY, "outcome": "listed", "key": "PMID 11"})
        # nothing but bibliographic facts: no summary, no interpretation, no abstract text
        self.assertEqual(set(e), {"key", "kind", "title", "source", "date", "url", "tier", "articleTypes", "treatments", "highImpact", "listedOn", "verification"})
        self.assertNotIn("Abstract text here", json.dumps(out))

    def test_a_trial_record_is_listed_once_with_the_newest_status(self):
        old = ctgov_item("NCT09999991", "2026-10-13", "A tinnitus device registry record", summary="Trial update — status: NOT_YET_RECRUITING.")
        new = ctgov_item("NCT09999991", "2026-10-20", "A tinnitus device registry record", summary="Trial update — status: RECRUITING.")
        rec = {new["id"]: (f"SOURCE: x\nRECORD COMPLETENESS: COMPLETE - nothing was left out\nCRITICAL SECTIONS MISSING: no\n---\nTitle: {new['title']}\nNCT ID: NCT09999991\n", {"completeness": "COMPLETE"})}
        out, counts, env = run([old, new], rec)
        self.assertEqual(counts, {"superseded": 1, "listed": 1})
        self.assertEqual(env.fetched, [new["id"]])                                          # the older entry is never fetched
        e = out["items"][0]
        self.assertEqual((e["key"], e["status"], e["articleTypes"]), ("NCT09999991", "RECRUITING", ["Registry record"]))
        self.assertEqual(old["listed"]["outcome"], "superseded")
        # a later update refreshes the same listing, keeps the first listing date, and is counted as an update, not a new listing
        later = ctgov_item("NCT09999991", "2026-11-05", "A tinnitus device registry record", summary="Trial update — status: COMPLETED.")
        out2, counts2, _ = listings.process([later], out, today="2026-11-20", fetch_context=Env({later["id"]: rec[new["id"]]}).fetch, record_meta=lambda i: {"completeness": "COMPLETE"})[0:2] + (None,)
        self.assertEqual((out2["count"], out2["items"][0]["status"], out2["items"][0]["listedOn"], counts2), (1, "COMPLETED", TODAY, {"updated": 1}))

    def test_what_must_not_be_listed(self):
        notice = pm(21, "Erratum: tinnitus trial"); notice["pubtypes"] = ["Published Erratum"]
        retracted = pm(22); rt, rm = pubmed_text(retracted); rm["pubtypes"] = ["Journal Article", "Retracted Publication"]
        incidental = pm(23, "Epidural blood patch for a cerebrospinal fluid leak", facts=FACTS_PASSING)
        news = news_item("x", "Lenire joins guidelines")
        held = pm(24); ht, hm = pubmed_text(held)
        wrong = pm(25); wt, wm = pubmed_text(pm(25, "A different paper entirely about cochlear implants in children"))
        items = [notice, retracted, incidental, news, held, wrong]
        out, counts, env = run(items, {retracted["id"]: (rt, rm), held["id"]: (ht, hm), wrong["id"]: (wt, wm)}, excluded=lambda it: it["id"] == held["id"])
        self.assertEqual(out["items"], [])
        self.assertEqual(counts, {"notice": 2, "screenedOut": 1, "ownerHeld": 1, "failedVerification": 1})
        self.assertEqual(notice["listed"]["outcome"], "notice"); self.assertEqual(retracted["listed"]["outcome"], "notice")
        self.assertEqual(incidental["listed"]["outcome"], "screened-out")
        self.assertNotIn("listed", news); self.assertNotIn("listed", held)                   # never touched
        self.assertEqual(wrong["listed"]["outcome"], "failed-verification"); self.assertFalse(wrong["listed"]["checks"]["titleMatchesRecord"])
        self.assertNotIn(news["id"], env.fetched); self.assertNotIn(held["id"], env.fetched); self.assertNotIn(incidental["id"], env.fetched)   # no fetch for what is never listed

    def test_a_record_for_a_different_identifier_is_never_listed_even_when_the_title_matches(self):
        it = pm(61, "Tinnitus counselling in primary care")
        other = pm(62, "Tinnitus counselling in primary care"); text, meta = pubmed_text(other)          # a record with the same title but PMID 62
        out, counts, _ = run([it], {it["id"]: (text, meta)})
        self.assertEqual((counts, out["items"]), ({"failedVerification": 1}, []))
        self.assertFalse(it["listed"]["checks"]["identifierMatchesRecord"]); self.assertTrue(it["listed"]["checks"]["titleMatchesRecord"])

    def test_company_news_is_never_listed_even_if_it_were_labelled_a_study(self):
        it = pm(63); it["intelligenceOnly"] = True; text, meta = pubmed_text(it)
        out, counts, env = run([it], {it["id"]: (text, meta)})
        self.assertEqual((counts, out["items"], env.fetched), ({}, [], []))
        self.assertNotIn("listed", it)

    def test_an_unavailable_record_is_retried_then_counted_as_unverifiable_and_kept(self):
        it = pm(31)
        for cycle, expect in ((1, {"deferred": 1}), (2, {"deferred": 1}), (3, {"unverifiable": 1})):
            out, counts, _ = run([it], {})
            self.assertEqual(counts, expect, cycle)
            self.assertEqual(out["items"], [])
        self.assertEqual(it["listed"]["outcome"], "unverifiable")
        out, counts, env = run([it], {})                                                      # an outcome is final: not fetched again
        self.assertEqual((counts, env.fetched), ({}, []))

    def test_missing_relevance_facts_defer_instead_of_listing_blindly(self):
        it = pm(32, facts=None); text, meta = pubmed_text(it)
        out, counts, _ = run([it], {it["id"]: (text, meta)})
        self.assertEqual((counts, out["items"]), ({"deferred": 1}, []))
        for _ in range(2):
            out, counts, _ = run([it], {it["id"]: (text, meta)})
        self.assertEqual(counts, {"unverifiable": 1})

    def test_enrich_is_called_for_pubmed_items_that_lack_facts(self):
        it = pm(33, facts=None); text, meta = pubmed_text(it)
        def enrich(items):
            for i in items:
                i["triage"] = dict(FACTS_IN)
        out, counts, _ = run([it], {it["id"]: (text, meta)}, enrich=enrich)
        self.assertEqual(counts, {"listed": 1})

    def test_a_first_run_over_a_backlog_is_capped_and_nothing_is_dropped(self):
        n = listings.MAX_NEW_PER_RUN + 5
        items = [pm(1000 + i, f"Tinnitus study number {i} of the backlog") for i in range(n)]
        recs = {it["id"]: pubmed_text(it) for it in items}
        out, counts, _ = run(items, recs)
        self.assertEqual((counts["listed"], counts["waiting"]), (listings.MAX_NEW_PER_RUN, 5))
        self.assertEqual(sum(1 for it in items if not it.get("listed")), 5)                  # the rest are simply picked up next cycle
        out2, counts2, _ = run(items, recs, existing=out)
        self.assertEqual((counts2["listed"], out2["count"]), (5, n))

    def test_listings_are_newest_first_and_the_function_is_idempotent(self):
        a, b = pm(41, "Tinnitus study A"), pm(42, "Tinnitus study B")
        out, _, _ = run([a], {a["id"]: pubmed_text(a)})
        env = Env({b["id"]: pubmed_text(b)})
        out2, c2 = listings.process([b], out, today="2026-11-15", fetch_context=env.fetch, record_meta=env.record_meta)
        self.assertEqual([e["key"] for e in out2["items"]], ["PMID 42", "PMID 41"])
        out3, c3 = listings.process([b, a], out2, today="2026-11-16", fetch_context=env.fetch, record_meta=env.record_meta)
        self.assertEqual((c3, out3["items"]), ({}, out2["items"]))


class Tags(unittest.TestCase):
    def test_tags_come_from_the_title_and_exclude_aliases_that_are_too_broad(self):
        self.assertEqual(listings.tags_for("Rhythmic bimodal Lenire stimulation for tinnitus"), ["lenire"])        # "bimodal" alone is not the Shore device
        self.assertEqual(listings.tags_for("The Shore somatosensory stimulation device"), ["shore-bimodal"])
        self.assertEqual(listings.tags_for("The history of tinnitus: from ancient interpretations to contemporary neuroscience and neuromodulation"), [])    # not Neuromod
        self.assertEqual(listings.tags_for("Trigeminal neuralgia and tinnitus"), [])
        self.assertEqual(listings.tags_for("Neuromod Devices announces a new Lenire study"), ["lenire"])
        self.assertEqual(listings.tags_for("Tongue stimulation for tinnitus"), ["lenire"])
        self.assertEqual(listings.tags_for("Repetitive transcranial magnetic stimulation for tinnitus"), ["rtms"])
        for generic in ("A drug interaction in cervical spine surgery", "Pulsatile tinnitus and sinus stenting", "Internet-based survey of insomnia", "Stem cell regeneration in the cochlea"):
            self.assertEqual(listings.tags_for(generic), [], generic)
        self.assertEqual(listings.tags_for("Cognitive behavioural therapy and acupuncture"), ["acupuncture", "cbt"])
        self.assertEqual(listings.tags_for(""), [])

    def test_abstract_only_mentions_do_not_tag(self):
        it = pm(51, "Hearing outcomes after surgery", facts={**FACTS_IN, "tracked": ["lenire", "rtms"]}); text, meta = pubmed_text(it)
        out, counts, _ = run([it], {it["id"]: (text, meta)})
        self.assertEqual(out["items"][0]["treatments"], [])


class Containment(unittest.TestCase):
    def test_a_failure_inside_the_listing_step_never_stops_the_cycle_or_touches_the_queue(self):
        import tempfile, shutil, weekly_cycle
        root = Path(tempfile.mkdtemp(prefix="te-cyc-"))
        try:
            (root / "engine").mkdir(); (root / "data").mkdir()
            (root / "engine" / "automation_settings.json").write_text(json.dumps({"listings": True}), encoding="utf-8")
            c = weekly_cycle.Cycle(root)
            queue = {"items": [pm(70)]}
            before = json.dumps(queue)
            real = listings.process
            listings.process = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
            try:
                c.phase1(queue)
            finally:
                listings.process = real
            self.assertEqual(json.dumps(queue), before)
            self.assertTrue(any("listings step failed" in e for e in c.status["errors"]))
            self.assertIsNone(c.listing_counts)
            self.assertNotIn(listings.LISTINGS_REL, c.staged)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class History(unittest.TestCase):
    def test_history_entry_and_idempotent_same_day_replacement(self):
        status = {"examined": 65, "newItems": 12, "retractionFindings": 0, "trialStatusUpdates": 2, "evaluation": {"state": "disabled"}}
        e = listings.history_entry("2026-11-01", status, {"listed": 7, "screenedOut": 3, "deferred": 1, "waiting": 1, "failedVerification": 0}, 70, 0.0)
        self.assertEqual((e["scanned"], e["newItems"], e["listed"], e["screenedOut"], e["waitingForVerification"], e["listingsTotal"], e["aiEvaluation"], e["estimatedCostUSD"]),
                         (65, 12, 7, 3, 2, 70, "disabled", 0.0))
        h = listings.add_history({"entries": []}, e)
        h = listings.add_history(h, {**e, "listed": 9})                                      # same day rerun replaces, never duplicates
        h = listings.add_history(h, {**e, "date": "2026-11-15"})
        self.assertEqual([r["date"] for r in h["entries"]], ["2026-11-15", "2026-11-01"])
        self.assertEqual(h["entries"][1]["listed"], 9)
        big = {"entries": [{"date": f"d{i}"} for i in range(listings.MAX_HISTORY + 20)]}
        self.assertEqual(len(listings.add_history(big, e)["entries"]), listings.MAX_HISTORY)


class Cycle(unittest.TestCase):
    ON = {"enabled": False, "mode": "staged", "limitPerRun": 10}
    A, B = pubmed_item(910001, "Tinnitus sound therapy trial A", source="J Audiol"), pubmed_item(910002, "Tinnitus counselling study B", source="J Audiol")
    FACTS = {"tinAbs": 4, "tinMesh": True, "tracked": [], "safety": [], "safetyWeak": [], "animalOnly": False, "hasAbstract": True}

    def queue(self):
        return [{**self.A, "triage": dict(self.FACTS)}, {**self.B, "triage": dict(self.FACTS)}]

    def test_everything_is_off_by_default(self):
        run_ = run_scenario({"queue": self.queue(), "settings": self.ON, "runs": [{}]})["runs"][0]
        self.assertIsNone(run_["listings"]); self.assertIsNone(run_["history"])
        self.assertNotIn("listings", run_["status"])

    def test_with_the_switches_on_the_cycle_lists_verifies_and_records_history(self):
        run_ = run_scenario({"queue": self.queue(), "settings": self.ON, "automation": {"listings": True, "updateHistory": True}, "runs": [{}]})["runs"][0]
        l = run_["listings"]
        self.assertEqual(l["count"], 2)
        self.assertEqual({e["key"] for e in l["items"]}, {"PMID 910001", "PMID 910002"})
        h = run_["history"]["entries"][0]
        self.assertEqual((h["listed"], h["aiEvaluation"], h["aiAttempted"], h["listingsTotal"]), (2, "disabled", 0, 2))
        self.assertEqual(run_["status"]["listings"]["listed"], 2)
        self.assertEqual(run_["totalApiCalls"], 0)                                           # no model is involved
        self.assertTrue(run_["ratingsUnchanged"] and run_["studiesUnchanged"])
        self.assertEqual(run_["leaks"], [])
        # the report says what is true while evaluation is off and listings are on
        item = run_["reportItems"][0]
        self.assertIn("2 new item(s) listed", item["title"]); self.assertIn("No AI has read them", item["why"])
        self.assertNotIn("have not been evaluated", item["title"])

    def test_a_second_cycle_lists_nothing_twice_and_a_paused_item_stays_out(self):
        a = run_scenario({"queue": self.queue(), "settings": self.ON, "automation": {"listings": True, "updateHistory": True}, "paused": ["pubmed-910002"], "runs": [{}, {}]})["runs"]
        self.assertEqual({e["key"] for e in a[0]["listings"]["items"]}, {"PMID 910001"})
        self.assertEqual(a[1]["listings"]["count"], 1)
        self.assertEqual(len(a[1]["history"]["entries"]), 1)                                  # the same-day rerun replaced its entry

    def test_listings_alone_do_not_write_a_history_and_history_alone_does_not_list(self):
        r1 = run_scenario({"queue": self.queue(), "settings": self.ON, "automation": {"listings": True}, "runs": [{}]})["runs"][0]
        self.assertIsNotNone(r1["listings"]); self.assertIsNone(r1["history"])
        r2 = run_scenario({"queue": self.queue(), "settings": self.ON, "automation": {"updateHistory": True}, "runs": [{}]})["runs"][0]
        self.assertIsNone(r2["listings"]); self.assertEqual(r2["history"]["entries"][0]["listed"], 0)


class IntegrityNoticeWording(unittest.TestCase):
    def test_the_notice_does_not_claim_a_review_nobody_performs(self):
        src = (Path(__file__).resolve().parent.parent / "weekly_cycle.py").read_text(encoding="utf-8")
        self.assertNotIn("The evidence impact is under review", src)
        self.assertIn("No rating has been changed because of this notice", src)
        self.assertIn("handled automatically: a factual notice is shown on the study", src)


if __name__ == "__main__":
    unittest.main()
