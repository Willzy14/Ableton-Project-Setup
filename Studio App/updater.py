"""Self-update for the packaged Studio App via a public `latest.json` feed.

Distribution model (Sam, 2026-06-29): the source repo stays PRIVATE; the built
EXE is published to a small PUBLIC releases feed (a `latest.json` + the .exe).
The app checks that feed on demand and swaps its own EXE when a newer version is
out. The feed is public, so NO token is ever baked into the distributed EXE.

The feed URL is configurable — it lives in `update_feed.json` next to this file
(committed with an empty placeholder), so Sam can point it at whatever hosting he
sets up without touching code. When running from source (not frozen), update is
a no-op here; the dev/git-pull path lives in engine_api.

latest.json shape:
    {"version": "0.2.0",
     "download_url": "https://.../StemToAbleton.exe",
     "notes": "What changed"}
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
FEED_CONFIG = APP_DIR / "update_feed.json"
DEFAULT_FEED_URL = ""   # set via update_feed.json (hosting decided later)

# Windows process-creation flags (DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
# so the swap script outlives the exiting app.
_DETACHED = 0x00000008 | 0x00000200


def is_frozen():
    """True when running as a PyInstaller-built EXE (vs from source)."""
    return bool(getattr(sys, "frozen", False))


def _feed_config_paths():
    """Where to look for the feed config, most specific first. A file dropped
    NEXT TO the distributed EXE wins, so the URL can be set/changed without a
    rebuild; the bundled placeholder is the fallback.
    """
    paths = []
    if is_frozen():
        paths.append(Path(sys.executable).resolve().parent / "update_feed.json")
    paths.append(FEED_CONFIG)
    return paths


def feed_url():
    """The configured latest.json URL, or '' when not set up yet."""
    for path in _feed_config_paths():
        try:
            if path.exists():
                url = (json.loads(path.read_text(encoding="utf-8"))
                       .get("feed_url") or "").strip()
                if url:
                    return url
        except Exception:  # noqa: BLE001 — skip a corrupt config
            continue
    return DEFAULT_FEED_URL


def _semver(v):
    nums = re.findall(r"\d+", v or "")
    nums = [int(x) for x in nums[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def check_for_update(current_version, url=None):
    """Fetch the feed and compare versions. Pure-ish — `url` is overridable so
    it can be tested against a local file:// latest.json.

    Returns {ok, available, latest, download_url, notes} or {ok: False, error}.
    """
    url = url or feed_url()
    if not url:
        return {"ok": False, "error": "No update feed configured yet."}
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "Couldn't reach the update feed: " + str(exc)}
    latest = str(data.get("version") or "0.0.0")
    return {
        "ok": True,
        "available": _semver(latest) > _semver(current_version),
        "latest": latest,
        "download_url": data.get("download_url") or data.get("url") or "",
        "notes": data.get("notes", ""),
    }


def write_swap_script(new_exe, target_exe, workdir):
    """Write a .bat that waits for the app to release its EXE, swaps in the new
    one, relaunches it, and deletes itself.

    `move` fails while the running app still locks target_exe, so it retries
    until the app has exited — no fragile process-name matching.
    """
    bat = Path(workdir) / "apply_update.bat"
    lines = [
        "@echo off",
        ":retry",
        'move /y "%s" "%s" >nul 2>nul' % (new_exe, target_exe),
        "if errorlevel 1 (",
        "  timeout /t 1 /nobreak >nul",
        "  goto retry",
        ")",
        'start "" "%s"' % target_exe,
        'del "%~f0"',
        "",
    ]
    # newline="" so the CRLFs we wrote aren't doubled to \r\r\n by the writer.
    with open(bat, "w", encoding="utf-8", newline="") as fh:
        fh.write("\r\n".join(lines))
    return bat


def stage_download(download_url, workdir):
    """Download the new EXE into workdir. Returns its path."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    dest = workdir / "StemToAbleton.new.exe"
    with urllib.request.urlopen(download_url, timeout=300) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    return dest


def apply_update(download_url):
    """Download the new EXE and spawn the detached swap script. The caller must
    then exit the app so the script can replace and relaunch it.
    """
    if not is_frozen():
        return {"ok": False, "error": "Update-apply only runs in the packaged app."}
    if not download_url:
        return {"ok": False, "error": "No download URL in the update feed."}
    target = Path(sys.executable)
    work = Path(tempfile.mkdtemp(prefix="stemupd_"))
    try:
        new_exe = stage_download(download_url, work)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "Download failed: " + str(exc)}
    bat = write_swap_script(new_exe, target, work)
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=_DETACHED, close_fds=True)
    return {"ok": True, "relaunching": True}
