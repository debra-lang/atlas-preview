"""The watched feeds must actually read real feed formats, report what each one offered, and hand recovered items to the normal review and protection process. Fixtures are written to match the structure of the live feeds (FDA and NIH RSS 2.0, Nature RSS 1.0), with invented content. No network.
Run:  python -m unittest discover -s engine/tests -v"""
import io, json, shutil, subprocess, sys, tempfile, unittest
from datetime import date, timedelta
from email.utils import format_datetime
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ENGINE, pubmed_item, run_scenario   # noqa: E402
from cycle_sandbox import HOLDS, KNOWN, LISTINGS, PAUSED, QUEUE, SOURCES, STATUS, TODAY, Sandbox, W   # noqa: E402

import weekly_scan   # noqa: E402

CUTOFF = date.today() - timedelta(days=20)
FEED = {"name": "FDA MedWatch safety alerts", "kind": "regulatory", "filter": ["tinnitus", "hearing", "ototoxic", "cochlear"], "url": "https://feeds.invalid/medwatch"}


def rfc(days_ago):
    return format_datetime(datetime.now(timezone.utc) - timedelta(days=days_ago))


def rss2(*items):
    return ('<?xml version="1.0" encoding="utf-8"?><rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0"><channel><title>Feed</title>' + "".join(items) + "</channel></rss>").encode("utf-8")


def item(title="Hearing aid recall: a device issue", desc="Details of the alert.", link="https://www.fda.gov/safety/alert-1", pub=None):
    t = "" if title is None else f"<title>{title}</title>"
    return f"<item>{t}<link>{link}</link><description>{desc}</description><pubDate>{pub or rfc(2)}</pubDate><dc:creator>FDA</dc:creator><guid isPermaLink=\"false\">a1</guid></item>"


def rss1(title="Tinnitus network study", when=None):
    return f'''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel rdf:about="https://www.nature.com/srep"><title>Scientific Reports</title></channel>
<item rdf:about="https://www.nature.com/articles/s1"><title><![CDATA[{title}]]></title><link>https://www.nature.com/articles/s1</link><content:encoded><![CDATA[<p>Scientific Reports, Published online: 2 November; <a href="x">doi</a></p>{title}]]></content:encoded><dc:title><![CDATA[{title}]]></dc:title><dc:creator>A. Author</dc:creator><dc:date>{when or (date.today() - timedelta(days=1)).isoformat()}</dc:date></item>
</rdf:RDF>'''.encode("utf-8")


def atom(body):
    return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>F</title>{body}</feed>'.encode("utf-8")


def parse(raw, feed=FEED):
    return weekly_scan.parse_feed(raw, feed, CUTOFF)[:2]


class TheOriginalDefects(unittest.TestCase):
    def test_an_ordinary_title_with_no_child_elements_is_read(self):
        """The first defect: `find(a) or find(b)` treats an element with no children as false, so every ordinary RSS title read as empty and the filter dropped every item."""
        items, n = parse(rss2(item()))
        self.assertEqual(n, 1)
        self.assertEqual(items[0]["title"], "Hearing aid recall: a device issue")

    def test_a_namespaced_rss_1_feed_is_found(self):
        """The second defect: Nature's feeds are RSS 1.0 in a namespace, so looking for a plain item found no entries at all."""
        items, n = parse(rss1(), {**FEED, "filter": ["tinnitus"], "kind": "study", "name": "Scientific Reports"})
        self.assertEqual(n, 1)
        self.assertEqual(items[0]["title"], "Tinnitus network study")
        self.assertEqual(items[0]["url"], "https://www.nature.com/articles/s1")
        self.assertEqual(items[0]["kind"], "study")
        self.assertEqual(items[0]["date"], (date.today() - timedelta(days=1)).isoformat())

    def test_the_month_first_date_nih_uses_is_read(self):
        """The third defect: NIH's dates look like 'Fri, 10/23/2026 - 13:00' and could not be read, so items from NIH would have had no date and escaped the window."""
        d = date.today() - timedelta(days=3)
        items, _ = parse(rss2(item(pub=f"Fri, {d.month:02d}/{d.day:02d}/{d.year} - 13:00\n")))
        self.assertEqual(items[0]["date"], d.isoformat())
        old = date.today() - timedelta(days=40)
        self.assertEqual(parse(rss2(item(pub=f"Fri, {old.month:02d}/{old.day:02d}/{old.year} - 13:00")))[0], [])


class RealWorldStructures(unittest.TestCase):
    def test_atom_with_several_links(self):
        items, n = parse(atom(f'<entry><title>Cochlear device update</title><link rel="self" href="https://x.invalid/self"/><link rel="alternate" href="https://x.invalid/page"/><updated>{date.today().isoformat()}T00:00:00Z</updated><summary>Text</summary></entry>'))
        self.assertEqual((n, items[0]["url"]), (1, "https://x.invalid/page"))

    def test_atom_with_a_link_lacking_rel_and_html_content(self):
        items, _ = parse(atom(f'<entry><title type="html">&lt;b&gt;Hearing&lt;/b&gt; alert</title><link href="https://x.invalid/a"/><published>{date.today().isoformat()}T00:00:00Z</published><content type="html">&lt;p&gt;Body&lt;/p&gt;</content></entry>'))
        self.assertEqual(items[0]["url"], "https://x.invalid/a")
        self.assertIn("Body", items[0]["summary"])
        self.assertIn("alert", items[0]["title"])

    def test_cdata_entities_and_nested_markup_in_a_title(self):
        for raw, want in (("<![CDATA[Hearing loss & a drug]]>", "Hearing loss & a drug"), ("Hearing loss &amp; a drug", "Hearing loss & a drug"), ("<b>Hearing</b> loss <i>alert</i>", "Hearing loss alert"), ("  Hearing \n loss  ", "Hearing loss")):
            with self.subTest(raw=raw):
                self.assertEqual(parse(rss2(item(title=raw)))[0][0]["title"], want)

    def test_description_markup_is_stripped_and_cut(self):
        items, _ = parse(rss2(item(desc="&lt;p&gt;" + "hearing " * 200 + "&lt;/p&gt;")))
        self.assertNotIn("<p>", items[0]["summary"])
        self.assertLessEqual(len(items[0]["summary"]), 400)

    def test_rss_1_with_a_plain_description(self):
        raw = b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns="http://purl.org/rss/1.0/"><item><title>A tinnitus item</title><link>u</link><description>Text</description></item></rdf:RDF>'
        items, n = parse(raw)
        self.assertEqual((n, items[0]["summary"]), (1, "Text"))


class MissingOrMalformedTitles(unittest.TestCase):
    def test_a_relevant_item_with_no_title_is_kept_not_dropped(self):
        for title in (None, "", "   ", "<![CDATA[]]>"):
            with self.subTest(title=title):
                items, _ = parse(rss2(item(title=title, desc="A hearing loss safety alert for a drug.")))
                self.assertEqual(len(items), 1)
                self.assertIn("hearing loss safety alert", items[0]["title"])
                self.assertTrue(items[0]["id"].startswith("feed-"))

    def test_an_untitled_undescribed_item_can_be_kept_only_from_an_always_relevant_feed(self):
        self.assertEqual(parse(rss2(item(title=None, desc="")))[0], [])
        items, _ = parse(rss2(item(title=None, desc="")), {**FEED, "alwaysRelevant": True})
        self.assertEqual(items[0]["title"], "Untitled item from FDA MedWatch safety alerts")

    def test_a_title_with_double_escaped_entities_is_read(self):
        self.assertEqual(parse(rss2(item(title="Hearing &amp;amp; balance alert")))[0][0]["title"], "Hearing & balance alert")

    def test_malformed_xml_raises_for_the_scanner_to_report(self):
        for raw in (b"<rss><channel><item><title>Unclosed", b"", b"not xml", b"<html><body><p>Temporarily<br>unavailable</body></html>"):
            with self.subTest(raw=raw[:12]):
                with self.assertRaises(Exception):
                    parse(raw)


class StableIds(unittest.TestCase):
    """The same alert must not queue again because its address changed. known_ids stops a repeat only if the id holds still."""

    def one(self, **k):
        return parse(rss2(item(**k)))[0][0]["id"]

    def test_tracking_parameters_scheme_www_and_a_trailing_slash_do_not_change_the_id(self):
        base = self.one(link="https://www.fda.gov/safety/a1")
        for link in ("https://www.fda.gov/safety/a1?utm_source=rss", "https://www.fda.gov/safety/a1?utm_campaign=x&amp;utm_medium=y", "http://www.fda.gov/safety/a1", "https://fda.gov/safety/a1", "https://www.fda.gov/safety/a1/", "https://WWW.FDA.GOV/safety/a1"):
            with self.subTest(link=link):
                raw = rss2(f"<item><title>Hearing aid recall</title><link>{link}</link><pubDate>{rfc(2)}</pubDate></item>")
                ref = rss2(f"<item><title>Hearing aid recall</title><link>https://www.fda.gov/safety/a1</link><pubDate>{rfc(2)}</pubDate></item>")
                self.assertEqual(parse(raw)[0][0]["id"], parse(ref)[0][0]["id"])
        self.assertTrue(base.startswith("feed-fda-medwatch-safety-alerts-"))

    def test_a_meaningful_query_still_makes_a_different_id(self):
        a = rss2(f"<item><title>Hearing a</title><link>https://x.invalid/alert?id=1</link><pubDate>{rfc(2)}</pubDate></item>")
        b = rss2(f"<item><title>Hearing a</title><link>https://x.invalid/alert?id=2</link><pubDate>{rfc(2)}</pubDate></item>")
        self.assertNotEqual(parse(a)[0][0]["id"], parse(b)[0][0]["id"])

    def test_an_edited_title_is_the_same_item(self):
        def x(title):
            return rss2(f'<item><title>{title}</title><link>https://a.invalid/1</link><guid isPermaLink="false">node-77</guid><pubDate>{rfc(2)}</pubDate></item>')
        self.assertEqual(parse(x("Hearing alert"))[0][0]["id"], parse(x("Hearing alert, updated"))[0][0]["id"])

    def test_a_feed_reusing_one_id_for_every_item_does_not_lose_alerts(self):
        """A known id is skipped for good, so two different alerts must never share one."""
        def x(link):
            return rss2(f'<item><title>Hearing alert</title><link>{link}</link><guid isPermaLink="false">same</guid><pubDate>{rfc(2)}</pubDate></item>')
        self.assertNotEqual(parse(x("https://a.invalid/1"))[0][0]["id"], parse(x("https://a.invalid/2"))[0][0]["id"])

    def test_addresses_that_differ_only_in_a_blank_value_a_bare_query_or_a_fragment_are_different(self):
        def x(link):
            return parse(rss2(f"<item><title>Hearing a</title><link>{link}</link><pubDate>{rfc(2)}</pubDate></item>"))[0][0]["id"]
        self.assertNotEqual(x("https://a.invalid/p?123"), x("https://a.invalid/p?124"))
        self.assertNotEqual(x("https://a.invalid/p?id=&amp;a=1"), x("https://a.invalid/p?a=1"))
        self.assertNotEqual(x("https://a.invalid/app#/alert/1"), x("https://a.invalid/app#/alert/2"))

    def test_one_item_repeated_within_a_feed_is_kept_once(self):
        self.assertEqual(len(parse(rss2(item(), item()))[0]), 1)

    def test_the_hash_is_long_enough_that_ids_do_not_collide_by_chance(self):
        tail = self.one().rsplit("-", 1)[1]
        self.assertEqual(len(tail), 16)
        self.assertTrue(all(c in "0123456789abcdef" for c in tail))

    def test_long_addresses_that_differ_only_at_the_end_do_not_collide(self):
        stem = "https://www.fda.gov/safety/recalls-market-withdrawals-safety-alerts/" + "a-very-long-company-name-issues-voluntary-nationwide-recall-of-" * 3
        a = rss2(f"<item><title>Hearing one</title><link>{stem}first</link><pubDate>{rfc(2)}</pubDate></item>")
        b = rss2(f"<item><title>Hearing two</title><link>{stem}second</link><pubDate>{rfc(2)}</pubDate></item>")
        self.assertNotEqual(parse(a)[0][0]["id"], parse(b)[0][0]["id"])

    def test_an_item_with_no_link_or_id_is_identified_by_its_text(self):
        a = rss2("<item><description>A hearing alert</description></item>")
        self.assertEqual(parse(a)[0][0]["id"], parse(rss2("<item><description>A hearing alert</description></item>"))[0][0]["id"])
        self.assertNotEqual(parse(a)[0][0]["id"], parse(rss2("<item><description>Another hearing alert</description></item>"))[0][0]["id"])


class HostileOrOddContent(unittest.TestCase):
    def test_only_web_addresses_are_kept(self):
        for bad in ("javascript:alert(1)", "data:text/html,x", "file:///etc/passwd", "JaVaScRiPt:alert(1)"):
            self.assertEqual(parse(rss2(item(link=bad)))[0][0]["url"], "")
        self.assertEqual(parse(rss2(item(link="HTTPS://x.invalid/a")))[0][0]["url"], "HTTPS://x.invalid/a")

    def test_markup_in_a_title_does_not_survive(self):
        self.assertEqual(parse(rss2(item(title="Hearing &lt;script&gt;x&lt;/script&gt; alert")))[0][0]["title"], "Hearing x alert")

    def test_a_keyword_late_in_a_long_description_still_counts(self):
        items, _ = parse(rss2(item(title="A drug recall", desc="words " * 200 + "may cause hearing loss")))
        self.assertEqual(len(items), 1)
        self.assertLessEqual(len(items[0]["summary"]), 400)

    def test_one_bad_entry_does_not_cost_the_rest(self):
        for raw in (item(title="Hearing a", pub="+99999999999999999"), item(title="Hearing b", link="http://[bad/1")):
            with self.subTest(raw=raw[:50]):
                items, n, readable, bad = weekly_scan.parse_feed(rss2(raw, item(title="Hearing good", link="https://x.invalid/g")), FEED, CUTOFF)
                self.assertEqual(n, 2)
                self.assertIn("Hearing good", [i["title"] for i in items])


class OneBadEntry(unittest.TestCase):
    def test_an_unexpected_error_on_one_entry_is_counted_and_the_rest_are_kept(self):
        real, calls = weekly_scan._feed_id, [0]

        def fails_once(*a, **k):
            calls[0] += 1
            if calls[0] == 1:
                raise RuntimeError("an unexpected error on one entry")
            return real(*a, **k)
        weekly_scan._feed_id = fails_once
        self.addCleanup(setattr, weekly_scan, "_feed_id", real)
        items, n, readable, bad = weekly_scan.parse_feed(rss2(item(title="Hearing one", link="https://x.invalid/1"), item(title="Hearing two", link="https://x.invalid/2")), FEED, CUTOFF)
        self.assertEqual((n, bad, [i["title"] for i in items]), (2, 1, ["Hearing two"]))


class DatesAndFilters(unittest.TestCase):
    def test_a_feed_listing_oldest_first_does_not_lose_its_newest_item(self):
        old = "".join(item(title=f"Old hearing item {i}", link=f"https://x.invalid/{i}", pub=rfc(40)) for i in range(60))
        items, n = parse(rss2(old + item(title="New hearing alert", link="https://x.invalid/new", pub=rfc(1))))
        self.assertEqual(n, 61)
        self.assertEqual([i["title"] for i in items], ["New hearing alert"])

    def test_an_endless_feed_is_cut_off(self):
        many = "".join(item(title=f"Hearing item {i}", link=f"https://x.invalid/{i}") for i in range(600))
        self.assertEqual(len(parse(rss2(many))[0]), 500)

    def test_an_old_item_is_not_imported(self):
        self.assertEqual(parse(rss2(item(pub=rfc(40))))[0], [])

    def test_an_item_inside_the_window_is_kept(self):
        self.assertEqual(len(parse(rss2(item(pub=rfc(19))))[0]), 1)

    def test_an_undated_or_unreadable_date_is_kept_for_a_person(self):
        for pub in ("", "next Tuesday", "99/99/2026"):
            self.assertEqual(parse(rss2(f"<item><title>Hearing alert</title><link>u</link><pubDate>{pub}</pubDate></item>"))[0][0]["date"], "")

    def test_an_unrelated_item_is_filtered_out(self):
        items, n = parse(rss2(item(title="A glucose meter correction", desc="Unrelated.")))
        self.assertEqual((items, n), ([], 1))


class TheScanner(unittest.TestCase):
    def setUp(self):
        self.real = weekly_scan.urllib.request.urlopen, weekly_scan.ROOT
        self.addCleanup(lambda: (setattr(weekly_scan.urllib.request, "urlopen", self.real[0]), setattr(weekly_scan, "ROOT", self.real[1])))
        self.dir = Path(tempfile.mkdtemp(prefix="te-feed-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        (self.dir / "engine").mkdir()
        weekly_scan.ROOT = self.dir
        (self.dir / "engine/sources.json").write_text(json.dumps({"feeds": [{**FEED, "name": n, "url": f"https://feeds.invalid/{n}"} for n in ("A", "B", "C")], "newsIntel": [], "pages": []}), encoding="utf-8")

    def answers(self, table):
        class A(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def urlopen(req, timeout=None):
            v = table[req.full_url.rsplit("/", 1)[1]]
            if isinstance(v, Exception):
                raise v
            return A(v)
        weekly_scan.urllib.request.urlopen = urlopen

    def test_one_failing_feed_does_not_stop_the_others_and_each_is_reported(self):
        self.answers({"A": rss2(item()), "B": OSError("timed out"), "C": b"<rss><broken"})
        items = weekly_scan.scan_feeds()
        self.assertEqual(len(items), 1)
        r = {x["name"]: x for x in weekly_scan.FEED_REPORT}
        self.assertEqual((r["A"]["entries"], r["A"]["kept"], r["A"]["error"]), (1, 1, None))
        self.assertEqual(r["B"]["error"], "OSError")        # the kind of error only: the status is public, and an outside server's wording does not belong there
        self.assertTrue(r["C"]["error"])

    def test_a_feed_that_offers_no_entries_is_a_failure_not_a_quiet_week(self):
        self.answers({"A": rss2(), "B": rss2(item(title="Unrelated", desc="x")), "C": rss2()})
        weekly_scan.scan_feeds()
        r = {x["name"]: x for x in weekly_scan.FEED_REPORT}
        self.assertEqual(r["A"]["error"], "the feed answered with no entries")
        self.assertIsNone(r["B"]["error"])          # entries offered, none relevant: an ordinary result
        self.assertEqual(r["B"]["entries"], 1)

    def test_an_outside_servers_wording_never_reaches_the_status(self):
        import urllib.error
        self.answers({"A": urllib.error.HTTPError("https://x", 503, "<b>PLANTED server text</b>", {}, None), "B": rss2(item()), "C": rss2(item())})
        weekly_scan.scan_feeds()
        self.assertNotIn("PLANTED", json.dumps(weekly_scan.FEED_REPORT))
        self.assertEqual(weekly_scan.FEED_REPORT[0]["error"], "HTTPError 503")

    def test_a_feed_whose_entries_have_no_readable_text_is_a_failure(self):
        """The original fault from outside: entries found, nothing readable, nothing kept, no error."""
        self.answers({"A": rss2("<item><title></title><link>u</link></item>" * 3), "B": rss2(item()), "C": rss2(item())})
        weekly_scan.scan_feeds()
        self.assertEqual({x["name"]: x for x in weekly_scan.FEED_REPORT}["A"]["error"], "the feed's entries had no readable text")

    def test_the_real_configuration_still_names_the_five_feeds(self):
        d = json.loads((ENGINE / "sources.json").read_text(encoding="utf-8"))
        self.assertEqual(len(d["feeds"]), 5)
        self.assertTrue(any("MedWatch" in f["name"] for f in d["feeds"]))


class ThroughTheRealCycle(Sandbox):
    """Recovered items enter the normal process: queued for review, protected by holds and pauses, never published or listed by being found."""

    def setUp(self):
        super().setUp()
        W(self.root, SOURCES, {"feeds": [{**FEED, "url": "https://feeds.invalid/m"}, {"name": "NIH news releases", "kind": "study", "filter": ["tinnitus", "hearing"], "url": "https://feeds.invalid/n"}], "newsIntel": [{"name": "n", "query": "q"}], "pages": [{"name": "p", "url": "u"}]})
        self.real = weekly_scan.urllib.request.urlopen, weekly_scan.ROOT, weekly_scan.scan_feeds
        self.addCleanup(lambda: (setattr(weekly_scan.urllib.request, "urlopen", self.real[0]), setattr(weekly_scan, "ROOT", self.real[1])))
        weekly_scan.ROOT = self.root
        self.keep_real = ("scan_feeds",)
        self.table = {"m": rss2(item(title="Hearing aid recall: a device issue", link="https://www.fda.gov/safety/a1"), item(title="Old hearing alert", link="https://www.fda.gov/safety/old", pub=rfc(40))),
                      "n": rss2(item(title="Lenire stimulation for tinnitus reported", link="https://www.nih.gov/news/lenire"), item(title="NIH tinnitus study", link="https://www.nih.gov/news/t1"))}

        class A(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def urlopen(req, timeout=None):
            if isinstance(req, str) or "feeds.invalid" not in req.full_url:
                raise OSError("no network in this test")
            v = self.table[req.full_url.rsplit("/", 1)[1]]
            if isinstance(v, Exception):
                raise v
            return A(v)
        weekly_scan.urllib.request.urlopen = urlopen

    def J(self, rel):
        return json.loads((self.root / rel).read_text(encoding="utf-8"))

    def fid(self, title):
        return next(i["id"] for i in self.J(QUEUE)["items"] if i["title"] == title)

    def test_recovered_items_are_queued_not_published_not_listed(self):
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-400:])
        titles = {i["title"] for i in self.J(QUEUE)["items"]}
        self.assertIn("Hearing aid recall: a device issue", titles)
        self.assertIn("NIH tinnitus study", titles)
        report = json.dumps(self.J(f"data/weekly/{TODAY}.json"))
        self.assertNotIn("Hearing aid recall", report)
        self.assertNotIn("NIH tinnitus study", report)
        listed = json.dumps(self.J(LISTINGS))
        self.assertNotIn("Hearing aid recall", listed)
        self.assertNotIn("NIH tinnitus study", listed)
        self.assertNotIn("Lenire", listed)

    def test_a_news_item_linking_to_a_trial_does_not_stand_in_for_that_trial(self):
        trial = {"id": "ctgov-NCT99000123-2026-10-13", "kind": "trial", "title": "A tinnitus trial", "source": "ClinicalTrials.gov", "date": "2026-10-13", "url": "https://clinicaltrials.gov/study/NCT99000123", "summary": "Registry update - needs evaluation."}
        W(self.root, QUEUE, {"items": [trial]})
        W(self.root, KNOWN, [trial["id"]])
        W(self.root, PAUSED, {"ids": [], "emptyOnPurpose": True})
        self.table["n"] = rss2(item(title="NIH tinnitus trial news", link="https://clinicaltrials.gov/study/NCT99000123"))
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-300:])
        q = {i["id"]: i for i in self.J(QUEUE)["items"]}
        self.assertNotEqual((q[trial["id"]].get("listed") or {}).get("outcome"), "superseded")
        feed_item = next(i for i in q.values() if i["id"].startswith("feed-nih"))
        self.assertNotIn("listed", feed_item)

    def test_a_news_item_linking_to_a_trial_does_not_supersede_it_for_the_evaluator(self):
        import evaluate_queue
        trial = {"id": "ctgov-NCT99000123-2026-10-13", "date": "2026-10-13", "url": "https://clinicaltrials.gov/study/NCT99000123"}
        news = {"id": "feed-nih-abc", "date": "2026-11-01", "url": "https://clinicaltrials.gov/study/NCT99000123"}
        self.assertEqual(evaluate_queue.superseded_map([trial, news]), {})

    def test_nothing_older_than_the_window_is_imported(self):
        self.run_main()
        self.assertNotIn("Old hearing alert", {i["title"] for i in self.J(QUEUE)["items"]})

    def test_a_topic_hold_applies_to_a_recovered_item(self):
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-400:])
        self.assertIn("Lenire stimulation for tinnitus reported", {i["title"] for i in self.J(QUEUE)["items"]})
        self.assertGreaterEqual(self.J(STATUS)["evaluation"]["paused"], 2)    # the sandbox's paused record and this one
        self.assertNotIn("Lenire", json.dumps(self.J(f"data/weekly/{TODAY}.json")))

    def test_a_pause_applies_to_a_recovered_item_on_later_runs(self):
        self.run_main()
        fid = self.fid("Hearing aid recall: a device issue")
        W(self.root, PAUSED, {"ids": [fid]})
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out[-400:])
        self.assertIn(fid, {i["id"] for i in self.J(QUEUE)["items"]})

    def test_a_second_run_does_not_add_the_same_item_again(self):
        self.run_main()
        n = len(self.J(QUEUE)["items"])
        self.run_main()
        self.assertEqual(len(self.J(QUEUE)["items"]), n)
        self.assertEqual(len(self.J(KNOWN)), len(set(self.J(KNOWN))))

    def test_the_status_reports_each_feed(self):
        self.run_main()
        src = next(s for s in self.J(STATUS)["sources"] if s["name"].startswith("Watched feeds"))
        self.assertEqual({f["name"]: f["entries"] for f in src["feeds"]}, {FEED["name"]: 2, "NIH news releases": 2})
        self.assertIsNone(src["error"])

    def test_one_failed_feed_is_reported_and_the_run_stays_green(self):
        self.table["m"] = OSError("timed out")
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        st = self.J(STATUS)
        src = next(s for s in st["sources"] if s["name"].startswith("Watched feeds"))
        self.assertIn("1 of 2", src["error"])
        self.assertTrue(any("incomplete" in e for e in st["errors"]))
        self.assertEqual(self.health().returncode, 0)

    def test_every_feed_failing_turns_the_run_red(self):
        self.table = {"m": OSError("x"), "n": OSError("y")}
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        self.assertEqual(self.health().returncode, 1)

    def health(self):
        d = Path(tempfile.mkdtemp(prefix="te-feed-h-"))
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (d / "engine").mkdir()
        (d / "data").mkdir()
        shutil.copy(ENGINE / "check_evaluation_health.py", d / "engine")
        shutil.copy(self.root / STATUS, d / "data" / "engine-status.json")
        return subprocess.run([sys.executable, str(d / "engine/check_evaluation_health.py")], capture_output=True, text=True, encoding="utf-8", errors="replace")


class WithAStubbedAI(unittest.TestCase):
    """AI stays off in production. With a fake client, a recovered item takes the same gates as any other item."""
    FEED_ITEM = {"id": "feed-fda-medwatch-safety-alerts-https-www-fda-gov-a1", "kind": "regulatory", "title": "Hearing aid recall: a device issue", "source": "FDA MedWatch safety alerts", "date": "2026-11-01", "url": "https://www.fda.gov/safety/a1", "summary": "Details.", "treatment": "", "proposal": "", "why": ""}
    HELD_ITEM = {**FEED_ITEM, "id": "feed-nih-lenire", "title": "Lenire stimulation for tinnitus reported", "source": "NIH news releases", "url": "https://www.nih.gov/news/lenire", "kind": "study"}

    def test_staged_mode_publishes_nothing_and_never_sends_a_held_item_to_the_ai(self):
        r = run_scenario({"queue": [self.FEED_ITEM, self.HELD_ITEM], "settings": {"enabled": True, "mode": "staged", "limitPerRun": 10}, "topicHolds": json.loads((ENGINE / "topic_holds.json").read_text(encoding="utf-8"))["holds"], "runs": [{}]})["runs"][0]
        self.assertIn(self.FEED_ITEM["id"], r["staged"])
        self.assertNotIn(self.FEED_ITEM["id"], json.dumps(r["reportItems"]))
        self.assertNotIn("Hearing aid recall", json.dumps(r["reportItems"]))
        self.assertNotIn(self.HELD_ITEM["id"], r["apiCalls"])
        self.assertIn(self.HELD_ITEM["id"], r["queue"])
        self.assertTrue(r["ratingsUnchanged"])

    def test_with_ai_off_a_recovered_item_just_waits(self):
        r = run_scenario({"queue": [self.FEED_ITEM], "settings": {"enabled": False, "mode": "staged", "limitPerRun": 10}, "runs": [{}]})["runs"][0]
        self.assertEqual(r["totalApiCalls"], 0)
        self.assertIn(self.FEED_ITEM["id"], r["queue"])
        self.assertNotIn("Hearing aid recall", json.dumps(r["reportItems"]))


if __name__ == "__main__":
    unittest.main()
