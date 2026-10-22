#!/usr/bin/env python3
"""Tinnitus Evidence — draw candidates for the HIDDEN gold test set (local tool; the OWNER runs it with a seed only the owner knows).

Purpose: a small, independent test set that the prompts were never tuned against. Rules this tool enforces:
  * the draw is deterministic from an owner-chosen seed (at least 12 characters) that is never written to any output, so nobody else can reproduce or anticipate the set;
  * every record the project has already SEEN is excluded: queue items, every id ever scanned (known_ids), cited studies, the test fixtures, and the benchmark;
  * stratified: tinnitus in the title (likely relevant) versus not (ambiguous), crossed with study type, so that relevant, borderline and irrelevant records are all present;
  * the output lists identifiers and neutral metadata ONLY: no AI evaluation, no label of any kind. A SHA-256 commitment of the identifier list is printed so the set
    cannot be quietly altered later;
  * store the output OUTSIDE the repository (the repository is public). The assistant that tunes prompts must not receive the list or the labels, only aggregate scores.

  python engine/gold_sampler.py --n 60 --root <clone of production> --exclude-file exposed-by-assistant.txt --out D:\\te-gold\\candidates.csv
(the seed is requested at a hidden prompt so it never enters the shell history; do not put it on the command line)

Two files are written: candidates.csv (what the labellers see: ids, year, publication types, language, title, empty label columns) and candidates.csv.strata.csv (OWNER ONLY: why
each record was drawn, e.g. as a seeded safety-query record; labellers must not see it because it could bias their labels).

Caveat: records published before the model's training cut-off may be partly familiar to the model; for a cleaner test also accumulate PROSPECTIVE records (items that arrive
after the prompt freeze) with the same tool and --exclude-file pointing at the earlier candidate file.
"""
import argparse, csv, getpass, hashlib, json, os, random, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUOTAS = [("rct", 0.15), ("systematic-review", 0.15), ("observational", 0.30), ("review-other", 0.15), ("case-or-letter", 0.10), ("other", 0.15)]
TECH = ["relevance_1to6", "study_type", "abstract_present", "notice_type", "has_sample_size", "has_design", "has_result_figures", "safety_wording"]   # the last four are yes/no technical labels read from the abstract
LABEL_COLUMNS = ([f"labeller1_{c}" for c in TECH] + ["labeller1_notes"] + [f"labeller2_{c}" for c in TECH] + ["labeller2_notes"] + [f"adjudicated_{c}" for c in TECH] +
                 ["CLINICIAN_ONLY_evidence_direction", "CLINICIAN_ONLY_clinically_meaningful", "CLINICIAN_ONLY_safety_concern", "CLINICIAN_ONLY_recommendation_impact"])
SPECIAL_PER_60 = {"notice": 3, "non-english": 5, "safety-query": 5}   # rare categories that a plain random draw would miss; scaled with n
NOTICE_TYPES = ("retraction of publication", "retracted publication", "published erratum", "erratum", "expression of concern", "corrected and republished", "retraction", "correction")
SAFETY_TERM = ('(tinnitus[tiab]) AND (seizure*[tiab] OR "adverse event*"[tiab] OR "serious adverse"[tiab] OR suicid*[tiab] OR "device-related"[tiab] OR "safety alert"[tiab] OR '
               '"permanent hearing loss"[tiab] OR ototoxic*[tiab])')


def is_notice(c):
    t = " ".join(c.get("pubtypes", [])).lower()
    return any(k in t for k in NOTICE_TYPES)


def is_non_english(c):
    lang = [str(x).lower() for x in c.get("lang", ["eng"]) if x]
    return bool(lang) and "eng" not in lang and lang != ["und"]


def study_type(pubtypes):
    t = " ".join(pubtypes).lower()
    if "randomized controlled trial" in t:
        return "rct"
    if "systematic review" in t or "meta-analysis" in t:
        return "systematic-review"
    if "case reports" in t or "letter" in t or "comment" in t or "editorial" in t:
        return "case-or-letter"
    if "review" in t:
        return "review-other"
    if "observational" in t or "cohort" in t or "cross-sectional" in t or "comparative study" in t or "validation" in t or "multicenter" in t:
        return "observational"
    return "other"


def exposed_ids(root):
    """Every identifier the project has already seen (so none can be in the hidden set)."""
    root = Path(root)
    seen = set()
    for rel in ("data/review-queue/queue.json", "data/review-queue/archive.json"):
        try:
            for it in json.loads((root / rel).read_text(encoding="utf-8")).get("items", []):
                seen.add(str((it.get("item") or it).get("id", "")))
        except Exception:
            pass
    try:
        seen |= set(json.loads((root / "engine/known_ids.json").read_text(encoding="utf-8")))
    except Exception:
        pass
    try:
        s = json.loads((root / "data/studies.json").read_text(encoding="utf-8"))
        for st in (s["studies"] if isinstance(s, dict) else s):
            if st.get("pmid"):
                seen.add("pubmed-" + str(st["pmid"]))
    except Exception:
        pass
    for f in (root / "engine" / "tests" / "fixtures").glob("*.json") if (root / "engine" / "tests" / "fixtures").exists() else []:
        seen |= {"pubmed-" + m for m in re.findall(r'pubmed-(\d{6,9})', f.read_text(encoding="utf-8", errors="ignore"))}
    return seen


def select(candidates, seed, n, exclude, quotas=QUOTAS, title_share=0.5, special=None, safety_pool=None):
    """candidates: list of dicts {id, title, pubtypes, year[, lang]}. Deterministic given seed; excludes `exclude`; stratified by (tinnitus-in-title, study type).
    special: {"notice": k, "non-english": k, "safety-query": k} guarantees at least k of each rare category when the pool has them (drawn first, counted within n);
    safety_pool: candidates from a separate safety-term query. select_with_report also returns warnings about short strata."""
    return select_with_report(candidates, seed, n, exclude, quotas, title_share, special, safety_pool)[0]


def select_with_report(candidates, seed, n, exclude, quotas=QUOTAS, title_share=0.5, special=None, safety_pool=None):
    if len(seed) < 12:
        raise ValueError("the seed must be at least 12 characters (a private phrase only the owner knows)")
    rng = random.Random(hashlib.sha256(seed.encode("utf-8")).hexdigest())
    warnings, chosen, taken = [], [], set()
    pool = sorted((c for c in candidates if c["id"] not in exclude), key=lambda c: c["id"])
    sp = special or {}
    safety = sorted((c for c in (safety_pool or []) if c["id"] not in exclude), key=lambda c: c["id"])
    for kind, pred, src in (("notice", is_notice, pool), ("non-english", is_non_english, pool), ("safety-query", lambda c: True, safety)):
        k = sp.get(kind, 0)
        if not k:
            continue
        avail = [c for c in src if pred(c) and c["id"] not in taken]
        rng.shuffle(avail)
        got = avail[:k]
        if len(got) < k:
            warnings.append(f"only {len(got)} of the {k} requested '{kind}' records exist in the pool")
        for c in got:
            taken.add(c["id"])
            chosen.append(dict(c, stratum="special:" + kind))
    pool = [c for c in pool if c["id"] not in taken]
    m = max(0, n - len(chosen))
    buckets = {}
    for c in pool:
        c = dict(c, stratum=("title" if re.search(r"tinnit", c["title"], re.I) else "no-tinnitus-in-title") + "/" + study_type(c["pubtypes"]))
        buckets.setdefault(c["stratum"], []).append(c)
    for key in sorted(buckets):
        rng.shuffle(buckets[key])
    main = []
    for tin in ("title", "no-tinnitus-in-title"):
        share = title_share if tin == "title" else 1 - title_share
        for typ, frac in quotas:
            main += buckets.get(f"{tin}/{typ}", [])[: round(m * share * frac)]
    ids = {c["id"] for c in main}
    rest = [c for key in sorted(buckets) for c in buckets[key] if c["id"] not in ids]
    rng.shuffle(rest)
    main += rest[: max(0, m - len(main))]                                               # top up when a stratum is short
    chosen += main[:m]
    return sorted(chosen[:n], key=lambda c: c["id"]), warnings


def commitment(rows):
    return hashlib.sha256("\n".join(r["id"] for r in rows).encode("utf-8")).hexdigest()


def _get(url, tries=5):
    for k in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "TinnitusEvidence-gold/1.0"}), timeout=60).read()
        except Exception:
            time.sleep(2 * (k + 1))
    raise RuntimeError("could not reach NCBI")


def fetch_pool(term, mindate, maxdate):
    q = urllib.parse.urlencode({"db": "pubmed", "term": term, "datetype": "pdat", "mindate": mindate, "maxdate": maxdate, "retmax": 5000, "retmode": "json"})
    ids = json.loads(_get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + q))["esearchresult"]["idlist"]
    out = []
    for i in range(0, len(ids), 150):
        s = json.loads(_get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?" + urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids[i:i + 150]), "retmode": "json"})))["result"]
        out += [{"id": "pubmed-" + u, "title": s[u].get("title", ""), "pubtypes": s[u].get("pubtype", []), "year": s[u].get("pubdate", "")[:4], "lang": s[u].get("lang", ["eng"])} for u in s["uids"]]
        time.sleep(0.5)
    return out


def read_exclude_file(path):
    """A previous candidates.csv (id column) or a plain text list containing 'pubmed-1234567' tokens, bare PMIDs, or PubMed URLs."""
    p = Path(path)
    if p.suffix.lower() == ".csv":
        with open(p, encoding="utf-8-sig") as fh:
            return {r["id"] for r in csv.DictReader(fh)}
    txt = p.read_text(encoding="utf-8", errors="ignore")
    return {"pubmed-" + m for m in re.findall(r"(?<!\d)(\d{6,9})(?!\d)", txt)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", help="avoid: a command line is kept in the shell history. Omit it to be asked at a hidden prompt (or set GOLD_SEED for one run)"); ap.add_argument("--n", type=int, default=60); ap.add_argument("--out", required=True)
    ap.add_argument("--term", default="tinnitus[tiab] OR tinnitus[MeSH Terms]"); ap.add_argument("--safety-term", default=SAFETY_TERM)
    ap.add_argument("--mindate", default="2023/01/01"); ap.add_argument("--maxdate", default="2026/06/30"); ap.add_argument("--title-share", type=float, default=0.5)
    ap.add_argument("--exclude-file", action="append", default=[], help="a previous candidates.csv or a text list of ids to exclude (repeatable)"); ap.add_argument("--root", default=str(ROOT))
    a = ap.parse_args(argv)
    if Path(a.out).resolve().is_relative_to(Path(a.root).resolve()):
        sys.exit("STOP: write the candidate list OUTSIDE the repository (it is public)")
    seed = a.seed or os.environ.get("GOLD_SEED")
    if not seed:
        seed = getpass.getpass("Private seed (12+ characters; nothing is displayed; write it down somewhere safe, it recreates the draw): ")
        if getpass.getpass("Type it again: ") != seed:
            sys.exit("STOP: the two entries differ")
    if len(seed) < 12:
        sys.exit("STOP: the seed must be at least 12 characters")
    exclude = exposed_ids(a.root)
    for f in a.exclude_file:
        exclude |= read_exclude_file(f)
    scale = a.n / 60
    special = {k: max(1, round(v * scale)) for k, v in SPECIAL_PER_60.items()} if a.n >= 30 else {}
    rows, warnings = select_with_report(fetch_pool(a.term, a.mindate, a.maxdate), seed, a.n, exclude, title_share=a.title_share, special=special,
                                        safety_pool=fetch_pool(a.safety_term, a.mindate, a.maxdate) if special else None)
    out = Path(a.out)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:                         # utf-8 with BOM so Excel shows accents correctly
        w = csv.DictWriter(f, fieldnames=["id", "year", "pubtypes", "language", "title"] + LABEL_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({"id": r["id"], "year": r["year"], "pubtypes": ";".join(r["pubtypes"]), "language": ";".join(r.get("lang", ["eng"])), "title": r["title"]})
    with open(str(out) + ".strata.csv", "w", newline="", encoding="utf-8") as f:       # OWNER ONLY
        w = csv.writer(f); w.writerow(["id", "stratum"]); [w.writerow([r["id"], r["stratum"]]) for r in rows]
    print(f"{len(rows)} candidates written to {out} (excluded {len(exclude)} already-seen ids). Commitment SHA-256 of the id list: {commitment(rows)}")
    for w_ in warnings:
        print("WARNING:", w_)
    print(f"OWNER ONLY: {out}.strata.csv says why each record was drawn; do not give it to the labellers.")
    print("Keep these files and the commitment OUTSIDE the repository and OUTSIDE any folder the assistant can read; do not send the list or any labels to the assistant.")


if __name__ == "__main__":
    main()
