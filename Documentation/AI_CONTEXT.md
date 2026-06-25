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
    als_patcher.py           # Template patching engine + silence/region detection
    stem_classifier.py       # Stem name → track type mapping (filename rules)
    stem_analysis.py         # Audio analysis (numpy) — full-mix + group-bus detection
    bpm_detector.py          # BPM detection from kick (pure stdlib)
    bounce.py                # Flat-reference stem summing (numpy + stdlib fallback)
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

**Flat reference is now a single bounced track, not a group (2026-06-25).** The duplicated-stems GroupTrack is gone. `bounce.py` sums the mix stems into one flat-ref track at the bottom: colour 14 (red), muted, Ext. Out. Supplied ref/master files are kept as separate match tracks (same treatment), never summed. Verified on a real ALS build: no GroupTrack, FLAT REF last + ext + muted, supplied "Ref Bounce" kept as a match track, working tracks untouched. **This retired the "ref group opens expanded" bug.**

**Tighter silence trimming + bass grouping + red refs (2026-06-25, Sam feedback).** Reference tracks recoloured red (14, was 37). Bass is now groupable (a "Bass" group when 2+ bass stems). `find_audio_regions` retuned to hug the audio tighter without chopping tails: window 0.25→0.1 s, headroom 40→55 dB (a wide threshold follows reverb/crash/fill decays down so they're never cut), min-gap 10→2.5 s (real silence splits into tight separate clips), tail 3→1 s. FX keep a 2 s lead-in for risers.

**Classifier hardening + audio-content analysis (2026-06-25).** A test batch of 5 random finished mixes exposed two real gaps on messy packs: (1) full mixes/masters named cryptically (e.g. "Current", "(TEST MIX)") were classified as music and **summed into the flat ref**, polluting it (Far Away bounce peaked 3.85); (2) a kick named just "K" wasn't recognised. Fixes: added filename patterns (`TEST MIX`/`ROUGH MIX`/`SCRATCH MIX`→reference; `K`/`KCK`→kick), and a new **`stem_analysis.py`** (numpy FFT) that, when a filename can't place a music/unclassified file, decides if the audio is a full mix and if so moves it to references (out of the sum). The full-mix rule — **crest ≤ 5 (mastered-loud) + 6+ active bands (broadband) + sustain ≥ 0.6** — was tuned against labelled real files and cleanly separated every real full mix (Ref Bounce, TEST MIX, SW Flat Mix, Far Away Master *and* Current) from every individual stem. Audio kick-detection was deliberately dropped (kick vs bass overlap too much; filenames handle it). Falls back to filename-only when numpy is absent.

**Group-bus / sub-mix detection (2026-06-25).** A frequent, painful problem on big packs: a producer leaves a group *bus* (e.g. a bass bus, "All Drums") in among the individual stems — summing it double-counts and "everything sounds wrong on play". Since stems are sample-aligned (one session export), a bus is literally the sum of its members. `find_group_buses()` (numpy) runs a **non-negative greedy matching pursuit** in Gram-matrix space: a stem reconstructed to >88% of its energy by a positive sum of ≥2 other stems is a bus. Non-negativity is the key — the bus (=+1·members) is flagged but a member can't be rebuilt from the others without subtracting, so individuals are safe. Validated: caught Coldabank "All Drums" and Far Away's "BASS EGYBE" (= b + b_3, Sam's exact complaint), no false positives. Detected buses are **kept** in the project but parked at the very bottom (below the refs), coloured grey (37), **muted**, routed to Main, and **excluded from the flat-ref sum** — recall one by unmuting it. Per Sam's spec.

**Bounce uses numpy when available (2026-06-25).** `bounce.py` mixes via numpy if installed (~15× faster on a 14-stem/2-min pack: 1.9s vs 29s; scales better on bigger packs), and falls back to a pure-stdlib path when numpy is absent — output is bit-identical between the two (verified). So the tool stays install-free but is fast where numpy exists.

**Working-track grouping implemented (2026-06-25).** Each groupable category with 2+ stems (drums, music, vocals, fx — per `CATEGORIES[cat]["group"]`) is wrapped in a GroupTrack: audible, routed to Main, expanded, coloured with the category colour; children route to `AudioOut/GroupTrack` with matching `TrackGroupId`. Group names: Drums / Bass / Music / Vox / FX. Kick, sends and any single-stem category stay standalone. Reused the canonical 12.4 GroupTrack template (now parametrised for muted/unfolded). Verified on real builds: Coldabank (Bass×2, Drums×5, Music×2, Vox×3; kick standalone) and Ak1ra (adds FX×2 group; 24-bit stems).

**Known issues / not yet working**:
1. **Python 3.14.0 transient interpreter glitch** — the machine runs Python 3.14.0 (a brand-new release with an experimental JIT/adaptive specializer). Hit a one-off bogus `TypeError: 'int' object is not an iterator` inside `find_audio_regions` that vanished on re-run (the bytecode and `range` are both correct). If a build ever crashes with a weird TypeError, just re-run; if it recurs often, installing stable Python 3.13 would eliminate it.
2. **Group-bus detection needs energy in the analysed window** — a bus that's silent in the first 180 s (some producer "Group"/"TAKE" exports are near-silent there) won't be matched; but such stems contribute ~nothing to the sum anyway. Buses with heavy post-bus processing (so they're no longer an exact sum of members) may also slip past — revisit if it shows up.
3. **Silence-trim tuning is iteration 1** — values (headroom 55 / min-gap 2.5 / tail 1.0) hug tighter; needs Sam's eye to confirm nothing audible is chopped.
4. **Python 3.14.0 transient interpreter glitch** — one-off bogus `TypeError` inside `find_audio_regions` that vanished on re-run; the per-build retry in the batch script absorbs it. If a real build crashes oddly, re-run; stable Python 3.13 would eliminate it.

## What's Next
1. Sam to eyeball the Test Builds projects in Ableton — confirm trim tightness, grouping, red refs, and that full mixes are out of the flat ref
2. Optional: detect sub-group/bus bounces (drum "Group" etc.) to keep them out of the sum too
3. Optional: speed up `find_audio_regions` 24-bit RMS (the slow part of large 24-bit builds; numpy could help here too)

## Key Decisions
- **No XML libraries** — ALS files are patched as raw text lines per ABLETON_INTERACTION.md. `xml.etree.ElementTree` would corrupt the format.
- **No warping** — all stems placed with `IsWarped="false"`. Stems arrive at the correct BPM.
- **BPM from percussion** — kick or snare is the most reliable BPM source. Global tempo is set from this.
- **Template-based approach** — start from a known-good ALS file saved by Ableton, patch in stems dynamically.
- **Track AND clip colours match** — both set to the same palette index per category (6/24/8/13/55/17/14). Sam's existing projects only had clip colours set, but the tool now sets both for consistency.
- **Flat reference track (2026-06-25, replaced the group)** — instead of duplicating every stem into a summing group, the tool now prints a single **flat bounce** of the mix stems (sum → 32-bit float WAV, [bounce.py](Source/bounce.py); numpy fast path + stdlib fallback) as one track at the very bottom: colour 14 (red), muted, output routed to **Ext. Out** (bypasses the master chain). A supplied "ref"/"riff"/master file is NEVER trusted to be the flat sum (it may be someone else's track or a limited master) — we always print our own bounce, and keep any supplied reference as its own match track (same red / muted / Ext. Out treatment). This also retired the long-standing "ref group opens expanded" bug — there is no group any more.
- **Working-track grouping (2026-06-25)** — groupable categories (drums, bass, music, vocals, fx) with 2+ stems get a GroupTrack coloured with the category colour, audible, routed to Main, expanded; children route to `AudioOut/GroupTrack`. Kick and sends never group. Group/child structure mirrors Sam's real finished projects.
- **Group-bus detection (2026-06-25)** — exploits that stems are sample-aligned: a stem reconstructed by a non-negative sum of ≥2 others is a group/sub-mix bus. Such buses are parked muted/grey at the very bottom and excluded from the flat-ref sum, instead of double-counting. Non-negativity flags the bus, never its members. Sam: this is a big, frequent problem on real packs ("press play and everything sounds wrong"), so worth the dedicated detector.
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
| 14 | Reference tracks (red) | flat bounce + any supplied ref/master; muted, routed to Ext. Out, at the bottom |
| 37 | Group buses (grey) | detected sum-of-others stems; muted, Main out, very bottom (below refs), excluded from sum |

### Track Order
1. **Session Time** — always first, track color 27, HOFA Project Time plugin, no audio
2. **Kick** — standalone, never grouped, clip color 6
3. **Drums** — hats, snares, claps, perc — grouped when multiple stems, clip color 6
4. **Bass** — grouped when multiple stems (else standalone), clip color 24
5. **Music** — synths, chords, keys, pads, strings, instruments — clip color 8
6. **Vocals** — grouped when multiple, clip color 13
7. **FX** — grouped when multiple, clip color 55
8. **Sends** — reverb/delay stems if provided, clip color 17
9. **Supplied reference tracks** (if any) — each kept as its own match track, color 14 (red), muted, Ext. Out
10. **Flat Reference bounce** — single summed bounce of the mix stems, color 14 (red), muted, Ext. Out
11. **Group buses** (if detected) — sum-of-others stems, VERY bottom (below refs), color 37 grey, muted, Main out, excluded from the sum

### Grouping Rules (implemented 2026-06-25)
- **Group when 2+ stems** in a *groupable* category: drums, bass, music, vocals, fx (`CATEGORIES[cat]["group"]`). Group is audible, routed to Main, expanded, coloured with the category colour.
- Group names: **Drums / Bass / Music / Vox / FX**. Children route to `AudioOut/GroupTrack` with matching `TrackGroupId`.
- **Kick and sends are never grouped** (standalone), even with multiple stems.

### Stem Package Shapes (how producers deliver stems) — feature in progress (2026-06-25)
Real packs aren't always one flat folder of stems. The builder must resolve the folder tree and lay things out accordingly:

| Shape | What it is | Desired handling |
|-------|-----------|------------------|
| **Versions** | extended / radio edit / dub — same song, different arrangements. Packaged either as a **subfolder** (e.g. Fallon `Edit STems/`) or a **same-folder name-token** (e.g. Get Right `…S16…` vs `…S17 -SHRT EDIT…`) | Lay out as separate **timeline sections** down the arrangement: Extended first, then a **fixed 16-bar gap**, then Radio edit, then any further versions. Each element shares ONE track across versions (kick-on-kick) so per-track processing hits all versions. A **flat-mix bounce under each version**. |
| **Category subfolders** | `drum stems/`, `vox stems/`, `instrument stems/` — one version split by type | **Flatten / stack** into the single version (walk the tree, pull them all in). Their elements are unique (don't mirror), which is how they're told apart from version subfolders. |
| **Wet/dry** | same elements provided both wet and dry | **Wet ON** (normal tracks); **dry grouped + muted, parked underneath** the wet (kept for recall). |
| **Group buses** | a stem = sum of others | DONE — muted/grey at bottom, out of the sum. |
| **Full mixes / masters** | 2-mix, master, bounce | DONE — red refs (per version, under each section). |

**Detection rule (versions vs category):** a subfolder whose element keys (filename after the last `_`, normalised) **mirror** the top-level stems (≥50% overlap) is an alternate VERSION; otherwise it's a CATEGORY subfolder and gets flattened in. `Source/versions.py::detect_versions()` does this — validated: Fallon → Extended + Edit STems with 39/39 elements paired; flat packs → None.

**Build status:** version detection + LAYOUT ENGINE done + validated on Fallon. `build_multiversion_project()` in project_builder processes each version independently (classify → full-mix → bus-detect → flat bounce), pairs elements across versions onto shared tracks (clip inserter now takes a `base_start_beat` offset and stacks multiple clips per track), lays versions out at `VERSION_GAP_BARS` (16) gaps, flat-ref bounce under each version. Fallon → Extended@bar33 + Edit STems@bar241, 36 element tracks each carrying extended + radio clips, FLAT REF with a bounce clip per version. Single-version packs route around all of this (detect_versions → None). Still to build: same-folder name-token version detection (Get Right S16/S17), and wet/dry (wet on, dry grouped+muted under).

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
