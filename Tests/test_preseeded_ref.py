"""A master the user pre-seeds into the TARGET project folder (to A/B against)
must be wired in as a red reference match track, not left orphaned.

Logic tests are pure. The end-to-end test builds a real project and inspects the
ALS; it is skipped when the Ableton template isn't present on this machine.
"""
import re
import sys
import wave
import struct
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

import project_builder
from project_builder import (build_project, get_template_path,
                             _find_preseeded_audio, REF_TRACK_COLOR)
from als_patcher import decompress_als
from validate_project import validate_path


def _tone(path, secs=0.4, f=220, sr=44100):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(secs * sr)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            v = int(12000 * ((i * f // sr) % 2 * 2 - 1))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


# --- discovery logic (no template needed) ----------------------------------

def test_find_preseeded_scans_audio_and_root_dedup():
    tmp = Path(tempfile.mkdtemp(prefix="preseed_"))
    proj = tmp / "Proj"
    audio = proj / "Audio"
    _tone(audio / "My Master.wav")
    _tone(proj / "root_ref.wav")
    (proj / "notes.txt").write_text("not audio")
    found = {f.name for f in _find_preseeded_audio(proj, audio)}
    assert found == {"My Master.wav", "root_ref.wav"}


def test_find_preseeded_empty_when_nothing_there():
    tmp = Path(tempfile.mkdtemp(prefix="preseed_"))
    proj = tmp / "Proj"       # doesn't exist yet
    assert _find_preseeded_audio(proj, proj / "Audio") == []


# --- end-to-end: pre-seeded master becomes a red ref track -----------------

def _ref_track_names(lines):
    """EffectiveNames of tracks coloured with REF_TRACK_COLOR."""
    names, ranges = [], []
    import als_patcher
    for t in als_patcher.find_track_ranges(lines):
        if t["type"] != "AudioTrack":
            continue
        color = None
        name = t["name"]
        for k in range(t["start"], t["end"] + 1):
            mc = re.search(r'<Color Value="(\d+)"', lines[k])
            if mc:
                color = int(mc.group(1))
                break
        ranges.append((name, color))
    return [n for n, c in ranges if c == REF_TRACK_COLOR]


def test_end_to_end_preseeded_master_wired_as_ref():
    if not Path(get_template_path()).exists():
        print("SKIP test_end_to_end_preseeded_master (template not on this machine)")
        return
    tmp = Path(tempfile.mkdtemp(prefix="preseed_"))
    src = tmp / "pack"
    _tone(src / "01_Kick.wav", f=60)
    _tone(src / "02_Bass.wav", f=90)
    _tone(src / "03_Synth.wav", f=440)

    out = tmp / "out"
    # Pre-seed the master into the target project's Audio/ BEFORE the build.
    proj_folder = out / "Test - Amen [Lab] Project"
    _tone(proj_folder / "Audio" / "Test - Amen (V9) Master.wav", f=200)

    proj = build_project(src, "Test", "Amen", "Lab", bpm=124,
                         output_base=out, use_ml=False)
    als = next(Path(proj).glob("*.als"))

    result = validate_path(als, expected_tempo=124)
    assert result.ok, "validate errors: " + "; ".join(result.errors)

    lines = decompress_als(als)
    refs = _ref_track_names(lines)
    assert any("V9" in n and "Master" in n for n in refs), \
        "pre-seeded master not wired as a red reference; refs=" + str(refs)
    assert "FLAT REF" in refs, "flat bounce missing"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except Exception:  # noqa: BLE001
            failed += 1
            print("FAIL", fn.__name__)
            traceback.print_exc()
    print("ALL PASS" if not failed else str(failed) + " FAILED")
    sys.exit(1 if failed else 0)
