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
