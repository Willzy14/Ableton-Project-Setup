"""The build writes a Session Report.json (the Studio App's Result Card reads it)
and the engine_api title-guesser normalises a dropped folder name.
"""
import sys
import json
import wave
import struct
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Source"))
sys.path.insert(0, str(ROOT / "Studio App"))

from project_builder import build_project, get_template_path
import engine_api


def _tone(path, f=220, secs=0.4, sr=44100):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(secs * sr)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", int(12000 * ((i * f // sr) % 2 * 2 - 1)))
                               for i in range(n)))


# --- title guesser (pure) --------------------------------------------------

def test_title_from_zip_strips_noise():
    t = engine_api._title_from_paths(["C:/x/Vlad - Nightfall [Defected] MULTITRACKS.zip"])
    assert t == "Vlad - Nightfall [Defected]", t


def test_title_from_folder_keeps_grammar():
    t = engine_api._title_from_paths(["C:/x/Replicage - Amen [Sound Better] Stems"])
    assert t == "Replicage - Amen [Sound Better]", t


def test_title_empty_when_no_paths():
    assert engine_api._title_from_paths([]) == ""


# --- report is written -----------------------------------------------------

def test_build_writes_session_report():
    if not Path(get_template_path()).exists():
        print("SKIP test_build_writes_session_report (template not on this machine)")
        return
    tmp = Path(tempfile.mkdtemp(prefix="report_"))
    src = tmp / "pack"
    _tone(src / "01_Kick.wav", f=60)
    _tone(src / "02_Bass.wav", f=90)
    _tone(src / "03_Synth.wav", f=440)
    _tone(src / "04_Pad.wav", f=300)
    proj = build_project(src, "Test", "Report", "Lab", bpm=124,
                         output_base=tmp / "out", use_ml=False)
    rep_path = Path(proj) / "Session Report.json"
    assert rep_path.exists(), "Session Report.json not written"
    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    for key in ("bpm", "tracks_total", "categories", "groups", "flat_ref_peak",
                "als_name", "references_supplied"):
        assert key in rep, "missing report key: " + key
    assert rep["bpm"] == 124.0
    assert rep["categories"].get("music") == 2      # Synth + Pad
    assert rep["tracks_total"] >= 4
    # A human-readable copy is written too.
    assert (Path(proj) / "Session Report.txt").exists()


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print("PASS", fn.__name__)
        except Exception:  # noqa: BLE001
            failed += 1
            print("FAIL", fn.__name__)
            traceback.print_exc()
    print("ALL PASS" if not failed else str(failed) + " FAILED")
    sys.exit(1 if failed else 0)
