"""Non-WAV stems (MP3/FLAC/AIFF dropped in with the stems) must not crash the
build: they're converted to WAV; a truly unreadable file is skipped, not fatal.
"""
import sys
import wave
import struct
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Source"))

from project_builder import _ensure_wav_paths
from als_patcher import get_wav_info, find_audio_regions

try:
    import soundfile as _sf
    HAVE_SF = True
except Exception:  # noqa: BLE001
    HAVE_SF = False


def _sine_flac(path, secs=0.5, sr=44100, f=220):
    import math
    data = [0.3 * math.sin(2 * math.pi * f * i / sr) for i in range(int(secs * sr))]
    _sf.write(str(path), data, sr, format="FLAC")


def test_wav_passes_through_untouched():
    tmp = Path(tempfile.mkdtemp())
    w = tmp / "kick.wav"
    with wave.open(str(w), "w") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(44100)
        wf.writeframes(struct.pack("<" + "h" * 1000, *([1000] * 1000)))
    new, skipped = _ensure_wav_paths([w], tmp / "staging")
    assert new == [w] and not skipped          # unchanged, no staging copy


def test_flac_converted_to_engine_readable_wav():
    if not HAVE_SF:
        print("SKIP test_flac_converted (no soundfile)")
        return
    tmp = Path(tempfile.mkdtemp())
    flac = tmp / "Round The World Girl.flac"
    _sine_flac(flac)
    new, skipped = _ensure_wav_paths([flac], tmp / "staging")
    assert not skipped and len(new) == 1
    out = new[0]
    assert out.suffix.lower() == ".wav"
    # The engine's own WAV reader must accept it (this is what crashed before).
    n_frames, sr, _ = get_wav_info(out)
    assert n_frames > 0 and sr == 44100
    regions = find_audio_regions(out)
    assert regions and regions[0][1] > 0


def test_unreadable_file_is_skipped_not_fatal():
    tmp = Path(tempfile.mkdtemp())
    junk = tmp / "broken.flac"
    junk.write_bytes(b"this is not audio at all")
    new, skipped = _ensure_wav_paths([junk], tmp / "staging")
    assert new == [] and len(skipped) == 1     # dropped, no exception raised
    assert skipped[0][0] == junk


def test_mixed_list_keeps_order_and_converts_only_non_wav():
    if not HAVE_SF:
        print("SKIP test_mixed_list (no soundfile)")
        return
    tmp = Path(tempfile.mkdtemp())
    w = tmp / "snare.wav"
    with wave.open(str(w), "w") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(44100)
        wf.writeframes(struct.pack("<" + "h" * 500, *([500] * 500)))
    flac = tmp / "ref.flac"
    _sine_flac(flac)
    new, skipped = _ensure_wav_paths([w, flac], tmp / "staging")
    assert not skipped and len(new) == 2
    assert new[0] == w                          # wav untouched, order kept
    assert new[1].suffix.lower() == ".wav" and new[1] != flac


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
