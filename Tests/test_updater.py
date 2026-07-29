"""Self-updater (PRIVATE GitHub-releases model): version compare, config read,
release parsing, and swap-script generation.

Pure-function + mocked-API coverage (no real EXE / network). The GitHub call is
stubbed; the real EXE swap + relaunch is a frozen-only path Sam verifies on a build.
"""
import sys
import json
import ssl
import tempfile
import urllib.error
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


def test_api_get_retries_with_certifi_on_cert_verify_failure():
    # Real-world case (2026-07-29): one of several machines running the
    # identical build failed with CERTIFICATE_VERIFY_FAILED / "unable to get
    # local issuer certificate" while the other two updated fine -- a stale
    # local cert store, not a code bug. _api_get must retry once with
    # certifi's own bundle instead of failing the update outright over it.
    if updater.certifi is None:
        print("SKIP test_api_get_retries_with_certifi_on_cert_verify_failure (no certifi installed)")
        return
    calls = []

    def fake_fetch(url, headers, ssl_context=None):
        calls.append(ssl_context)
        if ssl_context is None:
            raise urllib.error.URLError(ssl.SSLCertVerificationError(
                1, "unable to get local issuer certificate"))
        return _FakeResp({"ok": True})

    orig = updater._fetch
    try:
        updater._fetch = fake_fetch
        with updater._api_get("https://api.github.com/x", "tok") as resp:
            assert json.loads(resp.read()) == {"ok": True}
    finally:
        updater._fetch = orig
    assert len(calls) == 2
    assert calls[0] is None            # first attempt: default (host) trust store
    assert calls[1] is not None        # retry: explicit certifi-backed context


def test_api_get_does_not_mask_non_ssl_errors():
    def fake_fetch(url, headers, ssl_context=None):
        raise urllib.error.URLError("connection refused")
    orig = updater._fetch
    try:
        updater._fetch = fake_fetch
        try:
            updater._api_get("https://api.github.com/x", "tok")
            assert False, "expected URLError to propagate"
        except urllib.error.URLError:
            pass
    finally:
        updater._fetch = orig


def test_swap_script_retries_relaunches_reports_outcome():
    tmp = Path(tempfile.mkdtemp())
    bat = updater.write_swap_script(tmp / "new.exe", tmp / "app.exe", tmp, "v0.1.1")
    raw = bat.read_bytes()
    assert b"\r\n" in raw and b"\r\r\n" not in raw   # clean CRLF for cmd.exe
    text = raw.decode("utf-8")
    assert ":retry" in text and "goto retry" in text
    assert "move /y" in text and "new.exe" in text and "app.exe" in text
    assert 'start "" ' in text
    assert "del " not in text   # the self-delete trick errors after deleting itself
    # Bounded retry (used to loop forever with no feedback) + a visible window
    # instead of the old fully-detached one (Sam couldn't tell if it was stuck).
    assert "tries+=1" in text and "GEQ 30" in text
    assert "ping -n 2 127.0.0.1" in text          # console-safe sleep, not `timeout`
    assert "PYINSTALLER_RESET_ENVIRONMENT" not in text  # dead flag, removed
    # Both outcomes get written somewhere the next launch can read and report.
    assert ":ok" in text and "update_ok.txt" in text and "v0.1.1" in text
    assert ":fail" in text and "update_failed.txt" in text
    # Every literal '>' outside a real redirect must be caret-escaped, or cmd.exe
    # silently creates a stray file instead of printing it (a real bug caught by
    # actually RUNNING this script, 2026-07-29 — the `title` line's arrow wasn't
    # escaped and cmd.exe redirected it into a file called "Ableton"). Redirect
    # targets (move/echo-to-marker/ping output) are the only allowed bare '>'.
    for line in text.splitlines():
        if line.startswith(("move ", "ping ")) or "> \"" in line or ">nul" in line:
            continue
        assert "^>" in line or ">" not in line, "unescaped > will redirect: " + repr(line)


def test_pop_update_result_reads_and_clears_markers(monkeypatch=None):
    tmp = Path(tempfile.mkdtemp())
    orig = updater._config_dir
    try:
        updater._config_dir = lambda: tmp
        assert updater.pop_update_result() is None      # nothing written yet

        (tmp / "update_ok.txt").write_text("v0.1.1\n", encoding="utf-8")
        r = updater.pop_update_result()
        assert r == {"status": "ok", "version": "v0.1.1"}
        assert not (tmp / "update_ok.txt").exists()      # cleared after reading
        assert updater.pop_update_result() is None        # only reports once

        (tmp / "update_failed.txt").write_text("could not replace the app\n", encoding="utf-8")
        r = updater.pop_update_result()
        assert r == {"status": "failed", "message": "could not replace the app"}
        assert not (tmp / "update_failed.txt").exists()
    finally:
        updater._config_dir = orig


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
