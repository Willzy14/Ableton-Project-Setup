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
                             find_dry_stems, CATEGORIES, AUDIO_EXTENSIONS)
from als_patcher import (patch_project, find_audio_regions, CLIP_START_BEATS,
                         SILENCE_FLOOR_DB, get_wav_info)
from bpm_detector import detect_bpm
from bounce import sum_stems_to_wav
from stem_analysis import audio_label, find_group_buses, analysis_available
from versions import detect_versions, element_key

VERSION_GAP_BARS = 16   # gap between version sections on the timeline

# Categories whose working group is clustered into nested sub-groups (singer
# under Vox, Kit/Percussion under Drums, instrument families under Music).
SUBGROUP_CATEGORIES = ("vocals", "drums", "music")

CONFIG_PATH = Path(__file__).resolve().parents[1] / "Config" / "project_builder.json"
_TEMPLATE_NAME = "Ableton Project Set Up 250 Tracks.als"


def _first_existing(*paths):
    for p in paths:
        if p and Path(p).exists():
            return Path(p)
    return None


# Template: Carillon's User Library, else Sam's Mac User Library, else a copy
# checked into the repo (Templates/), else the Windows path as a last resort so
# the value is never None. get_template_path() adds the frozen-EXE bundle + a
# clear not-found error. Machine-specific values still come from config/env.
DEFAULT_TEMPLATE_PATH = _first_existing(
    Path(r"C:\Users\Carillon\Documents\Ableton\User Library\Templates") / _TEMPLATE_NAME,
    Path.home() / "Documents" / "Ableton" / "User Library" / "Templates" / _TEMPLATE_NAME,
    Path.home() / "Music" / "Ableton" / "User Library" / "Templates" / _TEMPLATE_NAME,
    Path(__file__).resolve().parents[1] / "Templates" / _TEMPLATE_NAME,
) or Path(r"C:\Users\Carillon\Documents\Ableton\User Library\Templates") / _TEMPLATE_NAME

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
# Updated/revised stems (from an 'updated stems' subfolder): placed right next to
# the original they replace, muted (off) and in their own colour so you can A/B
# them in the arrangement. 5 = a bright lime — reads as "new". Excluded from the
# flat-ref sum (it's a duplicate element).
UPDATED_TRACK_COLOR = 5
# External reference tracks (other artists' tracks from a 'ref' subfolder): laid
# to the RIGHT of the arrangement, routed to Ext. Out (bypasses the master),
# LEFT ON (audible) and given their own colour so you can A/B your mix against
# them. 26 = magenta — distinct from the red flat-ref.
REFCOMPARE_COLOR = 26
# Where built projects land by default. Sam's in-progress stem mixes live here,
# so a freshly set-up project belongs alongside them — and this keeps generated
# output OUT of the code repo (an env/config override still wins). CLI only; the
# Studio App uses its own configured output folder. Falls back to a home-relative
# path on a machine that isn't Carillon (e.g. Sam's Mac) so it's never an
# unwritable Windows path on the wrong OS.
def _default_output_base():
    carillon = Path(r"C:\Users\Carillon\Wired Masters Dropbox\Sam Wills\2. Ongoing Stem Mixes")
    if carillon.parent.exists():
        return carillon
    home = Path.home()
    mac = home / "Wired Masters Dropbox" / "Sam Wills" / "2. Ongoing Stem Mixes"
    if mac.parent.exists():
        return mac
    return home / "Downloads"


DEFAULT_OUTPUT_BASE = _default_output_base()

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
    # In a packaged EXE the template ALS is bundled alongside the code (see
    # Studio App/build_exe.py), so builds work on a machine without the
    # template in the User Library. An env/config override still wins.
    if getattr(sys, "frozen", False) and not os.environ.get("ABLETON_TEMPLATE_PATH"):
        bundled = Path(getattr(sys, "_MEIPASS", "")) / "template.als"
        if bundled.exists():
            return bundled
    # An explicit env override is honoured verbatim (the user chose it).
    env = os.environ.get("ABLETON_TEMPLATE_PATH")
    if env:
        return Path(env)
    p = _configured_path("ABLETON_TEMPLATE_PATH", "template_path", DEFAULT_TEMPLATE_PATH)
    # A stale CONFIG path (e.g. carried to another machine via Dropbox) falls
    # back to whatever the resolved default found on this machine.
    if not p.exists() and DEFAULT_TEMPLATE_PATH.exists():
        return DEFAULT_TEMPLATE_PATH
    return p


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


def get_ml_timeout_sec(n_stems):
    """Wall-clock budget for the ML subprocess, scaled by stem count.

    Demucs on CPU is genuinely slow (tens of seconds per stem), and a big pack
    like Moby had 47 unknowns — so the budget is generous per stem so a real run
    is never killed mid-flight, but bounded so a hung/wedged subprocess can't
    stall the whole build forever. `ML_TIMEOUT_SEC` (env) forces a fixed total.
    """
    env_value = os.environ.get("ML_TIMEOUT_SEC")
    if env_value:
        try:
            return max(1.0, float(env_value))
        except ValueError:
            pass
    cfg = _load_project_config()
    per = float(cfg.get("ml_timeout_per_stem_sec", 240))
    base = float(cfg.get("ml_timeout_base_sec", 180))
    return base + per * max(1, int(n_stems))


def _ensure_wav_paths(paths, staging_dir):
    """Convert any non-WAV audio (AIFF/MP3/FLAC/OGG...) to 32-bit float WAV.

    The whole engine reads WAV only (clip lengths come from the WAV header, the
    bounce/analysis read PCM frames), so a stray non-WAV stem — often an MP3/FLAC
    reference dropped in with the stems — otherwise crashes the build. Converts
    via soundfile into staging_dir and substitutes the path; WAVs pass through
    untouched (zero cost for normal packs). A file that can't be read is dropped
    with a warning rather than killing the build. Returns (new_paths, skipped).
    """
    from als_patcher import _read_wav_header
    new, skipped = [], []
    sf = None
    for p in paths:
        p = Path(p)
        if p.suffix.lower() == ".wav":
            # Validate the header — a 0-byte / corrupt / mislabelled .wav must be
            # SKIPPED (with a warning), not abort the whole pack when the engine
            # later tries to read it.
            try:
                hdr = _read_wav_header(p)
                if hdr["rate"] <= 0 or hdr["data_size"] <= 0 or hdr["bps"] <= 0:
                    raise ValueError("empty or invalid WAV")
            except Exception as exc:  # noqa: BLE001
                skipped.append((p, "bad WAV: " + str(exc)))
                continue
            new.append(p)
            continue
        if sf is None:
            try:
                import soundfile as _sf
                sf = _sf
            except Exception:  # noqa: BLE001 — no soundfile -> can't convert
                sf = False
        if not sf:
            skipped.append((p, "soundfile not installed (can't read non-WAV)"))
            continue
        try:
            data, sr = sf.read(str(p))
            staging_dir.mkdir(parents=True, exist_ok=True)
            out = staging_dir / (p.stem + ".wav")
            sf.write(str(out), data, sr, subtype="FLOAT")  # 32-bit float — engine reads this
            new.append(out)
        except Exception as exc:  # noqa: BLE001 — unreadable -> skip, don't crash
            skipped.append((p, str(exc)))
    return new, skipped


def _skip_labels(skipped):
    """(path, why) pairs -> 'name — why' strings for the report / flags."""
    return [Path(pth).name + " — " + why for pth, why in skipped]


def _normalize_audio_to_wav(classified, references, unclassified, staging_dir):
    """Run _ensure_wav_paths across every classified/reference/unknown list.

    Returns (classified, references, unclassified, skipped_labels) — the skipped
    labels are surfaced in the session report + 'needs a look' flags so an
    unreadable stem is never silently absent from the build.
    """
    skipped = []
    for cat in list(classified.keys()):
        classified[cat], sk = _ensure_wav_paths(classified[cat], staging_dir)
        skipped += sk
        if not classified[cat]:
            del classified[cat]
    references, sk = _ensure_wav_paths(references, staging_dir)
    skipped += sk
    unclassified, sk = _ensure_wav_paths(unclassified, staging_dir)
    skipped += sk
    if skipped:
        print("\nWARNING — couldn't read these files, left OUT of the build:")
        for pth, why in skipped:
            print("  " + Path(pth).name + " — " + why)
    return classified, references, unclassified, _skip_labels(skipped)


def _find_preseeded_audio(project_folder, audio_folder):
    """Audio files the user pre-seeded into the target project folder.

    Sam sometimes drops his current master into the target ``Audio/`` (or the
    project root) so he can A/B the new mix against it. The builder classifies
    the *source* stems folder, not the target, so such a file would be copied
    around but left unreferenced in the .als. This captures those files up front
    (before we copy any source stems in) so they can be wired in as red
    reference match tracks at the bottom. Top-level only (never MASTER RENDERS).
    """
    found, seen = [], set()
    for d in (audio_folder, project_folder):
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if (f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
                    and f.name not in seen):
                seen.add(f.name)
                found.append(f)
    return found


def _bpm_from_filenames(paths):
    """Read a labelled BPM off the filenames (e.g. '…120BPM…', '…125.5 BPM…').
    Dance packs almost always name it — but it's only a hint to grid-check against
    the audio (see _resolve_project_bpm). Half-BPMs ('125.5') are kept, not
    truncated. Returns the most-voted value in 60–200, or None."""
    votes = {}
    for p in paths:
        for m in re.finditer(r"(?<!\d)(\d{2,3}(?:\.\d)?)\s*bpm\b",
                             Path(p).stem, re.IGNORECASE):
            v = float(m.group(1))
            if 60 <= v <= 200:
                votes[v] = votes.get(v, 0) + 1
    return float(max(votes, key=votes.get)) if votes else None


def _score_bpm_candidates(paths):
    scored = []
    for f in paths:
        try:
            result = detect_bpm(f)
        except Exception:  # noqa: BLE001 - a bad stem should not abort the build
            result = None
        if result:
            n_onsets = max(result.get("n_onsets", 0), 1)
            inlier_ratio = result.get("n_inliers", 0) / n_onsets
            residual = result.get("residual_ms")
            residual = 999.0 if residual is None else float(residual)
            scored.append({
                "bpm_key": result.get("bpm_rounded"),
                "credible": inlier_ratio >= 0.5 and residual <= 5.0,
                "quality": (inlier_ratio, -residual, result.get("n_inliers", 0)),
                "result": result, "source": f,
            })
    return scored


def _best_bpm(scored):
    if not scored:
        return None, None
    consensus = {}
    for it in scored:
        if it["credible"]:
            consensus[it["bpm_key"]] = consensus.get(it["bpm_key"], 0) + 1
    best = max(scored, key=lambda it: (consensus.get(it["bpm_key"], 0),
                                       1 if it["credible"] else 0, it["quality"]))
    return best["result"], best["source"]


def detect_project_bpm(classified):
    """Auto-detect BPM from the cleanest grid-locking rhythmic stem.

    Scores every kick/drum/bass candidate (consensus + grid-lock quality) — this
    catches packs like Moby where the kick is syncopated but snare/hat land on
    the grid. If NOTHING percussive locks credibly, it widens to melodic anchors
    (a glockenspiel, pluck or stab is often a perfect grid reference — Sam's
    "perc/glock in place of a snare"). Returns (result, source) or (None, None).
    """
    primary = []
    for cat in ("kick", "drums", "bass"):
        primary.extend(classified.get(cat, []))
    scored = _score_bpm_candidates(primary)
    if any(it["credible"] for it in scored):
        return _best_bpm(scored)
    extra = []
    for cat in ("music", "fx", "vocals"):
        extra.extend(classified.get(cat, []))
    return _best_bpm(scored + _score_bpm_candidates(extra))


# A filename-labelled BPM (e.g. "…130BPM…") is only a HINT — producers mislabel
# it (Sam hit a pack tagged 130 that was really 132). It must be grid-checked
# against the actual audio, never trusted outright. See Key Decisions.
BPM_AGREE_TOL = 0.6   # BPM; audio within this of the label = confirmed


def _fmt_bpm(x):
    """Whole tempos print as ints ('132'), halves keep one dp ('128.5')."""
    x = float(x)
    return str(int(x)) if x == int(x) else ("%.1f" % x)


def _octave_align(value, anchor):
    """Fold `value` to the ×/÷2 octave closest to `anchor`.

    The filename BPM resolves octave ambiguity in the audio fit: if a kick locks
    to 66 but the label says 132, that is the same tempo, not a conflict.
    """
    value = float(value)
    anchor = float(anchor)
    if value <= 0 or anchor <= 0:
        return value
    while value < anchor / 1.5:
        value *= 2.0
    while value > anchor * 1.5:
        value /= 2.0
    return value


def _bpm_is_credible(result):
    """Did the audio grid-lock cleanly enough to arbitrate the tempo?"""
    if not result:
        return False
    n = max(result.get("n_onsets", 0), 1)
    ratio = result.get("n_inliers", 0) / n
    res = result.get("residual_ms")
    res = 999.0 if res is None else float(res)
    return ratio >= 0.5 and res <= 5.0


def _audio_quality_flags(bpm, result, credible):
    """Review notes for an audio-derived BPM (low-confidence / half-double)."""
    flags = []
    b = int(round(float(bpm)))
    res = result.get("residual_ms") if result else None
    if not credible or res is None or res > 5.0:
        flags.append("Auto-BPM " + str(b) + " is low-confidence"
                     + ((" (±" + str(res) + "ms)") if res is not None else "")
                     + " — verify the tempo.")
    elif b > 150 or b < 90:
        # Clean grid-lock but an unusual tempo for dance — the classic
        # half/double-time trap (e.g. 168 is likely 84×2).
        flags.append("Auto-BPM " + str(b) + " is outside the usual range — "
                     "check it isn't half/double-time (try " + str(b // 2)
                     + " or " + str(b * 2) + ").")
    return flags


def _resolve_project_bpm(classified, fn_bpm):
    """Choose the project BPM, treating any filename label as a hint to verify.

    A labelled BPM is grid-checked against the cleanest-locking rhythmic stem —
    the audio is the arbiter. Returns (bpm, bpm_meta, bpm_flags); bpm is None
    only when there is no label AND nothing locked (the caller then raises).
    """
    result, src = detect_project_bpm(classified)
    credible = _bpm_is_credible(result)

    def _audio_meta():
        return {"source": src.name, "residual_ms": result["residual_ms"],
                "inliers": result["n_inliers"], "onsets": result["n_onsets"]}

    # No filename hint — the audio decides (unchanged behaviour).
    if fn_bpm is None:
        if result is None:
            return None, None, []
        bpm = float(result["bpm_rounded"])
        return bpm, _audio_meta(), _audio_quality_flags(bpm, result, credible)

    # Filename hint present — verify it against the audio.
    if not credible:
        # Nothing locked cleanly to confirm the label. Keep it, but say so —
        # never silently trust a filename for something this integral.
        meta = {"source": "filename (unverified)", "residual_ms": None,
                "inliers": None, "onsets": None}
        flag = ("BPM " + _fmt_bpm(fn_bpm) + " came from the filename and could not be "
                "confirmed against the audio (no clean rhythmic stem to grid-check it) "
                "— verify the tempo.")
        return float(fn_bpm), meta, [flag]

    aligned = _octave_align(result["bpm"], fn_bpm)   # label resolves the octave
    if abs(aligned - fn_bpm) <= BPM_AGREE_TOL:
        # The audio confirms the label.
        meta = {"source": "filename (audio-confirmed)",
                "residual_ms": result["residual_ms"],
                "inliers": result["n_inliers"], "onsets": result["n_onsets"]}
        return float(fn_bpm), meta, []

    # Conflict: the audio grid-locks to a different tempo than the label says.
    # Trust the audio (Sam's rule) and flag the discrepancy loudly. Round to the
    # nearest whole BPM — the detector reads ~0.3 low but its nearest-int is
    # dead-on, matching how the audio-only path already snaps (bpm_rounded).
    audio_bpm = float(round(aligned))
    meta = {"source": "audio (overrode filename " + _fmt_bpm(fn_bpm) + ")",
            "residual_ms": result["residual_ms"],
            "inliers": result["n_inliers"], "onsets": result["n_onsets"]}
    flag = ("Filename said " + _fmt_bpm(fn_bpm) + " BPM but the audio grid-locks to "
            + _fmt_bpm(audio_bpm) + " — using " + _fmt_bpm(audio_bpm) + " (from "
            + src.name + "). Verify the tempo.")
    return float(audio_bpm), meta, [flag]


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


def _ml_classify_unknowns(paths, use_whisper=True, python_exe=None, timeout=None):
    """Classify filename-unknown stems by audio content (Demucs + Whisper).

    Runs Source/audio_ml_classify.py as a subprocess (separate CUDA context,
    PYTHON_JIT=0). Returns {Path: result_dict}; an empty dict if ML is
    unavailable or errors, so the caller can fall back to placing them in music.
    """
    if not paths:
        return {}
    python_exe = python_exe or get_ml_python_exe() or sys.executable
    work = Path(tempfile.mkdtemp(prefix="als_ml_"))
    try:
        in_json = work / "in.json"
        out_json = work / "out.json"
        with open(in_json, "w", encoding="utf-8") as fh:
            json.dump([str(p) for p in paths], fh)
        cmd = [python_exe, str(ML_SCRIPT), "--in", str(in_json), "--out", str(out_json)]
        if not use_whisper:
            cmd.append("--no-whisper")
        env = dict(os.environ)
        env["PYTHON_JIT"] = "0"
        if timeout is None:
            timeout = get_ml_timeout_sec(len(paths))
        try:
            subprocess.run(cmd, env=env, check=True, timeout=timeout)
            with open(out_json, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except subprocess.TimeoutExpired:
            # A hung/wedged Demucs must never stall the build — fall back to music.
            print("  ML classification timed out after %ds; unknowns -> music"
                  % int(timeout))
            return {}
        except Exception as e:  # noqa: BLE001 — ML is best-effort; never abort the build
            print("  ML classification unavailable (" + repr(e) + "); unknowns -> music")
            return {}
        return {p: raw[str(p)] for p in paths if str(p) in raw}
    finally:
        # Always clean up the temp scratch dir (was leaking one per build).
        shutil.rmtree(work, ignore_errors=True)


def _build_groups_report(stems):
    """[{name, subgroups:[...]}] for the working GroupTracks, in layout order."""
    groups = {}
    for s in stems:
        g = s.get("group_name")
        if not g or g == "Dry":
            continue
        groups.setdefault(g, [])
        sg = s.get("subgroup_name")
        if sg and sg not in groups[g]:
            groups[g].append(sg)
    return [{"name": g, "subgroups": subs} for g, subs in groups.items()]


def _find_energetic_point(path, win_sec=2.0, intro_skip_sec=8.0, smooth_sec=8.0):
    """Time (sec) of the ENERGETIC part of a full track — the drop/hook, used to
    drop an A/B locator. Finds the onset of the loudest sustained section (peak
    smoothed RMS, skipping the intro). Returns 0.0 if it can't analyse."""
    try:
        import numpy as np
        import soundfile as sf
    except Exception:  # noqa: BLE001 — no numpy/soundfile -> marker at the start
        return 0.0
    try:
        data, sr = sf.read(str(path), always_2d=True)
    except Exception:  # noqa: BLE001
        return 0.0
    x = data.mean(axis=1).astype("float64")
    win = int(win_sec * sr)
    if win < 1 or len(x) < win * 2:
        return 0.0
    n = len(x) // win
    rms = np.sqrt((x[:n * win].reshape(n, win) ** 2).mean(axis=1) + 1e-12)
    k = max(1, int(round(smooth_sec / win_sec)))
    sm = np.convolve(rms, np.ones(k) / k, mode="same")
    peak = float(sm.max())
    if peak <= 0:
        return 0.0
    intro = int(round(intro_skip_sec / win_sec))
    thr = 0.9 * peak
    for i in range(len(sm)):
        if i >= intro and sm[i] >= thr:
            return float(i * win_sec)
    return float(int(np.argmax(sm)) * win_sec)


def _make_refcompare_track(refcompare_files, audio_folder, start_beat, bpm):
    """Build the single 'References' track — other artists' tracks laid out one
    after another from `start_beat` (to the RIGHT of the song), Ext. Out, left
    on, own colour, with a numbered key-mapped locator on the energetic part of
    each. Returns (tracks, locators): tracks is [] or a one-track list. Shared by
    the single- and multi-version build paths."""
    if not refcompare_files:
        return [], []
    locators = []
    cursor = _next_phrase_boundary(start_beat + 16.0)
    clips = []
    for i, f in enumerate(refcompare_files):
        dest = audio_folder / f.name
        if not dest.exists():
            shutil.copy2(f, dest)
        n_frames, sr_hz, _ = get_wav_info(dest)
        dur_beats = (n_frames / float(sr_hz) / 60.0) * float(bpm) if sr_hz else 8.0
        energetic_sec = _find_energetic_point(dest)
        key = str(i + 1) if i < 9 else ("0" if i == 9 else None)  # 1..9 then 0
        locators.append((cursor + (energetic_sec / 60.0) * float(bpm),
                         (key + " · " if key else "") + f.stem[:28], key))
        clips.append({"file_path": dest, "rel_path": "Audio/" + f.name,
                      "regions": None, "start_beat": cursor, "clip_name": f.stem})
        print("  ref " + str(i + 1) + " (one track, Ext. Out, on): " + f.name
              + ("  [energetic @ %.0fs]" % energetic_sec))
        cursor = math.ceil((cursor + dur_beats + 8.0) / 4.0) * 4.0   # gap, snap to bar
    primary = clips[0]
    track = {"name": "References", "clip_name": primary["clip_name"],
             "category": "refcompare", "color": REFCOMPARE_COLOR,
             "file_path": primary["file_path"], "rel_path": primary["rel_path"],
             "regions": None, "base_start_beat": primary["start_beat"],
             "extra_clips": clips[1:]}
    return [track], locators


def _collect_flags(unmatched_updated, skipped, silent_tracks, bpm_flags=()):
    """Human-readable 'needs a look' notes for the UI — build decisions Sam
    should review BEFORE opening the project (not silent guesses).

    BPM notes (low-confidence, filename/audio conflict, unverified label) are
    produced by _resolve_project_bpm and passed in via bpm_flags."""
    flags = []
    if unmatched_updated:
        flags.append("Updated stem(s) had no matching original — parked muted at the "
                     "bottom for you to position: " + ", ".join(unmatched_updated))
    if skipped:
        flags.append("Left OUT of the build (unreadable / sample-rate mismatch): "
                     + ", ".join(skipped))
    flags.extend(bpm_flags or [])
    if silent_tracks:
        flags.append(str(len(silent_tracks)) + " empty / dead stem(s) parked at the bottom "
                     "— check they weren't meant to have audio.")
    return flags


def _safe_filename(name):
    """Sanitise a user-typed name for use as a file/folder name: replace the
    characters Windows/macOS forbid (\\ / : * ? " < > |) with '_' and collapse
    whitespace, so a label like 'Artist - Title [Bad<>Name]' can't blow up the
    build when it becomes the project folder + .als name."""
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    return re.sub(r"\s+", " ", name).strip() or "Untitled"


def _analysis_off_flags():
    """A flag when the numpy content-analysis safety nets (full-mix + group-bus
    detection) can't run, so an un-caught full mix / bus in the flat-ref sum
    isn't a silent surprise. Empty when numpy is present (Sam's normal case)."""
    if analysis_available():
        return []
    return ["Audio safety analysis is OFF (numpy not installed) — a full mix / "
            "master or a group-bus left among the stems won't be auto-caught and "
            "could pollute the flat-ref sum. Check the flat-ref peak and listen."]


def _validate_als_flags(als_path, expected_bpm=None):
    """Parse the just-written .als and surface any structural problem (incl. a
    tempo that didn't land) as a flag. A CLI build otherwise has NO safety net —
    only the Studio App validated. Read-only ET parse; never fails a good build."""
    try:
        from validate_project import validate_path
        result = validate_path(als_path, expected_bpm)
        errs = list(getattr(result, "errors", []) or [])
        if errs:
            return ["The built project didn't fully validate: " + "; ".join(errs[:3])
                    + (" (+" + str(len(errs) - 3) + " more)" if len(errs) > 3 else "")
                    + " — open it in Ableton to check."]
    except Exception:  # noqa: BLE001 — validation must never break a good build
        pass
    return []


REPORTS_DIRNAME = "Reports"


def _reports_dir(project_folder):
    """Tool-generated reports live in a dedicated 'Reports/' subfolder so the
    project root stays tidy — just the .als, Audio/, and the DAW's own folders."""
    d = Path(project_folder) / REPORTS_DIRNAME
    try:
        d.mkdir(exist_ok=True)
    except Exception:  # noqa: BLE001 — reporting must never fail a good build
        pass
    return d


def session_report_path(project_folder):
    """Resolve the machine-readable build report (the Studio App reads this to
    draw its Result Card). Prefers Reports/ but falls back to the project root so
    older builds still resolve."""
    project_folder = Path(project_folder)
    new = project_folder / REPORTS_DIRNAME / "Session Report.json"
    old = project_folder / "Session Report.json"
    return old if old.exists() and not new.exists() else new


def _write_json_atomic(path, obj, attempts=5):
    """Write JSON atomically (temp + os.replace) with a short Dropbox-lock retry.
    The Studio App reads Session Report.json to show the result card, so a
    transient lock shouldn't lose it and leave the card without its result."""
    import time
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    for _ in range(attempts):
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(obj, fh, indent=2)
            os.replace(tmp, path)
            return True
        except (PermissionError, OSError):
            time.sleep(1.0)
    try:
        tmp.unlink()
    except OSError:
        pass
    return False


def _write_session_report(project_folder, report):
    """Write the machine-readable Session Report.json (the Studio App reads it to
    show a build Result Card) plus a short human-readable Session Report.txt.
    Both live in the Reports/ subfolder to keep the project root tidy."""
    rdir = _reports_dir(project_folder)
    _write_json_atomic(rdir / "Session Report.json", report)  # atomic + lock-retry
    try:
        lines = [
            report.get("project_name", ""),
            "=" * 56,
            "BPM: " + str(report.get("bpm", "?"))
            + (" (from " + report["bpm_source"] + ", " + str(report.get("bpm_inliers", "?"))
               + "/" + str(report.get("bpm_onsets", "?")) + " on grid, +/-"
               + str(report.get("bpm_residual_ms", "?")) + "ms)"
               if report.get("bpm_source") else " (set manually)"),
            "Tracks: " + str(report.get("tracks_total", "?")) + " + Session Time",
            "",
            "Categories: " + ", ".join(k.upper() + " " + str(v)
                                       for k, v in report.get("categories", {}).items()),
        ]
        for g in report.get("groups", []):
            subs = (" > " + ", ".join(g["subgroups"])) if g.get("subgroups") else ""
            lines.append("  Group " + g["name"] + subs)
        if report.get("buses"):
            lines.append("Buses parked (out of the sum): " + ", ".join(report["buses"]))
        if report.get("dry_parked"):
            lines.append("Dry parked: " + ", ".join(report["dry_parked"]))
        if report.get("silent"):
            lines.append("Silent/dead exports: " + ", ".join(report["silent"]))
        if report.get("skipped"):
            lines.append("Skipped (unreadable / SR mismatch): " + ", ".join(report["skipped"]))
        lines.append("Flat-ref peak: " + str(report.get("flat_ref_peak", "?")))
        with open(rdir / "Session Report.txt", "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
    except Exception:  # noqa: BLE001
        pass


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


def _extract_special_dirs(classified, references, unclassified, root):
    """Pull files that live in an 'updated stems' / 'ref' SUBfolder out of the
    normal classification (classify_stems recurses into subfolders, so they'd
    otherwise be built as ordinary tracks). Returns (updated_files, ref_files);
    the classified/references/unclassified containers are edited in place.

    Only SUBfolders are sifted — a file directly in the pack root is never
    diverted even if the pack is named like 'Coldplay - Fix You Stems', so a
    whole pack isn't mis-sifted into muted A/B tracks."""
    from versions import special_dir_kind
    # .absolute() not .resolve(): a plain parent==root check (Path equality
    # normalises case/separators) doesn't need symlink resolution, and .resolve()
    # does per-file I/O that can stall on a stale network share inside this loop.
    root = Path(root).absolute()
    updated, ref_compare = [], []

    def sift(lst):
        keep = []
        for f in lst:
            parent = Path(f).absolute().parent
            kind = None if parent == root else special_dir_kind(parent.name)
            if kind == "update":
                updated.append(f)
            elif kind == "ref":
                ref_compare.append(f)
            else:
                keep.append(f)
        return keep

    for cat in list(classified.keys()):
        classified[cat] = sift(classified[cat])
        if not classified[cat]:
            del classified[cat]
    references[:] = sift(references)
    unclassified[:] = sift(unclassified)
    return updated, ref_compare


def _gather_special_dir_files(stem_folder):
    """(updated_files, ref_files) from any 'updated stems' / 'ref' subfolder at
    ANY depth of a pack. Used by the multi-version path, which dispatches before
    classify_stems runs, so it can wire those folders in rather than drop them —
    including a REF/ nested inside a version subfolder."""
    from versions import special_dir_kind

    def _audio_under(folder):
        return [f for f in Path(folder).rglob("*")
                if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
                and not f.name.startswith(".") and "__MACOSX" not in f.parts]

    updated, ref_compare = [], []
    folder = Path(stem_folder)
    if not folder.exists():
        return updated, ref_compare
    for d in sorted(p for p in folder.rglob("*") if p.is_dir()):
        if d.name == "__MACOSX" or d.name.startswith("."):
            continue
        kind = special_dir_kind(d.name)
        if kind == "update":
            updated += _audio_under(d)
        elif kind == "ref":
            ref_compare += _audio_under(d)
    return updated, ref_compare


def _match_key(path):
    """Identity key for pairing an updated stem to the original it replaces.

    Robust to real names like 'UPDATE_STEM_ SUB BASS_2': strips an update prefix/
    words, a leading export index, and a trailing counter, then normalises — so
    it lands next to '…Sub Bass'."""
    name = Path(path).stem
    name = re.sub(r"(?i)^\s*(update[_\s]*stems?|updated?|revis\w*|new)[_\s]*", " ", name)
    name = re.sub(r"(?i)^\s*stem[_\s]*\d{1,3}[_\-\s.]*", " ", name)  # 'STEM N -' prefix
    name = re.sub(r"(?i)\b(updat\w*|revis\w*|replacement|corrected|amended|fixe?d?|new)\b", " ", name)
    name = re.sub(r"^\s*\d{1,3}[_\-\s.]+", " ", name)     # leading export index
    name = re.sub(r"[_\-]", " ", name)
    name = re.sub(r"\s+\d{1,2}$", "", name)               # trailing counter
    return re.sub(r"\s+", " ", name).strip().lower() or Path(path).stem.lower()


def _apply_subgroups(stems, scope):
    """Cluster each in-scope category's flat group into nested sub-groups.

    `stems` are already laid out in category order; each contiguous category
    block is replaced by its sub-clustered (reordered + tagged) version when the
    clusterer finds a useful structure. Returns the rebuilt stems list.
    """
    from subgroup_cluster import cluster_subgroups
    out = []
    i = 0
    while i < len(stems):
        cat = stems[i]["category"]
        j = i
        while j < len(stems) and stems[j]["category"] == cat:
            j += 1
        block = stems[i:j]
        if cat in scope and block[0].get("group_key"):
            clustered = cluster_subgroups(block, cat)
            if clustered:
                block = clustered
        out.extend(block)
        i = j
    return out


_ABLETON_ICON = "AProject.ico"


def _ableton_icon_source():
    """The bundled Ableton project icon (frozen EXE bundle, else repo Assets/)."""
    if getattr(sys, "frozen", False):
        cand = Path(getattr(sys, "_MEIPASS", "")) / _ABLETON_ICON
        if cand.exists():
            return cand
    return Path(__file__).resolve().parents[1] / "Assets" / _ABLETON_ICON


def apply_ableton_folder_icon(project_folder):
    """Give a project folder the Ableton project icon (like a native Ableton
    project) — copy AProject.ico into 'Ableton Project Info/', write Desktop.ini,
    and set the folder read-only so Explorer honours it. Windows-only; wrapped so
    a cosmetic icon can never fail (or block) a build. Idempotent (safe to redo
    on a rebuild)."""
    try:
        project_folder = Path(project_folder)
        info = project_folder / "Ableton Project Info"
        info.mkdir(parents=True, exist_ok=True)
        src = _ableton_icon_source()
        if src.exists():
            shutil.copy2(src, info / _ABLETON_ICON)
        ini_path = project_folder / "Desktop.ini"
        _win_set_attrs(ini_path, 0x80)   # NORMAL first, so we can overwrite it
        ini_path.write_text(
            "[.ShellClassInfo]\r\nConfirmFileOp=0\r\nNoSharing=0\r\n"
            "IconFile=Ableton Project Info\\" + _ABLETON_ICON + "\r\nIconIndex=0\r\n",
            encoding="ascii")
        _win_set_attrs(ini_path, 0x02 | 0x04)          # HIDDEN | SYSTEM
        _win_set_attrs(project_folder, None, add=0x01)  # folder READONLY
    except Exception:  # noqa: BLE001 — the icon is cosmetic; never fail the build
        pass


def _win_set_attrs(path, value, add=None):
    """Set (value) or OR-in (add) Windows file attributes. No-op off Windows."""
    if sys.platform != "win32":
        return
    import ctypes
    k = ctypes.windll.kernel32
    if add is not None:
        cur = k.GetFileAttributesW(str(path))
        value = (0 if cur in (-1, 0xFFFFFFFF) else cur) | add
    k.SetFileAttributesW(str(path), value)


def build_project(stem_folder, artist, title, label, bpm=None, output_base=None,
                  use_ml=None, project_name=None, category_colors=None,
                  subgroup_categories=None):
    """Build a complete Ableton project from a folder of stems.

    Args:
        stem_folder: Path to folder containing stem audio files
        artist: Artist name
        title: Track title
        label: Label or contact name
        bpm: Project tempo (int/float). Pass None or "auto" to detect it from
            the kick/percussion stems.
        output_base: Where to create the project folder (defaults to OUTPUT_BASE)
        category_colors: optional {category: palette_index} overriding the
            default working-track colours (kick/drums/bass/music/vocals/fx/
            sends) — used by the studio UI's per-user/partner colour profiles.
        subgroup_categories: which categories get clustered into nested
            sub-groups. None = default (vocals/drums/music); pass an empty
            list/tuple to disable nesting entirely.

    Returns:
        Path to the created project folder
    """
    stem_folder = Path(stem_folder)
    if output_base is None:
        output_base = get_output_base()
    output_base = Path(output_base)
    if use_ml is None:
        use_ml = get_enable_ml_classifier()

    def cat_color(cat):
        if category_colors and cat in category_colors:
            return category_colors[cat]
        return CATEGORIES[cat]["color"]

    versions = detect_versions(stem_folder)
    if versions:
        # A multi-version pack can still carry 'ref'/'updated stems' subfolders —
        # gather them so the multi-version builder wires them in too.
        mv_updated, mv_refcompare = _gather_special_dir_files(stem_folder)
        # Belt-and-braces: ANY audio in the pack not claimed by a version or a
        # special folder (a top-level supplied master/ref, a name-token minority
        # stem, a stray file) is a LEFTOVER — never drop it silently. It's wired
        # in as a parked reference track and flagged for review.
        claimed = {Path(f).resolve() for v in versions for f in v["files"]}
        claimed |= {Path(f).resolve() for f in mv_updated + mv_refcompare}
        all_audio = [f for f in Path(stem_folder).rglob("*")
                     if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
                     and not f.name.startswith(".") and "__MACOSX" not in f.parts]
        mv_leftovers = [f for f in all_audio if f.resolve() not in claimed]
        return build_multiversion_project(
            versions, artist, title, label, bpm, output_base, use_ml=use_ml,
            category_colors=category_colors,
            subgroup_categories=subgroup_categories,
            updated_files=mv_updated, refcompare_files=mv_refcompare,
            leftover_files=mv_leftovers, project_name=project_name,
        )

    if project_name is None:
        project_name = artist + " - " + title + " [" + label + "]"
    project_name = _safe_filename(project_name)   # can't blow up the folder/.als
    project_folder = output_base / (project_name + " Project")
    audio_folder = project_folder / "Audio"
    info_folder = project_folder / "Ableton Project Info"
    master_folder = project_folder / "MASTER RENDERS"

    # Capture anything the user pre-seeded into the target folder BEFORE we copy
    # source stems in, so a supplied master (dropped in to A/B against) is wired
    # in as a red reference rather than left orphaned. Filtered against the
    # source stems below so our own copies/bounce aren't re-added.
    preseeded = _find_preseeded_audio(project_folder, audio_folder)

    project_folder.mkdir(parents=True, exist_ok=True)
    audio_folder.mkdir(exist_ok=True)
    info_folder.mkdir(exist_ok=True)
    master_folder.mkdir(exist_ok=True)

    print("Classifying stems...")
    classified, references, unclassified = classify_stems(stem_folder)
    # Pull out 'updated stems' / 'ref' subfolders BEFORE anything else (parent
    # folder is intact here; WAV normalisation would stage them and lose it).
    updated_files, refcompare_files = _extract_special_dirs(
        classified, references, unclassified, stem_folder)
    # Names of every source stem, by stem (no extension — survives WAV
    # normalisation), so pre-seeded extras can be told apart from our own copies.
    # Includes the updated/ref-folder files too, so rebuilding into an existing
    # project folder doesn't re-wire last build's REF/UPDATE copies as duplicate
    # reference tracks (they'd otherwise pile up one more per rebuild).
    source_names = {p.stem.lower()
                    for lst in (references, unclassified, updated_files,
                                refcompare_files, *classified.values())
                    for p in lst}

    # Normalise non-WAV audio (AIFF/MP3/FLAC dropped in with the stems) to WAV
    # up front, so every downstream reader (regions, BPM, bounce, analysis) only
    # ever sees WAV. Unreadable files are dropped with a warning, never crash.
    wav_staging = Path(tempfile.mkdtemp(prefix="als_wav_"))
    classified, references, unclassified, pre_skipped = _normalize_audio_to_wav(
        classified, references, unclassified, wav_staging)
    updated_files, _sk = _ensure_wav_paths(updated_files, wav_staging)
    pre_skipped += _skip_labels(_sk)
    refcompare_files, _sk = _ensure_wav_paths(refcompare_files, wav_staging)
    pre_skipped += _skip_labels(_sk)

    # Audio-content safety net (numpy): a file filenames couldn't place
    # (music/unclassified) but that ANALYSES as a full mix / master / sub-bounce
    # is moved to references — so it is kept OUT of the flat bounce (summing a
    # whole mix into the reference would pollute it). No-op without numpy.
    suspects = list(unclassified) + list(classified.get("music", []))
    # When numpy is absent the full-mix / group-bus safety nets can't run — flag
    # it so an un-caught full mix / bus summed into the flat ref isn't a silent
    # surprise (on Sam's machine numpy is present, so this never fires there).
    analysis_flags = _analysis_off_flags()
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
        _write_ml_report(_reports_dir(project_folder) / "ML Classification Report.txt",
                         unclassified, ml_results)
        if use_ml:
            n_ml = sum(1 for f in unclassified
                       if ml_results.get(f) and ml_results[f].get("category"))
            print("  audio-classified " + str(n_ml) + "/" + str(len(unclassified))
                  + " stems -> see 'Reports/ML Classification Report.txt'")
        unclassified = []

    bpm_meta = None
    bpm_flags = []
    if bpm is None or str(bpm).lower() == "auto":
        # A BPM labelled in the filenames ("…130BPM…") is only a hint — grid-check
        # it against the audio, which is the arbiter (Sam: a 130-tagged pack was
        # really 132). _resolve_project_bpm reconciles the two.
        fn_bpm = _bpm_from_filenames([f for lst in classified.values() for f in lst])
        print("\nResolving BPM"
              + (" (filename hint: " + _fmt_bpm(fn_bpm) + ")" if fn_bpm else " from audio")
              + "...")
        bpm, bpm_meta, bpm_flags = _resolve_project_bpm(classified, fn_bpm)
        if bpm is None:
            # Diagnose the shape: a folder of mixdowns/masters (a delivery batch,
            # not one song's stems) fails here — say so instead of a bare error.
            n_stems = sum(len(v) for v in classified.values())
            if len(references) >= max(2, n_stems):
                raise ValueError(
                    "This doesn't look like one song's stem pack — "
                    + str(len(references)) + " file(s) read as full mixes/"
                    "masters vs " + str(n_stems) + " stems (a delivery batch "
                    "of mixdowns?). Build one song's stems at a time, or type "
                    "a BPM to force a build.")
            raise ValueError(
                "Could not auto-detect BPM (no usable rhythmic stem). "
                "Type the BPM to build anyway."
            )
        print("  BPM " + _fmt_bpm(bpm) + " — " + bpm_meta["source"]
              + (("  <-- " + bpm_flags[0]) if bpm_flags else ""))

    print("\nCopying stems and detecting audio regions...")
    stems = []
    for cat in sorted(classified.keys(), key=lambda c: CATEGORIES[c]["order"]):
        color = cat_color(cat)
        for f in classified[cat]:
            dest = audio_folder / f.name
            if not dest.exists():
                shutil.copy2(f, dest)
            # FX (risers/uplifters build from near-silence) get a lead-in so
            # the ramp isn't trimmed; everything else trims tight at the front.
            regions, true_peak_db = find_audio_regions(
                dest, head_sec=2.0 if cat == "fx" else 0.0, return_peak=True)
            stems.append({
                "name": f.stem,
                "category": cat,
                "color": color,
                "file_path": dest,
                "rel_path": "Audio/" + f.name,
                "regions": regions,
                "silent": true_peak_db < SILENCE_FLOOR_DB,
            })

    # --- Empty/silent stems --------------------------------------------------
    # A stem with no audio in it (TRUE PEAK below the silence floor) is moved to
    # the very bottom and given its own colour so it's obviously a dead export.
    # True peak (not windowed RMS) so a quiet, sparse-but-real stem — a soft
    # shaker — is kept as audio, not parked as dead.
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

    # Nested sub-groups: cluster vocals (singer/role), drums (kit/perc) and
    # music (by instrument) into named sub-groups within their category group.
    scope = SUBGROUP_CATEGORIES if subgroup_categories is None else tuple(subgroup_categories)
    if scope:
        stems = _apply_subgroups(stems, scope)
        subbed = sorted({s["subgroup_name"] for s in stems if s.get("subgroup_name")})
        if subbed:
            print("\nSub-groups: " + ", ".join(subbed))

    # --- Updated / revised stems (A/B) --------------------------------------
    # A stem from an 'updated stems' subfolder replaces an original; keep BOTH so
    # Sam can A/B in the arrangement. Place the updated copy right next to its
    # original (same group/sub-group), in its own colour, MUTED (off), and OUT of
    # the flat-ref sum (it's a duplicate element).
    unmatched_updated = []
    if updated_files:
        by_key = {}
        for idx, s in enumerate(stems):
            by_key.setdefault(_match_key(s["file_path"]), idx)
        matched, unmatched = [], []
        for f in updated_files:
            dest = audio_folder / f.name
            if not dest.exists():
                shutil.copy2(f, dest)
            regions, _peak = find_audio_regions(dest, return_peak=True)
            orig_idx = by_key.get(_match_key(f))
            orig = stems[orig_idx] if orig_idx is not None else None
            t = {
                "name": ((orig["name"] if orig else f.stem) + " (updated)"),
                "clip_name": f.stem,
                "category": orig["category"] if orig else "music",
                "color": UPDATED_TRACK_COLOR,
                "file_path": dest, "rel_path": "Audio/" + f.name,
                "regions": regions, "muted": True, "updated": True,
            }
            if orig:
                for k in ("group_key", "group_name", "subgroup_key", "subgroup_name",
                          "subgroup_color", "subgroup_muted", "subgroup_unfolded"):
                    if orig.get(k) is not None:
                        t[k] = orig[k]
            print("  updated stem (A/B, muted, own colour): " + f.name
                  + (" -> next to " + orig["name"] if orig else " (no match, appended)"))
            (matched if orig_idx is not None else unmatched).append((orig_idx, t))
        for orig_idx, t in sorted(matched, key=lambda x: x[0], reverse=True):
            stems.insert(orig_idx + 1, t)
        stems += [t for _i, t in unmatched]
        unmatched_updated = [t["clip_name"] for _i, t in unmatched]

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

    # Wire in any master/reference the user pre-seeded into the target folder
    # (not one of our source stems, not our own flat bounce) as a red match track.
    preseeded_refs = [f for f in preseeded
                      if f.stem.lower() not in source_names
                      and "FLAT REF" not in f.name.upper()]
    for f in preseeded_refs:
        dest = audio_folder / f.name
        if f.parent != audio_folder and not dest.exists():
            shutil.copy2(f, dest)
        print("  wiring in pre-seeded reference: " + f.name)
        ref_tracks.append({
            "name": f.stem,
            "clip_name": f.stem,
            "category": "reference",
            "color": REF_TRACK_COLOR,
            "file_path": dest,
            "rel_path": "Audio/" + f.name,
            "regions": None,
        })

    # External reference tracks (other artists' tracks from a 'ref' subfolder):
    # ALL on ONE "References" track, laid out one after another to the RIGHT of
    # the arrangement (after the song). Routed to Ext. Out (bypasses the master),
    # LEFT ON, own colour — so Sam can flick across and A/B against his mix. Never
    # summed. A numbered locator is dropped on the ENERGETIC part (the drop) of
    # each ref so he can jump straight to the meat of each.
    max_end_sec = 0.0
    for s in stems:
        for (_rs, _re) in (s.get("regions") or []):
            max_end_sec = max(max_end_sec, _re)
    content_end = CLIP_START_BEATS + (max_end_sec / 60.0) * float(bpm)
    refcompare_tracks, ref_locators = _make_refcompare_track(
        refcompare_files, audio_folder, content_end, bpm)

    mix_files = [s["file_path"] for s in stems if not s.get("updated")]
    print("\nBouncing flat reference (summing " + str(len(mix_files)) + " mix stems)...")
    bounce_name = project_name + " FLAT REF.wav"
    bounce_path = audio_folder / bounce_name
    summary = sum_stems_to_wav(mix_files, bounce_path)
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

    all_stems = (stems + dry_tracks + ref_tracks + refcompare_tracks
                 + bus_tracks + silent_tracks)

    print("Classification summary:")
    cat_counts = {}
    for s in stems:
        if s.get("updated"):
            continue   # an updated A/B copy isn't a new element in the tally
        cat_counts[s["category"]] = cat_counts.get(s["category"], 0) + 1
    for cat in sorted(cat_counts.keys(), key=lambda c: CATEGORIES[c]["order"]):
        print("  " + cat.upper() + ": " + str(cat_counts[cat]) + " stems")
    if dry_tracks:
        print("  DRY (parked, muted group): " + str(len(dry_tracks)) + " stems")
    print("  REF TRACKS: " + str(len(ref_tracks)) + " (flat bounce + "
          + str(len(references)) + " supplied + "
          + str(len(preseeded_refs)) + " pre-seeded)")
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
        locators=ref_locators,
    )
    als_flags = _validate_als_flags(als_path, float(bpm))

    print("\nProject created:")
    print("  Folder: " + str(project_folder))
    print("  ALS:    " + str(als_path))
    print("  BPM:    " + str(bpm))
    print("  Tracks: " + str(len(all_stems)) + " + Session Time")

    report = {
        "project_name": project_name, "artist": artist, "title": title, "label": label,
        "als_name": als_path.name,
        "bpm": float(bpm),
        "bpm_source": bpm_meta["source"] if bpm_meta else None,
        "bpm_residual_ms": bpm_meta["residual_ms"] if bpm_meta else None,
        "bpm_inliers": bpm_meta["inliers"] if bpm_meta else None,
        "bpm_onsets": bpm_meta["onsets"] if bpm_meta else None,
        "tracks_total": len(all_stems),
        "categories": {cat: cat_counts[cat]
                       for cat in sorted(cat_counts, key=lambda c: CATEGORIES[c]["order"])},
        "groups": _build_groups_report(stems),
        "buses": [s["name"] for s in bus_tracks],
        "dry_parked": [s.get("display_name", s.get("name", "")) for s in dry_tracks],
        "silent": [s.get("display_name", s.get("name", "")) for s in silent_tracks],
        "references_supplied": len(references),
        "references_preseeded": len(preseeded_refs),
        "updated_stems": [Path(f).stem for f in updated_files],
        "refcompare": [Path(f).stem for f in refcompare_files],
        "flat_ref_peak": round(float(summary["peak"]), 3),
        "skipped": list(summary.get("skipped", [])) + pre_skipped,
        "flags": _collect_flags(unmatched_updated,
                                list(summary.get("skipped", [])) + pre_skipped,
                                silent_tracks, bpm_flags) + analysis_flags + als_flags,
        "multiversion": False,
    }
    _write_session_report(project_folder, report)
    apply_ableton_folder_icon(project_folder)

    # The WAV-conversion scratch dir is done with — clean it up (it used to leak
    # one OS-temp dir per build that had any non-WAV stems).
    shutil.rmtree(wav_staging, ignore_errors=True)

    return project_folder


def _process_version_files(files, version_audio_dir, rel_prefix, use_ml=True,
                           ml_report_path=None, category_colors=None):
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

    # Normalise non-WAV audio to WAV before any analysis (same as single build).
    classified, references, unclassified, v_skipped = _normalize_audio_to_wav(
        classified, references, unclassified, version_audio_dir / "_wav_staging")

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
        color = (category_colors or {}).get(cat, CATEGORIES[cat]["color"])
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
    return mix_stems, ref_stems, bus_stems, v_skipped


def build_multiversion_project(versions, artist, title, label, bpm, output_base,
                               use_ml=True, category_colors=None,
                               subgroup_categories=None, updated_files=None,
                               refcompare_files=None, leftover_files=None,
                               project_name=None):
    """Build a project from multiple versions (extended / radio edit / dub ...).

    Each element shares ONE track across versions; versions are laid out as
    sequential sections down the arrangement (VERSION_GAP_BARS between them),
    with a flat-ref bounce under each version. 'updated stems' / 'ref' subfolders
    (updated_files / refcompare_files) are wired in like the single-version path.
    """
    if project_name is None:
        project_name = artist + " - " + title + " [" + label + "]"
    project_name = _safe_filename(project_name)   # can't blow up the folder/.als
    project_folder = Path(output_base) / (project_name + " Project")
    audio_folder = project_folder / "Audio"
    updated_files = list(updated_files or [])
    refcompare_files = list(refcompare_files or [])
    leftover_files = list(leftover_files or [])
    # Capture any pre-seeded master/reference in the target folder BEFORE copying
    # source stems in (same as the single-version path), so it's wired in below.
    preseeded = _find_preseeded_audio(project_folder, audio_folder)
    source_names = {Path(f).stem.lower() for v in versions for f in v["files"]}
    source_names |= {Path(f).stem.lower()
                     for f in updated_files + refcompare_files + leftover_files}
    for sub in ("Audio", "Ableton Project Info", "MASTER RENDERS"):
        (project_folder / sub).mkdir(parents=True, exist_ok=True)
    mv_pre_skipped = []
    updated_files, _sk = _ensure_wav_paths(updated_files, audio_folder / "_wav_staging")
    mv_pre_skipped += _skip_labels(_sk)
    refcompare_files, _sk = _ensure_wav_paths(refcompare_files, audio_folder / "_wav_staging")
    mv_pre_skipped += _skip_labels(_sk)
    leftover_files, _sk = _ensure_wav_paths(leftover_files, audio_folder / "_wav_staging")
    mv_pre_skipped += _skip_labels(_sk)

    print("Multi-version package: " + " | ".join(v["name"] for v in versions))

    pv = []
    for v in versions:
        vname = _safe_filename(v["name"]) or "Version"
        rel_prefix = "Audio/" + vname + "/"
        print("\n[" + v["name"] + "] processing " + str(len(v["files"])) + " files...")
        report_path = _reports_dir(project_folder) / ("ML Classification Report - " + vname + ".txt")
        mix, refs, buses, v_skipped = _process_version_files(
            v["files"], audio_folder / vname, rel_prefix,
            use_ml=use_ml, ml_report_path=report_path,
            category_colors=category_colors,
        )
        mv_pre_skipped += v_skipped
        print("  mix=" + str(len(mix)) + " refs=" + str(len(refs)) + " buses=" + str(len(buses)))
        pv.append({"name": v["name"], "vname": vname, "rel_prefix": rel_prefix,
                   "vdir": audio_folder / vname, "mix": mix, "refs": refs, "buses": buses})

    bpm_meta = None
    bpm_flags = []
    if bpm is None or str(bpm).lower() == "auto":
        # Same rule as the single-version path: a filename BPM is a hint that must
        # be grid-checked against the audio (arbiter). Verify on the primary version.
        fn_bpm = _bpm_from_filenames([s["file_path"] for p in pv for s in p["mix"]])
        prim_classified = {}
        for s in pv[0]["mix"]:
            prim_classified.setdefault(s["category"], []).append(s["file_path"])
        bpm, bpm_meta, bpm_flags = _resolve_project_bpm(prim_classified, fn_bpm)
        if bpm is None:
            raise ValueError("Could not auto-detect BPM; pass it explicitly.")
        print("\nBPM " + _fmt_bpm(bpm) + " — " + bpm_meta["source"]
              + (("  <-- " + bpm_flags[0]) if bpm_flags else ""))
    bpm = float(bpm)

    mv_skipped = []
    mv_peak = None
    for p in pv:
        bounce_name = project_name + " " + p["vname"] + " FLAT REF.wav"
        bounce_path = p["vdir"] / bounce_name
        if p["mix"]:
            summary = sum_stems_to_wav([s["file_path"] for s in p["mix"]], bounce_path)
            p["bounce_path"] = bounce_path
            p["bounce_rel"] = p["rel_prefix"] + bounce_name
            mv_skipped += list(summary.get("skipped", []))
            if mv_peak is None:
                mv_peak = round(float(summary["peak"]), 3)   # primary version's peak
            print("  " + p["name"] + " flat bounce: " + str(summary["n_summed"]) + " stems")
            if summary["skipped"]:
                print("  WARNING skipped (sample-rate mismatch): " + ", ".join(summary["skipped"]))
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
        # A long pre-kick intro can drive base_start below 0. Clamp the whole
        # version offset (not each clip) so it stays internally in sync — the
        # kick just lands a little later rather than the clips desyncing.
        base_start = max(0.0, bar_cursor - fb_beats)
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

    # Nested sub-groups on the primary (shared) tracks — later-version clips ride
    # the same tracks, so tagging the primary layer sub-groups every version.
    # _apply_subgroups only reorders (same track objects), so track_by_elem below
    # still resolves for stacking the later versions' clips.
    scope = SUBGROUP_CATEGORIES if subgroup_categories is None else tuple(subgroup_categories)
    if scope:
        all_stems = _apply_subgroups(all_stems, scope)

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

    # Wire in any master/reference the user pre-seeded into the target folder as
    # a red match track (single clip — a pre-seeded master isn't per-version).
    preseeded_refs = [f for f in preseeded
                      if f.stem.lower() not in source_names
                      and "FLAT REF" not in f.name.upper()]
    for f in preseeded_refs:
        dest = audio_folder / f.name
        if f.parent != audio_folder and not dest.exists():
            shutil.copy2(f, dest)
        print("  wiring in pre-seeded reference: " + f.name)
        all_stems.append({"name": f.stem, "clip_name": f.stem,
                          "category": "reference", "color": REF_TRACK_COLOR,
                          "file_path": dest, "rel_path": "Audio/" + f.name,
                          "regions": None, "base_start_beat": offsets[0],
                          "extra_clips": []})

    # 'ref' / 'updated stems' subfolders carried by a multi-version pack. Refs go
    # on one 'References' track to the RIGHT of the last version (key-mapped drop
    # locators); updated stems are parked muted in their own colour for A/B.
    content_end = max(offsets[k] + pv[k].get("length_beats", 0.0)
                      for k in range(len(pv)))
    rc_tracks, rc_locs = _make_refcompare_track(
        refcompare_files, audio_folder, content_end, bpm)
    all_stems += rc_tracks
    locators = list(locators) + rc_locs
    mv_updated_names = []
    for f in updated_files:
        dest = audio_folder / f.name
        if not dest.exists():
            shutil.copy2(f, dest)
        regions, _peak = find_audio_regions(dest, return_peak=True)
        print("  updated stem (A/B, muted, own colour): " + f.name)
        all_stems.append({"name": f.stem + " (updated)", "clip_name": f.stem,
                          "category": "music", "color": UPDATED_TRACK_COLOR,
                          "file_path": dest, "rel_path": "Audio/" + f.name,
                          "regions": regions, "muted": True, "updated": True,
                          "base_start_beat": offsets[0], "extra_clips": []})
        mv_updated_names.append(f.stem)

    # Leftovers: any pack audio not claimed by a version or special folder. Never
    # dropped — parked at the bottom as a muted red reference track (Ext. Out) so
    # nothing is lost, and flagged for Sam to place. (Catches a top-level supplied
    # master, a name-token minority stem, or a stray file.)
    leftover_names = []
    for f in leftover_files:
        dest = audio_folder / f.name
        if not dest.exists():
            shutil.copy2(f, dest)
        all_stems.append({"name": f.stem, "clip_name": f.stem,
                          "category": "reference", "color": REF_TRACK_COLOR,
                          "file_path": dest, "rel_path": "Audio/" + f.name,
                          "regions": None, "muted": True,
                          "base_start_beat": offsets[0], "extra_clips": []})
        leftover_names.append(f.stem)
    if leftover_names:
        print("  leftover (parked, muted, review): " + ", ".join(leftover_names))

    als_path = project_folder / (project_name + ".als")
    print("\nPatching template (" + str(len(all_stems)) + " tracks)...")
    patch_project(template_path=get_template_path(), output_path=als_path,
                  stems=all_stems, bpm=bpm, project_audio_dir=audio_folder,
                  locators=locators)
    als_flags = _validate_als_flags(als_path, float(bpm))

    bars = [str(int((locators[i][0] - CLIP_START_BEATS) / 4) + 33) for i in range(len(pv))]
    print("\nMulti-version project created: " + str(project_folder))
    print("  BPM " + str(int(bpm)) + " | versions at bars: "
          + ", ".join(pv[i]["name"] + "=" + bars[i] for i in range(len(pv))))

    primary_tracks = [t for t in all_stems if t.get("category") not in ("reference", "bus")]
    report = {
        "project_name": project_name, "artist": artist, "title": title, "label": label,
        "als_name": als_path.name,
        "bpm": float(bpm),
        "bpm_source": bpm_meta["source"] if bpm_meta else None,
        "bpm_residual_ms": bpm_meta["residual_ms"] if bpm_meta else None,
        "bpm_inliers": bpm_meta["inliers"] if bpm_meta else None,
        "bpm_onsets": bpm_meta["onsets"] if bpm_meta else None,
        "tracks_total": len(all_stems),
        "categories": {cat: cat_counts[cat]
                       for cat in sorted(cat_counts, key=lambda c: CATEGORIES[c]["order"])},
        "groups": _build_groups_report(primary_tracks),
        "buses": sorted({s["orig_name"] for p in pv for s in p["buses"]}),
        "dry_parked": [], "silent": [],
        "references_supplied": sum(len(p["refs"]) for p in pv),
        "references_preseeded": len(preseeded_refs),
        "updated_stems": [Path(f).stem for f in updated_files],
        "refcompare": [Path(f).stem for f in refcompare_files],
        "flat_ref_peak": mv_peak,
        "skipped": mv_skipped + mv_pre_skipped,
        "flags": (_collect_flags(mv_updated_names, mv_skipped + mv_pre_skipped, [], bpm_flags)
                  + _analysis_off_flags() + als_flags
                  + ([str(len(leftover_names)) + " file(s) weren't matched to a "
                      "version — parked muted at the bottom for you to place: "
                      + ", ".join(leftover_names)] if leftover_names else [])),
        "multiversion": True,
        "versions": [p["name"] for p in pv],
    }
    _write_session_report(project_folder, report)
    apply_ableton_folder_icon(project_folder)

    # Remove the per-version WAV-conversion scratch dirs — these sit INSIDE the
    # project's Audio/ (unlike the single-version OS-temp dir), so leaving them
    # would clutter the delivered project and confuse a later rebuild's ref scan.
    for st in audio_folder.rglob("_wav_staging"):
        shutil.rmtree(st, ignore_errors=True)

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
