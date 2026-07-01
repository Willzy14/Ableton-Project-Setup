"""Find tempo in the entire MainTrack section."""
import gzip
from pathlib import Path

als = Path(r"C:\Users\Carillon\Documents\Ableton\User Library\Templates\Ableton Project Set Up 250 Tracks.als")
with gzip.open(als, "rb") as f:
    content = f.read().decode("utf-8")
lines = content.splitlines(keepends=True)

# Find MainTrack range
mt_start = None
for i, line in enumerate(lines):
    if "<MainTrack " in line or "<MainTrack>" in line:
        mt_start = i
        break

if mt_start:
    print("MainTrack starts at " + str(mt_start))
    # Search for tempo within MainTrack
    for j in range(mt_start, len(lines)):
        if "</MainTrack>" in lines[j]:
            print("MainTrack ends at " + str(j))
            break
        stripped = lines[j].strip()
        if "empo" in stripped:  # Matches Tempo, tempo, AutoTempo
            # Print context
            for k in range(max(mt_start, j - 2), min(len(lines), j + 8)):
                print(str(k).rjust(6) + " | " + lines[k].rstrip())
            print()
