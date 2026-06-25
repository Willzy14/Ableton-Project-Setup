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

## Current Status (2026-06-25) — what NOT to rebuild
- ✅ **BPM auto-detection** — `Source/bpm_detector.py` (pure-stdlib kick onset + lattice fit). `project_builder` bpm arg is optional.
- ✅ **Clip naming** — track name = display ("DR Kick"), clip name = original filename ("Kick").
- ✅ **Classifier patterns** — BVs→vocals, Ref Bounce→reference, Tops/Fills/CABASA/DRM_*→drums.
- ✅ **Flat reference** — single bounced track (`Source/bounce.py`), colour 37, muted, Ext. Out, last. Supplied refs kept as separate match tracks. NO ref GroupTrack.
- ✅ **Working-track grouping** — drums/music/vocals/fx with 2+ stems → GroupTrack (audible, Main, expanded, category colour). Kick/bass/sends standalone.
- ✅ **bounce.py** uses numpy when present (~15×) with bit-identical stdlib fallback.
- ⚠️ Machine runs **Python 3.14.0** — saw a one-off transient JIT TypeError; re-run if a build crashes oddly.
- **Next**: optional INST→music, optional Bass group, optional 24-bit RMS speedup.
