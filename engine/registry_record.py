#!/usr/bin/env python3
"""Tinnitus Evidence — compact, structured primary-record text for the AI evaluator.

Why this exists (Phase 2 finding): the evaluator used to send ClinicalTrials.gov's `protocolSection` as indent-expanded JSON cut at 12,000
characters. Site addresses could consume most of that budget, the references list and eligibility criteria were the first things lost,
`hasResults` / `resultsSection` were never sent (so "no results posted" was a guess), and the model was not told that anything had been cut.

This module builds plain, compact text in a fixed order of importance, keeps the content that matters for judging evidence (design,
masking, arms, outcomes, eligibility, references, results availability and a compact results summary), replaces the site list by a count
and the list of countries, and REPORTS what was shortened or omitted, both inside the text (so the model knows) and in a metadata dict
(so the pipeline and the reviewer know). Pure functions, no network access.
"""
import re

BUDGET = 20000                       # characters of record text sent to the model (was 12,000 of expanded JSON)
CRITICAL = ("primaryOutcomes", "eligibility", "references", "results")   # sections whose loss must never go unnoticed
SCALES = (1.0, 0.75, 0.55, 0.40, 0.28)


def _s(v):
    return "" if v is None else str(v).strip()


def _ws(t):
    return re.sub(r"\s+", " ", _s(t))


class _Ctx:
    """Collects what was shortened (a text field cut) and what was omitted (list items or a whole section left out)."""

    def __init__(self, scale):
        self.scale = scale
        self.shortened, self.omitted = [], []

    def clip(self, text, base, label):
        t = _ws(text)
        n = max(80, int(base * self.scale))
        if len(t) <= n:
            return t
        if label not in self.shortened:
            self.shortened.append(label)
        return t[:n].rstrip() + f" ...[{len(t) - n} more characters not shown]"

    def cap(self, items, base, label, floor=3):
        n = max(floor, int(base * self.scale))
        if len(items) > n:
            self.omitted.append({"section": label, "shown": n, "total": len(items)})
            return items[:n]
        return items


def _g(d, *path, default=None):
    for p in path:
        if not isinstance(d, dict):
            return default
        d = d.get(p)
    return default if d is None else d


def _date(struct):
    if isinstance(struct, dict) and struct.get("date"):
        return f"{struct['date']} ({struct.get('type', '').lower() or 'type not stated'})"
    return "not stated"


def _group_label(groups, gid):
    g = groups.get(gid, {})
    return _ws(g.get("title") or gid)[:60]


def _results_text(res, cx):
    """Compact summary of resultsSection: outcome measures with values and analyses, adverse events, limitations/caveats."""
    lines = []
    om = _g(res, "outcomeMeasuresModule", "outcomeMeasures", default=[]) or []
    shown = cx.cap(om, 12, "results.outcomeMeasures", floor=4)
    for i, m in enumerate(shown, 1):
        groups = {g.get("id"): g for g in (m.get("groups") or [])}
        head = f"R{i}. [{_s(m.get('type')).lower()}] {_ws(m.get('title'))}"
        meta = " | ".join(x for x in (_s(m.get("paramType")).lower(), _s(m.get("dispersionType")).lower(),
                                      _s(m.get("unitOfMeasure")), "time frame: " + _ws(m.get("timeFrame")) if m.get("timeFrame") else "") if x)
        lines.append(head + (f" ({meta})" if meta else ""))
        if m.get("description"):
            lines.append("   what: " + cx.clip(m["description"], 300, "results.outcomeDescription"))
        for d in (m.get("denoms") or [])[:1]:
            cnt = ", ".join(f"{_group_label(groups, c.get('groupId'))}={c.get('value')}" for c in (d.get("counts") or []))
            if cnt:
                lines.append(f"   analysed ({_s(d.get('units')) or 'participants'}): {cnt}")
        for c in (m.get("classes") or [])[:4]:
            for cat in (c.get("categories") or [])[:4]:
                vals = "; ".join(
                    f"{_group_label(groups, x.get('groupId'))}: {x.get('value')}" + (f" (spread {x['spread']})" if x.get("spread") else "")
                    + (f" [{x['lowerLimit']} to {x['upperLimit']}]" if x.get("lowerLimit") else "")
                    for x in (cat.get("measurements") or []))
                label = " / ".join(z for z in (_ws(c.get("title")), _ws(cat.get("title"))) if z)
                lines.append("   values" + (f" ({label})" if label else "") + ": " + cx.clip(vals, 400, "results.values"))
        for a in (m.get("analyses") or [])[:3]:
            bits = [f"{k}={_s(a.get(k))}" for k in ("statisticalMethod", "paramType", "paramValue", "pValue", "ciPctValue", "ciLowerLimit", "ciUpperLimit", "nonInferiorityType") if a.get(k)]
            if bits:
                lines.append("   analysis: " + "; ".join(bits))
    ae = res.get("adverseEventsModule") or {}
    if ae:
        evg = ae.get("eventGroups") or []
        lines.append("ADVERSE EVENTS (registry): " + cx.clip(_s(ae.get("description")), 300, "results.adverseEvents") +
                     (f" Frequency threshold {ae.get('frequencyThreshold')}%." if ae.get("frequencyThreshold") else ""))
        for g in evg[:6]:
            lines.append(f"   {_ws(g.get('title'))[:60]}: serious {g.get('seriousNumAffected')}/{g.get('seriousNumAtRisk')}, other {g.get('otherNumAffected')}/{g.get('otherNumAtRisk')}")
        ser = ae.get("seriousEvents") or []
        terms = cx.cap(ser, 10, "results.seriousEventTerms", floor=3)
        if terms:
            lines.append("   serious event terms: " + "; ".join(_ws(t.get("term")) for t in terms))
    mi = res.get("moreInfoModule") or {}
    lim = _g(mi, "limitationsAndCaveats", "description")
    if lim:
        lines.append("LIMITATIONS AND CAVEATS (as reported by the sponsor): " + cx.clip(lim, 800, "results.limitations"))
    ca = mi.get("certainAgreement") or {}
    if ca:
        lines.append(f"AGREEMENTS: PI is a sponsor employee = {ca.get('piSponsorEmployee')}; restrictive agreement = {ca.get('restrictiveAgreement')}")
    pf = _g(res, "participantFlowModule", "periods", default=[]) or []
    if pf:
        done = []
        for p in pf[:2]:
            for ms in (p.get("milestones") or []):
                if _s(ms.get("type")).upper() in ("STARTED", "COMPLETED"):
                    done.append(f"{_ws(p.get('title'))[:30]} {_s(ms.get('type')).lower()}: " + ", ".join(f"{c.get('groupId')}={c.get('numSubjects')}" for c in (ms.get("achievements") or [])))
        if done:
            lines.insert(0, "PARTICIPANT FLOW: " + " | ".join(done)[:600])
    return lines


def _build(study, cx):
    ps = study.get("protocolSection") or {}
    ident, status, spons = ps.get("identificationModule") or {}, ps.get("statusModule") or {}, ps.get("sponsorCollaboratorsModule") or {}
    design, desc = ps.get("designModule") or {}, ps.get("descriptionModule") or {}
    arms, outs = ps.get("armsInterventionsModule") or {}, ps.get("outcomesModule") or {}
    elig, refs, loc = ps.get("eligibilityModule") or {}, ps.get("referencesModule") or {}, ps.get("contactsLocationsModule") or {}
    has_results = bool(study.get("hasResults"))
    L, sections = [], []

    L.append(f"NCT ID: {_s(ident.get('nctId'))}" + (f" (also {_ws(ident.get('acronym') or _g(ident, 'orgStudyIdInfo', 'id'))})" if ident.get("acronym") else ""))
    L.append("Title: " + _ws(ident.get("briefTitle")))
    if ident.get("officialTitle"):
        L.append("Official title: " + cx.clip(ident["officialTitle"], 500, "officialTitle"))
    L.append(f"Overall status: {_s(status.get('overallStatus'))} (verified {_s(status.get('statusVerifiedDate')) or 'date not stated'})"
             + (f"; why stopped: {_ws(status.get('whyStopped'))}" if status.get("whyStopped") else ""))
    L.append(f"Dates: start {_date(status.get('startDateStruct'))}; primary completion {_date(status.get('primaryCompletionDateStruct'))}; "
             f"completion {_date(status.get('completionDateStruct'))}; first posted {_date(status.get('studyFirstPostDateStruct'))}; last update posted {_date(status.get('lastUpdatePostDateStruct'))}")
    L.append(f"Sponsor: {_ws(_g(spons, 'leadSponsor', 'name'))} ({_s(_g(spons, 'leadSponsor', 'class'))}); responsible party: {_s(_g(spons, 'responsibleParty', 'type'))}"
             + (f" {_ws(_g(spons, 'responsibleParty', 'investigatorFullName'))} ({_ws(_g(spons, 'responsibleParty', 'investigatorAffiliation'))})" if _g(spons, "responsibleParty", "investigatorFullName") else ""))
    collabs = [_ws(c.get("name")) for c in (spons.get("collaborators") or [])]
    if collabs:
        L.append("Collaborators: " + "; ".join(collabs[:12]))
    ov = ps.get("oversightModule") or {}
    L.append(f"Oversight: data monitoring committee = {ov.get('oversightHasDmc')}; FDA-regulated drug = {ov.get('isFdaRegulatedDrug')}; FDA-regulated device = {ov.get('isFdaRegulatedDevice')}")
    sections.append("identity")

    mk = _g(design, "designInfo", "maskingInfo") or design.get("maskingInfo") or {}
    L.append("DESIGN: " + "; ".join(x for x in (
        f"type {_s(design.get('studyType'))}", f"phase {', '.join(design.get('phases') or []) or 'n/a'}",
        f"allocation {_s(_g(design, 'designInfo', 'allocation'))}", f"model {_s(_g(design, 'designInfo', 'interventionModel'))}",
        f"purpose {_s(_g(design, 'designInfo', 'primaryPurpose'))}", f"masking {_s(mk.get('masking'))} ({', '.join(mk.get('whoMasked') or []) or 'who not stated'})",
        f"enrollment {_g(design, 'enrollmentInfo', 'count')} ({_s(_g(design, 'enrollmentInfo', 'type')).lower() or 'type not stated'})") if x))
    if mk.get("maskingDescription"):
        L.append("Masking description: " + cx.clip(mk["maskingDescription"], 500, "maskingDescription"))
    conds = (ps.get("conditionsModule") or {}).get("conditions") or []
    if conds:
        L.append("Conditions: " + "; ".join(_ws(c) for c in conds[:10]))
    sections.append("design")

    L.append("BRIEF SUMMARY: " + cx.clip(desc.get("briefSummary"), 3000, "briefSummary"))
    if desc.get("detailedDescription"):
        L.append("DETAILED DESCRIPTION: " + cx.clip(desc["detailedDescription"], 5000, "detailedDescription"))
    sections.append("description")

    for a in cx.cap(arms.get("armGroups") or [], 12, "arms", floor=4):
        L.append(f"ARM [{_s(a.get('type'))}] {_ws(a.get('label'))}: " + cx.clip(a.get("description"), 500, "armDescription") +
                 (f" Interventions: {', '.join(a.get('interventionNames') or [])}" if a.get("interventionNames") else ""))
    for it in cx.cap(arms.get("interventions") or [], 10, "interventions", floor=4):
        L.append(f"INTERVENTION [{_s(it.get('type'))}] {_ws(it.get('name'))}: " + cx.clip(it.get("description"), 400, "interventionDescription"))
    sections.append("arms")

    for i, o in enumerate(outs.get("primaryOutcomes") or [], 1):   # never dropped
        L.append(f"PRIMARY OUTCOME {i}: {_ws(o.get('measure'))} | time frame: {_ws(o.get('timeFrame'))} | " + cx.clip(o.get("description"), 800, "primaryOutcomeDescription"))
    sec = outs.get("secondaryOutcomes") or []
    for i, o in enumerate(cx.cap(sec, 20, "secondaryOutcomes", floor=6), 1):
        L.append(f"SECONDARY OUTCOME {i}: {_ws(o.get('measure'))} | time frame: {_ws(o.get('timeFrame'))} | " + cx.clip(o.get("description"), 300, "secondaryOutcomeDescription"))
    oth = outs.get("otherOutcomes") or []
    for i, o in enumerate(cx.cap(oth, 10, "otherOutcomes", floor=3), 1):
        L.append(f"OTHER OUTCOME {i}: {_ws(o.get('measure'))} | time frame: {_ws(o.get('timeFrame'))} | " + cx.clip(o.get("description"), 250, "otherOutcomeDescription"))
    sections.append("primaryOutcomes")

    if elig:
        L.append(f"ELIGIBILITY: sex {_s(elig.get('sex'))}; ages {_s(elig.get('minimumAge'))} to {_s(elig.get('maximumAge')) or 'no maximum stated'}; healthy volunteers {elig.get('healthyVolunteers')}")
        L.append("Criteria: " + cx.clip(elig.get("eligibilityCriteria"), 3000, "eligibilityCriteria"))
        sections.append("eligibility")
    rl = refs.get("references") or []
    if rl:
        for r in cx.cap(rl, 20, "references", floor=5):
            L.append(f"REFERENCE [{_s(r.get('type'))}] PMID {_s(r.get('pmid')) or 'none'}: " + cx.clip(r.get("citation"), 300, "referenceCitation"))
        sections.append("references")
    else:
        L.append("REFERENCES: none listed in the registry record")

    hdr = [f"REGISTRY FIELD hasResults: {'TRUE (results posted' if has_results else 'FALSE (no results posted'}"
           + (f"; first posted {_date(status.get('resultsFirstPostDateStruct'))})" if has_results else ")")]
    res = study.get("resultsSection") or {}
    if has_results and res:
        L.append("RESULTS POSTED IN THE REGISTRY (compact):")
        L.extend(_results_text(res, cx))
        sections.append("results")
    elif has_results:
        L.append("RESULTS: the registry says results are posted but the results section was not available to this tool.")
        cx.omitted.append({"section": "results", "shown": 0, "total": 1})

    sites = loc.get("locations") or []
    countries = sorted({_ws(s.get("country")) for s in sites if s.get("country")})
    L.append(f"SITES: {len(sites)} site(s)" + (f" in {', '.join(countries)}" if countries else "") + " (addresses and contacts are deliberately not included)")
    return hdr, L, sections, has_results, _s(ident.get("nctId"))


def build_ctgov_record(study, budget=BUDGET):
    """study: the full ClinicalTrials.gov API v2 JSON (protocolSection, resultsSection, hasResults ...). Returns (text, meta)."""
    best = None
    for sc in SCALES:
        cx = _Ctx(sc)
        hdr, lines, sections, has_results, nct = _build(study, cx)
        body = "\n".join(lines)
        best = (cx, hdr, body, sections, has_results, nct, sc)
        if len(body) + 600 <= budget:
            break
    cx, hdr, body, sections, has_results, nct, sc = best
    cut_tail = 0
    if len(body) + 600 > budget:                       # last resort: still too long after the smallest scale
        cut_tail = len(body) - (budget - 600)
        body = body[: budget - 600]
        cx.omitted.append({"section": "tail of record", "shown": len(body), "total": len(body) + cut_tail})
    omitted_sections = [o["section"] for o in cx.omitted]
    critical = any(o["section"].split(".")[0] in CRITICAL or o["section"] == "tail of record" for o in cx.omitted)
    if omitted_sections:
        state = "TRUNCATED"
        note = "NOT SHOWN: " + "; ".join(f"{o['section']} ({o['shown']} of {o['total']} shown)" for o in cx.omitted)
    elif cx.shortened:
        state = "SHORTENED"
        note = "long text fields were shortened: " + ", ".join(cx.shortened)
    else:
        state, note = "COMPLETE", "nothing was left out"
    header = ("SOURCE: ClinicalTrials.gov API v2 record, rebuilt by this pipeline as compact structured text (site addresses omitted)\n"
              f"RECORD COMPLETENESS: {state} - {note}\n"
              f"CRITICAL SECTIONS MISSING: {'yes' if critical else 'no'}\n" + "\n".join(hdr) + "\n---\n")
    text = header + body
    meta = {"sourceKind": "ctgov", "nctId": nct, "hasResults": has_results, "chars": len(text), "completeness": state,
            "truncated": bool(omitted_sections), "criticalOmitted": critical, "omitted": cx.omitted, "shortened": cx.shortened,
            "sectionsPresent": sections, "scale": sc}
    return text, meta


def finish_pubmed_record(raw, pmid, cap=20000):
    """PubMed abstract text from efetch, with the same completeness header. Abstracts are short; the cap is a safety net, and a cut is reported."""
    raw = raw or ""
    truncated = len(raw) > cap
    body = raw[:cap]
    state = "TRUNCATED" if truncated else "COMPLETE"
    note = f"{len(raw) - cap} characters at the end were not shown (this includes the conflict-of-interest statement)" if truncated else "nothing was left out"
    header = ("SOURCE: PubMed abstract record (NCBI efetch, text format)\n"
              f"RECORD COMPLETENESS: {state} - {note}\n"
              f"CRITICAL SECTIONS MISSING: {'yes' if truncated else 'no'}\n---\n")
    m_lang = re.search(r"\[Article in ([A-Za-z ]+?)(?:;|\])", raw)
    meta = {"sourceKind": "pubmed", "pmid": str(pmid), "chars": len(header) + len(body), "completeness": state, "truncated": truncated, "nonEnglishAbstract": bool(m_lang and m_lang.group(1).strip().lower() != "english"),
            "criticalOmitted": truncated, "omitted": ([{"section": "tail of record", "shown": cap, "total": len(raw)}] if truncated else []), "shortened": [],
            "hasResults": None}
    return header + body, meta


def unavailable_record(reason):
    """Headline-only items (news wire) and failed fetches. The model is told explicitly that no primary record exists."""
    text = ("SOURCE: none\nRECORD COMPLETENESS: UNAVAILABLE - " + reason + "\nCRITICAL SECTIONS MISSING: yes\n---\n"
            "(no primary record is available: evaluate from the item metadata alone; confidence must be low and nothing may be stated as verified)")
    return text, {"sourceKind": "none", "chars": len(text), "completeness": "UNAVAILABLE", "truncated": False, "criticalOmitted": True,
                  "omitted": [], "shortened": [], "hasResults": None}


HDR_RE = re.compile(r"^RECORD COMPLETENESS:\s*(COMPLETE|SHORTENED|TRUNCATED|UNAVAILABLE)\b", re.M)
CRIT_RE = re.compile(r"^CRITICAL SECTIONS MISSING:\s*(yes|no)\b", re.M)
RES_RE = re.compile(r"^REGISTRY FIELD hasResults:\s*(TRUE|FALSE)\b", re.M)


def parse_header(text):
    """Read the completeness header back from a record text. Returns None when the text has no header (an unknown or hand-made record)."""
    m = HDR_RE.search(text or "")
    if not m:
        return None
    c, r = CRIT_RE.search(text), RES_RE.search(text)
    return {"completeness": m.group(1), "truncated": m.group(1) == "TRUNCATED", "criticalOmitted": bool(c and c.group(1) == "yes"),
            "hasResults": (r.group(1) == "TRUE") if r else None}
