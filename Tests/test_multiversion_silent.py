"""M1 stage 3: an element silent in EVERY version of a multi-version pack is parked
at the bottom (own colour), matching the single-version path. An element with audio
in at least one version stays a working track.
"""
import sys
import json
import math
import wave
import struct
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Source"))
import project_builder as pb
from project_builder import build_project, session_report_path

SR = 44100


def _wav(path, samples):
    with wave.open(str(path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(s)) for s in samples))


def _tone(secs=6.0, freq=110.0, amp=12000):
    n = int(secs * SR)
    return [amp * math.sin(2 * math.pi * freq * i / SR) for i in range(n)]


def _silent(secs=6.0):
    return [0] * int(secs * SR)


def _version(folder, dead_name):
    folder.mkdir(parents=True, exist_ok=True)
    _wav(folder / "01_Kick.wav", _tone(freq=60))
    _wav(folder / "02_Bass.wav", _tone(freq=90))
    _wav(folder / "03_Synth.wav", _tone(freq=220))
    _wav(folder / (dead_name + ".wav"), _silent())    # dead export, silent in both


def test_element_silent_in_all_versions_is_parked():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "pack"
        _version(src / "Extended", "04_DeadFX")
        _version(src / "Radio Edit", "04_DeadFX")
        out = tmp / "out"
        proj = Path(build_project(str(src), "Test", "Silent", "Lab",
                                  bpm=120, output_base=str(out), use_ml=False))

        report = json.loads(session_report_path(proj).read_text(encoding="utf-8"))
        assert report.get("multiversion") is True, report.get("multiversion")
        silent = report.get("silent", [])
        # the dead element (silent in BOTH versions) is parked...
        assert any("DeadFX" in s for s in silent), "dead element not parked: " + str(silent)
        # ...and the audible ones are NOT parked
        assert not any("Kick" in s or "Bass" in s or "Synth" in s for s in silent), silent


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except Exception:  # noqa: BLE001
            failed += 1
            print("FAIL", fn.__name__)
            traceback.print_exc()
    print(("ALL PASS" if not failed else str(failed) + " FAILED"))
    sys.exit(1 if failed else 0)
