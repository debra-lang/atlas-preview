"""Checks for the Level B disclosure edits (branch disclosure-b). Run: python -X utf8 -m unittest discover -s engine/tests"""
import json, re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
read = lambda p: (ROOT / p).read_text(encoding="utf-8")


class TestDisclosureEdits(unittest.TestCase):
    def test_overstated_phrases_are_gone_from_the_public_pages(self):
        for page in ("research.html", "about.html"):
            s = re.sub(r"\s+", " ", read(page))
            for bad in ("automatically verified against primary sources", "Missing information is never inferred", "after automated verification of the source"):
                self.assertFalse(bad in s, f"{page} still says: {bad}")
        self.assertFalse("never inferred" in read("engine/README.md"))

    def test_notice_dates_are_exactly_the_four_september_reports_that_carry_ai_written_items(self):
        js = read("js/app.js")
        dates = re.search(r"AI_UNREVIEWED = \{\s*dates: \[([^\]]*)\]", js).group(1)
        dates = re.findall(r"'(\d{4}-\d\d-\d\d)'", dates)
        self.assertEqual(dates, ["2026-09-07", "2026-09-14", "2026-09-21", "2026-09-26"])
        for d in dates:
            self.assertTrue((ROOT / "data" / "weekly" / f"{d}.json").exists())

    def test_item_label_is_only_a_string_so_array_map_index_cannot_leak_into_the_page(self):
        self.assertIn("typeof label === 'string' && label", read("js/app.js"))

    def test_notice_and_label_wording_claims_no_review_or_verification(self):
        js = read("js/app.js")
        block = js[js.index("AI_UNREVIEWED = {"): js.index("const renderReport")]
        for bad in ("verified", "fact-checked", "validated", "accurate", "peer review", "clinician-reviewed by", "approved by"):
            self.assertNotRegex(block.replace("not clinician-reviewed", ""), re.compile(r"\b" + bad, re.I), bad)
        for need in ("No person reviewed them individually", "none was reviewed by a physician or other clinician", "do not use these summaries for medical decisions"):
            self.assertIn(need, block)

    def test_weekly_report_files_are_unchanged_from_production(self):
        # the disclosure is rendered by the page; no published research record is edited
        import subprocess
        out = subprocess.run(["git", "diff", "--name-only", "a69020cc76615cfff7827ca3c3d4c438623cb128", "--", "data/weekly", "data/studies.json", "data/treatments.json", "data/trials.json"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, "")


class TestPublicStatementsAreAccurate(unittest.TestCase):
    """The public pages must describe how things work TODAY (22 Oct 2026): evaluation is off, AI-written summaries are paused, nothing AI-written publishes without the site editor, updates run twice a month."""
    PAGES = ("research.html", "about.html", "index.html", "js/app.js")

    def text(self, page):
        return re.sub(r"\s+", " ", read(page))

    def test_no_public_page_claims_that_updates_publish_automatically_except_registry_status_changes(self):
        for page in self.PAGES:
            s = self.text(page)
            for bad in ("Routine updates publish", "Routine research updates", "publish to the research updates page (\"Latest Tinnitus Research\") automatically, after automated verification",
                        "automatically verified against primary sources", "Routine updates publish automatically"):
                self.assertNotIn(bad, s, f"{page}: {bad}")

    def test_the_research_page_and_the_about_page_say_what_is_true(self):
        r, a = self.text("research.html"), self.text("about.html")
        for need in ("twice-monthly digest", "AI-written study summaries are currently paused", "Summaries published between September 7 and September 26, 2026, were not reviewed by a person before publication",
                     "Before new summaries are published, the site editor will review each summary against its source", "it does not mean that a clinician has reviewed or endorsed a summary",
                     "Items that could affect an evidence rating will be held for additional review", "Evidence ratings will not change automatically"):
            self.assertIn(need, r, need)
        for need in ("AI-written summaries have been paused since September 28, 2026", "each summary will require editorial review against its source before it is published", "none will be published automatically",
                     "It is not a clinical review, and it does not mean that a clinician has reviewed or endorsed a summary", "Trial status changes</strong> verified directly at the registry",
                     "twice a month, on the 1st and 15th", "The scheduled start is 06:00 Pacific Time, but that is when the run is triggered, not a guaranteed publication time",
                     "we cannot guarantee that nothing is missed after a long interruption", "The AI is instructed not to infer missing information",
                     "published between September 7 and September 26, 2026, were not reviewed by any person before publication"):
            self.assertIn(need, a, need)
        self.assertNotIn("identified inaccuracies", a + r)                      # the owner's draft word: the evidence supports a narrower statement (below)

    def test_the_statements_about_the_september_review_never_go_beyond_the_recorded_evidence(self):
        evidence = json.loads(read("engine/tests/fixtures/september-review-evidence.json"))
        a = self.text("about.html")
        if "statements that the source does not make" in a:
            self.assertGreaterEqual(len(evidence["itemsWithClaimsTheAbstractDoesNotMake"]), 1)
        if "one incorrect date" in a:
            self.assertNotEqual(evidence["fdaItem"]["publishedDecisionDate"], evidence["fdaItem"]["officialDecisionDate"])
        self.assertNotIn("incorrect numbers", a)                                # the check found paraphrased or derived numbers, not wrong ones
        self.assertNotRegex(a, r"we (have )?corrected|corrections (were|have been) (made|published)")      # nothing has been corrected yet: only "we are preparing corrections"
        self.assertIn("we are preparing corrections", a)

    def test_editorial_review_is_never_presented_as_clinical_review_or_endorsement(self):
        for page in ("research.html", "about.html"):
            self.assertRegex(self.text(page), r"not a clinical review|does not mean that a clinician")
        self.assertIn("editorial review (not a clinical review)", read("js/app.js"))

    def test_the_label_is_only_put_on_items_the_ai_actually_wrote(self):
        js = read("js/app.js")
        self.assertIn("it.detail && it.detail.studyType ? AI_UNREVIEWED.label : ''", js)
        self.assertIn("Except for trial status changes taken directly from the registry", js)

    def test_no_page_of_the_site_claims_automatic_publication_of_summaries(self):
        allowed = ("what publishes automatically and what never does", "Hypotheses are never auto-published", "automatically, after checks of the identifier", "none will be published automatically",
                   "never published automatically")
        hits = []
        for f in sorted(ROOT.rglob("*.html")):
            rel = f.relative_to(ROOT).as_posix()
            if rel in ("preview.html", "admin.html") or rel.startswith(("audit", "docs/", "node_modules", ".git")):
                continue
            t = re.sub(r"\s+", " ", f.read_text(encoding="utf-8"))
            for m in re.finditer(r".{0,60}(?:publish\w* automatically|automatically publish|auto-publish|automatically verified).{0,60}", t, re.I):
                if not any(a in m.group(0) for a in allowed):
                    hits.append((rel, m.group(0)))
        self.assertEqual(hits, [])

    def test_the_footer_line_on_every_page_matches(self):
        js = read("js/app.js")
        self.assertIn("AI-written summaries are currently paused and, when they resume, will receive editorial review (not a clinical review) before publication", js)
        self.assertNotIn("Routine updates publish automatically after source verification", js)

    def test_no_unfinished_placeholder_text_is_on_any_public_page(self):
        for page in ("about.html", "research.html", "index.html", "trials.html", "js/app.js"):
            self.assertNotRegex(read(page), r"\[N statements|\[DATE\]|\bLINK\]|TODO|FIXME", page)

    def test_the_notice_links_to_a_section_that_exists(self):
        js, about = read("js/app.js"), read("about.html")
        for anchor in re.findall(r'about\.html#([a-z\-]+)', js):
            self.assertIn(f'id="{anchor}"', about, f"the notice links to about.html#{anchor}, which does not exist")

    def test_the_generated_notices_do_not_say_repaired_or_weekly(self):
        src = (ROOT / "engine" / "weekly_cycle.py").read_text(encoding="utf-8")
        self.assertNotIn("being repaired", src)
        self.assertIn("currently paused while its safeguards are being tested", src)


if __name__ == "__main__":
    unittest.main()
