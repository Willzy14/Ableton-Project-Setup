# Codebase Review And Next Steps

Date: 2026-06-26
Reviewer: Codex
Context: first Codex pass over a repo mainly built by Claude, after the Moby unnamed-stem test.

## Summary

The project is already useful and the core direction is right. The strongest pieces are:

- Template-based ALS generation instead of XML rewriting.
- Track colour/order/grouping matched to Sam's workflow.
- Flat-reference bounce instead of a duplicated-stem ref group.
- Audio full-mix detection to keep refs out of the flat sum.
- Group-bus/submix detection to avoid double-counted stems.
- Optional Demucs + Whisper classification for unnamed stems.
- BPM selection now scores all rhythmic candidates and prefers credible consensus.

The main risk is that this has grown from research scripts into a real production tool without enough structure around config, validation, and repeatability. The next phase should focus less on new clever detection and more on making the pipeline reliable enough to hand to another engineer, another machine, or eventually a client-facing service.

## Highest Priority Fixes

### 1. Multi-version builds bypass the new ML classifier

File: `Source/project_builder.py`
Area: `_process_version_files()`

Status: **Completed by Codex on 2026-06-26 as Section 2.**

Single-version builds now do:

1. filename classification
2. full-mix safety check
3. ML classification for genuine unknowns
4. region detection
5. bus detection
6. naming/reporting

Multi-version builds used to skip this path. In `_process_version_files()`, unknown stems fell straight into `music`. A Moby-style unnamed multi-version pack would lose the main ML improvement.

Implemented change:

- `_process_version_files()` now keeps true filename-unknown stems separate instead of immediately placing them in `music`.
- It runs `_ml_classify_unknowns()` for those unknowns when `use_ml=True`.
- It falls back to `music` only when ML is disabled or unavailable.
- `build_project(..., use_ml=False)` now passes that flag through to `build_multiversion_project()`.
- Multi-version builds write per-version reports named `ML Classification Report - <Version>.txt` when a version has filename-unknown stems.

Validated on 2026-06-26:

- `py -3.13 Tests\test_multiversion_ml_classification.py` PASS.
- `py -3.13 Tests\test_validate_project.py` PASS.
- `py -3.13 Tests\test_moby_tempo_selection.py` PASS.

Remaining possible expansion:

- Extract a fully shared single-version/multi-version classification helper to reduce duplication further.
- Add an end-to-end multi-version fixture once a small safe test pack exists in the repo.

### 2. Multi-version grid alignment still has the old weak path

File: `Source/project_builder.py`
Area: `build_multiversion_project()`, version offset calculation

Status: **Completed by Codex on 2026-06-26 as Section 3.**

The single-version BPM selector now checks all rhythmic candidates and prefers credible BPM consensus. Multi-version offset logic still loops over kick/drum candidates and accepts the first `detect_bpm()` result for `first_beat_sec`.

Known issue from Claude:

- A later version can have pre-roll silence/pickup before the first real downbeat.
- `detect_bpm()` can return a folded grid phase rather than first actual kick/snare onset.
- This can place later sections slightly off-grid even if the tempo is correct.

Implemented change:

- `Source/bpm_detector.py::detect_bpm()` now returns `first_actual_onset_sec`, the first physical detected onset in the file.
- `Source/project_builder.py` now places later-version stacks on the next phrase slot after the previous version, currently the next 32-bar boundary after the configured 16-bar minimum gap.
- The whole later-version stack is then nudged by one shared amount so the earliest credible kick-named layer lands on that phrase grid. This is deliberately not the same as putting the dry kick at the version locator: if the radio edit has no dry kick at the start, a `Kick Bass Process`/processed kick layer can be the correct anchor.
- This keeps every stem in a version locked together while correcting the small grid offset Sam would do by dragging the whole stack left/right in Ableton.

Validated on 2026-06-26:

- `py -3.13 Tests\test_multiversion_alignment.py` PASS.
- `py -3.13 Tests\test_multiversion_ml_classification.py` PASS.
- `py -3.13 Tests\test_validate_project.py` PASS.
- `py -3.13 Tests\test_moby_tempo_selection.py` PASS.
- Real Fallon verification build:
  - Source copied from `C:\Users\Carillon\Wired Masters Dropbox\Sam Wills\2.1. Finished Stem Mixes\Fallon - No Panties [Black Book] Project\Audio`.
  - Output: `Test Builds 2\Fallon - No Panties [Black Book CODEX VERIFY 6] Project`.
  - Tempo: 128 BPM from the Extended version.
  - Radio stack kick-grid target: beat `1024.0`, the next 32-bar phrase boundary.
  - The kick-named processed layer starts about 1.41s into its source file, so the radio stack and locator are nudged to begin around beat `1020.992`.
  - The dry radio kick clip starts around beat `1087.979`, matching Sam's manually aligned `SW Fix` within about `0.0012` beats.
  - All Edit STems clips are moved together and match `SW Fix` within about `0.0012` beats. Source stems were copied only, never moved.

Remaining possible expansion:

- Still evaluate the separate precise-BPM drift issue for long unwarped versions (`127.71` vs rounded `128`).

### 3. Hardcoded paths block portability

File: `Source/project_builder.py`

Status: **Completed by Codex on 2026-06-26 as Section 4.**

Current hardcoded examples:

- Template path: `C:\Users\Carillon\Documents\Ableton\User Library\Templates\Ableton Project Set Up 250 Tracks.als`
- Output base: repo path under Dropbox.
- Tests reference Desktop Moby stems directly.

Implemented change:

- Added `Config/project_builder.json` with Sam's current defaults.
- Added config/env getters in `Source/project_builder.py`:
  - `get_template_path()`
  - `get_output_base()`
  - `get_ml_python_exe()`
  - `get_enable_ml_classifier()`
- Environment variables override config:
  - `ABLETON_TEMPLATE_PATH`
  - `ABLETON_OUTPUT_BASE`
  - `PYTHON_ML_EXE`
  - `ENABLE_ML_CLASSIFIER`
- `build_project()` now defaults `output_base` and `use_ml` from config/env when arguments are not supplied.
- `_ml_classify_unknowns()` now uses `PYTHON_ML_EXE`/config before falling back to the current interpreter.

Validated on 2026-06-26:

- `py -3.13 Tests\test_project_config.py` PASS.
- `py -3.13 Tests\test_validate_project.py` PASS.
- `py -3.13 Tests\test_multiversion_ml_classification.py` PASS.
- `py -3.13 Tests\test_multiversion_alignment.py` PASS.
- `py -3.13 Tests\test_moby_tempo_selection.py` PASS.

Remaining possible expansion:

- Move more CLI options into argparse so output base/project name/use-ML can be set without importing `build_project()`.
- Consider a machine-specific ignored override file later, if Sam uses different template paths on Mac/Windows.

### 4. Validation scripts are not trustworthy enough

File: `verify_output.py`

Status: **Completed by Codex on 2026-06-26 as Section 1.**

`verify_output.py` has a hardcoded ALS path and ignores arbitrary outputs. This already caused confusion during the Moby check.

Implemented change:

- Added `Source/validate_project.py`.
- Added `Tests/test_validate_project.py`.
- The validator accepts:

```powershell
py -3.13 Source\validate_project.py "<path-to-project-or-als>" --expect-tempo 160
```

It verifies:

- ALS gzip can be decompressed.
- Main tempo matches expected value if supplied.
- Main tempo automation matches the manual tempo/expected tempo. This specifically catches the Moby failure mode where `Tempo/Manual` was 160 but the `FloatEvent` automation still forced Ableton to 104.
- Track count is non-zero.
- Session Time exists first.
- Reference tracks are red, muted, and routed to Ext. Out.
- Flat ref exists and has a file ref.
- Every audio file referenced in ALS exists on disk.
- Build/ML/classification report exists.

Validated on 2026-06-26:

- `py -3.13 Tests\test_validate_project.py` PASS.
- `py -3.13 Source\validate_project.py "C:\Users\Carillon\Desktop\Mobi Project" --expect-tempo 160` PASS.
- `py -3.13 Tests\test_moby_tempo_selection.py` PASS.

Remaining possible expansion:

- Check group headers and child routing more deeply.
- Check flat-ref bounce reports for skipped files/sample-rate mismatches once the build report is structured.
- Fail if ML fallback occurred unexpectedly, once the ML environment is configurable.

### 5. Python 3.14 needs to be retired for this project

The repo has repeatedly hit Python 3.14 instability or weird write/compile behaviour. Claude already worked around hot loops with numpy, but the project should run under stable Python 3.13 for now.

Status: **Completed by Codex on 2026-06-26 as Section 5.**

Status on 2026-06-26:

- Python 3.13.14 installed.
- `numpy` and `soundfile` installed under Python 3.13.
- `Tests/test_moby_tempo_selection.py` passes under Python 3.13.
- Full ML stack is now installed and import-verified under Python 3.13:
  - `torch 2.12.1+cpu`
  - `torchaudio 2.11.0+cpu`
  - `demucs 4.0.1`
  - `faster-whisper 1.2.1`

Validated on 2026-06-26:

- `py -3.13 -c "import torch, demucs, faster_whisper, torchaudio"` PASS.
- `py -3.13 -m pip show torch demucs faster-whisper torchaudio` PASS.
- `py -3.13 Tests\test_project_config.py` PASS.
- `py -3.13 Tests\test_validate_project.py` PASS.
- `py -3.13 Tests\test_multiversion_ml_classification.py` PASS.
- `py -3.13 Tests\test_multiversion_alignment.py` PASS.
- `py -3.13 Tests\test_moby_tempo_selection.py` PASS.

Remaining possible expansion:

- Run one real 3.13 ML classification pass on a small stem pack when convenient, to verify model download/runtime beyond imports.
- Keep `PYTHON_JIT=0` only as a temporary fallback if Python 3.14 is used again.

## Medium Priority Improvements

### 6. ML subprocess needs cleanup and timeouts

File: `Source/project_builder.py`
Area: `_ml_classify_unknowns()`

Current concerns:

- Uses `tempfile.mkdtemp()` and does not clean the temp folder.
- `subprocess.run()` has no timeout.
- If Demucs/Whisper hangs, the build can hang indefinitely.

Recommended change:

- Use `tempfile.TemporaryDirectory()`.
- Add a timeout, probably configurable.
- Capture stderr/stdout into the build report.
- Treat partial ML failures per stem, not just all-or-nothing where possible.

### 7. Folder scanning is too shallow

File: `Source/stem_classifier.py`
Area: `classify_stems()`

Current behaviour:

- Scans top-level audio files.
- Scans one subfolder level.

Real packs can be deeper:

- `Stems/Audio/Drums/Kick.wav`
- `Wet/Drums/...`
- `Dry/Vox/...`
- `Version A/STEMS/...`

Recommended change:

- Build a dedicated package resolver before classification.
- Explicitly detect and label:
  - flat pack
  - category folders
  - version folders
  - wet/dry folders
  - ignore folders (`__MACOSX`, backups, renders, Ableton metadata)

### 8. Flat-reference bounce can silently be incomplete

Files: `Source/project_builder.py`, `Source/bounce.py`

`sum_stems_to_wav()` skips files with a different sample rate from the first stem and reports them in `summary["skipped"]`. The builder prints a warning but continues.

Risk:

- The FLAT REF might not equal the actual session if some stems were skipped.

Recommended change:

- Write skipped stems into `Build Report.txt`.
- Consider failing the build unless `--allow-sample-rate-skip` is set.
- Longer term: resample mismatched stems or use a consistent audio backend.

### 9. Confidence reporting should be first-class

The Moby ML report is useful. Make this standard for every build.

Recommended `Build Report.txt` sections:

- Source folder and project output.
- Detected package shape.
- Classification summary.
- Unknown stems and ML decisions.
- BPM candidates, consensus group, selected BPM, confidence.
- Full mixes moved to refs.
- Group buses detected and their likely members.
- Flat-ref bounce peak, engine, skipped files.
- Any warnings that require human review.

### 10. Repo hygiene needs a pass

Current repo includes:

- Root-level exploratory scripts.
- `*.tmp.*` files.
- `__pycache__`.
- Generated demo/test output folders.
- Validators with hardcoded local paths.

Recommended cleanup:

- Move one-off inspection scripts into `Automation/Diagnostics/`.
- Move generated builds into `Output/` and add to `.gitignore` if not already.
- Delete or ignore `*.tmp.*` and `__pycache__/`.
- Promote only reliable scripts into `Source/` or `Tests/`.

## Test Coverage Recommendations

Add lightweight regression tests for:

1. Moby tempo selection: snare/hat consensus beats bad kick.
2. Unknown stems get ML in both single-version and multi-version builds.
3. Full mixes named `Current`, `ROUGH LEVEL REF`, etc. become refs.
4. Group-bus detection catches known Coldabank/Far Away examples.
5. `verify_project.py` catches hardcoded-path validator mistakes.
6. Multi-version radio/edit onset alignment.
7. Track names for generic stems: `Vox`, `Vox 2`, not `Vox 02`.
8. Sample-rate mismatch in flat ref is reported or fails.

## Suggested Work Order For Claude

1. Build the canonical ALS/project validator.
2. Refactor classification into one shared pipeline.
3. Wire ML unknown-stem handling into multi-version builds.
4. Fix multi-version first-actual-onset alignment.
5. Add build reports.
6. Move hardcoded paths into config.
7. Clean repo structure and generated-output handling.
8. Move/verify the full ML stack under Python 3.13, or configure a deliberate 3.14 ML subprocess.
9. Re-run validation on Moby, Coldabank, Fallon, and one messy finished-mix pack.

## Notes For Sam

This is worth continuing. The Moby test exposed exactly the right failure modes:

- Filename-only classification is not enough.
- Kick-first BPM is not enough.
- A generated project needs an explanation report, not just an ALS file.

The tool is now past proof-of-concept. The next value comes from making it boringly reliable.
