"""Verify GroupTrack and ref track grouping in generated ALS."""
import gzip
import re
from pathlib import Path

als = Path(r"Test Output\TEST Ak1ra - The Way [Test Run] Project\TEST Ak1ra - The Way [Test Run].als")
with gzip.open(als, "rb") as f:
    content = f.read().decode("utf-8")
lines = content.splitlines()

for i, line in enumerate(lines):
    if "<GroupTrack " in line:
        m = re.search(r'Id="(\d+)"', line)
        gid = m.group(1) if m else "?"
        name = ""
        speaker = ""
        audio_out = ""
        unfolded = ""
        for j in range(i, min(i + 60, len(lines))):
            if "<EffectiveName" in lines[j]:
                m2 = re.search(r'Value="([^"]*)"', lines[j])
                if m2:
                    name = m2.group(1)
            if "<Speaker>" in lines[j]:
                for k in range(j, min(j + 5, len(lines))):
                    if "<Manual" in lines[k]:
                        m2 = re.search(r'Value="([^"]*)"', lines[k])
                        if m2:
                            speaker = m2.group(1)
            if "<AudioOutputRouting>" in lines[j]:
                for k in range(j, min(j + 5, len(lines))):
                    if "<Target" in lines[k]:
                        m2 = re.search(r'Value="([^"]*)"', lines[k])
                        if m2:
                            audio_out = m2.group(1)
            if "<TrackUnfolded" in lines[j]:
                m2 = re.search(r'Value="([^"]*)"', lines[j])
                if m2:
                    unfolded = m2.group(1)
        print("GroupTrack: Id=" + gid + ", Name=" + name + ", Speaker=" + speaker + ", Output=" + audio_out + ", Unfolded=" + unfolded)

print("\nRef track grouping:")
for i, line in enumerate(lines):
    if "<AudioTrack " in line:
        m = re.search(r'Id="(\d+)"', line)
        tid = m.group(1) if m else ""
        name = ""
        color = ""
        group_id = ""
        for j in range(i, min(i + 40, len(lines))):
            if "<EffectiveName" in lines[j] and not name:
                m2 = re.search(r'Value="([^"]*)"', lines[j])
                if m2:
                    name = m2.group(1)
            if "<Color Value=" in lines[j] and not color and j < i + 30:
                m2 = re.search(r'Value="(\d+)"', lines[j])
                if m2:
                    color = m2.group(1)
            if "<TrackGroupId" in lines[j]:
                m2 = re.search(r'Value="([^"]*)"', lines[j])
                if m2:
                    group_id = m2.group(1)
                break
        if color == "14":
            print("  " + name.ljust(30) + " color=" + color + " TrackGroupId=" + group_id)

print("\nClip counts per track:")
in_track = False
track_name = ""
clip_count = 0
for i, line in enumerate(lines):
    if "<AudioTrack " in line:
        in_track = True
        track_name = ""
        clip_count = 0
    if in_track and "<EffectiveName" in line and not track_name:
        m = re.search(r'Value="([^"]*)"', line)
        if m:
            track_name = m.group(1)
    if in_track and "<AudioClip " in line:
        clip_count += 1
    if "</AudioTrack>" in line and in_track:
        if clip_count > 0:
            print("  " + track_name.ljust(30) + " clips=" + str(clip_count))
        in_track = False
