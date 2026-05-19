"""Test the stem classifier against real project folders."""
import sys
sys.path.insert(0, "Source")
from stem_classifier import classify_stems, CATEGORIES
from pathlib import Path

base = Path(r"C:\Users\Carillon\Wired Masters Dropbox\Sam Wills\2.1. Finished Stem Mixes")

test_folders = [
    base / "2. Ongoing Stem Mixes" / "Ak1ra - The Way [Ramzi Karam] Project" / "Audio",
    base / "2. Ongoing Stem Mixes" / "Eats Everything - Ms Noise [Black Book] Project" / "Audio",
    base / "2. Ongoing Stem Mixes" / "Noden - Disco [Sound Better] Project" / "Audio",
    base / "RILEY - False Reality [Good Company] Project" / "Audio",
    base / "Stephani B - Activ-8 (Come With Me) [Perfect Havoc] Project" / "Audio",
]

for folder in test_folders:
    if not folder.exists():
        print("SKIPPED: " + str(folder))
        continue

    print("=" * 70)
    print("FOLDER: " + folder.parent.name)
    print()

    classified, refs, unknown = classify_stems(folder)

    for cat, files in sorted(classified.items(), key=lambda x: CATEGORIES[x[0]]["order"]):
        color = CATEGORIES[cat]["color"]
        print("  " + cat.upper() + " (color " + str(color) + "):")
        for f in files:
            print("    " + f.name)

    if refs:
        print("  REFERENCES:")
        for f in refs:
            print("    " + f.name)

    if unknown:
        print("  UNCLASSIFIED:")
        for f in unknown:
            print("    " + f.name)

    print()
