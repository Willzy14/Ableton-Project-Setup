"""Regression tests for the 2026-07 audit quick-win batch.

Covers: atomic/lock-safe .als write, unreadable stems surfaced in the report/
flags (not silently dropped), and the cross-platform validator path join.
"""
import sys
import gzip
import wave
import struct
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

import als_patcher
import project_builder as pb
import validate_project


def test_compress_als_roundtrip_and_no_temp_left():
    """compress_als writes atomically (temp + rename) and round-trips clean."""
    lines = ['<?xml version="1.0"?>\n', "<Ableton>\n", "  <x/>\n", "</Ableton>\n"]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "Proj.als"
        als_patcher.compress_als(lines, out)
        assert out.exists()
        assert als_patcher.decompress_als(out) == lines          # round-trips
        assert not (out.with_name(out.name + ".tmp")).exists()   # no stray temp
        # Overwriting (a rebuild) still works and stays valid.
        als_patcher.compress_als(lines, out)
        assert als_patcher.decompress_als(out) == lines


def test_unreadable_stem_is_surfaced_not_dropped():
    """A corrupt WAV is skipped AND reported — never silently absent."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        good = tmp / "Kick.wav"
        with wave.open(str(good), "w") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
            w.writeframes(struct.pack("<" + "h" * 100, *([0] * 100)))
        bad = tmp / "Broken.wav"
        bad.write_bytes(b"RIFF\x00\x00\x00\x00WAVEjunk")   # not a real WAV
        classified = {"drums": [good, bad]}
        staging = tmp / "stg"
        classified, refs, unc, skipped = pb._normalize_audio_to_wav(
            classified, [], [], staging)
        assert good in classified["drums"]
        assert bad not in classified.get("drums", [])
        assert any("Broken" in s for s in skipped), skipped     # surfaced
        # and it reaches the "needs a look" flags
        flags = pb._collect_flags([], skipped, [])
        assert any("Broken" in f for f in flags), flags


def test_validator_resolves_posix_relative_cross_platform():
    """RelativePath (stored with '/') resolves by parts, not a literal backslash."""
    fr = ET.fromstring(
        '<FileRef><RelativePath Value="Audio/Kick.wav"/></FileRef>')
    resolved = validate_project._resolve_file_ref(Path("/proj"), fr)
    # The path must end with the Audio + Kick.wav components, on any OS.
    assert resolved.parts[-2:] == ("Audio", "Kick.wav"), resolved


def test_validate_als_flags_never_raises():
    """The inline validator always returns a list — never propagates an exception."""
    assert isinstance(pb._validate_als_flags(Path("nope.als"), 128.0), list)
    with tempfile.TemporaryDirectory() as tmp:
        junk = Path(tmp) / "junk.als"
        junk.write_bytes(b"not gzip, not xml")
        assert isinstance(pb._validate_als_flags(junk, 128.0), list)


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
