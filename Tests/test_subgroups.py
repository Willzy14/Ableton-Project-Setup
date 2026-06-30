"""Nested sub-groups: clustering logic + a real nested-ALS TrackGroupId chain.

The clustering tests are pure logic (no template). The end-to-end test builds a
real project and inspects the parent/child TrackGroupId chain in the ALS; it is
skipped when the Ableton template isn't present on this machine.
"""
import re
import sys
import wave
import struct
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

from subgroup_cluster import cluster_subgroups
import als_patcher
from als_patcher import decompress_als
import project_builder
from project_builder import build_project, get_template_path
from validate_project import validate_path


def _stems(names):
    """Minimal stem dicts the clusterer understands (file_path + group tags)."""
    out = []
    for n in names:
        out.append({"file_path": Path(n + ".wav"), "color": 13,
                    "group_color": 13, "group_key": "x"})
    return out


def _sub_layout(stems):
    """(subgroup_name or None) for each stem, in returned order."""
    return [s.get("subgroup_name") for s in stems]


# --- clustering: vocals ----------------------------------------------------

def test_vocals_multi_singer_makes_a_subgroup_per_singer():
    res = cluster_subgroups(_stems([
        "01_Lauren Lead Vox", "02_Lauren Lead FX", "03_Lauren BGV",
        "04_Sarah Lead Vox", "05_Sarah BGV", "06_Sarah BGV FX",
    ]), "vocals")
    assert res is not None
    names = [s["subgroup_name"] for s in res]
    assert names == ["Lauren", "Lauren", "Lauren", "Sarah", "Sarah", "Sarah"]


def test_vocals_role_order_lead_then_leadfx_then_bgv():
    # Within a singer, each role's FX follows it: Lead, Lead-FX, BGV, BGV-FX.
    res = cluster_subgroups(_stems([
        "01_Lauren BGV", "02_Lauren BGV FX", "03_Lauren Lead", "04_Lauren Lead FX",
        "05_Sarah Lead", "06_Sarah BGV",
    ]), "vocals")
    lauren = [s["file_path"].stem for s in res if s["subgroup_name"] == "Lauren"]
    assert lauren == ["03_Lauren Lead", "04_Lauren Lead FX",
                      "01_Lauren BGV", "02_Lauren BGV FX"]


def test_vocals_single_singer_falls_back_to_role_groups():
    # One singer / no usable names -> group by role (Lead vs BGV) directly.
    res = cluster_subgroups(_stems([
        "01_Lead Vox", "02_Lead Double", "03_BGV 1", "04_BGV 2", "05_Adlib",
    ]), "vocals")
    assert res is not None
    by_name = {}
    for s in res:
        by_name.setdefault(s.get("subgroup_name"), []).append(s["file_path"].stem)
    assert set(by_name["Lead"]) == {"01_Lead Vox", "02_Lead Double"}
    assert set(by_name["BGV"]) == {"03_BGV 1", "04_BGV 2"}
    assert by_name.get(None) == ["05_Adlib"]          # ad-lib left loose


def test_title_token_in_every_stem_is_not_a_singer():
    # "Amen" in every name is a title token, not a singer -> role fallback,
    # and since there are no roles either, no useful sub-grouping.
    res = cluster_subgroups(_stems([
        "01_Amen Vox A", "02_Amen Vox B", "03_Amen Vox C",
    ]), "vocals")
    assert res is None


# --- clustering: drums + music --------------------------------------------

def test_drums_kit_vs_percussion():
    res = cluster_subgroups(_stems([
        "01_Snare", "02_Hat", "03_Shaker", "04_Conga", "05_Crash",
    ]), "drums")
    by_name = {}
    for s in res:
        by_name.setdefault(s.get("subgroup_name"), []).append(s["file_path"].stem)
    assert set(by_name["Kit"]) == {"01_Snare", "02_Hat", "05_Crash"}
    assert set(by_name["Percussion"]) == {"03_Shaker", "04_Conga"}


def test_music_groups_by_instrument_family():
    res = cluster_subgroups(_stems([
        "01_Piano", "02_Rhodes", "03_Guitar Lick", "04_Guitar Chord", "05_Bell",
    ]), "music")
    by_name = {}
    for s in res:
        by_name.setdefault(s.get("subgroup_name"), []).append(s["file_path"].stem)
    assert set(by_name["Keys"]) == {"01_Piano", "02_Rhodes"}
    assert set(by_name["Guitar"]) == {"03_Guitar Lick", "04_Guitar Chord"}
    assert by_name.get(None) == ["05_Bell"]           # lone bell stays loose


def test_no_subgroup_when_too_few_or_no_signal():
    assert cluster_subgroups(_stems(["01_Vox", "02_Vox"]), "vocals") is None
    # 3 generic vox, no singer, no roles -> nothing to nest.
    assert cluster_subgroups(_stems(
        ["01_Vox", "02_Vox", "03_Vox"]), "vocals") is None


# --- patcher: nested GroupTrack id allocation is unique --------------------

def test_insert_group_track_nested_sets_parent_and_routing():
    lines = als_patcher._GROUP_TRACK_TEMPLATE  # smoke: template formats nested
    block = als_patcher.insert_group_track(
        ["<x/>\r\n"], 0, "Lauren", 99, color=13, muted=False, unfolded=True,
        parent_group_id=42)
    # insert_group_track returns a count; re-render to inspect the text.
    out = []
    als_patcher.insert_group_track(out, 0, "Lauren", 99, color=13,
                                   muted=False, unfolded=True, parent_group_id=42)
    text = "".join(out)
    assert '<TrackGroupId Value="42" />' in text
    assert 'Value="AudioOut/GroupTrack"' in text
    assert '<EffectiveName Value="Lauren" />' in text


def test_insert_group_track_toplevel_routes_to_main():
    out = []
    als_patcher.insert_group_track(out, 0, "Vox", 50, color=13,
                                   muted=False, unfolded=True)
    text = "".join(out)
    assert '<TrackGroupId Value="-1" />' in text
    assert 'Value="AudioOut/Main" />' in text


# --- end-to-end: real nested ALS, parent/child TrackGroupId chain ----------

def _tone(path, secs=0.4, f=220, sr=44100):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(secs * sr)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            v = int(12000 * ((i * f // sr) % 2 * 2 - 1))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def _group_tracks(lines):
    """[(id, trackgroupid, name)] for every GroupTrack header in the file."""
    groups = []
    i = 0
    while i < len(lines):
        m = re.search(r'<GroupTrack Id="(\d+)"', lines[i])
        if m:
            gid = m.group(1)
            tgid = name = None
            for j in range(i + 1, min(i + 40, len(lines))):
                if tgid is None:
                    mt = re.search(r'<TrackGroupId Value="(-?\d+)"', lines[j])
                    if mt:
                        tgid = mt.group(1)
                if name is None:
                    mn = re.search(r'<EffectiveName Value="([^"]*)"', lines[j])
                    if mn:
                        name = mn.group(1)
                if tgid is not None and name is not None:
                    break
            groups.append((gid, tgid, name))
        i += 1
    return groups


def _audio_track_group_ids(lines):
    """{track_name: trackgroupid} for the AudioTracks."""
    out = {}
    for t in als_patcher.find_track_ranges(lines):
        if t["type"] != "AudioTrack":
            continue
        tgid = None
        for k in range(t["start"], t["end"] + 1):
            mt = re.search(r'<TrackGroupId Value="(-?\d+)"', lines[k])
            if mt:
                tgid = mt.group(1)
                break
        out[t["name"]] = tgid
    return out


def test_end_to_end_nested_vox_chain():
    if not Path(get_template_path()).exists():
        print("SKIP test_end_to_end_nested_vox_chain (template not on this machine)")
        return
    tmp = Path(tempfile.mkdtemp(prefix="subgrp_"))
    src = tmp / "pack"
    _tone(src / "01_Kick.wav", f=60)
    _tone(src / "02_Lauren Lead Vox.wav", f=220)
    _tone(src / "03_Lauren BGV Vox.wav", f=260)
    _tone(src / "04_Sarah Lead Vox.wav", f=330)
    _tone(src / "05_Sarah BGV Vox.wav", f=390)

    proj = build_project(src, "Test", "Nested", "Lab", bpm=124,
                         output_base=tmp / "out", use_ml=False)
    als = next(Path(proj).glob("*.als"))

    # XML well-formed + project sane (catches a broken nested header).
    result = validate_path(als, expected_tempo=124)
    assert result.ok, "validate_project errors: " + "; ".join(result.errors)

    lines = decompress_als(als)
    groups = _group_tracks(lines)
    by_name = {name: (gid, tgid) for gid, tgid, name in groups}

    assert "Vox" in by_name, "no Vox parent group"
    vox_id, vox_tgid = by_name["Vox"]
    assert vox_tgid == "-1", "Vox should be top-level (TrackGroupId -1)"

    assert "Lauren" in by_name and "Sarah" in by_name, "singer sub-groups missing"
    assert by_name["Lauren"][1] == vox_id, "Lauren not nested under Vox"
    assert by_name["Sarah"][1] == vox_id, "Sarah not nested under Vox"
    lauren_id = by_name["Lauren"][0]
    sarah_id = by_name["Sarah"][0]

    atg = _audio_track_group_ids(lines)
    # Each singer's vocal tracks point at their singer sub-group.
    lauren_children = [n for n, g in atg.items() if g == lauren_id]
    sarah_children = [n for n, g in atg.items() if g == sarah_id]
    assert len(lauren_children) == 2, lauren_children
    assert len(sarah_children) == 2, sarah_children
    print("nested chain OK: Vox(%s) > Lauren(%s)/Sarah(%s)"
          % (vox_id, lauren_id, sarah_id))


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
