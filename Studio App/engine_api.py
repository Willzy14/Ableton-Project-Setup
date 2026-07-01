"""Backend for the Studio App — wraps the project_builder engine.

Exposes a small API (profiles, settings, ingest, batch build) that the
PyWebView front-end calls via ``window.pywebview.api.*``. All the heavy lifting
(classification, BPM, layout, wet/dry, silent stems, flat ref) lives in
``Source/project_builder.py``; this module only orchestrates it for the UI:
per-user/partner colour profiles, drag-dropped WAV/AIFF/ZIP ingest, parsing the
typed "Artist - Title [Label]" name, and running a queue of projects in the
background while the front-end polls for progress.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import traceback
import zipfile
from pathlib import Path

# --- locate the engine ----------------------------------------------------
APP_DIR = Path(__file__).resolve().parent
REPO_DIR = APP_DIR.parent
SOURCE_DIR = REPO_DIR / "Source"
sys.path.insert(0, str(SOURCE_DIR))

from project_builder import (build_project, get_output_base,  # noqa: E402
                             SUBGROUP_CATEGORIES)
from stem_classifier import CATEGORIES, AUDIO_EXTENSIONS    # noqa: E402
from validate_project import validate_path                 # noqa: E402

# --- config locations ------------------------------------------------------
CONFIG_DIR = APP_DIR / "Config"
PROFILES_PATH = CONFIG_DIR / "profiles.json"
SETTINGS_PATH = CONFIG_DIR / "settings.json"

# Working-track categories the user can colour (kick rides with drums in the UI).
COLOR_CATEGORIES = ["drums", "bass", "music", "vocals", "fx", "sends"]

DEFAULT_COLORS = {c: CATEGORIES[c]["color"] for c in CATEGORIES}

# Ableton clip-colour palette (14 cols x 5 rows = 70 indices, row-major).
# Hexes are an approximation for the UI swatches; the ENGINE uses the index,
# which is authoritative — tweak a hex here if a swatch looks off, the build is
# unaffected.
ABLETON_PALETTE = [
    "#FF94A6", "#FFA529", "#CC9927", "#F7F47C", "#BFFB00", "#1AFF2F", "#25FFA8", "#5CFFE8",
    "#8BC5FF", "#5480E4", "#92A7FF", "#D86CE4", "#E553A0", "#FFFFFF",
    "#FF3636", "#F66C03", "#99724B", "#FFF034", "#87FF67", "#3DC300", "#00BFAF", "#19E9FF",
    "#10A4EE", "#007DC0", "#886CE4", "#B677C6", "#FF39D4", "#D0D0D0",
    "#E2675A", "#FFA374", "#D3A07C", "#FDEFA8", "#D2E498", "#BAD074", "#9CC2BB", "#A3CFE5",
    "#A6BFCC", "#85A5C2", "#A595B5", "#BF9FBE", "#BC7196", "#A9A9A9",
    "#C6000B", "#9E3500", "#714B00", "#C68B00", "#6E8500", "#3B6700", "#005950", "#005474",
    "#1D5780", "#0E3F80", "#5B47A1", "#702F62", "#9E2174", "#727272",
    "#AF2F00", "#A95300", "#724B00", "#DBC300", "#85961F", "#539400", "#0A9C8E", "#236384",
    "#1A2F96", "#2E52A3", "#624BAD", "#A9217E", "#FF50AE", "#3C3C3C",
]


# --- helpers ---------------------------------------------------------------
def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001 — missing/corrupt -> default
        return default


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def get_version():
    try:
        return (APP_DIR / "VERSION").read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return "0.0.0"


def default_profile(name="Default"):
    return {"name": name,
            "colors": {c: DEFAULT_COLORS[c] for c in COLOR_CATEGORIES}}


def load_profiles():
    data = _read_json(PROFILES_PATH, None)
    if not data or not data.get("profiles"):
        data = {"profiles": [default_profile()]}
        _write_json(PROFILES_PATH, data)
    return data["profiles"]


def save_profiles(profiles):
    _write_json(PROFILES_PATH, {"profiles": profiles})


def load_settings():
    data = _read_json(SETTINGS_PATH, None) or {}
    if not data.get("output_folder"):
        data["output_folder"] = str(get_output_base())
    if not data.get("active_profile"):
        data["active_profile"] = load_profiles()[0]["name"]
    if "subgroups" not in data:
        # Which categories get clustered into nested sub-groups (singer under
        # Vox, Kit/Percussion, instrument families). Default = all on.
        data["subgroups"] = list(SUBGROUP_CATEGORIES)
    return data


def save_settings(settings):
    _write_json(SETTINGS_PATH, settings)


def parse_project_name(text):
    """Parse 'Artist - Title [Label]' -> (artist, title, label).

    Falls back gracefully: missing label -> '', missing artist -> ''. The full
    typed string is always used verbatim as the project/folder name elsewhere.
    """
    text = (text or "").strip()
    label = ""
    m = re.search(r"\[([^\]]*)\]\s*$", text)
    if m:
        label = m.group(1).strip()
        text = text[:m.start()].strip()
    if " - " in text:
        artist, title = text.split(" - ", 1)
    else:
        artist, title = "", text
    return artist.strip(), title.strip(), label


def _os_open(path):
    """Open a file/folder with the OS default app — a .als launches Ableton."""
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)  # noqa: — Windows shell-opens with the default handler
    elif sys.platform == "darwin":
        import subprocess
        subprocess.run(["open", path], check=False)
    else:
        import subprocess
        subprocess.run(["xdg-open", path], check=False)


# Noise tokens stripped when guessing a title from a dropped folder/zip name.
_TITLE_NOISE = re.compile(
    r"\b(stems?|session|multitracks?|project|audio|files?|bounces?|masters?|wav|"
    r"24\s?44\.?1?|16\s?44\.?1?|44\.?1|48k?)\b", re.IGNORECASE)


def _title_from_paths(paths):
    """Best-guess 'Artist - Title [Label]' from the dropped folder/zip name.

    Pro packs are usually already named that way, so keep it verbatim and only
    strip obvious noise (Stems / Multitracks / Project / sample-rate tags)."""
    if not paths:
        return ""
    p0 = Path(paths[0])
    if p0.is_dir() or not p0.suffix:      # a folder (extension-less) name
        base = p0.name
    elif p0.suffix.lower() == ".zip":
        base = p0.stem
    else:
        base = p0.parent.name             # loose file(s) -> their folder
    n = re.sub(r"[_]+", " ", base)
    n = _TITLE_NOISE.sub("", n)
    n = re.sub(r"\s{2,}", " ", n).strip(" -_·")
    return n


def _audio_files_in(folder):
    return [p for p in Path(folder).iterdir()
            if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS]


def _find_audio_root(folder):
    """Return the deepest single folder that directly holds the audio files.

    Zips often extract to one wrapper folder; this digs through single-child
    wrappers to the folder that actually contains the stems.
    """
    folder = Path(folder)
    if _audio_files_in(folder):
        return folder
    subdirs = [p for p in folder.iterdir() if p.is_dir()]
    # search children for the one richest in audio
    best, best_n = folder, 0
    for d in subdirs:
        cand = _find_audio_root(d)
        n = len(_audio_files_in(cand))
        if n > best_n:
            best, best_n = cand, n
    return best


def prepare_stem_folder(paths, workdir):
    """Resolve dropped path(s) into ONE folder for the engine to scan.

    A single dropped folder or .zip is returned with its subfolder structure
    INTACT (so 'UPDATE STEMS' / 'REF' / version subfolders survive) — the engine
    resolves the tree and converts any non-WAV audio itself. Only a mix of loose
    files / multiple inputs is flattened into ``workdir``.
    """
    paths = [Path(p) for p in paths]

    # Single folder: scan it in place — subfolders preserved.
    if len(paths) == 1 and paths[0].is_dir():
        return _find_audio_root(paths[0])

    # Single zip: extract and scan the extraction root — subfolders preserved.
    # (The old code copied only the top-level files AND left a duplicate
    # '_zip_...' folder beside them, which was then mis-read as a 2nd version.)
    if len(paths) == 1 and paths[0].suffix.lower() == ".zip":
        ex = Path(workdir)
        ex.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(paths[0]) as z:
            z.extractall(ex)
        return _find_audio_root(ex)

    # Otherwise: loose files / multiple inputs — flatten into one staged folder.
    staged = Path(workdir)
    staged.mkdir(parents=True, exist_ok=True)

    def _ingest_file(f):
        if f.suffix.lower() in AUDIO_EXTENSIONS:
            shutil.copy2(f, staged / f.name)   # non-WAV converted later by the engine

    for p in paths:
        if p.is_dir():
            for f in _audio_files_in(_find_audio_root(p)):
                _ingest_file(f)
        elif p.suffix.lower() == ".zip":
            ex = Path(tempfile.mkdtemp(prefix="_zip_"))   # outside staged, no duplicate
            with zipfile.ZipFile(p) as z:
                z.extractall(ex)
            for f in _audio_files_in(_find_audio_root(ex)):
                _ingest_file(f)
        else:
            _ingest_file(p)

    return staged


# --- the API the front-end calls ------------------------------------------
class Api:
    """Methods here are reachable from JS as window.pywebview.api.<name>()."""

    def __init__(self):
        self._status = []      # one dict per queued project
        self._running = False
        self._window = None    # set by app.py for native dialogs

    # ---- bootstrap / settings ----
    def get_bootstrap(self):
        return {
            "profiles": load_profiles(),
            "settings": load_settings(),
            "palette": ABLETON_PALETTE,
            "colorCategories": COLOR_CATEGORIES,
            "version": get_version(),
        }

    def update_app(self):
        """Check for a newer version.

        Packaged EXE: query the public `latest.json` feed (configurable in
        update_feed.json). If a newer version is out, return its details so the
        UI can confirm before apply_update() swaps the EXE. Running from source:
        fall back to `git pull` (Dropbox usually syncs it already anyway).
        """
        import updater
        if updater.is_frozen():
            if not updater.feed_url():
                return {"ok": False, "error": "Update feed not set up yet "
                        "(no URL in update_feed.json)."}
            info = updater.check_for_update(get_version())
            if not info.get("ok"):
                return info
            if not info.get("available"):
                return {"ok": True, "changed": False, "version": get_version()}
            return {"ok": True, "changed": True, "needsApply": True,
                    "latest": info["latest"], "download_url": info["download_url"],
                    "notes": info.get("notes", ""), "version": get_version()}

        if not (REPO_DIR / ".git").exists():
            return {"ok": False, "error": "Not a git checkout — updates arrive via Dropbox sync."}
        try:
            import subprocess
            out = subprocess.run(["git", "pull", "--ff-only"], cwd=str(REPO_DIR),
                                 capture_output=True, text=True, timeout=60)
            msg = (out.stdout + out.stderr).strip()
            changed = "Already up to date" not in msg
            return {"ok": out.returncode == 0, "changed": changed,
                    "message": msg, "version": get_version()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def apply_update(self, download_url):
        """Download the new EXE, spawn the detached swap script, then quit so it
        can replace and relaunch us. Only meaningful in the packaged app.
        """
        import updater
        res = updater.apply_update(download_url)
        if res.get("ok") and res.get("relaunching"):
            def _quit():
                try:
                    if self._window is not None:
                        self._window.destroy()
                    else:
                        os._exit(0)
                except Exception:  # noqa: BLE001
                    os._exit(0)
            threading.Timer(0.6, _quit).start()
        return res

    def save_profile(self, profile):
        profiles = load_profiles()
        for i, p in enumerate(profiles):
            if p["name"].lower() == profile["name"].lower():
                profiles[i] = profile
                break
        else:
            profiles.append(profile)
        save_profiles(profiles)
        return {"ok": True, "profiles": profiles}

    def delete_profile(self, name):
        profiles = [p for p in load_profiles() if p["name"] != name]
        if not profiles:
            profiles = [default_profile()]
        save_profiles(profiles)
        return {"ok": True, "profiles": profiles}

    def set_setting(self, key, value):
        s = load_settings()
        s[key] = value
        save_settings(s)
        return {"ok": True, "settings": s}

    def pick_output_folder(self):
        if self._window is None:
            return {"ok": False, "error": "no window"}
        import webview
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if result:
            folder = result[0]
            self.set_setting("output_folder", folder)
            return {"ok": True, "folder": folder}
        return {"ok": False}

    def pick_paths(self, mode="folder"):
        """Native picker -> list of real paths. mode 'folder' or 'files'.

        Native dialogs are the dependable way to get true filesystem paths in a
        desktop webview (HTML5 drag-drop hides them); the dropzone calls this.
        """
        if self._window is None:
            return {"ok": False, "error": "no window"}
        import webview
        if mode == "files":
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=True,
                file_types=("Stems (*.wav;*.aif;*.aiff;*.zip)", "All files (*.*)"))
        else:
            result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return {"ok": bool(result), "paths": list(result) if result else []}

    def suggest_title(self, paths):
        """Guess a project title from dropped paths, for auto-filling the card."""
        try:
            return {"ok": True, "title": _title_from_paths(paths)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "title": ""}

    def open_project(self, als_path):
        """Open a finished .als (launches Ableton with the default handler)."""
        try:
            p = Path(als_path)
            if not p.exists():
                return {"ok": False, "error": "File not found — was it moved?"}
            _os_open(p)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def reveal_folder(self, folder):
        """Open a finished project folder in the file explorer."""
        try:
            p = Path(folder)
            if not p.exists():
                return {"ok": False, "error": "Folder not found — was it moved?"}
            _os_open(p)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    # ---- batch build ----
    def get_status(self):
        return {"running": self._running, "projects": self._status}

    def run_batch(self, projects):
        """projects: [{paths:[...], title:str, profile:str, bpm:str|None}]"""
        if self._running:
            return {"ok": False, "error": "A batch is already running."}
        self._status = [{"title": p.get("title") or "(untitled)",
                         "state": "pending", "message": "", "folder": "",
                         "als": "", "report": None}
                        for p in projects]
        self._running = True
        threading.Thread(target=self._run_batch_worker,
                         args=(projects,), daemon=True).start()
        return {"ok": True}

    def _run_batch_worker(self, projects):
        settings = load_settings()
        profiles = {p["name"]: p for p in load_profiles()}
        output_base = settings.get("output_folder") or str(get_output_base())
        # Global sub-group preference (Vocals/Drums/Music checkboxes). A list
        # (possibly empty to disable); None falls back to the engine default.
        subgroups = settings.get("subgroups")
        # The Studio App runs ML OFF (the decided model): named packs classify by
        # filename, and ML in the GUI is heavy (Demucs spins the fans) and — when
        # frozen — would spawn the GUI EXE as its own subprocess. ML-only naming
        # of fully-generic stems stays a CLI job.
        use_ml = False

        for i, proj in enumerate(projects):
            st = self._status[i]
            tmp = None
            try:
                st["state"] = "running"
                st["message"] = "Preparing stems…"
                profile = profiles.get(proj.get("profile")) or default_profile()
                colors = {**DEFAULT_COLORS, **profile.get("colors", {})}

                tmp = Path(tempfile.mkdtemp(prefix="studioapp_"))
                stem_folder = prepare_stem_folder(proj["paths"], tmp / "stems")

                title = proj.get("title") or "Untitled"
                artist, ttl, label = parse_project_name(title)
                bpm = proj.get("bpm") or None

                st["message"] = "Building project…"
                folder = build_project(
                    str(stem_folder), artist, ttl, label,
                    bpm=bpm, output_base=output_base,
                    project_name=title, category_colors=colors,
                    subgroup_categories=subgroups, use_ml=use_ml,
                )
                st["folder"] = str(folder)

                st["message"] = "Validating…"
                als = next(Path(folder).glob("*.als"), None)
                st["als"] = str(als) if als else ""
                st["report"] = _read_json(Path(folder) / "Session Report.json", None)
                ok = bool(als) and validate_path(als).ok
                st["state"] = "done" if ok else "warn"
                st["message"] = "Done" if ok else "Built — validator flagged it, check by ear"
            except Exception as exc:  # noqa: BLE001 — one bad pack must not kill the batch
                st["state"] = "failed"
                st["message"] = str(exc)
                st["trace"] = traceback.format_exc()
            finally:
                if tmp and tmp.exists():
                    shutil.rmtree(tmp, ignore_errors=True)

        self._running = False
