#!/usr/bin/env python3
"""Tinnitus Evidence — deterministic Level 3 triggers (no AI decides these).

Level 3 means "needs a person (and a clinician where the content is clinical)". Some of the triggers cannot depend on the model's own judgement, so they are
rules over the item's title and fetched record, plus one rule over the evaluation's declared direction:

  safety-term        a strong safety term in the title/record: seizure, convulsion, anaphylaxis, suicide, serious adverse event, safety communication, product recall,
                     life-threatening, cardiac arrest, permanent hearing loss, ...    -> HOLD (never published automatically)
  bears-on-tracked   the evaluation says the item strengthens or weakens the evidence for a treatment we track   -> HOLD (a possible evidence-strength change)
  regulatory-item    any item of kind 'regulatory' (FDA clearances, approvals, recalls)   -> HOLD (R1: regulatory status is Level 3; the FDA record fixes the date, a person decides)
  high-impact-study  an RCT, systematic review or meta-analysis whose treatment we track, WHATEVER direction the model gave   -> HOLD (R2: the direction label is the model's own opinion)
  advice-to-reader   public text addressed to the reader ("if you have ...", "patients should ...", "do not rely on ...")   -> HOLD (R3: clinical advice is Level 3)
  weak-safety-term   death, mortality, stroke, hospitalisation, ototoxicity, adverse events ...  -> shown to the reviewer as a flag only (too common in trial records to gate on)

Measured on real records (21 Oct 2026): the strong list fired on 1 of 51 pending PubMed abstracts (the AAO-HNSF guideline summary, already paused), 0 of 19 registry records
and on the benchmark's seizure vignette C6; the weak list fired on half of the registry records, which is why it is advisory. Negated mentions ("no seizures") are ignored.
"recall" counts only as a product/device recall (memory "recall" is not a safety signal).
"""
import re

STRONG = [r"seizures?", r"convuls\w+", r"anaphyla\w+", r"suicid\w+", r"serious adverse (?:event|reaction)s?", r"safety (?:communication|alert|warning)",
          r"(?:product|device|voluntary|fda|class (?:i|1)) recall(?:s|ed)?", r"recalled (?:the|its|all)", r"withdrawn from the market", r"unexpected deaths?", r"life-threatening",
          r"cardiac arrest", r"permanent (?:hearing loss|deafness|damage)", r"(?:device|product)[- ]related (?:injur\w+|harm|death)", r"warning letter"]
WEAK = [r"deaths?", r"died", r"fatal\w*", r"mortality", r"stroke", r"hospitali[sz]\w+", r"ototox\w+", r"adverse events?", r"harm(?:s|ed|ing|ful|fully|fulness|less)?", r"injur\w+"]    # 'harm' as a word and its forms only: the old harm\w* also matched "harmony" and "harmonic"
_STRONG = re.compile(r"\b(?:" + "|".join(STRONG) + r")\b", re.I)
_WEAK = re.compile(r"\b(?:" + "|".join(WEAK) + r")\b", re.I)
_NEG = re.compile(r"\b(no|not|none|without|nor|neither|zero|absence)\b", re.I)


# Exclusion-criterion wording ("excluding those with a history of ... stroke, seizures"). This only ANNOTATES a strong-term hold; it never lifts it (see triggers()).
# A hit counts as exclusion-only when an exclusion cue stands before the term in the same sentence, within 30 words, with none of the words that turn the term into
# something that happened to participants ("excluded after seizures", "because of seizures", "who developed seizures"). Cue AFTER the term ("had seizures and were excluded") never counts.
_EXCL_CUE = re.compile(r"\b(?:exclu\w*|ineligible|not eligible)\b", re.I)
_EXCL_BLOCK = re.compile(r"\b(?:after|following|followed|because|due|owing|who|whom|whose|that|which|developed|develop|developing|experienced|experiencing|reported|occurred|occurring|"
                         r"during|resulted|resulting|withdrew|withdrawn|discontinued|dropped|dropout|dropouts|stopped|terminated|event|events|incidence|rate|rates|cases)\b", re.I)


_EXCL_AFTER = re.compile(r"\b(?:occurred|occurring|observed|seen|reported|developed|experienced|noted|recorded|happened|resulted|in (?:\d|one|two|three|four|five|six|seven|eight|nine|ten))\b|\d", re.I)


def _is_exclusion_context(sent, start, end):
    pre = sent[:start]
    cue = None
    for c in _EXCL_CUE.finditer(pre):
        cue = c
    if cue is None:
        return False
    between = pre[cue.end():]
    if len(re.findall(r"[A-Za-z']+", between)) > 30:
        return False
    after = " ".join(sent[end:].split()[:8])          # "After exclusion of non-completers, seizures occurred in 2 patients": the term is something that happened
    return not _EXCL_BLOCK.search(between) and not _EXCL_AFTER.search(after)


def exclusion_only_terms(text, rx):
    """Terms from rx that appear (not negated) ONLY in exclusion-criterion context. A term with even one other mention is not in the result."""
    ctx, other = set(), set()
    for sent in re.split(r"(?<=[.!?;])\s+", text or ""):
        for m in rx.finditer(sent):
            pre = re.findall(r"[A-Za-z']+", sent[:m.start()])[-5:]
            if any(_NEG.fullmatch(w) for w in pre):
                continue
            (ctx if _is_exclusion_context(sent, m.start(), m.end()) else other).add(m.group(0).lower())
    return sorted(ctx - other)


def _hits(text, rx):
    out = []
    for sent in re.split(r"(?<=[.!?;])\s+", text or ""):
        for m in rx.finditer(sent):
            pre = re.findall(r"[A-Za-z']+", sent[:m.start()])[-5:]
            if not any(_NEG.fullmatch(w) for w in pre):
                out.append(m.group(0).lower())
    return sorted(set(out))


HIGH_IMPACT = re.compile(r"\bRCT\b|(?<!non-)(?<!non)(?<!quasi-)randomi[sz]ed|meta[- ]?analys|systematic review|crossover", re.I)
ADVICE = re.compile(r"\bif you\b|\byou (?:should|shouldn't|can|could|may|might|need|must|are advised)\b|\byour (?:doctor|clinician|audiologist|physician)\b|"
                    r"\b(?:patients|people|those|sufferers) (?:with [\w\s]{0,30})?(?:should|must|need to|ought)\b|\bdo not (?:use|rely|skip|stop|start)\b|\bshould not be used as a reason\b", re.I)
_ADVICE_NEG = re.compile(r"\b(no|not|none|nothing|never|without|nor|neither)\b", re.I)
ADVICE_FIELDS = ("weeklyTitle", "whyMatters", "whatIsNew")


def advice_hits(ev):
    out = []
    for f in ADVICE_FIELDS:
        for sent in re.split(r"(?<=[.!?;])\s+", str((ev or {}).get(f) or "")):
            for m in ADVICE.finditer(sent):
                pre = re.findall(r"[A-Za-z']+", sent[:m.start()])[-6:]
                if not any(_ADVICE_NEG.fullmatch(w) for w in pre):      # "changes nothing about what patients should do" is not advice
                    out.append(f"{f}: {m.group(0).lower()}")
    return sorted(set(out))


def triggers(item, record_text, ev, tracked_ids=()):
    """Returns a list of {'tier': 'level3'|'flag', 'kind': ..., 'detail': ...}. Pure function; no network, no AI."""
    text = (item.get("title") or "") + ". " + (record_text or "")
    out = []
    s = _hits(text, _STRONG)
    if s:
        trig = {"tier": "level3", "kind": "safety-term", "detail": s}
        xo = exclusion_only_terms(text, _STRONG)
        if xo:
            trig["exclusionOnly"] = xo     # annotation for the reviewer and the scorer; the hold itself is NOT lifted
        out.append(trig)
    if (ev or {}).get("evidenceDirection") in ("strengthens", "weakens") and (ev or {}).get("affectedTreatment") in set(tracked_ids):
        out.append({"tier": "level3", "kind": "bears-on-tracked-treatment", "detail": f"{ev.get('evidenceDirection')} {ev.get('affectedTreatment')}"})
    if (item or {}).get("kind") == "regulatory":
        out.append({"tier": "level3", "kind": "regulatory-item", "detail": "regulatory record: reviewed by a person, never published automatically"})
    if (ev or {}).get("affectedTreatment") in set(tracked_ids) and HIGH_IMPACT.search(str((ev or {}).get("studyType") or "")):
        out.append({"tier": "level3", "kind": "high-impact-study-on-tracked-treatment", "detail": f"{ev.get('studyType')} on {ev.get('affectedTreatment')} (direction given by the model: {ev.get('evidenceDirection')})"})
    adv = advice_hits(ev)
    if adv:
        out.append({"tier": "level3", "kind": "advice-to-reader", "detail": adv})
    w = [x for x in _hits(text, _WEAK)]
    if w and not s:
        out.append({"tier": "flag", "kind": "weak-safety-term", "detail": w})
    return out
