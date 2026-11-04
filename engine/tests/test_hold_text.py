"""A hold reads the record's real text. The registry answer used to be checked as a JSON dump, where a line break is the two characters backslash and n, so a held name after a line break or a tab, past the compact text, read "nLenire", was not found, and the record could be listed publicly.
These go through the real fetch (only the network answer is stubbed) and the real hold check, with the real hold file; test_hold_cycle.py runs the whole cycle. Run:  python -m unittest discover -s engine/tests -v"""
import html, json, sys, unittest
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
                           ("an entity space", "&nbsp;Lenire"), ("an entity hyphen inside", " Le&shy;nire"), ("markup", "<b>Lenire</b>"), ("underscores for emphasis", "_Lenire_"), ("a written-out form feed", " \\fLenire"), ("a written-out vertical tab", " \\vLenire"), ("a written-out backspace", " \\bLenire"), ("markup inside the name", " Le<b>nire</b>"), ("a break after an accented name", " L\u00e9nire<br>device"), ("a footnote in markup after an accented name", " L&eacute;nire<sup>2</sup>"), ("a split name before a break", " Neuro\u200bmod<br>Devices"), ("a tag with no meaning inside the name", " Le<wbr>nire"), ("a superscript tag inside the name", " Le<sup>n</sup>ire"), ("a highlight inside the name", " Le<mark>nire</mark>"), ("a long tag inside the name", ' Le<span class="a-rather-long-class-name-that-goes-on-for-a-while">nire</span>'), ("a tag inside the trial name", "\nTENT-<wbr>A1"),
                           ("a hyphen at the end of a line", "\nTENT-\nA1"), ("a no-break hyphen at the end of a line", "\nTENT\u2011\nA1"), ("an en dash at the end of a line", "\nTENT\u2013\r\nB"), ("an encoded hyphen at the end of a line", "\nTENT&#8209;\nA"), ("an invisible character after the hyphen", "\nTENT-\u200b\nA"), ("a windows line end after a hyphen", "\nTENT-\r\nB"), ("an indented line after a hyphen", "\nTENT-\n   A1"), ("a minus sign at the end of a line", "\nTENT\u2212\nA1"), ("a hyphen bullet at the end of a line", "\nTENT\u2043\nA1"), ("a small hyphen at the end of a line", "\nTENT\ufe63\nA1"), ("a full-width hyphen at the end of a line", "\nTENT\uff0d\nA1"), ("a figure dash at the end of a line", "\nTENT\u2012\nA1"), ("a control character inside", " Le\x01nire"), ("an entity encoded twice", " &amp;#76;enire"),
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
                           ("capital dotted I", "\nLEN\u0130RE"), ("capitals", "\nLENIRE"), ("full-width letters", "\n\uff2c\uff45\uff4e\uff49\uff52\uff45"), ("no-break hyphen in the trial name", "\nTENT\u2011A1"), ("figure dash in the trial name", "\nTENT\u2012A1"), ("en dash in the trial name", "\nTENT\u2013B"),
                           ("no-break space after", "\nLenire\u00a0device"), ("no-break space before", "\u00a0Lenire"), ("thin space", "\u2009Lenire"), ("registered sign", "\nLenire\u00ae"), ("trade mark sign", "\nLenire\u2122"),
                           ("accent and trade mark sign", "\nL\u00e9nire\u2122"), ("soft hyphen and service mark", "\nLe\u00adnire\u2120"), ("full-width and trade mark sign", "\n\uff2c\uff45\uff4e\uff49\uff52\uff45\u2122"), ("accent and registered sign", "\nL\u00e9nire\u00ae"),
                           ("minus sign in the trial name", "\nTENT\u2212A1"), ("hyphen bullet in the trial name", "\nTENT\u2043A1"), ("footnote mark", "\nLenire\u00b9"), ("another footnote mark", "\nNeuromod\u00b2 Devices"), ("superscript digit", "\nLenire\u2075"), ("subscript digit", "\nLenire\u2082")):
            with self.subTest(name):
                self.assertEqual(self.check(self.with_description(tail)), "lenire-neuromod")


class NumericEntities(Base):
    """A decimal entity of more than 4300 digits used to make the check raise, and every listing stopped. It is taken out, and nothing near it is hidden."""

    def found(self, text):
        return topic_holds.match_item({"id": "x"}, self.holds, extra_text=text)

    def test_oversized_entities_do_not_raise(self):
        for name, text in (("just past the limit", "&#" + "9" * 4301 + ";"), ("far past it", "&#" + "9" * 100000 + ";"), ("no semicolon", "&#" + "9" * 5000), ("all zeros", "&#" + "0" * 5000 + ";"), ("twice encoded", "&amp;#" + "9" * 5000 + ";"), ("three times encoded", "&amp;amp;#" + "9" * 5000 + ";"), ("two together", "&#" + "9" * 5000 + ";&#" + "8" * 5000 + ";"), ("padded and oversized", "&#000" + "9" * 5000 + ";"), ("padded, oversized and twice encoded", "&amp;#000" + "9" * 5000 + ";"), ("hex", "&#x" + "9" * 5000 + ";"), ("in the middle of a word", "wo&#" + "9" * 5000 + ";rd")):
            with self.subTest(name):
                self.assertIsNone(self.found(text))

    def test_it_does_not_depend_on_where_python_sets_its_digit_limit(self):
        """The limit can be lowered by a setting, so the correction must not sit just under the default."""
        before = sys.get_int_max_str_digits()
        self.addCleanup(sys.set_int_max_str_digits, before)
        sys.set_int_max_str_digits(640)
        self.assertIsNone(self.found("&#" + "9" * 641 + ";"))
        self.assertEqual(self.found("&#" + "9" * 641 + "; Lenire"), "lenire-neuromod")

    def test_a_held_name_beside_one_is_still_found(self):
        huge = "&#" + "9" * 5000 + ";"
        for name, text in (("after", huge + " Lenire"), ("before", "Lenire " + huge), ("the next line", huge + "\nNeuromod"), ("no semicolon", "&#" + "9" * 5000 + " Lenire"), ("twice encoded", "&amp;#" + "9" * 5000 + "; Lenire"), ("needing the plain form", huge + " L\u00e9nire"), ("trial name", huge + " TENT-A1")):
            with self.subTest(name):
                self.assertEqual(self.found(text), "lenire-neuromod")

    def test_ordinary_entities_still_read(self):
        for name, text in (("a letter", "&#76;enire"), ("padded to seven digits", "&#0000076;enire"), ("padded to eight digits", "&#00000076;enire"), ("padded far past the digit limit", "&#" + "0" * 5000 + "76;enire"), ("padded and twice encoded", "&amp;#00000076;enire"), ("a padded soft hyphen inside", "Le&#00000173;nire"), ("a padded hyphen in the trial name", "TENT&#00000045;A1"), ("hex letter", "&#x4C;enire"), ("named accent", "L&eacute;nire"), ("twice encoded", "&amp;#76;enire")):
            with self.subTest(name):
                self.assertEqual(self.found(text), "lenire-neuromod")

    def test_padding_changes_nothing_about_what_a_reference_reads_as(self):
        for code in (1, 9, 10, 32, 45, 76, 173, 8209, 65279, 1114111):
            with self.subTest(code):
                plain = topic_holds._plain(f"x&#{code};y")
                for zeros in (1, 7, 12, 5000):
                    self.assertEqual(topic_holds._plain("x&#" + "0" * zeros + f"{code};y"), plain)

    def test_a_name_that_itself_needs_decoding_is_still_read_beside_an_oversized_one(self):
        """So the correction cannot be replaced by catching the error and leaving the text undecoded."""
        huge = "&#" + "9" * 5000 + ";"
        for name, text in (("an accent entity", huge + " L&eacute;nire"), ("a letter entity", huge + " &#76;enire"), ("a soft hyphen entity", huge + " Le&shy;nire")):
            with self.subTest(name):
                self.assertEqual(self.found(text), "lenire-neuromod")

    def test_what_replaces_one_keeps_the_words_apart(self):
        """In both directions: a name directly after one is still a whole word, and the digits' neighbours do not join into a name."""
        self.assertEqual(self.found("x&#99999999;L\u00e9nire"), "lenire-neuromod")
        self.assertIsNone(self.found("Le&#99999999;nire"))

    def test_the_longest_real_reference_reads_as_python_reads_it(self):
        for code in ("1114111", "9999999", "1000000"):
            with self.subTest(code):
                self.assertEqual(topic_holds._unescape(f"x&#{code};y"), html.unescape(f"x&#{code};y"))

    def test_malformed_entities_neither_raise_nor_hide_a_name(self):
        for bad in ("&#;", "&#x;", "&#abc;", "&#-1;", "&#0;", "&#1114112;", "&#xD800;", "&#xFFFFFFFF;", "&#", "&", "&;", "&nosuch;", "&#12345678;", "&#99999999;"):
            with self.subTest(bad):
                self.assertIsNone(self.found(bad))
                self.assertEqual(self.found(bad + " Le&#110;ire"), "lenire-neuromod")     # only the decoded text shows this name, so the text as written cannot answer for it

    def test_in_nested_record_fields_through_the_real_fetch(self):
        huge = "&#" + "9" * 5000 + ";"
        s = study()
        s["protocolSection"]["contactsLocationsModule"] = {"locations": [{"facility": huge}, {"facility": {"a": [huge, "\nLenire"]}}]}
        self.assertEqual(self.check(s), "lenire-neuromod")
        s["protocolSection"]["contactsLocationsModule"] = {"locations": [{"facility": huge}]}
        self.assertIsNone(self.check(s))


class TheItemFields(Base):
    """The check reads the title, the source and the summary as well as the record."""

    def test_each_field_is_read(self):
        for field in ("title", "source", "summary"):
            with self.subTest(field):
                self.assertEqual(topic_holds.match_item({"id": "x", field: "A study of\nLenire"}, self.holds), "lenire-neuromod")
                self.assertIsNone(topic_holds.match_item({"id": "x", field: "A study of neuromodulation"}, self.holds))


class EveryField(Base):
    def only_the_full_record_finds_it(self, s):
        """The compact text carries some fields too, so the question here is whether the reader of the full record finds it, with the compact text taken away."""
        return topic_holds.match_item({"id": "x"}, self.holds, extra_text=topic_holds.record_text(s))

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
                self.assertEqual(self.only_the_full_record_finds_it(s), "lenire-neuromod")

    def test_the_text_reader_itself_has_no_depth_limit(self):
        """A direct call, at a depth no real answer reaches: the JSON reader gives up first. test_hold_cycle.py covers what does arrive."""
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
                           ("after a real tab", "x\tent-A"), ("after a real line break, the n stays out", "x\neuromod"), ("the status words", "\nNOT_YET_RECRUITING"), ("a long dash is not a trial name", "\nin a tent\u2014a small one"), ("a hyphen and a space in a sentence", "\nin a tent- a small one"), ("another long dash", "\ntent\u2015B"), ("a trade mark sign after another word", "\nSolenire\u2122"), ("an entity that is not a name", "\n&amp; &lt;device&gt;"), ("accented other word", "\nL\u00e9nore")):
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

    def test_the_limit_on_how_long_a_tag_can_be(self):
        at = "Le<b " + "x" * 76 + ">nire"       # 80 characters after the tag's first letter
        over = "Le<b " + "x" * 90 + ">nire"
        self.assertEqual(topic_holds.match_item({"id": "x"}, self.holds, extra_text=at), "lenire-neuromod")
        self.assertIsNone(topic_holds.match_item({"id": "x"}, self.holds, extra_text=over))

    def test_a_long_comparison_does_not_hide_a_name_as_if_it_were_a_tag(self):
        self.assertEqual(topic_holds.match_item({"id": "x"}, self.holds, extra_text="x<y " + "word " * 30 + "L\u00e9nire z>w"), "lenire-neuromod")

    def test_a_sign_after_a_name_only_the_plain_form_shows_does_not_glue_onto_it(self):
        """Compatibility forms would turn the sign into letters or a digit. An encoded name has no text as written to fall back on."""
        for sign in ("\u2122", "\u00ae", "\u2120", "\u00b9"):
            with self.subTest(sign):
                self.assertEqual(topic_holds.match_item({"id": "x"}, self.holds, extra_text="Le&#110;ire" + sign), "lenire-neuromod")

    def test_known_limits_are_pinned_so_a_change_is_seen(self):
        """Over-holds: withheld, the safe direction. Misses: the same on production. Each is reported to the owner."""
        for text in ("a tent-\nA shelter", "Neuro</p><p>mod", "tent\u2013A", "a tent\u2013a thing", "tent-\u00c5", "Neuro<a b>mod", "neuromod_score"):
            with self.subTest(over_hold=text):
                self.assertEqual(topic_holds.match_item({"id": "x"}, self.holds, extra_text=text), "lenire-neuromod")
        for text in ("<L\u00e9nire>", "%20Lenire", "L\u0435nire"):
            with self.subTest(miss=text):
                self.assertIsNone(topic_holds.match_item({"id": "x"}, self.holds, extra_text=text))

    def test_a_name_only_the_text_as_written_shows_is_still_found(self):
        """The plain form sits beside the text as written, never instead of it: it reads a backslash and n as a line break, which would cut this name if it stood alone."""
        self.assertEqual(topic_holds.match_item({"id": "x"}, self.holds, extra_text="\\neuromod"), "lenire-neuromod")


if __name__ == "__main__":
    unittest.main()
