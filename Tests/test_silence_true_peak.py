"""A quiet-but-real shaker must not be parked as a dead/empty export.

The silence test uses TRUE PEAK, not a windowed RMS: a sparse, transient stem
(shaker) has a low window RMS even though it has real peaks, so a windowed
measure wrongly reads it as silent. Truly empty exports (digital silence,
noise-floor-only) still get flagged.
"""
import sys
import wave
import struct
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

import als_patcher
from als_patcher import find_audio_regions, SILENCE_FLOOR_DB, _rms_windows_np, \
    _read_wav_header

SR = 44100
WIN = int(0.1 * SR)


def _write_int16(path, samples):
    with wave.open(str(path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(s)) for s in samples))


def _quiet_shaker(secs=3.0, amp=318):
    """Sparse ~-40 dBFS transients (high crest factor, like a quiet shaker):
    window RMS lands near -62 dB (under the old floor) while true peak is ~-40."""
    n = int(secs * SR)
    s = [0] * n
    for base in range(0, n, WIN):
        for k in range(30):                 # 30 spikes per 0.1s window
            i = base + k * 7
            if i < n:
                s[i] = amp if k % 2 == 0 else -amp
    return s


def test_quiet_shaker_not_flagged_silent():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "Shaker.wav"
        _write_int16(p, _quiet_shaker())
        regions, true_peak = find_audio_regions(p, return_peak=True)

        # The OLD measure (peak windowed RMS) sits below the silence floor — this
        # is exactly what used to false-flag the shaker as a dead export.
        hdr = _read_wav_header(p)
        with open(p, "rb") as f:
            f.seek(hdr["data_offset"]); raw = f.read()
        rms_list, _ = _rms_windows_np(raw, 1, 2, False, WIN)
        assert max(rms_list) < -60.0, "expected window RMS under old floor: " + str(max(rms_list))

        # The TRUE PEAK is well above the floor, so it is kept as real audio.
        assert true_peak > SILENCE_FLOOR_DB, true_peak
        assert true_peak > -50.0, true_peak
        assert regions, "a non-silent stem must yield at least one region"


def test_digital_silence_is_flagged():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "Dead.wav"
        _write_int16(p, [0] * SR)
        _regions, true_peak = find_audio_regions(p, return_peak=True)
        assert true_peak < SILENCE_FLOOR_DB, true_peak


def test_noise_floor_only_export_is_flagged():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "Hiss.wav"
        amp = max(1, int(10 ** (-80 / 20) * 32768))    # ~-80 dBFS = effectively empty
        _write_int16(p, [amp if i % 2 else -amp for i in range(SR)])
        _regions, true_peak = find_audio_regions(p, return_peak=True)
        assert true_peak < SILENCE_FLOOR_DB, true_peak


def test_numpy_and_stdlib_peak_agree():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "Shaker.wav"
        _write_int16(p, _quiet_shaker(1.0))
        np_peak = find_audio_regions(p, return_peak=True)[1]
        orig = als_patcher._np
        try:
            als_patcher._np = None                       # force the stdlib fallback
            std_peak = find_audio_regions(p, return_peak=True)[1]
        finally:
            als_patcher._np = orig
        assert abs(np_peak - std_peak) < 0.05, (np_peak, std_peak)


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
