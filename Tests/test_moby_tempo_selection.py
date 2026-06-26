"""Regression test for tempo selection on syncopated-kick stem packs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

import project_builder  # noqa: E402
from project_builder import detect_project_bpm  # noqa: E402
from stem_classifier import classify_stems  # noqa: E402


def test_moby_snare_grid_beats_syncopated_kick():
    folder = Path(r"C:\Users\Carillon\Desktop\for now 160 multitracks 24 441")
    if not folder.exists():
        raise AssertionError("Moby stem folder missing; cannot verify tempo regression")

    classified, _references, _unknown = classify_stems(folder)
    result, source = detect_project_bpm(classified)

    assert result is not None
    assert result["bpm_rounded"] == 160
    assert source.name in {"sn_03.wav", "hh_03.wav"}
    assert result["n_inliers"] == result["n_onsets"]
    assert result["residual_ms"] <= 1.0


def test_consensus_bpm_beats_single_stem_when_candidates_are_credible():
    original_detect_bpm = project_builder.detect_bpm
    paths = {
        "solo.wav": Path("solo.wav"),
        "snare.wav": Path("snare.wav"),
        "hat.wav": Path("hat.wav"),
    }
    fake_results = {
        paths["solo.wav"]: {
            "bpm": 127.9, "bpm_rounded": 128, "n_onsets": 60,
            "n_inliers": 60, "residual_ms": 0.2,
        },
        paths["snare.wav"]: {
            "bpm": 159.6, "bpm_rounded": 160, "n_onsets": 58,
            "n_inliers": 57, "residual_ms": 0.4,
        },
        paths["hat.wav"]: {
            "bpm": 160.2, "bpm_rounded": 160, "n_onsets": 240,
            "n_inliers": 236, "residual_ms": 0.5,
        },
    }

    def fake_detect_bpm(path):
        return fake_results[path]

    project_builder.detect_bpm = fake_detect_bpm
    try:
        result, source = detect_project_bpm({
            "kick": [paths["solo.wav"]],
            "drums": [paths["snare.wav"], paths["hat.wav"]],
        })
    finally:
        project_builder.detect_bpm = original_detect_bpm

    assert result["bpm_rounded"] == 160
    assert source in {paths["snare.wav"], paths["hat.wav"]}


if __name__ == "__main__":
    test_moby_snare_grid_beats_syncopated_kick()
    test_consensus_bpm_beats_single_stem_when_candidates_are_credible()
    print("tempo selection regression passed")
