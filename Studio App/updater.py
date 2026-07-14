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
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
FEED_CONFIG = APP_DIR / "update_feed.json"
_API = "https://api.github.com"
_UA = "StemToAbleton-Updater"

# Windows process-creation flags (DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
# so the swap script outlives the exiting app.
_DETACHED = 0x00000008 | 0x00000200


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


def _semver(v):
    nums = [int(x) for x in re.findall(r"\d+", v or "")[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def _api_get(url, token, accept="application/vnd.github+json", strip_auth_on_redirect=True):
    """GET a GitHub API URL with the token. For release-ASSET downloads GitHub 302s
    to a signed URL that must be fetched WITHOUT the Authorization header (S3 rejects
    it) — so on a cross-host redirect we drop auth and refetch."""
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": _UA,
    })

    class _NoAuthRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            newreq = super().redirect_request(req, fp, code, msg, headers, newurl)
            if newreq is not None and strip_auth_on_redirect:
                newreq.headers = {k: v for k, v in newreq.headers.items()
                                  if k.lower() != "authorization"}
            return newreq

    opener = urllib.request.build_opener(_NoAuthRedirect())
    return opener.open(req, timeout=300)


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


def write_swap_script(new_exe, target_exe, workdir):
    """Write a .bat that waits for the app to release its EXE, swaps in the new one,
    relaunches it, and deletes itself. `move` retries until the running app exits."""
    bat = Path(workdir) / "apply_update.bat"
    lines = [
        "@echo off",
        ":retry",
        'move /y "%s" "%s" >nul 2>nul' % (new_exe, target_exe),
        "if errorlevel 1 (",
        "  timeout /t 1 /nobreak >nul",
        "  goto retry",
        ")",
        # A PyInstaller one-file EXE must relaunch as a FRESH top-level instance,
        # or it can try to reuse the just-replaced app's _MEIPASS temp environment.
        "set PYINSTALLER_RESET_ENVIRONMENT=1",
        'start "" "%s"' % target_exe,
        'del "%~f0"',
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


def apply_update(asset_url, expected_sha256=""):
    """Download the new EXE from the private repo, VERIFY its sha256 (if published),
    then spawn the detached swap script. The caller then exits so the script can
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
    bat = write_swap_script(new_exe, target, work)
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=_DETACHED, close_fds=True)
    return {"ok": True, "relaunching": True}
