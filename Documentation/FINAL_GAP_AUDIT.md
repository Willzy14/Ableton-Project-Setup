# Final Gap Audit — post-hardening

*Multi-agent verify-heavy audit, 2026-07-02 — 34 confirmed findings.*

> **Verdict:** The single-version path — the one Sam actually ran the Replicage job on — is genuinely solid after today's hardening: the drop-race, WAV-format, sample-rate, rebuild-dup and REF/UPDATE fixes all held up under re-verification. The remaining risk is concentrated in the multiversion path, which can still silently lose files four different ways (ref-like top files, token-less stems, nested REF folders, off-rate bounce stems), plus one resurrected UI drop-routing race and a cluster of cross-machine path landmines. None of it blocks careful single-version use on Carillon this week, but the multiversion silent-drop fixes and the drop-queue fix should land before he trusts multi-version packs or a second machine.

## Fix now
- Guard _extract_special_dirs against the pack root itself (only sift when resolved parent != scan root) and stop _find_audio_root descending into a single child whose name is special_dir_kind()-positive — kills the 'Fix You / Amended Masters' whole-build hijack (~10 lines).
- Make drop push/deliver strictly 1:1: app.js pushes onto __wmDropQueue only when e.dataTransfer.files.length > 0, and app.py always calls __wmReceiveDrop (empty array when no paths) with the shift happening first — closes the wrong-card misroute before it eats a real client's stems (~6 lines).
- Multiversion leftover sweep: wire detect_versions' filtered ref-like top files into build_multiversion_project as red reference tracks, and belt-and-braces compute leftovers = all pack audio minus union(version files, special-dir files) → mv_refcompare, so NOTHING can fall through silently again.
- Flatten non-qualifying nametoken groups into the primary version's files and add the invariant sum(len(v['files'])) == len(top_files) — stops the token-less acapella/FX drop.
- Make _gather_special_dir_files recursive (walk descendants, classify with special_dir_kind, prune claimed dirs) so REF/UPDATE folders nested inside a version subfolder aren't dropped.
- Clamp negative version offsets at the source (shift base_start up to the next bar before appending to offsets/locators) and add max(0.0, time_beat) in insert_locators — keeps a long-intro primary internally in time.
- Pipe per-version bounce summary['skipped'] and peak into report['skipped'], flat_ref_peak, and _collect_flags on the multiversion path (~5 lines) — mixed-rate packs then warn instead of shipping an incomplete FLAT REF.
- Honour the RIFF pad byte in _read_wav_header (2 lines: seek chunk_size + (chunk_size & 1)) and validate .wav files in _ensure_wav_paths (header parses, rate > 0, data_size > 0 → else route to the existing skipped/WARNING plumbing) — one dead or metadata-heavy WAV no longer fails or silently empties a pack.
- applyStatusToCards: only reassign + re-render a card when JSON.stringify of its status actually changed, hide/disable 'Build again' while State.batchRunning, persist trace-open state on proj — makes the app usable during a long batch.
- Delete the dead duplicate 'if not subdirs' block (versions.py:214-217) while in the file.
- Before any Mac/second-machine use (not gating Carillon this week): existence-check config paths in _configured_path, derive DEFAULT_* from Path.home(), sanity-check settings.json output_folder for the current OS, and untrack Config/project_builder.json (git rm --cached + example file).
- SAM-SIDE (only when the EXE matters, not gating real jobs from source): py -3.13 -m pip install -r 'Studio App/requirements.txt', one smoke build of build_exe.py, one launch of dist/StemToAbleton.exe — and fix the build_exe.py docstring to bump VERSION before building.

## Full punch list
- HIGH — Pack root named like an update/ref folder ('Coldplay - Fix You Stems', 'Amended Masters', 'TRACK UPDATE STEMS.zip') sifts every stem into updated/ref: build dies with a misleading BPM error or ships only muted A/B tracks (project_builder._extract_special_dirs + versions._UPDATE_DIR_RE '\bfix' + engine_api._find_audio_root descent).
- HIGH — Multiversion builds silently drop ALL top-level ref-like files — supplied master, rough mix, even a legit stem named 'Bass Master.wav' — filtered by _REFLIKE_RE in detect_versions and never rescanned; no flag, no report line (versions.py:198-207,233 + build_multiversion_project).
- HIGH — Negative version offset (credible kick anchor >32 bars in) desyncs the multiversion primary: per-clip clamp slides each early clip to beat 0 by a DIFFERENT amount, FLAT REF shifts by the full offset, and the version locator is written with negative Time (project_builder.py:1350-1355,1501 + als_patcher.py:423-430,1131).
- HIGH — Stale __wmDropQueue entry (text/URL/no-path drop pushes but Python never delivers) FIFO-misroutes the NEXT real stem drop onto the wrong card — resurrects the wrong-card class fixed in bb0bb8b (app.js:456-501 + app.py:40-52).
- HIGH — Git-tracked AND Dropbox-synced Config/project_builder.json carries Carillon-only absolute paths: breaks every build on the Mac (_configured_path has no existence check), machines overwrite each other via Dropbox, and a future upstream edit silently stalls the launcher's hidden 'git pull' (Run Studio App.bat:10).
- HIGH (deploy, latent) — Frozen onefile EXE writes settings/profiles into ephemeral _MEIPASS (lost every restart) and never reads the bundled engine config, falling back to hardcoded Carillon paths on clean machines (engine_api.py:24,35-37 + project_builder.py:35,70 + build_exe.py:47).
- MED — Name-token version split drops token-less minority stems (acapella, crowd noise, FX) into no version — up to 40% of a flat folder silently gone; the docstring's 'never dropped' claim is false (versions._detect_nametoken_versions:153-175).
- MED — REF/UPDATE folders nested INSIDE a version subfolder are dropped on the multiversion path (single-version handles identical nesting at any depth) — _gather_special_dir_files only scans pack-root children (project_builder.py:634-656).
- MED — Multiversion discards per-version bounce 'skipped' and peak: mixed-sample-rate packs get FLAT REFs quietly missing stems while the report hardcodes skipped=[] and no flag fires — Sam A/Bs against an incomplete reference (project_builder.py:1317-1327 vs single-version 1158-1161).
- MED — A corrupt/0-byte/misnamed .wav fails the ENTIRE pack instead of being skipped with a warning: _ensure_wav_paths whitelists .wav suffix without validating the header (project_builder.py:163-167 → _read_wav_header raise; data-before-fmt also gives ZeroDivisionError).
- MED — _read_wav_header ignores the RIFF word-alignment pad byte after odd-sized chunks (bext/LIST/iXML from Pro Tools/broadcast exports): a perfectly good stem silently reads as empty and gets parked as the CLIENT's 'empty export' (als_patcher.py:185,196-201).
- MED — 700ms poll rebuilds every card during a batch: typing focus destroyed every tick, failed-trace 'Show details' re-collapses within 700ms, mid-batch 'Build again' resets are silently reverted (app.js:669-673 → renderQueue innerHTML wipe).
- MED — DEFAULT_TEMPLATE_PATH and DEFAULT_OUTPUT_BASE hardcode C:\Users\Carillon with no Mac/other-user fallback — the live failure path for the frozen EXE and for any machine without config (project_builder.py:36,70).
- MED — Studio App settings.json Dropbox-syncs a Windows-absolute output_folder to the Mac, where builds silently land in a literal junk folder named 'C:\Users\Carillon\Downloads' relative to CWD (engine_api.load_settings falsy-only check).
- MED (deploy, Sam-side) — PyInstaller is not installed, so the EXE has never been buildable and every frozen-path defect has zero real-world coverage (pip install -r 'Studio App/requirements.txt' + one smoke build + one launch).
- MED (deploy) — build_exe.py and publish_release.py document the build/publish order in opposite directions; the wrong order bakes a stale VERSION and creates an infinite self-update loop (build_exe.py:11-12 vs publish_release.py:79-83).
- MED (tests) — The 0ed039a hardening batch (extensible WAV, negative-time clamp, rebuild dups, majority SR) shipped with zero tests — the exact silent-corruption class the audit flagged is unguarded against regression.
- MED (tests) — Octave/half-time BPM flag and multiversion flags/bpm_source emission have no test coverage; the flag IS the BPM safety net until the CRNN kick detector lands (_collect_flags:493-519, mv emission at 1521/1537).
- MED (docs) — AI_CONTEXT.md Current State is a full working day behind: all six hardening/UI commits from 2026-07-01/02 absent; 'What's Next' priority 1 already done — next session gets a materially wrong picture.
- MED (docs) — HARDENING_AUDIT.md is uncommitted and still reads as 51 open findings though ~10 of 12 ranked items are fixed; genuinely-open items (#3 multi-zip collisions, #5 foreign-name flag, #12 lone-Dry, fixtures, QC lamp, hardcoded paths) are indistinguishable from the fixed ones.
- LOW — Free-text BPM ('128,5', '128 bpm') skips auto-detect and survives to a cryptic float() failure AFTER minutes of copying/analysis; sanitise in engine_api._run_batch_worker and fall back to auto with a flag.
- LOW — _version_label substring-matches STEM names before the k==0 'Extended' default: a primary whose stems include 'Dub Delay Return' gets its arrangement locator labelled 'Dub' (project_builder.py:1334-1343).
- LOW — Multiversion leaves duplicate _wav_staging folders inside the delivered project's Audio/ whenever a pack contains MP3/AIFF/FLAC — duplicate audio syncs to Dropbox and shows in Ableton's browser (use tempfile.mkdtemp like single-version).
- LOW — Dead byte-identical duplicate 'if not subdirs' block in detect_versions reads like a merge artifact in a hot function (versions.py:214-217) — delete.
- LOW — Test suite hard-fails on any machine but Carillon (and on Carillon if the Desktop folder is cleaned): Moby regression test raises instead of pytest.skip when its fixture folder is missing (Tests/test_moby_tempo_selection.py:13-15).
- LOW (tests) — _match_key producer-prefix stripping (UPDATE_STEM_ / 'STEM N -') is covered by nothing but the one live BESH run; a regex tweak would pass the suite while parking BESH-shaped updated stems (failure mode is flagged, not silent).
- LOW (deploy) — publish_release.py writes a literal 'TODO-set-release_base' download_url into an uploadable latest.json when release_base is empty, and the download→swap→relaunch path has never executed once.
- LOW (docs) — Two stale AI_CONTEXT.md.tmp.* droppings in Documentation/ (May 19, Jun 25) surface month-old 'Current State' text to greps — delete both; *.tmp.* is already gitignored.

---

# Stem → Ableton — Final Pre-Production Audit (2026-07-02)

## Verdict

The **single-version path is sound** after today's hardening — every fix from the 51-finding audit that was re-verified held up, and the failure modes Sam hit live (wrong-card drops, version stacking, extensible WAVs, REF/UPDATE folders) are genuinely closed. The remaining exposure is almost entirely the **multiversion path**, which still has four independent ways to *silently lose audio files*, plus one resurrected UI drop-routing race and a cluster of cross-machine path landmines that don't bite on Carillon but will bite the Mac or any studio PC on day one. Nothing found blocks careful single-version use this week; the Fix Now list below should land before multi-version packs or a second machine are trusted.

## Fix Now (small + sharp, before more real jobs)

**Engine — silent file loss (the theme of this audit):**
1. **Root-name hijack** — guard `_extract_special_dirs` against the scan root itself and stop `_find_audio_root` descending into a special-named single child. Today, a pack called "Coldplay - Fix You Stems" or "Amended Masters" sifts *every* stem into updated/ref and the build dies or ships only muted A/B tracks. ~10 lines.
2. **Multiversion leftover sweep** — wire `detect_versions`' filtered ref-like top files (supplied master, rough mix, "Bass Master.wav") into `build_multiversion_project` as red refs, plus belt-and-braces: leftovers = all pack audio − placed files → `mv_refcompare`. Nothing can fall through silently again.
3. **Nametoken leftovers** — flatten non-qualifying token groups into the primary version; add invariant `sum(version files) == len(top_files)`.
4. **Nested REF/UPDATE** — make `_gather_special_dir_files` recursive so "Extended Stems/REF/" isn't dropped on the multiversion path (single-version already handles it).
5. **Negative offset clamp at source** — shift a negative `base_start` to the next bar before it hits offsets/locators; `max(0, time)` in `insert_locators`. Stops long-intro primaries desyncing clip-by-clip.
6. **Multiversion bounce skipped** — pipe per-version `summary['skipped']`/peak into report + `_collect_flags` (~5 lines). Mixed-rate packs then warn instead of shipping an incomplete FLAT REF.

**Engine — WAV robustness:**
7. **RIFF pad byte** in `_read_wav_header` (2 lines) — pro-DAW/broadcast WAVs with odd-sized bext/LIST/iXML chunks currently read as *empty* and get blamed on the client as "empty export".
8. **Validate .wav in `_ensure_wav_paths`** — a 0-byte/corrupt/renamed file currently fails the entire pack; route failures to the existing skipped/WARNING plumbing instead.

**Studio App:**
9. **Drop-queue 1:1** — JS pushes only when `files.length > 0`; Python always calls `__wmReceiveDrop` (shift first, empty array OK). A dragged URL/text currently plants a stale queue entry that misroutes the *next real stem drop onto the wrong card* — the exact class Sam got burned by before.
10. **Poll re-render diff** — only re-render a card whose status actually changed; disable "Build again" mid-batch; persist trace-open state. Fixes lost typing focus, collapsing traces, and reverting resets during batches.

**Ride-along:** delete the dead duplicate block in `versions.py:214-217`.

**Before first Mac / second-machine run (not gating Carillon):** existence-check config paths, home-derived defaults, OS-sane `output_folder` check, untrack `Config/project_builder.json`.

**Sam-side (deployment, not gating real jobs from source):** `pip install -r "Studio App/requirements.txt"`, one smoke EXE build + launch, and fix the build/publish order docstring (wrong order = infinite self-update loop later).

## Punch List by Area

### Engine — version detection & multiversion path
- **HIGH** Root named like update/ref folder hijacks the whole build (`_extract_special_dirs` + `_UPDATE_DIR_RE` `\bfix` + `_find_audio_root`).
- **HIGH** Top-level ref-like files silently dropped on the multiversion path — never rescanned, no flag (`versions.py:198-207,233`).
- **HIGH** Negative version offset: per-clip clamp desyncs early clips independently; locator written with negative Time (`project_builder.py:1350-1355` + `als_patcher.py:423-430,1131`).
- **MED** Nametoken split drops token-less minority stems — up to 40% of a folder gone, docstring claims otherwise (`versions.py:153-175`).
- **MED** REF/UPDATE nested inside a version subfolder dropped (`_gather_special_dir_files` root-only).
- **MED** Multiversion discards bounce `skipped`/peak — report hardcodes `skipped: []` (`1317-1327` vs single-version `1158-1161`).
- **LOW** `_version_label` substring-matches stem names → "Dub Delay Return" mislabels the locator "Dub".
- **LOW** Multiversion leaves duplicate `_wav_staging` folders inside delivered `Audio/`.
- **LOW** Dead duplicate `if not subdirs` block (`versions.py:214-217`).

### Engine — WAV / audio handling
- **MED** Corrupt/0-byte/misnamed .wav aborts the entire pack (`_ensure_wav_paths` suffix whitelist).
- **MED** RIFF pad byte ignored — good broadcast WAVs silently read as empty, flagged as the client's "empty export" (`als_patcher.py:185,196-201`).

### Studio App UI
- **HIGH** Stale `__wmDropQueue` entry misroutes the next drop onto the wrong card (push/deliver asymmetry, `app.js:456-501` + `app.py:40-52`).
- **MED** 700ms poll full re-render: typing focus lost, failed traces collapse, mid-batch resets reverted (`app.js:669-673`).
- **LOW** Free-text BPM ("128,5", "128 bpm") fails late with a cryptic `float()` error after minutes of work.

### Cross-machine & config
- **HIGH** Git-tracked + Dropbox-synced `Config/project_builder.json` with Carillon-only paths: breaks Mac builds (no existence check in `_configured_path`), machines fight via Dropbox, silently stalls the launcher's hidden `git pull`.
- **MED** `DEFAULT_TEMPLATE_PATH`/`DEFAULT_OUTPUT_BASE` hardcode `C:\Users\Carillon` — no Mac/other-user fallback (`project_builder.py:36,70`).
- **MED** `settings.json` syncs a Windows-absolute `output_folder` to the Mac → builds land in a literal `C:\Users\...` junk folder relative to CWD.
- **LOW** Moby regression test raises (instead of skips) on any machine without the Desktop fixture folder.

### Deployment / EXE (Sam-side, gated on distribution — not this week's jobs)
- **MED** PyInstaller not installed; the EXE has never been built, so all frozen-path fixes have zero coverage.
- **HIGH (latent)** Frozen onefile EXE: settings/profiles written to ephemeral `_MEIPASS` (lost every restart); bundled config never read → hardcoded Carillon paths leak on clean machines.
- **MED** build/publish order documented both ways round — wrong order = permanent "update available" loop.
- **LOW** `publish_release.py` can emit a literal TODO `download_url` into an uploadable `latest.json`; the download→swap→relaunch path has never executed.

### Tests
- **MED** The 0ed039a hardening batch (extensible WAV, negative-time clamp, rebuild dups, majority SR) shipped with zero tests — a refactor regresses all four invisibly.
- **MED** Octave/half-time flag + multiversion `flags`/`bpm_source` emission untested — this flag is the BPM safety net until the CRNN kick detector lands.
- **LOW** `_match_key` producer-prefix stripping validated only by the one live BESH run (regression would be flagged, not silent).

### Docs / housekeeping
- **MED** `AI_CONTEXT.md` Current State is a full working day behind (all six 2026-07-01/02 commits absent; "What's Next" #1 already done).
- **MED** `HARDENING_AUDIT.md` uncommitted and unannotated — ~10 of 12 ranked items are fixed but indistinguishable from the genuinely open ones (#3 multi-zip collisions, #5 foreign-name flag, #12 lone-Dry, fixture packs, QC lamp, hardcoded paths).
- **LOW** Two stale `AI_CONTEXT.md.tmp.*` droppings in `Documentation/` — delete (already gitignored).

## What Is Solid (checked and passed)

These were re-verified during this audit and **held up** — no action needed:

- **Single-version build path** — handles nested REF/UPDATE at any depth, reports bounce `skipped` + peak, surfaces flags on the Result Card, and cannot hit the negative-offset desync (base_start is always 128).
- **Drop routing for real file drops** — the bb0bb8b FIFO works correctly when files carry paths; the remaining hole is only the no-path/empty-drop asymmetry above.
- **Rebuild idempotency** — `_find_preseeded_audio` iterates files only (never re-wires directories), `source_names` seeding prevents duplicate refs on rebuild, pre-seeded target masters wire as red refs (the 2026-07-01 fix confirmed).
- **WAV hardening from 0ed039a** — WAVE_FORMAT_EXTENSIBLE (0xFFFE) resolution, majority-sample-rate bounce, and the per-clip clamp all work as committed (they just need tests, and the clamp needs the version-level fix above).
- **`__MACOSX`/dotfile filtering, chop→vox reclassification, filename-BPM (`_bpm_from_filenames` has a unit test), octave flag logic** — all present and correct in the current tree.
- **`_UPDATE_DIR_RE` scope** — "The Remix Stems" does NOT false-match (`\bfix` needs a word boundary); the hijack blast radius is real but bounded.
- **Batch resilience** — `engine_api` catches per pack, so one failed pack shows an error card and the rest of the batch survives.
- **UI input values** — persist via `oninput` even through the re-render churn; no data loss, only focus/interaction annoyance.
- **Updater pure functions** — semver compare, feed reads via `file://`, and swap-script content all have real test coverage; the packaged "feed not set up yet" dead-end is deliberate and gracefully handled.
- **Ref locators** — refs consolidated on one track, energetic locators key-mapped 1..9/0 via inline `PersistentKeyString` (confirmed working from the live session).
- **Housekeeping already done** — `*.tmp.*` gitignored; `profiles.json`/`settings.json` correctly untracked; VERSION + `update_feed.json` bundle paths correct for the frozen app.

**Bottom line:** hammer single-version jobs on Carillon with confidence now; land the ~10 Fix Now items (one focused session — they're all small) before trusting multiversion packs, and do the cross-machine config pass before the Mac ever runs a build.