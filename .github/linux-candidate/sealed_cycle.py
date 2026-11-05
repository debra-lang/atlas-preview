"""Runs engine/weekly_cycle.py from a throwaway copy, sealed: GET requests to public sources only, no GitHub, no Anthropic, no program started, no file written outside the copy and the temp folder.
Every network answer is kept in a cache folder and replayed on later runs, so two runs see exactly the same answers and differ only by their code. An entry in the plant file edits one cached answer on the way out.
Never decrypts anything: the real held store is left where it is, and an empty stand-in takes its place, as the workflow's restore step would provide.
Usage: sealed_cycle.py <copy> <cache folder> <log> [plant.json]"""
import base64, hashlib, io, json, os, runpy, sys, urllib.error, urllib.parse, urllib.request
from pathlib import Path

TREE, CACHE, LOG = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
PLANT = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8")) if len(sys.argv) > 4 else {}
CACHE.mkdir(parents=True, exist_ok=True)
for k in list(os.environ):
    if any(s in k.upper() for s in ("ANTHROPIC", "API_KEY", "STATE_KEY", "TOKEN", "SECRET", "YOUTUBE", "GH_", "GITHUB")):
        del os.environ[k]
ROOTS = [os.path.normcase(os.path.realpath(p)) for p in (TREE, CACHE, LOG.parent, os.environ["TEMP"])]
BLOCKED_HOSTS = ("anthropic", "github", "tinnitusevidence", "cloudflare", "workers.dev")
stats = {"replayed": 0, "fetched": 0, "planted": 0, "blocked": []}
busy = [False]


def note(msg):
    busy[0] = True
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    finally:
        busy[0] = False


def block(msg):
    stats["blocked"].append(msg)
    note("BLOCKED " + msg)
    raise PermissionError("sealed cycle: " + msg)


def hook(event, args):
    if busy[0]:
        return
    if event == "subprocess.Popen":
        block(f"program started: {args[0]} {str(args[1])[:120]}")
    elif event in ("os.system", "os.exec", "os.spawn", "os.startfile"):
        block(f"{event}: {str(args)[:120]}")
    elif event == "urllib.Request":
        if args[3] not in (None, "GET") or args[1] is not None:
            block(f"non-GET request to {args[0]}")
    elif event == "socket.getaddrinfo":
        host = str(args[0] or "").lower()
        if any(b in host for b in BLOCKED_HOSTS):
            block(f"connection to {host}")
    elif event == "open":
        path, mode, flags = args
        writes = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (mode is None and isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
        if writes and isinstance(path, (str, bytes, os.PathLike)):
            p = os.path.normcase(os.path.realpath(os.fsdecode(path)))
            if not any(p == r or p.startswith(r + os.sep) for r in ROOTS):
                block(f"write outside the copy: {p}")


class Resp(io.BytesIO):
    def __init__(self, body, status, headers, url):
        super().__init__(body)
        self.status, self.code, self.url = status, status, url
        self.headers = self.msg = HeaderBag(headers)

    def getcode(self):
        return self.status

    def geturl(self):
        return self.url

    def info(self):
        return self.headers


class HeaderBag(dict):
    def get_content_charset(self, failobj=None):
        ct = self.get("Content-Type", "")
        return ct.split("charset=")[-1].split(";")[0].strip() if "charset=" in ct else failobj


real_urlopen = urllib.request.urlopen


def plant(url, body):
    for nct, text in PLANT.items():
        if f"/studies/{nct}" in url:
            d = json.loads(body)
            d["protocolSection"].setdefault("oversightModule", {})["rehearsalNote"] = text        # a field the compact text leaves out: only the complete record shows it
            stats["planted"] += 1
            note(f"PLANTED in {nct}: {text!r}")
            return json.dumps(d).encode()
    return body


def urlopen(req, data=None, timeout=60, **k):
    url = req.full_url if isinstance(req, urllib.request.Request) else req
    if (isinstance(req, urllib.request.Request) and req.get_method() != "GET") or data is not None:
        block(f"non-GET request to {url}")
    host = urllib.parse.urlsplit(url).hostname or ""
    if any(b in host.lower() for b in BLOCKED_HOSTS):
        block(f"connection to {host}")
    f = CACHE / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    if f.exists():
        stats["replayed"] += 1
        c = json.loads(f.read_text(encoding="utf-8"))
    else:
        stats["fetched"] += 1
        try:
            with real_urlopen(req, timeout=timeout) as r:
                c = {"url": url, "status": r.status, "headers": dict(r.headers.items()), "body": base64.b64encode(r.read()).decode()}
        except urllib.error.HTTPError as e:
            c = {"url": url, "error": "http", "code": e.code, "reason": str(e.reason)}
        except Exception as e:
            c = {"url": url, "error": "url", "reason": f"{type(e).__name__}: {str(e)[:150]}"}
        busy[0] = True
        try:
            f.write_text(json.dumps(c), encoding="utf-8")
        finally:
            busy[0] = False
        note(f"FETCHED {host} {c.get('status') or c.get('error')} {c.get('code', '')}")
    if c.get("error") == "http":
        raise urllib.error.HTTPError(url, c["code"], c["reason"], {}, io.BytesIO(b""))
    if c.get("error"):
        raise urllib.error.URLError(c["reason"])
    return Resp(plant(url, base64.b64decode(c["body"])), c["status"], c["headers"], url)


urllib.request.urlopen = urlopen
sys.addaudithook(hook)
os.chdir(TREE)
sys.path.insert(0, str(TREE / "engine"))
sys.argv = [str(TREE / "engine" / "weekly_cycle.py")]
code = 0
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
except SystemExit as e:
    code = e.code or 0
print("SEALED:", json.dumps({k: (v if k != "blocked" else len(v)) for k, v in stats.items()}))
for b in stats["blocked"][:20]:
    print("  blocked:", b)
sys.exit(code)
