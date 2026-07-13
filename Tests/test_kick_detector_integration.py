"""Kick Detector V3 integration for BPM onset picking."""
import math
import struct
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

import bpm_detector  # noqa: E402

SR = 44100


def _write_wav(path):
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", 0) for _ in range(SR * 8)))


def _pcm24(value):
    return int(value).to_bytes(3, byteorder="little", signed=True)


def _write_stereo_24bit_wav(path):
    frames = [
        _pcm24(8388607) + _pcm24(-8388608),
        _pcm24(4194304) + _pcm24(4194304),
    ]
    with wave.open(str(path), "w") as w:
        w.setnchannels(2)
        w.setsampwidth(3)
        w.setframerate(SR)
        w.writeframes(b"".join(frames))


def _write_fake_kick_detector(source_dir):
    source_dir.mkdir()
    (source_dir / "model.py").write_text("MARKER = 'fake'\n", encoding="utf-8")
    (source_dir / "infer.py").write_text(
        "from model import MARKER\n"
        "class KickModel:\n"
        "    def __init__(self, ckpt, device='cpu'):\n"
        "        self.ckpt = ckpt\n"
        "    def onsets(self, audio, sr, thresh=0.3):\n"
        "        return [i * 0.5 for i in range(16)]\n",
        encoding="utf-8",
    )


def _write_noisy_fake_kick_detector(source_dir):
    source_dir.mkdir()
    (source_dir / "model.py").write_text(
        "print('model import noise')\nMARKER = 'fake'\n", encoding="utf-8")
    (source_dir / "infer.py").write_text(
        "print('infer import noise')\n"
        "from model import MARKER\n"
        "class KickModel:\n"
        "    def __init__(self, ckpt, device='cpu'):\n"
        "        print('model load noise')\n"
        "    def onsets(self, audio, sr, thresh=0.3):\n"
        "        print('inference noise')\n"
        "        return [i * 0.5 for i in range(16)]\n",
        encoding="utf-8",
    )


def test_kick_detector_onsets_feed_existing_lattice_fit():
    old_model = sys.modules.get("model")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        wav = tmp / "Kick.wav"
        ckpt = tmp / "kick_crnn_V3.pt"
        source = tmp / "Kick Detector Source"
        _write_wav(wav)
        ckpt.write_bytes(b"fake weights")
        _write_fake_kick_detector(source)

        bpm_detector.configure_kick_detector(
            enabled=True,
            model_path=ckpt,
            source_dir=source,
            threshold=0.30,
            device="cpu",
        )
        try:
            result = bpm_detector.detect_bpm(wav)
        finally:
            bpm_detector.configure_kick_detector(enabled=False)

    assert result is not None
    assert result["detector"] == "kick_crnn_v3"
    assert math.isclose(result["bpm"], 120.0, abs_tol=0.01)
    assert result["n_onsets"] == 16
    assert sys.modules.get("model") is old_model


def test_kick_detector_subprocess_ignores_stdout_noise():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        wav = tmp / "Kick.wav"
        ckpt = tmp / "kick_crnn_V3.pt"
        source = tmp / "Noisy Kick Detector Source"
        _write_wav(wav)
        ckpt.write_bytes(b"fake weights")
        _write_noisy_fake_kick_detector(source)

        bpm_detector.configure_kick_detector(
            enabled=True,
            model_path=ckpt,
            source_dir=source,
            threshold=0.30,
            device="cpu",
            python_exe=sys.executable,
        )
        try:
            result = bpm_detector.detect_bpm(wav)
        finally:
            bpm_detector.configure_kick_detector(enabled=False)

    assert result is not None
    assert result["detector"] == "kick_crnn_v3"
    assert math.isclose(result["bpm"], 120.0, abs_tol=0.01)


def test_kick_detector_failure_falls_back_to_energy_detector():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        wav = tmp / "Kick.wav"
        _write_wav(wav)

        bpm_detector.configure_kick_detector(
            enabled=True,
            model_path=tmp / "missing.pt",
            source_dir=tmp / "missing_source",
        )
        try:
            result = bpm_detector.detect_bpm(wav)
        finally:
            bpm_detector.configure_kick_detector(enabled=False)

    assert result is None


def test_kick_detector_name_gate_targets_kick_like_files():
    old = bpm_detector.os.environ.get("KICK_DETECTOR_ALL_CANDIDATES")
    try:
        bpm_detector.os.environ.pop("KICK_DETECTOR_ALL_CANDIDATES", None)
        assert bpm_detector._kick_model_name_allowed("1.0 - KICK.wav")
        assert bpm_detector._kick_model_name_allowed("KIK 909.wav")
        assert bpm_detector._kick_model_name_allowed("BD 01.wav")
        assert bpm_detector._kick_model_name_allowed("KickBassProcess.wav")
        assert not bpm_detector._kick_model_name_allowed("1.0 - Clap.wav")

        bpm_detector.os.environ["KICK_DETECTOR_ALL_CANDIDATES"] = "1"
        assert bpm_detector._kick_model_name_allowed("1.0 - Clap.wav")
    finally:
        if old is None:
            bpm_detector.os.environ.pop("KICK_DETECTOR_ALL_CANDIDATES", None)
        else:
            bpm_detector.os.environ["KICK_DETECTOR_ALL_CANDIDATES"] = old


def test_in_process_wav_reader_decodes_stereo_24bit_pcm():
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "Kick.wav"
        _write_stereo_24bit_wav(wav)

        audio, sr = bpm_detector._read_wav_mono_np(wav)

    assert sr == SR
    assert len(audio) == 2
    assert abs(float(audio[0]) - 0.0) < 0.001
    assert abs(float(audio[1]) - 0.5) < 0.001


if __name__ == "__main__":
    test_kick_detector_onsets_feed_existing_lattice_fit()
    test_kick_detector_subprocess_ignores_stdout_noise()
    test_kick_detector_failure_falls_back_to_energy_detector()
    test_kick_detector_name_gate_targets_kick_like_files()
    test_in_process_wav_reader_decodes_stereo_24bit_pcm()
    print("kick detector integration tests passed")
