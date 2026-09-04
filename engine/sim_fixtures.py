"""Fixtures for `weekly_cycle.py --simulate` — the required end-to-end scenarios.
Items carry canned evaluations so the full routing logic runs without API calls.
Set SIM_MODE=quiet to simulate a week with no new research."""
import os

def _ev(**kw):
    base = {
        "whatIsNew": "", "notRelevant": False, "affectedTreatment": "", "studyType": "RCT",
        "studyQuality": "moderate", "population": "Adults with chronic subjective tinnitus",
        "sampleSize": "Not reported", "controlQuality": "no-control", "randomized": True,
        "blinded": "unclear", "primaryEndpoint": "Not reported", "secondaryEndpoints": "Not reported",
        "comparisonType": "Not reported", "numericalResult": "none reported",
        "loudnessEffect": "none — loudness was not measured", "distressEffect": "none",
        "otherOutcomes": "Not reported", "clinicalSignificance": "Not reported",
        "safetyObservations": "Not reported", "safetySignal": False, "mainLimitations": [],
        "conflictOfInterest": "unclear", "regulatorySource": "n/a",
        "evidenceDirection": "no-meaningful-change", "changeClass": "routine",
        "proposedScoreChange": None, "proposedRankChange": None,
        "importance": "Does Not Change Current Evidence", "weeklyTitle": "", "whyMatters": "",
        "factuallyVerified": True, "factuallyVerifiedReason": "identifier + trusted source",
        "summaryForAdmin": "", "confidence": "high", "duplicateOf": None,
    }
    base.update(kw)
    return base


ROUTINE = {  # -> should PUBLISH automatically (Class A)
    "id": "pubmed-90000001", "kind": "study", "source": "JAMA Otolaryngology",
    "title": "Twelve-month follow-up of internet-delivered CBT for tinnitus",
    "date": "2026-09-01", "url": "https://pubmed.ncbi.nlm.nih.gov/90000001/",
    "summary": "sim", "treatment": "", "proposal": "", "why": "",
    "evaluation": _ev(
        whatIsNew="A 12-month follow-up of an existing iCBT trial reports maintained benefit.",
        affectedTreatment="digital-cbt", sampleSize="120", controlQuality="active-control",
        blinded="single", primaryEndpoint="TFI at 12 months", comparisonType="between-group",
        numericalResult="TFI difference 8.1 points (95% CI 2.0-14.2) favoring iCBT at 12 months.",
        distressEffect="moderate — TFI benefit maintained at one year",
        clinicalSignificance="Below the 13-point TFI threshold on average but durable.",
        safetyObservations="No adverse events reported in this study.",
        conflictOfInterest="independent", evidenceDirection="strengthens",
        importance="Confirms Previous Evidence",
        weeklyTitle="iCBT benefit holds at 12 months in follow-up of a randomized trial",
        whyMatters="One of the open questions about therapy-by-app was whether the benefit lasts. This follow-up says it can.",
        summaryForAdmin="Routine confirmatory follow-up; no rating change warranted."),
}

DUPLICATE = {  # -> should be REJECTED as duplicate (title already in the published weekly feed)
    "id": "feed-fakejournal-dup", "kind": "study", "source": "Medical News Aggregator",
    "title": "First double-blind sham-app-controlled tinnitus RCT (JAMA Otolaryngology, online May 7, 2026)",
    "date": "2026-09-02", "url": "https://pubmed.ncbi.nlm.nih.gov/38888888/",
    "summary": "sim duplicate", "treatment": "", "proposal": "", "why": "",
    "evaluation": _ev(duplicateOf="kyorin-2026-app"),
}

CONTRADICTORY_RCT = {  # -> MAJOR: held; fact verified -> publishes flagged "under evaluation"
    "id": "pubmed-90000002", "kind": "study", "source": "The Lancet",
    "title": "Large independent sham-controlled trial of bimodal tongue stimulation finds no benefit",
    "date": "2026-09-01", "url": "https://pubmed.ncbi.nlm.nih.gov/90000002/",
    "summary": "sim", "treatment": "", "proposal": "", "why": "",
    "evaluation": _ev(
        whatIsNew="The first fully independent sham-controlled RCT of bimodal tongue stimulation reports no separation from sham.",
        affectedTreatment="lenire", studyQuality="high", sampleSize="240",
        controlQuality="sham/placebo-controlled", blinded="double",
        primaryEndpoint="THI change at 12 weeks vs sham", comparisonType="between-group",
        numericalResult="THI -14.1 active vs -13.2 sham; difference 0.9 (95% CI -3.1 to 4.9), p=0.66.",
        distressEffect="none — no separation from sham in this trial",
        clinicalSignificance="Directly challenges the assumption that prior within-arm gains were device-specific.",
        conflictOfInterest="independent (public funding)", evidenceDirection="weakens",
        changeClass="major",
        proposedScoreChange={"treatment": "lenire", "from": 3, "to": 2,
                             "reason": "Independent sham-controlled null contradicts manufacturer-funded trials."},
        proposedRankChange={"treatment": "lenire", "from": 2, "to": 5, "reason": "same"},
        importance="Potentially Important",
        weeklyTitle="Independent sham-controlled trial of bimodal tongue stimulation finds no benefit over sham",
        whyMatters="This is the placebo-controlled test the field was waiting for — and it came back negative. Our rating of this treatment is now under formal re-evaluation.",
        summaryForAdmin="High-quality contradictory RCT. Score/rank downgrade proposed — must be human-resolved against TENT-A1/A2/A3 record."),
}

SAFETY_SIGNAL = {  # -> MAJOR + safety: held; verified fact publishes with prominent flag
    "id": "feed-fda-medwatch-sim1", "kind": "regulatory", "source": "FDA MedWatch safety alerts",
    "title": "FDA safety communication: reports of oral burns with tongue-stimulation devices",
    "date": "2026-09-02", "url": "https://www.fda.gov/safety/medwatch/sim-example",
    "summary": "sim", "treatment": "", "proposal": "", "why": "",
    "evaluation": _ev(
        whatIsNew="A regulator flagged device-related adverse event reports for a treatment category we track.",
        affectedTreatment="lenire", studyType="regulatory record", studyQuality="not-a-study",
        safetyObservations="FDA reports a cluster of oral mucosal injury reports; causality not established.",
        safetySignal=True, regulatorySource="authoritative (FDA/EMA/registry record)",
        evidenceDirection="weakens", changeClass="major",
        importance="Potentially Important",
        weeklyTitle="FDA safety communication concerning tongue-stimulation devices",
        whyMatters="A regulator is looking at adverse-event reports. That deserves attention — and a careful read of the actual communication, not a headline.",
        factuallyVerifiedReason="Authoritative regulator source",
        summaryForAdmin="Potential safety signal — held for safety-assessment review; must not be summarized away."),
}

COMPANY_PR = {  # -> routine but labeled Company-reported development
    "id": "feed-businesswire-sim1", "kind": "news", "source": "Company announcement",
    "title": "Sound Pharmaceuticals announces NDA submission timeline for SPI-1005",
    "date": "2026-09-02", "url": "https://www.businesswire.com/news/sim-example",
    "summary": "sim", "treatment": "", "proposal": "", "why": "",
    "evaluation": _ev(
        whatIsNew="The company says it plans an NDA submission; no regulator has confirmed anything.",
        affectedTreatment="spi-1005", studyType="press release", studyQuality="not-a-study",
        regulatorySource="company announcement", importance="Interesting but Early",
        weeklyTitle="SPI-1005 maker announces NDA submission plans",
        whyMatters="Company plans are pipeline intelligence, not evidence — nothing changes until a regulator or a peer-reviewed paper confirms it.",
        factuallyVerifiedReason="The company did make this announcement (the fact reported is the announcement itself)",
        summaryForAdmin="Pipeline note only."),
}

UNTRUSTED_SOURCE = {  # -> HELD (uncertainty): unknown blog, no identifier
    "id": "feed-blog-sim1", "kind": "study", "source": "Wellness blog",
    "title": "Miracle supplement eliminates tinnitus in new study",
    "date": "2026-09-02", "url": "https://tinnitus-miracle-cures.example.com/post",
    "summary": "sim", "treatment": "", "proposal": "", "why": "",
    "evaluation": _ev(
        whatIsNew="A blog claims a study exists; no journal, no registry, no identifier found.",
        affectedTreatment="supplements", studyQuality="low",
        factuallyVerified=False, factuallyVerifiedReason="Unable to verify — no locatable primary source",
        confidence="low", importance="Does Not Change Current Evidence",
        weeklyTitle="Unverifiable supplement claim", whyMatters="",
        summaryForAdmin="Cannot verify the study exists."),
}


def _good_source():
    return [ROUTINE, DUPLICATE, CONTRADICTORY_RCT, SAFETY_SIGNAL, COMPANY_PR, UNTRUSTED_SOURCE]


def _failing_source():
    raise ConnectionError("simulated: NIH news feed timed out")


if os.environ.get("SIM_MODE") == "quiet":
    SCANNERS = [("PubMed (sim)", lambda: []), ("ClinicalTrials.gov (sim)", lambda: []),
                ("Watched feeds (sim)", _failing_source)]
    TRIAL_FIXTURE = {}
else:
    SCANNERS = [("PubMed (sim)", _good_source), ("ClinicalTrials.gov (sim)", lambda: []),
                ("Watched feeds (sim)", _failing_source)]
    # trial status change scenario: etanercept trial completes
    TRIAL_FIXTURE = {"NCT04066348": "Completed"}
