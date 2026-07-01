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
**Backlog sweep — engine parity, name-token versions, ML hardening, output base, branding, housekeeping (2026-07-01, Claude).** Seven follow-ups cleared in one pass (all validated; full suite 13/13 green):
- **Multi-version parity** — the multi-version build path (`build_multiversion_project`) now applies **nested sub-groups** to its shared tracks (threaded `subgroup_categories` → `_apply_subgroups` on the primary layer, which every later version's clips ride) AND **wires in a pre-seeded master** from the target folder, matching the single-version path.
- **Same-folder name-token versions** — Get Right `S16` vs `S17 -SHRT EDIT` in ONE flat folder now builds as a proper 2-version project. `versions._detect_nametoken_versions` splits a flat folder by a version token (session/version code `S\d+`/`V\d+`, or radio/shrt/short/edit/dub/instrumental/extended), and `element_key` now strips those tokens so the same element pairs across versions (kick-on-kick). Deliberately conservative — needs 2+ token groups of 3+ stems that cover most of the folder and mirror each other in BOTH directions, so a normal pack with an incidental "edit"/"dub" stem is never mis-split (files never dropped). Validated e2e together with multi-version sub-groups + pre-seeded ref in `Tests/test_multiversion_parity.py`.
- **ML subprocess hardening** — `_ml_classify_unknowns` now runs Demucs with a **timeout** (`get_ml_timeout_sec`: base + per-stem budget, config/`ML_TIMEOUT_SEC` overridable) so a hung subprocess can't stall the build (falls back to music on timeout), and the temp scratch dir is **always cleaned up** in a `finally` (was leaking one per build).
- **Default output base moved off the repo root** — `DEFAULT_OUTPUT_BASE` + `Config/project_builder.json` now point at `2. Ongoing Stem Mixes` (env/config still override; the Studio App uses its own output setting). This is *why* builds used to clutter the repo and generated ~91 GB of test output.
- **Studio App Wired Masters branding + real OS drag-drop (subagent)** — top bar now shows the WM logo mark + white wordmark (assets in `Studio App/Web/assets/`: `wm_logo.png`, `wm_text_logo.png`), with the studio photo `studio_bg.jpg` (downscaled from 44 MB → 349 KB) as a subtle ~10%-opacity background under a dark scrim. Drag-drop of folders/WAV/AIFF/ZIP onto a queue card now routes real OS paths via a pywebview 6.x `document` drop bridge in `app.py` (`__wmReceiveDrop`), through the same ingest as the picker (picker kept as fallback). **Needs Sam to verify on a real run** (native window can't be tested headless): branding look + drag-drop paths + multi-card routing.
- **Housekeeping** — 13 loose dev/analysis scripts moved out of the repo root into `Scripts/` (with a README); `Tests/test_versions.py` +3 cases, `Tests/test_multiversion_parity.py` new.

**Pre-seeded target-folder masters now wired in as refs (2026-07-01, Claude).** Sam sometimes drops his current master into the *target* project `Audio/` folder (to A/B the new mix against). The builder classifies the *source* stems folder, not the target, so that master was copied around but left unreferenced in the .als (Sam wired it in by hand on the Replicage - Amen run). Now `build_project` captures any audio in the target `Audio/` + project root **before** copying source stems (`_find_preseeded_audio`), and at the reference step adds any that aren't one of our source stems or our own `FLAT REF` bounce as a **red reference match track** at the bottom (colour 14). Matched by filename stem (survives WAV normalisation). **Validated:** `Tests/test_preseeded_ref.py` 3/3 (discovery logic + an e2e build where a pre-seeded `(V9) Master` becomes a red ref, validator PASS) + full suite 12/12 green. **Single-version path only** — the multi-version path (`build_multiversion_project`) doesn't scan the target folder yet (follow-up). Also housekeeping this session: removed empty crash-repro stub folders, and `.gitignore` now ignores built `*] Project/` folders (default output base is the repo root, so builds otherwise clutter it).

**Studio App first-run crash FIXED (2026-06-30, Claude).** Sam ran the app and builds died (folders created, no audio copied, no .als; fans spun then the app closed). Two root causes, both fixed + tested: (1) **Non-WAV stems crashed the engine** — `AUDIO_EXTENSIONS` accepts mp3/flac/m4a/ogg/aiff but every reader is WAV-only, so a stray reference mp3 dropped in with the stems hit `_read_wav_header` → `ValueError: Not a WAV file` and aborted the build (this is the "no .als" case). Fixed with `project_builder._ensure_wav_paths` / `_normalize_audio_to_wav`: right after classification, any non-WAV audio is converted to 32-bit-float WAV via soundfile (libsndfile 1.2.2 reads mp3/flac/ogg/aiff) and substituted; an unreadable file is dropped with a warning, never fatal. Applied to both the single- and multi-version paths. (2) **The app was running the ML classifier** (Demucs = the fans, and the heavy/native risk behind the hard "app closed"); now **ML is forced OFF in the Studio App** (the decided model — named packs classify by filename; ML stays a CLI job). Reproduced both of Sam's crashed packs (Vlad = mp3; Hiisak/LIFT-OFF) from the CLI — both now build + validate. The launcher (`Run Studio App.bat`) also now auto-installs pywebview and pauses on error instead of flashing away. **Validated:** `Tests/test_non_wav.py` 4/4 + full suite green.

**Versions-in-subfolders detection FIXED (2026-06-30, Claude).** Follow-on from the crash fix: a multi-version pack whose versions live entirely in subfolders with NO top-level stems (e.g. LIFT-OFF `Extended/` + `Radio/`) was merging into one build with duplicate-named tracks. `versions.detect_versions` now handles the no-top-level case via `_detect_subfolder_versions`: the fullest/extended-named subfolder (`_pick_base`) is the baseline, another subfolder mirroring it (≥50% shared element keys) is an alternate version, a non-mirroring one is a category subfolder flattened in. Verified on the real LIFT-OFF pack — builds as a proper 2-version project (Extended @ bar 33, Radio @ bar 180, shared tracks, audio in `Audio/Extended` + `Audio/Radio`), validator PASS. `Tests/test_versions.py` 5/5 + full suite green.


**Nested sub-groups — BUILT + VALIDATED (2026-06-30, Claude).** The spec-locked nested-GroupTrack feature is shipped. `als_patcher` now supports a GroupTrack whose parent is another GroupTrack: `insert_group_track(..., parent_group_id=N)` sets the child group's `TrackGroupId` to the parent and routes its audio up into it (`AudioOut/GroupTrack`); a new `_apply_track_groups(lines, stems)` replaces the old single-level `runs` loop and lays out two levels (parent header above its sub-group headers above their tracks), exploiting that GroupTrack headers are invisible to `find_track_ranges` so audio-track→stem indices stay aligned. A new `Source/subgroup_cluster.py` does **singer-first** clustering: Vox → *Singer* (Lead, Lead-FX, BGV, BGV-FX ordered within); one/no singer → role groups (Lead vs BGV); a title token shared by every stem is correctly NOT treated as a singer. Also offered: **Drums** → Kit/Percussion, **Music** → instrument family (Keys/Synth/Guitar/Strings/Brass/Bells). Conservative: a sub-group needs 2+ members (else its stems stay loose in the parent), the category needs 3+ stems, and a single sub-group that swallows everything is skipped. Threaded through `build_project` via `_apply_subgroups` + a new `subgroup_categories` param (default vocals/drums/music; pass `[]` to disable). **Validated:** `Tests/test_subgroups.py` 11/11 incl. an end-to-end build of a 2-singer pack whose ALS re-parses (validate_project PASS) with the parent/child `TrackGroupId` chain confirmed (Vox → Lauren/Sarah, each singer's tracks pointing at their sub-group). Full suite green, no regressions. **NOT yet applied to the multi-version build path** (it builds its own shared-track `all_stems`); follow-up. **Not yet surfaced in the Studio App UI** as a toggle.

**Studio App: sub-groups toggle + EXE packaging/self-updater — BUILT (2026-06-30, Claude).** Two UI threads on top of the engine work, both validated by tests (native window + real EXE build still need Sam on a machine). (1) **Sub-groups toggle** — the top bar now has Vox/Drums/Music checkboxes (global setting `subgroups`, default all on) threaded `engine_api → build_project(subgroup_categories=...)`; unticking all disables nesting. (2) **EXE packaging + configurable self-updater** (per the DECIDED model below): `Studio App/build_exe.py` (PyInstaller one-file, ML-excluded, bundles Web + VERSION + update_feed.json + the template ALS + Config; engine/app made frozen-path-aware via `_MEIPASS`, and `build_project` forces **ML off when frozen** so the EXE never spawns itself as an ML subprocess); `Studio App/updater.py` (reads a public `latest.json` feed, semver-compares, downloads the new EXE and writes a retry-until-unlocked **swap .bat** that replaces+relaunches, then the app quits); the `⟳ Update` button now checks the feed and confirms before self-swapping when packaged, and still does `git pull` when run from source. **Feed URL is configurable, not hardcoded** (`update_feed.json` placeholder, also overridable by a file dropped next to the EXE) — Sam wires the real hosting later. `Studio App/publish_release.py` bumps VERSION + writes `latest.json`. **Validated:** `Tests/test_updater.py` 8/8 (semver, feed read incl. file://, swap-script content) + full suite green. **Still Sam's to do:** run `build_exe.py` on a machine, set up the public feed + URL, smoke-test the EXE + native window.

**Studio App distribution + update model — DECIDED (Sam, 2026-06-29).** The Dropbox-synced-source idea was rejected: not all studio machines have Dropbox, and Sam won't be logged into it on all of them, so there's no reliable synced local folder. **Final plan: a self-contained EXE that auto-updates from GitHub, with the code staying PRIVATE.** Reconciled by splitting code from binaries — the code repo stays private; a small **public "releases" feed** (e.g. a separate public repo or a hosted static file) holds only the built `.exe` + a `latest.json` (version + download URL). The app checks `latest.json` on launch / via the Update button, and downloads + swaps the EXE when newer. **No GitHub token is ever baked into the distributed EXE** (it would be extractable); auth-free because the releases feed is public while the source stays private. EXE shipped **ML-off by default** (Demucs/Whisper would bloat it to GBs; filename classification covers named packs). Already built this session: `VERSION` (0.1.0), UI version badge, and an `⟳ Update` button (currently `git pull` — to be repointed at the `latest.json` feed). NOT yet built: PyInstaller packaging, the `latest.json` updater/self-swap, and the public releases feed + publish script.

**Studio UI prototype started (2026-06-29, Claude).** A `Studio App/` desktop front-end (PyWebView + PyInstaller target) wrapping the engine, per Sam's spec: switchable **colour profiles** (per user/partner — each holds Ableton palette indices for drums/bass/music/vox/fx/sends; selectable globally and per-project), a one-time **output folder**, a multi-project **queue** (drag-drop / browse a folder, WAV/AIFF/ZIP, "+" to add more, per-project title `Artist - Title [Label]` and optional BPM), and a **Build all** batch runner that builds + validates each project with live status chips (a bad pack flags but doesn't stop the batch). Sleek dark UI (`Web/index.html` + `styles.css` + `app.js`). Backend `Studio App/engine_api.py` handles profiles/settings IO, ZIP extraction, AIFF→WAV (via soundfile), title parsing, and the threaded batch. Engine hook added: `build_project(..., category_colors=...)` (threaded through multiversion too) so profiles drive colours. Validated: `Tests/test_studio_app.py` 7/7 (parse, profiles roundtrip, zip/loose ingest, audio-root, palette=70), backend import + `get_bootstrap` smoke, full suite green. **Not yet validated by Claude (needs Sam to run):** the actual native window visuals and the PyInstaller EXE build — those can't run headless here. Next: run `py -3.13 "Studio App/app.py"`, then real OS drag-drop paths, EXE smoke test, optional branding/logo.

**Wet/dry (vocals-only) + empty-stem handling (2026-06-29, Claude).**

*Wet/dry — VOCALS ONLY, explicit pairs only (per Sam).* The rule applies only to **vocals**, and only when the same vocal is supplied as an explicit pair — one stem says **WET**, one says **DRY**. The WET stays ON (normal working track); the DRY is parked in a muted, collapsed **"Dry" group** (colour 37 grey) underneath, kept for recall and excluded from the flat-ref sum (else the element double-counts). `stem_classifier.find_dry_stems` requires a `dry` token AND a sibling with a `wet` token sharing the same base identity (export index `NN_` + wet/dry tokens stripped before matching); the caller (`build_project`) only passes vocal stems. A music `ARP DRY` next to a plain `ARP` is therefore NOT touched (no `wet` sibling, and not a vocal). `als_patcher` group runs now carry per-run `muted`/`unfolded`/`group_color` so the Dry group is muted+collapsed while working groups stay audible+expanded.

*Empty/silent stems.* A stem with no audio in it (peak window RMS below `als_patcher.SILENCE_FLOOR_DB = -60 dBFS`) is moved to the **very bottom** and given its **own colour** (`SILENT_TRACK_COLOR = 12`) so it's obviously a dead export; it's pulled out of the working layout and the flat-ref sum. `find_audio_regions(..., return_peak=True)` now also returns the peak (one read — uses a RELATIVE threshold for region-finding, so the absolute peak floor is what flags true silence).

*Validated:* `Tests/test_wet_dry.py` 7/7 (explicit pair parks; DRY+plain does NOT; orphan dry left; WET-only left; index-difference still pairs) + a combined synthetic e2e inspected in the ALS — vocal DRY parked & muted, music `ARP DRY` stayed a working track in the Music group, silent stem at bottom coloured 12, flat ref summed only the 7 real stems — + `validate_project.py` PASS + full suite green (no regression). **NB:** the real Replicage project Sam already has was built *before* these features; rebuild it to pick them up if needed (it has no wet/dry vocal pair, but this is the general note).

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
1. **Multi-version drift — precise-BPM part RESOLVED (Sam, 2026-06-29).** Policy is settled: always round BPM (whole or half), never warp — the true tempo is a round number, so the rounded value IS the grid; any apparent drift from a 127.71 reading is the reading being wrong, not the rounding. The first-onset alignment bug was already fixed in code (`first_actual_onset_sec` drives version placement). No open decision here any more.
2. **Group-bus detection needs energy in the analysed window** — a bus silent in the first 180 s won't be matched (contributes ~nothing anyway); heavily post-processed buses (not an exact sum) may slip past.
3. **Silence-trim is iteration 1** — Sam confirmed trims look tight/good on the single-version packs.
4. **Python 3.14.0 interpreter instability** — intermittent AND sometimes persistent miscompiles of hot pure-Python loops (bogus TypeError / segfault / "int not iterator"). Python 3.13.14 is now installed with the normal and ML dependencies; use `py -3.13` explicitly for builds. The launcher still defaults to 3.14.

## What's Next

### ⭐ Priority order
1. **Sam: run the Studio App** — `py -3.13 -m pip install pywebview` then `Studio App/Run Studio App.bat`. Verify: (a) look/feel + the colour-profile flow, (b) the new **Wired Masters branding** (logo + subtle studio background — nudge `.app::before` opacity if too subtle/strong), (c) the new **real OS drag-drop** (drag a folder / WAV / ZIP onto a card, incl. dropping onto the *second* card). (Claude can't test the native window headless.)
2. ~~**Build nested sub-groups**~~ **DONE (2026-06-30/07-01)** — engine + Studio App toggle; now applied to the **multi-version path** too (2026-07-01). Only remaining follow-up: none.
3. ~~**Package + auto-update the Studio App**~~ **SCAFFOLDING BUILT (2026-06-30)** — `build_exe.py` (PyInstaller, ML-off, bundles template), `updater.py` (latest.json check + EXE self-swap), `publish_release.py`, configurable `update_feed.json`; Update button repointed at the feed (git-pull dev fallback). **Sam to finish:** run `build_exe.py`, stand up the public feed + set its URL, EXE smoke test.
4. ~~**Studio App real OS drag-drop**~~ **DONE (2026-07-01)** — pywebview 6.x `document` drop bridge in `app.py` routes real OS paths through the same ingest as the picker (picker kept as fallback). Needs Sam to verify on a real run.
5. ~~**ML subprocess cleanup/timeouts**~~ **DONE (2026-07-01)** — timeout (`get_ml_timeout_sec`) + guaranteed temp-dir cleanup in `_ml_classify_unknowns`.
6. ~~**Logo / branding pass**~~ **DONE (2026-07-01)** — Wired Masters logo + wordmark + subtle studio background in the Studio App. Needs Sam to eyeball on a real run.

### Longer-running / lower priority
0. **Sam checks the fresh rebuilt Moby project in Ableton** at `C:\Users\Carillon\Desktop\Mobi Project\Mobi.als`; both manual tempo and tempo automation are verified at 160 BPM from project creation, not patched after the fact.
0. **Continue Codex handoff list:** `Documentation/CODEBASE_REVIEW_NEXT_STEPS.md` now marks Sections 1-5 completed; continue with ML subprocess cleanup/timeouts next.
0. **Review/commit ML classifier work** from 2026-06-26 (`Source/audio_ml_classify.py`, `project_builder.py`, `stem_classifier.py`) after Sam checks the Moby project in Ableton.
1. **Use Python 3.13 explicitly** (`py -3.13`) for normal builds.
2. ~~Decide precise-BPM policy~~ **RESOLVED (Sam, 2026-06-29): always round BPM (whole or half), never warp.** Dance tracks sit on a round grid; a detected 125.71 is analysis jitter, not a real tempo. No code change — current rounding is correct.
3. ~~**Same-folder name-token versions**~~ **DONE (2026-07-01)** — `versions._detect_nametoken_versions` + token-stripping `element_key`; Get Right `S16` vs `S17 -SHRT EDIT` in one flat folder now builds as 2 versions. Conservative (won't mis-split a normal pack). NB still true: NOT the Replicage case — there the arrangements are baked end-to-end into one long timeline per stem (correctly a single-version build).
4. ~~Wet/dry~~ **DONE (2026-06-29)** — see Current State.
5. **Nested sub-groups — SPEC LOCKED (Sam, 2026-06-29), ready to build.** Cluster stems into nested sub-groups by name tokens within a parent group. **Axis = SINGER-FIRST:** Vox → *Singer* (e.g. Lauren) → that singer's `Lead`, `Lead FX 1/2/3`, `BGV`, `BGV FX 1/2/3` (each role's FX follows it); when there's one singer / no names, fall back to grouping by **role** (Lead vs BGV) directly. **Scope = vocals + offered elsewhere:** also sub-group **drums** (e.g. kit vs percussion) and **music** (by instrument) where name tokens clearly suggest it. Needs a NEW patcher capability: **nested GroupTracks** (a GroupTrack whose parent is another GroupTrack — the child group's `TrackGroupId` = the parent group's id; grandchildren point at the child group). Build plan: (a) `als_patcher` — support a group whose parent is a group (extend the run/`insert_group_track` machinery to handle a parent_group_id and a second nesting level); (b) `stem_classifier`/a new helper — name-token clustering within a category (singer-name detection, Lead/BGV role + "FX N" attachment, verse/chorus/stacks); (c) thread a sub-group structure through `project_builder` layout; (d) validate with unit tests + a synthetic nested-group ALS inspection (parent/child TrackGroupId chain correct, audible, expanded).
6. **Studio App polish** — real OS drag-drop paths, PyInstaller EXE smoke test, logo/branding. (Update mechanism DONE — see below.)

## Key Decisions
- **BPM always rounded, never warped (2026-06-29)** — projects sit on a round tempo (whole or half BPM); a detected decimal like 125.71 is analysis jitter, so round it and place stems unwarped. Settles the old precise-BPM-vs-warp question for good.
- **Wet/dry: VOCALS ONLY, explicit pairs (2026-06-29, Sam)** — the rule applies only to vocals, and only when the same vocal is supplied as an explicit pair (one stem says WET, one says DRY). The wet stays a normal working track; the dry goes into a muted, collapsed grey "Dry" group underneath, excluded from the flat-ref sum (else the element double-counts). A dry stem is parked only if a sibling carries a `wet` token with the same base identity (after stripping the `NN_` export index and wet/dry tokens). A `DRY` next to a plain (non-wet) stem, or any non-vocal, is left alone. *Why vocals-only:* on instruments a "dry" stem is often a genuinely different sound to keep, not a redundant duplicate; only the vocal is reliably a true wet/dry of one performance.
- **Empty/silent stems parked at the bottom (2026-06-29, Sam)** — a stem with no audio in it (peak window RMS < -60 dBFS) is moved to the very bottom and given its own colour (12), out of the working layout and the flat-ref sum. *Why:* dead exports happen in real packs; surfacing them clearly (rather than burying them in a group) lets Sam see and ignore them at a glance.
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
| **Wet/dry** | same VOCAL provided both wet and dry | DONE (2026-06-29) — **vocals only**, explicit WET+DRY pair only: **Wet ON**; **dry parked in a muted, collapsed "Dry" group** (grey 37), kept for recall, excluded from the flat-ref sum. `stem_classifier.find_dry_stems` + vocals filter in `build_project`. |
| **Empty/silent stem** | a stem with no audio in it (dead export) | DONE (2026-06-29) — moved to the **very bottom**, own colour (`SILENT_TRACK_COLOR=12`), out of the layout + sum. Peak floor `SILENCE_FLOOR_DB=-60 dBFS` via `find_audio_regions(return_peak=True)`. |
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
