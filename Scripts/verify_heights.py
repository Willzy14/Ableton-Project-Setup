"""Verify LaneHeight and TrackUnfolded values in generated ALS files."""
import gzip
import re
import sys
from pathlib import Path

als_files = [
    Path(r"Test Output\TEST Ak1ra - The Way [Test Run] Project\TEST Ak1ra - The Way [Test Run].als"),
    Path(r"Test Output\Sparks - How To Survive Edit [Test Run] Project\Sparks - How To Survive Edit [Test Run].als"),
]

for als in als_files:
    if not als.exists():
        print("MISSING: " + str(als))
        continue
    print("\n=== " + als.name + " ===")
    with gzip.open(als, "rb") as f:
        content = f.read().decode("utf-8")
    lines = content.splitlines()

    in_track = False
    track_type = ""
    track_name = ""
    lane_height = ""
    unfolded = ""
    for i, line in enumerate(lines):
        if "<AudioTrack " in line or "<GroupTrack " in line or "<MainTrack>" in line:
            in_track = True
            track_name = ""
            lane_height = ""
            unfolded = ""
            if "<AudioTrack" in line:
                track_type = "Audio"
            elif "<GroupTrack" in line:
                track_type = "Group"
            else:
                track_type = "Main"
        if in_track and "<EffectiveName" in line and not track_name:
            m = re.search(r'Value="([^"]*)"', line)
            if m:
                track_name = m.group(1)
        if in_track and "<TrackUnfolded" in line and not unfolded:
            m = re.search(r'Value="([^"]*)"', line)
            if m:
                unfolded = m.group(1)
        if in_track and "<LaneHeight" in line and not lane_height:
            m = re.search(r'Value="(\d+)"', line)
            if m:
                lane_height = m.group(1)
        if in_track and ("</AudioTrack>" in line or "</GroupTrack>" in line or "</MainTrack>" in line):
            print("  " + track_type.ljust(8) + track_name.ljust(35) + "Unfolded=" + unfolded.ljust(6) + "LaneHeight=" + lane_height)
            in_track = False
