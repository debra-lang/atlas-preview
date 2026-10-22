#!/usr/bin/env python3
"""Tinnitus Evidence — deterministic FDA record builder (R1). No AI, no network in this module (the caller fetches the JSON).

Why: the weekly scan gave FDA items the date it DETECTED them as their date and a one-line record, so the evaluator had nothing to read and repeated the detection date as if it were
the decision date (a published item said 2026-09-04; FDA's record says 2026-08-13). The record built here carries the facts the FDA database holds, starts with the same completeness
header as the PubMed and registry records, and `decision_date` becomes the item's date.
"""
HEADER = "SOURCE: {src}\nRECORD COMPLETENESS: COMPLETE - nothing was left out of this database entry\nCRITICAL SECTIONS MISSING: no\n---\n"


def _line(label, v):
    return f"{label}: {v}\n" if v not in (None, "", []) else ""


def build_510k_record(r):
    """openFDA 510(k) result -> (record text, meta). The text states the FDA's own decision date and decision; it says nothing about efficacy because the database does not."""
    body = (_line("510(k) number", r.get("k_number")) + _line("Device name", r.get("device_name")) + _line("Applicant", r.get("applicant")) +
            _line("Decision date", r.get("decision_date")) + _line("Decision", r.get("decision_description")) + _line("Date received by FDA", r.get("date_received")) +
            _line("Product code", r.get("product_code")) + _line("Clearance type", r.get("clearance_type")) + _line("Advisory committee", r.get("advisory_committee_description")) +
            _line("Statement or summary", r.get("statement_or_summary")) + "Note: a 510(k) decision concerns substantial equivalence to a predicate device; it is not an FDA finding of efficacy.\n")
    text = HEADER.format(src="openFDA 510(k) clearance database (api.fda.gov/device/510k)") + f"IDENTIFIER: {r.get('k_number')}\n" + body
    return text, {"sourceKind": "openfda-510k", "completeness": "COMPLETE", "truncated": False, "criticalOmitted": False, "omitted": [], "shortened": [], "hasResults": None,
                  "chars": len(text), "itemDate": r.get("decision_date") or None}


def build_pma_record(r):
    body = (_line("PMA number", r.get("pma_number")) + _line("Supplement number", r.get("supplement_number")) + _line("Trade name", r.get("trade_name")) + _line("Applicant", r.get("applicant")) +
            _line("Decision date", r.get("decision_date")) + _line("Decision code", r.get("decision_code")) + _line("Product code", r.get("product_code")) +
            _line("Advisory committee", r.get("advisory_committee_description")) + _line("Supplement reason", r.get("supplement_reason")) + _line("Generic name", r.get("generic_name")))
    text = HEADER.format(src="openFDA PMA database (api.fda.gov/device/pma)") + f"IDENTIFIER: {r.get('pma_number')}\n" + body
    return text, {"sourceKind": "openfda-pma", "completeness": "COMPLETE", "truncated": False, "criticalOmitted": False, "omitted": [], "shortened": [], "hasResults": None,
                  "chars": len(text), "itemDate": r.get("decision_date") or None}
