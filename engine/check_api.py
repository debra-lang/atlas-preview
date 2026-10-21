#!/usr/bin/env python3
"""Tinnitus Evidence: one-request check that the Anthropic API key + credits work. Standard library only.

Reads ANTHROPIC_API_KEY from the environment, sends a 1-token request, and prints ONLY the outcome class and HTTP status. It never prints,
logs or echoes the key (not even part of it), writes no files, and touches no queue or data. Safe to run locally or in CI.

Exit codes: 0 usable | 2 authentication failed (invalid/revoked key) | 3 billing (credit balance too low) | 4 permission/other API error |
            5 network error | 6 key not set
Usage:  python engine/check_api.py            (model defaults to the evaluator's model; override with ANTHROPIC_MODEL)
"""
import json, os, sys, urllib.request, urllib.error

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")
key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
if not key:
    print("RESULT: key-not-set  (ANTHROPIC_API_KEY is empty or missing in this environment)")
    sys.exit(6)
fmt_ok = key.startswith("sk-ant-")
req = urllib.request.Request(
    "https://api.anthropic.com/v1/messages",
    data=json.dumps({"model": MODEL, "max_tokens": 1, "messages": [{"role": "user", "content": "ping"}]}).encode("utf-8"),
    headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}, method="POST")
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        print(f"RESULT: ok  (HTTP {r.status}; model {MODEL} answered; key length {len(key)}, expected prefix {'yes' if fmt_ok else 'NO'})")
        sys.exit(0)
except urllib.error.HTTPError as e:
    try:
        body = json.loads(e.read().decode("utf-8", "replace"))
        etype, emsg = body.get("error", {}).get("type", "?"), str(body.get("error", {}).get("message", ""))[:200]
    except Exception:
        etype, emsg = "?", ""
    low = emsg.lower()
    if e.code == 401 or etype == "authentication_error":
        print(f"RESULT: auth-failed  (HTTP {e.code}, {etype}: {emsg}) key length {len(key)}, expected prefix {'yes' if fmt_ok else 'NO'}")
        sys.exit(2)
    if e.code == 400 and ("credit balance" in low or "billing" in low):
        print(f"RESULT: billing  (HTTP {e.code}: {emsg})")
        sys.exit(3)
    print(f"RESULT: api-error  (HTTP {e.code}, {etype}: {emsg})")
    sys.exit(4)
except Exception as e:
    print(f"RESULT: network-error  ({type(e).__name__})")
    sys.exit(5)
