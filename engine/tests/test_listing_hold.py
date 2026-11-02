"""An owner topic hold (Lenire/Neuromod) must keep an item out of the public listings when ANY part of its complete source record names the topic, whatever the feed and
whatever the AI settings; unrelated records must not be caught. The REAL weekly cycle runs in a temp sandbox with the AI and all network fetches stubbed (run_scenario.py).
Run:  python -m unittest discover -s engine/tests -v"""
import json, sys, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import evaluate_queue, listings, registry_record, topic_holds  # noqa: E402

FACTS = {"tinAbs": 4, "tinMesh": True, "tracked": [], "safety": [], "safetyWeak": [], "animalOnly": False, "hasAbstract": True}
AUTO = {"listings": True, "updateHistory": True}
SETTINGS = {"AI off (production)": {"enabled": False, "mode": "staged", "limitPerRun": 10},
            "AI on, staged": {"enabled": True, "mode": "staged", "limitPerRun": 100},
            "AI on, publish": {"enabled": True, "mode": "publish", "limitPerRun": 100}}


def pm(n, title, extra=""):
    it = pubmed_item(n, title, source="J Audiol", date="2026 Oct 12"); it["triage"] = dict(FACTS)
    raw = f"1. J Tinnitus Res. 2026 Oct;12(3):1-9.\n\n{title}\n\nAbstract: tinnitus outcomes were measured.{extra}\n\nPMID: {n}\n"
    return it, registry_record.finish_pubmed_record(raw, str(n))[0]


def ct(nct, title, sponsor="University Hospital", interventions="Device: stimulator"):
    it = ctgov_item(nct, title=title, source=sponsor, date="2026-10-13")
    return it, "\n".join(["SOURCE: simulated", "RECORD COMPLETENESS: COMPLETE - nothing was left out", "CRITICAL SECTIONS MISSING: no", "REGISTRY FIELD hasResults: FALSE (no results posted)", "---",
                          f"NCT ID: {nct}", f"Title: {title}", "Conditions: Tinnitus", "Primary outcome: Tinnitus Handicap Inventory", f"Interventions: {interventions}", f"Sponsor: {sponsor}"])


HELD = [pm(990101, "Lenire bimodal stimulation for chronic tinnitus: a randomised trial"),
        pm(990102, "Long-term outcomes with the LENIRE® device in tinnitus"),
        pm(990103, "A tinnitus trial funded by Neuromod Devices"),
        pm(990104, "TENT-A3 follow-up in tinnitus"),
        pm(990105, "Bimodal neuromodulation for chronic tinnitus: a randomised trial", " Participants used the Lenire device."),        # abstract only
        pm(990106, "Sound and touch stimulation in chronic tinnitus", " Funding: a grant from Neuromod Devices Limited."),                 # funding statement only
        ct("NCT99000101", "Lenire for Tinnitus in Adults"),
        ct("NCT99000102", "Bimodal Stimulation for Tinnitus", sponsor="Neuromod Devices Limited"),
        ct("NCT99000103", "Bimodal Stimulation for Chronic Tinnitus", interventions="Device: Lenire"),                                     # registry interventions only
        ({"id": "feed-scirep-lenire-990202", "kind": "study", "title": "Lenire outcomes in tinnitus", "source": "Scientific Reports", "date": "2026-10-13", "url": "https://www.nature.com/articles/x", "summary": "RSS item."}, None),
        ({"id": "feed-nih-lenire-990201", "kind": "news", "title": "NIH note on the Lenire tinnitus device", "source": "NIH news releases", "date": "2026-10-13", "url": "https://www.nih.gov/news/x", "summary": "RSS item."}, None),
        ({"id": "fda-510k-lenire-990301", "kind": "regulatory", "title": "FDA 510(k) decision: Lenire (Neuromod Devices Ltd) — Substantially Equivalent", "source": "openFDA 510(k) database", "date": "2026-10-13", "url": "https://www.accessdata.fda.gov/x", "summary": "Authoritative FDA database record."}, None),
        (news_item("neuromod-lenire-routine-990401", "Company appoints a new officer", source="News wire watch: Neuromod / Lenire"), None),
        (news_item("tinnitus-trial-toplines-lenire-990402", "Lenire added to guidelines", source="News wire watch: Tinnitus trial toplines"), None),
        (news_item("auricle-shore-neuromod-990403", "Auricle and Neuromod compete in tinnitus", source="News wire watch: Auricle / Shore device"), None)]
FREE = [pm(990601, "Transcranial neuromodulation for chronic tinnitus: a randomised trial"),
        pm(990602, "Bimodal neuromodulation for chronic tinnitus: a controlled trial", " The neuromodulation device was worn daily; a tent-shaped response curve was seen."),   # 'neuromodulation', 'tent' are not the hold
        ct("NCT99000601", "Counselling for Chronic Tinnitus")]


def queue(rows):
    return [it for it, _ in rows]


def records(rows):
    return {it["id"]: rec for it, rec in rows if rec}


def key(it):
    return ("PMID " + it["id"].split("-")[1]) if it["id"].startswith("pubmed-") else (it["id"].split("-")[1] if it["id"].startswith("ctgov-") else None)


def listed(run):
    return {e["key"] for e in ((run.get("listings") or {}).get("items") or [])}


class EveryFeedAndSetting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = {n: run_scenario({"queue": queue(HELD + FREE), "records": records(HELD + FREE), "settings": s, "automation": AUTO, "paused": [], "runs": [{}, {}]})["runs"] for n, s in SETTINGS.items()}

    def test_a_held_item_is_never_listed_sent_staged_published_or_lost(self):
        for name, runs in self.runs.items():
            reports = json.dumps([r["reportItems"] for r in runs])
            for it, _ in HELD:
                with self.subTest(setting=name, item=it["id"]):
                    if key(it):
                        self.assertNotIn(key(it), listed(runs[1]))
                    self.assertFalse(any(it["id"] in r["apiCalls"] for r in runs))
                    self.assertFalse(any(it["id"] in r["staged"] for r in runs))
                    self.assertNotIn(it["title"], reports)
                    self.assertIn(it["id"], runs[1]["queue"])

    def test_unrelated_records_are_still_listed(self):
        for name, runs in self.runs.items():
            for it, _ in FREE:
                with self.subTest(setting=name, item=it["id"]):
                    self.assertIn(key(it), listed(runs[1]))

    def test_the_count_of_owner_held_items_is_reported(self):
        for name, runs in self.runs.items():
            with self.subTest(setting=name):
                self.assertEqual(runs[0]["status"]["listings"]["ownerHeld"], sum(1 for it, _ in HELD if key(it)))


class CompleteRecord(unittest.TestCase):
    def test_a_name_beyond_the_compact_text_still_holds_the_item(self):
        it, rec = pm(990701, "Sound and touch stimulation in chronic tinnitus")
        self.assertNotIn("lenire", rec.lower())
        run = run_scenario({"queue": [it], "records": {it["id"]: rec}, "fullRecords": {it["id"]: rec + " Declaration: consultant to the makers of Lenire."}, "settings": SETTINGS["AI off (production)"], "automation": AUTO, "paused": [], "runs": [{}]})["runs"][0]
        self.assertNotIn(key(it), listed(run))
        self.assertIn(it["id"], run["queue"])

    def test_fetch_context_keeps_the_complete_pubmed_record_beyond_the_cap(self):
        raw = "Title\n\n" + "x " * 11000 + "\nFunding: Neuromod Devices.\n\nPMID: 990702\n"
        with mock.patch.object(evaluate_queue, "_get", side_effect=[raw.encode("utf-8"), json.dumps({"result": {"990702": {"pubtype": []}}}).encode("utf-8")]):
            text = evaluate_queue.fetch_context({"id": "pubmed-990702", "title": "Title"})
        self.assertNotIn("Neuromod", text)                                                          # the compact text the AI sees is capped
        self.assertTrue(topic_holds.match_item({"id": "pubmed-990702", "title": "Title"}, extra_text=evaluate_queue.RECORD_FULL.pop("pubmed-990702")))

    def test_fetch_context_keeps_every_registry_field(self):
        study = {"protocolSection": {"identificationModule": {"nctId": "NCT99000702", "briefTitle": "Bimodal Stimulation"}, "contactsLocationsModule": {"locations": [{"facility": "Neuromod Devices Test Centre", "city": "Dublin"}]}}}
        with mock.patch.object(evaluate_queue, "_get", return_value=json.dumps(study).encode("utf-8")):
            text = evaluate_queue.fetch_context({"id": "ctgov-NCT99000702-2026-10-13", "title": "Bimodal Stimulation"})
        self.assertNotIn("Neuromod", text)                                                          # site addresses are left out of the compact text by design
        self.assertTrue(topic_holds.match_item({"id": "x", "title": "Bimodal Stimulation"}, extra_text=evaluate_queue.RECORD_FULL.pop("ctgov-NCT99000702-2026-10-13")))


class NothingLost(unittest.TestCase):
    def test_a_held_record_is_listed_once_the_hold_is_lifted(self):
        rows = [pm(990801, "Bimodal stimulation in chronic tinnitus", " Participants used the Lenire device.")]
        run = run_scenario({"queue": queue(rows), "records": records(rows), "settings": SETTINGS["AI off (production)"], "automation": AUTO, "paused": [], "topicHolds": [], "runs": [{}]})["runs"][0]
        self.assertIn("PMID 990801", listed(run))

    def test_held_records_use_none_of_the_allowance_and_stay_undecided(self):
        n = listings.MAX_NEW_PER_RUN
        rows = [pm(990900 + i, f"Bimodal stimulation in chronic tinnitus: cohort {i}") for i in range(n + 3)]
        items = queue(rows); recs = records(rows)
        held = {items[i]["id"] for i in range(3)}
        out, counts = listings.process(items, {"items": []}, today="2026-11-15", fetch_context=lambda it: recs[it["id"]], record_meta=lambda i: None, held_by_record=lambda it, text: it["id"] in held)
        self.assertEqual((counts["ownerHeld"], counts["listed"]), (3, n))
        for it in items:
            self.assertEqual(bool(it.get("listed")), it["id"] not in held)

    def test_an_unavailable_record_is_never_listed(self):
        it, _ = pm(990950, "Bimodal stimulation in chronic tinnitus")
        out, counts = listings.process([it], {"items": []}, today="2026-11-15", fetch_context=lambda i: registry_record.unavailable_record("offline")[0], record_meta=lambda i: None, held_by_record=lambda i, t: False)
        self.assertEqual(out["items"], [])
        self.assertEqual(counts["deferred"], 1)


if __name__ == "__main__":
    unittest.main()
