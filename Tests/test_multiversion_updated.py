"""M1 stage 5: an updated/revised stem in a multi-version pack is MATCHED to the
working track it replaces (by _match_key) and placed next to it, inheriting its
category — not dumped as a generic 'music' track at the bottom and flagged as
unmatched (the old multi behaviour).
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
    _wav(folder / "03_Synth.wav", 220)


def test_multiversion_updated_stem_matches_original():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "pack"
        _version(src / "Extended")
        _version(src / "Radio Edit")
        upd = src / "UPDATE STEMS"
        upd.mkdir(parents=True)
        _wav(upd / "01_Kick.wav", 62)     # a revised kick, same element name

        proj = Path(build_project(str(src), "Test", "Updated", "Lab",
                                  bpm=120, output_base=str(tmp / "out"), use_ml=False))
        report = json.loads(session_report_path(proj).read_text(encoding="utf-8"))
        assert report.get("multiversion") is True

        # the updated kick is present...
        assert any("Kick" in u for u in report.get("updated_stems", [])), \
            report.get("updated_stems")
        # ...and MATCHED, so NO "no matching original" flag fires
        flags = report.get("flags", [])
        assert not any("no matching original" in f for f in flags), \
            "matched updated stem was wrongly flagged as unmatched: " + str(flags)


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
