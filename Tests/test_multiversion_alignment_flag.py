"""SNAG-001: a version whose kick-grid anchor can't be confidently detected gets
NO onset correction and can land a hair off-grid — with, previously, no signal
that it happened. This proves the low-confidence flag actually reaches the
session report end-to-end (not just the unit-level _version_stack_anchor call).
"""
import sys
import math
import wave
import struct
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Source"))
from project_builder import build_project, session_report_path

SR = 44100


def _write_int16(path, samples):
    with wave.open(str(path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(s)) for s in samples))


def _kick_train(bpm, n_beats=16):
    """A clean, confidently-locking kick pulse train (same generator proven in
    test_bpm_reconcile.py)."""
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


def _tone(secs=4.0, freq=220.0, amp=10000):
    n = int(secs * SR)
    return [amp * math.sin(2 * math.pi * freq * i / SR) for i in range(n)]


def test_low_confidence_version_anchor_surfaces_in_report():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "pack"

        # Extended: has a real kick that locks confidently.
        extended = src / "Extended"
        extended.mkdir(parents=True)
        _write_int16(extended / "01_Kick.wav", _kick_train(120))
        _write_int16(extended / "02_Synth.wav", _tone())

        # Radio Edit: NOTHING matches the kick/drums buckets at all (no "kick" in
        # any filename, no kick/drums category stem) — guaranteed confident=False
        # regardless of audio content, since the bucket match happens before
        # detect_bpm is ever attempted.
        radio = src / "Radio Edit"
        radio.mkdir(parents=True)
        _write_int16(radio / "01_Synth.wav", _tone(freq=330.0))
        _write_int16(radio / "02_Pad.wav", _tone(freq=440.0))

        proj = Path(build_project(str(src), "Test", "LowConfidence", "Lab",
                                  bpm=120, output_base=str(tmp / "out"), use_ml=False))
        report = __import__("json").loads(
            session_report_path(proj).read_text(encoding="utf-8"))

        assert report.get("multiversion") is True
        flags = report.get("flags", [])
        matching = [f for f in flags if "couldn't confidently grid-lock" in f.lower()]
        assert matching, "expected a low-confidence alignment flag; flags=" + str(flags)
        assert "Radio Edit" in matching[0], matching[0]
        assert "Extended" not in matching[0], \
            "Extended has a real kick and must not be flagged: " + matching[0]


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
