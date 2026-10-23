"""Checks for the Level B disclosure edits (branch disclosure-b). Run: python -X utf8 -m unittest discover -s engine/tests"""
import json, re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
read = lambda p: (ROOT / p).read_text(encoding="utf-8")


def corrections_log():
    return json.loads(read("data/corrections-log.json"))


def _field(it, field):
    holder, key = {"Summary": (it, "summary"), "Why it matters": (it, "whyMatters"), "Headline": (it, "title"), "Funding / conflicts": (it["detail"], "funding"), "Limitations": (it["detail"], "limitations"), "Safety": (it["detail"], "safety"), "Control": (it["detail"], "control"), "Study type": (it["detail"], "studyType")}[field]
    return holder, key


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
            self.assertNotRegex(block.replace("not clinician-reviewed", "").replace("has not been verified", ""), re.compile(r"\b" + bad, re.I), bad)
        for need in ("No person reviewed them individually", "none was reviewed by a physician or other clinician", "do not use these summaries for medical decisions"):
            self.assertIn(need, block)

    def test_the_only_changes_to_published_records_are_the_logged_corrections(self):
        # the report files differ from production ONLY by the logged corrections: putting each logged field's original text back must give production's file exactly
        import subprocess, copy
        BASE = "a69020cc76615cfff7827ca3c3d4c438623cb128"
        log = corrections_log()
        # Only files that already existed at BASE are held to the rule (--diff-filter=M): a new weekly report added by a later cycle is not a change to a published record.
        # The weekly index is the one existing file a cycle legitimately rewrites; it may only GAIN entries, every entry that existed at BASE must be unchanged.
        changed = subprocess.run(["git", "diff", "--name-only", "--diff-filter=M", BASE, "--", "data/weekly", "data/studies.json", "data/treatments.json", "data/trials.json"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        if "data/weekly/index.json" in changed:
            base_idx = json.loads(subprocess.run(["git", "show", f"{BASE}:data/weekly/index.json"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout)["reports"]
            now_idx = json.loads(read("data/weekly/index.json"))["reports"]
            self.assertEqual([r for r in now_idx if r["date"] in {b["date"] for b in base_idx}], base_idx, "existing index entries are unchanged; the index only gains newer reports")
            changed.remove("data/weekly/index.json")
        self.assertEqual(sorted(changed), sorted({c["file"] for c in log["corrections"]}))
        for f in changed:
            base = json.loads(subprocess.run(["git", "show", f"{BASE}:{f}"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout)
            now = json.loads(read(f))
            restored = copy.deepcopy(now)
            for fld in [x for x in log["fields"] if x["file"] == f]:
                it = [i for i in restored["items"] if i["url"] == fld["itemUrl"]]
                self.assertEqual(len(it), 1)
                holder, key = _field(it[0], fld["field"])
                self.assertEqual(holder[key], fld["after"], "the log's 'after' text is what the report says now")
                holder[key] = fld["before"]
            self.assertEqual(restored, base, f)

    def test_every_logged_correction_is_consistent_with_its_field_history(self):
        log = corrections_log()
        self.assertEqual(len(log["corrections"]), 33)
        as_text = lambda v: v if isinstance(v, str) else " | ".join(v)       # a list field (limitations) is compared as its joined text
        for c in log["corrections"]:
            fld = [x for x in log["fields"] if x["file"] == c["file"] and x["itemUrl"] == c["itemUrl"] and x["field"] == c["field"]]
            self.assertEqual(len(fld), 1, c["id"])
            self.assertEqual(as_text(fld[0]["before"]).count(c["original"]), 1, c["id"])                  # the original passage was in the published text exactly once
            if c["corrected"]:
                self.assertEqual(as_text(fld[0]["after"]).count(c["corrected"]), 1, c["id"])
            self.assertNotIn(c["original"], as_text(fld[0]["after"]).replace(c["corrected"], "") if c["corrected"] else as_text(fld[0]["after"]), c["id"])   # and is gone now
            self.assertIn(c["original"].strip()[:60], c["noteText"], c["id"])                     # the note quotes the original wording
            self.assertTrue(c["reason"] and c["sourceLabel"] and c["itemUrl"].startswith("https://"), c["id"])
        self.assertEqual(len({c["id"] for c in log["corrections"]}), 33)

    def test_no_correction_introduces_a_priority_novelty_or_authority_claim(self):
        bad = re.compile(r"\b(first|novel|novelty|largest|senior|well[- ]established|long-standing|under-?studied|coin flip|no better than chance|long-contested|unprecedented|pioneering)\b", re.I)
        for c in corrections_log()["corrections"]:
            self.assertIsNone(bad.search(c["corrected"]), (c["id"], c["corrected"]))


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
        log = json.loads(read("data/corrections-log.json"))
        a = self.text("about.html")
        self.assertGreaterEqual(len(evidence["itemsWithClaimsTheAbstractDoesNotMake"]), 1)       # "statements that the source does not make" is evidence-bound
        self.assertNotEqual(evidence["fdaItem"]["publishedDecisionDate"], evidence["fdaItem"]["officialDecisionDate"])   # "one incorrect date"
        self.assertIn("one incorrect date", a)
        self.assertNotIn("incorrect numbers", a)                                # the check found paraphrased or derived numbers, not wrong ones
        # "They were corrected" is only true if every item the check flagged was corrected or explicitly cleared in the log
        self.assertIn("They were corrected, and each correction is shown under the item it changes", a)
        self.assertNotIn("we are preparing corrections", a)
        res = log["flags"]["resolution"]
        self.assertEqual(sorted(res), sorted(evidence["reviewFlaggedPmids"]))
        self.assertIn("an item without a correction note has not been verified", a)      # the honest limit stays next to the claim

    def test_every_review_flag_is_resolved_by_a_correction_or_explicitly_withdrawn_with_a_justification(self):
        evidence = json.loads(read("engine/tests/fixtures/september-review-evidence.json"))
        log = corrections_log()
        ids = {c["id"] for c in log["corrections"]}
        res = log["flags"]["resolution"]
        self.assertEqual(len(evidence["reviewFlaggedPmids"]), 11)
        for pmid in evidence["reviewFlaggedPmids"]:
            r = res[pmid]
            if r.get("withdrawn"):
                self.assertGreater(len(r["justification"]), 80, pmid)                    # a documented reason, not a bare withdrawal
                self.assertNotIn("resolvedBy", r)
            else:
                self.assertTrue(r["resolvedBy"] and set(r["resolvedBy"]) <= ids, pmid)
                for cid in r["resolvedBy"]:
                    self.assertIn(pmid, [c for c in log["corrections"] if c["id"] == cid][0]["itemUrl"])   # the correction really is on that item
        self.assertEqual([w["pmid"] for w in log["flags"]["withdrawn"]], ["42710361"])
        self.assertIn("has not yet been evaluated in individuals with tinnitus", log["flags"]["withdrawn"][0]["justification"])
        js = read("js/app.js")
        self.assertNotIn("REVIEW_FLAG", js); self.assertNotIn("review-flag", js); self.assertNotIn("Review flag", js)      # no unresolved flag can be shown

    def test_the_clarification_is_exactly_the_approved_text_on_exactly_the_reports_that_made_the_quiet_statement(self):
        js = read("js/app.js")
        approved = ("This report previously stated that no evidence-changing tinnitus research was identified. However, automated evaluation was not completed for any of the records collected. "
                    "Therefore, this statement should not be interpreted as confirmation that no relevant research was found.")
        self.assertIn(approved, js)
        self.assertIn("<strong>Important clarification:</strong>", js)
        dates = re.findall(r"'(\d{4}-\d\d-\d\d)'", re.search(r"const QUIET = \{\s*dates: \[([^\]]*)\]", js).group(1))
        quiet = []
        for r in json.loads(read("data/weekly/index.json"))["reports"]:
            items = json.loads(read("data/weekly/" + r["file"]))["items"]
            if any("No evidence-changing" in (i.get("title") or "") for i in items):
                quiet.append(r["date"])
        self.assertEqual(sorted(dates), sorted(quiet))                                         # every report that made the statement, and no other
        self.assertEqual(sorted(dates), ["2026-09-04", "2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"])
        evidence = json.loads(read("engine/tests/fixtures/september-review-evidence.json"))["quietReports"]
        for d in dates:
            self.assertEqual(evidence[d]["evaluated"], 0, d)                                    # the clarified statement is true of each: evaluation was not completed
            self.assertGreater(evidence[d]["awaitingEvaluation"], 0, d)
        self.assertIn('<span class="small muted">— clarification added</span>', js)                  # visible in the archive list too

    def test_the_fda_date_correction_matches_the_primary_source_and_keeps_the_original_wording_in_the_log(self):
        js = read("js/app.js")
        fda = json.loads(read("engine/tests/fixtures/september-review-evidence.json"))["fdaItem"]
        log = corrections_log()
        self.assertEqual(fda["primarySourceDecisionDate"], fda["officialDecisionDate"])         # the FDA page and the API agree
        self.assertNotEqual(fda["publishedDecisionDate"], fda["primarySourceDecisionDate"])
        c8 = [c for c in log["corrections"] if c["id"] == "C8"][0]
        self.assertEqual(c8["itemUrl"], fda["primarySource"])
        self.assertIn(fda["publishedDecisionDate"], c8["original"])                              # the wrong date is kept in the history...
        self.assertIn("on " + fda["primarySourceDecisionDate"], c8["corrected"])                  # ...and the FDA's date is what the item says now
        self.assertNotIn("2026-09-04", c8["corrected"])
        self.assertEqual(c8["sourceLabel"], "FDA 510(k) Premarket Notification database, K260413")
        self.assertIn("08/13/2026", c8["reason"]); self.assertIn("02/09/2026", c8["reason"])
        self.assertNotIn("entered the weekly scan", c8["corrected"])                              # a clause no surviving record supports is not published
        rep = json.loads(read("data/weekly/2026-09-07.json"))
        item = [i for i in rep["items"] if i.get("url") == fda["primarySource"]]
        self.assertEqual(len(item), 1)
        self.assertIn("on " + fda["primarySourceDecisionDate"], item[0]["summary"]); self.assertNotIn(fda["publishedDecisionDate"], item[0]["summary"])
        self.assertIn('Source: <a href="${esc(it.url)}" rel="noopener" target="_blank">', js)    # the source is a working link
        self.assertIn("Correction (added October 2026):", js)
        self.assertEqual([c["id"] for c in log["corrections"] if c["reportDate"] == "2026-09-07"], ["C8", "R1a", "R1b", "R6"])      # the FDA correction plus the final-round corrections to two other items in that report

    def test_the_four_further_corrections_rest_on_the_papers_full_text_and_do_not_generalise(self):
        q = {k: v["quote"] for k, v in json.loads(read("engine/tests/fixtures/full-text-quotes-23oct.json")).items() if k != "note"}
        by = {c["id"]: c for c in corrections_log()["corrections"]}
        # Siemens Healthineers co-funded the MRI scans: the funding line says so and no longer claims there was no manufacturer involvement
        self.assertIn("Siemens Healthineers", q["ship_funding"])
        n5 = by["N5"]["corrected"]
        self.assertIn("MRI scans in the cohort were supported by a joint grant from Siemens Healthineers", n5)
        self.assertIn("Federal State of Mecklenburg-West Pomerania", n5)
        self.assertIn("no device or drug manufacturer involvement", by["N5"]["original"]); self.assertNotIn("no device or drug manufacturer involvement", n5)
        self.assertTrue(n5.startswith("unclear / manufacturer-linked"), n5)                      # not labelled "independent" any more
        # the questionnaire list includes the mTQ
        self.assertIn("(mTQ)", q["icf_questionnaires"])
        self.assertIn("mini-TQ variants", by["N6"]["original"]); self.assertNotIn("mini-TQ", by["N6"]["corrected"])
        # the periodontal "new association" claim is gone; the paper cites earlier associations
        self.assertIn("Previous observational studies have reported associations", q["periodontal_prior_studies"])
        self.assertIn("new candidate risk-factor association", by["N7"]["original"]); self.assertNotIn("new", by["N7"]["corrected"].lower())
        # donepezil: dropouts and dropouts because of side effects are stated separately, per group, exactly as the paper gives them, and are not generalised
        flow = q["donepezil_flow"]
        for fact in ("14 individuals (40%) in the active drug group dropped out, 13 due to side effects", "9 individuals (25.7%) were excluded: 5 due to side effects", "(p = 0.006)"):
            self.assertIn(fact, flow)
        self.assertIn("35 in the donepezil group and 35 in the placebo group", q["donepezil_allocation"])
        for fact in ("14 of the 35 participants allocated to donepezil (40%) dropped out, 13 of them because of side effects", "9 of the 35 allocated to placebo (25.7%) dropped out or were excluded, 5 of them because of side effects", "p = 0.006", "These figures describe this trial only"):
            self.assertIn(fact, by["N8a"]["corrected"])
        self.assertTrue(by["N8a"]["corrected"].startswith("The abstract does not report adverse events."))
        for fact in ("14 of 35 participants on donepezil dropped out (13 for side effects)", "9 of 35 on placebo dropped out or were excluded (5 for side effects)", "insomnia 5/35, nausea 3/35 and epigastralgia 3/35 on donepezil against 0/35, 0/35 and 1/35 on placebo", "These figures describe this trial only"):
            self.assertIn(fact, by["N8b"]["corrected"])
        for fact in ("Insomnia 5 (14.3) 0 (0)", "Nausea 3 (8.6) 0 (0)", "Epigastralgia 3 (8.6) 1 (2.9)"):
            self.assertIn(fact, q["donepezil_table1"])
        for cid in ("N8a", "N8b"):
            self.assertNotRegex(by[cid]["corrected"], r"(?i)\b(causes?|is unsafe|dangerous|should (not )?(take|use|avoid)|all patients|in general|usually)\b")      # no claim beyond the study
        self.assertNotIn("known cholinergic side-effect profile", by["N8b"]["corrected"])        # the outside-knowledge list is gone

    def test_the_notice_says_that_not_reported_refers_to_the_abstract_unless_the_full_paper_was_checked(self):
        js = read("js/app.js"); worker = read("ask-worker/worker.js")
        self.assertIn("refers to the study\\'s abstract, which these summaries were written from; the full paper may report it, unless a correction note says the full paper was also checked", js)
        self.assertIn("refers to the study's abstract, which these summaries were written from; the full paper may report it, unless a correction note says the full paper was also checked", worker)
        for cid in ("N8a", "N8b"):
            self.assertIn("Full paper checked", [c for c in corrections_log()["corrections"] if c["id"] == cid][0]["reason"])      # the notes that did check the full paper say so

    def test_the_final_round_corrections_r1_to_r6_rest_on_the_sources_and_leave_nothing_stale(self):
        q = {k: v["quote"] for k, v in json.loads(read("engine/tests/fixtures/source-quotes-24oct.json")).items() if k != "note"}
        log = corrections_log()
        by = {c["id"]: c for c in log["corrections"]}
        fields = {(f["itemUrl"], f["field"]): f for f in log["fields"]}
        self.assertEqual([c["id"] for c in log["corrections"]][-8:], ["R1a", "R1b", "R2a", "R2b", "R3", "R4", "R5", "R6"])
        def after(cid): return fields[(by[cid]["itemUrl"], by[cid]["field"])]["after"]
        # R1, R2: the papers declare no competing interests and no funding, so the "no statement in the record" claims are gone
        self.assertIn("declare that no financial support was received", q["R1_funding_fulltext"]); self.assertIn("no known competing", q["R1_coi_record"])
        self.assertIn("received no specific grant", q["R2_grant_fulltext"]); self.assertIn("declare no conflicts of interest", q["R2_coi_record"])
        for cid, lab in (("R1a", "independent"), ("R2a", "independent")):
            self.assertTrue(by[cid]["corrected"].startswith(lab), cid)
            self.assertNotIn("no funding", by[cid]["corrected"].lower()); self.assertNotIn("in the available record", by[cid]["corrected"])
        self.assertIn("no financial support was received", by["R1a"]["corrected"]); self.assertIn("received no specific grant", by["R2a"]["corrected"])
        self.assertNotIn(by["R1b"]["original"], after("R1b"))                                    # the whole limitation line is gone
        self.assertNotIn("not stated in the available record", " ".join(after("R2b")))
        self.assertEqual(by["R1b"]["corrected"], "")
        # R3: an odds ratio is not a likelihood
        self.assertIn("aOR = 2.55", q["R3_abstract"]); self.assertIn("2.5 times higher adjusted odds", q["R3_fulltext"])
        self.assertIn("2.5 times the odds", by["R3"]["corrected"]); self.assertIn("adjusted odds ratio 2.55", by["R3"]["corrected"])
        self.assertNotIn("more likely", by["R3"]["corrected"]); self.assertNotIn("more likely to fall", after("R3"))
        # R4: one department, not two centres
        self.assertIn("in the Department of Otorhinolaryngology at Navodaya Medical College and Hospital", q["R4_abstract"])
        self.assertEqual(by["R4"]["corrected"], "from one Indian department"); self.assertNotIn("centres", after("R4"))
        # R5: the veterans study has 165 controls
        self.assertIn("young non-Veteran controls with minimal noise exposure", q["R5_abstract"]); self.assertIn("165", q["R5_abstract_n"])
        self.assertEqual(after("R5"), "Young non-Veteran controls with minimal noise exposure (n=165)")
        # R6: a national survey analysis, not a cohort (and no label the abstract does not use)
        self.assertIn("Data were drawn from the 8th (2020) and 9th (2022) Korea National Health and Nutrition Examination Survey", q["R6_abstract"])
        self.assertEqual(after("R6"), "national health survey analysis (2020 and 2022 survey waves)")
        self.assertNotIn("cohort", after("R6")); self.assertNotIn("cross-sectional", after("R6"))
        for cid in ("R1a", "R1b", "R2a", "R2b", "R3", "R4", "R5", "R6"):
            self.assertGreater(len(by[cid]["reason"]), 40, cid)

    def test_the_ask_worker_cannot_say_nothing_was_found_and_relays_the_notices(self):
        import shutil, subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not installed here; tools/ask_core_test.mjs runs in the Ask benchmark workflow")
        r = subprocess.run([node, "tools/ask_core_test.mjs"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-1000:])
        self.assertRegex(r.stdout, r"\d+ passed, 0 failed")
        worker = read("ask-worker/worker.js")
        self.assertNotIn("honest quiet week", worker)                                          # the instruction that made "quiet week" the answer
        self.assertNotIn("IS the answer", worker)

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
