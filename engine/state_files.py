#!/usr/bin/env python3
"""Tinnitus Evidence - protection and state files fail CLOSED.

A damaged file is never read as "nothing": an empty pause list publishes what was paused, an empty queue loses what was queued, an empty register publishes duplicates.
So a file that is missing (when required), unreadable, not valid UTF-8 JSON, or wrongly structured raises DamagedFile, and the weekly cycle stops before it scans, calls anything or writes anything.
preflight() checks every file at once and names them all, so one repair is enough.
A UTF-8 byte-order mark is accepted only on the hand-edited files (PowerShell can add one when saving), and every reader of those files accepts it. On a file the engine writes, it stops the run, because other readers of those files cannot read it.
NaN, Infinity and numbers too large to hold are refused on reading, and the engine refuses to write them: they are not JSON, and a browser reading a public data file would fail on them.

Deliberate exceptions, each one the safe direction:
  * Absent OPTIONAL files start empty: they do not exist until first needed (the plaintext held and staged stores also need their .enc file to be absent).
  * An absent engine/eval_settings.json or engine/automation_settings.json means OFF, and a value other than exactly true means OFF, as the project has always defined them. A settings file that is present but damaged stops the run.

Shape checks only. A valid file with the wrong CONTENT (an id removed, a pattern edited) passes here, apart from the checks below; removing a protection on purpose is the hold-release safeguard's job.
  * An empty pause, hold, archive or listings file needs "emptyOnPurpose": true, and the flag on a file that is not empty stops the run: it can never stay armed to excuse a later accidental deletion.
  * A paused id must be one the scan has seen: a mistyped id pauses nothing.
  * The append-only files (known ids, published register, report index, studies, treatments) are never empty.
  * A hold pattern that cannot match is rejected: a control or invisible character ("\\b" written with one backslash in JSON is a backspace), or a literal backslash ("\\\\b" written with too many).
  * The queue and the listings cannot be empty when the last run's status says it left records in them. The archive and the private held store cannot disappear.
"""
import json, re, unicodedata
from datetime import date, timedelta
from pathlib import Path


class DamagedFile(RuntimeError):
    """A protection or state file cannot be trusted. Messages name the file and the problem, never its contents (some of these files are private)."""


_MISSING = object()


def _unique(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError("a key appears twice")   # JSON would silently keep the last one, so a second "ids" could empty the first. The key itself is not repeated: some of these files are private
        d[k] = v
    return d


def bad_constant(name):
    raise ValueError(f"{name} is not valid JSON")


def finite_float(text):
    v = float(text)
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError("a number is too large to hold")
    return v


def read(path, default=_MISSING):
    """The parsed file. Absent: `default`, or DamagedFile if none is given. Anything else wrong: DamagedFile."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        if default is _MISSING:
            raise DamagedFile(f"{path.name}: the file is missing") from None
        return default
    except OSError as e:
        raise DamagedFile(f"{path.name}: the file cannot be read ({type(e).__name__})") from None
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique, parse_constant=bad_constant, parse_float=finite_float)
    except UnicodeDecodeError:
        raise DamagedFile(f"{path.name}: not UTF-8 text (save it as UTF-8)") from None
    except json.JSONDecodeError as e:
        raise DamagedFile(f"{path.name}: not valid JSON (line {e.lineno}, column {e.colno}: {e.msg})") from None
    except (ValueError, RecursionError) as e:
        raise DamagedFile(f"{path.name}: not valid JSON ({str(e)[:80]})") from None


# ---------- shapes: each returns a problem in words, or None ----------
def _clean_strings(v, what, allow_empty=True):
    if not isinstance(v, list):
        return f"{what} must be a list"
    if not v and not allow_empty:
        return f"{what} is empty"
    for x in v:
        if not isinstance(x, str) or not x or x != x.strip():
            return f"{what} must hold non-empty text with no surrounding spaces"
        if any(unicodedata.category(c) in ("Cc", "Cf") for c in x):
            return f"{what} holds a control or invisible character, which never matches (in JSON a backslash must be doubled)"
    return None


def _obj(d):
    return None if isinstance(d, dict) else "must be a JSON object"


def _dicts(v, what, key=None):
    if not isinstance(v, list):
        return f"{what} must be a list"
    for x in v:
        if not isinstance(x, dict):
            return f"{what} must hold objects"
        if key and (not isinstance(x.get(key), str) or not x[key]):
            return f"every entry in {what} needs a text '{key}'"
    return None


def _items(key=None):
    def check(d):
        return _obj(d) or ("needs an 'items' list" if "items" not in d else _dicts(d["items"], "items", key))
    return check


def _flag(d, key):
    """The opt-out says one thing only: this list is empty on purpose. Set on a list with entries it would stay armed and excuse a later accidental deletion, so it stops the run."""
    if d[key] and "emptyOnPurpose" in d:
        return f"'emptyOnPurpose' is set but {key} is not empty; remove it"
    if not d[key] and d.get("emptyOnPurpose") is not True:
        return f"{key} is empty; add \"emptyOnPurpose\": true if that is intended"
    return None


def _archive(d):   # entries keep the record under "item"; append-only, so empty needs saying
    p = _items()(d)
    if p:
        return p
    if any(not isinstance(e.get("item"), dict) for e in d["items"]):
        return "every entry in items needs an 'item' object"
    return _flag(d, "items")


def _top_keys(d, allowed):
    unknown = sorted(set(d) - allowed)
    return f"unknown key '{unknown[0]}'" if unknown else None


def _is_past_date(v):
    try:
        return date.fromisoformat(v) <= date.today() + timedelta(days=1)    # a day's grace for time zones
    except (TypeError, ValueError):
        return False


def _paused(d):
    p = _obj(d) or _top_keys(d, {"comment", "note", "ids", "emptyOnPurpose"}) or ("needs an 'ids' list" if "ids" not in d else _clean_strings(d["ids"], "ids"))
    if p:
        return p
    return _flag(d, "ids")


HOLD_KEYS = {"id", "label", "comment", "note", "idPrefixes", "patterns"}


def _holds(d):
    p = _obj(d) or _top_keys(d, {"comment", "note", "holds", "emptyOnPurpose"}) or ("needs a 'holds' list" if "holds" not in d else _dicts(d["holds"], "holds", "id"))
    if p:
        return p
    p = _flag(d, "holds")
    if p:
        return p
    for h in d["holds"]:
        unknown = sorted(set(h) - HOLD_KEYS)
        if unknown:                                     # a misspelt "patern" would otherwise leave the hold matching less than it says
            return f"hold '{h['id']}' has an unknown key '{unknown[0]}'"
        for k in ("patterns", "idPrefixes"):
            p = _clean_strings(h.get(k, []), f"{k} of hold '{h['id']}'")
            if p:
                return p
        if not h.get("patterns") and not h.get("idPrefixes"):
            return f"hold '{h['id']}' has no patterns or idPrefixes, so it would match nothing"
        for rx in h.get("patterns", []):
            if "\\\\" in rx:
                return f"hold '{h['id']}' has a pattern with a literal backslash, which would never match a title (in JSON write \\\\b once, not \\\\\\\\b)"
            try:
                re.compile(rx)
            except Exception:    # not only re.error: an absurd repeat count or nesting raises other errors
                return f"hold '{h['id']}' has a pattern that is not a valid regular expression"
    return None


def _strings(d):   # written by the cycle, not by hand: a published title made only of symbols registers as an empty key, so the entries are not held to the hand-edited files' rules
    if not isinstance(d, list) or not all(isinstance(x, str) for x in d):
        return "must be a list of text"
    return None if d else "the file is empty"


def _rows(key=None, allow_empty=True):
    def check(d):
        p = _dicts(d, "the file", key)
        return p or (None if d or allow_empty else "the file is empty")
    return check


LISTED_OUTCOMES = {"listed", "screened-out", "notice", "superseded", "unverifiable", "failed-verification"}


def _listings(d):   # the listing step needs both: without them it fails part-way
    p = _items("key")(d) or _items("listedOn")(d)
    if p:
        return p
    return "'emptyOnPurpose' is set but items is not empty; remove it" if d["items"] and "emptyOnPurpose" in d else None


def _queue(d):   # the cycle reads these as text
    p = _items("id")(d)
    if p:
        return p
    if d["items"] and "emptyOnPurpose" in d:
        return "'emptyOnPurpose' is set but items is not empty; remove it"
    seen = set()
    for i in d["items"]:
        if i["id"] in seen:     # one id, two records: a mark or an outcome could land on the wrong one
            return f"the id '{i['id']}' appears more than once"
        seen.add(i["id"])
        if "topicHold" in i and (not isinstance(i["topicHold"], str) or not i["topicHold"].strip()):
            return f"item '{i['id']}' has a hold mark that is not understood"
        for k in ("title", "url", "source"):
            if k in i and not isinstance(i[k], str):
                return f"item '{i['id']}' has a '{k}' that is not text"
        if "listed" in i:     # any other value would leave the record never listed and never flagged
            m = i["listed"]
            if not isinstance(m, dict) or not isinstance(m.get("outcome"), str) or m["outcome"] not in LISTED_OUTCOMES or (m["outcome"] == "listed" and not isinstance(m.get("key"), str)):
                return f"item '{i['id']}' has a 'listed' mark that is not understood"
    return None


def _batch(d):     # evaluate_queue writes "items" as an object keyed by custom id
    p = _obj(d)
    if p:
        return p
    return None if isinstance(d.get("batchId"), str) and d["batchId"] and isinstance(d.get("items"), dict) else "needs a 'batchId' and an 'items' object"


def _reports(d):
    p = _obj(d) or ("needs a 'reports' list" if "reports" not in d else _dicts(d["reports"], "reports", "file"))
    return p or (None if d["reports"] else "reports is empty")


def _studies(d):
    return _rows("id", allow_empty=False)(d)


def _sources(d):
    return _obj(d) or _watch_rows(d, "feeds", "name", "url") or _watch_rows(d, "newsIntel", "name", "query") or _watch_rows(d, "pages", "name", "url")


def _watch_rows(d, key, *fields):   # an empty list is an owner's explicit choice; a misspelt key or an entry the scanner cannot use is not
    if key not in d:
        return f"needs a '{key}' list"
    for f in fields:
        p = _dicts(d[key], key, f)
        if p:
            return p
    return None


def _scan_state(d):
    p = _obj(d)
    if p:
        return p
    for k in ("pubmed", "ctgov"):
        if not _is_past_date(d.get(k)):                  # a misspelt key or a future date would quietly lose the look-back that recovers a missed run
            return f"needs a '{k}' date that is not in the future"
    return None


def _retraction_state(d):
    return _obj(d) or (None if _is_past_date(d.get("lastRun")) else "needs a 'lastRun' date that is not in the future")   # a future date skips the back-check until then


def _rules(d):
    p = _obj(d) or (None if isinstance(d.get("aliases"), dict) and d["aliases"] else "needs an 'aliases' object")
    if p:
        return p
    for k, kind in (("noticePubtypes", list), ("priorityPubtypes", list), ("catalogueMaxAbstractMentions", int)):
        if not isinstance(d.get(k), kind) or isinstance(d.get(k), bool) or (kind is list and not d[k]):
            return f"needs '{k}'"
    for k, rx in d["aliases"].items():
        try:
            re.compile(rx)
        except Exception:
            return f"alias '{k}' is not a valid regular expression"
    return None


def _ledger(d):
    return _obj(d) or _dicts(d.get("runs"), "runs")


def _decisions(d):
    return _obj(d) or _dicts(d.get("decisions"), "decisions")


def _history(d):
    return _obj(d) or _dicts(d.get("entries"), "entries")


# Always present in a working repository: absent means something is wrong.
REQUIRED = {"engine/paused_ids.json": _paused, "engine/topic_holds.json": _holds, "engine/known_ids.json": _strings, "engine/published_ids.json": _strings,
            "data/review-queue/queue.json": _queue, "data/review-queue/archive.json": _archive, "data/weekly/index.json": _reports,
            "data/trials.json": _rows("nctId"), "data/studies.json": _studies, "data/treatments.json": _rows("id", allow_empty=False)}
# Read by the real scan only; a test or --simulate run with scan fixtures does not use them.
REQUIRED_FOR_SCAN = {"engine/scan-state.json": _scan_state, "engine/sources.json": _sources, "engine/page-hashes.json": _obj, "engine/retraction-state.json": _retraction_state, "engine/triage_rules.json": _rules}
# May be absent until first needed. If present, must be sound.
OPTIONAL = {"data/review-queue/held.json": _items(), "data/review-queue/staged.json": _items("id"), "data/review-queue/decisions.json": _decisions,
            "engine/batch-state.json": _batch, "engine/usage-ledger.json": _ledger, "engine/triage-evidence.json": _obj, "engine/benchmark-report.json": _obj,
            "engine/eval_settings.json": _obj, "engine/automation_settings.json": _obj, "data/engine-status.json": _obj}
LISTINGS, HISTORY = "data/listings.json", "data/update-history.json"
# The files people edit by hand, whose every reader accepts a byte-order mark. Anywhere else a mark stops the run with a clear reason: those files have other readers (the page build, the budget and retraction checks) that cannot read one, and a late failure or a silent default there is worse.
MARK_ALLOWED = {"engine/paused_ids.json", "engine/topic_holds.json", "engine/eval_settings.json", "engine/automation_settings.json", "engine/sources.json", "engine/triage_rules.json"}


def checked(path, shape):
    """Reads and shape-checks one file that must exist."""
    d = read(path)
    p = shape(d)
    if p:
        raise DamagedFile(f"{Path(path).name}: {p}")
    return d


def paused_ids(root):
    return set(checked(Path(root) / "engine" / "paused_ids.json", _paused)["ids"])


def preflight(root, scan_files=True, today=None):
    """Checks every protection and state file and raises DamagedFile naming all problems. Reads only; changes nothing."""
    root, problems, loaded = Path(root), [], {}

    def check(rel, shape, required):
        try:
            d = read(root / rel) if required else read(root / rel, None)
            if d is None and not required and not (root / rel).exists():
                return
            p = shape(d)
            if not p and rel not in MARK_ALLOWED and (root / rel).read_bytes().startswith(b"\xef\xbb\xbf"):
                p = "has a byte-order mark, which its other readers cannot read (save it as UTF-8 without one)"
            if p:
                problems.append(f"{rel}: {p}")
            else:
                loaded[rel] = d
        except DamagedFile as e:
            problems.append(f"{rel}: {str(e).split(': ', 1)[1]}")
    for rel, shape in REQUIRED.items():
        check(rel, shape, True)
    if scan_files:
        for rel, shape in REQUIRED_FOR_SCAN.items():
            check(rel, shape, True)
    for rel, shape in OPTIONAL.items():
        check(rel, shape, False)
    settings = loaded.get("engine/automation_settings.json") or {}
    check(LISTINGS, _listings, settings.get("listings") is True)
    check(HISTORY, _history, settings.get("updateHistory") is True)
    today = today or date.today().isoformat()
    check(f"data/weekly/{today}.json", _items(), False)
    if scan_files and not (root / "data/review-queue/held.json").exists() and not (root / "data/review-queue/held.json.enc").exists():
        problems.append("data/review-queue/held.json.enc is missing: the workflow never removes it, so its absence means the private held store was lost")
    status = loaded.get("data/engine-status.json") or {}
    evaluation = status.get("evaluation") if isinstance(status.get("evaluation"), dict) else {}
    left = sum(n for n in (evaluation.get("awaitingEvaluation"), evaluation.get("paused")) if isinstance(n, int))
    queue = loaded.get("data/review-queue/queue.json")
    if queue is not None and not queue["items"] and left > 0 and queue.get("emptyOnPurpose") is not True:
        problems.append(f"data/review-queue/queue.json: empty, but the last run left {left} record(s) in it; add \"emptyOnPurpose\": true if that is intended")
    listed = status.get("listings").get("total") if isinstance(status.get("listings"), dict) else None
    if LISTINGS in loaded and not loaded[LISTINGS]["items"] and isinstance(listed, int) and listed > 0 and loaded[LISTINGS].get("emptyOnPurpose") is not True:
        problems.append(f"{LISTINGS}: empty, but the last run left {listed} listing(s) in it; add \"emptyOnPurpose\": true if that is intended")
    for name in ("held", "staged"):
        if (root / f"data/review-queue/{name}.json.enc").exists() and not (root / f"data/review-queue/{name}.json").exists():
            problems.append(f"data/review-queue/{name}.json.enc exists but was not decrypted (STATE_KEY missing, or the restore step failed): refusing to run so {name} items cannot be lost")
    if "engine/paused_ids.json" in loaded and "engine/known_ids.json" in loaded and "data/review-queue/queue.json" in loaded:
        seen = set(loaded["engine/known_ids.json"]) | {i["id"] for i in loaded["data/review-queue/queue.json"]["items"]}
        unseen = sorted(set(loaded["engine/paused_ids.json"]["ids"]) - seen)
        if unseen:
            problems.append(f"engine/paused_ids.json: {len(unseen)} id(s) the scan has never seen, probably mistyped, so they pause nothing: {', '.join(unseen[:5])}")
    if problems:
        raise DamagedFile("protection or state file(s) cannot be trusted, nothing was scanned, published or changed. " + " | ".join(problems))
