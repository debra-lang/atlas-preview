"""R4: an abstract that is not clearly English is held before any paid call. Offline. Texts are synthetic (written for these tests), in the pipeline's PubMed record format."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *   # noqa: E402,F401
import language_screen as L, registry_record  # noqa: E402

HEAD = "SOURCE: PubMed abstract record (NCBI efetch, text format)\nRECORD COMPLETENESS: COMPLETE - nothing was left out\nCRITICAL SECTIONS MISSING: no\n---\n"
EN = ("BACKGROUND: Tinnitus is a common symptom that affects the quality of life of many patients. METHODS: We enrolled 84 adults with chronic tinnitus in a randomised, "
      "double-blind trial and compared the active treatment with a placebo for twelve weeks. RESULTS: The mean score fell from 52.1 to 38.4 in the active group and from 51.8 to 49.2 in the placebo group "
      "(p = 0.01). CONCLUSIONS: The treatment was well tolerated and was associated with a modest improvement.")
FR = ("CONTEXTE : Les acouphènes sont un symptôme fréquent qui altère la qualité de vie des patients. MÉTHODES : Nous avons inclus 84 adultes présentant des acouphènes chroniques dans un essai "
      "randomisé en double aveugle et nous avons comparé le traitement actif avec un placebo pendant douze semaines. RÉSULTATS : Le score moyen a diminué de 52,1 à 38,4 dans le groupe actif, "
      "et de 51,8 à 49,2 dans le groupe placebo. CONCLUSIONS : Le traitement a été bien toléré dans cette étude.")
DE = ("HINTERGRUND: Tinnitus ist ein häufiges Symptom, das die Lebensqualität der Patienten beeinträchtigt. METHODEN: Wir haben 84 Erwachsene mit chronischem Tinnitus in eine randomisierte "
      "doppelblinde Studie eingeschlossen und die aktive Behandlung mit einem Placebo über zwölf Wochen verglichen. ERGEBNISSE: Der mittlere Wert sank in der aktiven Gruppe von 52,1 auf 38,4 und in der "
      "Placebogruppe von 51,8 auf 49,2. SCHLUSSFOLGERUNG: Die Behandlung wurde gut vertragen.")
ES = ("INTRODUCCIÓN: El tinnitus es un síntoma frecuente que afecta a la calidad de vida de los pacientes. MÉTODOS: Se incluyeron 84 adultos con tinnitus crónico en un ensayo aleatorizado "
      "doble ciego y se comparó el tratamiento activo con un placebo durante doce semanas. RESULTADOS: La puntuación media disminuyó de 52,1 a 38,4 en el grupo activo y de 51,8 a 49,2 en el grupo "
      "placebo. CONCLUSIONES: El tratamiento fue bien tolerado en este estudio.")
PT = ("INTRODUÇÃO: O zumbido é um sintoma frequente que afeta a qualidade de vida dos pacientes. MÉTODOS: Foram incluídos 84 adultos com zumbido crônico em um ensaio randomizado duplo-cego "
      "e o tratamento ativo foi comparado com um placebo durante doze semanas. RESULTADOS: A pontuação média diminuiu de 52,1 para 38,4 no grupo ativo e de 51,8 para 49,2 no grupo placebo. "
      "CONCLUSÕES: O tratamento foi bem tolerado e não houve eventos graves.")
IT = ("INTRODUZIONE: L'acufene è un sintomo frequente che peggiora la qualità della vita dei pazienti. METODI: Sono stati inclusi 84 adulti con acufene cronico in uno studio randomizzato "
      "in doppio cieco e il trattamento attivo è stato confrontato con un placebo per dodici settimane. RISULTATI: Il punteggio medio è sceso da 52,1 a 38,4 nel gruppo attivo e da 51,8 a 49,2 nel "
      "gruppo placebo. CONCLUSIONI: Il trattamento è stato ben tollerato.")
NL = ("ACHTERGROND: Tinnitus is een veelvoorkomend symptoom dat de kwaliteit van leven van patiënten vermindert. METHODEN: Wij includeerden 84 volwassenen met chronische tinnitus in een gerandomiseerde "
      "dubbelblinde studie en vergeleken de actieve behandeling met een placebo gedurende twaalf weken. RESULTATEN: De gemiddelde score daalde van 52,1 naar 38,4 in de actieve groep en van 51,8 naar 49,2 "
      "in de placebogroep. CONCLUSIE: De behandeling werd goed verdragen door de patiënten.")
ZH = "耳鸣是无明确相应外部声源时的声音感知，其发生与听觉信息在丘脑水平的加工处理过程密切相关。本研究纳入八十四例慢性耳鸣患者，随机分为两组，治疗十二周后比较两组的评分变化，结果显示治疗组评分明显下降。"
RU = ("Шум в ушах является частым симптомом, который снижает качество жизни пациентов. В исследование были включены 84 взрослых пациента с хроническим шумом в ушах, которые были "
      "рандомизированы в две группы и получали активное лечение или плацебо в течение двенадцати недель. Средний балл снизился в основной группе, различия были статистически значимыми.")
EL = ("Ο εμβοές είναι ένα συχνό σύμπτωμα που επηρεάζει την ποιότητα ζωής των ασθενών. Στη μελέτη συμπεριλήφθηκαν ογδόντα τέσσερις ενήλικες με χρόνιο εμβοές και συγκρίθηκε η ενεργή "
      "θεραπεία με εικονικό φάρμακο για δώδεκα εβδομάδες. Η μέση βαθμολογία μειώθηκε σημαντικά στην ομάδα της ενεργής θεραπείας.")
AUTH = ("Doe J(1), Müller K(2).\n\nAuthor information:\n(1)Klinik für Hals-, Nasen- und Ohrenheilkunde, Universitätsklinikum der Stadt, Berlin, Deutschland.\n"
        "(2)Département d'Oto-rhino-laryngologie, Hôpital de la Ville, Paris, France. Instituto de Otorrinolaringología, Madrid, España.\n\n")


def rec(*paras, marker="", title="[Effect of a treatment on tinnitus].", auth=AUTH, tail="DOI: 10.1000/x\nPMID: 123 [Indexed for MEDLINE]\n\nConflict of interest statement: none."):
    parts = ["1. J Test. 2026 Oct;1:1. doi: 10.1000/x.", title] + ([marker] if marker else []) + [auth.rstrip("\n")] + list(paras) + [tail]
    return HEAD + "\n\n".join(parts)


class Screen(unittest.TestCase):
    def test_clear_english_passes_even_with_foreign_names_in_the_author_block(self):
        s = L.screen(rec(EN))
        self.assertEqual((s["state"], s["hold"], s["translated"]), ("english", False, False))

    def test_each_latin_script_language_is_held_without_any_label(self):
        for name, txt in (("French", FR), ("German", DE), ("Spanish", ES), ("Portuguese", PT), ("Italian", IT), ("Dutch", NL)):
            s = L.screen(rec(txt))
            self.assertEqual((s["state"], s["hold"]), ("non_english", True), name)
            self.assertIn("R4", s["reason"])

    def test_other_scripts_are_held(self):
        for name, txt in (("Chinese", ZH), ("Russian", RU), ("Greek", EL)):
            self.assertTrue(L.screen(rec(txt))["hold"], name)
        self.assertEqual(L.screen(rec("Publisher: \n" + ZH))["state"], "non_english")             # the publisher-supplied abstract format seen on PubMed

    def test_english_plus_another_language_is_held_as_mixed(self):
        for other in (FR, ZH, ES):
            s = L.screen(rec(EN, other))
            self.assertEqual((s["state"], s["hold"]), ("mixed", True), other[:12])
        self.assertEqual(L.screen(rec(EN + " " + FR))["state"], "mixed")                          # both languages in ONE paragraph

    def test_a_translated_english_abstract_of_a_foreign_article_is_evaluated_but_flagged(self):
        for marker in ("[Article in German]", "[Article in German; Abstract available in German from the publisher]", "[Article in Japanese]"):
            s = L.screen(rec(EN, marker=marker))
            self.assertEqual((s["state"], s["hold"], s["translated"]), ("english", False, True), marker)
            self.assertTrue(registry_record.finish_pubmed_record(rec(EN, marker=marker), "1")[1]["nonEnglishAbstract"])   # existing cap/flag still applies
        self.assertEqual(L.screen(rec(EN, marker="[Article in English]"))["articleLanguage"], None)

    def test_the_label_alone_decides_nothing_when_the_text_is_english_and_nothing_when_the_text_is_foreign(self):
        self.assertFalse(L.screen(rec(EN, marker="[Article in French]"))["hold"])
        s = L.screen(rec(FR))                                                                     # foreign text without ANY label (seen on real records): still held
        self.assertTrue(s["hold"] and s["articleLanguage"] is None)

    def test_no_abstract_or_a_very_short_one(self):
        self.assertFalse(L.screen(rec())["hold"])                                                 # English-labelled article without abstract: not a language problem (the evidence check handles it)
        self.assertEqual(L.screen(rec())["state"], "indeterminate")
        self.assertTrue(L.screen(rec(marker="[Article in Italian]"))["hold"])                     # foreign article, nothing to confirm: fail closed
        self.assertFalse(L.screen(rec("Short English note on tinnitus."))["hold"])
        self.assertTrue(L.screen(rec("Un breve riassunto.", marker="[Article in Italian]"))["hold"])

    def test_terse_english_full_of_gene_and_drug_names_is_still_english(self):
        gene = ("Methods: Expression of BDNF, NTRF3 and GABRA1 in the cochlear nucleus of noise-exposed mice was quantified by qPCR at days 1, 7 and 28 and compared with controls. "
                "Results: BDNF rose 2.1-fold at day 7 (p < 0.01) while GABRA1 fell in the exposed group, which suggests altered inhibition in the auditory brainstem of the animals.")
        self.assertEqual(L.screen(rec(gene))["state"], "english")

    def test_a_short_foreign_quotation_inside_an_english_abstract_does_not_hold_it(self):
        s = L.screen(rec(EN.replace("Tinnitus is", "Tinnitus (French: acouphène) is")))
        self.assertFalse(s["hold"])

    def test_header_lines_and_identifiers_are_not_judged(self):
        s = L.screen(rec(EN, tail="DOI: 10.1000/x\nPMID: 1\n\nConflict of interest statement: " + FR + "\n\nCopyright © " + DE))
        self.assertEqual(s["state"], "english")

    def test_extraction_without_an_author_information_block(self):
        t = HEAD + "\n\n".join(["1. J Test. 2026;1:1.", "[Title].", "Doe J.", EN, "DOI: 1"])
        self.assertEqual(L.screen(t)["state"], "english")
        t2 = HEAD + "\n\n".join(["1. J Test. 2026;1:1.", "[Title].", "Doe J.", FR, "DOI: 1"])
        self.assertTrue(L.screen(t2)["hold"])


class InThePipeline(unittest.TestCase):
    """The REAL evaluator and cycle with the SDK stubbed (engine/tests/run_scenario.py): a held abstract costs nothing and is never published."""
    def test_foreign_abstract_makes_no_api_call_and_is_held_never_published(self):
        a, b, c = pubmed_item(90100001, "A foreign tinnitus trial"), pubmed_item(90100002, "A bilingual tinnitus trial"), pubmed_item(90100003, "An ordinary English tinnitus trial")
        recs = {a["id"]: registry_record.finish_pubmed_record(rec(FR).split("\n---\n", 1)[1], "90100001")[0],
                b["id"]: registry_record.finish_pubmed_record(rec(EN, ES).split("\n---\n", 1)[1], "90100002")[0],
                c["id"]: registry_record.finish_pubmed_record(rec(EN).split("\n---\n", 1)[1], "90100003")[0]}
        for settings in ({"enabled": True, "mode": "staged", "limitPerRun": 10}, {"enabled": True, "mode": "publish", "limitPerRun": 10}):
            r = run_scenario({"queue": [a, b, c], "settings": settings, "records": recs, "runs": [{}]})["runs"][0]
            self.assertNotIn(a["id"], r["apiCalls"]); self.assertNotIn(b["id"], r["apiCalls"])    # nothing is sent to the AI
            self.assertIn(c["id"], r["apiCalls"])                                                 # the ordinary one still is
            self.assertIn(a["id"], r["held"]); self.assertIn(b["id"], r["held"])
            self.assertIn("R4", r["heldReasons"][a["id"]])
            shown = [x["identifier"] for x in r["reportItems"]] + list(r["staged"])
            self.assertNotIn(a["id"], shown); self.assertNotIn(b["id"], shown)
            self.assertEqual(r["leaks"], [])
            self.assertEqual(r["status"]["evaluation"]["screenedWithoutAI"], 2)                 # counted as screened without the AI


if __name__ == "__main__":
    unittest.main()
