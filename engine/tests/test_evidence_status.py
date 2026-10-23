"""Offline tests for the evidence-status notices on treatment pages (tools/evidence_status.py, the static build, and the same words in js/app.js).
No network. Run:  python -m unittest discover -s engine/tests -v"""
import json, shutil, subprocess, sys, tempfile, unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import evidence_status as ES  # noqa: E402

T = {"id": "cbt", "name": "CBT", "evidenceThrough": "2026-09-04", "studies": ["s1", "s2", "s3"]}
S = {"s1": {"id": "s1", "title": "A <b>retracted</b> trial", "integrityNotice": {"severity": "retracted", "source": "PubMed"}},
     "s2": {"id": "s2", "title": "Corrected trial", "integrityNotice": {"severity": "erratum"}},
     "s3": {"id": "s3", "title": "Fine trial"}}


def entry(n, listed, treatments=("cbt",), title=None):
    return {"key": f"PMID {n}", "title": title or f"Tinnitus study {n}", "source": "J Audiol", "date": "2026 Oct 1", "url": f"https://pubmed.ncbi.nlm.nih.gov/{n}/", "listedOn": listed, "treatments": list(treatments)}


class Rules(unittest.TestCase):
    def test_only_severe_notices_make_a_rating_provisional(self):
        self.assertEqual([s["id"] for s, n in ES.provisional(T, S)], ["s1"])             # an erratum does not
        S2 = {**S, "s3": {"id": "s3", "title": "x", "integrityNotice": {"severity": "expression-of-concern"}}, "s2": {"id": "s2", "title": "y", "integrityNotice": {"severity": "partially-retracted"}}}
        self.assertEqual([s["id"] for s, n in ES.provisional(T, S2)], ["s1", "s2", "s3"])
        self.assertEqual(ES.provisional({**T, "studies": ["s3"]}, S), [])

    def test_pending_counts_only_tagged_records_listed_after_the_evidence_date(self):
        L = {"items": [entry(1, "2026-10-30"), entry(2, "2026-09-04"), entry(3, "2026-09-05"), entry(4, "2026-10-30", treatments=("rtms",)), entry(5, "2026-10-31", treatments=())]}
        self.assertEqual([e["key"] for e in ES.pending(T, L)], ["PMID 1", "PMID 3"])
        self.assertEqual(ES.pending(T, None), []); self.assertEqual(ES.pending({**T, "evidenceThrough": ""}, L), [])

    def test_only_clearly_tinnitus_records_count_as_newer_evidence(self):
        L = {"items": [{**entry(1, "2026-10-30"), "tier": 2}, {**entry(2, "2026-10-30"), "tier": 3}, entry(3, "2026-10-30")]}      # no tier on an older entry counts as 2
        self.assertEqual([e["key"] for e in ES.pending(T, L)], ["PMID 3", "PMID 1"])

    def test_staleness_is_more_than_a_year(self):
        self.assertFalse(ES.is_stale(T, date(2027, 9, 4)));  self.assertTrue(ES.is_stale(T, date(2027, 9, 5)))
        self.assertFalse(ES.is_stale({"evidenceThrough": "not a date"}, date(2030, 1, 1)))

    def test_nothing_to_say_means_no_html(self):
        self.assertEqual(ES.status_html({**T, "studies": ["s3"]}, S, {"items": []}, today=date(2026, 11, 1)), "")


class Html(unittest.TestCase):
    def test_the_three_notices_and_their_wording(self):
        L = {"items": [entry(i, "2026-10-30") for i in range(1, 8)]}
        h = ES.status_html(T, S, L, today=date(2027, 10, 1))
        for phrase in (ES.W_PROV_TITLE, ES.W_PROV_LEAD, ES.W_PROV_TAIL, ES.W_PEND_TITLE, ES.W_PEND_LEAD, "Since then 7 " + ES.W_PEND_MID, ES.W_STALE_TITLE, ES.W_STALE_TAIL):
            self.assertIn(phrase, h)
        self.assertEqual(h.count('class="notice"'), 3)
        self.assertEqual(h.count("<li>"), ES.MAX_SHOWN)
        self.assertIn("and 2 more are on the", h)
        self.assertIn("September 4, 2026", h)

    def test_titles_are_escaped(self):
        h = ES.status_html(T, S, {"items": [entry(1, "2026-10-30", title='<script>alert(1)</script> & "x"')]}, today=date(2026, 11, 1))
        self.assertNotIn("<script>", h); self.assertIn("&lt;script&gt;", h); self.assertIn("A &lt;b&gt;retracted&lt;/b&gt; trial", h)

    def test_the_rating_is_never_changed_or_called_assessed(self):
        h = ES.status_html(T, S, {"items": [entry(1, "2026-10-30")]}, today=date(2026, 11, 1))
        self.assertIn("has not changed this rating", h); self.assertIn("rating shown is unchanged", h)
        for bad in ("lower", "downgrad", "no longer", "unsafe", "ineffective", "recommend"):
            self.assertNotIn(bad, h.lower())


class JsStaysInStep(unittest.TestCase):
    def test_every_fixed_phrase_of_the_static_notices_is_also_in_the_interactive_page(self):
        js = (ROOT / "js" / "app.js").read_text(encoding="utf-8").replace("\\u2019", "’")
        for name in ("W_PROV_TITLE", "W_PROV_LEAD", "W_PROV_TAIL", "W_PEND_TITLE", "W_PEND_LEAD", "W_PEND_MID", "W_STALE_TITLE", "W_STALE_TAIL"):
            self.assertIn(getattr(ES, name), js, name)
        self.assertIn("/ 86400000 > %d" % ES.STALE_DAYS, js)         # same one-year threshold
        self.assertIn("slice(0, 5)", js)                        # same number of records shown as MAX_SHOWN
        self.assertEqual(ES.MAX_SHOWN, 5)
        self.assertIn("research.html#listings", js)
        self.assertIn("(e.tier || 2) <= 2", js)                  # same relevance filter as pending()


class StaticBuild(unittest.TestCase):
    """Runs the real tools/build_seo.py on a throw-away copy of the site."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="te-seo-"))
        shutil.copytree(ROOT, cls.tmp / "site", ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__", "*.bundle"))
        cls.site = cls.tmp / "site"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def build(self):
        p = subprocess.run([sys.executable, "-X", "utf8", str(self.site / "tools" / "build_seo.py")], cwd=self.site, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(p.returncode, 0, p.stdout[-400:] + p.stderr[-600:])
        return (self.site / "treatments" / "cbt" / "index.html").read_text(encoding="utf-8"), (self.site / "treatments" / "rtms" / "index.html").read_text(encoding="utf-8")

    def test_pages_carry_the_notices_only_when_their_conditions_hold(self):
        base_cbt, base_rtms = self.build()
        self.assertNotIn("Rating provisional", base_cbt); self.assertNotIn("Newer records not yet assessed", base_cbt)           # listings off, no notices: unchanged
        (self.site / "data" / "listings.json").write_text(json.dumps({"items": [entry(77, "2026-10-30", treatments=("cbt",), title="CBT for tinnitus: a new trial")]}), encoding="utf-8")
        studies = json.loads((self.site / "data" / "studies.json").read_text(encoding="utf-8"))
        rows = studies["studies"] if isinstance(studies, dict) else studies
        for s in rows:
            if s["id"] == "fuller-2020-cochrane":
                s["integrityNotice"] = {"severity": "retracted", "source": "PubMed", "text": "x"}
        (self.site / "data" / "studies.json").write_text(json.dumps(studies), encoding="utf-8")
        cbt, rtms = self.build()
        self.assertIn("Rating provisional.", cbt); self.assertIn("Newer records not yet assessed.", cbt); self.assertIn("CBT for tinnitus: a new trial", cbt)
        self.assertIn("Since then 1 record(s)", cbt)
        self.assertEqual(cbt.count('role="note" aria-label="Rating provisional"'), 1)
        self.assertNotIn("Newer records not yet assessed", rtms)                      # a different treatment is untouched
        self.assertEqual(rtms, base_rtms)


if __name__ == "__main__":
    unittest.main()
