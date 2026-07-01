"""Multi-version parity: the name-token version path (Get Right S16/S17) must
also get nested sub-groups on its shared tracks AND wire in a pre-seeded master
— the two things the single-version path already did.

End-to-end; skipped when the Ableton template isn't present on this machine.
"""
import re
import sys
import wave
import struct
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

import als_patcher
from als_patcher import decompress_als
from project_builder import build_project, get_template_path, REF_TRACK_COLOR
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


def _group_tracks(lines):
    groups = []
    for i, ln in enumerate(lines):
        m = re.search(r'<GroupTrack Id="(\d+)"', ln)
        if not m:
            continue
        gid, tgid, name = m.group(1), None, None
        for j in range(i + 1, min(i + 40, len(lines))):
            if tgid is None:
                mt = re.search(r'<TrackGroupId Value="(-?\d+)"', lines[j])
                if mt:
                    tgid = mt.group(1)
            if name is None:
                mn = re.search(r'<EffectiveName Value="([^"]*)"', lines[j])
                if mn:
                    name = mn.group(1)
            if tgid is not None and name is not None:
                break
        groups.append((gid, tgid, name))
    return groups


def _ref_track_names(lines):
    out = []
    for t in als_patcher.find_track_ranges(lines):
        if t["type"] != "AudioTrack":
            continue
        color = None
        for k in range(t["start"], t["end"] + 1):
            mc = re.search(r'<Color Value="(\d+)"', lines[k])
            if mc:
                color = int(mc.group(1)); break
        if color == REF_TRACK_COLOR:
            out.append(t["name"])
    return out


def test_nametoken_multiversion_subgroups_and_preseeded_ref():
    if not Path(get_template_path()).exists():
        print("SKIP test_nametoken_multiversion_parity (template not on this machine)")
        return
    tmp = Path(tempfile.mkdtemp(prefix="mvparity_"))
    src = tmp / "pack"
    # One FLAT folder, two versions by name token (S16 = full, S17 = short edit),
    # each with a 2-singer vocal set so vocals nest into singer sub-groups.
    for tok in ("S16", "S17 SHRT EDIT"):
        _tone(src / f"01_Kick {tok}.wav", f=60)
        _tone(src / f"02_Bass {tok}.wav", f=90)
        _tone(src / f"03_Lauren Lead Vox {tok}.wav", f=220)
        _tone(src / f"04_Lauren BGV Vox {tok}.wav", f=260)
        _tone(src / f"05_Sarah Lead Vox {tok}.wav", f=330)
        _tone(src / f"06_Sarah BGV Vox {tok}.wav", f=390)

    out = tmp / "out"
    # Pre-seed a master into the target project's Audio/ before the build.
    proj_folder = out / "Test - Grip [Lab] Project"
    _tone(proj_folder / "Audio" / "Test - Grip (V4) Master.wav", f=200)

    proj = build_project(src, "Test", "Grip", "Lab", bpm=124,
                         output_base=out, use_ml=False)
    als = next(Path(proj).glob("*.als"))

    result = validate_path(als, expected_tempo=124)
    assert result.ok, "validate errors: " + "; ".join(result.errors)

    lines = decompress_als(als)
    by_name = {name: (gid, tgid) for gid, tgid, name in _group_tracks(lines)}

    # Item 3b: nested sub-groups on the shared tracks (Vox -> Lauren/Sarah).
    assert "Vox" in by_name, "no Vox parent group; groups=" + str(list(by_name))
    vox_id = by_name["Vox"][0]
    assert by_name["Vox"][1] == "-1", "Vox should be top-level"
    assert "Lauren" in by_name and "Sarah" in by_name, "singer sub-groups missing"
    assert by_name["Lauren"][1] == vox_id and by_name["Sarah"][1] == vox_id, \
        "singer sub-groups not nested under Vox"

    # Item 3a: the pre-seeded master is wired in as a red reference track.
    refs = _ref_track_names(lines)
    assert any("V4" in n and "Master" in n for n in refs), \
        "pre-seeded master not wired as red ref; refs=" + str(refs)


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
