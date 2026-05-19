"""Find the exact tempo location in the template."""
import gzip
import re
from pathlib import Path

als = Path(r"C:\Users\Carillon\Documents\Ableton\User Library\Templates\Ableton Project Set Up 250 Tracks.als")
with gzip.open(als, "rb") as f:
    content = f.read().decode("utf-8")
lines = content.splitlines(keepends=True)

for i, line in enumerate(lines):
    if "<MainTrack " in line or "<MainTrack>" in line:
        print("MainTrack starts at line " + str(i))
        # Find Tempo section
        for j in range(i, min(i + 200, len(lines))):
            if "Tempo" in lines[j] or "tempo" in lines[j].lower():
                print(str(j).rjust(6) + " | " + lines[j].rstrip())
            if "Manual" in lines[j] and j > i and j < i + 50:
                print(str(j).rjust(6) + " | " + lines[j].rstrip())
        break
