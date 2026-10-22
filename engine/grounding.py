#!/usr/bin/env python3
"""Tinnitus Evidence — deterministic checks on an AI evaluation (no network, no AI).

The model's own `factuallyVerified` and `confidence` are SELF-ASSESSMENTS: the model has no tools and checks nothing outside the text it was
given. They are recorded but are never, on their own, a reason to publish. This module computes what code CAN verify, independently of the model:

  * was a primary record actually retrieved, does it carry the item's own identifier (PMID / NCT), and was it complete or cut?
  * does every number the model reports (results, sample size, headline) appear in the record it was given (with rounding)?
  * does the public-facing text contain novelty or authority claims ("first", "largest", "senior author" ...) that the record does not make?
  * (advisory only) which capitalised names in the text appear nowhere in the record, the item metadata or our database?
  * enumerated fields: strip instruction text the model copied into them (the Phase 2 `comparisonType` leak) and map to the allowed values.

It also clamps `confidence` in code where the evidence for the model's confidence is missing (no record, cut record, ungrounded numbers).

Two DIFFERENT questions are kept apart (see evidence_adequacy below):
  1. source-grounding accuracy: does the report say only what the record says?  (numbers, terms, names, identifier: the checks above)
  2. adequacy of the underlying evidence: does the RECORD ITSELF contain verifiable study specifics (how many, how it was done, what was found)?
     A faithful summary of a data-free abstract answers 1 yes and 2 no. Question 2 is judged from the record text by code, never from the model's answer,
     and a primary study whose record shows none of the three specifics FAILS CLOSED: factuallyVerified is forced false, confidence is forced low, and the
     publication gate (weekly_cycle.verified) refuses it whatever the model said.
It cannot verify prose claims such as "unblinded" or "no sham control"; those remain a human-review matter (see engine/STAGED-REVIEW.md).
"""
import re

CHECKS_VERSION = 2   # 2 = adds evidenceAdequacy; an evaluation without it (version 1) is NOT publishable: the gate fails closed
PASSING_CHECKS = {"version": CHECKS_VERSION, "ok": True, "recordFetched": True, "identifierMatchesItem": True, "recordComplete": True,
                  "criticalOmitted": False, "ungroundedNumbers": [], "unsupportedTerms": [], "ungroundedNames": [], "ungroundedDates": [], "enumFixes": [],
                  "evidenceAdequacy": {"assessed": True, "applies": True, "level": "adequate", "adequate": True, "reasons": []},
                  "note": "synthetic passing checks for simulation fixtures"}

# fields whose numbers must be found in the record (they become public text or the headline)
HARD_NUMBER_FIELDS = ("numericalResult", "sampleSize", "whatIsNew", "weeklyTitle")
SOFT_NUMBER_FIELDS = ("whyMatters", "population", "primaryEndpoint", "secondaryEndpoints", "otherOutcomes", "safetyObservations")
TERM_FIELDS = ("whatIsNew", "weeklyTitle", "whyMatters", "summaryForAdmin", "conflictOfInterest", "mainLimitations", "clinicalSignificance")
NAME_FIELDS = ("whatIsNew", "whyMatters", "conflictOfInterest", "mainLimitations", "summaryForAdmin")
UNSUPPORTED_TERMS = ("first", "largest", "novel", "pioneering", "landmark", "breakthrough", "groundbreaking", "unprecedented",
                     "world-first", "senior authors?", "corresponding authors?", "lead authors?", "gold standard",
                     "equity", "well-sized", "well-powered", "reassuring", "compelling", "impressive", "definitive")

DOMAIN_TERMS = {"quality of life": r"quality[- ]of[- ]life", "sleep": r"sleep", "anxiety": r"anxi", "depression": r"depress", "cognition": r"cognit", "pain": r"\bpain"}   # stems: 'depressive' in the record supports 'depression' in the text
DOMAIN_FIELDS = ("whatIsNew", "whyMatters", "weeklyTitle")
COI_LABELS = ("manufacturer-funded", "author equity", "independent", "unclear")
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
         "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
         "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100}
COMMON = set("""Tinnitus Patients Adults Registry Study Trial Trials Review Analysis Results Outcome Outcomes Treatment Therapy Hearing Medical Questionnaire
Inventory Handicap Functional Index Visual Analogue Scale Placebo Sham Control Group Groups Randomized Randomised Double Single Blind Blinded Primary Secondary
Evidence Database Company Sponsor Registry Clinical Trial Phase Systematic Meta Cohort Report Reported Record Records Weekly Feed Public Nothing Abstract
Journal Article Paper Published Publication January February March April May June July August September October November December Not Unclear None
Inference Independent University Hospital Institute Department School Center Centre""".split())


def _num(tok):
    try:
        return float(tok.replace(",", "").rstrip("."))
    except ValueError:
        return None


def _decimals(tok):
    t = tok.replace(",", "")
    return len(t.split(".")[1]) if "." in t else 0


def record_numbers(text):
    vals = set()
    for m in NUM_RE.finditer(text or ""):
        v = _num(m.group(0))
        if v is not None:
            vals.add(v)
    for w, v in WORDS.items():
        if re.search(rf"\b{w}\b", text or "", re.I):
            vals.add(float(v))
    for m in re.finditer(r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[- ](one|two|three|four|five|six|seven|eight|nine)\b", text or "", re.I):
        vals.add(float(WORDS[m.group(1).lower()] + WORDS[m.group(2).lower()]))
    for m in re.finditer(r"\b(one|two|three|four|five|six|seven|eight|nine)[- ]hundred\b", text or "", re.I):
        vals.add(float(WORDS[m.group(1).lower()] * 100))
    return vals


def number_grounded(tok, vals):
    """True when the token equals a number in the record, or is that number rounded to the token's own precision (12.5 for 12.52, 9 for 9.11)."""
    v = _num(tok)
    if v is None:
        return True
    d = _decimals(tok)
    return any(abs(n - v) < 1e-9 or round(n, d) == v or round(abs(n), d) == v for n in vals)


def _flat(v):
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return " ; ".join(_flat(x) for x in v)
    return str(v)


def ungrounded_numbers(ev, record_text, fields):
    vals = record_numbers(record_text)
    out = []
    for f in fields:
        for m in NUM_RE.finditer(_flat(ev.get(f))):
            tok = m.group(0).rstrip(",.")
            if tok and not number_grounded(tok, vals):
                out.append({"field": f, "value": tok})
    return out


NEG = re.compile(r"\b(no|not|nor|none|without|neither|never|absent|unreported)\b", re.I)


def negated(sentence, start, end, before=6, after=0):
    """True when a negation word stands within `before` words ahead of, or `after` words behind, the matched term (so 'equity holdings are not reported' is negated,
    and 'measured distress and quality of life, not how loud' is NOT negated for the term 'quality of life')."""
    pre = re.findall(r"[A-Za-z']+", sentence[:start])[-before:] if before else []
    post = re.findall(r"[A-Za-z']+", sentence[end:])[:after] if after else []
    return any(NEG.fullmatch(w) for w in pre + post)


def unsupported_terms(ev, record_text):
    out = []
    low = (record_text or "").lower()
    for f in TERM_FIELDS:
        for sent in re.split(r"(?<=[.!?;])\s+", _flat(ev.get(f)).lower()):
            for t in UNSUPPORTED_TERMS:
                pat = t if t.endswith("?") else re.escape(t)      # entries ending in '?' are regular expressions (plural forms)
                m = re.search(rf"\b{pat}\b", sent)
                if m and not re.search(rf"\b{pat}\b", low) and not negated(sent, m.start(), m.end(), before=6, after=4):
                    out.append({"field": f, "term": m.group(0)})
    return out


def ungrounded_domain_terms(ev, record_text):
    """Advisory: an outcome domain (quality of life, sleep ...) stated affirmatively in the public text but never mentioned in the record. Negated sentences are skipped."""
    low = (record_text or "").lower()
    out = []
    for f in DOMAIN_FIELDS:
        for s in re.split(r"(?<=[.!?;])\s+", _flat(ev.get(f))):
            for t, stem in DOMAIN_TERMS.items():
                m = re.search(stem if stem.startswith(r"\b") else rf"\b{stem}", s, re.I)
                if m and not re.search(stem, low) and not negated(s, m.start(), m.end(), before=6, after=0):
                    out.append({"field": f, "term": t})
    return out


def compound_coi_label(ev):
    """Advisory: the label before the first ' - ' / em dash / colon names more than one option (the schema's option list copied instead of ONE label chosen)."""
    s = _flat(ev.get("conflictOfInterest"))
    head = re.split(r"\s[-\u2014\u2013]\s|:", s, maxsplit=1)[0].lower()
    found = [l for l in COI_LABELS if l in head]
    return found if len(found) > 1 else []


def ungrounded_names(ev, record_text, known_words=()):
    """Advisory: capitalised words (not sentence-initial) in explanatory text that appear nowhere in the record, metadata or database."""
    low = (record_text or "").lower()
    known = {w.lower()[:4] for w in known_words}
    out = []
    for f in NAME_FIELDS:
        text = _flat(ev.get(f))
        for m in re.finditer(r"(?<![.!?;:]\s)(?<!^)\b([A-Z][a-zA-Z]{4,})\b", text):
            w = m.group(1)
            if w in COMMON or w.lower()[:4] in known or w.lower()[:4] in low:
                continue
            out.append({"field": f, "name": w})
    seen, dedup = set(), []
    for o in out:
        if o["name"] not in seen:
            seen.add(o["name"]); dedup.append(o)
    return dedup


# ---------------------------------------------------------------- enumerated fields
ENUMS = {
    "comparisonType": ["between-group", "within-group only", "none", "Not reported"],
    "controlQuality": ["sham/placebo-controlled", "active-control", "no-control", "n/a"],
    "blinded": ["double", "single", "none", "unclear", "n/a"],
    "studyQuality": ["high", "moderate", "low", "not-a-study"],
    "evidenceDirection": ["strengthens", "weakens", "no-meaningful-change"],
    "changeClass": ["routine", "major"],
    "confidence": ["low", "moderate", "high"],
    "importance": ["Potentially Important", "Interesting but Early", "Confirms Previous Evidence", "Negative Result", "Does Not Change Current Evidence"],
    "regulatorySource": ["authoritative (FDA/EMA/registry record)", "company announcement", "secondary reporting", "n/a"],
}


def normalise_enums(ev):
    """Map a value that starts with an allowed option (the model appended explanation or copied instruction text) to the option itself.
    Returns a list of fixes [{field, from, to}]; values that match nothing are left alone and listed with to=None for the reviewer."""
    fixes = []
    for f, options in ENUMS.items():
        v = ev.get(f)
        if not isinstance(v, str) or not v.strip():
            continue
        s = v.strip()
        hit = next((o for o in options if s.lower() == o.lower()), None) or \
            next((o for o in sorted(options, key=len, reverse=True) if s.lower().startswith(o.lower())), None)
        if hit is None:
            fixes.append({"field": f, "from": s[:80], "to": None})
        elif hit != v:
            ev[f] = hit
            fixes.append({"field": f, "from": s[:80], "to": hit})
    rc = ev.get("relevanceCategory")
    if isinstance(rc, str):
        m = re.match(r"\s*([1-6])\b", rc)
        if m:
            ev["relevanceCategory"] = int(m.group(1))
            fixes.append({"field": "relevanceCategory", "from": rc[:40], "to": int(m.group(1))})
    return fixes


# ---------------------------------------------------------------- record identity
# ---- evidence adequacy: judged from the RECORD text, not from the model's answer -----------------------------------------------------------------------------
SAMPLE_RE = re.compile(r"\b[nN]\s*=\s*\d|\b(?:\d[\d,]*|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)\s+(?:\w+\s+){0,3}?(?:patients?|participants?|subjects?|individuals?|people|persons?|adults?|children|adolescents?|men|women|males?|females?|"
                       r"cases?|ears?|veterans?|volunteers?|respondents?|students?|controls?|infants?|neonates?|workers?|studies|trials|articles|animals?|rats?|mice|guinea pigs?|gerbils?)\b|"
                       r"\b(?:total of|sample of|cohort of|enrolled|recruited|included|randomi[sz]ed|analy[sz]ed|surveyed|screened|evaluated|assessed|examined|reviewed)\s+\d[\d,]*", re.I)
DESIGN_RE = re.compile(r"\b(?:randomi[sz]ed|randomly|controlled|double-blind|single-blind|blinded|placebo|sham|cohort|case-control|cross-sectional|retrospective|prospective|longitudinal|survey|"
                       r"questionnaires?|interviews?|registry|database|crossover|open-label|single-arm|pilot|feasibility|were (?:divided|assigned|allocated|enrolled|recruited|compared|measured|assessed|"
                       r"evaluated|recorded|tested|analy[sz]ed|treated|exposed|included|collected)|(?:primary|secondary)\s+(?:outcome|endpoint)s?|outcome measures?|main outcome|THI|TFI|THQ|VAS|"
                       r"PSQI|audiometr\w+|EEG|MRI|fMRI|ABR|DPOAE|regression|logistic|mixed[- ]effects|Mann-Whitney|t-test|ANOVA|Kaplan|chi-square|multivariable|adjusted)\b", re.I)
RESULT_RE = re.compile(r"\d\s*%|\bp\s*[<=>\u2264\u2265]\s*0?\.\d|\b(?:OR|HR|RR|AOR|aHR|aOR|SMD|MD|WMD|IRR|PPV|NPV)\b\s*[=:,]?\s*\(?\d|95\s*%\s*(?:CI|confidence)|\bCI\b\s*[:,]?\s*\d|"
                       r"\d\s*(?:\u00b1|\+/-|\+-)\s*\d|\b(?:mean|median|average)\b[^.;]{0,60}\d|\b(?:increased?|decreased?|reduced?|improved?|declined?|rose|fell|dropped|changed?|difference)\b[^.;]{0,40}\bby\b\s*\d|"
                       r"\bfrom\s+\d+(?:\.\d+)?\s+to\s+\d|\bd\s*=\s*\d|\bsensitivity\b[^.;]{0,30}\d|\bspecificity\b[^.;]{0,30}\d|\br\s*=\s*-?0?\.\d|\bincidence\b[^.;]{0,40}\d|\bprevalence\b[^.;]{0,40}\d", re.I)
REVIEW_TEXT_RE = re.compile(r"\breview\b|meta-?analys[ie]s|systematic|overview|scoping|narrative|guideline|consensus|perspective|state[- ]of[- ]the[- ]art", re.I)
PROTOCOL_TEXT_RE = re.compile(r"\bprotocol\b|study design and rationale|trial registration", re.I)
CASE_TEXT_RE = re.compile(r"\bcase reports?\b|\bcase series\b|\bwe (?:report|describe|present) (?:a|an|two|three|four|five|\d+)\b|\b(?:a|an) \d+-year-old", re.I)
# PubMed's own publication types (from the scan, independent of the model and of the abstract): types for which sample size and results are not expected
EXEMPT_PUBTYPES = {"review": "review", "systematic review": "review", "meta-analysis": "review", "practice guideline": "review", "guideline": "review", "consensus development conference": "review",
                   "case reports": "case report", "editorial": "commentary", "comment": "commentary", "letter": "commentary", "published erratum": "notice", "retraction of publication": "notice",
                   "retracted publication": "notice", "expression of concern": "notice"}
MODEL_EXEMPT = (("review", REVIEW_TEXT_RE, "review"), ("meta-analysis", REVIEW_TEXT_RE, "review"), ("guideline", REVIEW_TEXT_RE, "review"), ("protocol", PROTOCOL_TEXT_RE, "protocol"),
                ("case report", CASE_TEXT_RE, "case report"), ("case series", CASE_TEXT_RE, "case report"))


def _missing(v):
    t = str(v if v is not None else "").strip().lower()
    return t in ("", "n/a", "none", "unable to verify", "unclear", "none reported", "no results", "-") or t.startswith(("not reported", "none reported", "none -", "none \u2014", "not stated", "not given"))


def record_body(record_text):
    """The record without its machine-written completeness header (everything up to the first '---' line), so header words cannot count as study specifics."""
    t = record_text or ""
    i = t.find("\n---\n")
    t = t[i + 5:] if t.startswith(("SOURCE:", "RECORD COMPLETENESS")) and i != -1 else t
    return re.sub(r"(?im)^\s*(?:PMID|PMCID|DOI|NCT ID)\b[^\n]*$", "", t)


def evidence_adequacy(item, ev, record_text):
    """Does the RECORD contain verifiable study specifics? Cues searched in the record text only: (1) a sample size, (2) design/method/endpoint wording, (3) result figures.
      level 'insufficient' : a primary study whose record shows NONE of the three  -> not adequate (fail closed)
      level 'thin'         : exactly one cue present                                 -> adequate, recorded as an advisory for the reviewer
      level 'adequate'     : two or three cues
      level 'exempt'       : review, protocol, case report, commentary or notice, identified by PubMed's publication type or (model label AND corroborating text); never by the model alone
      level 'not-applicable': not a PubMed/abstract study item (registry, regulatory and news items have their own completeness and source gates)
    A model that asserts a limited/moderate/strong loudness or distress effect when the record contains no result figure at all is also insufficient. Numbers the model
    invents (a sample size or result the record does not give) are caught by the existing grounding check (`ungroundedNumbers`), which the gate applies first; an earlier version
    of this function also second-guessed those fields and wrongly held legitimate answers (a qualitative result in `numericalResult`, a spelled-out sample), so it no longer does."""
    out = {"assessed": True, "applies": False, "level": "not-applicable", "adequate": True, "cues": {}, "reasons": [], "exemptReason": None}
    if (item or {}).get("kind") != "study":
        return out
    out["applies"] = True
    body = record_body(record_text)
    title = (item or {}).get("title", "")
    text = title + "\n" + body
    cues = {"sampleSize": bool(SAMPLE_RE.search(text)), "design": bool(DESIGN_RE.search(text)), "results": bool(RESULT_RE.search(text))}
    out["cues"] = cues
    # exemption: PubMed's own publication types, else the model's label corroborated by the record text
    pts = [str(x).lower() for x in (item or {}).get("pubtypes", []) or []]
    exempt = next((EXEMPT_PUBTYPES[t] for t in pts if t in EXEMPT_PUBTYPES), None)
    if exempt is None:
        st = str((ev or {}).get("studyType", "")).lower()
        for key, rx, kind in MODEL_EXEMPT:
            if key in st and rx.search(text):
                exempt = kind
                break
    n = sum(cues.values())
    fabricated = []
    # a benefit asserted while the record contains no result figure at all (closes the easy bypass of adding a sample size and a design word to a promotional abstract)
    asserted = [f for f in ("loudnessEffect", "distressEffect") if str((ev or {}).get(f, "")).strip().lower().replace(",", " ").split(" ")[0] in ("limited", "moderate", "strong")]
    if asserted and not cues["results"] and exempt in (None, "case report"):
        fabricated.append("the evaluation asserts a " + " and ".join(a.replace("Effect", " effect") for a in asserted) + " but the record contains no result figure")
    if exempt and not fabricated:
        out.update(level="exempt", exemptReason=exempt)
        return out
    if fabricated:
        out.update(level="insufficient", adequate=False, reasons=fabricated)
        return out
    if n == 0:
        out.update(level="insufficient", adequate=False, reasons=["the record gives no sample size, no design or endpoint wording and no result figures: the study's own claim cannot be verified from it"])
    elif n == 1:
        out.update(level="thin", reasons=["only one of sample size, design/endpoint wording and result figures appears in the record"])
    else:
        out["level"] = "adequate"
    return out


def apply_adequacy(ev, sc):
    """Fail closed: when the record cannot support the study's own claim, the model's 'verified' is overridden (its original answer is kept as factuallyVerifiedModel)."""
    ea = (sc or {}).get("evidenceAdequacy") or {}
    if ea.get("adequate") is False:
        ev["factuallyVerifiedModel"] = ev.get("factuallyVerified")
        ev["factuallyVerified"] = False
        ev["evidenceAdequacyNote"] = "; ".join(ea.get("reasons") or ["record insufficient"])
        return True
    return False


ISO_DATE_RE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
DATE_FIELDS = ("whatIsNew", "weeklyTitle", "whyMatters", "numericalResult", "summaryForAdmin", "clinicalSignificance", "otherOutcomes")


def ungrounded_dates(ev, context):
    """Full ISO dates (YYYY-MM-DD) in the evaluation's text that appear nowhere in the record, the item's own date or its title/summary. (A published FDA item gave 2026-09-04, the day the
    scan found it, as the decision date; the record said 2026-08-13.)"""
    have = set(ISO_DATE_RE.findall(context or ""))
    out = []
    for f in DATE_FIELDS:
        for d in ISO_DATE_RE.findall(_flat((ev or {}).get(f))):
            if d not in have:
                out.append({"field": f, "date": d})
    return out


def identifier_matches(item, record_text):
    iid = item.get("id", "")
    t = record_text or ""
    if iid.startswith("pubmed-"):
        pmid = iid.split("-", 1)[1]
        return bool(re.search(rf"PMID:?\s*{re.escape(pmid)}\b", t))
    if iid.startswith("ctgov-"):
        return bool(re.search(rf"NCT ID:\s*{re.escape(iid.split('-')[1])}\b", t))
    return None   # no identifier to match (news items): the item has no primary record anyway


def source_checks(item, ev, record_text, meta, known_words=()):
    """The deterministic verification record stored with every evaluation. `ok` is True only when nothing failed that code can detect."""
    meta = meta or {}
    fetched = meta.get("completeness") in ("COMPLETE", "SHORTENED", "TRUNCATED")
    ident = identifier_matches(item, record_text) if fetched else None
    context = (record_text or "") + " " + " ".join(_flat(item.get(k)) for k in ("title", "summary", "source", "date"))
    sc = {"version": CHECKS_VERSION, "recordFetched": fetched, "identifierMatchesItem": ident, "recordComplete": meta.get("completeness") in ("COMPLETE", "SHORTENED"),
          "criticalOmitted": bool(meta.get("criticalOmitted")), "completeness": meta.get("completeness", "UNKNOWN"),
          "hasResults": meta.get("hasResults"), "ungroundedNumbers": ungrounded_numbers(ev, context, HARD_NUMBER_FIELDS), "ungroundedDates": ungrounded_dates(ev, context),
          "advisoryNumbers": ungrounded_numbers(ev, context, SOFT_NUMBER_FIELDS), "unsupportedTerms": unsupported_terms(ev, context),
          "ungroundedNames": ungrounded_names(ev, context, known_words), "ungroundedDomainTerms": ungrounded_domain_terms(ev, context),
          "compoundCoiLabel": compound_coi_label(ev), "nonEnglishAbstract": bool(meta.get("nonEnglishAbstract")), "enumFixes": [], "evidenceAdequacy": evidence_adequacy(item, ev, record_text)}
    needs_record = item.get("id", "").startswith(("pubmed-", "ctgov-"))
    sc["ok"] = bool(fetched and not sc["criticalOmitted"] and (ident is not False) and (ident or not needs_record)
                    and not sc["ungroundedNumbers"] and not sc["ungroundedDates"] and not sc["unsupportedTerms"] and sc["evidenceAdequacy"]["adequate"])
    return sc


def clamp_confidence(ev, sc):
    """The model's confidence is kept as `confidenceModel`; the working `confidence` is lowered where code can show the basis is missing."""
    order = ["low", "moderate", "high"]
    model = ev.get("confidence") if ev.get("confidence") in order else "low"
    cap = "high"
    if not sc.get("recordFetched"):
        cap = "low"
    elif sc.get("criticalOmitted") or sc.get("completeness") == "TRUNCATED":
        cap = "moderate"
    if sc.get("nonEnglishAbstract") and cap == "high":
        cap = "moderate"   # the model translated; neither code nor a typical reviewer can check the translation
    if sc.get("ungroundedNumbers") or sc.get("unsupportedTerms") or sc.get("ungroundedDates"):
        cap = "low"
    if (sc.get("evidenceAdequacy") or {}).get("adequate") is False:
        cap = "low"
    final = order[min(order.index(model), order.index(cap))]
    ev["confidenceModel"] = ev.get("confidence")
    ev["confidence"] = final
    return final


def source_checks_pass(ev):
    sc = ev.get("sourceChecks")
    if not isinstance(sc, dict):
        return False, "no automated source checks recorded for this evaluation"
    if not sc.get("recordFetched"):
        return False, "no primary record was retrieved, so the facts cannot be checked"
    if sc.get("criticalOmitted"):
        return False, "the record given to the model was cut and lost critical sections"
    if sc.get("identifierMatchesItem") is False:
        return False, "the retrieved record does not carry this item's identifier"
    if sc.get("ungroundedNumbers"):
        return False, "numbers in the evaluation were not found in the source record"
    if sc.get("ungroundedDates"):
        return False, "dates in the evaluation were not found in the source record"
    if sc.get("unsupportedTerms"):
        return False, "the evaluation makes novelty/authority claims the record does not make"
    ea = sc.get("evidenceAdequacy")
    if not isinstance(ea, dict) or not ea.get("assessed"):
        return False, "evidence adequacy was not assessed for this evaluation (it predates the check): not publishable until re-evaluated"
    if ea.get("adequate") is not True:
        return False, "the record is insufficient to verify the study's own claim: " + "; ".join(ea.get("reasons") or ["no verifiable specifics"])
    if not sc.get("ok"):
        return False, "automated source checks did not pass"
    return True, ""
