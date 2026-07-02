# Hardening & Edge-Case Audit

*Multi-agent adversarial audit, 2026-07-01 — 51 confirmed edge-case findings. Verdict + testing plan + honest add/don-t-add.*

> **Verdict:** Honestly: it's ~90% there for Sam's core case (a house/techno pack, WAV stems, dropped as one folder/zip) and testing IS the right focus — but "just testing" undersells it, because there's a cluster of the exact same bug class you already hit once. The single biggest structural weakness is `_find_audio_root` in engine_api.py: it silently re-roots into the one richest subfolder, which drops REF/UPDATE STEMS folders, whole categories, and even entire versions on real pro pack shapes with no error and no flag. Fix that one function plus the 32-bit-float WAV decode and the `chop`→vocals bug, wire flags into the multiversion path, and it's genuinely ready to hammer.

## Is it there?

Close. For Sam's bread-and-butter — a house/techno pack of WAV stems, dropped as one folder or one zip — the engine does the right thing and saves the ~30 min it's supposed to (validated on the Replicage - Amen job). Testing IS the correct next move.

But "it just needs testing" quietly assumes the packs behave. The real risk is a **cluster of the same bug class you already hit once**: a pack shaped a particular way produces a *wrong-but-plausible* project with **no error and no flag**. The archetype is `_find_audio_root` (engine_api.py:180-197): when the top folder has no loose audio, it recurses and returns the **single subfolder richest in audio**, silently discarding every sibling — REF/, UPDATE STEMS/, other category folders, even whole versions. That one function is the direct heir to the zip bug and it has several real-world triggers. Add the 32-bit-float WAV decode bug and the `chop`→vocals misfire and you have three high-value fixes standing between "works on my pack" and "ready to hammer".

Grounded spot-checks I ran: `_find_audio_root` returns `best` via strict `n > best_n` (engine_api.py:191-196); `fmt_tag` is read verbatim with no 0xFFFE handling (als_patcher.py:186); `\bchop` sits in VOCAL_PATTERNS with vocals scored before music (stem_classifier.py:126); the multiversion dispatch returns before `_extract_special_dirs` (project_builder.py:650-656 vs 680).

## The next real-world bugs to catch (ranked)

### Ingest / folder-shape (the zip-bug family — highest priority)

**1. `_find_audio_root` drops sibling REF / UPDATE / category / version folders** — HIGH
- *Repro:* `MyTrack/Stems/*.wav` + `MyTrack/REF/other.wav` + `MyTrack/UPDATE STEMS/*.wav`, no top-level audio. Returns `Stems/`; REF and UPDATE are siblings outside the scanned tree → no References track, no A/B, no flag. Same for `Drums/ Bass/ Vocals/` category splits (keeps only the richest) and `Extended/ Radio/` version splits (keeps one version).
- *Fix:* only auto-descend through **true single-child wrappers** (exactly one non-junk subdir AND no top-level audio). When a folder has multiple audio-bearing branches or any `special_dir_kind()` sibling, return the **parent** unchanged so `detect_versions` / `classify_stems` / `_extract_special_dirs` resolve it — the downstream code is already built for that shape, it's just being starved. Add a validation cross-check: source tree had a REF/UPDATE folder but report shows 0 → raise a flag.

**2. macOS `__MACOSX` / `._Stem.wav` AppleDouble twins** — HIGH
- *Repro:* right-click→Compress on a Mac, drop the zip. `classify_stems` recurses into `__MACOSX/`, turns each `._Kick.wav` into a track, `_ensure_wav_paths` passes the fake .wav through unread → every stem gets a broken silent twin.
- *Fix:* skip `p.name.startswith('.')` and any dir named `__MACOSX` at every enumeration point (engine_api `_audio_files_in`/`_find_audio_root`, `classify_stems`, `versions._audio_in`).

**3. Multiple dropped zips/folders flatten by basename** — MED
- *Repro:* multi-select `Extended.zip` + `Radio.zip`, both with `Kick.wav` → `staged/Kick.wav` is whichever iterated last; the other is gone (engine_api.py:230, `allow_multiple=True`).
- *Fix:* namespace on collision (`{src}__{name}`) or keep each input in its own subfolder so versions.py treats them as versions.

### Classification

**4. `chop`/`chops` force-classified as VOCALS** — HIGH
- *Repro:* `Piano Chops.wav`, `Synth Chops.wav`, `Chord Chops.wav` → magenta Vox track, singer sub-group. Extremely common in house/tech-house. (`\bchop`, stem_classifier.py:126; vocals before music.)
- *Fix:* require a vocal context word — `(vocal|vox|voc)\W*chop` — or if the only vocal hit is `chop` and `has_music`, prefer music. Anchor to `\bchops?\b` so 'chopper' stops matching.

**5. Generic ('STEM 1', 'Audio 12') & foreign ('Bombo', 'Voz', 'Bajo') names → silently binned as 'music'** — MED
- *Repro:* Studio App forces `use_ml=False`; unclassified falls to 'music' (project_builder.py:731) with **no flag** (_collect_flags has no unclassified branch). Spanish-named rhythm section also breaks BPM auto-detect (reads kick/drums/bass only, line 239) — relevant to the Defected/Latin roster.
- *Fix:* flag a high unclassified fraction when ML is off; don't colour them as confident 'music'; add ~10-15 multilingual kick/bass/vocal tokens.

### BPM

**6. Octave fold sets a confident wrong tempo** — HIGH
- *Repro:* 70 BPM downtempo or 174 DnB kick → folds to 140/87; grid fits cleanly so residual ≤5ms; no flag (bpm_detector.py:180-183/258-261).
- *Fix:* record whether the fold changed the octave; if so, flag "detected {bpm} — raw grid {raw}, verify octave". Surface the pre-fold BPM in the report.

**7. Multiversion path never emits ANY BPM flag** — HIGH
- *Repro:* `flags: []` and `bpm_source: None` hardcoded (project_builder.py:1393/1404) — so on exactly the label packs that carry versions, a low-confidence *or* folded tempo is set silently.
- *Fix:* capture res_ms/n_inliers into a bpm_meta and run `_collect_flags` on the multiversion path too (see Add #1).

### WAV decode / bounce

**8. 32-bit-float EXTENSIBLE WAV decodes as int32 garbage** — HIGH
- *Repro:* Pro Tools / Cubase / Nuendo float stems (fmt tag 0xFFFE). Flat-ref plays as digital noise; region trims also mis-measure; every log line looks normal (als_patcher.py:186; bounce.py:60/111; region detector 218-223).
- *Fix once, centrally* in `_read_wav_header`: when fmt_tag == 0xFFFE, read the SubFormat GUID (fmt_data[24:26]) as the real code (1=PCM, 3=float). Every `fmt==3` check downstream then works unchanged.

**9. First stem sets the reference sample rate** — MED
- *Repro:* 44.1k pack + one 48k kick; drums sort first → sr0=48000, every 44.1k stem skipped, flat-ref is just the one oddball (bounce.py:197-206).
- *Fix:* pick sr0 as the **majority** rate (mode), not headers[0]; flag if >30% skipped.

### Layout / rebuild

**10. Rebuild into an existing folder duplicates REF/UPDATE as red reference tracks** — MED (but high frequency)
- *Repro:* build a single-version pack with a REF/UPDATE folder, then rebuild without deleting the folder → the ref/updated files appear twice, +1 duplicate per rebuild (source_names built after `_extract_special_dirs`; preseeded filter 946-948).
- *Fix:* seed source_names with the ref/updated stems too so preseeded copies aren't re-added.

**11. Long pre-kick intro → NEGATIVE arrangement time, written unclamped** — HIGH (needs >~62s intro)
- *Fix:* anchor the physical file start to bar 33 rather than subtracting the kick onset; at minimum clamp `base_start = max(CLIP_START_BEATS, …)` and `clip_start >= 0` in als_patcher.

**12. Single lone 'Dry' stem is wrapped in a group-of-1** — MED. *Fix:* mirror the category `>=2` guard before tagging `group_key='dry'`.

## A testing plan to surface this class proactively

Real packs are how these surface — so **manufacture the packs**. Build a `Tests/Fixtures/` set of tiny synthetic torture-packs (short generated WAVs, a few seconds each) plus a batch smoke test that builds every one and asserts on the Session Report, so the silent-drop class fails loudly in CI instead of on a real job.

**Torture-pack fixtures (one folder each):**
- `all_subfolder_categories/` — Drums/ Bass/ Vocals/ Synths/, no top-level audio → assert **all four** categories present.
- `stems_plus_ref_update/` — Stems/ + REF/ + UPDATE STEMS/, no top-level audio → assert refs>0 AND updated>0.
- `multiversion_plus_ref/` — Extended/ + Radio/ + REF/ → assert 2 versions AND refs>0.
- `macos_zip/` — a real Mac-made zip with `__MACOSX/._*.wav` → assert track count == real stem count (no phantoms).
- `float32_extensible/` — stems written with fmt tag 0xFFFE → assert flat-ref peak is sane (not full-scale noise).
- `mixed_samplerate/` — mostly 44.1k + one 48k kick → assert flat-ref summed the majority.
- `octave_fold/` — a 70 BPM and a 174 BPM kick → assert an octave-verify flag fires.
- `rebuild_twice/` — build a REF pack, build again into the same folder → assert reference-track count is stable.
- `generic_names/` + `spanish_names/` → assert an "N unclassified" flag fires when ML is off.
- `long_intro/` — extended stems with a 75s pre-kick intro → assert no clip writes Time < 0.

**Batch smoke test:** loop the fixtures through `run_batch`, load each `Session Report.json`, and assert (a) no exception, (b) expected refs/updated/version counts, (c) the expected flags present. This directly closes the gap that let the zip bug ship — it turns "only shows up on a real pack" into a red test.

Wire the same source-tree cross-check into `validate_project` (a REF/UPDATE folder existed in the input but the report shows zero → hard flag), so even un-fixtured shapes get caught at build time.

## Add vs don't-add (honest)

**Add (small and sharp):**
- **Pre-open flag checklist on the Result Card** (effort S) — the machinery exists (`_collect_flags`, `_write_session_report`); make it run on the multiversion path and render as a hard pane *before* "Open in Ableton". The payoff is Sam reading "kept this out of the sum / BPM low-confidence / these stems were silent" before he opens, not weeks later.
- **Read-only QC verdict on the flat-ref sum** (effort L) — true-peak/clip, integrated loudness, DC offset, dead-stem detection, and a kick-vs-sub polarity check, computed on the acc buffer bounce.py already holds. Green/amber/red lamp + a line in the report, **never** auto-correct. Validate thresholds against known-bad packs and his ear first. This is the one net-new thing that speaks his language as an engineer and is the honest productisation hook later.

**Finish (don't add on top of unfinished):**
- **The EXE + self-updater loop** — scaffolded and unit-tested but has never produced a single EXE and `feed_url()` dead-ends. One build, feed live, one smoke test.
- **Verify-on-real-machine items** — drag-drop bridge, native window, WM branding, sub-groups toggle: done in code, unvalidated in the one environment that matters. Just run it once.
- **Kill the hardcoded paths** — gitignore `Config/project_builder.json` and remove the `C:\Users\Carillon\…` defaults; they break every from-source run on the Mac.

**Don't add (yet):**
- Anodised Faceplate reskin / PROCESS fader / sampled thunk / VU-needle ballistics — sales theatre for an audience that doesn't exist; changes zero .als files.
- Truthful 9-band live spectra / kill fake waveforms — decoration for the deliverable (a one-line honesty fix is fine; a live-meter subsystem is not).
- Scrub-to-hear / WebAudio audition — Sam auditions in Ableton two clicks later; this is a mini-DAW inside the setup app.
- Learned house-style / per-label memory / accuracy ledger — depends on a corrections loop that doesn't exist; the "learned AI" framing over-claims exactly what the tool should be honest about.
- Multi-DAW / AAF / Pro Tools export — weeks of format reverse-engineering for zero current users; correctly parked.
- Speculative classifier keyword bolting — let real packs surface missing words; fix them one failing filename at a time.

The through-line: the bugs that bite on real jobs are **structural pack-shape** bugs, not vocabulary or polish. Fix `_find_audio_root` + the float-WAV decode + the chop misfire, wire flags into the multiversion path, ship the pre-open flags and the QC lamp, then hammer it with real packs.