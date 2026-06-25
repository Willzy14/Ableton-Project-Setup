"""Orchestrator — takes a stem folder and produces a complete Ableton project.

Usage:
    python project_builder.py <stem_folder> <artist> <title> <label> <bpm>

Example:
    python project_builder.py "./stems" "Ak1ra" "The Way" "Ramzi Karam" 122
"""
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from stem_classifier import classify_stems, classify_stem, apply_track_names, CATEGORIES
from als_patcher import patch_project, find_audio_regions, CLIP_START_BEATS
from bpm_detector import detect_bpm
from bounce import sum_stems_to_wav
from stem_analysis import audio_label, find_group_buses
from versions import detect_versions, element_key

VERSION_GAP_BARS = 16   # gap between version sections on the timeline

TEMPLATE_PATH = Path(r"C:\Users\Carillon\Documents\Ableton\User Library\Templates\Ableton Project Set Up 250 Tracks.als")

# Colour for the reference tracks at the bottom (flat bounce + any supplied
# ref/master). 14 = red — Sam wants the reference tracks red.
REF_TRACK_COLOR = 14

# Colour for detected group-bus / sub-mix stems — parked muted at the very
# bottom, below the references. 2 = a peach/warm tone (Ableton palette index).
# If it's not the peach you want, change this number — the palette is a 14x5
# grid, indices 0-69 left-to-right, top-to-bottom.
BUS_TRACK_COLOR = 2
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

    versions = detect_versions(stem_folder)
    if versions:
        return build_multiversion_project(versions, artist, title, label, bpm, output_base)

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

    # Audio-content safety net (numpy): a file filenames couldn't place
    # (music/unclassified) but that ANALYSES as a full mix / master / sub-bounce
    # is moved to references — so it is kept OUT of the flat bounce (summing a
    # whole mix into the reference would pollute it). No-op without numpy.
    suspects = list(unclassified) + list(classified.get("music", []))
    full_mixes = []
    for f in suspects:
        try:
            if audio_label(f) == "full_mix":
                full_mixes.append(f)
        except Exception:  # noqa: BLE001 — a bad file shouldn't abort the build
            pass
    if full_mixes:
        print("\nAudio analysis: these read as full mixes — kept OUT of the "
              "flat-ref sum, placed as red reference tracks:")
        for f in full_mixes:
            print("  " + f.name)
        references = list(references) + full_mixes
        if "music" in classified:
            classified["music"] = [f for f in classified["music"] if f not in full_mixes]
            if not classified["music"]:
                del classified["music"]
        unclassified = [f for f in unclassified if f not in full_mixes]

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

    # --- Group-bus detection -------------------------------------------------
    # A stem that is the (near-exact) sum of >=2 other stems is a group/sub-mix
    # bounce left in among the individual stems. Summing it double-counts and
    # makes everything sound wrong on play. Pull these out: keep them in the
    # project (own colour, parked muted at the bottom) but OUT of the flat-ref
    # sum and OUT of the working layout. No-op without numpy.
    bus_tracks = []
    bus_paths = find_group_buses([s["file_path"] for s in stems])
    if bus_paths:
        buses = [s for s in stems if s["file_path"] in bus_paths]
        stems = [s for s in stems if s["file_path"] not in bus_paths]
        print("\nGroup-bus detection: these are a sum of other stems — kept OUT "
              "of the flat-ref sum, parked (muted, grey) at the bottom:")
        for s in buses:
            print("  " + s["file_path"].name)
            bus_tracks.append({
                "name": s["file_path"].stem,
                "clip_name": s["file_path"].stem,
                "category": "bus",
                "color": BUS_TRACK_COLOR,
                "file_path": s["file_path"],
                "rel_path": s["rel_path"],
                "regions": None,
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

    all_stems = stems + ref_tracks + bus_tracks

    print("Classification summary:")
    cat_counts = {}
    for s in stems:
        cat_counts[s["category"]] = cat_counts.get(s["category"], 0) + 1
    for cat in sorted(cat_counts.keys(), key=lambda c: CATEGORIES[c]["order"]):
        print("  " + cat.upper() + ": " + str(cat_counts[cat]) + " stems")
    print("  REF TRACKS: " + str(len(ref_tracks)) + " (flat bounce + "
          + str(len(references)) + " supplied)")
    if bus_tracks:
        print("  GROUP BUSES: " + str(len(bus_tracks)) + " (parked muted at bottom)")
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


def _process_version_files(files, version_audio_dir, rel_prefix):
    """Classify + region-detect + bus/full-mix-detect ONE version's files.

    Copies files into version_audio_dir. Returns (mix_stems, ref_stems,
    bus_stems); each dict carries element_key, orig_name, file_path, rel_path,
    plus (mix/bus) category, color, regions.
    """
    classified = {}
    references = []
    for f in files:
        cat, is_ref = classify_stem(f.name)
        if is_ref:
            references.append(f)
        elif cat:
            classified.setdefault(cat, []).append(f)
        else:
            classified.setdefault("music", []).append(f)

    music = classified.get("music", [])
    fulls = []
    for f in music:
        try:
            if audio_label(f) == "full_mix":
                fulls.append(f)
        except Exception:  # noqa: BLE001
            pass
    if fulls:
        references += fulls
        classified["music"] = [f for f in music if f not in fulls]
        if not classified["music"]:
            classified.pop("music", None)

    version_audio_dir.mkdir(parents=True, exist_ok=True)

    def _copy(f):
        dest = version_audio_dir / f.name
        if not dest.exists():
            shutil.copy2(f, dest)
        return dest

    mix_stems = []
    for cat in sorted(classified.keys(), key=lambda c: CATEGORIES[c]["order"]):
        color = CATEGORIES[cat]["color"]
        for f in classified[cat]:
            dest = _copy(f)
            regions = find_audio_regions(dest, head_sec=2.0 if cat == "fx" else 0.0)
            mix_stems.append({
                "element_key": element_key(f), "orig_name": f.stem,
                "category": cat, "color": color, "file_path": dest,
                "rel_path": rel_prefix + f.name, "regions": regions,
            })

    bus_paths = find_group_buses([s["file_path"] for s in mix_stems])
    bus_stems = [s for s in mix_stems if s["file_path"] in bus_paths]
    mix_stems = [s for s in mix_stems if s["file_path"] not in bus_paths]

    ref_stems = []
    for f in references:
        dest = _copy(f)
        ref_stems.append({"element_key": element_key(f), "orig_name": f.stem,
                          "file_path": dest, "rel_path": rel_prefix + f.name})
    return mix_stems, ref_stems, bus_stems


def build_multiversion_project(versions, artist, title, label, bpm, output_base):
    """Build a project from multiple versions (extended / radio edit / dub ...).

    Each element shares ONE track across versions; versions are laid out as
    sequential sections down the arrangement (VERSION_GAP_BARS between them),
    with a flat-ref bounce under each version.
    """
    project_name = artist + " - " + title + " [" + label + "]"
    project_folder = Path(output_base) / (project_name + " Project")
    audio_folder = project_folder / "Audio"
    for sub in ("Audio", "Ableton Project Info", "MASTER RENDERS"):
        (project_folder / sub).mkdir(parents=True, exist_ok=True)

    def _safe(name):
        return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "Version"

    print("Multi-version package: " + " | ".join(v["name"] for v in versions))

    pv = []
    for v in versions:
        vname = _safe(v["name"])
        rel_prefix = "Audio/" + vname + "/"
        print("\n[" + v["name"] + "] processing " + str(len(v["files"])) + " files...")
        mix, refs, buses = _process_version_files(v["files"], audio_folder / vname, rel_prefix)
        print("  mix=" + str(len(mix)) + " refs=" + str(len(refs)) + " buses=" + str(len(buses)))
        pv.append({"name": v["name"], "vname": vname, "rel_prefix": rel_prefix,
                   "vdir": audio_folder / vname, "mix": mix, "refs": refs, "buses": buses})

    if bpm is None or str(bpm).lower() == "auto":
        prim_classified = {}
        for s in pv[0]["mix"]:
            prim_classified.setdefault(s["category"], []).append(s["file_path"])
        result, src = detect_project_bpm(prim_classified)
        if result is None:
            raise ValueError("Could not auto-detect BPM; pass it explicitly.")
        bpm = result["bpm_rounded"]
        print("\nBPM " + str(bpm) + " (from " + src.name + ")")
    bpm = float(bpm)

    for p in pv:
        bounce_name = project_name + " " + p["vname"] + " FLAT REF.wav"
        bounce_path = p["vdir"] / bounce_name
        if p["mix"]:
            summary = sum_stems_to_wav([s["file_path"] for s in p["mix"]], bounce_path)
            p["bounce_path"] = bounce_path
            p["bounce_rel"] = p["rel_prefix"] + bounce_name
            print("  " + p["name"] + " flat bounce: " + str(summary["n_summed"]) + " stems")
        else:
            p["bounce_path"] = None
        max_end = 0.0
        for s in p["mix"]:
            for (_rs, _re) in (s["regions"] or []):
                max_end = max(max_end, _re)
        p["length_beats"] = (max_end / 60.0) * bpm

    offsets = [CLIP_START_BEATS]
    for k in range(1, len(pv)):
        offsets.append(offsets[k - 1] + pv[k - 1]["length_beats"] + VERSION_GAP_BARS * 4)

    primary = pv[0]
    for s in primary["mix"]:
        s["name"] = s["orig_name"]
    apply_track_names(primary["mix"])

    group_names = {"drums": "Drums", "bass": "Bass", "music": "Music",
                   "vocals": "Vox", "fx": "FX"}
    cat_counts = {}
    for s in primary["mix"]:
        cat_counts[s["category"]] = cat_counts.get(s["category"], 0) + 1

    all_stems = []
    track_by_elem = {}
    for s in primary["mix"]:
        track = {
            "name": s["display_name"], "clip_name": s["orig_name"],
            "category": s["category"], "color": s["color"],
            "file_path": s["file_path"], "rel_path": s["rel_path"],
            "regions": s["regions"], "base_start_beat": offsets[0], "extra_clips": [],
        }
        if CATEGORIES[s["category"]]["group"] and cat_counts[s["category"]] >= 2:
            track["group_key"] = s["category"]
            track["group_name"] = group_names.get(s["category"], s["category"].title())
        all_stems.append(track)
        track_by_elem[s["element_key"]] = track

    extra_only = []
    for k in range(1, len(pv)):
        for s in pv[k]["mix"]:
            ec = {"file_path": s["file_path"], "rel_path": s["rel_path"],
                  "regions": s["regions"], "start_beat": offsets[k], "clip_name": s["orig_name"]}
            t = track_by_elem.get(s["element_key"])
            if t:
                t["extra_clips"].append(ec)
            else:
                nt = {"name": s["orig_name"], "clip_name": s["orig_name"],
                      "category": s["category"], "color": s["color"],
                      "file_path": s["file_path"], "rel_path": s["rel_path"],
                      "regions": s["regions"], "base_start_beat": offsets[k], "extra_clips": []}
                extra_only.append(nt)
                track_by_elem[s["element_key"]] = nt
    all_stems += extra_only

    # FLAT REF: one track, a bounce clip per version at each version's offset
    if primary.get("bounce_path"):
        flat = {"name": "FLAT REF", "clip_name": primary["bounce_path"].stem,
                "category": "reference", "color": REF_TRACK_COLOR,
                "file_path": primary["bounce_path"], "rel_path": primary["bounce_rel"],
                "regions": None, "base_start_beat": offsets[0], "extra_clips": []}
        for k in range(1, len(pv)):
            if pv[k].get("bounce_path"):
                flat["extra_clips"].append({
                    "file_path": pv[k]["bounce_path"], "rel_path": pv[k]["bounce_rel"],
                    "regions": None, "start_beat": offsets[k],
                    "clip_name": pv[k]["bounce_path"].stem})
        all_stems.append(flat)

    # Supplied refs and group buses are SHARED across versions by element too
    # (extended + radio of the same ref/bus stack on one track), so the bottom
    # of the project lines up as neatly as the working tracks.
    def _shared(items_by_version, category, color):
        by_elem = {}
        out = []
        for k, p in enumerate(pv):
            for it in items_by_version(p):
                ek = it["element_key"]
                t = by_elem.get(ek)
                if t is not None:
                    t["extra_clips"].append({
                        "file_path": it["file_path"], "rel_path": it["rel_path"],
                        "regions": None, "start_beat": offsets[k],
                        "clip_name": it["orig_name"]})
                else:
                    t = {"name": it["orig_name"], "clip_name": it["orig_name"],
                         "category": category, "color": color,
                         "file_path": it["file_path"], "rel_path": it["rel_path"],
                         "regions": None, "base_start_beat": offsets[k], "extra_clips": []}
                    by_elem[ek] = t
                    out.append(t)
        return out

    all_stems += _shared(lambda p: p["refs"], "reference", REF_TRACK_COLOR)
    all_stems += _shared(lambda p: p["buses"], "bus", BUS_TRACK_COLOR)

    als_path = project_folder / (project_name + ".als")
    print("\nPatching template (" + str(len(all_stems)) + " tracks)...")
    patch_project(template_path=TEMPLATE_PATH, output_path=als_path,
                  stems=all_stems, bpm=bpm, project_audio_dir=audio_folder)

    bars = [str(int((offsets[i] - CLIP_START_BEATS) / 4) + 33) for i in range(len(pv))]
    print("\nMulti-version project created: " + str(project_folder))
    print("  BPM " + str(int(bpm)) + " | versions at bars: "
          + ", ".join(pv[i]["name"] + "=" + bars[i] for i in range(len(pv))))
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
