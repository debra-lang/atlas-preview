#!/usr/bin/env python3
"""Tinnitus Evidence — rotate the STATE_KEY passphrase and migrate the encrypted review files (local tool; you run it on your computer).

Encrypted files in the repository: data/review-queue/held.json.enc (default OpenSSL PBKDF2 iterations) and data/review-queue/staged.json.enc (600,000 iterations).
This tool re-encrypts them under a NEW passphrase with verification at every step, a backup first, and a rollback. It never prints, logs or stores either
passphrase or any plaintext (plaintext lives only in memory; temporary files are ciphertext).

  python engine/rotate_state_key.py plan     --backup-dir D:\\te-backup      (dry run: decrypts with the OLD key, re-encrypts to temp, verifies; changes nothing)
  python engine/rotate_state_key.py apply    --backup-dir D:\\te-backup      (same, then replaces the repository files; backup and manifest written first)
  python engine/rotate_state_key.py verify   --manifest D:\\te-backup\\manifest.json   (NEW key only: confirms the repository files decrypt and match the manifest)
  python engine/rotate_state_key.py rollback --backup-dir D:\\te-backup      (restores the original files; verifies them with the OLD key)

Keys come from environment variables so they never appear on a command line or in shell history:  OLD_STATE_KEY, NEW_STATE_KEY.
What rotation does NOT do: ciphertext already committed to the public git history stays decryptable with the OLD key (history is not rewritten). It protects
FUTURE files and ends the old key's usefulness for them; keep the old key for as long as you may need the old history or a rollback.
"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = {"held.json.enc": None, "staged.json.enc": "600000"}   # name -> PBKDF2 iterations (None = OpenSSL default, exactly what weekly.yml's held steps use)
REL = "data/review-queue"


def _ssl():
    return os.environ.get("OPENSSL", "openssl")


def _cmd(decrypt, enc, iters, keyenv, out=None):
    c = [_ssl(), "enc"] + (["-d"] if decrypt else []) + ["-aes-256-cbc", "-pbkdf2"] + (["-iter", iters] if iters else []) + (["-salt"] if not decrypt else []) + ["-in", str(enc)]
    if out:
        c += ["-out", str(out)]
    return c + ["-pass", f"env:{keyenv}"]


def decrypt(enc, iters, keyenv):
    """Returns plaintext bytes or None (wrong key / wrong iteration count). Never raises with key material."""
    p = subprocess.run(_cmd(True, enc, iters, keyenv), capture_output=True)
    return p.stdout if p.returncode == 0 else None


def opens(enc, iters, keyenv):
    """True only if the key really opens the file: decrypts AND yields a valid review store. A WRONG key passes OpenSSL's padding check about once in 256 tries and returns
    garbage, so 'decrypt returned something' alone is not proof the key is right (this made the old-key check fail by chance, about 0.4% of runs)."""
    plain = decrypt(enc, iters, keyenv)
    if plain is None:
        return False
    try:
        canon(plain)
        return True
    except Exception:
        return False


def encrypt(plain_bytes, out, iters, keyenv):
    """Plaintext goes to openssl through stdin; only ciphertext is written."""
    c = [_ssl(), "enc", "-aes-256-cbc", "-pbkdf2"] + (["-iter", iters] if iters else []) + ["-salt", "-out", str(out), "-pass", f"env:{keyenv}"]
    p = subprocess.run(c, input=plain_bytes, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("encryption failed")


def canon(plain):
    """Hash of the parsed JSON (so the check does not depend on whitespace) plus the item count; raises if it is not the expected structure."""
    d = json.loads(plain.decode("utf-8"))
    if not isinstance(d, dict) or not isinstance(d.get("items"), list):
        raise ValueError("decrypted content is not a review store (no 'items' list)")
    return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(), len(d["items"])


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def strength_warnings(k):
    w = []
    if len(k) < 20:
        w.append("shorter than 20 characters")
    if len(set(k)) < 10:
        w.append("fewer than 10 distinct characters")
    if not (re.search(r"[a-z]", k) and re.search(r"[A-Z0-9]", k)):
        w.append("lacks mixed character classes")
    return w


def die(msg, code=2):
    print("STOP: " + msg, file=sys.stderr)
    sys.exit(code)


def present(root):
    return {n: Path(root) / REL / n for n in FILES if (Path(root) / REL / n).exists()}


def rehearse(root, backup_dir, apply):
    old, new = os.environ.get("OLD_STATE_KEY", ""), os.environ.get("NEW_STATE_KEY", "")
    if not old or not new:
        die("set OLD_STATE_KEY and NEW_STATE_KEY in the environment (they are never printed)")
    if old == new:
        die("the new key is identical to the old key")
    w = strength_warnings(new)
    if w:
        die("the new key is weak: " + "; ".join(w) + ". Use a long random passphrase (20+ characters from a password manager).")
    files = present(root)
    if not files:
        print("no encrypted review files exist: nothing to migrate. Set the new GitHub secret and you are done."); return {}
    plains = {}
    for name, path in files.items():                                    # 1. decrypt EVERYTHING with the old key first; any failure stops before anything is written
        plain = decrypt(path, FILES[name], "OLD_STATE_KEY")
        if plain is None:
            die(f"{name}: cannot be decrypted with OLD_STATE_KEY (wrong key, or a different iteration count). Nothing was changed.")
        try:
            plains[name] = (plain,) + canon(plain)
        except Exception as e:
            die(f"{name}: decrypted but {e}. Nothing was changed.")
    backup_dir = Path(backup_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    manifest = {"createdAt": stamp, "files": {}}
    work = Path(tempfile.mkdtemp(prefix="te-rot-new-"))
    try:
        for name, (plain, h, n) in plains.items():                       # 2. re-encrypt to temp (ciphertext only) and verify before anything is replaced
            out = work / name
            encrypt(plain, out, FILES[name], "NEW_STATE_KEY")
            back = decrypt(out, FILES[name], "NEW_STATE_KEY")
            if back is None or canon(back) != (h, n):
                die(f"{name}: verification of the re-encrypted file failed. Nothing was changed.")
            if opens(out, FILES[name], "OLD_STATE_KEY"):
                die(f"{name}: the re-encrypted file still opens with the OLD key (keys not distinct?). Nothing was changed.")
            manifest["files"][name] = {"items": n, "plainJsonSha256": h, "oldCiphertextSha256": sha(files[name]), "newCiphertextSha256": sha(out), "iterations": FILES[name] or "openssl-default"}
        print("plan verified for", ", ".join(f"{k} ({v['items']} item(s))" for k, v in manifest["files"].items()), "- old and new ciphertext both verified; no key or plaintext was printed or written.")
        if not apply:
            print("dry run: nothing was changed. Re-run with 'apply' to back up and replace the files."); return manifest
        backup_dir.mkdir(parents=True, exist_ok=True)                    # 3. backup first, then replace
        for name, path in files.items():
            shutil.copy2(path, backup_dir / f"{name}.bak-{stamp}")
            if sha(backup_dir / f"{name}.bak-{stamp}") != manifest["files"][name]["oldCiphertextSha256"]:
                die(f"{name}: the backup copy does not match the original. Nothing was replaced.")
            manifest["files"][name]["backup"] = str(backup_dir / f"{name}.bak-{stamp}")
        (backup_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        for name, path in files.items():
            tmp = path.with_suffix(path.suffix + ".new")
            shutil.copy2(work / name, tmp)
            tmp.replace(path)
        print(f"replaced {len(files)} file(s). Backup and manifest: {backup_dir}. Next: commit the files, set the GitHub secret, run the verify workflow.")
        return manifest
    finally:
        shutil.rmtree(work, ignore_errors=True)


def verify(root, manifest_path):
    m = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    ok = True
    for name, info in m["files"].items():
        path = Path(root) / REL / name
        if not path.exists():
            print(f"MISSING {name}"); ok = False; continue
        plain = decrypt(path, FILES[name], "NEW_STATE_KEY")
        if plain is None:
            print(f"FAIL {name}: does not decrypt with NEW_STATE_KEY"); ok = False; continue
        h, n = canon(plain)
        good = (h, n) == (info["plainJsonSha256"], info["items"])
        print(("OK   " if good else "FAIL ") + f"{name}: {n} item(s), content hash {'matches' if good else 'DIFFERS from'} the manifest")
        ok = ok and good
    sys.exit(0 if ok else 1)


def rollback(root, backup_dir):
    bd = Path(backup_dir)
    m = json.loads((bd / "manifest.json").read_text(encoding="utf-8"))
    for name, info in m["files"].items():                               # verify every backup (hash AND decryptable with the OLD key) before touching the repository
        b = Path(info["backup"])
        if sha(b) != info["oldCiphertextSha256"]:
            die(f"{name}: backup file does not match its recorded hash. Nothing was restored.")
        plain = decrypt(b, FILES[name], "OLD_STATE_KEY")
        if plain is None or canon(plain) != (info["plainJsonSha256"], info["items"]):
            die(f"{name}: backup does not decrypt with OLD_STATE_KEY to the recorded content. Nothing was restored.")
    for name, info in m["files"].items():
        dest = Path(root) / REL / name
        tmp = dest.with_suffix(dest.suffix + ".new")
        shutil.copy2(info["backup"], tmp)
        tmp.replace(dest)
    print(f"restored {len(m['files'])} file(s) byte-for-byte from the backup; also restore the OLD value of the GitHub secret (from your password manager).")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "apply", "verify", "rollback"])
    ap.add_argument("--backup-dir"); ap.add_argument("--manifest"); ap.add_argument("--root", default=str(ROOT))
    a = ap.parse_args(argv)
    if a.cmd in ("plan", "apply"):
        if not a.backup_dir:
            die("--backup-dir is required (a folder OUTSIDE the repository)")
        if Path(a.backup_dir).resolve().is_relative_to(Path(a.root).resolve()):
            die("the backup folder must be outside the repository")
        rehearse(a.root, a.backup_dir, a.cmd == "apply")
    elif a.cmd == "verify":
        if not a.manifest or not os.environ.get("NEW_STATE_KEY"):
            die("--manifest and NEW_STATE_KEY are required")
        verify(a.root, a.manifest)
    else:
        if not a.backup_dir or not os.environ.get("OLD_STATE_KEY"):
            die("--backup-dir and OLD_STATE_KEY are required")
        rollback(a.root, a.backup_dir)


if __name__ == "__main__":
    main()
