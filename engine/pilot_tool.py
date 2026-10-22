#!/usr/bin/env python3
"""Tinnitus Evidence - the 24-record pilot, owner side (local tool; nothing here is paid, nothing is published, no key is used).

  python pilot_tool.py draw      --out <private folder>       draw 24 unseen real PubMed records with a seed only you know (asked at a hidden prompt)
  python pilot_tool.py sheet     --dir <private folder>       write checklist.html: the BLIND checklist (title + abstract + six yes/no boxes; no pipeline output)
  python pilot_tool.py reconcile --dir <private folder> --answers <pilot-checklist.csv>
                                                             compare your answers with an automatic reading of the same text; write reconcile.html for the (few) disagreements
                                                             and, when there are none, pilot-final.csv directly

Design (owner decision 21 Oct 2026: one human checker, six yes/no source facts, blind first):
  * the checklist shows only source text, so the pipeline's answers cannot anchor your answers; the automatic reading is shown only afterwards and only where it disagrees with you;
  * the automatic reading uses the pipeline's own cue patterns (grounding.py) and safety lexicon (escalation.py), so a disagreement means 'look again', never 'the code is right';
  * the folder holds public PubMed text only, but keep it OUTSIDE the repository and iCloud-shared project folders: the list of records is the test, and the draw must stay private."""
import argparse, csv, getpass, hashlib, html, json, os, random, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import escalation, gold_sampler, grounding, language_screen, notices, registry_record  # noqa: E402

PLAN = {"notice": 3, "non-english": 3, "safety-query": 4, "short": 3, "review-case": 3, "ordinary": 8}   # = 24
QUESTIONS = [
    ("sample_size", "Sample size stated", "A number of participants, animals, records or cases is stated (\"83 participants\", \"n=12 per group\", \"three patients\")."),
    ("design", "Design stated in words", "The design or method is named (randomised, controlled, cohort, cross-sectional, retrospective, survey, sham, double-blind, \"were measured with ...\"). A bare heading such as \"Methods:\" does not count."),
    ("results", "At least one result figure", "A percentage, mean, difference, p-value, confidence interval, hazard or odds ratio, sensitivity. \"Improved significantly\" without a figure is No."),
    ("safety", "Explicit safety wording", "The title or abstract states a seizure or convulsion, a serious adverse event or reaction, a device recall or safety communication, a death, suicide, life-threatening event, cardiac arrest or permanent hearing loss. A statement that there were none is No."),
    ("notice", "Is a correction, retraction or expression of concern", "The record is itself a notice (erratum, correction, retraction, expression of concern), not a study."),
    ("abstract", "Has an abstract", "There is an abstract: real sentences about the study, not only a title and authors."),
]
KEYS = [k for k, _, _ in QUESTIONS]
NOTICE_PUBTYPES = ("published erratum", "retraction of publication", "retracted publication", "expression of concern", "erratum", "corrected and republished")
SHORT_CHARS = 600


# ------------------------------------------------------------------ the automatic reading (pipeline cue patterns; used only AFTER the human pass)
def abstract_text(text):
    return "\n\n".join(language_screen.abstract_paragraphs(text))


def code_reading(rec):
    """{question: (answer 'yes'/'no', evidence snippet or '')} for one record dict {id, title, pubtypes, text}. Same patterns the pipeline's checks use."""
    title, text = rec.get("title", ""), rec.get("text", "")
    body = grounding.record_body(text)
    whole = title + "\n" + body
    out = {}
    for key, rx in (("sample_size", grounding.SAMPLE_RE), ("design", grounding.DESIGN_RE), ("results", grounding.RESULT_RE)):
        m = rx.search(whole)
        out[key] = ("yes", m.group(0)[:80]) if m else ("no", "")
    strong = escalation._hits(title + ". " + body, escalation._STRONG)
    out["safety"] = ("yes", ", ".join(strong)) if strong else ("no", "")
    pts = [str(x).lower() for x in rec.get("pubtypes", []) or []]
    is_notice = notices.looks_like_notice({"title": title}) or any(t in NOTICE_PUBTYPES for t in pts)
    out["notice"] = ("yes", "title or publication type says notice") if is_notice else ("no", "")
    at = abstract_text(text)
    letters = [c for c in at if c.isalpha()]
    dense = bool(letters) and sum(1 for c in letters if language_screen._blocks(c) == "other") / len(letters) >= 0.5      # CJK and similar scripts carry more per character
    n = len(at)
    ok = n >= 150 or (dense and n >= 50)
    out["abstract"] = ("yes", f"{n} characters of abstract text") if ok else ("no", f"{n} characters of abstract text")
    return out


# ------------------------------------------------------------------ network (read-only PubMed; replaced in tests)
def fetch_text(pmid):
    q = urllib.parse.urlencode({"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "text"})
    for k in range(5):
        try:
            time.sleep(0.4)
            raw = urllib.request.urlopen(urllib.request.Request("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + q, headers={"User-Agent": "TinnitusEvidence-pilot/1.0"}), timeout=60).read().decode("utf-8", "replace")
            return registry_record.finish_pubmed_record(raw, pmid)[0]      # exactly the text the pipeline will give the model
        except Exception:
            time.sleep(2 * (k + 1))
    raise RuntimeError("could not reach NCBI")


# ------------------------------------------------------------------ the draw
def _rng(seed, stage):
    return random.Random(hashlib.sha256((seed + "|" + stage).encode("utf-8")).hexdigest())


def plan_draw(pool, safety_pool, seed, exclude, fetch=fetch_text, plan=PLAN, max_short_tries=80):
    """Deterministic given the seed. Returns (rows, warnings). Each row: the sampler's candidate dict + stratum."""
    if len(seed) < 12:
        raise ValueError("the seed must be at least 12 characters")
    warnings = []
    special, w = gold_sampler.select_with_report(pool, seed, sum(plan[k] for k in ("notice", "non-english", "safety-query")), exclude,
                                                 special={k: plan[k] for k in ("notice", "non-english", "safety-query")}, safety_pool=safety_pool)
    warnings += w
    taken = {c["id"] for c in special}
    rest = sorted((c for c in pool if c["id"] not in exclude and c["id"] not in taken and not gold_sampler.is_notice(c) and not gold_sampler.is_non_english(c)), key=lambda c: c["id"])
    chosen = list(special)

    def take(cands, k, stratum, rng):
        cands = list(cands); rng.shuffle(cands)
        got = cands[:k]
        if len(got) < k:
            warnings.append(f"only {len(got)} of {k} requested '{stratum}' records exist in the pool")
        for c in got:
            taken.add(c["id"]); chosen.append(dict(c, stratum=stratum))
        return got
    take([c for c in rest if gold_sampler.study_type(c["pubtypes"]) in ("systematic-review", "review-other", "case-or-letter")], plan["review-case"], "review-case", _rng(seed, "review-case"))
    rng = _rng(seed, "short")
    cand = [c for c in rest if c["id"] not in taken]; rng.shuffle(cand)
    got = 0
    for c in cand[:max_short_tries]:
        if got >= plan["short"]:
            break
        try:
            n = len(abstract_text(fetch(c["id"].split("-", 1)[1])))
        except Exception:
            continue
        if n < SHORT_CHARS:
            taken.add(c["id"]); chosen.append(dict(c, stratum="short")); got += 1
    if got < plan["short"]:
        warnings.append(f"only {got} of {plan['short']} requested 'short' records were found among {min(len(cand), max_short_tries)} checked")
    ordinary = [c for c in rest if c["id"] not in taken and gold_sampler.study_type(c["pubtypes"]) in ("rct", "observational", "other")]
    rng = _rng(seed, "ordinary")
    titled = [c for c in ordinary if re.search(r"tinnit", c["title"], re.I)]
    take(titled, min(plan["ordinary"], 5), "ordinary/tinnitus-in-title", rng)
    take([c for c in ordinary if c["id"] not in taken], plan["ordinary"] - sum(1 for c in chosen if c["stratum"] == "ordinary/tinnitus-in-title"), "ordinary", rng)
    return sorted(chosen, key=lambda c: c["id"]), warnings


def cmd_draw(a):
    out = Path(a.out)
    if (HERE.parent / ".git").exists() and out.resolve().is_relative_to(HERE.parent.resolve()):
        sys.exit("STOP: write the pilot folder OUTSIDE the repository (it is public)")
    if (out / "records.json").exists():
        sys.exit(f"STOP: {out}\\records.json already exists. The draw is made once; use a new folder only with Claude's agreement.")
    seed = os.environ.get("GOLD_SEED")
    if not seed:
        seed = getpass.getpass("Private seed (12+ characters; nothing is displayed; write it down somewhere safe): ")
        if getpass.getpass("Type it again: ") != seed:
            sys.exit("STOP: the two entries differ")
    if len(seed) < 12:
        sys.exit("STOP: the seed must be at least 12 characters")
    exclude = set()
    for f in [HERE / "exposed-ids.txt"] + [Path(x) for x in a.exclude_file]:
        if f.exists():
            exclude |= gold_sampler.read_exclude_file(f)
    if a.root:
        exclude |= gold_sampler.exposed_ids(a.root)
    pool = gold_sampler.fetch_pool(a.term, a.mindate, a.maxdate)
    safety = gold_sampler.fetch_pool(gold_sampler.SAFETY_TERM, a.mindate, a.maxdate)
    rows, warnings = plan_draw(pool, safety, seed, exclude)
    out.mkdir(parents=True, exist_ok=True)
    recs = []
    for r in rows:
        pmid = r["id"].split("-", 1)[1]
        recs.append({"id": r["id"], "title": r["title"], "year": r["year"], "pubtypes": r["pubtypes"], "language": r.get("lang", ["eng"]), "text": fetch_text(pmid)})
    (out / "records.json").write_text(json.dumps({"records": recs}, indent=1, ensure_ascii=False), encoding="utf-8")
    with open(out / "pilot-records.csv", "w", newline="", encoding="utf-8-sig") as f:       # what run-pilot.ps1 reads (ids and neutral metadata only)
        w = csv.writer(f); w.writerow(["id", "year", "pubtypes", "language", "title"])
        for r in rows:
            w.writerow([r["id"], r["year"], ";".join(r["pubtypes"]), ";".join(r.get("lang", ["eng"])), r["title"]])
    with open(out / "pilot-records.csv.strata.csv", "w", newline="", encoding="utf-8") as f:   # OWNER ONLY
        w = csv.writer(f); w.writerow(["id", "stratum"]); [w.writerow([r["id"], r["stratum"]]) for r in rows]
    print(f"{len(rows)} records drawn into {out} (excluded {len(exclude)} ids already seen). Commitment SHA-256 of the id list: {gold_sampler.commitment(rows)}")
    for w_ in warnings:
        print("WARNING:", w_)
    print("Next: python pilot_tool.py sheet --dir", out)


# ------------------------------------------------------------------ pages
CSS = """:root{--bg:#f6f7f9;--card:#fff;--ink:#1b2430;--mute:#5b6675;--line:#d5dbe3;--acc:#1f5fbf;--ok:#1d7a46;--warn:#b25b00;--sel:#e7f0ff}
@media (prefers-color-scheme:dark){:root{--bg:#12161c;--card:#1a2029;--ink:#e6eaf0;--mute:#9aa6b6;--line:#2c3644;--acc:#7fb0ff;--ok:#5fd18d;--warn:#ffb25c;--sel:#22344f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,Segoe UI,Arial,sans-serif}
header{position:sticky;top:0;background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;z-index:5;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
header h1{font-size:18px;margin:0}main{max-width:900px;margin:0 auto;padding:16px}details{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 14px;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:16px}.card.done{border-left:5px solid var(--ok)}
.meta{color:var(--mute);font-size:14px;margin:0 0 8px}.abs{white-space:pre-wrap;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px 12px;max-height:340px;overflow:auto;font-size:15px}
.q{display:grid;grid-template-columns:1fr auto;gap:6px 12px;padding:6px 0;border-top:1px solid var(--line);align-items:center}.q span.l{font-weight:600}.q small{color:var(--mute);grid-column:1/-1}
label.r{display:inline-flex;gap:4px;align-items:center;padding:3px 10px;border:1px solid var(--line);border-radius:999px;cursor:pointer;margin-left:6px}label.r:has(input:checked){background:var(--sel);border-color:var(--acc)}
button{font:inherit;background:var(--acc);color:#fff;border:0;border-radius:8px;padding:8px 14px;cursor:pointer}button.sec{background:transparent;color:var(--acc);border:1px solid var(--acc)}
textarea{width:100%;font:inherit;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px}.warn{color:var(--warn)}.hide{display:none}.cmp{background:var(--bg);border-radius:8px;padding:8px 10px;margin:6px 0}"""


def _json_for_script(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


JS_COMMON = r"""
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
function store(k,v){try{if(v===undefined){return JSON.parse(localStorage.getItem(k)||'null')}localStorage.setItem(k,JSON.stringify(v))}catch(e){return null}}
function csvCell(v){v=(v==null?'':String(v));return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v}
function download(name,text){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['﻿'+text],{type:'text/csv'}));a.download=name;document.body.appendChild(a);a.click();a.remove()}
"""


def make_sheet(records):
    cards = []
    for i, r in enumerate(records, 1):
        lang = ";".join(r.get("language") or ["eng"])
        nonen = any(l.lower() not in ("eng", "und") for l in (r.get("language") or ["eng"]))
        pmid = r["id"].split("-", 1)[1]
        absr = abstract_text(r.get("text", "")) or "(no abstract text in this record)"
        qs = "".join(f'<div class="q" data-q="{k}"><span class="l">{html.escape(lbl)}</span><span><label class="r"><input type="radio" name="{html.escape(r["id"])}|{k}" value="yes"> Yes</label>'
                     f'<label class="r"><input type="radio" name="{html.escape(r["id"])}|{k}" value="no"> No</label></span></div>' for k, lbl, _ in QUESTIONS)
        cant = (f'<p class="warn"><label><input type="checkbox" class="cant"> I cannot read this language well enough (leave questions 1-4 blank if unsure)</label></p>' if nonen else "")
        cards.append(f'<section class="card" id="c{i}" data-id="{html.escape(r["id"])}"><h2 style="font-size:17px;margin:0 0 4px">{i}. {html.escape(r["title"])}</h2>'
                     f'<p class="meta">{html.escape(str(r.get("year", "")))} &middot; publication types: {html.escape("; ".join(r.get("pubtypes") or []) or "none listed")} &middot; language field: {html.escape(lang)} &middot; '
                     f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" target="_blank" rel="noopener">PubMed {pmid}</a></p><div class="abs">{html.escape(absr)}</div>{cant}{qs}'
                     f'<p><textarea rows="1" placeholder="Optional note" class="note"></textarea></p></section>')
    defs = "".join(f"<li><b>{html.escape(l)}</b>: {html.escape(d)}</li>" for _, l, d in QUESTIONS)
    ids = [r["id"] for r in records]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pilot checklist</title><style>{CSS}</style></head><body>
<header><h1>Pilot checklist &mdash; {len(records)} records</h1><span id="prog">0 of {len(records)} complete</span><button id="exp">Save my answers (download CSV)</button><span class="meta">Your answers are also kept in this browser, so you can stop and come back.</span></header>
<main><details open><summary><b>How to fill this in (about 1.5 minutes per record)</b></summary><p>Read only the text shown. Tick Yes or No for each of the six questions. Do not judge whether the study is good, only what the text states. Answer from the text itself, not from what you expect. If you cannot read a language, tick the box and leave questions 1&ndash;4 blank if unsure. When all records are complete, press the button at the top, then run <code>pilot_tool.py reconcile</code> with the downloaded file.</p><ol>{defs}</ol></details>{''.join(cards)}</main>
<script>{JS_COMMON}
const IDS={_json_for_script(ids)}, KEYS={_json_for_script(KEYS)}, KEY='te-pilot-checklist-v1';
let ans=store(KEY)||{{}};
function read(card){{const id=card.dataset.id,o={{}};KEYS.forEach(k=>{{const c=$('input[name="'+id+'|'+k+'"]:checked',card);o[k]=c?c.value:''}});o.cant=$('.cant',card)?$('.cant',card).checked:false;o.note=$('.note',card).value;return o}}
function complete(o){{return o.cant?KEYS.every(k=>true):KEYS.every(k=>o[k])}}
function refresh(){{let n=0;$$('.card').forEach(c=>{{const o=read(c);ans[c.dataset.id]=o;const d=complete(o)&&(o.cant||KEYS.every(k=>o[k]));c.classList.toggle('done',d);if(d)n++}});$('#prog').textContent=n+' of '+IDS.length+' complete';store(KEY,ans)}}
$$('.card').forEach(c=>{{const o=ans[c.dataset.id];if(o){{KEYS.forEach(k=>{{const r=$('input[name="'+c.dataset.id+'|'+k+'"][value="'+o[k]+'"]',c);if(r)r.checked=true}});if($('.cant',c))$('.cant',c).checked=!!o.cant;$('.note',c).value=o.note||''}}c.addEventListener('change',refresh);c.addEventListener('input',refresh)}});
$('#exp').onclick=()=>{{refresh();const miss=IDS.filter(id=>!(ans[id]&&(ans[id].cant||KEYS.every(k=>ans[id][k]))));if(miss.length&&!confirm(miss.length+' record(s) are not complete. Download anyway?'))return;
 const rows=[['id',...KEYS,'cannot_read','note'].join(',')];IDS.forEach(id=>{{const o=ans[id]||{{}};rows.push([id,...KEYS.map(k=>csvCell(o[k]||'')),o.cant?'yes':'no',csvCell(o.note||'')].join(','))}});download('pilot-checklist.csv',rows.join('\\r\\n'))}};
refresh();
</script></body></html>"""


def read_answers(path):
    with open(path, encoding="utf-8-sig") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def disagreements(records, answers):
    """[(record, question, human answer, code answer, code evidence)] for every question the human answered differently from the automatic reading."""
    out = []
    for r in records:
        a = answers.get(r["id"])
        if not a:
            continue
        rd = code_reading(r)
        for k in KEYS:
            h = (a.get(k) or "").strip().lower()
            if h in ("yes", "no") and h != rd[k][0]:
                out.append((r, k, h, rd[k][0], rd[k][1]))
    return out


def make_reconcile(records, answers, diffs):
    by = {}
    for r, k, h, c, ev in diffs:
        by.setdefault(r["id"], []).append((k, h, c, ev))
    labels = {k: l for k, l, _ in QUESTIONS}
    defs = {k: d for k, _, d in QUESTIONS}
    cards = []
    for r in records:
        if r["id"] not in by:
            continue
        rows = ""
        for k, h, c, ev in by[r["id"]]:
            evt = f' (found: &ldquo;{html.escape(ev)}&rdquo;)' if ev and c == "yes" else ""
            note = f' ({html.escape(ev)})' if ev and c == "no" and k == "abstract" else ""
            rows += (f'<div class="cmp" data-q="{k}"><b>{html.escape(labels[k])}</b><br><small>{html.escape(defs[k])}</small><br>You answered <b>{h.upper()}</b>. The automatic reading says <b>{c.upper()}</b>{evt}{note}.<br>'
                     f'Final answer: <label class="r"><input type="radio" name="{html.escape(r["id"])}|{k}" value="yes"> Yes</label><label class="r"><input type="radio" name="{html.escape(r["id"])}|{k}" value="no"> No</label></div>')
        cards.append(f'<section class="card" data-id="{html.escape(r["id"])}"><h2 style="font-size:17px;margin:0 0 4px">{html.escape(r["title"])}</h2><p class="meta"><a href="https://pubmed.ncbi.nlm.nih.gov/{r["id"].split("-", 1)[1]}/" target="_blank" rel="noopener">PubMed</a></p>'
                     f'<div class="abs">{html.escape(abstract_text(r.get("text", "")) or "(no abstract text)")}</div>{rows}</section>')
    base = {i: {k: (a.get(k) or "") for k in KEYS} | {"cannot_read": a.get("cannot_read", "no"), "note": a.get("note", "")} for i, a in answers.items()}
    orig = {f"{r['id']}|{k}": h for r, k, h, _, _ in diffs}
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pilot reconciliation</title><style>{CSS}</style></head><body>
<header><h1>Reconcile {len(by)} record(s)</h1><span id="prog"></span><button id="exp">Save final answers (download CSV)</button></header>
<main><details open><summary><b>What to do</b></summary><p>Read the text again for each question below and choose the answer the TEXT supports. The automatic reading can be wrong in either direction; it is only a prompt to look again. Press the button when every question has a final answer.</p></details>{''.join(cards)}</main>
<script>{JS_COMMON}
const BASE={_json_for_script(base)}, ORIG={_json_for_script(orig)}, KEYS={_json_for_script(KEYS)};
function refresh(){{const t=$$('.cmp').length,d=$$('.cmp').filter(c=>$('input:checked',c)).length;$('#prog').textContent=d+' of '+t+' answered'}}
document.addEventListener('change',refresh);refresh();
$('#exp').onclick=()=>{{if($$('.cmp').some(c=>!$('input:checked',c))){{alert('Some questions have no final answer yet.');return}}
 const fin=JSON.parse(JSON.stringify(BASE)),changed={{}};$$('.cmp').forEach(c=>{{const [id,k]=$('input',c).name.split('|');const v=$('input:checked',c).value;fin[id][k]=v;changed[id+'|'+k]=(ORIG[id+'|'+k]!==v)}});
 const rows=[['id',...KEYS,'cannot_read','note','changed_after_reconcile'].join(',')];Object.keys(fin).forEach(id=>{{const o=fin[id];const ch=KEYS.filter(k=>changed[id+'|'+k]).join(';');rows.push([id,...KEYS.map(k=>csvCell(o[k])),o.cannot_read,csvCell(o.note),csvCell(ch)].join(','))}});download('pilot-final.csv',rows.join('\\r\\n'))}};
</script></body></html>"""


def cmd_sheet(a):
    d = Path(a.dir)
    recs = json.loads((d / "records.json").read_text(encoding="utf-8"))["records"]
    (d / "checklist.html").write_text(make_sheet(recs), encoding="utf-8")
    print(f"Wrote {d / 'checklist.html'}. Open it in your browser (double-click). Nothing from the pipeline is shown in it.")


def cmd_reconcile(a):
    d = Path(a.dir)
    recs = json.loads((d / "records.json").read_text(encoding="utf-8"))["records"]
    answers = read_answers(a.answers)
    missing = [r["id"] for r in recs if r["id"] not in answers]
    if missing:
        sys.exit(f"STOP: {len(missing)} record(s) are not in the answers file (was the checklist saved after the last record?)")
    incomplete = [i for i, r in answers.items() if r.get("cannot_read", "no") != "yes" and not all((r.get(k) or "").strip().lower() in ("yes", "no") for k in KEYS)]
    if incomplete:
        sys.exit(f"STOP: {len(incomplete)} record(s) still have unanswered questions; finish the checklist first.")
    diffs = disagreements(recs, answers)
    if not diffs:
        with open(d / "pilot-final.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f); w.writerow(["id"] + KEYS + ["cannot_read", "note", "changed_after_reconcile"])
            for r in recs:
                x = answers[r["id"]]; w.writerow([r["id"]] + [x.get(k, "") for k in KEYS] + [x.get("cannot_read", "no"), x.get("note", ""), ""])
        print(f"No disagreements with the automatic reading. Wrote {d / 'pilot-final.csv'}. Nothing more to reconcile.")
        return
    (d / "reconcile.html").write_text(make_reconcile(recs, answers, diffs), encoding="utf-8")
    print(f"{len(diffs)} question(s) in {len({r['id'] for r, *_ in diffs})} record(s) differ from the automatic reading. Open {d / 'reconcile.html'}, re-read, choose the final answers and download pilot-final.csv.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("draw"); p.add_argument("--out", required=True); p.add_argument("--term", default="tinnitus[tiab] OR tinnitus[MeSH Terms]")
    p.add_argument("--mindate", default="2025/07/01"); p.add_argument("--maxdate", default=time.strftime("%Y/%m/%d")); p.add_argument("--exclude-file", action="append", default=[]); p.add_argument("--root")
    p.set_defaults(fn=cmd_draw)
    p = sub.add_parser("sheet"); p.add_argument("--dir", required=True); p.set_defaults(fn=cmd_sheet)
    p = sub.add_parser("reconcile"); p.add_argument("--dir", required=True); p.add_argument("--answers", required=True); p.set_defaults(fn=cmd_reconcile)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
