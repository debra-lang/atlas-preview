#!/usr/bin/env python3
"""Tinnitus Evidence — owner topic holds (engine/topic_holds.json).

engine/paused_ids.json pauses named items. A topic hold pauses a TOPIC, so new items about it that the weekly scan finds later are
held too (the Lenire news watch runs every week). A held item is treated exactly like a paused id: never sent to the AI, never published,
never lost; it stays in the queue until the hold is released by editing engine/topic_holds.json.

Matching is deliberately precise: whole-word regular expressions on the item's title/source/summary (and, before any API call, on the
fetched record text). "Neuromod" matches the company; it does NOT match "neuromodulation", so unrelated neuromodulation research is not held.
"""
import json, re
from pathlib import Path
import html, unicodedata

ENGINE = Path(__file__).resolve().parent


def load_holds(path=None):
    try:
        data = json.loads((Path(path) if path else ENGINE / "topic_holds.json").read_text(encoding="utf-8"))
        return [h for h in data.get("holds", []) if h.get("id")]
    except Exception:
        return []


def _compiled(h):
    return [re.compile(p, re.I) for p in h.get("patterns", [])]


def record_text(record):
    """Every piece of text in a decoded record, one per line, at any depth. A hold must read the text itself: in a JSON dump a line break is the two characters backslash and n, so a name after it reads "nLenire" and no whole-word pattern finds it."""
    out, stack = [], [record]
    while stack:                       # not recursive: a very deep answer must not be the thing that stops the check
        x = stack.pop()
        if isinstance(x, dict):
            for k, v in reversed(list(x.items())):
                stack += [v, k]
        elif isinstance(x, list):
            stack += reversed(x)
        elif isinstance(x, str):
            out.append(x)
        elif isinstance(x, (int, float)) and not isinstance(x, bool):
            out.append(str(x))
    return "\n".join(out)


_HYPHENS = "\u2010\u2011\u2012\u2013\u2043\u2212\ufe63\uff0d"     # not the long dashes: "in a tent\u2014a small one" is not the trial TENT-A


class _Plain(dict):
    """For str.translate: accents, invisible and control characters go, hyphen-like characters read as a hyphen, and anything that is a space, and underscores, read as a space."""

    def __missing__(self, code):
        c = chr(code)
        cat = unicodedata.category(c)
        v = "-" if c in _HYPHENS else " " if c.isspace() or c == "_" or cat in ("Zs", "Zl", "Zp") else None if cat in ("Mn", "Cf", "Cc") else code
        self[code] = v
        return v


_PLAIN = _Plain()


def _plain(text):
    """The text with what can hide a name from a whole-word pattern taken out: entities, escapes written out as characters, compatibility forms, accents, invisible characters. Used beside the text as written, never instead of it, so it can only find more."""
    t = html.unescape(html.unescape(text))
    t = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), t)
    t = re.sub(r"\\[nrtfvb]", " ", t)
    t = re.sub(r"</?[a-zA-Z][^<>]{0,40}>", "", t)                # markup inside a word
    t = re.sub("[\u00a9\u00ae\u2120\u2122\u00b9\u00b2\u00b3\u2070-\u2079\u2080-\u2089]", " ", t)    # compatibility forms would glue these to the name as TM or a digit
    return re.sub(r" +", " ", unicodedata.normalize("NFKD", t).translate(_PLAIN))


def match_item(item, holds=None, extra_text=""):
    """Returns the id of the first hold that matches this item (or the fetched record text), else None."""
    holds = load_holds() if holds is None else holds
    hay = " ".join(str(item.get(k) or "") for k in ("title", "source", "summary")) + " " + (extra_text or "")
    plain = _plain(hay)
    for h in holds:
        if any(item.get("id", "").startswith(p) for p in h.get("idPrefixes", [])):
            return h["id"]
        if any(rx.search(hay) or rx.search(plain) for rx in _compiled(h)):
            return h["id"]
    return None
