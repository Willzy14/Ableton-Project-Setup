"""Verify the generated ALS file has correct tracks, colors, and clips."""
import gzip
import re
from pathlib import Path

als = Path(r"C:\Users\Carillon\Wired Masters Dropbox\Sam Wills\0.1---GIT HUB---\Ableton Project Setup\Test Output\TEST Ak1ra - The Way [Test Run] Project\TEST Ak1ra - The Way [Test Run].als")

with gzip.open(als, "rb") as f:
    content = f.read().decode("utf-8")
lines = content.splitlines(keepends=True)
print("Total lines: " + str(len(lines)))

# Find tracks
tracks = []
i = 0
while i < len(lines):
    line = lines[i]
    for tt in ["AudioTrack", "MainTrack"]:
        if "<" + tt + " " in line or ("<" + tt + ">" in line and tt == "MainTrack"):
            name = ""
            color = ""
            has_clip = False
            clip_color = ""
            depth = 1
            j = i + 1
            while j < len(lines) and depth > 0:
                tl = lines[j]
                if "<EffectiveName" in tl and not name:
                    m = re.search(r'Value="([^"]*)"', tl)
                    if m:
                        name = m.group(1)
                if "<Color Value=" in tl and not color and j < i + 30:
                    m = re.search(r'Value="(\d+)"', tl)
                    if m:
                        color = m.group(1)
                if "<AudioClip " in tl:
                    has_clip = True
                    # Find clip color
                    for k in range(j, min(j + 20, len(lines))):
                        if "<Color Value=" in lines[k]:
                            m = re.search(r'Value="(\d+)"', lines[k])
                            if m:
                                clip_color = m.group(1)
                            break

                for t2 in ["AudioTrack", "MainTrack"]:
                    if "<" + t2 + " " in tl:
                        depth += 1
                    if "</" + t2 + ">" in tl:
                        depth -= 1
                j += 1

            tracks.append({
                "type": tt, "name": name, "color": color,
                "has_clip": has_clip, "clip_color": clip_color,
            })
            i = j
            break
    else:
        i += 1

print("\nTrack count: " + str(len(tracks)))
print("\n  {:3s} | {:12s} | {:6s} | {:8s} | {:6s} | {}".format(
    "#", "Type", "TrkCol", "HasClip", "ClpCol", "Name"))
print("  " + "-" * 70)
for idx, t in enumerate(tracks):
    clip_str = "YES" if t["has_clip"] else ""
    print("  {:3d} | {:12s} | {:>6s} | {:8s} | {:>6s} | {}".format(
        idx + 1, t["type"], t["color"], clip_str, t["clip_color"], t["name"]))

# Check tempo
for i, line in enumerate(lines):
    if "<MainTrack " in line or "<MainTrack>" in line:
        for j in range(i, min(i + 100, len(lines))):
            if "<Tempo>" in lines[j]:
                for k in range(j, min(j + 10, len(lines))):
                    if "Manual Value" in lines[k]:
                        print("\nGlobal tempo: " + lines[k].strip())
                        break
                break
        break
