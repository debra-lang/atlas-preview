"""Offline tests for tools/audit_listings.py (the independent re-check of data/listings.json). The two public APIs are replaced by canned answers."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import audit_listings as au  # noqa: E402


def entry(n, title="Tinnitus counselling in primary care", source="Journal of Audiology", date="2026 Oct 12", types=("Journal Article",), **kw):
    return {"key": f"PMID {n}", "kind": "study", "title": title, "source": source, "date": date, "url": f"https://pubmed.ncbi.nlm.nih.gov/{n}/", "tier": 2,
            "articleTypes": list(types), "treatments": [], "highImpact": False, "listedOn": "2026-11-01", **kw}


def summary(n, title="Tinnitus counselling in primary care.", journal="Journal of audiology", pubdate="2026 Oct 12", types=("Journal Article",), doi="10.1/x"):
    return {"uid": str(n), "title": title, "fulljournalname": journal, "source": "J Audiol", "pubdate": pubdate, "epubdate": "", "pubtype": list(types),
            "articleids": [{"idtype": "pubmed", "value": str(n)}, {"idtype": "doi", "value": doi}]}


def fetch_for(sums, registry=None):
    def fetch(url, pause=0):
        if "esummary" in url:
            ids = [p for p in url.split("id=")[1].split("&")[0].replace("%2C", ",").split(",")]
            return {"result": {"uids": ids, **{i: sums[i] for i in ids if i in sums}}}
        nct = url.split("/studies/")[1].split("?")[0]
        if registry is None or nct not in registry:
            raise OSError("not found")
        return registry[nct]
    return fetch


class Source(unittest.TestCase):
    def run_one(self, e, s):
        rep = au.audit({"items": [e]}, None, fetch=fetch_for({e["key"].split()[1]: s} if s else {}))
        return rep["rows"][0]["sourceProblems"], rep

    def test_a_correct_listing_has_no_problems(self):
        self.assertEqual(self.run_one(entry(1), summary(1))[0], [])

    def test_each_kind_of_mismatch_is_reported(self):
        self.assertTrue(any("title differs" in p for p in self.run_one(entry(1), summary(1, title="A different paper altogether."))[0]))
        self.assertTrue(any("journal differs" in p for p in self.run_one(entry(1), summary(1, journal="Another Journal"))[0]))
        self.assertTrue(any("date differs" in p for p in self.run_one(entry(1), summary(1, pubdate="2019 Jan"))[0]))
        self.assertTrue(any("article types differ" in p for p in self.run_one(entry(1, types=("Journal Article", "Randomized Controlled Trial")), summary(1))[0]))
        self.assertTrue(any("retraction or erratum" in p for p in self.run_one(entry(1), summary(1, types=("Journal Article", "Retracted Publication")))[0]))
        self.assertTrue(any("not found" in p for p in self.run_one(entry(1), None)[0]))
        self.assertTrue(any("not found" in p for p in self.run_one(entry(1), summary(2))[0]))

    def test_the_abbreviated_journal_name_is_accepted(self):
        self.assertEqual(self.run_one(entry(1, source="J Audiol"), summary(1))[0], [])


class Registry(unittest.TestCase):
    @staticmethod
    def study(nct="NCT01", title="Tinnitus device trial", status="RECRUITING", conditions=("Tinnitus",)):
        return {"protocolSection": {"identificationModule": {"nctId": nct, "briefTitle": title}, "statusModule": {"overallStatus": status}, "conditionsModule": {"conditions": list(conditions)}}}

    def e(self, **kw):
        return {"key": "NCT01", "kind": "trial", "title": "Tinnitus device trial", "source": "Univ", "date": "2026-10-20", "url": "u", "tier": 2, "articleTypes": ["Registry record"],
                "treatments": [], "highImpact": False, "listedOn": "2026-11-01", "status": "RECRUITING", **kw}

    def test_matching_record_and_status_change_and_title_mismatch_and_unavailable(self):
        rep = au.audit({"items": [self.e()]}, None, fetch=fetch_for({}, {"NCT01": self.study()}))
        self.assertEqual((rep["rows"][0]["sourceProblems"], rep["rows"][0]["relevance"]), ([], "clear"))
        rep = au.audit({"items": [self.e()]}, None, fetch=fetch_for({}, {"NCT01": self.study(status="COMPLETED")}))
        self.assertEqual(rep["rows"][0]["sourceProblems"], []); self.assertTrue(any("status has changed" in p for p in rep["rows"][0]["informational"]))     # informational only
        rep = au.audit({"items": [self.e()]}, None, fetch=fetch_for({}, {"NCT01": self.study(title="Something else entirely")}))
        self.assertTrue(any("title differs" in p for p in rep["rows"][0]["sourceProblems"]))
        rep = au.audit({"items": [self.e()]}, None, fetch=fetch_for({}, {}))
        self.assertTrue(any("could not be fetched" in p for p in rep["rows"][0]["sourceProblems"]))

    def test_relevance_of_a_registry_record_comes_from_its_conditions(self):
        e = self.e(title="Pain after hip surgery")
        rep = au.audit({"items": [e]}, None, fetch=fetch_for({}, {"NCT01": self.study(title="Pain after hip surgery", conditions=("Pain",))}))
        self.assertEqual(rep["rows"][0]["relevance"], "loose")


class Duplicates(unittest.TestCase):
    def test_same_identifier_doi_and_title_are_found_and_near_duplicates_are_grouped(self):
        items = [entry(1), entry(1), entry(2, title="Tinnitus counselling in primary care"), entry(3, title="A completely different title here"),
                 entry(4, title="Clinical Practice Guideline: Tinnitus Update"), entry(5, title="Clinical Practice Guideline: Tinnitus Update (Executive Summary)")]
        sums = {"1": summary(1), "2": summary(2, doi="10.1/x"), "3": summary(3, title="A completely different title here.", doi="10.1/3"),
                "4": summary(4, title="Clinical Practice Guideline: Tinnitus Update.", doi="10.1/4"), "5": summary(5, title="Clinical Practice Guideline: Tinnitus Update (Executive Summary).", doi="10.1/5")}
        rep = au.audit({"items": items}, None, fetch=fetch_for(sums))
        dups = [r["duplicates"] for r in rep["rows"]]
        self.assertEqual(dups[0], [])
        self.assertTrue(any("same identifier" in d for d in dups[1]))
        self.assertTrue(any("same DOI" in d for d in dups[2]) and any("same title" in d for d in dups[2]))
        self.assertEqual(dups[3], [])
        self.assertEqual(rep["summary"]["nearDuplicateGroups"], [["PMID 4", "PMID 5"]])


class Relevance(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(au.relevance({"title": "Tinnitus after surgery"}, None), "clear")
        self.assertEqual(au.relevance({"title": "Hearing outcomes"}, {"tinMesh": True, "tinAbs": 0}), "central")
        self.assertEqual(au.relevance({"title": "Hearing outcomes"}, {"tinMesh": False, "tinAbs": 6}), "central")
        self.assertEqual(au.relevance({"title": "Hearing outcomes"}, {"tinMesh": False, "tinAbs": 2}), "loose")
        self.assertEqual(au.relevance({"title": "Hearing outcomes"}, None), "unknown")


class Cli(unittest.TestCase):
    def test_sample_and_exit_code(self):
        items = [entry(i, title=f"Tinnitus study number {i}") for i in range(1, 7)]
        sums = {str(i): summary(i, title=f"Tinnitus study number {i}.", doi=f"10.1/{i}") for i in range(1, 7)}
        rep = au.audit({"items": items}, None, fetch=fetch_for(sums), sample=3, seed=7)
        self.assertEqual(rep["summary"]["audited"], 3)
        self.assertEqual(au.audit({"items": items}, None, fetch=fetch_for(sums), sample=3, seed=7)["rows"], rep["rows"])      # the sample is reproducible


if __name__ == "__main__":
    unittest.main()
