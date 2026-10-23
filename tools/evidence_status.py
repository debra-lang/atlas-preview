#!/usr/bin/env python3
"""Evidence-status notices for treatment pages (static build). The interactive page (js/app.js, evidenceStatusHtml / attachPendingEvidence) shows the same notices with the same words;
tests/test_evidence_status.py checks that every fixed phrase below also appears in js/app.js, so the two cannot drift apart.

Three notices, all derived from data the site already holds, none of them an assessment:
  provisional   a study cited for the treatment has a retraction, partial retraction or expression-of-concern notice (data/studies.json -> integrityNotice). The rating is NOT changed.
  pending       records listed (data/listings.json) after the treatment's evidenceThrough date whose TITLE contains words linked to the treatment. Matched by keyword, not read, not assessed.
  stale         the assessment's evidenceThrough date is more than a year old.
"""
import html
from datetime import date

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)

SEVERE = ("retracted", "partially-retracted", "expression-of-concern")
STALE_DAYS = 365
MAX_SHOWN = 5

# fixed phrases (the approved public wording lives here and in js/app.js)
W_PROV_TITLE = "Rating provisional."
W_PROV_LEAD = "A study cited for this treatment has a"
W_PROV_TAIL = "Tinnitus Evidence has not changed this rating because of the notice. It stays as published and will be reconsidered at the next scheduled reassessment."
W_PEND_TITLE = "Newer records not yet assessed."
W_PEND_LEAD = "This treatment’s evidence was last assessed through"
W_PEND_MID = "record(s) with words linked to this treatment in the title have been listed. Tinnitus Evidence has not read or assessed them, and the rating shown is unchanged. Records are matched by keyword, so some may not concern this treatment."
W_STALE_TITLE = "This assessment may be out of date."
W_STALE_TAIL = "Newer research may exist that it does not reflect."


def _long(iso):
    try:
        d = date.fromisoformat(str(iso)[:10])
        return d.strftime("%B %d, %Y").replace(" 0", " ")
    except ValueError:
        return str(iso or "")


def provisional(t, studies_by_id):
    """[(study, integrityNotice)] for the cited studies that carry a severe notice."""
    out = []
    for sid in t.get("studies", []) or []:
        s = studies_by_id.get(sid)
        n = (s or {}).get("integrityNotice") or {}
        if s and n.get("severity") in SEVERE:
            out.append((s, n))
    return out


def pending(t, listings):
    thr = str(t.get("evidenceThrough") or "")
    # only records that are clearly about tinnitus (listing tier 2: tinnitus in the title, a MeSH heading, a registry title/condition/primary outcome) count as newer evidence for a treatment
    rows = [e for e in (listings or {}).get("items", []) if t.get("id") in (e.get("treatments") or []) and thr and str(e.get("listedOn", "")) > thr and (e.get("tier") or 2) <= 2]
    return sorted(rows, key=lambda e: (e["listedOn"], e["key"]), reverse=True)


def is_stale(t, today=None):
    try:
        return (( today or date.today()) - date.fromisoformat(str(t.get("evidenceThrough"))[:10])).days > STALE_DAYS
    except ValueError:
        return False


def status_html(t, studies_by_id, listings, today=None):
    out = []
    for s, n in provisional(t, studies_by_id):
        sev = str(n["severity"]).replace("-", " ")
        out.append(f'<div class="notice" role="note" aria-label="Rating provisional"><strong>{W_PROV_TITLE}</strong> {W_PROV_LEAD} {E(sev)} notice: '
                   f'<a href="research/{E(s["id"])}/">{E(s.get("title", ""))}</a>. {W_PROV_TAIL}</div>')
    rows = pending(t, listings)
    if rows:
        li = "".join(f'<li><a href="{E(e["url"])}" rel="noopener" target="_blank">{E(e["title"])}</a> <span class="muted">— {E(e.get("source", ""))}, {E(e.get("date", ""))}</span></li>'
                     for e in rows[:MAX_SHOWN])
        more = f' <span class="small">and {len(rows) - MAX_SHOWN} more are on the <a href="research.html#listings">research page</a>.</span>' if len(rows) > MAX_SHOWN else ""
        out.append(f'<div class="notice" role="note" aria-label="Newer records not yet assessed"><strong>{W_PEND_TITLE}</strong> {W_PEND_LEAD} {E(_long(t.get("evidenceThrough")))}. '
                   f'Since then {len(rows)} {W_PEND_MID}<ul class="small">{li}</ul>{more}</div>')
    if is_stale(t, today):
        out.append(f'<div class="notice" role="note" aria-label="Assessment may be out of date"><strong>{W_STALE_TITLE}</strong> It includes evidence through '
                   f'{E(_long(t.get("evidenceThrough")))}. {W_STALE_TAIL}</div>')
    return "".join(out)
