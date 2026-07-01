"""'updated stems' and 'ref' subfolders:
  - must NOT trigger a false multi-version build (the Best Tequila bug);
  - updated stems land next to their original, own colour, muted, out of the sum;
  - a 'ref' folder of other artists' tracks becomes Ext-Out A/B reference tracks
    (own colour, left ON) to the right of the arrangement.
"""
import re
import sys
import json
import wave
import struct
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

from versions import detect_versions
from project_builder import (build_project, get_template_path,
                             UPDATED_TRACK_COLOR, REFCOMPARE_COLOR)
from als_patcher import decompress_als, find_track_ranges
from validate_project import validate_path


def _tone(path, f=220, secs=0.4, sr=44100):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(secs * sr)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", int(12000 * ((i * f // sr) % 2 * 2 - 1)))
                               for i in range(n)))


def _make_pack(tmp):
    src = tmp / "Best Tequila [Label] Stems"
    for nm, f in [("01_Kick", 60), ("02_Bass", 90), ("03_Sub Bass", 70),
                  ("04_Sample Bass", 110), ("05_Synth", 440), ("06_Vox", 220)]:
        _tone(src / (nm + ".wav"), f)
    # revised versions of two stems (same element names)
    _tone(src / "updated stems" / "Sub Bass.wav", f=72)
    _tone(src / "updated stems" / "Sample Bass.wav", f=112)
    # other artists' tracks for A/B
    for nm in ("Artist A - Reference.wav", "Artist B - Reference.wav"):
        _tone(src / "ref" / nm, f=200)
    return src


def test_updated_and_ref_folders_are_not_versions():
    tmp = Path(tempfile.mkdtemp(prefix="special_"))
    src = _make_pack(tmp)
    assert detect_versions(src) is None, "updated/ref subfolders wrongly read as versions"


def _track_colors(lines):
    out = []
    for t in find_track_ranges(lines):
        if t["type"] != "AudioTrack":
            continue
        for k in range(t["start"], t["end"] + 1):
            m = re.search(r'<Color Value="(\d+)"', lines[k])
            if m:
                out.append(int(m.group(1))); break
    return out


def test_end_to_end_special_folders():
    if not Path(get_template_path()).exists():
        print("SKIP test_end_to_end_special_folders (template not on this machine)")
        return
    tmp = Path(tempfile.mkdtemp(prefix="special_"))
    src = _make_pack(tmp)
    proj = build_project(src, "Best Tequila", "Best Tequila", "Label", bpm=124,
                         output_base=tmp / "out", use_ml=False,
                         project_name="Best Tequila [Label]")

    # exactly ONE project (not two), and it validates
    als = list(Path(proj).glob("*.als"))
    assert len(als) == 1, "expected a single project, got " + str(len(als))
    assert validate_path(als[0], expected_tempo=124).ok

    lines = decompress_als(als[0])
    colors = _track_colors(lines)
    assert UPDATED_TRACK_COLOR in colors, "no updated-stem track (colour missing)"
    # All refs on ONE 'References' track (colour REFCOMPARE_COLOR), not one each.
    assert colors.count(REFCOMPARE_COLOR) == 1, "refs should be on a single track"
    # A numbered locator on the energetic part of each ref (2 refs -> 2 locators).
    n_locators = sum(1 for ln in lines if "<Locator Id=" in ln)
    assert n_locators == 2, "expected one locator per ref, got " + str(n_locators)

    rep = json.loads((Path(proj) / "Session Report.json").read_text(encoding="utf-8"))
    assert sorted(rep["updated_stems"]) == ["Sample Bass", "Sub Bass"], rep["updated_stems"]
    assert len(rep["refcompare"]) == 2, rep["refcompare"]
    assert rep["multiversion"] is False


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
