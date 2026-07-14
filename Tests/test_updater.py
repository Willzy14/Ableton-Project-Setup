"""Self-updater (PRIVATE GitHub-releases model): version compare, config read,
release parsing, and swap-script generation.

Pure-function + mocked-API coverage (no real EXE / network). The GitHub call is
stubbed; the real EXE swap + relaunch is a frozen-only path Sam verifies on a build.
"""
import sys
import json
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "Studio App"
sys.path.insert(0, str(APP_DIR))

import updater


class _FakeResp:
    def __init__(self, obj):
        self._d = json.dumps(obj).encode("utf-8")
    def read(self):
        return self._d
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def _with_config(repo="Willzy14/StemToAbleton-Releases", token="github_pat_x"):
    tmp = Path(tempfile.mkdtemp()) / "update_feed.json"
    tmp.write_text(json.dumps({"repo": repo, "token": token}), encoding="utf-8")
    updater.FEED_CONFIG = tmp


def test_semver_compare():
    assert updater._semver("0.2.0") > updater._semver("0.1.9")
    assert updater._semver("1.0") == updater._semver("1.0.0")
    assert updater._semver("0.1.0") < updater._semver("0.10.0")


def test_config_reads_repo_and_token():
    _with_config("owner/rel", "github_pat_abc")
    cfg = updater._config()
    assert cfg["repo"] == "owner/rel" and cfg["token"] == "github_pat_abc"


def test_check_no_repo_configured():
    tmp = Path(tempfile.mkdtemp()) / "update_feed.json"
    tmp.write_text(json.dumps({"repo": "", "token": ""}), encoding="utf-8")
    updater.FEED_CONFIG = tmp
    r = updater.check_for_update("0.1.0")
    assert not r["ok"] and "repo" in r["error"].lower()


def test_check_parses_latest_release(monkeypatched=None):
    _with_config()
    release = {
        "tag_name": "0.3.0",
        "body": "Fixes\nsha256: " + ("a" * 64),
        "assets": [
            {"name": "notes.txt", "url": "https://api.github.com/.../assets/1"},
            {"name": "StemToAbleton.exe", "url": "https://api.github.com/x/assets/9"},
        ],
    }
    orig = updater._api_get
    try:
        updater._api_get = lambda url, token, **kw: _FakeResp(release)
        r = updater.check_for_update("0.2.0")
    finally:
        updater._api_get = orig
    assert r["ok"] and r["available"]
    assert r["latest"] == "0.3.0"
    assert r["asset_url"].endswith("/assets/9")     # picked the .exe asset
    assert r["sha256"] == "a" * 64                  # parsed from the body


def test_check_not_newer():
    _with_config()
    orig = updater._api_get
    try:
        updater._api_get = lambda url, token, **kw: _FakeResp(
            {"tag_name": "0.1.0", "assets": []})
        r = updater.check_for_update("0.1.0")
    finally:
        updater._api_get = orig
    assert r["ok"] and not r["available"]


def test_swap_script_retries_relaunches_resets_env():
    tmp = Path(tempfile.mkdtemp())
    bat = updater.write_swap_script(tmp / "new.exe", tmp / "app.exe", tmp)
    raw = bat.read_bytes()
    assert b"\r\n" in raw and b"\r\r\n" not in raw   # clean CRLF for cmd.exe
    text = raw.decode("utf-8")
    assert ":retry" in text and "goto retry" in text
    assert "move /y" in text and "new.exe" in text and "app.exe" in text
    assert "PYINSTALLER_RESET_ENVIRONMENT=1" in text  # one-file fresh relaunch
    assert 'start "" ' in text and "del " in text


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
