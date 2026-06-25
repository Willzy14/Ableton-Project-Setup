# Ableton Project Setup

## What This Is
A Python-based tool that takes a folder of raw stems (kicks, snares, bass, vocals, etc.) and automatically creates a fully laid-out Ableton Live project matching Sam's exact mixing workflow — track order, clip colours, groups, BPM, folder structure. Stems arrive with inconsistent naming, so the tool classifies them intelligently. BPM is detected from percussive stems and set as the global tempo. No warping — stems are placed raw.

Part of the samwillsmixing.com ecosystem — speeds up the most repetitive part of starting a new mix.

## Tech Stack
- Python 3.x
- gzip (ALS decompression/compression)
- librosa or similar (BPM detection from audio)
- Template-based ALS patching (line-level text manipulation, NOT XML parsing)
- Ableton Live 12.3 format

## Architecture
```
Ableton Project Setup/
  Source/                    # Main Python code
    als_patcher.py           # Template patching engine
    stem_classifier.py       # Stem name → track type mapping
    bpm_detector.py          # BPM detection from audio
    project_builder.py       # Orchestrator — ties it all together
  Templates/                 # Reference ALS templates (Sam creates in Ableton)
  Documentation/             # AI context, specs, mix layout reference
  .github/                   # Memory, activity log
```

## How to Run
```
# BPM auto-detected from the kick stem:
python Source/project_builder.py "<stem_folder>" "<Artist>" "<Title>" "<Label>"

# Or pass BPM explicitly (overrides detection):
python Source/project_builder.py "<stem_folder>" "<Artist>" "<Title>" "<Label>" 122
```
Pure-stdlib — no `pip install` required. Standalone BPM check:
`python Source/bpm_detector.py "<kick stem>.wav"`

## Current State
**Phase: V1 working end-to-end.** Built and tested with 5 real projects (Ak1ra, Sparks, Jones - Fire In Your Eyes 130bpm, Coldabank - Never Say Sorry 134bpm, Pressure - Lucozade 125bpm). Working end-to-end: classification, BPM detection from kick onsets, multi-clip silence-aware placement, GroupTrack for ref stems, track heights (LaneHeight=17), TrackUnfolded=true on working tracks for inline waveforms.

**BPM auto-detection is now integrated (2026-06-25).** `bpm_detector.py` is a pure-stdlib module (no numpy/scipy/librosa) — algorithm borrowed from Automated DJ Mixes (`attack_onsets` + `lattice_fit`), adapted because our stems arrive pre-isolated (no Demucs needed). `project_builder` now detects BPM from the kick (fallback drums → bass) when the bpm arg is omitted or "auto"; an explicit bpm still overrides. Validated against 4 real kicks — Ak1ra 122, Coldabank 134, Jones 130, Lucozade 125 — all exact, sub-millisecond grid fits.

**Clip naming fixed (2026-06-25).** TRACK name = simplified display ("DR Kick"); CLIP name = original source filename ("Kick"). Threaded a separate `clip_name` field through `project_builder` → `patch_project` → `insert_clip_into_track`. Verified in a real generated ALS.

**Classifier patterns extended (2026-06-25).** Added: `BVs`→vocals (note the camel-splitter turns "BVs" into "b vs", handled), `Ref Bounce`→reference, `Tops`/`Fills`(plural)/`CABASA`/`DRM_*`→drums. Verified on real Coldabank + Lucozade folders; 11 regression cases held.

**Flat reference is now a single bounced track, not a group (2026-06-25).** The duplicated-stems GroupTrack is gone. `bounce.py` sums the mix stems (pure stdlib → 32-bit float WAV) into one flat-ref track at the bottom: colour 37, muted, Ext. Out. Supplied ref/master files are kept as separate match tracks (same treatment), never summed. Verified on a real ALS build: no GroupTrack, FLAT REF last + ext + muted, supplied "Ref Bounce" kept as a match track, working tracks untouched. **This retired the "ref group opens expanded" bug.** Perf note: summing is pure Python — ~32s for 14 stems @ 2 min; a 30-stem/6-min track will take a few minutes.

**Known issues / not yet working**:
1. **`INST ALL` (full instrumental bounce) still unclassified** → falls through to the music bucket with a warning. Out of scope for the 2026-06-25 pass; add `\binst\b`→music if desired.
2. `Group` (bus bounces from producer) → goes to music, OK behaviour.
3. Bounce summing is slow on large packs (pure stdlib). If it ever becomes a bottleneck, numpy would make the sum ~50× faster — a targeted dependency just for `bounce.py`.

## What's Next
1. Optional: classify `INST ALL` / instrumental bounces (currently land in music via the unclassified fallback)
2. Optional: speed up `bounce.py` (numpy) if large-pack build times become annoying

## Key Decisions
- **No XML libraries** — ALS files are patched as raw text lines per ABLETON_INTERACTION.md. `xml.etree.ElementTree` would corrupt the format.
- **No warping** — all stems placed with `IsWarped="false"`. Stems arrive at the correct BPM.
- **BPM from percussion** — kick or snare is the most reliable BPM source. Global tempo is set from this.
- **Template-based approach** — start from a known-good ALS file saved by Ableton, patch in stems dynamically.
- **Track AND clip colours match** — both set to the same palette index per category (6/24/8/13/55/17/14). Sam's existing projects only had clip colours set, but the tool now sets both for consistency.
- **Flat reference track (2026-06-25, replaced the group)** — instead of duplicating every stem into a summing group, the tool now prints a single **flat bounce** of the mix stems (pure-stdlib sum → 32-bit float WAV, [bounce.py](Source/bounce.py)) as one track at the very bottom: colour 37, muted, output routed to **Ext. Out** (bypasses the master chain). A supplied "ref"/"riff"/master file is NEVER trusted to be the flat sum (it may be someone else's track or a limited master) — we always print our own bounce, and keep any supplied reference as its own match track (same colour 37 / muted / Ext. Out treatment). This also retired the long-standing "ref group opens expanded" bug — there is no group any more.
- **Session Time track** — always first, has HOFA Project Time plugin, tracks time spent on each project. Must be in every project (comes from template).
- **Send stems are from producers** — reverb, delay, chorus stems are part of the stem pack, not created by Sam. Tool needs to classify and place them.

## Sam's Mix Layout Spec (Extracted from 100+ Projects)

### Clip Colour Coding (Ableton Palette Index)
| Index | Category | Keywords |
|-------|----------|----------|
| 6 | Drums | kick, snare, hat, clap, perc, shaker, tambourine, cymbal, break, top loop, drum fill, conga |
| 24 | Bass | bass, sub, 808, bassline, low end |
| 8 | Music | synth, chord, melody, piano, keys, pad, string, organ, stab, instrument, lead, arp, harp, drone, music, sample |
| 13 | Vocals | vocal, vox, acapella, voice, singing, lead vx, backing, harmony |
| 55 | FX | fx, effect, riser, impact, sweep, noise, texture, atmosphere, ambient, vinyl, downlifter |
| 17 | Sends | reverb, delay, chorus, echo (when provided as stems from the producer) |
| 37 | Reference tracks | flat bounce + any supplied ref/master; muted, routed to Ext. Out, at the bottom |

### Track Order
1. **Session Time** — always first, track color 27, HOFA Project Time plugin, no audio
2. **Kick** — standalone, never grouped, clip color 6
3. **Drums** — hats, snares, claps, perc — grouped when multiple stems, clip color 6
4. **Bass** — standalone, clip color 24
5. **Music** — synths, chords, keys, pads, strings, instruments — clip color 8
6. **Vocals** — grouped when multiple, clip color 13
7. **FX** — grouped when multiple, clip color 55
8. **Sends** — reverb/delay stems if provided, clip color 17
9. **Supplied reference tracks** (if any) — each kept as its own match track, color 37, muted, Ext. Out
10. **Flat Reference bounce** — single summed bounce of the mix stems, LAST track, color 37, muted, Ext. Out

### Grouping Rules
- **Group when 2+ stems** in the same category (except kick — always standalone)
- Group names: "Drums", "Vox", "FX", etc. (short, descriptive)
- Kick is NEVER inside a group, even if there are multiple kick stems

### Project Folder Structure
```
Artist - Title [Label] Project/
  Artist - Title [Label].als
  Audio/
    [all stems copied here]
  Ableton Project Info/
    AProject.ico
  Backup/
  MASTER RENDERS/
  Samples/
    Recorded/
```

### Naming Conventions
- **ALS file**: `Artist - Title [Label].als`
- **Project folder**: `Artist - Title [Label] Project`
- **Master renders**: `Artist - Title SW V1.wav`, `SW V2.wav`, etc.

## Connections
- **Automated DJ Mixes** — shares the ABLETON_INTERACTION.md reference for ALS file manipulation. Same technical foundation.
- **samwillsmixing.com** — this tool supports the mixing business by automating project setup.
- **Wren** — could eventually trigger project setup automatically when new stems arrive.
