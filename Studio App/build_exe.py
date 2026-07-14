"""Build the Studio App into a single self-contained Windows EXE (ML-off).

    py -3.13 "Studio App/build_exe.py"

Produces Studio App/dist/StemToAbleton.exe. The EXE bundles the engine
(Source/*.py), the Web UI, the VERSION + update_feed.json, and the Ableton
template ALS, so it runs on a studio machine with no Python, no Dropbox, and no
template in the User Library. The heavy ML stack (torch/demucs/whisper) is
EXCLUDED — filename + audio classification still works; ML-only naming of
totally generic stems is the single thing the EXE gives up, by design (it would
balloon the download to multiple GB).

RELEASE ORDER (important — the EXE bakes in the current VERSION at build time):
  1. Bump first:   publish_release.py --bump patch   (edits VERSION only)
  2. Build:        build_exe.py                       (bakes the bumped VERSION)
  3. Stamp+upload: publish_release.py --url <exe-url> (writes latest.json AT the
     current VERSION — do NOT --bump here, or latest.json would advertise a
     version newer than the EXE and the app would self-update in a loop).
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
REPO_DIR = APP_DIR.parent
SOURCE_DIR = REPO_DIR / "Source"
sys.path.insert(0, str(SOURCE_DIR))

from project_builder import get_template_path  # noqa: E402

NAME = "StemToAbleton"
SEP = ";"  # Windows --add-data separator (src;dest)

# Local, gitignored build inputs (never committed):
RELEASE_TOKEN_FILE = APP_DIR / "release_token.local"   # the fine-grained read-only PAT
WEBVIEW2_DIR = APP_DIR / "webview2_runtime"            # extracted WebView2 Fixed Version runtime


def _release_token():
    """The private-repo READ-ONLY PAT to bake in, from env or the local file.
    Never comes from git — the committed update_feed.json leaves token empty."""
    tok = (os.environ.get("STEMTOABLETON_RELEASE_TOKEN") or "").strip()
    if tok:
        return tok
    if RELEASE_TOKEN_FILE.exists():
        return RELEASE_TOKEN_FILE.read_text(encoding="utf-8").strip()
    return ""


def _baked_feed(work):
    """Write update_feed.json with the release token filled in (repo comes from the
    committed file), for bundling. The token is injected here at build time only."""
    cfg = json.loads((APP_DIR / "update_feed.json").read_text(encoding="utf-8"))
    cfg = {k: v for k, v in cfg.items() if not k.startswith("_")}
    cfg["token"] = _release_token()
    out = work / "update_feed.json"
    out.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    if not cfg["token"]:
        print("WARNING: no release token (STEMTOABLETON_RELEASE_TOKEN or "
              + RELEASE_TOKEN_FILE.name + ") — the built EXE won't be able to "
              "auto-update. Add the read-only PAT and rebuild to enable updates.")
    else:
        print("Release token baked in (auto-update from the private repo enabled).")
    return out


def _webview2_data():
    """If the WebView2 Fixed Version runtime is present locally, return (root, dest)
    to bundle it at 'webview2/' so the EXE is self-contained on ANY machine. app.py
    points pywebview at it via WEBVIEW2_BROWSER_EXECUTABLE_FOLDER when frozen."""
    if not WEBVIEW2_DIR.exists():
        print("WARNING: no WebView2 runtime at " + str(WEBVIEW2_DIR) + " — the EXE "
              "will rely on the target machine's own WebView2 (the in-app preflight "
              "warns + prompts to install if it's missing). To bundle it, extract "
              "Microsoft's WebView2 Fixed Version runtime there and rebuild.")
        return None
    hits = list(WEBVIEW2_DIR.rglob("msedgewebview2.exe"))
    if not hits:
        print("WARNING: " + str(WEBVIEW2_DIR) + " has no msedgewebview2.exe — "
              "not a valid runtime folder; skipping the WebView2 bundle.")
        return None
    root = hits[0].parent
    print("Bundling WebView2 Fixed Version runtime from " + str(root))
    return (root, "webview2")


def main():
    template = Path(get_template_path())
    if not template.exists():
        print("ERROR: template ALS not found at " + str(template))
        print("Set ABLETON_TEMPLATE_PATH or fix Config/project_builder.json first.")
        return 1

    work = Path(tempfile.mkdtemp(prefix="stembuild_"))
    bundled_template = work / "template.als"   # bundled name get_template_path looks for
    shutil.copy2(template, bundled_template)

    datas = [
        (APP_DIR / "Web", "Web"),
        (APP_DIR / "VERSION", "."),
        (_baked_feed(work), "."),               # update_feed.json WITH the token baked in
        (bundled_template, "."),
        (REPO_DIR / "Assets" / "AProject.ico", "."),   # Ableton folder icon
        # NB: the machine-specific Config/project_builder.json is NOT bundled —
        # it holds absolute paths; the frozen app resolves template from the
        # bundle and settings/output from %APPDATA% instead.
    ]
    wv2 = _webview2_data()                       # bundle WebView2 runtime if present
    if wv2:
        datas.append(wv2)

    # Build OFF Dropbox: PyInstaller's manifest write (EndUpdateResourceW) fails
    # intermittently when the EXE is created inside a Dropbox-synced folder —
    # Dropbox locks the file mid-write (retries eventually push through, but it's
    # flaky). Build to a local temp dir, then drop the finished EXE into dist/ as
    # a single completed-file copy.
    build_root = Path(tempfile.gettempdir()) / "stemtoableton_build"
    shutil.rmtree(build_root, ignore_errors=True)
    tmp_dist = build_root / "dist"
    args = [
        str(APP_DIR / "app.py"),
        "--name", NAME,
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--distpath", str(tmp_dist),
        "--workpath", str(build_root / "build"),
        "--specpath", str(build_root),
        "--paths", str(SOURCE_DIR),
        "--paths", str(APP_DIR),
    ]
    for src, dest in datas:
        if Path(src).exists():
            args += ["--add-data", str(src) + SEP + dest]
    # Keep the EXE lean: the ML stack is run-as-subprocess only and is force-off
    # in the packaged app, so it never needs bundling.
    for mod in ("torch", "torchaudio", "demucs", "faster_whisper", "whisper",
                "transformers", "scipy", "matplotlib"):
        args += ["--exclude-module", mod]

    print("PyInstaller args:\n  " + " ".join(args) + "\n")
    import PyInstaller.__main__ as pyi
    pyi.run(args)

    built = tmp_dist / (NAME + ".exe")
    final = APP_DIR / "dist" / (NAME + ".exe")
    if built.exists():
        final.parent.mkdir(parents=True, exist_ok=True)
        import time
        for attempt in range(8):          # a completed-file copy; retry a Dropbox lock
            try:
                shutil.copy2(built, final)
                break
            except PermissionError:
                time.sleep(1.0)
        print("\nBuilt: " + str(final))
    else:
        print("\nBuild finished but no EXE at " + str(built) + " — check the log.")
    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(build_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
