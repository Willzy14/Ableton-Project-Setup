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
from bpm_detector import detect_bpm
from bounce import sum_stems_to_wav

TEMPLATE_PATH = Path(r"C:\Users\Carillon\Documents\Ableton\User Library\Templates\Ableton Project Set Up 250 Tracks.als")

# Colour for the reference tracks at the bottom (flat bounce + any supplied
# ref/master). 14 = red — Sam wants the reference tracks red.
REF_TRACK_COLOR = 14
OUTPUT_BASE = Path(r"C:\Users\Carillon\Wired Masters Dropbox\Sam Wills\0.1---GIT HUB---\Ableton Project Setup")


def detect_project_bpm(classified):
    """Auto-detect BPM from the most reliable percussive stem available.

    Tries kick first (cleanest 4/4 pulse), then a full drums stem, then bass.
    Returns (result_dict, source_path) or (None, None) if nothing detectable.
    """
    candidates = []
    for cat in ("kick", "drums", "bass"):
        candidates.extend(classified.get(cat, []))
    for f in candidates:
        try:
            result = detect_bpm(f)
        except Exception:  # noqa: BLE001 — a bad stem shouldn't abort the build
            result = None
        if result:
            return result, f
    return None, None


def build_project(stem_folder, artist, title, label, bpm=None, output_base=None):
    """Build a complete Ableton project from a folder of stems.

    Args:
        stem_folder: Path to folder containing stem audio files
        artist: Artist name
        title: Track title
        label: Label or contact name
        bpm: Project tempo (int/float). Pass None or "auto" to detect it from
            the kick/percussion stems.
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

    if bpm is None or str(bpm).lower() == "auto":
        print("\nDetecting BPM from percussion...")
        result, src = detect_project_bpm(classified)
        if result is None:
            raise ValueError(
                "Could not auto-detect BPM (no usable kick/drums/bass stem). "
                "Pass the BPM explicitly as the 5th argument."
            )
        bpm = result["bpm_rounded"]
        res_ms = result["residual_ms"]
        warn = "" if (res_ms is not None and res_ms <= 5.0) else "  <-- LOW CONFIDENCE, verify"
        print("  " + str(bpm) + " BPM from " + src.name
              + " (raw " + ("%.2f" % result["bpm"]) + ", "
              + str(result["n_inliers"]) + "/" + str(result["n_onsets"])
              + " kicks, +/-" + str(res_ms) + "ms)" + warn)

    print("\nCopying stems and detecting audio regions...")
    stems = []
    for cat in sorted(classified.keys(), key=lambda c: CATEGORIES[c]["order"]):
        color = CATEGORIES[cat]["color"]
        for f in classified[cat]:
            dest = audio_folder / f.name
            if not dest.exists():
                shutil.copy2(f, dest)
            # FX (risers/uplifters build from near-silence) get a lead-in so
            # the ramp isn't trimmed; everything else trims tight at the front.
            regions = find_audio_regions(dest, head_sec=2.0 if cat == "fx" else 0.0)
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
        s["clip_name"] = s["file_path"].stem   # clip label = original source filename
        s["name"] = s["display_name"]          # track label = simplified display name

    # Tag groupable categories (2+ stems) so patch_project wraps them in a
    # GroupTrack. kick/bass/sends never group (CATEGORIES[cat]["group"] is False).
    group_names = {"drums": "Drums", "bass": "Bass", "music": "Music",
                   "vocals": "Vox", "fx": "FX"}
    cat_counts = {}
    for s in stems:
        cat_counts[s["category"]] = cat_counts.get(s["category"], 0) + 1
    for s in stems:
        cat = s["category"]
        if CATEGORIES[cat]["group"] and cat_counts[cat] >= 2:
            s["group_key"] = cat
            s["group_name"] = group_names.get(cat, cat.title())

    # --- Reference tracks at the bottom -------------------------------------
    # Always print our own flat bounce of the mix stems (a supplied "ref"/
    # "riff"/master file can't be trusted to equal the stem sum). Supplied
    # references are kept as separate match tracks, excluded from the sum.
    ref_tracks = []

    for f in references:
        dest = audio_folder / f.name
        if not dest.exists():
            shutil.copy2(f, dest)
        ref_tracks.append({
            "name": f.stem,
            "clip_name": f.stem,
            "category": "reference",
            "color": REF_TRACK_COLOR,
            "file_path": dest,
            "rel_path": "Audio/" + f.name,
            "regions": None,
        })

    print("\nBouncing flat reference (summing " + str(len(stems)) + " mix stems)...")
    bounce_name = project_name + " FLAT REF.wav"
    bounce_path = audio_folder / bounce_name
    summary = sum_stems_to_wav([s["file_path"] for s in stems], bounce_path)
    print("  " + str(summary["n_summed"]) + " stems summed -> " + bounce_name
          + " (peak " + ("%.2f" % summary["peak"]) + ")")
    if summary["skipped"]:
        print("  WARNING skipped (sample-rate mismatch): " + ", ".join(summary["skipped"]))
    ref_tracks.append({
        "name": "FLAT REF",
        "clip_name": bounce_path.stem,
        "category": "reference",
        "color": REF_TRACK_COLOR,
        "file_path": bounce_path,
        "rel_path": "Audio/" + bounce_name,
        "regions": None,
    })

    all_stems = stems + ref_tracks

    print("Classification summary:")
    cat_counts = {}
    for s in stems:
        cat_counts[s["category"]] = cat_counts.get(s["category"], 0) + 1
    for cat in sorted(cat_counts.keys(), key=lambda c: CATEGORIES[c]["order"]):
        print("  " + cat.upper() + ": " + str(cat_counts[cat]) + " stems")
    print("  REF TRACKS: " + str(len(ref_tracks)) + " (flat bounce + "
          + str(len(references)) + " supplied)")
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
    if len(sys.argv) < 5:
        print("Usage: python project_builder.py <stem_folder> <artist> <title> <label> [bpm]")
        print("  bpm is optional — omit it (or pass 'auto') to detect from the kick.")
        print('Example: python project_builder.py "./stems" "Ak1ra" "The Way" "Ramzi Karam" 122')
        print('Example: python project_builder.py "./stems" "Ak1ra" "The Way" "Ramzi Karam"')
        sys.exit(1)

    build_project(
        stem_folder=sys.argv[1],
        artist=sys.argv[2],
        title=sys.argv[3],
        label=sys.argv[4],
        bpm=sys.argv[5] if len(sys.argv) > 5 else None,
    )
