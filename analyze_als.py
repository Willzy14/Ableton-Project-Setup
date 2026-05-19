"""Analyze ALS files to extract track layout, colors, groups, and structure."""
import gzip
import re
import sys
from pathlib import Path


def decompress_als(als_path: Path) -> list:
    with gzip.open(als_path, "rb") as f:
        content = f.read().decode("utf-8")
    return content.splitlines(keepends=True)


def analyze_tracks(lines):
    tracks = []
    stack = []  # (track_type, start_line, name, color, group_id)

    for i, line in enumerate(lines):
        for tt in ["GroupTrack", "AudioTrack", "ReturnTrack", "MidiTrack", "MainTrack"]:
            if "<" + tt + " " in line or "<" + tt + ">" in line:
                tid = ""
                m = re.search(r'Id="(\d+)"', line)
                if m:
                    tid = m.group(1)
                stack.append({"type": tt, "start": i, "name": "", "color": "", "id": tid, "depth": len(stack)})
                break

        if stack:
            current = stack[-1]
            if "<EffectiveName" in line and not current["name"]:
                m = re.search(r'Value="([^"]*)"', line)
                if m:
                    current["name"] = m.group(1)
            if "<Color Value=" in line and not current["color"]:
                m = re.search(r'Value="(\d+)"', line)
                if m:
                    current["color"] = m.group(1)

            for tt in ["GroupTrack", "AudioTrack", "ReturnTrack", "MidiTrack", "MainTrack"]:
                if "</" + tt + ">" in line:
                    finished = stack.pop()
                    finished["end"] = i
                    finished["parent_depth"] = len(stack)
                    tracks.append(finished)
                    break

    return tracks


def find_group_membership(lines, tracks):
    """Figure out which tracks belong to which groups using TrackGroupId."""
    for t in tracks:
        start = t["start"]
        search_end = min(start + 50, t["end"])
        for i in range(start, search_end):
            if "<TrackGroupId" in lines[i]:
                m = re.search(r'Value="(-?\d+)"', lines[i])
                if m:
                    t["group_id"] = m.group(1)
                break
        else:
            t["group_id"] = "-1"
    return tracks


def print_track_tree(tracks):
    group_ids = {}
    for t in tracks:
        if t["type"] == "GroupTrack":
            group_ids[t["id"]] = t["name"]

    print("\n  TRACK LAYOUT:")
    print("  " + "-" * 60)
    for t in tracks:
        indent = "  " if t.get("group_id", "-1") != "-1" and t["type"] != "GroupTrack" else ""
        group_name = ""
        gid = t.get("group_id", "-1")
        if gid != "-1" and t["type"] != "GroupTrack":
            group_name = " [in: " + group_ids.get(gid, "?") + "]"

        color_str = t["color"].rjust(3)
        print("  " + indent + t["type"].ljust(12) + " | Color " + color_str + " | " + t["name"] + group_name)
    print()


def main():
    base = Path(r"C:\Users\Carillon\Wired Masters Dropbox\Sam Wills\2.1. Finished Stem Mixes")

    als_files = [
        base / "2. Ongoing Stem Mixes" / "Ak1ra - The Way [Ramzi Karam] Project" / "Ak1ra - The Way [Ramzi Karam].als",
        base / "2. Ongoing Stem Mixes" / "Eats Everything - Ms Noise [Black Book] Project" / "Eats Everything - Ms Noise [Black Book].als",
        base / "2. Ongoing Stem Mixes" / "Noden - Disco [Sound Better] Project" / "Noden - Disco [Sound Better].als",
        base / "James Poole - Lease Of Life [Defected] Project" / "James Poole - Lease Of Life [Defected].als",
        base / "Lost Boy Jay - Temptation [Good Company] Project" / "Lost Boy Jay - Temptation [Good Company].als",
        base / "RILEY - False Reality [Good Company] Project" / "RILEY - False Reality [Good Company].als",
        base / "Detlef - HighRoller [Blackbook Records] Project" / "Detlef - HighRoller [Blackbook Records].als",
        base / "Stephani B - Activ-8 (Come With Me) [Perfect Havoc] Project" / "Stephani B - Activ-8 (Come With Me) [Perfect Havoc].als",
    ]

    for als_path in als_files:
        if not als_path.exists():
            print("SKIPPED (not found): " + als_path.name)
            print()
            continue

        print("=" * 70)
        print("FILE: " + als_path.name)
        lines = decompress_als(als_path)
        print("Lines: " + str(len(lines)))

        tracks = analyze_tracks(lines)
        tracks = find_group_membership(lines, tracks)
        print_track_tree(tracks)


if __name__ == "__main__":
    main()
