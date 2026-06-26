"""Regression tests for multi-version grid alignment."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

import bpm_detector  # noqa: E402
import project_builder  # noqa: E402


def test_detect_bpm_reports_first_actual_onset_separately_from_grid_phase():
    originals = {
        "_read_envelope": bpm_detector._read_envelope,
        "_pick_onsets": bpm_detector._pick_onsets,
        "_seed_period": bpm_detector._seed_period,
        "_lattice_fit": bpm_detector._lattice_fit,
    }

    onsets = [31.4 + (0.46875 * i) for i in range(12)]
    bpm_detector._read_envelope = lambda _path: ([0.0], 1000)
    bpm_detector._pick_onsets = lambda _env, _rate: onsets
    bpm_detector._seed_period = lambda _onsets, _min_bpm, _max_bpm: 0.46875
    bpm_detector._lattice_fit = lambda _onsets, _period: (0.034, 0.46875, [0.0] * len(onsets))
    try:
        result = bpm_detector.detect_bpm(Path("fake.wav"))
    finally:
        bpm_detector._read_envelope = originals["_read_envelope"]
        bpm_detector._pick_onsets = originals["_pick_onsets"]
        bpm_detector._seed_period = originals["_seed_period"]
        bpm_detector._lattice_fit = originals["_lattice_fit"]

    assert result["first_beat_sec"] == 0.034
    assert result["first_actual_onset_sec"] == 31.4


def test_multiversion_alignment_prefers_first_actual_onset():
    result = {"first_beat_sec": 0.034, "first_actual_onset_sec": 31.4}

    assert project_builder._version_alignment_sec(result) == 31.4


def test_multiversion_alignment_uses_cleanest_kick_candidate():
    originals = {"detect_bpm": project_builder.detect_bpm}
    bad_kick = Path("Kick Bass Process.wav")
    clean_kick = Path("Kick.wav")
    fake_results = {
        bad_kick: {
            "first_beat_sec": 1.4,
            "first_actual_onset_sec": 1.4,
            "n_onsets": 100,
            "n_inliers": 60,
            "residual_ms": 10.0,
        },
        clean_kick: {
            "first_beat_sec": 0.034,
            "first_actual_onset_sec": 31.512,
            "n_onsets": 148,
            "n_inliers": 148,
            "residual_ms": 0.25,
        },
    }

    project_builder.detect_bpm = lambda path: fake_results[path]
    try:
        alignment = project_builder._detect_version_alignment_sec([
            {"category": "kick", "file_path": bad_kick},
            {"category": "kick", "file_path": clean_kick},
        ])
    finally:
        project_builder.detect_bpm = originals["detect_bpm"]

    assert alignment == 31.512


def test_multiversion_stack_anchor_uses_earliest_kick_layer():
    originals = {"detect_bpm": project_builder.detect_bpm}
    kick_layer = Path("Kick Bass Process.wav")
    dry_kick = Path("Kick.wav")
    fake_results = {
        kick_layer: {
            "bpm_rounded": 128,
            "first_actual_onset_sec": 1.41,
            "n_onsets": 214,
            "n_inliers": 127,
            "residual_ms": 10.15,
        },
        dry_kick: {
            "bpm_rounded": 128,
            "first_actual_onset_sec": 31.512,
            "n_onsets": 148,
            "n_inliers": 148,
            "residual_ms": 0.25,
        },
    }

    project_builder.detect_bpm = lambda path: fake_results[path]
    try:
        anchor = project_builder._detect_version_stack_anchor_sec([
            {"category": "bass", "file_path": kick_layer},
            {"category": "kick", "file_path": dry_kick},
        ], project_bpm=128)
    finally:
        project_builder.detect_bpm = originals["detect_bpm"]

    assert anchor == 1.41


def test_next_version_starts_on_next_32_bar_phrase_boundary():
    assert project_builder._next_phrase_boundary(960.145850340136) == 1024


def test_multiversion_build_anchor_can_use_detected_buses():
    originals = {"_detect_version_stack_anchor_sec": project_builder._detect_version_stack_anchor_sec}
    calls = []

    def fake_anchor(stems, project_bpm):
        calls.append(stems)
        return 1.41

    project_builder._detect_version_stack_anchor_sec = fake_anchor
    try:
        p = {"mix": [{"name": "dry kick"}], "buses": [{"name": "kick bus"}]}
        p["first_beat_sec"] = project_builder._detect_version_stack_anchor_sec(
            p["mix"] + p["buses"], 128
        )
    finally:
        project_builder._detect_version_stack_anchor_sec = originals["_detect_version_stack_anchor_sec"]

    assert p["first_beat_sec"] == 1.41
    assert calls[0] == [{"name": "dry kick"}, {"name": "kick bus"}]


if __name__ == "__main__":
    test_detect_bpm_reports_first_actual_onset_separately_from_grid_phase()
    test_multiversion_alignment_prefers_first_actual_onset()
    test_multiversion_alignment_uses_cleanest_kick_candidate()
    test_multiversion_stack_anchor_uses_earliest_kick_layer()
    test_next_version_starts_on_next_32_bar_phrase_boundary()
    test_multiversion_build_anchor_can_use_detected_buses()
    print("multi-version alignment tests passed")
