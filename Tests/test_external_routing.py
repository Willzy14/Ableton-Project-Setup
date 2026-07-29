"""SNAG-002 regression: 2MIX-prefixed working stems must never reach Ext. Out."""
import re
import struct
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

import als_patcher  # noqa: E402
import project_builder  # noqa: E402
from project_builder import get_template_path  # noqa: E402
from stem_classifier import CATEGORIES, classify_stem  # noqa: E402
from validate_project import validate_path  # noqa: E402


def _tone(path, frequency=220, seconds=0.2, sample_rate=44100):
    path.parent.mkdir(parents=True, exist_ok=True)
    count = int(seconds * sample_rate)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for i in range(count):
            value = 10000 if (i * frequency // sample_rate) % 2 else -10000
            frames += struct.pack("<h", value)
        handle.writeframes(bytes(frames))


def _track_states(lines):
    states = {}
    for track in als_patcher.find_track_ranges(lines):
        if track["type"] != "AudioTrack":
            continue
        state = {"target": None, "speaker": None, "color": None}
        in_output = False
        in_speaker = False
        for i in range(track["start"], track["end"] + 1):
            line = lines[i]
            if "<Color Value=" in line and state["color"] is None:
                state["color"] = re.search(r'Value="(\d+)"', line).group(1)
            if "<AudioOutputRouting>" in line:
                in_output = True
            elif "</AudioOutputRouting>" in line:
                in_output = False
            elif in_output and "<Target Value=" in line:
                state["target"] = re.search(r'Value="([^"]*)"', line).group(1)
            if "<Speaker>" in line:
                in_speaker = True
            elif "</Speaker>" in line:
                in_speaker = False
            elif in_speaker and "<Manual Value=" in line:
                state["speaker"] = re.search(r'Value="([^"]*)"', line).group(1)
        states[track["name"]] = state
    return states


def _stem(audio_dir, name, category, **extra):
    path = audio_dir / (name + ".wav")
    _tone(path)
    stem = {
        "name": name,
        "clip_name": name,
        "category": category,
        "color": CATEGORIES.get(category, {}).get("color", 8),
        "file_path": path,
        "rel_path": "Audio/" + path.name,
        "regions": None,
    }
    stem.update(extra)
    return stem


def test_production_2mix_names_stay_working_through_complex_layout():
    template = Path(get_template_path())
    if not template.exists():
        print("SKIP test_production_2mix_names_stay_working_through_complex_layout")
        return

    tmp = Path(tempfile.mkdtemp(prefix="snag002_"))
    project_dir = tmp / "Project"
    audio_dir = project_dir / "Audio"
    audio_dir.mkdir(parents=True)

    real_names = [
        ("WynStarks_COCO_DA_2MIX_loop1", "drums"),
        ("WynStarks_COCO_DA_2MIX_loop2", "drums"),
        ("LR_OneWayTicket_DA_2MIX_ohh", "drums"),
        ("WynStarks_COCO_DA_2MIX_CHOP", "music"),
        ("LR_OneWayTicket_DA_2MIX_CHOPS", "music"),
        ("LR_OneWayTicket_DA_2MIX_GTRS", "music"),
    ]
    for name, expected in real_names:
        category, is_reference = classify_stem(name + ".wav")
        assert not is_reference, name + " was still classified as a reference"
        assert category == expected, (name, category, expected)

    stems = [_stem(audio_dir, "Kick", "kick")]
    for name, category in real_names[:3]:
        stems.append(_stem(
            audio_dir, name, category,
            group_key="drums", group_name="Drums",
            subgroup_key="kit", subgroup_name="Kit", subgroup_color=6,
        ))
    for name, category in real_names[3:]:
        subgroup = (
            {"subgroup_key": "chops", "subgroup_name": "Chops", "subgroup_color": 8}
            if "CHOP" in name else {}
        )
        stems.append(_stem(
            audio_dir, name, category,
            group_key="music", group_name="Music", **subgroup,
        ))

    # Match the real project-builder tail order: working, Dry park, refs,
    # refcompare, bus park, silent park.
    stems += [
        _stem(
            audio_dir, "Vox DRY", "vocals",
            group_key="dry", group_name="Dry", group_muted=True,
            group_unfolded=False, group_color=37,
        ),
        _stem(audio_dir, "FLAT REF", "reference", color=14),
        _stem(audio_dir, "References", "refcompare", color=26),
        _stem(audio_dir, "Drum Bus", "bus", color=2),
        _stem(audio_dir, "Silent Stem", "silent", color=12),
    ]

    # Poison every destination template slot with External routing. The patcher
    # must explicitly restore all non-reference tracks before applying groups.
    tainted_lines = als_patcher.decompress_als(template)
    audio_tracks = [
        track for track in als_patcher.find_track_ranges(tainted_lines)
        if track["type"] == "AudioTrack"
    ]
    for track in audio_tracks[1:len(stems) + 1]:
        als_patcher.set_track_output_external(tainted_lines, track)
    tainted_template = tmp / "tainted-template.als"
    als_patcher.compress_als(tainted_lines, tainted_template)

    output = project_dir / "SNAG-002.als"
    als_patcher.patch_project(
        tainted_template, output, stems, 124.0, audio_dir, locators=[],
    )

    lines = als_patcher.decompress_als(output)
    states = _track_states(lines)
    assert states["Kick"]["target"] == "AudioOut/Main", states["Kick"]
    for name, _category in real_names:
        assert states[name]["target"] == "AudioOut/GroupTrack", (name, states[name])
    assert states["Vox DRY"]["target"] == "AudioOut/GroupTrack", states["Vox DRY"]
    assert states["Drum Bus"]["target"] == "AudioOut/Main", states["Drum Bus"]
    assert states["Silent Stem"]["target"] == "AudioOut/Main", states["Silent Stem"]
    assert states["FLAT REF"]["target"].startswith("AudioOut/External")
    assert states["FLAT REF"]["speaker"] == "false"
    assert states["References"]["target"].startswith("AudioOut/External")
    assert states["References"]["speaker"] == "true"

    result = validate_path(output, expected_tempo=124)
    assert result.ok, result.errors


def test_named_music_bypasses_full_mix_audio_safety_net():
    tmp = Path(tempfile.mkdtemp(prefix="snag002_audio_"))
    source = tmp / "LR_OneWayTicket_DA_2MIX_GTRS.wav"
    _tone(source)

    original_audio_label = project_builder.audio_label
    original_regions = project_builder.find_audio_regions
    original_buses = project_builder.find_group_buses
    try:
        # An intentionally hostile result: a filename-confirmed guitar stem must
        # not even be offered to the ambiguous-file full-mix detector.
        project_builder.audio_label = lambda _path: "full_mix"
        project_builder.find_audio_regions = (
            lambda _path, head_sec=0.0, return_peak=False:
            ([(0.0, 0.2)], -3.0) if return_peak else [(0.0, 0.2)]
        )
        project_builder.find_group_buses = lambda _paths: set()
        mix, refs, buses, drys, skipped = project_builder._process_version_files(
            [source], tmp / "Audio", "Audio/Test/", use_ml=False,
        )
    finally:
        project_builder.audio_label = original_audio_label
        project_builder.find_audio_regions = original_regions
        project_builder.find_group_buses = original_buses

    assert len(mix) == 1 and mix[0]["category"] == "music", mix
    assert refs == []
    assert buses == []
    assert drys == []
    assert skipped == []


if __name__ == "__main__":
    import traceback

    functions = [
        value for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failed = 0
    for function in functions:
        try:
            function()
            print("PASS", function.__name__)
        except Exception:  # noqa: BLE001
            failed += 1
            print("FAIL", function.__name__)
            traceback.print_exc()
    print("ALL PASS" if not failed else str(failed) + " FAILED")
    sys.exit(1 if failed else 0)
