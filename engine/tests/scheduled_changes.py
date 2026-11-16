"""The two changes the scheduled update may make to a published record, undone exactly, so the guards that compare with a
published baseline still catch everything else. Used by test_disclosure_pages and test_approved_record_changes.

1. A treatment's 'latest' news list: the update only ever inserts entries at the front (weekly_cycle.py), never edits or removes one.
2. A trial's registry 'status' (weekly_cycle.py, allowed display wordings only): no other trial field, and no trial added or removed."""
import copy

NEWS_KEYS = {"date", "text", "url"}


def undo_news(now_treatments, base_treatments):
    """-> now_treatments with the update's added news entries removed. Raises AssertionError if a 'latest' list changed in any
    other way: an entry edited, removed or reordered, or an added entry that is not a plain news note."""
    base = {t["id"]: t for t in base_treatments}
    out = copy.deepcopy(now_treatments)
    for t in out:
        if t["id"] not in base or "latest" not in t:
            continue
        had = base[t["id"]].get("latest")
        now, old = t["latest"], had or []
        added = len(now) - len(old)
        assert added >= 0 and now[added:] == old, f"{t['id']}: 'latest' changed other than by new entries at the front"
        assert all(isinstance(e, dict) and set(e) == NEWS_KEYS for e in now[:added]), f"{t['id']}: an added 'latest' entry is not a plain news note"
        if had is None:
            del t["latest"]
        else:
            t["latest"] = old
    return out


def only_status_changed(now_trials, base_trials):
    """True if the trial list differs from the baseline only in existing trials' 'status' field."""
    if [t.get("nctId") for t in now_trials] != [t.get("nctId") for t in base_trials] or None in (t.get("nctId") for t in base_trials):
        return False
    return all({k: v for k, v in a.items() if k != "status"} == {k: v for k, v in b.items() if k != "status"} for a, b in zip(now_trials, base_trials))
