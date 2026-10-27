"""Owner-approved record changes from the held-review process, as one exact list (engine/approved-record-changes.json).

The same list is used two ways, so what is applied and what the safeguards allow can never drift apart:
  * apply(...)  makes exactly these edits to treatments / studies / rankings (tools/apply_approved_changes.py);
  * revert(...) undoes exactly these edits; the disclosure safeguards (engine/tests) then require the result to equal the
    published file byte for byte, so ANY other change — another field, another treatment, an edited or deleted history
    entry, an extra study record — still fails.
Every value is checked before it is changed or reverted: a 'from' that does not match, a missing record or a moved history
entry raises ApprovedChangeMismatch instead of being silently accepted."""
import copy, json
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent / "approved-record-changes.json"


class ApprovedChangeMismatch(AssertionError):
    pass


def load(path=MANIFEST):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _get(obj, path):
    for k in path:
        obj = obj[k]
    return obj


def _set(obj, path, value):
    for k in path[:-1]:
        obj = obj[k]
    obj[path[-1]] = value


def _by_id(items, tid):
    hits = [x for x in items if x.get("id") == tid]
    if len(hits) != 1:
        raise ApprovedChangeMismatch(f"expected exactly one record with id {tid!r}, found {len(hits)}")
    return hits[0]


def _flip(target, field_changes, label, forward):
    for fc in field_changes:
        path = fc["path"]
        want, new = (fc["from"], fc["to"]) if forward else (fc["to"], fc["from"])
        have = _get(target, path)
        if have != want:
            raise ApprovedChangeMismatch(f"{label} {'.'.join(map(str, path))}: expected {want!r}, found {have!r}")
        _set(target, path, copy.deepcopy(new))


def _history(target, entries, label, forward):
    hist = target.setdefault("history", [])
    if forward:
        hist.extend(copy.deepcopy(entries))
        return
    n = len(entries)
    if n and (len(hist) < n or hist[-n:] != entries):
        raise ApprovedChangeMismatch(f"{label}: the approved history entries are not the last {n} entries (history may only be appended to)")
    del hist[len(hist) - n:]


def _rank_entry(rankings, rid):
    return _by_id(rankings["top"], rid)


def apply(treatments, studies, rankings, manifest=None):
    """Return new (treatments, studies, rankings) with exactly the approved edits made."""
    m = manifest or load()
    t, s, r = copy.deepcopy(treatments), copy.deepcopy(studies), copy.deepcopy(rankings)
    for ch in m["treatments"]:
        rec = _by_id(t, ch["id"])
        _flip(rec, ch["fields"], f"treatment {ch['id']}", True)
        _history(rec, ch["appendHistory"], f"treatment {ch['id']}", True)
    for new in m["studiesAdded"]:
        if any(x.get("id") == new["id"] for x in s):
            raise ApprovedChangeMismatch(f"study {new['id']} already exists")
        s.append(copy.deepcopy(new))
    for ch in m["rankings"]["top"]:
        _flip(_rank_entry(r, ch["id"]), ch["fields"], f"rankings top {ch['id']}", True)
    _history(r, m["rankings"]["appendHistory"], "rankings", True)
    return t, s, r


def revert(treatments, studies, rankings, manifest=None):
    """Return (treatments, studies, rankings) with exactly the approved edits undone; raises if any of them is not present as approved."""
    m = manifest or load()
    t, s, r = copy.deepcopy(treatments), copy.deepcopy(studies), copy.deepcopy(rankings)
    # undo in reverse order of approval, so a later approval that edits the same field or appends to the same history comes off first
    for ch in reversed(m["treatments"]):
        rec = _by_id(t, ch["id"])
        _history(rec, ch["appendHistory"], f"treatment {ch['id']}", False)
        _flip(rec, ch["fields"], f"treatment {ch['id']}", False)
    for new in m["studiesAdded"]:
        hits = [i for i, x in enumerate(s) if x.get("id") == new["id"]]
        if len(hits) != 1 or s[hits[0]] != new:
            raise ApprovedChangeMismatch(f"study {new['id']}: not present exactly as approved")
        del s[hits[0]]
    _history(r, m["rankings"]["appendHistory"], "rankings", False)
    for ch in reversed(m["rankings"]["top"]):
        _flip(_rank_entry(r, ch["id"]), ch["fields"], f"rankings top {ch['id']}", False)
    return t, s, r


def dump(obj):
    """The data files' exact serialisation (2-space indent, UTF-8 characters kept, CRLF, no trailing newline)."""
    return json.dumps(obj, indent=2, ensure_ascii=False).replace("\n", "\r\n")
