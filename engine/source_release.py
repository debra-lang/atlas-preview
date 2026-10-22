#!/usr/bin/env python3
"""Tinnitus Evidence: the narrowly restricted SOURCE-VERIFIED RELEASE path (ships SWITCHED OFF).

Purpose: a clean, low-risk study that the code accepts in every respect but that the MODEL declined to call "verified" (the P3 prompt makes the model cautious) would otherwise be held for
good, because a hold can never be approved into publication. This path lets the site editor publish such an item after DOCUMENTED verification against the source. It is an editorial
path, not a clinical one: the published item says so, and the editor's approval is never a substitute for clinical review.

It can NEVER override: a Level 3 trigger or flag, a safety signal, an unsupported claim (number, date, novelty/authority term, name, outcome domain, compound conflict-of-interest
label), inadequate or thin evidence, a code override of the model, a low confidence, a truncated or incomplete record, a non-English abstract, a major or rating-related change, a tracked
treatment, a non-research category, a notice, a pause or topic hold, a non-PubMed item. Eligibility is computed by code from the stored evaluation, at the time the decision is RECORDED and
again when it is APPLIED. The path is off unless engine/eval_settings.json has "sourceVerifiedRelease": true (exactly), and at most "sourceVerifiedReleaseMaxPerRun" (default 3) items
can be released per weekly run.
"""
import hashlib, json, re

REQUIRED_CHECKS = ("sentences", "numbers-and-dates", "claims", "no-advice", "no-safety-or-rating-implication", "conflict-of-interest")
CHECK_TEXT = {"sentences": "every sentence of the public text compared with the abstract or record", "numbers-and-dates": "every number and date compared with the source",
              "claims": "no novelty, priority, authority or interpretation the source does not state", "no-advice": "no advice or recommendation addressed to patients or clinicians",
              "no-safety-or-rating-implication": "nothing about safety, regulatory status or any treatment rating", "conflict-of-interest": "the funding and conflict-of-interest wording compared with the source"}
LABEL = "Reviewed by the site editor against the source record. This is an editorial check, not a clinical review."
OK_IMPORTANCE = ("Does Not Change Current Evidence", "Interesting but Early", "Confirms Previous Evidence", "Negative Result")
UNTRACKED = ("", "none", "new-treatment-candidate")


def settings_on(settings):
    return isinstance(settings, dict) and settings.get("sourceVerifiedRelease") is True


def max_per_run(settings):
    try:
        return max(1, min(10, int((settings or {}).get("sourceVerifiedReleaseMaxPerRun", 3))))
    except (TypeError, ValueError):
        return 3


def eligibility(entry, tracked_ids=(), settings=None):
    """-> (eligible, [reasons it is not]). Pure; reads only the stored entry."""
    why = []
    if not settings_on(settings):
        why.append("the source-verified release path is switched off (engine/eval_settings.json)")
    item = (entry or {}).get("item") or {}
    ev = item.get("evaluation") or {}
    sc = ev.get("sourceChecks") if isinstance(ev.get("sourceChecks"), dict) else {}
    if (entry or {}).get("proposedRoute") != "hold":
        why.append("the proposed outcome is not a plain hold")
    if item.get("kind") != "study" or not str(item.get("id", "")).startswith("pubmed-"):
        why.append("only PubMed study items are eligible")
    if item.get("notice") or item.get("intelligenceOnly"):
        why.append("notices and news-wire items are never eligible")
    if ev.get("factuallyVerified") is not False or "factuallyVerifiedModel" in ev:
        why.append("the hold must be solely the model's own 'not verified' (a code override or a model 'true' is not this case)")
    if not sc:
        why.append("no automated source checks recorded")
    else:
        ea = sc.get("evidenceAdequacy") or {}
        if ea.get("level") != "adequate" or ea.get("adequate") is not True:
            why.append(f"evidence adequacy is '{ea.get('level', 'not assessed')}', not 'adequate'")
        from grounding import source_checks_pass
        ok, reason = source_checks_pass(ev)
        if not ok:
            why.append("automated source checks fail: " + reason)
        for k, label in (("ungroundedNames", "names not in the record"), ("ungroundedDomainTerms", "outcome domains not in the record"), ("advisoryNumbers", "advisory numbers")):
            if sc.get(k):
                why.append(f"advisory not clear: {label}")
        if sc.get("compoundCoiLabel"):
            why.append("compound conflict-of-interest label")
        if sc.get("nonEnglishAbstract"):
            why.append("the abstract is not in English (cannot be checked by code)")
        if not sc.get("recordComplete") or sc.get("criticalOmitted") or sc.get("completeness") != "COMPLETE":
            why.append("the record is not complete")
    if ev.get("escalation"):
        why.append("a Level 3 trigger or reviewer flag is present: " + ", ".join(sorted({t.get("kind", "?") for t in ev["escalation"]})))
    if ev.get("confidence") not in ("moderate", "high"):
        why.append(f"confidence is '{ev.get('confidence')}'")
    if ev.get("changeClass") != "routine" or ev.get("proposedScoreChange") or ev.get("proposedRankChange"):
        why.append("a major change or a score/rank proposal is present")
    if ev.get("safetySignal"):
        why.append("a safety signal is flagged")
    if ev.get("notRelevant") or str(ev.get("relevanceCategory")) not in ("1", "2"):
        why.append("not a research-feed category (1 or 2)")
    if ev.get("importance") not in OK_IMPORTANCE:
        why.append(f"importance '{ev.get('importance')}' is not eligible")
    aff = ev.get("affectedTreatment")
    if aff not in UNTRACKED or (aff and aff in set(tracked_ids)):
        why.append("the item bears on a tracked treatment")
    if (item.get("evalInput") or {}).get("hasResults"):
        why.append("registry results are posted")
    return (not why), why


def public_text(item):
    """The text that would become public, exactly as the weekly item builds it (lazy import: weekly_cycle imports this module's callers)."""
    import weekly_cycle
    w = weekly_cycle.Cycle.weekly_item(None, item, item.get("evaluation") or {}, under_eval=False)
    return {k: w.get(k) for k in ("title", "importance", "whyMatters", "summary", "detail", "url", "kind", "treatment")}


def text_hash(item):
    return hashlib.sha256(json.dumps(public_text(item), sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def validate_attestation(dec, entry):
    """-> list of problems (empty = documented verification is complete and bound to this exact text and this exact source)."""
    item = (entry or {}).get("item") or {}
    bad = []
    pmid = str(item.get("id", "")).split("-", 1)[-1]
    if str(dec.get("pmid", "")).strip() != pmid or not pmid.isdigit():
        bad.append("the PMID typed does not match the item's PMID (open the source record and copy it)")
    if dec.get("textHash") != text_hash(item):
        bad.append("the text hash does not match the public text (the text changed or the hash was not copied from the export)")
    if sorted(set(dec.get("checked") or [])) != sorted(REQUIRED_CHECKS):
        bad.append("all six verification checks must be confirmed: " + ", ".join(REQUIRED_CHECKS))
    if dec.get("notClinicalReview") is not True:
        bad.append("the decision must state that this is not a clinical review")
    rv = str(dec.get("reviewer", "")).strip()
    if not 2 <= len(rv) <= 40:
        bad.append("a reviewer role or initials (2-40 characters) is required; the file is public, so use a role such as 'site editor', not a full name")
    return bad


def release(dec, entry, tracked_ids, settings, released_so_far=0):
    """-> (ok, problems, item) ; item carries the audit record and the public label when ok."""
    ok, why = eligibility(entry, tracked_ids, settings)
    problems = list(why) + validate_attestation(dec, entry)
    if released_so_far >= max_per_run(settings):
        problems.append(f"the per-run limit of {max_per_run(settings)} source-verified releases is reached; this decision stays for the next run")
    if problems:
        return False, problems, None
    import copy
    item = copy.deepcopy(entry["item"])
    item["releasedAfterSourceCheck"] = {"reviewer": str(dec["reviewer"]).strip(), "textHash": dec["textHash"], "decidedAt": dec.get("decidedAt"), "checks": list(REQUIRED_CHECKS)}
    return True, [], item
