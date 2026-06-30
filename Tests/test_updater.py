"""Self-updater: version compare, feed read, and swap-script generation.

Pure-function coverage (no real EXE / network) — check_for_update reads a local
file:// latest.json; the swap script is checked for content. The actual EXE swap
+ relaunch is a frozen-only path Sam verifies on a real build.
"""
import sys
import json
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "Studio App"
sys.path.insert(0, str(APP_DIR))

import updater


def _feed(tmp, version, url="https://example.com/StemToAbleton.exe", notes="x"):
    p = Path(tmp) / "latest.json"
    p.write_text(json.dumps({"version": version, "download_url": url,
                             "notes": notes}), encoding="utf-8")
    return p.as_uri()


def test_semver_compare():
    assert updater._semver("0.2.0") > updater._semver("0.1.9")
    assert updater._semver("1.0") == updater._semver("1.0.0")
    assert updater._semver("0.1.0") < updater._semver("0.10.0")


def test_check_for_update_sees_newer():
    tmp = tempfile.mkdtemp()
    uri = _feed(tmp, "0.2.0")
    r = updater.check_for_update("0.1.0", url=uri)
    assert r["ok"] and r["available"]
    assert r["latest"] == "0.2.0"
    assert r["download_url"].endswith("StemToAbleton.exe")


def test_check_for_update_already_current():
    tmp = tempfile.mkdtemp()
    uri = _feed(tmp, "0.1.0")
    r = updater.check_for_update("0.1.0", url=uri)
    assert r["ok"] and not r["available"]


def test_check_for_update_no_url():
    r = updater.check_for_update("0.1.0", url="")
    assert not r["ok"] and "configured" in r["error"]


def test_check_for_update_unreachable():
    r = updater.check_for_update("0.1.0", url="file:///definitely/not/here.json")
    assert not r["ok"] and "feed" in r["error"].lower()


def test_swap_script_retries_then_relaunches():
    tmp = Path(tempfile.mkdtemp())
    bat = updater.write_swap_script(tmp / "new.exe", tmp / "app.exe", tmp)
    raw = bat.read_bytes()
    assert b"\r\n" in raw and b"\r\r\n" not in raw   # clean CRLF for cmd.exe
    text = raw.decode("utf-8")
    assert ":retry" in text
    assert "move /y" in text and "new.exe" in text and "app.exe" in text
    assert "goto retry" in text                 # waits for the lock to clear
    assert 'start "" ' in text                  # relaunches
    assert "del " in text                       # cleans itself up


def test_feed_url_reads_bundled_config_when_set():
    # Point the module's bundled config at a temp file with a URL set.
    tmp = Path(tempfile.mkdtemp())
    cfg = tmp / "update_feed.json"
    cfg.write_text(json.dumps({"feed_url": "https://feed.example/latest.json"}),
                   encoding="utf-8")
    orig = updater.FEED_CONFIG
    try:
        updater.FEED_CONFIG = cfg
        assert updater.feed_url() == "https://feed.example/latest.json"
    finally:
        updater.FEED_CONFIG = orig


def test_feed_url_empty_when_placeholder():
    # The committed placeholder has an empty feed_url -> not configured.
    assert updater.feed_url() == ""


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except Exception:  # noqa: BLE001
            failed += 1
            print("FAIL", fn.__name__)
            traceback.print_exc()
    print("ALL PASS" if not failed else str(failed) + " FAILED")
    sys.exit(1 if failed else 0)
