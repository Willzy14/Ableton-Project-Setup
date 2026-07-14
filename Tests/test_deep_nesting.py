"""A4 — deep-nesting / format-wrapper support.

Before this: classify_stems and detect_versions both scanned only ONE subfolder
level, so a pack that nested stems under a format wrapper (Drums/24bit WAV/Kick.wav
or Extended/WAV/... + Radio/WAV/...) built a COMPLETELY EMPTY project with no flag,
and partial nesting silently dropped the deep stems. Now both recurse to any depth,
special-dir branches are excluded from version scans, copies are collision-safe, a
coverage backstop catches anything unplaced, and a pack with audio but zero working
stems fails loudly instead of building empty.
"""
import sys
import math
import wave
import json
import struct
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Source"))

from stem_classifier import classify_stems
from versions import detect_versions, _audio_under, _audio_here
from project_builder import (build_project, session_report_path,
                             _copy_stem_dest, _all_source_audio, _place_stem_file)
from validate_project import validate_path

SR = 44100


def _wav(path, freq=110.0, secs=4.0, amp=12000):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(secs * SR)
    s = (amp * math.sin(2 * math.pi * freq * i / SR) for i in range(n))
    with wave.open(str(path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(x)) for x in s))


def _touch(root, rels):
    for rp in rels:
        p = Path(root) / rp
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"RIFF")
    return Path(root)


# --- classification / detection (name-only, fast) -------------------------

def _placed(root):
    classified, refs, unc = classify_stems(root)
    return sum(len(v) for v in classified.values()) + len(refs) + len(unc)


def test_format_wrapper_single_classifies_all():
    root = _touch(tempfile.mkdtemp(), [
        "Drums/24bit WAV/Kick.wav", "Drums/24bit WAV/Snare.wav",
        "Bass/24bit WAV/Bass.wav", "Music/24bit WAV/Lead.wav"])
    assert _placed(root) == 4                      # was 0 (empty build)
    assert detect_versions(root) is None           # a single version, not multi


def test_partial_nesting_drops_nothing():
    root = _touch(tempfile.mkdtemp(), [
        "Kick.wav", "Drums/Snare.wav", "Drums/Perc/Shaker.wav", "Drums/Perc/Tamb.wav"])
    assert _placed(root) == 4                       # was 2


def test_versions_behind_format_wrapper():
    root = _touch(tempfile.mkdtemp(), [
        "Extended/WAV/Kick.wav", "Extended/WAV/Snare.wav", "Extended/WAV/Bass.wav",
        "Radio/WAV/Kick.wav", "Radio/WAV/Snare.wav", "Radio/WAV/Bass.wav"])
    v = detect_versions(root)
    assert v is not None and len(v) == 2, v         # was None -> empty build
    assert "Extended" in v[0]["name"]


def test_nested_ref_not_a_version_member():
    # A REF/ nested deep must NOT count as a stem/version member (Codex #1):
    # _audio_under excludes special branches; detect stays single-version.
    root = _touch(tempfile.mkdtemp(), [
        "Drums/WAV/Kick.wav", "Drums/WAV/Snare.wav", "Bass/WAV/Bass.wav",
        "Extras/REF/OtherArtist Master.wav"])
    under = _audio_under(root)
    assert not any("REF" in p.parts for p in under), [str(p) for p in under]
    assert detect_versions(root) is None


def test_user_named_folders_not_silently_dropped():
    # A producer folder that happens to be named like the tool's own output
    # (Backup/Reports) must NOT be silently skipped — surfacing beats dropping
    # (MiniMax #1). The manifest and classify agree, so the coverage backstop
    # never has to fire, but nothing vanishes.
    root = _touch(tempfile.mkdtemp(), [
        "Kick.wav", "Snare.wav", "Bass.wav",
        "Reports/extra_a.wav", "Backup/extra_b.wav"])
    assert _placed(root) == 5
    assert len(_all_source_audio(root)) == 5


def test_macosx_and_dotfiles_still_skipped():
    root = _touch(tempfile.mkdtemp(), [
        "Kick.wav", "Snare.wav",
        "__MACOSX/._Kick.wav", ".hidden/junk.wav", "._Snare.wav"])
    assert _placed(root) == 2                        # only the two real stems
    assert len(_all_source_audio(root)) == 2


def test_appledouble_not_counted_in_versions():
    # macOS AppleDouble sidecars must not inflate version file counts / _pick_base
    # (MiniMax #4). Each version has 2 REAL stems despite the ._ twins.
    root = _touch(tempfile.mkdtemp(), [
        "Extended/Kick.wav", "Extended/._Kick.wav", "Extended/Snare.wav",
        "Radio/Kick.wav", "Radio/._Kick.wav", "Radio/Snare.wav"])
    v = detect_versions(root)
    assert v is not None and len(v) == 2, v
    assert all(len(ver["files"]) == 2 for ver in v), [len(x["files"]) for x in v]


def test_flat_and_one_level_unchanged():
    flat = _touch(tempfile.mkdtemp(), ["Kick.wav", "Snare.wav", "Bass.wav", "Lead.wav"])
    one = _touch(tempfile.mkdtemp(), [
        "Drums/Kick.wav", "Drums/Snare.wav", "Bass/Bass.wav", "Music/Lead.wav"])
    assert _placed(flat) == 4 and _placed(one) == 4
    assert detect_versions(flat) is None and detect_versions(one) is None
    # _audio_here stays shallow: only the direct file for the one-level pack root.
    assert _audio_here(one) == []


# --- collision-safe copy --------------------------------------------------

def test_collision_safe_dest_disambiguates_different_sources():
    a = _touch(tempfile.mkdtemp(), ["Drums/WAV/Loop.wav", "Perc/WAV/Loop.wav"])
    f1 = a / "Drums" / "WAV" / "Loop.wav"
    f2 = a / "Perc" / "WAV" / "Loop.wav"
    audio = Path(tempfile.mkdtemp())
    used = {}
    d1 = _copy_stem_dest(f1, audio, used)
    d2 = _copy_stem_dest(f2, audio, used)
    assert d1.name == "Loop.wav"
    assert d2.name != d1.name, (d1.name, d2.name)   # no silent overwrite
    # same source again -> same dest (rebuild into an existing folder)
    assert _copy_stem_dest(f1, audio, used).name == "Loop.wav"


def test_place_stem_file_recopies_truncated():
    # A partial/truncated dest left by a crashed build must be RE-COPIED, not
    # trusted (Codex pre-package review: the validator only checks a path exists).
    src_dir = Path(tempfile.mkdtemp())
    src = src_dir / "Kick.wav"
    src.write_bytes(b"RIFFfull-content-here-1234567890")
    audio = Path(tempfile.mkdtemp())
    (audio / "Kick.wav").write_bytes(b"RIFFtrunc")     # partial from a dead build
    dest = _place_stem_file(src, audio, {})
    assert dest.read_bytes() == src.read_bytes(), "truncated dest was not re-copied"


def test_place_stem_file_in_place():
    # A file already sitting in the Audio folder (a pre-seeded ref) is used in
    # place, never copied onto itself.
    audio = Path(tempfile.mkdtemp())
    f = audio / "Master.wav"
    f.write_bytes(b"RIFFmaster")
    dest = _place_stem_file(f, audio, {})
    assert dest == f and dest.read_bytes() == b"RIFFmaster"


def test_collision_many_same_basename_all_distinct():
    # Many different sources sharing one basename must all get distinct dests
    # (unbounded counter — never silently overwrites, never hangs). MiniMax #3.
    root = Path(tempfile.mkdtemp())
    srcs = []
    for i in range(60):
        p = root / f"g{i}" / "WAV" / "Loop.wav"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"RIFF")
        srcs.append(p)
    audio = Path(tempfile.mkdtemp())
    used = {}
    names = [_copy_stem_dest(s, audio, used).name for s in srcs]
    assert len(set(n.lower() for n in names)) == 60, "collision produced a duplicate dest"


# --- end-to-end build + hard guard ---------------------------------------

def test_format_wrapper_builds_and_validates():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "Pack"
        _wav(src / "Drums" / "24bit WAV" / "01_Kick.wav", 60)
        _wav(src / "Drums" / "24bit WAV" / "02_Snare.wav", 200)
        _wav(src / "Bass" / "24bit WAV" / "03_Bass.wav", 90)
        _wav(src / "Music" / "24bit WAV" / "04_Synth.wav", 300)
        proj = Path(build_project(str(src), "Nest", "Wrapped", "Lab",
                                  bpm=124, output_base=str(tmp / "out"), use_ml=False))
        report = json.loads(session_report_path(proj).read_text(encoding="utf-8"))
        # every deep stem placed as a working track, none dropped/parked
        cats = report.get("categories", {})
        assert sum(cats.values()) >= 4, report
        assert not any("nested unexpectedly" in f for f in report.get("flags", [])), \
            report.get("flags")
        assert validate_path(proj).ok


def test_audio_but_no_working_stems_raises():
    # Only reference/master files -> zero working stems -> loud error, not a
    # silent empty build.
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "OnlyMasters"
        _wav(src / "Track Master.wav", 100)
        _wav(src / "Rough Mix.wav", 100)
        raised = False
        try:
            build_project(str(src), "X", "Y", "Z", bpm=120,
                          output_base=str(tmp / "out"), use_ml=False)
        except ValueError as e:
            raised = "couldn't place" in str(e) or "working stems" in str(e)
        assert raised, "expected a hard-guard ValueError for a stemless pack"


def test_all_stems_inside_ref_folder_raises():
    # Every stem lives in a REF/ folder -> all parked as refs, zero working
    # stems -> loud hard-guard error, not a silent near-empty build (MiniMax #2).
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "RefOnly"
        _wav(src / "REF" / "Kick.wav", 60)
        _wav(src / "REF" / "Snare.wav", 200)
        _wav(src / "REF" / "Bass.wav", 90)
        raised = False
        try:
            build_project(str(src), "X", "Y", "Z", bpm=120,
                          output_base=str(tmp / "out"), use_ml=False)
        except ValueError as e:
            raised = "working stems" in str(e)
        assert raised, "expected a hard-guard ValueError when all audio is in REF/"


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
