# A4 — Deep-nesting / format-wrapper support (plan)

## Problem (proven on synthetic packs, 2026-07-13)

`classify_stems` (stem_classifier.py) and `detect_versions` (versions.py, via
`_audio_in`) **both** scan only one subfolder level. Measured behaviour:

| Pack shape | Today |
|---|---|
| flat | ✅ all placed |
| `Drums/Kick.wav` (one level) | ✅ all placed |
| `Drums/24bit WAV/Kick.wav` (**format wrapper**) | ❌ **0 placed — empty build, no flag** |
| top + `Drums/Perc/Shaker.wav` (partial) | ❌ deep stems **silently dropped** |
| `Extended/WAV/…` + `Radio/WAV/…` | ❌ **0 placed — empty build, no flag** |

The format-wrapper case (stems under `24bit WAV/` / `WAVs/` / `Audio/`) is a
common real delivery shape and produces a **completely empty project, silently**.

## Fix

### Part A — make scanning nest-aware

**A1. `versions.py` — split the one-level helper into `here` vs `under`.**
- `top = _audio_here(folder)` (direct children only — the top-level-stem test must
  stay shallow).
- A subdir is a candidate when it has audio *anywhere under it*; a version/category
  subfolder's files come from `_audio_under(d)` (recursive, `__MACOSX`/dotfile
  excluded). `_pick_base` and `_detect_subfolder_versions` use `_audio_under`.
- Net effect: a version behind a format wrapper (`Extended/WAV/…`) now resolves and
  mirrors correctly; a *category* folder behind a wrapper (`Drums/WAV/…`) still
  fails the mirror test → flattened into one version → `detect_versions` returns
  None → single path (where A2 catches it). Same mirroring logic, now depth-proof.

**A2. `stem_classifier.classify_stems` — recurse depth-first.**
Replace the two-level scan with a depth-first walk that emits *top files sorted,
then recurse each sorted subdir* (skip `__MACOSX`/dotfile dirs). For a one-level
pack this reproduces the **exact old track order** (proven by the harness); deeper
nesting extends it naturally.

**A3. `project_builder._extract_special_dirs` — ancestor-aware.**
A `REF/` or `updated stems/` folder can now sit at any depth. Sift by checking every
ancestor dir up to (not incl.) root, nearest wins — not just the immediate parent.

### Part B — coverage backstop (single-version path)

Independent of classify_stems, compute a recursive manifest of all source audio
(`__MACOSX`/dotfile excluded) and diff it against everything classification claimed
(classified + references + unclassified + updated + refcompare), captured **before**
WAV normalisation rewrites the paths. Any leftover is wired in as a parked reference
+ a "needs a look" flag — mirroring the multi-version path's existing `mv_leftovers`.
Because the manifest is an *independent* rglob, this fires if classify_stems ever
regresses again → the guarantee "no source audio is ever silently dropped".

## Regression proof

- `Scripts/m1_refactor_harness.py` `snapshot` on current code → `compare` after the
  change. Admonic (single, flat) exercises A2; Fallon (multi, one-level) exercises
  A1. Both **must** produce byte-identical `.als` XML + report — recursion only adds
  files that a shallow pack doesn't have, so real one-level packs are unchanged.
- New synthetic tests: format-wrapper single, partial deep, fully-nested versions,
  deep REF folder, coverage-flag fires when a file is excluded.
