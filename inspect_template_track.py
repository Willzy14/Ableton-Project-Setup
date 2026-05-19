"""Inspect an empty audio track from the template to find where clips and colors go."""
import gzip
import re
from pathlib import Path

als = Path(r"C:\Users\Carillon\Documents\Ableton\User Library\Templates\Ableton Project Set Up 250 Tracks.als")
with gzip.open(als, "rb") as f:
    content = f.read().decode("utf-8")
lines = content.splitlines(keepends=True)

# Track 2 (first empty audio track) starts at line 4252, ends at 4740
# Print key structural lines
track_start = 4252
track_end = 4740

print("=== EMPTY AUDIO TRACK (lines " + str(track_start) + "-" + str(track_end) + ") ===")
for i in range(track_start, track_end + 1):
    line = lines[i]
    stripped = line.strip()
    # Show structural lines
    if any(kw in stripped for kw in [
        "<AudioTrack", "</AudioTrack>", "EffectiveName", "UserName",
        "<Color ", "TrackGroupId", "<Events", "</Events>",
        "ArrangerAutomation", "<Sample>", "</Sample>",
        "MainSequencer", "FreezeSequencer",
        "IsWarped", "WarpMode", "FileRef",
        "<Tempo>", "Manual Value",
    ]):
        print(str(i).rjust(6) + " | " + line.rstrip())

# Also find the Events tag specifically
print("\n=== EVENTS SECTION (where clips go) ===")
for i in range(track_start, track_end + 1):
    if "Events" in lines[i]:
        for k in range(max(track_start, i - 3), min(track_end + 1, i + 4)):
            print(str(k).rjust(6) + " | " + lines[k].rstrip())
        print()
