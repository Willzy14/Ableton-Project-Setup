"""Version-shape detection — including versions that live entirely in
subfolders with no top-level stems (e.g. Extended/ + Radio/), the case that
previously merged into one project with duplicate tracks.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

from versions import detect_versions


def _pack(layout):
    """layout = {subfolder_or_'': [filenames]}. '' = top-level files."""
    root = Path(tempfile.mkdtemp())
    for sub, names in layout.items():
        d = root / sub if sub else root
        d.mkdir(parents=True, exist_ok=True)
        for n in names:
            (d / n).write_bytes(b"RIFF")   # detection is name-only, no reading
    return root


def test_subfolder_versions_no_top_level():
    root = _pack({
        "LIFT - OFF  Extended": ["01_kick.wav", "02_bass.wav", "03_vox.wav", "04_synth.wav"],
        "LIFT - OFF  Radio":    ["01_kick.wav", "02_bass.wav", "03_vox.wav"],
    })
    v = detect_versions(root)
    assert v is not None and len(v) == 2
    # Extended (the fuller, extended-named folder) is primary.
    assert "Extended" in v[0]["name"]
    assert "Radio" in v[1]["name"]
    assert len(v[0]["files"]) == 4


def test_single_subfolder_is_not_versions():
    root = _pack({"Only": ["01_kick.wav", "02_bass.wav"]})
    assert detect_versions(root) is None


def test_non_mirroring_subfolders_not_versions():
    # Two subfolders that don't share element keys = category split, not versions.
    root = _pack({
        "drum stems": ["01_kick.wav", "02_snare.wav"],
        "vox stems":  ["03_lead.wav", "04_bgv.wav"],
    })
    assert detect_versions(root) is None


def test_top_level_baseline_still_works():
    # Regression: top-level stems + a mirroring subfolder = versions as before.
    root = _pack({
        "": ["01_kick.wav", "02_bass.wav", "03_vox.wav"],
        "Edit STems": ["01_kick.wav", "02_bass.wav"],
    })
    v = detect_versions(root)
    assert v is not None and len(v) == 2
    assert v[0]["name"] == "Extended"


def test_extended_chosen_over_radio_regardless_of_order():
    # Even if Radio sorts first / is equal size, Extended wins as primary.
    root = _pack({
        "AAA Radio":    ["01_kick.wav", "02_bass.wav", "03_vox.wav"],
        "ZZZ Extended": ["01_kick.wav", "02_bass.wav", "03_vox.wav"],
    })
    v = detect_versions(root)
    assert "Extended" in v[0]["name"]


def test_nametoken_versions_one_flat_folder():
    # Get Right shape: one flat folder, versions told apart by a name token.
    root = _pack({"": [
        "01_Kick S16.wav", "02_Bass S16.wav", "03_Vox S16.wav", "04_Synth S16.wav",
        "01_Kick S17 SHRT EDIT.wav", "02_Bass S17 SHRT EDIT.wav",
        "03_Vox S17 SHRT EDIT.wav", "04_Synth S17 SHRT EDIT.wav",
    ]})
    v = detect_versions(root)
    assert v is not None and len(v) == 2, v
    assert v[0]["name"] == "S16"                    # fuller arrangement is primary
    assert "S17" in v[1]["name"]
    assert len(v[0]["files"]) == 4 and len(v[1]["files"]) == 4


def test_normal_flat_pack_is_not_nametoken_versions():
    root = _pack({"": [
        "01_Kick.wav", "02_Bass.wav", "03_Vox.wav",
        "04_Synth.wav", "05_Clap.wav", "06_Hat.wav",
    ]})
    assert detect_versions(root) is None


def test_incidental_token_does_not_split():
    # 8 real stems + a couple of "dub"/"edit"-named FX must NOT be mis-split.
    root = _pack({"": [
        "01_Kick.wav", "02_Bass.wav", "03_Vox.wav", "04_Synth.wav",
        "05_Clap.wav", "06_Hat.wav", "07_Perc.wav", "08_Lead.wav",
        "09_Reverb Dub.wav", "10_Guitar Edit.wav",
    ]})
    assert detect_versions(root) is None


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
