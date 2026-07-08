"""M1 stage 4: the DRY half of a wet/dry vocal pair in a multi-version pack is
parked in a muted "Dry" group (like the single path), the WET stays a working
track, and the same dry element pairs across versions onto ONE dry track (not one
per version) — despite element_key keying every '_DRY' to 'dry'.
"""
import sys
import json
import math
import wave
import struct
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Source"))
from project_builder import build_project, session_report_path
from als_patcher import decompress_als

SR = 44100


def _wav(path, freq=110.0, secs=6.0, amp=12000):
    n = int(secs * SR)
    s = [amp * math.sin(2 * math.pi * freq * i / SR) for i in range(n)]
    with wave.open(str(path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(x)) for x in s))


def _version(folder):
    folder.mkdir(parents=True, exist_ok=True)
    _wav(folder / "01_Kick.wav", 60)
    _wav(folder / "02_Bass.wav", 90)
    _wav(folder / "03_Lead Vox WET.wav", 300)
    _wav(folder / "04_Lead Vox DRY.wav", 300)   # the dry half of the pair


def test_multiversion_wetdry_parks_dry_once_and_groups_it():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "pack"
        _version(src / "Extended")
        _version(src / "Radio Edit")
        proj = Path(build_project(str(src), "Test", "WetDry", "Lab",
                                  bpm=120, output_base=str(tmp / "out"), use_ml=False))

        report = json.loads(session_report_path(proj).read_text(encoding="utf-8"))
        assert report.get("multiversion") is True
        dry = report.get("dry_parked", [])
        # exactly ONE dry track (the Lead Vox dry, paired across both versions)...
        assert len(dry) == 1, "expected 1 paired dry track, got: " + str(dry)
        assert any("DRY" in d.upper() for d in dry), dry
        # ...and there IS a muted "Dry" group in the .als
        lines = decompress_als(next(proj.glob("*.als")))
        blob = "".join(lines)
        assert "Dry" in blob, "no Dry group in the project"


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
