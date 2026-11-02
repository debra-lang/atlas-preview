"""Release A's explicit allowlist (owner decisions, 23 Oct 2026): fixtures/release-a-allowlist.json names every data edit of this release as
file, record id, exact field path, before and after. It is measured against one baseline commit, fails if the branch's base differs, and
retires by itself once Release A is in production (the next release then starts from that commit). A history entry never authorises a change."""
import copy, json, re, subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
LIST = json.loads((Path(__file__).resolve().parent / "fixtures" / "release-a-allowlist.json").read_text(encoding="utf-8"))
BASELINE, ENTRIES = LIST["baseline"], LIST["changes"]
FILES = sorted({e["file"] for e in ENTRIES})
EXCEPTION = LIST["independentException"]


def git(*args, repo=REPO):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8")


def merge_base(repo=REPO):
    return git("merge-base", "HEAD", "origin/main", repo=repo).stdout.strip() or None


def at(rev, rel, repo=REPO):
    return json.loads(git("show", f"{rev}:{rel}", repo=repo).stdout)


def now(rel, repo=REPO):
    return json.loads((repo / rel).read_text(encoding="utf-8"))


def state(base, repo=REPO):
    """'active': this branch is built on the allowlist's baseline. 'retired': Release A is already in production. 'stale': any other base, re-measure first."""
    if base == BASELINE:
        return "active"
    rec = [s for s in at(base, "data/studies.json", repo) if s["id"] == EXCEPTION["id"]]
    return "retired" if rec and rec[0].get("independent") is EXCEPTION["after"] else "stale"


def _record(records, rid):
    hit = [r for r in records if r["id"] == rid]
    if len(hit) != 1:
        raise KeyError(f"expected one record {rid}, found {len(hit)}")
    return hit[0]


def _parent(rec, path):
    keys = [int(t[1:-1]) if t.startswith("[") else t for t in re.findall(r"\[\d+\]|[^.\[\]]+", path)]
    for k in keys[:-1]:
        rec = rec[k]
    return rec, keys[-1]


def _get(holder, key):
    if isinstance(holder, list):
        return holder[key] if key < len(holder) else None
    return holder.get(key)


def _put(holder, key, value):
    """value None removes a field that the edit added (new list item or new key)."""
    if value is None:
        del holder[key]
    elif isinstance(holder, list) and key == len(holder):
        holder.append(value)
    else:
        holder[key] = value


def apply(rel, records):
    """Baseline records + every entry for this file. Raises if an entry's 'before' does not match."""
    out = copy.deepcopy(records)
    for e in [x for x in ENTRIES if x["file"] == rel]:
        holder, key = _parent(_record(out, e["id"]), e["path"])
        if _get(holder, key) != e["before"]:
            raise ValueError(f"{e['id']} {e['path']}: 'before' does not match the baseline")
        _put(holder, key, e["after"])
    return out


def undo(rel, records):
    """Current records minus every entry for this file. Raises if an entry's 'after' is not what the record says now."""
    out = copy.deepcopy(records)
    for e in reversed([x for x in ENTRIES if x["file"] == rel]):
        holder, key = _parent(_record(out, e["id"]), e["path"])
        if _get(holder, key) != e["after"]:
            raise ValueError(f"{e['id']} {e['path']}: 'after' is not what the record says now")
        _put(holder, key, e["before"])
    return out


def problems(base, repo=REPO):
    """Empty when the data on disk is exactly the baseline's plus this list: an unlisted change, a wrong 'after' and an unapplied entry all fail."""
    out = []
    for rel in FILES:
        try:
            if apply(rel, at(base, rel, repo)) != now(rel, repo):
                out.append(f"{rel}: differs from the baseline plus the allowlist")
        except (KeyError, ValueError, IndexError) as e:
            out.append(f"{rel}: {e}")
    return out
