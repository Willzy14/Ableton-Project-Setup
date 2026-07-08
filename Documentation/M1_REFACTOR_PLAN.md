# M1 refactor plan — unify the single/multi-version build paths (Codex-reviewed)

Status: **lined up, not started.** Plan reviewed adversarially by Codex (2026-07-08); its corrections
are folded in below. Do this as its own focused session — it touches core build orchestration.

## Direction (confirmed by Codex)
Extract the shared **head** and **tail** into narrow helpers, **keep the two middles separate**, and
close the parity gaps. Do NOT force a single `pv`-based path — a full unification would drag Fallon's
version-stack alignment into simple builds and subtly change single-version behaviour (per-version
audio namespaces, offsets, the "delivery batch?" BPM diagnostic, one-flat-ref-vs-per-version, etc.).

## The steps (each its own bisectable commit + tests)

1. **`_make_project_context(...)` — narrow head extraction.** Only: `_safe_filename` name →
   `project_folder`/`audio_folder`, create subfolders, `_find_preseeded_audio`, `source_names`.
   *Do NOT* pull normalise-to-WAV or BPM resolve into it — multi does those **per version** inside
   `_process_version_files`, so a shared "prepare incl. BPM" is not a pure extraction (that's the
   middle creeping into the head). Pure extraction → suite stays green.

2. **`_patch_and_validate(...)` + `_finish_project(...)` — split tail (not one mega-helper).**
   Common tail is only: `patch_project` → `_validate_als_flags` → write report → icon → rmtree staging.
   Report **assembly stays in each path** (schemas differ: single has real `dry_parked`/`silent`/matched
   updated + one flat-ref peak; multi has `versions`/per-version bounces/leftovers/locators). Shape:
   ```
   als_flags = _patch_and_validate(als_path, all_stems, bpm, locators)
   report["flags"] += als_flags
   _finish_project(project_folder, report, cleanup_paths=[wav_staging, ...])
   ```

3. **Parity gap — multi silent-stem parking (per version, not union).** The real fix point:
   multi region detection (`_process_version_files`, ~L1565) doesn't pass `return_peak=True` (single does,
   ~L1200). Add it and park silent stems — but **per clip**: if Extended's `Kick` is valid and Radio's
   `Kick` is silent, park only the silent Radio clip, don't move the shared Kick track to the bottom.
   Tests: primary silent/later valid · primary valid/later silent · both silent · silent dry pair.

4. **Parity gap — multi wet/dry (PER VERSION).** ⚠ My first plan said "run on the multi union" —
   Codex correctly flagged that as WRONG: a union falsely pairs Radio's `DRY` with Extended's `WET`.
   Do dry-stem detection inside `_process_version_files` on **that version's vocal files only**, return a
   `dry_stems` collection, and stack parked dry tracks across versions with the existing shared-track /
   `extra_clips` pattern (before each version's flat-ref bounce, so the dry is excluded from the sum).

5. **Parity gap — multi updated stems (separate commit).** Single matches updated stems next to their
   original and inherits group/subgroup metadata; multi currently appends every updated stem as muted
   `music` at the bottom AND passes those names to `_collect_flags` as if unmatched. Weaker + likely
   user-visible. List as its own commit after 3-4.

## Validation strategy (Codex-corrected)
- **Not** byte-identical — use **structural assertions** on the decompressed ALS: track count, clip
  count, group names, locators, tempo, references, report fields. Gzip metadata / ordering can differ
  without behaviour changing.
- **Rebuild into a FRESH output folder** (rebuilding into an existing project folder changes preseeded-ref
  behaviour by design).
- Before/after on steps 1-2 (pure extraction): structural equality on a real single-version pack AND the
  real Fallon multi-version pack. Steps 3-5 get new targeted tests (they're intended behaviour changes).
- Each step a separate commit so a regression bisects cleanly.

## What NOT to touch
The MIDDLE — clip offsets, phrase-slot placement, kick-grid nudge (Fallon alignment). Head/tail only.
