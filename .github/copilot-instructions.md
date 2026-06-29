# Ableton Project Setup - Copilot Instructions

## What This Is
A Python tool that takes a folder of raw stems and creates a fully laid-out Ableton Live 12.3 project (`.als`) matching Sam Wills' mixing workflow: track order, colours, groups, BPM detection, no warping.

## Key Technical Rules
- Never use XML parsing libraries (`xml.etree`, `lxml`) to write ALS files. ALS files are gzipped XML but must be patched as raw text lines. See `Automated DJ Mixes/Documentation/ABLETON_INTERACTION.md`.
- ALS line endings must remain CRLF. Mixed endings can corrupt files silently.
- Stems are placed unwarped: `IsWarped Value="false"` on all audio clips.
- IDs must be unique. Allocate from a high base (`50000+`) to avoid template collisions.
- BPM is detected from percussive stems and written to both MainTrack manual tempo and tempo automation.
- Source stem folders, especially Finished Stem Mixes, are copy-only. Never move source stems.

## Activity Log
Read and update `.github/ai-activity-log.md` at the start and end of every task.

## Project Structure
```
Ableton Project Setup/
  Config/              # Local project_builder defaults
  Source/              # Python code
  Templates/           # Reference ALS templates
  Documentation/       # AI_CONTEXT.md, specs, toolbox
  Tests/               # Regression tests
  .github/             # memory.json, activity log, this file
```

## Current Status (2026-06-29 EOD)
- Done: FIRST REAL PRODUCTION RUN — built `Replicage - Amen [Sound Better]` into `2. Ongoing Stem Mixes` (single-version; radio/extended/dub baked end-to-end into one long timeline per stem).
- Done: wet/dry handling — VOCALS ONLY, explicit WET+DRY pairs only. WET stays on; DRY parked in a muted, collapsed grey "Dry" group, out of the flat-ref sum. `stem_classifier.find_dry_stems` + vocals filter in `build_project`.
- Done: empty/silent stems (peak < `als_patcher.SILENCE_FLOOR_DB` -60 dBFS) moved to the very bottom with their own colour (`SILENT_TRACK_COLOR` 12), out of layout + sum. `find_audio_regions(return_peak=True)`.
- Decision: BPM always rounded (whole or half), never warp — closes the precise-BPM question.
- Done: BPM auto-detect (`Source/bpm_detector.py`) and clip naming (track = simplified display, clip = original filename).
- Done: classifier plus audio full-mix detection (`Source/stem_analysis.py`): full mixes and refs stay out of the flat sum.
- Done: flat-ref bounce (`Source/bounce.py`): one red muted Ext. Out reference track, not a reference group.
- Done: working-track grouping including bass, plus group-bus detection for sum-of-others stems.
- Done: optional ML classifier (`Source/audio_ml_classify.py`) for filename-unknown stems, using Demucs source bins and optional Whisper vocal confirmation.
- Done: canonical validator (`Source/validate_project.py`). Use `py -3.13 Source\validate_project.py "<project-folder-or-als>" --expect-tempo <bpm>`.
- Done: config/env defaults in `Config/project_builder.json`, overridden by `ABLETON_TEMPLATE_PATH`, `ABLETON_OUTPUT_BASE`, `PYTHON_ML_EXE`, and `ENABLE_ML_CLASSIFIER`.
- Done: multi-version builds run ML classification per version and lay versions on shared tracks with per-version flat refs.
- Done: Fallon radio-edit alignment corrected. Later-version stacks are placed on phrase slots, then the whole stack is nudged together using the earliest credible kick-named layer. `Test Builds 2\Fallon - No Panties [Black Book CODEX VERIFY 6] Project` matches Sam's manual `SW Fix` clip starts within about `0.0012` beats.

## Python
- Use explicit `py -3.13` for normal builds and tests.
- Python 3.13.14 is installed at `C:\Users\Carillon\AppData\Local\Programs\Python\Python313\python.exe`.
- Python 3.13 has `numpy`, `soundfile`, `torch 2.12.1+cpu`, `torchaudio 2.11.0+cpu`, `demucs 4.0.1`, and `faster-whisper 1.2.1` installed and import-verified.
- The launcher still defaults to Python 3.14; avoid it unless forced.

## Next Priority
1. **Studio UI front-end** (discussed 2026-06-29) — drag-drop WAV/AIFF/ZIP, multi-project queue with a "+" to add projects and a per-project title field, a static "select output folder" set once at start, and a per-user colour setup (Ableton palette indices for drums/bass/music/vox/fx). Drop files + titles for the day's projects, hit Go, come back to a folder of fully set-up projects. Wraps the existing `build_project` engine.
2. Add ML subprocess cleanup and timeout handling.
3. Add same-folder version-token detection, e.g. Get Right `S16` vs `S17 -SHRT EDIT`.
4. Consider applying wet/dry + silent-stem handling to the multi-version build path too (currently single-version only).
