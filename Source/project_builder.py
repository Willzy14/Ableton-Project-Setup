"""Orchestrator — takes a stem folder and produces a complete Ableton project.

Usage:
    python project_builder.py <stem_folder> <artist> <title> <label> <bpm>

Example:
    python project_builder.py "./stems" "Ak1ra" "The Way" "Ramzi Karam" 122
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from stem_classifier import classify_stems, apply_track_names, CATEGORIES
from als_patcher import patch_project, find_audio_regions

TEMPLATE_PATH = Path(r"C:\Users\Carillon\Documents\Ableton\User Library\Templates\Ableton Project Set Up 250 Tracks.als")

FLAT_REF_COLOR = 14
OUTPUT_BASE = Path(r"C:\Users\Carillon\Wired Masters Dropbox\Sam Wills\0.1---GIT HUB---\Ableton Project Setup")


def build_project(stem_folder, artist, title, label, bpm, output_base=None):
    """Build a complete Ableton project from a folder of stems.

    Args:
        stem_folder: Path to folder containing stem audio files
        artist: Artist name
        title: Track title
        label: Label or contact name
        bpm: Project tempo (int or float)
        output_base: Where to create the project folder (defaults to OUTPUT_BASE)

    Returns:
        Path to the created project folder
    """
    stem_folder = Path(stem_folder)
    if output_base is None:
        output_base = OUTPUT_BASE
    output_base = Path(output_base)

    project_name = artist + " - " + title + " [" + label + "]"
    project_folder = output_base / (project_name + " Project")
    audio_folder = project_folder / "Audio"
    info_folder = project_folder / "Ableton Project Info"
    master_folder = project_folder / "MASTER RENDERS"

    project_folder.mkdir(parents=True, exist_ok=True)
    audio_folder.mkdir(exist_ok=True)
    info_folder.mkdir(exist_ok=True)
    master_folder.mkdir(exist_ok=True)

    print("Classifying stems...")
    classified, references, unclassified = classify_stems(stem_folder)

    if unclassified:
        print("\nWARNING — unclassified stems (will be placed as music):")
        for f in unclassified:
            print("  " + f.name)
        if "music" not in classified:
            classified["music"] = []
        classified["music"].extend(unclassified)
        unclassified = []

    print("\nCopying stems and detecting audio regions...")
    stems = []
    for cat in sorted(classified.keys(), key=lambda c: CATEGORIES[c]["order"]):
        color = CATEGORIES[cat]["color"]
        for f in classified[cat]:
            dest = audio_folder / f.name
            if not dest.exists():
                shutil.copy2(f, dest)
            regions = find_audio_regions(dest, head_sec=3.0 if cat == "fx" else 0.0)
            stems.append({
                "name": f.stem,
                "category": cat,
                "color": color,
                "file_path": dest,
                "rel_path": "Audio/" + f.name,
                "regions": regions,
            })

    apply_track_names(stems)
    for s in stems:
        s["name"] = s["display_name"]

    flat_ref_stems = []
    for s in stems:
        flat_ref_stems.append({
            "name": s["file_path"].stem,
            "category": "reference",
            "color": FLAT_REF_COLOR,
            "file_path": s["file_path"],
            "rel_path": s["rel_path"],
            "regions": s["regions"],
        })

    all_stems = stems + flat_ref_stems

    print("Classification summary:")
    cat_counts = {}
    for s in stems:
        cat_counts[s["category"]] = cat_counts.get(s["category"], 0) + 1
    for cat in sorted(cat_counts.keys(), key=lambda c: CATEGORIES[c]["order"]):
        print("  " + cat.upper() + ": " + str(cat_counts[cat]) + " stems")
    print("  FLAT REF: " + str(len(flat_ref_stems)) + " stems (duplicated)")
    print("  TOTAL TRACKS: " + str(len(all_stems)) + " (+ Session Time)")

    als_path = project_folder / (project_name + ".als")
    print("\nPatching template...")
    patch_project(
        template_path=TEMPLATE_PATH,
        output_path=als_path,
        stems=all_stems,
        bpm=float(bpm),
        project_audio_dir=audio_folder,
    )

    print("\nProject created:")
    print("  Folder: " + str(project_folder))
    print("  ALS:    " + str(als_path))
    print("  BPM:    " + str(bpm))
    print("  Tracks: " + str(len(all_stems)) + " + Session Time")

    return project_folder


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print("Usage: python project_builder.py <stem_folder> <artist> <title> <label> <bpm>")
        print('Example: python project_builder.py "./stems" "Ak1ra" "The Way" "Ramzi Karam" 122')
        sys.exit(1)

    build_project(
        stem_folder=sys.argv[1],
        artist=sys.argv[2],
        title=sys.argv[3],
        label=sys.argv[4],
        bpm=sys.argv[5],
    )
