"""Analyze the 250-track template ALS file."""
import gzip
import re
from pathlib import Path


def decompress_als(als_path):
    with gzip.open(als_path, "rb") as f:
        content = f.read().decode("utf-8")
    return content.splitlines(keepends=True)


def main():
    als_path = Path(r"C:\Users\Carillon\Documents\Ableton\User Library\Templates\Ableton Project Set Up 250 Tracks.als")
    lines = decompress_als(als_path)
    print("Total lines: " + str(len(lines)))

    # Find all tracks
    tracks = []
    i = 0
    while i < len(lines):
        line = lines[i]
        for tt in ["GroupTrack", "AudioTrack", "ReturnTrack", "MidiTrack", "MainTrack"]:
            if "<" + tt + " " in line or ("<" + tt + ">" in line and tt == "MainTrack"):
                tid = ""
                m = re.search(r'Id="(\d+)"', line)
                if m:
                    tid = m.group(1)

                name = ""
                color = ""
                depth = 1
                j = i + 1
                while j < len(lines) and depth > 0:
                    tl = lines[j]
                    if "<EffectiveName" in tl and not name:
                        m2 = re.search(r'Value="([^"]*)"', tl)
                        if m2:
                            name = m2.group(1)
                    if "<Color Value=" in tl and not color and j < i + 30:
                        m2 = re.search(r'Value="(\d+)"', tl)
                        if m2:
                            color = m2.group(1)

                    for t2 in ["GroupTrack", "AudioTrack", "ReturnTrack", "MidiTrack", "MainTrack"]:
                        if "<" + t2 + " " in tl:
                            depth += 1
                        if "</" + t2 + ">" in tl:
                            depth -= 1
                    j += 1

                tracks.append({
                    "type": tt,
                    "id": tid,
                    "name": name,
                    "color": color,
                    "start": i,
                    "end": j - 1
                })
                i = j
                break
        else:
            i += 1

    # Print summary
    type_counts = {}
    for t in tracks:
        type_counts[t["type"]] = type_counts.get(t["type"], 0) + 1

    print("\nTrack type counts:")
    for tt, count in type_counts.items():
        print("  " + tt + ": " + str(count))

    # Print first 10 and last 5 tracks
    print("\nFirst 10 tracks:")
    for t in tracks[:10]:
        print("  " + t["type"].ljust(12) + " | Id=" + t["id"].rjust(5) + " | Color=" + t["color"].rjust(3) + " | " + t["name"] + " (lines " + str(t["start"]) + "-" + str(t["end"]) + ")")

    print("\nLast 5 tracks:")
    for t in tracks[-5:]:
        print("  " + t["type"].ljust(12) + " | Id=" + t["id"].rjust(5) + " | Color=" + t["color"].rjust(3) + " | " + t["name"] + " (lines " + str(t["start"]) + "-" + str(t["end"]) + ")")

    # Check unique colors
    colors = set(t["color"] for t in tracks)
    print("\nUnique track colors: " + str(sorted(colors)))

    # Check if Session Time track has HOFA plugin
    session_time = None
    for t in tracks:
        if "session" in t["name"].lower() or "time" in t["name"].lower() or t == tracks[0]:
            session_time = t
            break

    if session_time:
        print("\nFirst track: '" + session_time["name"] + "' (lines " + str(session_time["start"]) + "-" + str(session_time["end"]) + ")")
        # Check for plugin references in first track
        for li in range(session_time["start"], min(session_time["start"] + 200, session_time["end"])):
            if "hofa" in lines[li].lower() or "HOFA" in lines[li] or "PluginDesc" in lines[li] or "PlugName" in lines[li]:
                print("  Line " + str(li) + ": " + lines[li].rstrip())

    # Print lines per track (to understand track size for duplication)
    sizes = [t["end"] - t["start"] for t in tracks if t["type"] == "AudioTrack"]
    if sizes:
        print("\nAudioTrack sizes: min=" + str(min(sizes)) + " max=" + str(max(sizes)) + " avg=" + str(sum(sizes) // len(sizes)))


if __name__ == "__main__":
    main()
