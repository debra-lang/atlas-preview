#!/usr/bin/env python3
"""The rating lock: an automated run can never change a published rating, rank or claim. It compares the working files with the last commit, so an owner's reviewed commit moves the baseline and a run cannot.
Called from tools/check_seo.py, which runs before the workflow commits anything: a stop here means nothing from the run is committed or published."""
import json, subprocess

RATINGS = ("tier", "evidenceScore", "confidence", "replication", "independence", "safetyLevel", "category", "subtypeTags")
LEVELS = ("loudness", "distress")
WHOLE_FILES = ("data/rankings.json", "data/claims.json")


def _rows(data, key):
    return data if isinstance(data, list) else (data or {}).get(key, [])


def compare(old, new):
    """old, new: {path: parsed file}. Returns the protected changes, in words."""
    out = []
    ot, nt = {t["id"]: t for t in _rows(old["data/treatments.json"], "treatments")}, {t["id"]: t for t in _rows(new["data/treatments.json"], "treatments")}
    if list(ot) != list(nt):
        out.append(f"data/treatments.json: treatments added, removed or reordered ({sorted(set(ot) ^ set(nt))})")
    for tid in set(ot) & set(nt):
        a, b = ot[tid], nt[tid]
        out += [f"treatment {tid}: {k} changed from {a.get(k)!r} to {b.get(k)!r}" for k in RATINGS if a.get(k) != b.get(k)]
        out += [f"treatment {tid}: {k} level changed from {(a.get(k) or {}).get('level')!r} to {(b.get(k) or {}).get('level')!r}" for k in LEVELS if (a.get(k) or {}).get("level") != (b.get(k) or {}).get("level")]
    os_, ns = {s["id"]: s for s in _rows(old["data/studies.json"], "studies")}, {s["id"]: s for s in _rows(new["data/studies.json"], "studies")}
    if set(os_) != set(ns):
        out.append(f"data/studies.json: studies added or removed ({sorted(set(os_) ^ set(ns))})")
    out += [f"study {sid}: independent flag changed" for sid in set(os_) & set(ns) if os_[sid].get("independent") != ns[sid].get("independent")]
    out += [f"{f}: changed" for f in WHOLE_FILES if old.get(f) != new.get(f)]
    return out


def check(root):
    """-> (errors, a note). Outside a git checkout, as in an export, there is no baseline, so it says so and does not pass silently as checked."""
    paths = ("data/treatments.json", "data/studies.json") + WHOLE_FILES
    old, new = {}, {}
    for f in paths:
        p = subprocess.run(["git", "show", f"HEAD:{f}"], cwd=root, capture_output=True)
        if p.returncode:
            return [], f"rating lock: not checked, no committed baseline for {f}"
        old[f] = json.loads(p.stdout)
        new[f] = json.loads((root / f).read_text(encoding="utf-8"))
    return [f"rating lock: {c}" for c in compare(old, new)], "rating lock: checked against the last commit"
