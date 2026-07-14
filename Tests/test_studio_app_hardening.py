"""Studio App hardening (2026-07 audit): zip-slip-safe extraction + update sha256."""
import sys
import json
import hashlib
import zipfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Source"))
sys.path.insert(0, str(ROOT / "Studio App"))

import engine_api
import updater


def test_safe_extract_blocks_zip_slip():
    """A '../' traversal member must NOT be written outside the extraction root."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        z = tmp / "evil.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("good/kick.wav", b"RIFFxxxxWAVE")
            zf.writestr("../escape.txt", b"pwned")          # path traversal
        dest = tmp / "ex"
        dest.mkdir()
        with zipfile.ZipFile(z) as zf:
            engine_api._safe_extract(zf, dest)
        assert (dest / "good" / "kick.wav").exists()         # good member kept
        assert not (tmp / "escape.txt").exists()             # traversal blocked


def test_check_for_update_surfaces_sha256():
    # Private-repo model: sha256 is parsed from the release BODY + lowercased.
    cfg = Path(tempfile.mkdtemp()) / "update_feed.json"
    cfg.write_text(json.dumps({"repo": "o/r", "token": "github_pat_x"}), encoding="utf-8")
    updater.FEED_CONFIG = cfg
    sha = "AB" * 32                                           # 64 hex, upper-case
    release = {"tag_name": "9.9.9", "body": "notes\nSHA256: " + sha,
               "assets": [{"name": "StemToAbleton.exe", "url": "http://x/assets/1"}]}

    class _R:
        def __init__(s, o): s._d = json.dumps(o).encode()
        def read(s): return s._d
        def __enter__(s): return s
        def __exit__(s, *a): return False
    orig = updater._api_get
    try:
        updater._api_get = lambda url, token, **kw: _R(release)
        info = updater.check_for_update("0.1.0")
    finally:
        updater._api_get = orig
    assert info["ok"] and info["available"]
    assert info["sha256"] == sha.lower()                     # normalised lowercase


def test_sha256_helper_matches_hashlib():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "x.bin"
        f.write_bytes(b"hello world")
        assert updater._sha256(f) == hashlib.sha256(b"hello world").hexdigest()


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except Exception:  # noqa: BLE001
            failed += 1
            print("FAIL", fn.__name__)
            traceback.print_exc()
    print(("ALL PASS" if not failed else str(failed) + " FAILED"))
    sys.exit(1 if failed else 0)
