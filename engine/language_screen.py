#!/usr/bin/env python3
"""R4 - hold abstracts that are not in English. Deterministic, no network, no AI.

The code cannot check a model's reading of text it cannot read itself, and neither can an English-reading reviewer, so an abstract that is not clearly English is HELD for a
person before any paid call (nothing is sent to the model, nothing is published). What is judged is the abstract text the pipeline actually shows the model, not the article's
label: most PubMed records for non-English articles carry an English abstract (author- or publisher-supplied), and those are checkable like any other.

  state          meaning                                                              what happens
  english        every abstract paragraph is clearly English                           normal path (a translated abstract is labelled, see `translated`)
  non_english    the abstract text is another language or script                       HOLD, no paid call
  mixed          English and another language/script in the abstract text              HOLD, no paid call (which part the model read cannot be checked)
  indeterminate  too little text to tell                                               HOLD only if the record is labelled an article in another language, else normal path

`translated` = clearly English abstract on an article labelled as another language: evaluated, flagged, confidence-capped (grounding.py), never eligible for the restricted
release path, and never published without a person reading it (staged mode approves nothing automatically).
Stdlib only. Function words only (no vocabulary), so medical English with many gene/drug names still scores as English."""
import re

MARKER = re.compile(r"\[Article in ([A-Za-z][A-Za-z ,]*?)(?:;[^\]]*)?\]")
MIN_TOKENS = 25                 # fewer Latin-script words than this in a paragraph: that paragraph is too short to judge
MIN_LETTERS_NONLATIN = 40       # fewer non-Latin letters than this: too short to judge
EN_MIN, EN_WEAK, OTHER_MAX = 0.16, 0.08, 0.05

_EN = set("the of and in to with was were for that is are by from at this these be or which had has have not than after between during both using its their also there been can may "
          "those into who while among all more most other such only our we but if when where whether however therefore compared versus per".split())
_OTHERS = {
    "fr": set("le la les des du une est dans pour avec que qui sur au aux par sont ont cette ces été pas plus chez lors après comme mais nous vous il elle leur leurs entre ainsi ou où donc dont".split()),
    "de": set("der die das und mit bei von den dem nicht ist eine einer einen auf für zur zum im des wurde wurden sind auch oder nach als über sich aus durch bei werden wird kann können".split()),
    "es": set("el los las de que en con por una del para se su como más fue fueron sin sobre este esta estos estas pero también han ser son entre al lo le un".split()),
    "pt": set("os as do da dos das em com uma foi não são pelo pela mais entre sobre também ao nos nas por que se um para".split()),
    "it": set("il di che per con della sono gli nel nella dei delle del una più non anche tra sul alla dal sia stato stati è".split()),
    "nl": set("de het een van en met voor niet op bij zijn werd werden naar ook door als aan uit dat die deze er".split()),
}
_NOT_PARAGRAPHS = re.compile(r"^(DOI:|PMID:|PMCID:|Conflict of interest|Copyright|©|Comment in|Erratum in|Update in|Republished|Retraction|Free PMC|Author information|Trial registration|Keywords?:|KEYWORDS?:|SOURCE:|RECORD COMPLETENESS|CRITICAL SECTIONS|---)", re.I)
_CITATION = re.compile(r"^\d+\.\s")


def _blocks(c):
    o = ord(c)
    if o < 0x250 or 0x1E00 <= o <= 0x1EFF:
        return "latin"
    if 0x370 <= o <= 0x3FF:
        return "greek"
    return "other"


def article_language(text):
    """The language the record's own label gives for the ARTICLE ('French'), or None for an English/unlabelled article. A label never says anything about the abstract."""
    m = MARKER.search(text or "")
    if not m:
        return None
    lang = m.group(1).strip()
    return None if lang.lower() in ("english", "eng") else lang


def abstract_paragraphs(text):
    """The paragraphs of the record that are abstract text: after the citation, title, label, authors and affiliations, before the identifiers and statements."""
    body = (text or "").split("\n---\n", 1)[-1] if "\n---\n" in (text or "") else (text or "")
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    ai = next((i for i, p in enumerate(paras) if p.startswith("Author information")), None)
    if ai is not None:
        cand = paras[ai + 1:]
    else:
        cand = [p for p in paras if not _CITATION.match(p)]
        lead = 0
        while cand and lead < 3 and len(cand[0]) < 200:   # title, label and authors are short; abstract paragraphs are not
            cand, lead = cand[1:], lead + 1
    out = []
    for p in cand:
        if _NOT_PARAGRAPHS.match(p) or MARKER.match(p):
            continue
        out.append(re.sub(r"^Publisher:\s*", "", p))
    return out


def _paragraph_state(p):
    letters = [c for c in p if c.isalpha()]
    if not letters:
        return None
    kinds = [_blocks(c) for c in letters]
    n, other, greek = len(letters), kinds.count("other"), kinds.count("greek")
    if greek / n >= 0.4 and greek >= MIN_LETTERS_NONLATIN:
        return "non_english"
    nonlatin = other / max(1, n - greek)
    if other >= MIN_LETTERS_NONLATIN:
        return "non_english" if nonlatin >= 0.9 else "mixed" if nonlatin >= 0.1 else "english_or_short"
    toks = [t.lower() for t in re.findall(r"[^\W\d_]+", p)]
    if len(toks) < MIN_TOKENS:
        return "short" if other == 0 else "indeterminate_script"
    rate = lambda words: sum(1 for t in toks if t in words) / len(toks)
    en = rate(_EN)
    best = max(rate(w) for w in _OTHERS.values())
    if en >= 0.10 and best >= 0.10:
        return "mixed"
    if (en >= EN_MIN and en >= 2 * best) or (en >= EN_WEAK and best <= OTHER_MAX):
        return "english"
    return "non_english"


def screen(text):
    """Judge the abstract text of one PubMed record (pipeline format). Returns {state, articleLanguage, translated, hold, reason}."""
    lang = article_language(text)
    states = [s for s in (_paragraph_state(p) for p in abstract_paragraphs(text)) if s]
    if any(s == "mixed" for s in states):
        state = "mixed"
    elif any(s == "non_english" for s in states):
        state = "mixed" if any(s == "english" for s in states) else "non_english"
    elif any(s == "english" for s in states):
        state = "english"
    elif any(s == "english_or_short" for s in states):
        state = "english"
    else:
        state = "indeterminate"
    hold = state in ("non_english", "mixed") or (state == "indeterminate" and lang is not None)
    reason = ""
    if hold:
        reason = ({"non_english": "the abstract text is not in English", "mixed": "the abstract text mixes English with another language or script"}.get(state)
                  or f"the article is labelled as being in {lang} and no English abstract text could be confirmed")
        reason += ": held for a person to read; nothing was sent to the AI, nothing is published (rule R4)"
    return {"state": state, "articleLanguage": lang, "translated": bool(state == "english" and lang), "hold": hold, "reason": reason}
