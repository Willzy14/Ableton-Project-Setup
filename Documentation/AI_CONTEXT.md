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

Local interpreter note (2026-06-26): Python 3.13.14 is installed and should be used explicitly via `py -3.13`; it has `numpy`, `soundfile`, `torch 2.12.1+cpu`, `torchaudio 2.11.0+cpu`, `demucs 4.0.1`, and `faster-whisper 1.2.1` installed. The launcher still defaults to Python 3.14, which has shown instability.

## Architecture
```
Ableton Project Setup/
  Config/
    project_builder.json     # Local defaults for template/output/ML settings
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
**Moby fresh rebuild re-verified (2026-06-29, Claude).** Independent re-validation + clean redelivery of the Codex 06-26 work — no source changes (head `6310fd6`). Rebuilt `C:\Users\Carillon\Desktop\Mobi Project\Mobi.als` from scratch: consensus `detect_project_bpm()` auto-selected **160 BPM** from `hh_03.wav` (248/248 on grid) / `sn_03.wav` (57/57), rejecting the syncopated kick's 104 — i.e. Sam's "line the snares up on the grid" trick, now programmatic. 47/47 filename-unknown stems audio-classified by Demucs+Whisper (37 vox / 3 drums / 2 bass / 5 music; Whisper transcribed real lyrics off the vocal layers). Standalone ALS inspector confirms 56 tracks + Drums/Bass/Music/Vox groups + red rough-ref & flat-ref, project tempo (manual **and** automation) = 160. ML classifier separately re-validated against Nurko ground truth = 9/10 big-bucket at full confidence. Ready for Sam + partner to open. (Sidebar: the repo is Dropbox-synced; Codex's committed work synced in mid-session, so the on-disk code was already ahead of the session summary.)

**Moby unnamed-stem test built on Desktop (2026-06-26).** Claude added a second-stage ML classifier for stems whose filenames have no usable instrument label: `Source/audio_ml_classify.py` runs Demucs as a source-bin classifier (drums/bass/other/vocals) and uses Whisper only to confirm vocal-like stems. Codex validated the generated output at `C:\Users\Carillon\Desktop\Mobi Project\Mobi.als`: 62 tracks, grouped Drums/Bass/Music/Vox, 55 source WAVs copied plus `Mobi FLAT REF.wav`, and `ML Classification Report.txt` showing 47 audio-classified stems. The source folder was `C:\Users\Carillon\Desktop\for now 160 multitracks 24 441`. Treat this as a real-world validation run, but still review in Ableton by ear because many generic `Audio XX` stems were classified as Vox from Demucs energy and partial Whisper transcripts.

**Moby tempo correction (2026-06-26).** The first Moby build was incorrectly set to 104 BPM because `detect_project_bpm()` returned the first kick result even though it was low confidence. Sam identified the correct tempo as 160 by lining up the snare stem on the grid. Codex changed `detect_project_bpm()` to score every kick/drum/bass candidate by grid-lock quality. It now also prefers consensus: if multiple credible stems round to the same BPM, that BPM wins before picking the cleanest individual stem. For Moby, `sn_03.wav` and `hh_03.wav` agree at 160 with all inliers and sub-ms residual, beating the syncopated kick (104 BPM, poor inliers). Regression: `Tests/test_moby_tempo_selection.py`.

**Moby ALS actually fixed for Ableton (2026-06-26).** Sam reported `C:\Users\Carillon\Desktop\Mobi Project\Mobi.als` still opened at 104. Root cause: the MainTrack `Tempo/Manual` value had been patched to 160, but the tempo automation envelope for `PointeeId Value="8"` still contained `<FloatEvent ... Value="104" />`, which Ableton used as the displayed/project tempo. Codex backed up the old file to `C:\Users\Carillon\Desktop\Mobi Project\Backup\Mobi 104 Tempo Automation Backup.als`, patched the live `Mobi.als` with `als_patcher.set_global_tempo(..., 160)`, and verified there are now zero `Value="104"` entries; both Main tempo and tempo automation read 160. `Source/als_patcher.py::set_global_tempo()` is the canonical fix path for future builds because it updates both locations.

**Fresh Moby rebuild for partner review (2026-06-26).** Sam deleted the old patched Moby project because changing tempo after the first build moved already cut-up clips. Codex rebuilt from scratch from `C:\Users\Carillon\Desktop\for now 160 multitracks 24 441` into `C:\Users\Carillon\Desktop\Mobi Project\Mobi.als`, using Python 3.14 with `PYTHON_JIT=0` so the ML stack was available. The rebuild classified 47/47 unnamed stems by audio, selected 160 BPM from `hh_03.wav`, wrote Main tempo and tempo automation at 160 from the start, and produced 56 WAV files including `Mobi FLAT REF.wav`. Validation: `Source\validate_project.py` PASS, manual tempo 160, automation tempo 160, zero `Value="104"` entries, 146 audio clips, 146 unwarped clips, Moby tempo regression PASS.

**Validator, multi-version, config, and Python follow-up (2026-06-26).** Codex added `Source/validate_project.py` as the canonical ALS/project validator and `Tests/test_validate_project.py`, including the tempo-automation mismatch check that catches the Moby 104/160 issue. Codex also fixed `_process_version_files()` so multi-version builds now run the same ML classification step for true filename-unknown stems instead of dumping them straight into `music`; per-version ML reports are written as `ML Classification Report - <Version>.txt`. Multi-version alignment now uses `first_actual_onset_sec` from `bpm_detector.detect_bpm()` instead of the folded `first_beat_sec` grid phase, so versions with pre-roll/pickup can land their first real rhythmic onset on the intended bar. `Config/project_builder.json` now holds local defaults for template/output/ML settings, with env overrides for `ABLETON_TEMPLATE_PATH`, `ABLETON_OUTPUT_BASE`, `PYTHON_ML_EXE`, and `ENABLE_ML_CLASSIFIER`. Python 3.13 now has the full ML stack import-verified, so normal builds should run with `py -3.13`. Regressions: `Tests/test_validate_project.py`, `Tests/test_multiversion_ml_classification.py`, `Tests/test_multiversion_alignment.py`, `Tests/test_project_config.py`.

**Real Fallon radio-edit verification corrected (2026-06-26).** Codex rebuilt Fallon from the Finished Stem Mixes source folder, copying stems only: `C:\Users\Carillon\Wired Masters Dropbox\Sam Wills\2.1. Finished Stem Mixes\Fallon - No Panties [Black Book] Project\Audio`. The correct alignment model is: place the later-version stack at the next phrase slot after the extended version, then nudge the whole stack by one shared amount so the earliest credible kick-named layer lands on-grid. This handles radio edits with no dry kick at the start. Verification output is `Test Builds 2\Fallon - No Panties [Black Book CODEX VERIFY 6] Project`. It uses beat `1024.0` as the kick-grid target, starts the Radio Edit stack/locator around beat `1020.992` because the processed kick layer begins about 1.41s into its file, and matches Sam's manually aligned `SW Fix` clip starts within about `0.0012` beats.

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
1. **Multi-version drift still needs a policy decision** — the first-onset alignment bug is fixed in code (`first_actual_onset_sec` now drives version placement), but the separate precise-BPM drift issue remains: if detected BPM is 127.71 and project tempo is rounded to 128, unwarped clips can drift against the grid across a long section. Consider setting the project tempo to the precise detected BPM, or discuss warping with Sam.
2. **Group-bus detection needs energy in the analysed window** — a bus silent in the first 180 s won't be matched (contributes ~nothing anyway); heavily post-processed buses (not an exact sum) may slip past.
3. **Silence-trim is iteration 1** — Sam confirmed trims look tight/good on the single-version packs.
4. **Python 3.14.0 interpreter instability** — intermittent AND sometimes persistent miscompiles of hot pure-Python loops (bogus TypeError / segfault / "int not iterator"). Python 3.13.14 is now installed with the normal and ML dependencies; use `py -3.13` explicitly for builds. The launcher still defaults to 3.14.

## What's Next
0. **Sam checks the fresh rebuilt Moby project in Ableton** at `C:\Users\Carillon\Desktop\Mobi Project\Mobi.als`; both manual tempo and tempo automation are verified at 160 BPM from project creation, not patched after the fact.
0. **Continue Codex handoff list:** `Documentation/CODEBASE_REVIEW_NEXT_STEPS.md` now marks Sections 1-5 completed; continue with ML subprocess cleanup/timeouts next.
0. **Review/commit ML classifier work** from 2026-06-26 (`Source/audio_ml_classify.py`, `project_builder.py`, `stem_classifier.py`) after Sam checks the Moby project in Ableton.
1. **Use Python 3.13 explicitly** (`py -3.13`) for normal builds.
2. **Decide precise-BPM policy for multi-version drift** (known-issue #1 above) — exact detected BPM vs rounded BPM vs warping.
3. **Same-folder name-token versions** — Get Right `S16` vs `S17 -SHRT EDIT` (reuses the multi-version engine; extend `versions.detect_versions` to split a single folder's mirror sets by a name token).
4. **Wet/dry** — wet ON (normal tracks); dry grouped + muted underneath.

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
| **Versions** | extended / radio edit / dub — same song, different arrangements. Packaged either as a **subfolder** (e.g. Fallon `Edit STems/`) or a **same-folder name-token** (e.g. Get Right `…S16…` vs `…S17 -SHRT EDIT…`) | Lay out as separate **timeline sections** down the arrangement: Extended first, then later versions on the next phrase slot after the extended, currently next 32-bar boundary after the configured 16-bar minimum gap. Then nudge the whole later-version stack by one shared amount so the earliest credible kick-named layer is on-grid. Each element shares ONE track across versions (kick-on-kick) so per-track processing hits all versions. A **flat-mix bounce under each version**. |
| **Category subfolders** | `drum stems/`, `vox stems/`, `instrument stems/` — one version split by type | **Flatten / stack** into the single version (walk the tree, pull them all in). Their elements are unique (don't mirror), which is how they're told apart from version subfolders. |
| **Wet/dry** | same elements provided both wet and dry | **Wet ON** (normal tracks); **dry grouped + muted, parked underneath** the wet (kept for recall). |
| **Group buses** | a stem = sum of others | DONE — muted/grey at bottom, out of the sum. |
| **Full mixes / masters** | 2-mix, master, bounce | DONE — red refs (per version, under each section). |

**Detection rule (versions vs category):** a subfolder whose element keys (filename after the last `_`, normalised) **mirror** the top-level stems (≥50% overlap) is an alternate VERSION; otherwise it's a CATEGORY subfolder and gets flattened in. `Source/versions.py::detect_versions()` does this — validated: Fallon → Extended + Edit STems with 39/39 elements paired; flat packs → None.

**Build status:** version detection + LAYOUT ENGINE done + validated on Fallon. `build_multiversion_project()` in project_builder processes each version independently (classify → full-mix → bus-detect → flat bounce), pairs elements across versions onto shared tracks (clip inserter now takes a `base_start_beat` offset and stacks multiple clips per track), places later-version stacks on phrase slots, then applies one shared kick-grid nudge per version. Fallon CODEX VERIFY 6 matches Sam's `SW Fix` clip starts within about `0.0012` beats. Single-version packs route around all of this (detect_versions → None). Still to build: same-folder name-token version detection (Get Right S16/S17), and wet/dry (wet on, dry grouped+muted under).

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
