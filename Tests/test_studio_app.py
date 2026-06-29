"""Studio App backend logic — title parse, profiles IO, ingest, palette."""
import sys
import wave
import struct
import math
import zipfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Studio App"))

import engine_api as ea  # noqa: E402


def _tone(p, secs=0.5, f=220.0, sr=44100):
    p.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(p), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(b"".join(
            struct.pack("<h", int(6000 * math.sin(2 * math.pi * f * n / sr)))
            for n in range(int(sr * secs))))


def test_parse_project_name():
    assert ea.parse_project_name("Replicage - Amen [Sound Better]") == \
        ("Replicage", "Amen", "Sound Better")
    assert ea.parse_project_name("Just A Title") == ("", "Just A Title", "")
    assert ea.parse_project_name("Artist - Title") == ("Artist", "Title", "")
    a, t, l = ea.parse_project_name("A - B - C [Label]")
    assert a == "A" and t == "B - C" and l == "Label"


def test_palette_is_70():
    assert len(ea.ABLETON_PALETTE) == 70


def test_default_profile_has_all_categories():
    prof = ea.default_profile("X")
    for c in ea.COLOR_CATEGORIES:
        assert c in prof["colors"]


def test_profiles_roundtrip(tmp_path=None):
    tmp = Path(tempfile.mkdtemp())
    ea.PROFILES_PATH = tmp / "profiles.json"
    ea.SETTINGS_PATH = tmp / "settings.json"
    profs = ea.load_profiles()                      # creates default
    assert profs and profs[0]["name"] == "Default"
    profs.append(ea.default_profile("Partner A"))
    ea.save_profiles(profs)
    again = ea.load_profiles()
    assert [p["name"] for p in again] == ["Default", "Partner A"]


def test_find_audio_root_through_wrapper():
    tmp = Path(tempfile.mkdtemp())
    inner = tmp / "wrapper" / "stems"
    _tone(inner / "01_Kick.wav")
    _tone(inner / "02_Bass.wav")
    root = ea._find_audio_root(tmp)
    assert root == inner
    assert len(ea._audio_files_in(root)) == 2


def test_prepare_from_zip_and_loose():
    tmp = Path(tempfile.mkdtemp())
    # a zip of two wavs
    src = tmp / "src"; _tone(src / "01_Kick.wav"); _tone(src / "02_Snare.wav", f=300)
    zpath = tmp / "pack.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for f in src.iterdir():
            z.write(f, f.name)
    # a loose wav
    loose = tmp / "loose"; _tone(loose / "03_Hat.wav", f=900)

    work = tmp / "work"
    folder = ea.prepare_stem_folder([zpath, loose / "03_Hat.wav"], work)
    wavs = sorted(p.name for p in ea._audio_files_in(folder))
    assert wavs == ["01_Kick.wav", "02_Snare.wav", "03_Hat.wav"]


def test_prepare_single_clean_folder_used_in_place():
    tmp = Path(tempfile.mkdtemp())
    stems = tmp / "MyPack"; _tone(stems / "01_Kick.wav"); _tone(stems / "02_Bass.wav")
    folder = ea.prepare_stem_folder([stems], tmp / "work")
    assert folder == stems   # no needless staging copy when it's already clean WAVs


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print("PASS", fn.__name__)
        except Exception:  # noqa: BLE001
            failed += 1; print("FAIL", fn.__name__); traceback.print_exc()
    print("ALL PASS" if not failed else str(failed) + " FAILED")
    sys.exit(1 if failed else 0)
