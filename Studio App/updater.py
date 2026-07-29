"""Self-update from a PRIVATE GitHub Releases repo (Sam, 2026-07-14).

DISTRIBUTION MODEL: the tool must NOT be publicly downloadable. So the built EXE
is published to a **private** GitHub repo's Releases, and the app downloads its own
updates using a baked-in **fine-grained, read-only** Personal Access Token (scope:
Contents = Read-only on that ONE repo). The token is injected at BUILD time by
build_exe.py and is NEVER committed to git. It is extractable by someone who already
holds the EXE — but it is read-only, single-repo, and revocable (rotate the PAT +
ship a new build), so a leak only lets a trusted holder re-download the app they
already have. Publishing uses the `gh` CLI on Sam's build machine (his own login);
no publish token is baked in.

Config (bundled `update_feed.json`, `token` filled in at build time):
    { "repo": "owner/name", "token": "github_pat_..." }

When running from source (not frozen), update is a no-op here — the dev git-pull
path lives in engine_api.
"""
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
from pathlib import Path

try:
    import certifi
except ImportError:  # pragma: no cover — always present in practice; degrade, don't crash
    certifi = None

APP_DIR = Path(__file__).resolve().parent
FEED_CONFIG = APP_DIR / "update_feed.json"
_API = "https://api.github.com"
_UA = "StemToAbleton-Updater"

# Windows process-creation flags (CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP)
# so the swap script outlives the exiting app AND is visible. Used to be fully
# DETACHED (no console at all) — but a swap can take several seconds (Windows
# won't release the lock on a running exe's own image until it fully exits),
# and a silent invisible wait looked exactly like "the update did nothing"
# (Sam, 2026-07-29). Showing SOMETHING beats a silent gap.
_SWAP_PROCESS_FLAGS = 0x00000010 | 0x00000200


def is_frozen():
    """True when running as a PyInstaller-built EXE (vs from source)."""
    return bool(getattr(sys, "frozen", False))


def _config_paths():
    """Where to look for the release config, most specific first. A file dropped
    NEXT TO the distributed EXE wins (lets Sam repoint/rotate without a rebuild);
    the bundled config is the fallback."""
    paths = []
    if is_frozen():
        paths.append(Path(sys.executable).resolve().parent / "update_feed.json")
    paths.append(FEED_CONFIG)
    return paths


def _config():
    """Return {repo, token} from the release config (first that has a repo)."""
    for path in _config_paths():
        try:
            if path.exists():
                cfg = json.loads(path.read_text(encoding="utf-8"))
                if (cfg.get("repo") or "").strip():
                    return {"repo": cfg["repo"].strip(),
                            "token": (cfg.get("token") or "").strip()}
        except Exception:  # noqa: BLE001 — skip a corrupt config
            continue
    return {"repo": "", "token": ""}


def _config_dir():
    """The same stable per-user folder engine_api.py persists profiles/settings
    to (its CONFIG_DIR) — used here so the result marker survives the swap and
    is found regardless of where the exe itself lives."""
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / "StemToAbleton"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ok_marker():
    return _config_dir() / "update_ok.txt"


def _fail_marker():
    return _config_dir() / "update_failed.txt"


def pop_update_result():
    """Read + clear the last swap script's outcome, if any, so the (re)launched
    app can tell the user whether their last Update actually landed instead of
    leaving them guessing (see write_swap_script). Returns
    {"status": "ok", "version": "v0.1.1"} / {"status": "failed", "message": "..."}
    / None if there's nothing to report."""
    try:
        ok, fail = _ok_marker(), _fail_marker()
        if ok.exists():
            result = {"status": "ok", "version": ok.read_text(encoding="utf-8").strip()}
            ok.unlink(missing_ok=True)
            fail.unlink(missing_ok=True)
            return result
        if fail.exists():
            result = {"status": "failed", "message": fail.read_text(encoding="utf-8").strip()}
            fail.unlink(missing_ok=True)
            return result
    except Exception:  # noqa: BLE001 — a marker read failure just means no news
        pass
    return None


def _semver(v):
    nums = [int(x) for x in re.findall(r"\d+", v or "")[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


class _NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub 302s a release-ASSET URL to a signed S3 URL that must be fetched
    WITHOUT the Authorization header (S3 rejects it) — strip auth on redirect."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newreq = super().redirect_request(req, fp, code, msg, headers, newurl)
        if newreq is not None:
            newreq.headers = {k: v for k, v in newreq.headers.items()
                              if k.lower() != "authorization"}
        return newreq


def _fetch(url, headers, ssl_context=None):
    handlers = [_NoAuthRedirect()]
    if ssl_context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=ssl_context))
    opener = urllib.request.build_opener(*handlers)
    return opener.open(urllib.request.Request(url, headers=headers), timeout=300)


def _api_get(url, token, accept="application/vnd.github+json"):
    """GET a GitHub API URL with the token.

    Some machines' local certificate store is missing or stale and can't
    verify GitHub's cert chain even though the connection itself is fine —
    seen in the field (2026-07-29): CERTIFICATE_VERIFY_FAILED / "unable to get
    local issuer certificate" on one of several machines running the IDENTICAL
    build (the other two updated fine), so it's a host-machine cert-store
    issue, not a code bug. Retries once with certifi's independently-
    maintained CA bundle rather than failing the update outright over that
    machine's own cert hygiene.
    """
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": _UA,
    }
    try:
        return _fetch(url, headers)
    except urllib.error.URLError as exc:
        # Narrowly SSLCertVerificationError, not the broader SSLError — a
        # protocol/connection-level TLS failure (SSLEOFError etc.) wouldn't be
        # fixed by swapping the CA bundle, and retrying it just risks masking
        # the real error with a less informative one (Codex review, 2026-07-29).
        if certifi is not None and isinstance(exc.reason, ssl.SSLCertVerificationError):
            return _fetch(url, headers, ssl.create_default_context(cafile=certifi.where()))
        raise


def check_for_update(current_version):
    """Query the private repo's latest release. Returns
    {ok, available, latest, asset_url, sha256, notes} or {ok: False, error}."""
    cfg = _config()
    if not cfg["repo"]:
        return {"ok": False, "error": "No update repo configured yet."}
    if not cfg["token"]:
        return {"ok": False, "error": "This build has no update token baked in."}
    url = "%s/repos/%s/releases/latest" % (_API, cfg["repo"])
    try:
        with _api_get(url, cfg["token"]) as resp:
            rel = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "Couldn't reach the update repo: " + str(exc)}
    latest = str(rel.get("tag_name") or rel.get("name") or "0.0.0")
    assets = rel.get("assets") or []
    exe = next((a for a in assets if str(a.get("name", "")).lower().endswith(".exe")), None)
    # sha256: prefer a "sha256: <hex>" line in the release body, else a *.sha256 asset.
    body = rel.get("body") or ""
    m = re.search(r"sha-?256[:=\s]+([0-9a-fA-F]{64})", body, re.IGNORECASE)
    sha = m.group(1).lower() if m else ""
    return {
        "ok": True,
        "available": _semver(latest) > _semver(current_version),
        "latest": latest,
        "asset_url": (exe.get("url") if exe else ""),   # the API asset URL (auth'd)
        "sha256": sha,
        "notes": rel.get("body", ""),
    }


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_swap_script(new_exe, target_exe, workdir, new_version=""):
    """Write a .bat that waits for the app to release its EXE and swaps in the
    new one, then relaunches it.

    `move` retries until the running app exits (Windows won't let you replace a
    running exe's own image until it fully terminates) — but it used to retry
    FOREVER with no visible feedback, which on a real update (Sam, 2026-07-29)
    looked exactly like nothing was happening even though the swap was working;
    it just took a few seconds longer than anyone was willing to wait and stare
    at a closed app with no window at all. Now: capped at 30 tries (~30s), and
    writes a plain marker file the next launch reads (see pop_update_result) so
    the outcome — success OR failure — is always reported, never silent.

    Deliberately does NOT self-delete (the classic `del "%~f0"` trick errors
    with "The batch file cannot be found" on whatever line runs after it, since
    cmd re-reads the .bat from disk to execute each line) — it's a few KB left
    in its own throwaway temp workdir, not worth the fragility.
    """
    bat = Path(workdir) / "apply_update.bat"
    ok_marker = str(_ok_marker())
    fail_marker = str(_fail_marker())
    lines = [
        "@echo off",
        "title Installing Stem -^> Ableton update...",
        "echo Installing %s ..." % (new_version or "update"),
        "echo Please wait - this window closes on its own.",
        "set tries=0",
        ":retry",
        'move /y "%s" "%s" >nul 2>nul' % (new_exe, target_exe),
        "if not errorlevel 1 goto ok",
        "set /a tries+=1",
        "if %tries% GEQ 30 goto fail",
        # ping-based sleep: works with no console attached too, unlike `timeout`
        # (which errors immediately without a real stdin handle).
        "ping -n 2 127.0.0.1 >nul",
        "goto retry",
        "",
        ":ok",
        'echo %s> "%s"' % (new_version or "unknown", ok_marker),
        "echo Done - reopening...",
        'start "" "%s"' % target_exe,
        "exit",
        "",
        ":fail",
        'echo Update FAILED - could not replace the app after 30 seconds.> "%s"' % fail_marker,
        "echo.",
        "echo Update FAILED - could not replace the app after 30 seconds.",
        "echo Close every Stem -^> Ableton window completely, then click Update again.",
        "ping -n 6 127.0.0.1 >nul",
        "",
    ]
    with open(bat, "w", encoding="utf-8", newline="") as fh:
        fh.write("\r\n".join(lines))
    return bat


def stage_download(asset_url, token, workdir):
    """Download the release-asset binary (auth'd, follows GitHub's signed-URL 302
    with auth stripped) into workdir. Returns its path."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    dest = workdir / "StemToAbleton.new.exe"
    with _api_get(asset_url, token, accept="application/octet-stream") as resp, \
            open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    return dest


def apply_update(asset_url, expected_sha256="", new_version=""):
    """Download the new EXE from the private repo, VERIFY its sha256 (if published),
    then spawn the visible swap script. The caller then exits so the script can
    replace + relaunch the EXE."""
    if not is_frozen():
        return {"ok": False, "error": "Update-apply only runs in the packaged app."}
    if not asset_url:
        return {"ok": False, "error": "No .exe asset found in the latest release."}
    cfg = _config()
    if not cfg["token"]:
        return {"ok": False, "error": "This build has no update token baked in."}
    target = Path(sys.executable)
    work = Path(tempfile.mkdtemp(prefix="stemupd_"))
    try:
        new_exe = stage_download(asset_url, cfg["token"], work)
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(work, ignore_errors=True)
        return {"ok": False, "error": "Download failed: " + str(exc)}
    expected = (expected_sha256 or "").strip().lower()
    if expected:
        actual = _sha256(new_exe)
        if actual != expected:
            shutil.rmtree(work, ignore_errors=True)
            return {"ok": False, "error": "Update REJECTED — the downloaded file's "
                    "checksum didn't match the release (expected " + expected[:12]
                    + "…, got " + actual[:12] + "…). Not installing."}
    bat = write_swap_script(new_exe, target, work, new_version)
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=_SWAP_PROCESS_FLAGS, close_fds=True)
    return {"ok": True, "relaunching": True}
