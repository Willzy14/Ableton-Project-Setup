# Ableton Project Setup — Copilot Instructions

## What This Is
A Python tool that takes a folder of raw stems and creates a fully laid-out Ableton Live 12.3 project (.als) matching Sam Wills' mixing workflow — track order, colours, groups, BPM detection, no warping.

## Key Technical Rules
- **NEVER use XML parsing libraries** (xml.etree, lxml) on ALS files. ALS files are gzipped XML but must be patched as raw text lines. See `Automated DJ Mixes/Documentation/ABLETON_INTERACTION.md` for the full reference.
- **Line endings must be `\r\n`** — mixing `\n` and `\r\n` corrupts the file silently.
- **Stems are placed unwarped** — `IsWarped Value="false"` on all AudioClips.
- **IDs must be unique** — allocate from a high base (50000+) to avoid collision with template IDs.
- **BPM is detected from percussive stems** (kick or snare) and set as global tempo on the MainTrack.

## Activity Log
Read and update `.github/ai-activity-log.md` at the start and end of every task.

## Project Structure
```
Ableton Project Setup/
  Source/              # Python code
  Templates/           # Reference ALS templates
  Documentation/       # AI_CONTEXT.md, specs
  .github/             # memory.json, activity log, this file
```

## Current Status (2026-06-25 EOD) — what NOT to rebuild
- ✅ **BPM auto-detect** (`bpm_detector.py`), **clip naming** (track=display, clip=original).
- ✅ **Classifier + audio full-mix detection** (`stem_analysis.py`) — filenames + crest/bands/sustain; full mixes (incl. "Current") → red refs, out of the sum.
- ✅ **Flat-ref bounce** (`bounce.py`, numpy+stdlib) — single track, colour **14 (red)**, muted, Ext. Out. Replaced the old ref GroupTrack.
- ✅ **Working-track grouping** incl. **bass** (category colour); **group-bus detection** (sum-of-others → colour 37 peach, muted, bottom, out of sum).
- ✅ **numpy** in `bounce.py` + `find_audio_regions` (fixes 3.14 crash, faster; region-identical fallback).
- ✅ **Multi-version packs** (`versions.py` + `build_multiversion_project`) — extended/radio on shared tracks, 16-bar sections, per-version flat-mix/refs/buses, Extended/Radio Edit markers.
- 🔴 **#1 BUG (fix tomorrow): multi-version radio section is OFF-GRID** — align by first ACTUAL kick onset (not the folded grid phase); BPM rounding (127.71→128) also drifts unwarped audio. See AI_CONTEXT Known Issues #1.
- ⚠️ Machine runs **Python 3.14.0** (miscompiles hot loops) — **install 3.13 first tomorrow**; use `PYTHON_JIT=0` meanwhile.
- **Next**: 3.13 → off-grid fix → name-token versions (Get Right) → wet/dry.
