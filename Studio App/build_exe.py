"""Build the Studio App into a single self-contained Windows EXE (ML-off).

    py -3.13 "Studio App/build_exe.py"

Produces Studio App/dist/StemToAbleton.exe. The EXE bundles the engine
(Source/*.py), the Web UI, the VERSION + update_feed.json, and the Ableton
template ALS, so it runs on a studio machine with no Python, no Dropbox, and no
template in the User Library. The heavy ML stack (torch/demucs/whisper) is
EXCLUDED — filename + audio classification still works; ML-only naming of
totally generic stems is the single thing the EXE gives up, by design (it would
balloon the download to multiple GB). After building, run publish_release.py to
produce latest.json for the public releases feed.
"""
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
        (APP_DIR / "update_feed.json", "."),
        (bundled_template, "."),
        (REPO_DIR / "Config" / "project_builder.json", "Config"),
    ]

    args = [
        str(APP_DIR / "app.py"),
        "--name", NAME,
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--distpath", str(APP_DIR / "dist"),
        "--workpath", str(APP_DIR / "build"),
        "--specpath", str(APP_DIR),
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

    out = APP_DIR / "dist" / (NAME + ".exe")
    print("\nBuilt: " + str(out) if out.exists() else "\nBuild finished (check dist/).")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
