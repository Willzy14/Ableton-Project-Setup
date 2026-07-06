"""Regression tests for multi-version stem classification."""
import sys
import struct
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

import project_builder  # noqa: E402


def _tiny_wav(path):
    """A real (short) WAV so _ensure_wav_paths' header validation accepts it."""
    with wave.open(str(path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
        w.writeframes(struct.pack("<" + "h" * 100, *([0] * 100)))


def test_multiversion_unknown_stems_use_ml_category():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "Audio 01.wav"
        _tiny_wav(source)
        output_dir = root / "Output Audio"

        originals = {
            "_ml_classify_unknowns": project_builder._ml_classify_unknowns,
            "audio_label": project_builder.audio_label,
            "find_audio_regions": project_builder.find_audio_regions,
            "find_group_buses": project_builder.find_group_buses,
        }

        def fake_ml(paths):
            return {paths[0]: {"category": "bass", "confidence": 0.99}}

        project_builder._ml_classify_unknowns = fake_ml
        project_builder.audio_label = lambda _path: "stem"
        project_builder.find_audio_regions = lambda _path, head_sec=0.0: [(0.0, 1.0)]
        project_builder.find_group_buses = lambda _paths: []
        try:
            mix, refs, buses, _skipped = project_builder._process_version_files(
                [source],
                output_dir,
                "Audio/Extended/",
            )
        finally:
            project_builder._ml_classify_unknowns = originals["_ml_classify_unknowns"]
            project_builder.audio_label = originals["audio_label"]
            project_builder.find_audio_regions = originals["find_audio_regions"]
            project_builder.find_group_buses = originals["find_group_buses"]

        assert refs == []
        assert buses == []
        assert len(mix) == 1
        assert mix[0]["category"] == "bass"
        assert mix[0]["color"] == project_builder.CATEGORIES["bass"]["color"]
        assert (output_dir / source.name).exists()


def test_multiversion_unknown_stems_fall_back_to_music_when_ml_disabled():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "Audio 02.wav"
        _tiny_wav(source)

        originals = {
            "_ml_classify_unknowns": project_builder._ml_classify_unknowns,
            "audio_label": project_builder.audio_label,
            "find_audio_regions": project_builder.find_audio_regions,
            "find_group_buses": project_builder.find_group_buses,
        }

        def fail_if_called(_paths):
            raise AssertionError("ML classifier should not run when use_ml=False")

        project_builder._ml_classify_unknowns = fail_if_called
        project_builder.audio_label = lambda _path: "stem"
        project_builder.find_audio_regions = lambda _path, head_sec=0.0: [(0.0, 1.0)]
        project_builder.find_group_buses = lambda _paths: []
        try:
            mix, _refs, _buses, _skipped = project_builder._process_version_files(
                [source],
                root / "Output Audio",
                "Audio/Extended/",
                use_ml=False,
            )
        finally:
            project_builder._ml_classify_unknowns = originals["_ml_classify_unknowns"]
            project_builder.audio_label = originals["audio_label"]
            project_builder.find_audio_regions = originals["find_audio_regions"]
            project_builder.find_group_buses = originals["find_group_buses"]

        assert len(mix) == 1
        assert mix[0]["category"] == "music"


if __name__ == "__main__":
    test_multiversion_unknown_stems_use_ml_category()
    test_multiversion_unknown_stems_fall_back_to_music_when_ml_disabled()
    print("multi-version ML classification tests passed")
