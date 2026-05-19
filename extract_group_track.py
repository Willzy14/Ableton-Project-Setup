"""Extract a GroupTrack XML block and an AudioTrack XML block from a real project."""
import gzip
import re
from pathlib import Path


def decompress_als(als_path):
    with gzip.open(als_path, "rb") as f:
        content = f.read().decode("utf-8")
    return content.splitlines(keepends=True)


als = Path(r"C:\Users\Carillon\Wired Masters Dropbox\Sam Wills\2.1. Finished Stem Mixes\2. Ongoing Stem Mixes\Ak1ra - The Way [Ramzi Karam] Project\Ak1ra - The Way [Ramzi Karam].als")
lines = decompress_als(als)

# Find first GroupTrack
for i, line in enumerate(lines):
    if "<GroupTrack " in line:
        start = i
        depth = 1
        j = i + 1
        while j < len(lines) and depth > 0:
            if "<GroupTrack " in lines[j]:
                depth += 1
            if "</GroupTrack>" in lines[j]:
                depth -= 1
            j += 1
        end = j

        print("=== GROUPTRACK (lines " + str(start) + "-" + str(end) + ", " + str(end - start) + " lines) ===")
        # Print first 80 lines
        for k in range(start, min(start + 80, end)):
            print(str(k).rjust(6) + " | " + lines[k].rstrip())
        if end - start > 80:
            print("... (" + str(end - start - 80) + " more lines)")
            # Print last 20 lines
            for k in range(max(end - 20, start + 80), end):
                print(str(k).rjust(6) + " | " + lines[k].rstrip())
        break

# Also check how TrackGroupId works on child tracks
print("\n\n=== CHILD TRACK TrackGroupId SECTION ===")
for i, line in enumerate(lines):
    if "<TrackGroupId" in line:
        for k in range(max(0, i - 2), min(len(lines), i + 3)):
            print(str(k).rjust(6) + " | " + lines[k].rstrip())
        print()
        break

# Also find the Tracks closing tag area
print("\n=== AREA AROUND </Tracks> ===")
for i, line in enumerate(lines):
    if "</Tracks>" in line:
        for k in range(max(0, i - 5), min(len(lines), i + 5)):
            print(str(k).rjust(6) + " | " + lines[k].rstrip())
        break
