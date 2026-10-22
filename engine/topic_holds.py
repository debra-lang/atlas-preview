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

ENGINE = Path(__file__).resolve().parent


def load_holds(path=None):
    try:
        data = json.loads((Path(path) if path else ENGINE / "topic_holds.json").read_text(encoding="utf-8"))
        return [h for h in data.get("holds", []) if h.get("id")]
    except Exception:
        return []


def _compiled(h):
    return [re.compile(p, re.I) for p in h.get("patterns", [])]


def match_item(item, holds=None, extra_text=""):
    """Returns the id of the first hold that matches this item (or the fetched record text), else None."""
    holds = load_holds() if holds is None else holds
    hay = " ".join(str(item.get(k) or "") for k in ("title", "source", "summary")) + " " + (extra_text or "")
    for h in holds:
        if any(item.get("id", "").startswith(p) for p in h.get("idPrefixes", [])):
            return h["id"]
        if any(rx.search(hay) for rx in _compiled(h)):
            return h["id"]
    return None
