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
    with tempfile.TemporaryDirectory() as tmp:
        feed = Path(tmp) / "latest.json"
        feed.write_text(json.dumps({
            "version": "9.9.9", "download_url": "http://x/app.exe",
            "sha256": "ABC123"}))
        info = updater.check_for_update("0.1.0", url=feed.as_uri())
        assert info["ok"] and info["available"]
        assert info["sha256"] == "abc123"                    # normalised lowercase


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
