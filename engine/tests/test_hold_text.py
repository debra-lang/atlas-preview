"""A hold reads the record's real text. The registry answer used to be checked as a JSON dump, where a line break is the two characters backslash and n, so a held name after a line break or a tab, past the compact text, read "nLenire", was not found, and the record could be listed publicly.
Everything here goes through the real fetch (only the network answer is stubbed) and the real hold check, with the real hold file. Run:  python -m unittest discover -s engine/tests -v"""
import json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ENGINE   # noqa: E402
import evaluate_queue, topic_holds   # noqa: E402

NCT = "NCT99000777"
ITEM = {"id": f"ctgov-{NCT}-2026-10-13", "kind": "trial", "title": "A tinnitus trial of sound therapy", "source": "ClinicalTrials.gov", "date": "2026-10-13", "url": f"https://clinicaltrials.gov/study/{NCT}", "summary": "Registry update - needs evaluation."}
FILLER = " ".join(["word"] * 8000)     # long enough that the compact text does not reach what follows it


def study(**extra):
    s = {"protocolSection": {"identificationModule": {"nctId": NCT, "briefTitle": ITEM["title"], "officialTitle": ITEM["title"], "organization": {"fullName": "A University"}},
                             "statusModule": {"overallStatus": "RECRUITING", "lastUpdatePostDateStruct": {"date": "2026-10-13"}},
                             "sponsorCollaboratorsModule": {"leadSponsor": {"name": "A University"}},
                             "descriptionModule": {"briefSummary": "A study of tinnitus.", "detailedDescription": FILLER},
                             "conditionsModule": {"conditions": ["Tinnitus"]},
                             "designModule": {"studyType": "INTERVENTIONAL"}, "eligibilityModule": {"eligibilityCriteria": "Adults."},
                             "armsInterventionsModule": {"interventions": [{"name": "Sound therapy", "type": "BEHAVIORAL"}]}}, "derivedSection": {"miscInfoModule": {"versionHolder": "2026-11-01"}}, "hasResults": False}
    s.update(extra)
    return s


class Base(unittest.TestCase):
    def setUp(self):
        self.holds = topic_holds.load_holds(ENGINE / "topic_holds.json")
        self.addCleanup(setattr, evaluate_queue, "_get", evaluate_queue._get)
        evaluate_queue.RECORD_FULL.clear()
        evaluate_queue.RECORD_META.clear()

    def check(self, answer, item=ITEM):
        """What the listing step does: the real fetch, then the hold check on the compact text and the full record together."""
        evaluate_queue._get = lambda url, attempts=3: answer if isinstance(answer, bytes) else json.dumps(answer, ensure_ascii=False).encode("utf-8")
        text = evaluate_queue.fetch_context(dict(item))
        full = evaluate_queue.RECORD_FULL.pop(item["id"], "")
        self.assertNotIn("UNAVAILABLE", text.split("---")[0], "the record itself must have been accepted, or this test proves nothing")
        return topic_holds.match_item(item, self.holds, extra_text=text + "\n" + full)

    def with_description(self, tail):
        s = study()
        s["protocolSection"]["descriptionModule"]["detailedDescription"] = FILLER + tail
        return s


class LineBreaksAndEscapes(Base):
    def test_a_held_name_after_any_separator_past_the_compact_text_is_found(self):
        for name, tail in (("line break", "\nLenire device daily."), ("two line breaks", "\n\nLenire device daily."), ("windows line break", "\r\nLenire device."), ("tab", "\tLenire device."),
                           ("form feed", "\fLenire device."), ("vertical tab", "\vLenire device."), ("backspace character", "\bLenire device."), ("control character", "\x01Lenire device."),
                           ("line separator", "\u2028Lenire device."), ("paragraph separator", "\u2029Lenire device."), ("next line", "\x85Lenire device."),
                           ("the company after a break", "\nNeuromod Devices sponsors this."), ("the trial name after a tab", "\tTENT-A1 protocol"), ("a bullet", "\n* Lenire"),
                           ("quoted", ' the "Lenire" device'), ("a backslash", "\\Lenire"), ("a slash", "/Lenire"), ("already mid-sentence", " uses the Lenire device daily.")):
            with self.subTest(name):
                self.assertEqual(self.check(self.with_description(tail)), "lenire-neuromod")

    def test_escapes_stored_in_the_text_itself_are_read_through(self):
        for name, tail in (("a written-out line break", "\\nLenire"), ("a written-out tab", "\\tLenire"), ("a written-out unicode escape", "\\u00a0Lenire"), ("an entity quote", "\\&#39;Lenire\\&#39;"),
                           ("an entity space", "&nbsp;Lenire"), ("an entity hyphen inside", " Le&shy;nire"), ("markup", "<b>Lenire</b>"), ("underscores for emphasis", "_Lenire_"), ("markup inside the name", " Le<b>nire</b>"), ("a break after an accented name", " L\u00e9nire<br>device"), ("a footnote in markup after an accented name", " L&eacute;nire<sup>2</sup>"), ("a split name before a break", " Neuro\u200bmod<br>Devices"), ("a hyphen at the end of a line", "\nTENT-\nA1"), ("a windows line end after a hyphen", "\nTENT-\r\nB"), ("a control character inside", " Le\x01nire"), ("an entity encoded twice", " &amp;#76;enire"),
                           ("a written-out soft hyphen inside", " Le\\u00adnire"), ("a written-out zero-width space inside", " Le\\u200bnire"), ("a written-out letter", " \\u004cenire")):
            with self.subTest(name):
                self.assertEqual(self.check(self.with_description(tail)), "lenire-neuromod")

    def test_a_name_broken_across_lines_is_found(self):
        for tail in ("\nNeuromod\nDevices", " Neuromod\r\n   Devices", "\nNeuromod\tDevices", "\nNeuromod\u00a0Devices", "\nNeuromod\u2009Devices", "\nNeuromod\u2028Devices"):
            with self.subTest(tail):
                self.assertTrue(topic_holds.match_item({"id": "x"}, [{"id": "h", "patterns": ["\\bNeuromod Devices\\b"]}], extra_text=tail), "a pattern written with a plain space")
                self.assertEqual(self.check(self.with_description(tail)), "lenire-neuromod")


class UnicodeForms(Base):
    def test_other_forms_of_a_held_name_are_found(self):
        for name, tail in (("soft hyphen inside", "\nLe\u00adnire"), ("zero-width space inside", "\nLe\u200bnire"), ("zero-width joiner inside", "\nNeuro\u200dmod"), ("byte order mark before", "\n\ufeffLenire"), ("accent", "\nL\u00e9nire"), ("combining accent", "\nLe\u0301nire"),
                           ("capital dotted I", "\nLEN\u0130RE"), ("capitals", "\nLENIRE"), ("full-width letters", "\n\uff2c\uff45\uff4e\uff49\uff52\uff45"), ("no-break hyphen in the trial name", "\nTENT\u2011A1"), ("en dash in the trial name", "\nTENT\u2013B"),
                           ("no-break space after", "\nLenire\u00a0device"), ("no-break space before", "\u00a0Lenire"), ("thin space", "\u2009Lenire"), ("registered sign", "\nLenire\u00ae"), ("trade mark sign", "\nLenire\u2122"),
                           ("accent and trade mark sign", "\nL\u00e9nire\u2122"), ("soft hyphen and service mark", "\nLe\u00adnire\u2120"), ("full-width and trade mark sign", "\n\uff2c\uff45\uff4e\uff49\uff52\uff45\u2122"), ("accent and registered sign", "\nL\u00e9nire\u00ae"),
                           ("minus sign in the trial name", "\nTENT\u2212A1"), ("hyphen bullet in the trial name", "\nTENT\u2043A1"), ("footnote mark", "\nLenire\u00b9"), ("another footnote mark", "\nNeuromod\u00b2 Devices"), ("superscript digit", "\nLenire\u2075")):
            with self.subTest(name):
                self.assertEqual(self.check(self.with_description(tail)), "lenire-neuromod")


class EveryField(Base):
    def test_the_name_is_found_in_every_part_of_the_record(self):
        def at(*path, value="\nLenire device"):
            s = study()
            d = s
            for k in path[:-1]:
                d = d.setdefault(k, {})
            d[path[-1]] = value
            return s
        P = "protocolSection"
        for name, s in (("eligibility", at(P, "eligibilityModule", "eligibilityCriteria", value="Inclusion Criteria:\n\n* Adults\n\nExclusion Criteria:\n\nLenire users")),
                        ("a site, in a list, in an object", at(P, "contactsLocationsModule", "locations", value=[{"facility": "A", "city": "B"}, {"facility": "Clinic\nNeuromod", "city": "C"}])),
                        ("an intervention's other name", at(P, "armsInterventionsModule", "interventions", value=[{"name": "Device", "otherNames": ["Sound", "\tLenire"]}])),
                        ("an arm's description", at(P, "armsInterventionsModule", "armGroups", value=[{"label": "A", "description": "Uses\nTENT-C2"}])),
                        ("a collaborator", at(P, "sponsorCollaboratorsModule", "collaborators", value=[{"name": "\nNeuromod Devices"}])),
                        ("an outcome", at(P, "outcomesModule", "primaryOutcomes", value=[{"measure": "THI", "description": "\nwith Lenire"}])),
                        ("a reference", at(P, "referencesModule", "references", value=[{"citation": "Smith J.\nLenire trial. Lancet."}])),
                        ("a results contact", at("resultsSection", "moreInfoModule", "pointOfContact", value={"organization": "\nNeuromod Devices"})),
                        ("a results group", at("resultsSection", "participantFlowModule", "groups", value=[{"title": "G", "description": "Treated\nwith Lenire"}])),
                        ("the derived section", at("derivedSection", "interventionBrowseModule", "meshes", value=[{"term": "\nLenire"}])),
                        ("the document section", at("documentSection", "largeDocumentModule", "largeDocs", value=[{"label": "\nLenire"}])),
                        ("the annotation section", at("annotationSection", "annotationModule", "unpostedAnnotation", value={"note": "\nLenire"})),
                        ("a part the registry may add later", at("aNewSection", "aNewModule", "deep", value={"a": [{"b": [{"c": "\nLenire"}]}]}))):
            with self.subTest(name):
                self.assertEqual(self.check(s), "lenire-neuromod")

    def test_a_very_deep_record_is_still_read(self):
        d = "\nLenire"
        for _ in range(5000):
            d = [d]
        self.assertIn("Lenire", topic_holds.record_text({"a": d}))

    def test_the_text_reader_keeps_keys_numbers_and_order_and_skips_only_empty_values(self):
        self.assertEqual(topic_holds.record_text({"a": "x", "b": [1, 2.5, None, True, {"c": "y"}]}).split("\n"), ["a", "x", "b", "1", "2.5", "c", "y"])

    def test_a_pubmed_record_with_the_name_in_a_wrapped_line_is_found(self):
        raw = ("1. J Audiol. 2026 Oct;1(1):1-2.\n\nA tinnitus trial.\n\nSmith J(1).\n\nAuthor information:\n(1)A University.\n\n" + "Word " * 5000 + "\nNeuromod\nDevices funded this.\n\nDOI: 10.1/x\nPMID: 990701  [Indexed for MEDLINE]\n").encode("utf-8")
        it = {"id": "pubmed-990701", "kind": "study", "title": "A tinnitus trial.", "pubtypes": ["Journal Article"]}
        self.assertEqual(self.check(raw, it), "lenire-neuromod")
        self.holds = [{"id": "only-the-whole-name", "patterns": ["\\bNeuromod Devices\\b"]}]     # the one word alone would match above, and say nothing about the wrapped line
        self.assertEqual(self.check(raw, it), "only-the-whole-name")


class NoBroaderThanIntended(Base):
    def test_unrelated_words_and_names_are_not_held(self):
        for name, tail in (("neuromodulation", "\nNeuromodulation therapy"), ("neuromodulator", "\tneuromodulators"), ("a longer word", "\nLenires and Lenirea"), ("another word ending the same", "\nSolenire"),
                           ("a name split by a line break is a different text", "\nLe\nnire"), ("split by a space", "\nNeuro mod"), ("another trial letter", "\nTENT-D"), ("too many digits", "\nTENT-A12"), ("a word ending in tent", "\ncontent-A"),
                           ("after a real tab", "x\tent-A"), ("after a real line break, the n stays out", "x\neuromod"), ("the status words", "\nNOT_YET_RECRUITING"), ("a long dash is not a trial name", "\nin a tent\u2014a small one"), ("another long dash", "\ntent\u2015B"), ("a trade mark sign after another word", "\nSolenire\u2122"), ("an entity that is not a name", "\n&amp; &lt;device&gt;"), ("accented other word", "\nL\u00e9nore")):
            with self.subTest(name):
                self.assertIsNone(self.check(self.with_description(tail)))

    def test_a_clean_record_is_not_held(self):
        self.assertIsNone(self.check(study()))

    def test_a_record_with_every_kind_of_separator_and_no_held_name_is_not_held(self):
        self.assertIsNone(self.check(self.with_description("\n\n* An item\t- another\r\n\u2028more\u00a0text \u200b &#39;quoted&#39; \\* escaped")))

    def test_the_item_fields_are_read_the_same_way(self):
        for title in ("Le\u200bnire results", "TENT\u2011A follow-up", "A study of\nLenire"):
            with self.subTest(title):
                self.assertEqual(topic_holds.match_item({"id": "x", "title": title}, self.holds), "lenire-neuromod")
        self.assertIsNone(topic_holds.match_item({"id": "x", "title": "Neuromodulation for tinnitus"}, self.holds))

    def test_id_prefix_holds_still_work(self):
        self.assertEqual(topic_holds.match_item({"id": "newsintel-neuromod-lenire-abc", "title": "Unrelated"}, self.holds), "lenire-neuromod")

    def test_a_name_only_the_text_as_written_shows_is_still_found(self):
        """The plain form sits beside the text as written, never instead of it: the trade mark sign turns into the letters TM there, which would hide the name if it stood alone."""
        self.assertEqual(topic_holds.match_item({"id": "x"}, self.holds, extra_text="Lenire\u2122"), "lenire-neuromod")
        self.assertEqual(topic_holds.match_item({"id": "x"}, self.holds, extra_text="\\neuromod"), "lenire-neuromod")


if __name__ == "__main__":
    unittest.main()
