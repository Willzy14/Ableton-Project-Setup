"""A filename-labelled BPM is a HINT, never trusted outright — it must be
grid-checked against the actual audio, which is the arbiter.

Real case (Sam, Cole Horton): a pack tagged "130BPM" was really 132. The old
code took the label verbatim and never ran the detector, so 130 shipped. Now:
  - audio confirms the label      -> use it, no flag
  - audio disagrees with the label -> use the AUDIO tempo + a loud conflict flag
  - nothing locks to check against -> keep the label but flag it unverified
"""
import sys
import math
import wave
import struct
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

import project_builder as pb
import als_patcher
from project_builder import (
    _resolve_project_bpm, _octave_align, _fmt_bpm, _bpm_from_filenames,
)

SR = 44100


def _write_int16(path, samples):
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(s)) for s in samples))


def _kick_train(bpm, n_beats=40):
    """A clean 60 Hz kick on every beat at the given tempo — locks tightly."""
    period = 60.0 / bpm
    total = int((n_beats + 1) * period * SR)
    s = [0] * total
    decay = 0.012 * SR
    for b in range(n_beats):
        start = int(b * period * SR)
        for k in range(int(0.06 * SR)):
            i = start + k
            if i < total:
                env = math.exp(-k / decay)
                s[i] = int(28000 * env * math.sin(2 * math.pi * 60 * k / SR))
    return s


def _make_kick(tmp, name, bpm):
    p = Path(tmp) / name
    _write_int16(p, _kick_train(bpm))
    return p


# --- pure helpers ----------------------------------------------------------

def test_octave_align_folds_to_nearest_octave():
    assert _octave_align(66.0, 130) == 132.0     # half-time -> ×2
    assert _octave_align(264.0, 130) == 132.0    # double-time -> ÷2
    assert _octave_align(132.0, 130) == 132.0    # already aligned
    assert _octave_align(120.0, 120) == 120.0


def test_fmt_bpm():
    assert _fmt_bpm(132.0) == "132"
    assert _fmt_bpm(128.5) == "128.5"


# --- reconciliation branches (real audio) ----------------------------------

def test_conflict_audio_overrides_wrong_label():
    """The Horton case: file says 130, the audio grid-locks to 132."""
    with tempfile.TemporaryDirectory() as tmp:
        kick = _make_kick(tmp, "Horton 130BPM Kick.wav", 132)
        fn_bpm = _bpm_from_filenames([kick])
        assert fn_bpm == 130.0, fn_bpm
        bpm, meta, flags = _resolve_project_bpm({"kick": [kick]}, fn_bpm)
        assert bpm == 132.0, bpm
        assert meta["source"].startswith("audio (overrode filename 130)"), meta
        assert flags and "130" in flags[0] and "132" in flags[0], flags


def test_agreement_label_confirmed_no_flag():
    with tempfile.TemporaryDirectory() as tmp:
        kick = _make_kick(tmp, "Track 128BPM Kick.wav", 128)
        fn_bpm = _bpm_from_filenames([kick])
        assert fn_bpm == 128.0
        bpm, meta, flags = _resolve_project_bpm({"kick": [kick]}, fn_bpm)
        assert bpm == 128.0, bpm
        assert meta["source"] == "filename (audio-confirmed)", meta
        assert flags == [], flags
        assert meta["residual_ms"] is not None   # carries the grid-lock quality


def test_label_unverified_when_nothing_locks():
    """A pack tagged 124BPM but no lockable rhythmic stem — keep it, flag it."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "Pad 124BPM.wav"
        _write_int16(p, [0] * (SR * 2))          # silence -> no onsets, no lock
        fn_bpm = _bpm_from_filenames([p])
        assert fn_bpm == 124.0
        bpm, meta, flags = _resolve_project_bpm({"music": [p]}, fn_bpm)
        assert bpm == 124.0, bpm
        assert meta["source"] == "filename (unverified)", meta
        assert flags and "could not be confirmed" in flags[0], flags


def test_no_label_audio_decides():
    with tempfile.TemporaryDirectory() as tmp:
        kick = _make_kick(tmp, "Kick.wav", 124)
        bpm, meta, flags = _resolve_project_bpm({"kick": [kick]}, None)
        assert bpm == 124.0, bpm
        assert meta["source"] == "Kick.wav", meta   # sourced from the stem
        assert not any("overrode" in f for f in flags)


def test_no_label_no_audio_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "Silence.wav"
        _write_int16(p, [0] * (SR * 2))
        bpm, meta, flags = _resolve_project_bpm({"music": [p]}, None)
        assert bpm is None and meta is None and flags == []


# --- genuine half-BPM (125.5) must survive ---------------------------------

def test_filename_reads_half_bpm():
    with tempfile.TemporaryDirectory() as tmp:
        whole = Path(tmp) / "Track 128BPM Kick.wav"
        half = Path(tmp) / "Track 125.5 BPM Kick.wav"
        assert _bpm_from_filenames([whole]) == 128.0
        assert _bpm_from_filenames([half]) == 125.5          # .5 kept, not 125


def test_labelled_half_confirmed_by_audio_stays_half():
    """A pack labelled 125.5 whose audio locks near 125.5 keeps the half."""
    with tempfile.TemporaryDirectory() as tmp:
        kick = _make_kick(tmp, "Track 125.5BPM Kick.wav", 125.5)
        fn_bpm = _bpm_from_filenames([kick])
        assert fn_bpm == 125.5
        bpm, meta, flags = _resolve_project_bpm({"kick": [kick]}, fn_bpm)
        assert bpm == 125.5, bpm
        assert meta["source"] == "filename (audio-confirmed)", meta


def test_set_global_tempo_preserves_half():
    """The .als writer must not truncate 125.5 -> 125 (Manual AND automation)."""
    lines = [
        "<MainTrack>",
        "<Tempo>",
        '<Manual Value="120" />',
        '<AutomationTarget Id="8">',
        "</AutomationTarget>",
        "</Tempo>",
        "</MainTrack>",
        '<AutomationEnvelope Id="0">',
        '<PointeeId Value="8" />',
        '<FloatEvent Time="63072000" Value="120" />',
        "</AutomationEnvelope>",
    ]
    als_patcher.set_global_tempo(lines, 125.5)
    blob = "\n".join(lines)
    assert 'Manual Value="125.5"' in blob, blob
    assert 'FloatEvent Time="63072000" Value="125.5"' in blob, blob
    assert '"125"' not in blob                    # no truncation anywhere

    lines2 = list(lines)
    als_patcher.set_global_tempo(lines2, 128)
    assert 'Manual Value="128"' in "\n".join(lines2)   # whole stays clean int


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
