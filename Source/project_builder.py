"""Orchestrator — takes a stem folder and produces a complete Ableton project.

Usage:
    python project_builder.py <stem_folder> <artist> <title> <label> <bpm>

Example:
    python project_builder.py "./stems" "Ak1ra" "The Way" "Ramzi Karam" 122
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from stem_classifier import (classify_stems, classify_stem, apply_track_names,
                             find_dry_stems, CATEGORIES)
from als_patcher import (patch_project, find_audio_regions, CLIP_START_BEATS,
                         SILENCE_FLOOR_DB)
from bpm_detector import detect_bpm
from bounce import sum_stems_to_wav
from stem_analysis import audio_label, find_group_buses
from versions import detect_versions, element_key

VERSION_GAP_BARS = 16   # gap between version sections on the timeline

CONFIG_PATH = Path(__file__).resolve().parents[1] / "Config" / "project_builder.json"
DEFAULT_TEMPLATE_PATH = Path(r"C:\Users\Carillon\Documents\Ableton\User Library\Templates\Ableton Project Set Up 250 Tracks.als")

# Colour for the reference tracks at the bottom (flat bounce + any supplied
# ref/master). 14 = red — Sam wants the reference tracks red.
REF_TRACK_COLOR = 14

# Colour for detected group-bus / sub-mix stems — parked muted at the very
# bottom, below the references. 2 = a peach/warm tone (Ableton palette index).
# If it's not the peach you want, change this number — the palette is a 14x5
# grid, indices 0-69 left-to-right, top-to-bottom.
BUS_TRACK_COLOR = 2

# Colour for the parked "Dry" group (the dry half of any wet/dry pair, kept
# muted underneath the wet for recall). 37 = grey — reads as inactive/parked.
DRY_GROUP_COLOR = 37

# Colour for empty/silent stems — a stem with no audio in it, moved to the very
# bottom with its own colour so it's obviously a dead export. 12 = a distinct
# tone; change the index if you'd prefer another (palette is 0-69).
SILENT_TRACK_COLOR = 12
DEFAULT_OUTPUT_BASE = Path(r"C:\Users\Carillon\Wired Masters Dropbox\Sam Wills\0.1---GIT HUB---\Ableton Project Setup")

# Backwards-compatible names for older scripts importing these constants.
TEMPLATE_PATH = DEFAULT_TEMPLATE_PATH
OUTPUT_BASE = DEFAULT_OUTPUT_BASE

# Audio-content classifier for stems the filename classifier can't name
# (Demucs + Whisper). Run as a subprocess so the CUDA context / any failure
# stays isolated from the build.
ML_SCRIPT = Path(__file__).parent / "audio_ml_classify.py"


def _load_project_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _configured_path(env_name, config_key, default):
    env_value = os.environ.get(env_name)
    if env_value:
        return Path(env_value)
    config_value = _load_project_config().get(config_key)
    if config_value:
        return Path(config_value)
    return Path(default)


def get_template_path():
    return _configured_path("ABLETON_TEMPLATE_PATH", "template_path", DEFAULT_TEMPLATE_PATH)


def get_output_base():
    return _configured_path("ABLETON_OUTPUT_BASE", "output_base", DEFAULT_OUTPUT_BASE)


def get_ml_python_exe():
    env_value = os.environ.get("PYTHON_ML_EXE")
    if env_value:
        return env_value
    return _load_project_config().get("python_ml_exe") or None


def get_enable_ml_classifier():
    env_value = os.environ.get("ENABLE_ML_CLASSIFIER")
    if env_value is not None:
        return env_value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(_load_project_config().get("enable_ml_classifier", True))


def detect_project_bpm(classified):
    """Auto-detect BPM from the cleanest grid-locking rhythmic stem.

    Scores every kick/drum/bass candidate instead of trusting the first result.
    Prefer BPMs that multiple credible stems agree on, then choose the cleanest
    grid lock inside that consensus group. This catches packs like Moby where
    the kick is syncopated but snare/hat stems land exactly on the grid.
    Returns (result_dict, source_path) or (None, None) if nothing detectable.
    """
    candidates = []
    for cat in ("kick", "drums", "bass"):
        candidates.extend(classified.get(cat, []))
    scored = []
    for f in candidates:
        try:
            result = detect_bpm(f)
        except Exception:  # noqa: BLE001 - a bad stem should not abort the build
            result = None
        if result:
            n_onsets = max(result.get("n_onsets", 0), 1)
            inlier_ratio = result.get("n_inliers", 0) / n_onsets
            residual = result.get("residual_ms")
            residual = 999.0 if residual is None else float(residual)
            quality = (inlier_ratio, -residual, result.get("n_inliers", 0))
            credible = inlier_ratio >= 0.5 and residual <= 5.0
            scored.append({
                "bpm_key": result.get("bpm_rounded"),
                "credible": credible,
                "quality": quality,
                "result": result,
                "source": f,
            })
    if not scored:
        return None, None
    consensus_counts = {}
    for item in scored:
        if item["credible"]:
            consensus_counts[item["bpm_key"]] = consensus_counts.get(item["bpm_key"], 0) + 1
    best = max(
        scored,
        key=lambda item: (
            consensus_counts.get(item["bpm_key"], 0),
            1 if item["credible"] else 0,
            item["quality"],
        ),
    )
    return best["result"], best["source"]


def _version_alignment_sec(bpm_result):
    """Return the physical onset used to align a version to the timeline."""
    return bpm_result.get("first_actual_onset_sec", bpm_result.get("first_beat_sec", 0.0))


def _detect_version_alignment_sec(mix_stems):
    """Choose the cleanest kick/drum source for multi-version alignment."""
    for preferred_categories in (("kick",), ("drums",)):
        scored = []
        for stem in mix_stems:
            if stem.get("category") not in preferred_categories:
                continue
            try:
                result = detect_bpm(stem["file_path"])
            except Exception:  # noqa: BLE001
                result = None
            if not result:
                continue
            n_onsets = max(result.get("n_onsets", 0), 1)
            inlier_ratio = result.get("n_inliers", 0) / n_onsets
            residual = result.get("residual_ms")
            residual = 999.0 if residual is None else float(residual)
            scored.append((inlier_ratio, -residual, result.get("n_inliers", 0), result))
        if scored:
            return _version_alignment_sec(max(scored, key=lambda item: item[:3])[3])
    return 0.0


def _detect_version_stack_anchor_sec(mix_stems, project_bpm):
    """Find the source-time downbeat used as the start of a later version stack.

    Prefer the earliest kick-layer onset that agrees with the project BPM. This
    keeps stacks together while avoiding the dry-kick-only problem: in Fallon the
    dry kick enters much later, but the processed kick layer marks the radio
    edit's musical start.
    """
    def _is_named_kick(stem):
        return "kick" in stem["file_path"].stem.lower()

    buckets = (
        lambda stem: _is_named_kick(stem),
        lambda stem: stem.get("category") == "kick",
        lambda stem: stem.get("category") == "drums",
    )
    for matches_bucket in buckets:
        candidates = []
        for stem in mix_stems:
            if not matches_bucket(stem):
                continue
            try:
                result = detect_bpm(stem["file_path"])
            except Exception:  # noqa: BLE001
                result = None
            if not result:
                continue
            rounded = result.get("bpm_rounded")
            if rounded is not None and abs(float(rounded) - float(project_bpm)) > 1.0:
                continue
            n_onsets = max(result.get("n_onsets", 0), 1)
            inlier_ratio = result.get("n_inliers", 0) / n_onsets
            residual = result.get("residual_ms")
            residual = 999.0 if residual is None else float(residual)
            if inlier_ratio < 0.5 or residual > 15.0:
                continue
            candidates.append(_version_alignment_sec(result))
        if candidates:
            return min(candidates)
    return 0.0


def _next_phrase_boundary(beat, phrase_bars=32):
    phrase_beats = phrase_bars * 4
    return math.ceil(beat / phrase_beats) * phrase_beats


def _ml_classify_unknowns(paths, use_whisper=True, python_exe=None):
    """Classify filename-unknown stems by audio content (Demucs + Whisper).

    Runs Source/audio_ml_classify.py as a subprocess (separate CUDA context,
    PYTHON_JIT=0). Returns {Path: result_dict}; an empty dict if ML is
    unavailable or errors, so the caller can fall back to placing them in music.
    """
    if not paths:
        return {}
    python_exe = python_exe or get_ml_python_exe() or sys.executable
    work = Path(tempfile.mkdtemp(prefix="als_ml_"))
    in_json = work / "in.json"
    out_json = work / "out.json"
    with open(in_json, "w", encoding="utf-8") as fh:
        json.dump([str(p) for p in paths], fh)
    cmd = [python_exe, str(ML_SCRIPT), "--in", str(in_json), "--out", str(out_json)]
    if not use_whisper:
        cmd.append("--no-whisper")
    env = dict(os.environ)
    env["PYTHON_JIT"] = "0"
    try:
        subprocess.run(cmd, env=env, check=True)
        with open(out_json, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception as e:  # noqa: BLE001 — ML is best-effort; never abort the build
        print("  ML classification unavailable (" + repr(e) + "); unknowns -> music")
        return {}
    return {p: raw[str(p)] for p in paths if str(p) in raw}


def _write_ml_report(report_path, ordered_paths, ml_results):
    """Write a human-readable report of every audio-classified (unnamed) stem."""
    lines = [
        "ML Classification Report",
        "=" * 60,
        "Stems with no recognisable filename, classified by audio content",
        "(Demucs source separation; Whisper confirms vocals via lyrics).",
        "",
        "drums/bass/other/vocals = energy fraction in each Demucs bin.",
        "'other' maps to MUSIC. FX has no Demucs bin so it lands in MUSIC.",
        "full_mix? = energy spread across all four bins (possible mix/ref) - review.",
        "",
        str(len(ordered_paths)) + " stems classified:",
        "",
    ]
    by_cat = {}
    for p in ordered_paths:
        rec = ml_results.get(p)
        cat = (rec.get("category") if rec else None) or "music"
        by_cat.setdefault(cat, []).append((p, rec))
    for cat in ("drums", "bass", "music", "vocals"):
        items = by_cat.get(cat)
        if not items:
            continue
        lines.append("[" + cat.upper() + "]")
        for p, rec in items:
            if not rec:
                lines.append("  %-38s (fallback - ML unavailable)" % p.name[:38])
                continue
            fr = rec.get("fractions", {})
            flag = "  full_mix?" if rec.get("full_mix_like") else ""
            lines.append("  %-38s conf %.2f  d/b/o/v %.2f/%.2f/%.2f/%.2f%s" % (
                p.name[:38], rec.get("confidence", 0.0),
                fr.get("drums", 0), fr.get("bass", 0), fr.get("other", 0),
                fr.get("vocals", 0), flag))
            if rec.get("whisper_text"):
                lines.append("      whisper (%d words): \"%s\"" % (
                    rec.get("whisper_words", 0), rec["whisper_text"][:90]))
        lines.append("")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def build_project(stem_folder, artist, title, label, bpm=None, output_base=None,
                  use_ml=None, project_name=None):
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
        output_base = get_output_base()
    output_base = Path(output_base)
    if use_ml is None:
        use_ml = get_enable_ml_classifier()

    versions = detect_versions(stem_folder)
    if versions:
        return build_multiversion_project(
            versions, artist, title, label, bpm, output_base, use_ml=use_ml
        )

    if project_name is None:
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
        if use_ml:
            print("\n" + str(len(unclassified)) + " stems have no recognisable "
                  "name — classifying by audio content (Demucs + Whisper)...")
        else:
            print("\nWARNING — " + str(len(unclassified))
                  + " unclassified stems (ML off; placed as music):")
        ml_results = _ml_classify_unknowns(unclassified) if use_ml else {}
        for f in unclassified:
            rec = ml_results.get(f)
            cat = (rec.get("category") if rec else None) or "music"
            classified.setdefault(cat, []).append(f)
        _write_ml_report(project_folder / "ML Classification Report.txt",
                         unclassified, ml_results)
        if use_ml:
            n_ml = sum(1 for f in unclassified
                       if ml_results.get(f) and ml_results[f].get("category"))
            print("  audio-classified " + str(n_ml) + "/" + str(len(unclassified))
                  + " stems -> see 'ML Classification Report.txt'")
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
            regions, peak_db = find_audio_regions(
                dest, head_sec=2.0 if cat == "fx" else 0.0, return_peak=True)
            stems.append({
                "name": f.stem,
                "category": cat,
                "color": color,
                "file_path": dest,
                "rel_path": "Audio/" + f.name,
                "regions": regions,
                "silent": peak_db < SILENCE_FLOOR_DB,
            })

    # --- Empty/silent stems --------------------------------------------------
    # A stem with no audio in it (peak below the silence floor) is moved to the
    # very bottom and given its own colour so it's obviously a dead export.
    # Pulled out of the working layout and the flat-ref sum (it adds nothing).
    silent_tracks = []
    if any(s.get("silent") for s in stems):
        silent_stems = [s for s in stems if s.get("silent")]
        stems = [s for s in stems if not s.get("silent")]
        print("\nEmpty stems (no audio) — moved to the bottom, own colour:")
        for s in silent_stems:
            print("  " + s["file_path"].name)
            s["category"] = "silent"
            s["color"] = SILENT_TRACK_COLOR
        silent_tracks = silent_stems

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

    # --- Wet/dry (VOCALS ONLY) ------------------------------------------------
    # Per Sam, the wet/dry rule applies ONLY to vocals, and only when the same
    # vocal is supplied as an explicit pair — one stem says WET, one says DRY.
    # Keep WET on (normal working track) and park the DRY copy in a muted "Dry"
    # group underneath for recall, OUT of the flat-ref sum (summing wet+dry of
    # one element double-counts it).
    vocal_files = [s["file_path"] for s in stems if s["category"] == "vocals"]
    dry_set = set(find_dry_stems(vocal_files))
    dry_tracks = []
    if dry_set:
        dry_stems = [s for s in stems if s["file_path"] in dry_set]
        stems = [s for s in stems if s["file_path"] not in dry_set]
        print("\nWet/dry: these are the DRY half of a pair — kept OUT of the "
              "flat-ref sum, parked (muted) in a 'Dry' group underneath:")
        for s in dry_stems:
            print("  " + s["file_path"].name)
        dry_tracks = dry_stems

    apply_track_names(stems)
    for s in stems:
        s["clip_name"] = s["file_path"].stem   # clip label = original source filename
        s["name"] = s["display_name"]          # track label = simplified display name

    if dry_tracks:
        apply_track_names(dry_tracks)
        for s in dry_tracks:
            s["clip_name"] = s["file_path"].stem
            s["name"] = s["display_name"]
            s["group_key"] = "dry"             # one shared run -> one "Dry" group
            s["group_name"] = "Dry"
            s["group_muted"] = True            # group muted = whole dry submix off
            s["group_unfolded"] = False        # collapsed: tucked away
            s["group_color"] = DRY_GROUP_COLOR

    if silent_tracks:
        apply_track_names(silent_tracks)
        for s in silent_tracks:
            s["clip_name"] = s["file_path"].stem
            s["name"] = s["display_name"]

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

    all_stems = stems + dry_tracks + ref_tracks + bus_tracks + silent_tracks

    print("Classification summary:")
    cat_counts = {}
    for s in stems:
        cat_counts[s["category"]] = cat_counts.get(s["category"], 0) + 1
    for cat in sorted(cat_counts.keys(), key=lambda c: CATEGORIES[c]["order"]):
        print("  " + cat.upper() + ": " + str(cat_counts[cat]) + " stems")
    if dry_tracks:
        print("  DRY (parked, muted group): " + str(len(dry_tracks)) + " stems")
    print("  REF TRACKS: " + str(len(ref_tracks)) + " (flat bounce + "
          + str(len(references)) + " supplied)")
    if silent_tracks:
        print("  SILENT (empty, bottom, own colour): " + str(len(silent_tracks)) + " stems")
    if bus_tracks:
        print("  GROUP BUSES: " + str(len(bus_tracks)) + " (parked muted at bottom)")
    print("  TOTAL TRACKS: " + str(len(all_stems)) + " (+ Session Time)")

    als_path = project_folder / (project_name + ".als")
    print("\nPatching template...")
    patch_project(
        template_path=get_template_path(),
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


def _process_version_files(files, version_audio_dir, rel_prefix, use_ml=True,
                           ml_report_path=None):
    """Classify + region-detect + bus/full-mix-detect ONE version's files.

    Copies files into version_audio_dir. Returns (mix_stems, ref_stems,
    bus_stems); each dict carries element_key, orig_name, file_path, rel_path,
    plus (mix/bus) category, color, regions.
    """
    classified = {}
    references = []
    unclassified = []
    for f in files:
        cat, is_ref = classify_stem(f.name)
        if is_ref:
            references.append(f)
        elif cat:
            classified.setdefault(cat, []).append(f)
        else:
            unclassified.append(f)

    music = classified.get("music", [])
    fulls = []
    for f in list(unclassified) + list(music):
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
        unclassified = [f for f in unclassified if f not in fulls]

    if unclassified:
        ml_results = _ml_classify_unknowns(unclassified) if use_ml else {}
        for f in unclassified:
            rec = ml_results.get(f)
            cat = (rec.get("category") if rec else None) or "music"
            classified.setdefault(cat, []).append(f)
        if ml_report_path is not None:
            _write_ml_report(ml_report_path, unclassified, ml_results)

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


def build_multiversion_project(versions, artist, title, label, bpm, output_base,
                               use_ml=True):
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
        report_path = project_folder / ("ML Classification Report - " + vname + ".txt")
        mix, refs, buses = _process_version_files(
            v["files"], audio_folder / vname, rel_prefix,
            use_ml=use_ml, ml_report_path=report_path,
        )
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
        p["first_beat_sec"] = _detect_version_stack_anchor_sec(p["mix"] + p["buses"], bpm)

    def _version_label(k):
        p = pv[k]
        blob = (p["name"] + " " + " ".join(s["orig_name"] for s in p["mix"][:5])).lower()
        if "radio" in blob:
            return "Radio Edit"
        if "dub" in blob:
            return "Dub"
        if "instrumental" in blob or " inst" in blob:
            return "Instrumental"
        return "Extended" if k == 0 else p["name"]

    # Later versions are placed on phrase slots first, then the whole stack is
    # nudged by the earliest credible kick-named layer so the kick sits on-grid.
    # The locator follows the physical stack start, not the kick anchor.
    offsets = []
    locators = []
    bar_cursor = float(CLIP_START_BEATS)
    for k, p in enumerate(pv):
        fb_beats = (p["first_beat_sec"] / 60.0) * bpm
        base_start = bar_cursor - fb_beats
        offsets.append(base_start)
        locators.append((base_start, _version_label(k)))
        content_end = base_start + p["length_beats"]
        next_start = content_end + VERSION_GAP_BARS * 4
        bar_cursor = (
            math.ceil(next_start / 4.0) * 4
            if k == 0 and len(pv) == 1
            else _next_phrase_boundary(next_start)
        )

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
    patch_project(template_path=get_template_path(), output_path=als_path,
                  stems=all_stems, bpm=bpm, project_audio_dir=audio_folder,
                  locators=locators)

    bars = [str(int((locators[i][0] - CLIP_START_BEATS) / 4) + 33) for i in range(len(pv))]
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
