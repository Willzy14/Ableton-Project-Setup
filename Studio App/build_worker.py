"""Isolated build worker — runs ONE project build in its own process.

Why: the Studio App used to build in a thread inside the GUI process, so a
native crash (access violation in numpy/BLAS, a Dropbox filter-driver blip
mid-read — seen intermittently in battle testing) would kill the whole app and
the rest of the batch. Run each build here instead: a crash costs one project,
the batch survives, and the parent captures the log for the failed card.

Contract: invoked as `python build_worker.py <job.json>` (or, packaged,
`StudioApp.exe --build-worker <job.json>`). Prints progress lines to stdout as
the engine works, then a final `@@RESULT@@{json}` line the parent parses.
"""
import json
import sys
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


def run_job(job):
    """job: {paths, title, colors, subgroups, output_base, bpm}. Returns dict."""
    sys.path.insert(0, str(APP_DIR))
    import engine_api as E
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="studioapp_"))
    try:
        print("Preparing stems...", flush=True)
        stem_folder = E.prepare_stem_folder(job["paths"], tmp / "stems")
        artist, ttl, label = E.parse_project_name(job["title"])
        from project_builder import build_project, session_report_path
        from validate_project import validate_path

        folder = build_project(
            str(stem_folder), artist, ttl, label,
            bpm=job.get("bpm") or None,
            output_base=job["output_base"],
            project_name=job["title"],
            category_colors=job.get("colors") or None,
            subgroup_categories=job.get("subgroups"),
            use_ml=False,   # decided model: the Studio App always runs ML off
        )
        folder = Path(folder)
        print("Validating...", flush=True)
        als = next(folder.glob("*.als"), None)
        v = validate_path(als) if als else None
        report = None
        rp = session_report_path(folder)
        if rp.exists():
            try:
                report = json.loads(rp.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — a bad report must not fail the build
                report = None
        return {
            "ok": True,
            "folder": str(folder),
            "als": str(als) if als else "",
            "validated": bool(v and v.ok),
            "report": report,
        }
    except Exception as exc:  # noqa: BLE001 — one bad pack must not kill the batch
        return {"ok": False, "error": str(exc), "trace": traceback.format_exc()}
    finally:
        import shutil
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Accept both `build_worker.py <job>` and `EXE --build-worker <job>` forms.
    args = [a for a in argv if a != "--build-worker"]
    if not args:
        print("@@RESULT@@" + json.dumps({"ok": False, "error": "no job file"}))
        return 2
    try:
        job = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print("@@RESULT@@" + json.dumps({"ok": False, "error": "bad job file: " + str(exc)}))
        return 2
    res = run_job(job)
    print("@@RESULT@@" + json.dumps(res), flush=True)
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
