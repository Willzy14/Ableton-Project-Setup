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


def test_find_audio_root_keeps_parent_when_multiple_branches():
    # No top-level audio but 2+ audio-bearing subfolders (versions / REF+stems /
    # category splits) -> return the PARENT so downstream code sees all branches,
    # NOT the single richest subfolder (which silently dropped the rest).
    tmp = Path(tempfile.mkdtemp())
    _tone(tmp / "Extended" / "01_Kick.wav"); _tone(tmp / "Extended" / "02_Bass.wav")
    _tone(tmp / "Radio" / "01_Kick.wav")
    assert ea._find_audio_root(tmp) == tmp


def test_find_audio_root_ignores_macosx_and_dotdirs():
    # A macOS zip's __MACOSX/ sibling must not be mistaken for a content branch.
    tmp = Path(tempfile.mkdtemp())
    inner = tmp / "wrapper"
    _tone(inner / "01_Kick.wav"); _tone(inner / "02_Bass.wav")
    (tmp / "__MACOSX").mkdir()
    (tmp / "__MACOSX" / "._01_Kick.wav").write_bytes(b"AppleDouble")
    assert ea._find_audio_root(tmp) == inner            # descends the real wrapper
    assert len(ea._audio_files_in(inner)) == 2          # dotfiles excluded


def test_prepare_single_zip_preserves_subfolders():
    # A single dropped .zip with UPDATE STEMS / REF subfolders must extract with
    # those subfolders INTACT (and no duplicate) so the engine reads one project,
    # not a false second version. (The BESH - Tequila zip bug.)
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))
    from versions import detect_versions

    tmp = Path(tempfile.mkdtemp())
    src = tmp / "src"
    for i in range(6):
        _tone(src / ("%02d_Stem.wav" % i), f=80 + i * 20)
    _tone(src / "UPDATE STEMS" / "Sub Bass.wav", f=70)
    _tone(src / "REF" / "Other Artist.wav", f=200)
    zpath = tmp / "BESH - pack.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for f in src.rglob("*.wav"):
            z.write(f, str(f.relative_to(src)))

    folder = ea.prepare_stem_folder([zpath], tmp / "work")
    subs = sorted(d.name for d in Path(folder).iterdir() if d.is_dir())
    assert subs == ["REF", "UPDATE STEMS"], subs        # subfolders preserved, no _zip_ dupe
    assert len(ea._audio_files_in(folder)) == 6         # 6 top stems, not doubled
    assert detect_versions(folder) is None              # ONE project, not two


def test_build_worker_subprocess_contract():
    # The isolated build worker must run a real build in its own process and
    # print a parseable @@RESULT@@ with folder/als/report — the crash-isolation
    # path the batch runner relies on (a native crash then costs ONE project).
    import subprocess as sp
    import json as _json
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))
    from project_builder import get_template_path
    if not Path(get_template_path()).exists():
        print("SKIP test_build_worker_subprocess_contract (template not on this machine)")
        return
    tmp = Path(tempfile.mkdtemp())
    src = tmp / "pack"
    for nm, f in [("01_Kick", 60), ("02_Bass", 90), ("03_Synth", 440)]:
        _tone(src / (nm + ".wav"), f=f)
    job = {"paths": [str(src)], "title": "Worker - Test [Lab]", "colors": None,
           "subgroups": [], "output_base": str(tmp / "out"), "bpm": 124}
    job_file = tmp / "job.json"
    job_file.write_text(_json.dumps(job), encoding="utf-8")
    worker = Path(__file__).resolve().parents[1] / "Studio App" / "build_worker.py"
    cp = sp.run([sys.executable, str(worker), str(job_file)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=300)
    marker = [l for l in cp.stdout.splitlines() if l.startswith("@@RESULT@@")]
    assert marker, "no @@RESULT@@ line; rc=" + str(cp.returncode) + " out=" + cp.stdout[-400:]
    res = _json.loads(marker[-1][len("@@RESULT@@"):])
    assert res["ok"] is True, res
    assert res["validated"] is True, res
    assert res["report"] and res["report"]["bpm"] == 124.0
    assert Path(res["als"]).exists()


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
