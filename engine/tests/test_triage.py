"""Deterministic triage by source metadata (engine/triage.py): nothing is discarded, nothing is judged clinically, Level 3 is never lowered. Offline."""
import json, shutil, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import triage  # noqa: E402

XML = """<?xml version="1.0"?><PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>111</PMID><Article><ArticleTitle>Sound masking in adults with hearing loss</ArticleTitle><Abstract><AbstractText>We studied 40 adults. Tinnitus was a secondary outcome.</AbstractText></Abstract></Article>
<MeshHeadingList><MeshHeading><DescriptorName>Humans</DescriptorName></MeshHeading></MeshHeadingList></MedlineCitation></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>222</PMID><Article><ArticleTitle>Salicylate exposure in rats</ArticleTitle><Abstract><AbstractText>Tinnitus tinnitus tinnitus-like behaviour. One animal had a seizure.</AbstractText></Abstract></Article>
<MeshHeadingList><MeshHeading><DescriptorName>Animals</DescriptorName></MeshHeading><MeshHeading><DescriptorName>Tinnitus</DescriptorName></MeshHeading></MeshHeadingList></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


def item(n, title, pubtypes=None, facts=None, **kw):
    it = {"id": f"pubmed-{n}", "kind": "study", "title": title, "source": "J", "date": "2026 Oct 1", "url": f"https://pubmed.ncbi.nlm.nih.gov/{n}/", "pubtypes": pubtypes or ["Journal Article"]}
    if facts is not None:
        it["triage"] = facts
    it.update(kw)
    return it


QUIET = {"tinAbs": 1, "tinMesh": False, "tracked": [], "safety": [], "animalOnly": False, "hasAbstract": True}


class Rules(unittest.TestCase):
    def test_every_tracked_treatment_has_a_pattern_that_recognises_its_own_name(self):
        treatments = json.loads((REPO / "data" / "treatments.json").read_text(encoding="utf-8"))
        al = triage.rules()["aliases"]
        self.assertEqual(sorted(set(t["id"] for t in treatments) - set(al)), [])
        misses = [t["id"] for t in treatments if t["id"] not in triage.tracked_in(t["name"])]
        self.assertEqual(misses, [])


class Facts(unittest.TestCase):
    def test_features_are_derived_values_not_text(self):
        f = triage.features_from_xml(XML)
        self.assertEqual((f["111"]["tinAbs"], f["111"]["tinMesh"], f["111"]["tracked"], f["111"]["safety"]), (1, False, ["sound-therapy"], []))
        self.assertEqual((f["222"]["tinAbs"], f["222"]["tinMesh"], f["222"]["animalOnly"], f["222"]["safety"]), (3, True, True, ["seizure"]))
        self.assertEqual(f["222"]["safetyWeak"], []); self.assertEqual(triage.features_from_xml(XML.replace("One animal had a seizure.", "Adverse events were recorded."))["222"]["safetyWeak"], ["adverse events"])
        self.assertTrue(all(isinstance(v, (int, bool, list)) for d in f.values() for v in d.values()))     # no abstract text is kept: the queue file is public

    def test_enrich_attaches_facts_and_a_failed_lookup_changes_nothing(self):
        its = [item(111, "Sound masking in adults"), item(333, "Another")]
        old = triage.fetch_xml
        try:
            triage.fetch_xml = lambda ids: XML
            self.assertEqual(triage.enrich(its), 1); self.assertIn("triage", its[0]); self.assertNotIn("triage", its[1])
            its2 = [item(111, "x")]
            triage.fetch_xml = lambda ids: None
            self.assertEqual(triage.enrich(its2), 0); self.assertNotIn("triage", its2[0])
            triage.fetch_xml = lambda ids: "<not xml"
            self.assertEqual(triage.enrich(its2), 0)
        finally:
            triage.fetch_xml = old


class Classify(unittest.TestCase):
    def c(self, it):
        return triage.classify(it)

    def test_tiers(self):
        self.assertEqual(self.c(item(1, "Erratum: tinnitus trial", ["Published Erratum"]))["tier"], 0)
        self.assertEqual(self.c(item(2, "Retraction notice: X"))["tier"], 0)
        self.assertEqual(self.c(item(3, "A trial", ["Randomized Controlled Trial"], QUIET))["tier"], 1)
        self.assertEqual(self.c(item(4, "A review", ["Systematic Review", "Meta-Analysis"], QUIET))["tier"], 1)
        self.assertEqual(self.c(item(5, "Tinnitus and rTMS in adults"))["tier"], 1)                      # tracked treatment in the title
        self.assertEqual(self.c(item(6, "Tinnitus outcomes after therapy", None, dict(QUIET, tracked=["acupuncture"])))["tier"], 1)   # tinnitus in the title AND a tracked treatment in abstract or MeSH
        self.assertEqual((self.c(item(61, "Headache outcomes", None, dict(QUIET, tracked=["acupuncture"])))["tier"], self.c(item(61, "Headache outcomes", None, dict(QUIET, tracked=["acupuncture"])))["lane"]), (3, "evaluate"))   # abstract-only match: lower priority, never catalogued
        self.assertEqual(self.c(item(7, "A drug study", None, dict(QUIET, safety=["seizure"])))["tier"], 1)
        self.assertEqual(self.c(item(8, "Tinnitus prevalence in veterans"))["tier"], 2)
        self.assertEqual(self.c(item(9, "Hearing loss in adults", None, dict(QUIET, tinAbs=3)))["tier"], 3)
        self.assertEqual(self.c({"id": "fda-510-k-clearance-k1", "kind": "regulatory", "title": "FDA decision"})["tier"], 1)
        self.assertEqual(self.c({"id": "ctgov-NCT01-2026-01-01", "kind": "trial", "title": "A registry record"})["tier"], 2)
        self.assertEqual(self.c(item(10, "Tinnitus x", None, None, triageForce=True))["tier"], 1)

    def test_catalogue_rule_c1_only_for_quiet_mentions_with_known_facts(self):
        quiet = item(20, "Sleep and screen time in adolescents", None, QUIET)
        r = self.c(quiet)
        self.assertEqual((r["lane"], r["rule"]), ("catalogue", "C1"))
        for name, it in {"facts unknown (fail open)": item(21, "Sleep and screen time", None, None),
                         "tinnitus in the title": item(22, "Tinnitus and sleep", None, QUIET),
                         "MeSH heading": item(23, "Sleep and screen time", None, dict(QUIET, tinMesh=True)),
                         "three mentions": item(24, "Sleep and screen time", None, dict(QUIET, tinAbs=3)),
                         "RCT": item(25, "Sleep and screen time", ["Randomized Controlled Trial"], QUIET),
                         "systematic review": item(26, "Sleep and screen time", ["Systematic Review"], QUIET),
                         "tracked treatment in the abstract": item(27, "Sleep and screen time", None, dict(QUIET, tracked=["cbt"])),
                         "safety term": item(28, "Sleep and screen time", None, dict(QUIET, safety=["suicide"])),
                         "safety term in the title": item(29, "Seizure after device implantation", None, QUIET),
                         "pulsatile tinnitus wording": item(30, "Pulsatile sound after surgery", None, QUIET),
                         "weaker safety wording": item(34, "Sleep and screen time", None, dict(QUIET, safetyWeak=["adverse events"])),
                         "notice": item(31, "Correction to: sleep study", None, QUIET),
                         "owner promoted": item(32, "Sleep and screen time", None, QUIET, triageForce=True),
                         "not PubMed": {"id": "ctgov-NCT01-2026-01-01", "kind": "trial", "title": "Sleep", "triage": QUIET},
                         "facts missing the abstract count": item(33, "Sleep", None, {"tinMesh": False})}.items():
            self.assertEqual(self.c(it)["lane"], "evaluate", name)

    def test_it_never_changes_what_the_clinical_rules_do(self):
        # a catalogue candidate that carries a strong safety term is not catalogued, so the Level 3 trigger still sees the record
        self.assertEqual(self.c(item(40, "Adverse event report", None, dict(QUIET, safety=["serious adverse event"])))["lane"], "evaluate")


class Ordering(unittest.TestCase):
    def test_lowest_tier_first_oldest_first_within_a_tier_and_nothing_dropped(self):
        q = [item(1, "Tinnitus a"), item(2, "Hearing", None, dict(QUIET, tinAbs=3)), item(3, "Tinnitus b"), item(4, "A trial", ["Randomized Controlled Trial"], QUIET), item(5, "Erratum: x", ["Published Erratum"])]
        got = [i["id"] for i in triage.order(q)]
        self.assertEqual(got, ["pubmed-5", "pubmed-4", "pubmed-3", "pubmed-1", "pubmed-2"])     # queue position 0 is the newest, so 3 (older) precedes 1
        self.assertEqual(sorted(got), sorted(i["id"] for i in q))

    def test_settings_are_off_unless_exactly_true(self):
        self.assertEqual(triage.load_settings({}), {"order": False, "catalogue": False, "shadow": False, "auditSample": 2})
        self.assertEqual(triage.load_settings({"triage": {"order": "true", "catalogue": 1}}), {"order": False, "catalogue": False, "shadow": False, "auditSample": 2})
        self.assertEqual(triage.load_settings({"triage": {"order": True, "catalogue": True, "auditSample": 99}}), {"order": True, "catalogue": True, "shadow": False, "auditSample": 10})
        self.assertEqual(triage.load_settings({"triage": {"auditSample": "x"}})["auditSample"], 2)
        self.assertEqual(triage.load_settings(None), {"order": False, "catalogue": False, "shadow": False, "auditSample": 2})
        cfg = json.loads((ENGINE / "eval_settings.json").read_text(encoding="utf-8"))
        self.assertEqual(any(triage.load_settings(cfg)[k] for k in ("order", "catalogue", "shadow")), False)      # shipped OFF
        self.assertTrue(triage.load_settings({"triage": {"shadow": True}})["shadow"]); self.assertFalse(triage.load_settings({"triage": {"shadow": "yes"}})["shadow"])

    def test_audit_pick_is_deterministic_and_bounded(self):
        c = [item(i, "x") for i in range(30)]
        a, b = triage.audit_pick(c, 3, "2026-11-01"), triage.audit_pick(c, 3, "2026-11-01")
        self.assertEqual(a, b); self.assertEqual(len(a), 3)
        self.assertNotEqual(a, triage.audit_pick(c, 3, "2026-11-15"))
        self.assertEqual(triage.audit_pick(c, 0, "x"), set())


QUIETQ = [item(70000001 + i, f"Sleep and screen time cohort {i}", None, QUIET) for i in range(4)]
KEEP = [item(70000101, "Tinnitus and sleep in adults", None, QUIET), item(70000102, "A randomised trial of something", ["Randomized Controlled Trial"], QUIET), item(70000103, "Erratum: tinnitus study", ["Published Erratum"])]


def cfg(**t):
    return {"enabled": True, "mode": "staged", "limitPerRun": 20, "triage": t}


class InThePipeline(unittest.TestCase):
    def run_(self, queue, settings, extra=None):
        return run_scenario({"queue": queue, "settings": settings, **(extra or {}), "runs": [{}]})["runs"][0]

    def test_off_by_default_everything_is_evaluated(self):
        r = self.run_(QUIETQ + KEEP[:2], cfg())
        for i in QUIETQ + KEEP[:2]:
            self.assertIn(i["id"], r["apiCalls"])
        self.assertNotIn("triage", r["status"])

    def test_catalogue_archives_with_a_reason_and_makes_no_api_call_and_loses_nothing(self):
        r = self.run_(QUIETQ + KEEP[:2], cfg(catalogue=True, auditSample=0))
        for i in QUIETQ:
            self.assertNotIn(i["id"], r["apiCalls"]); self.assertIn(i["id"], r["archived"])
            self.assertNotIn(i["id"], r["queue"] + r["held"] + list(r["staged"]))             # in exactly one place: the archive
            self.assertIn(i["id"], r["knownIds"])                                             # and never rescanned
        for i in KEEP[:2]:
            self.assertIn(i["id"], r["apiCalls"])
        self.assertEqual(r["status"]["triage"]["catalogued"], 4)
        self.assertEqual([x["identifier"] for x in r["reportItems"] if x["identifier"] in {q["id"] for q in QUIETQ}], [])      # nothing is published from a catalogued record
        self.assertTrue(r["ratingsUnchanged"] and r["studiesUnchanged"])

    def test_shadow_mode_changes_nothing_but_counts_what_the_catalogue_would_have_missed(self):
        r = self.run_(QUIETQ + KEEP[:2], cfg(shadow=True, auditSample=0))
        for i in QUIETQ + KEEP[:2]:
            self.assertIn(i["id"], r["apiCalls"])                                               # everything is evaluated, exactly as with triage off
        self.assertEqual(r["archived"].count("pubmed-70000001"), 0)
        self.assertEqual(r["status"]["triage"]["auditEvaluated"], 4)                              # the four catalogue candidates are counted
        fed = sum(1 for k, v in r["staged"].items() if k in {q["id"] for q in QUIETQ} and v["route"] in ("publish", "publish-under-eval"))
        self.assertEqual(r["status"]["triage"].get("auditWouldFeed", 0), fed)
        self.assertNotIn("catalogued", r["status"]["triage"])
        ev = r["triageEvidence"]
        self.assertEqual((ev["evaluated"], ev["wouldFeed"], len(ev["misses"])), (4, fed, fed))              # the cumulative ledger the digest shows

    def test_the_audit_sample_is_evaluated_anyway_and_counted(self):
        r = self.run_(QUIETQ, cfg(catalogue=True, auditSample=1))
        called = [i["id"] for i in QUIETQ if i["id"] in r["apiCalls"]]
        self.assertEqual(len(called), 1)
        self.assertEqual(r["status"]["triage"]["catalogued"], 3); self.assertEqual(r["status"]["triage"]["auditEvaluated"], 1)

    def test_a_notice_or_trial_or_tracked_treatment_is_never_catalogued_even_when_tinnitus_is_missing_from_the_title(self):
        its = [item(70000201, "Sleep study", ["Randomized Controlled Trial"], QUIET), item(70000202, "Sleep study", None, dict(QUIET, tracked=["cbt"])), item(70000203, "Correction to: sleep study", ["Published Erratum"], QUIET)]
        r = self.run_(its, cfg(catalogue=True, auditSample=0))
        self.assertEqual(r["status"].get("triage", {}).get("catalogued", 0), 0)
        self.assertEqual(r["archived"].count("pubmed-70000201"), 0)

    def test_order_spends_the_limit_on_the_most_important_and_preserves_the_rest(self):
        q = QUIETQ[:2] + [item(70000301, "Tinnitus prevalence", None, QUIET)] + KEEP[1:2]
        r = self.run_(q, {"enabled": True, "mode": "staged", "limitPerRun": 2, "triage": {"order": True, "catalogue": False}})
        self.assertEqual(sorted(r["apiCalls"]), sorted(["pubmed-70000102", "pubmed-70000301"]))      # the trial (tier 1) and the tinnitus-in-title record (tier 2)
        for i in QUIETQ[:2]:
            self.assertIn(i["id"], r["queue"])                                                # not evaluated, not lost: still queued
        r0 = self.run_(q, {"enabled": True, "mode": "staged", "limitPerRun": 2, "triage": {"order": False}})
        self.assertNotEqual(sorted(r0["apiCalls"]), sorted(r["apiCalls"]))                       # without ordering the limit is spent in queue order

    def test_a_catalogued_record_can_be_promoted_back(self):
        root = Path(tempfile.mkdtemp(prefix="te-tri-"))
        (root / "data" / "review-queue").mkdir(parents=True)
        (root / "data/review-queue/queue.json").write_text(json.dumps({"items": []}), encoding="utf-8")
        (root / "data/review-queue/archive.json").write_text(json.dumps({"items": [{"archivedAt": "2026-11-01T06:00:00", "reason": "catalogued without AI evaluation (rule C1): x", "item": {"id": "pubmed-5", "title": "Sleep", "url": "u"}},
                                                                                 {"archivedAt": "2026-11-01T06:00:00", "reason": "relevance category 4", "item": {"id": "pubmed-6", "title": "Other", "url": "u"}}]}), encoding="utf-8")
        self.assertTrue(triage.promote(root, "pubmed-5")); self.assertFalse(triage.promote(root, "pubmed-6")); self.assertFalse(triage.promote(root, "pubmed-404"))
        q = json.loads((root / "data/review-queue/queue.json").read_text(encoding="utf-8"))["items"]
        self.assertEqual([i["id"] for i in q], ["pubmed-5"]); self.assertEqual(triage.classify(q[0])["tier"], 1)
        self.assertEqual(len(json.loads((root / "data/review-queue/archive.json").read_text(encoding="utf-8"))["items"]), 1)
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
