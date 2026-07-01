"""Extract a real AudioClip XML block to use as a clip template."""
import gzip
import re
from pathlib import Path


als = Path(r"C:\Users\Carillon\Wired Masters Dropbox\Sam Wills\2.1. Finished Stem Mixes\2. Ongoing Stem Mixes\Ak1ra - The Way [Ramzi Karam] Project\Ak1ra - The Way [Ramzi Karam].als")
with gzip.open(als, "rb") as f:
    content = f.read().decode("utf-8")
lines = content.splitlines(keepends=True)

# Find first AudioClip (from the kick track, track 2)
for i, line in enumerate(lines):
    if "<AudioClip " in line and i > 4000:
        start = i
        depth = 1
        j = i + 1
        while j < len(lines) and depth > 0:
            if "<AudioClip " in lines[j]:
                depth += 1
            if "</AudioClip>" in lines[j]:
                depth -= 1
            j += 1

        print("=== AUDIOCLIP (lines " + str(start) + "-" + str(j - 1) + ", " + str(j - start) + " lines) ===")
        for k in range(start, j):
            print(str(k).rjust(6) + " | " + lines[k].rstrip())
        break
