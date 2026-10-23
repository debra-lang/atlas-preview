"""Offline tests for the public wording approved on 23 Oct 2026 (the "who prepares this site" disclosure, the disclaimer bullet, the research-page lead, the footer, the Ask page).
They pin the approved texts, keep the disclosure from being repeated across the site, and keep automated checking from being described as clinical review. No network."""
import re, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def text(rel):
    return re.sub(r"\s+", " ", (ROOT / rel).read_text(encoding="utf-8"))


W1 = ("Who prepares this site.</strong> Tinnitus Evidence is an independent educational resource developed by its owner using published scientific research and automated tools, "
      "including AI. It is not affiliated with or endorsed by a medical institution. Its content, including treatment assessments and Ask responses, has not undergone independent "
      "clinical review. Automated source checks verify that research records match their original sources; they do not establish whether a study's conclusions are valid or whether "
      "a treatment is effective.")


class About(unittest.TestCase):
    def test_the_single_full_disclosure_is_the_approved_text_and_has_its_anchor(self):
        a = text("about.html")
        self.assertIn('<p id="review"><strong>' + W1, a)
        self.assertEqual(a.count('id="review"'), 1)

    def test_the_disclaimer_bullet_is_short_and_links_to_the_disclosure(self):
        a = text("about.html")
        self.assertIn('<li>is <strong>not</strong> reviewed or endorsed by a physician or other qualified healthcare professional (see <a href="#review">Who prepares this site</a>);</li>', a)

    def test_the_september_disclosure_is_kept_once_in_about(self):
        a = text("about.html")
        self.assertEqual(a.count("published between September 7 and September 26, 2026, were not reviewed by any person before publication"), 1)

    def test_the_ask_statement_is_true_ai_does_write_ask_answers(self):
        a = text("about.html")
        self.assertIn("No AI-written text is currently published in the research updates. (Answers from Ask Tinnitus Evidence are generated automatically by an AI model from this site's database.)", a)
        self.assertNotIn("AI is not currently used to write anything the public sees", a)

    def test_listings_ratings_and_safety_statements_match_what_the_code_does(self):
        a = text("about.html")
        self.assertIn("Research listings and notices make no statement about safety", a)                 # the site's treatment pages do carry safety-evidence ratings, so the claim is limited to listings and notices
        self.assertNotIn("draws no safety conclusions of its own", a)
        self.assertIn("a single new study is not enough to raise one", a)
        self.assertIn("treatment pages that cite the study are marked \"Rating provisional\"", a)
        self.assertIn("Routine corrections (errata) are recorded in the audit log", a)
        self.assertNotIn("routed to held review", a)
        self.assertIn("No person and no AI reads or assesses a listed record", a)


class OtherPages(unittest.TestCase):
    def test_the_research_page_and_footer_do_not_repeat_the_disclosure(self):
        # (the script and the Ask page legitimately say "see a clinician" or "does not replace an ENT physician"; what must not recur is a statement about REVIEW or ENDORSEMENT)
        pattern = r"clinical review|reviewed (or|by)|endorse|clinician-reviewed|clinician has|has not undergone|independent(ly)? (clinical|review)"
        for rel in ("research.html", "ask/index.html"):
            self.assertNotRegex(text(rel), pattern, rel)
        js = text("js/app.js")
        footer = js[js.index("New research records are checked against their sources before listing"):][:260]
        self.assertNotRegex(footer, pattern)

    def test_the_footer_line(self):
        js = text("js/app.js")
        self.assertIn("New research records are checked against their sources before listing. Listings are not evidence assessments. Treatment ratings and safety assessments are not automatically changed.", js)

    def test_the_research_descriptions_say_source_checked(self):
        r = text("research.html")
        self.assertEqual(r.count("source-checked tinnitus research updates"), 3)
        self.assertNotIn("source-verified", r)

    def test_the_ask_page_points_to_the_disclosure_instead_of_repeating_it(self):
        t = text("ask/index.html")
        self.assertIn('This tool provides research information, not diagnosis or personalized medical advice. Answers are generated automatically from this site\'s database. <a href="about.html#review">Who prepares this site</a>', t)
        self.assertNotIn("verified evidence database", t); self.assertNotIn("verified database", t)
        self.assertIn("Searching the evidence database…", t); self.assertIn("Coverage in the database:", t)
        self.assertEqual(text("tools/build_seo.py").count("Searching the evidence database…"), 2)                  # the generator matches the generated page

    def test_the_ask_worker_fixed_answers_and_fallback_phrase_agree(self):
        w = text("ask-worker/worker.js")
        self.assertEqual(w.count("does not currently contain enough evidence in its database to answer this question reliably"), 3)    # two fixed answers and the prompt's quoted fallback
        self.assertNotIn("enough verified evidence", w)
        self.assertIn("here is where to look in the database.", w)

    def test_the_ask_link_target_exists(self):
        self.assertIn('id="review"', text("about.html"))


class Placeholders(unittest.TestCase):
    def test_the_dormant_notices_contain_no_clinician_statement(self):
        js = text("js/app.js")
        block = js[js.index("evidence-status notices"): js.index("watchlist (v2")]
        self.assertNotRegex(block, r"physician|clinician|clinical review")


if __name__ == "__main__":
    unittest.main()
