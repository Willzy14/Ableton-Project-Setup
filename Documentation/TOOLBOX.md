# Ableton Project Setup Toolbox

## Core Commands

Build a project with auto BPM detection:

```powershell
py -3.13 Source\project_builder.py "<stem_folder>" "<Artist>" "<Title>" "<Label>"
```

Build with explicit BPM:

```powershell
py -3.13 Source\project_builder.py "<stem_folder>" "<Artist>" "<Title>" "<Label>" 122
```

Config/env overrides:

```powershell
$env:ABLETON_TEMPLATE_PATH = "C:\Path\To\Template.als"
$env:ABLETON_OUTPUT_BASE = "C:\Path\To\Output Folder"
$env:PYTHON_ML_EXE = "C:\Path\To\python.exe"
$env:ENABLE_ML_CLASSIFIER = "true"
$env:ENABLE_KICK_DETECTOR = "true"
$env:KICK_DETECTOR_PYTHON_EXE = "py -3.14"
```

Defaults live in `Config\project_builder.json`. Environment variables win over the config file.

Standalone BPM check:

```powershell
py -3.13 Source\bpm_detector.py "<kick_or_drum_stem.wav>"
```

Syntax check changed modules:

```powershell
py -3.13 -m py_compile Source\project_builder.py Source\stem_classifier.py Source\audio_ml_classify.py
```

Moby tempo regression:

```powershell
py -3.13 Tests\test_moby_tempo_selection.py
```

Multi-version ML classification regression:

```powershell
py -3.13 Tests\test_multiversion_ml_classification.py
```

Multi-version alignment regression:

```powershell
py -3.13 Tests\test_multiversion_alignment.py
```

Config regression:

```powershell
py -3.13 Tests\test_project_config.py
```

Validate a generated Ableton project:

```powershell
py -3.13 Source\validate_project.py "<project-folder-or-als>" --expect-tempo 160
```

## Important Modules

- `Source/project_builder.py` - Orchestrates folder scan, classification, BPM detection, project folder creation, flat-ref bounce, ALS patching, and the Ableton folder icon (`apply_ableton_folder_icon`). Reports (Session Report + ML Classification Report) write into a `Reports/` subfolder via `_reports_dir()`; `session_report_path()` resolves it for readers (falls back to the project root for older builds).
- `Config/project_builder.json` - Local defaults for template path, output base, ML interpreter, and ML enablement. Environment variables override it.
- `Source/stem_classifier.py` - Filename-based stem classification and display track-name generation. `classify_stems()` walks the stem folder **depth-first to any depth** (2026-07-13, A4) — a format-wrapper pack (`Drums/24bit WAV/Kick.wav`) no longer builds empty; one-level order is byte-identical to the old scan; skips `__MACOSX`/dotfile/output folders via `versions.is_skip_dir`. Also `find_dry_stems()` — detects explicit WET+DRY vocal pairs (used vocals-only by the builder) so the dry copy can be parked. `FX_STRONG_PATTERNS` (downer/sub-drop/riser/uplifter) outranks bass/music; `hook`/`topline` are guarded weak vocal signals (a real instrument name overrides them) — see 2026-07-02 fix.
- `Source/audio_ml_classify.py` - Heavy second-stage audio classifier for unnamed stems; uses Demucs and Whisper when installed.
- `Source/stem_analysis.py` - Lightweight numpy audio analysis for full-mix and group-bus detection.
- `Source/als_patcher.py` - Raw-text ALS patching engine. Do not replace with XML parsing. `find_audio_regions(return_peak=True)` returns TRUE PEAK (not windowed RMS, since 2026-07-02 — a sparse stem like a quiet shaker needs true peak to not be false-flagged as silent); silence floor `SILENCE_FLOOR_DB = -66 dBFS`. Group runs support per-run muted/unfolded/colour (used by the parked "Dry" group).
- `Source/bounce.py` - Flat-reference WAV summing, numpy fast path plus stdlib fallback.
- `Source/versions.py` - Multi-version package detection. Scans are **nest-aware** (2026-07-13, A4): `_audio_here()` = direct children only (the shallow top-level-stem test), `_audio_under()` = recursive (sees a version behind a format wrapper, `Extended/WAV/…`) but excludes `__MACOSX`/dotfile/output folders **and** special ref/update branches (a nested `REF/` is gathered by project_builder, not counted as a version member). `is_skip_dir()` — shared skip predicate (macOS junk, dotfiles, the tool's own output folders: Reports/Ableton Project Info/MASTER RENDERS/Backup). `element_key()` strips a trailing 1-2 digit export index before pairing (2026-07-06). `sorted_element_key()` (order-independent fallback, consulted only when `element_key` misses — pairs a reversed-word-order element like `FX_FILLS`/`FILLS_FX` across versions). `dry_pair_key()` (wet/dry-stripped, order-independent — needed because `element_key` collides every `_DRY` stem to `'dry'`).
- `Source/bpm_detector.py` - BPM detection from kick/drum stems. Default/fallback is the pure-stdlib energy onset picker; optional Kick Detector V3 mode lazy-calls the sibling `Kick Detector/Source/infer.py::KickModel` with `Models/kick_crnn_V3.pt` and feeds its onsets into the existing lattice fit. On `STUDIO-2`, local `Config/project_builder.json` enables this via subprocess mode (`kick_detector_python_exe: "py -3.14"`) because Python 3.13 lacks `librosa`.
- `Source/project_builder.py` additions (2026-07-06/08): `_resolve_project_bpm()` — a filename-labelled BPM is a HINT verified against the audio (never trusted outright); `_safe_filename()` — sanitises user-typed names before they become folder/`.als` paths; `_analysis_off_flags()` — flags when numpy is absent (full-mix/bus safety nets can't run); `_make_project_context()` / `_patch_and_validate()` / `_finish_project()` — the shared head/tail extracted from both build paths in the M1 refactor (see `Documentation/M1_REFACTOR_PLAN.md`, complete). Deep-nesting (2026-07-13, A4): `_all_source_audio()` — canonical recursive manifest for the single-path coverage backstop (nothing silently dropped); `_copy_stem_dest()` — collision-safe copy destinations so two deep stems sharing a basename don't overwrite each other; `_extract_special_dirs()` is ancestor-aware (a `REF/`/`updated stems/` folder at any depth). See `Documentation/A4_DEEP_NESTING_PLAN.md`.
- `Scripts/m1_refactor_harness.py` - Before/after safety harness for the M1 refactor: rebuilds two real fixtures (Admonic=single, Fallon=multi) into fixed folders and diffs decompressed `.als` XML + report for byte-identical behaviour. `snapshot` / `compare` modes. Re-run after any `project_builder.py` build-path change.
- `Scripts/audit_classifier_vs_projects.py` - Mines every finished project's clip name→colour as classifier ground truth; reports agreement rate + ranked gaps. Re-run after any `stem_classifier.py` change.

## Validation Notes

- `Source\validate_project.py` is the canonical project checker. It accepts either a project folder or an `.als` path and checks gzip/XML readability, expected manual tempo, expected tempo automation, Session Time first, FLAT REF/reference routing, and referenced audio files.
- Kick Detector smoke for the BPM path:
  `ENABLE_KICK_DETECTOR=1 KICK_DETECTOR_PYTHON_EXE="py -3.14" py -3.13 Source\bpm_detector.py "<kick stem.wav>"`
- `verify_output.py` has a hardcoded ALS path and does not honor CLI arguments. Do not trust it for arbitrary outputs.
- For Desktop builds, validate the generated `.als` by parsing the gzip XML and checking track count, group layout, file references, and presence of the flat-ref bounce.
- For unnamed-stem ML builds, always inspect `ML Classification Report.txt`; the model can make plausible but still review-worthy calls, especially vocal-vs-music.

## Known Local Environment

> **REQUIRED: Python 3.13.** This project targets **Python 3.13** explicitly via
> `py -3.13`. The launcher defaults to 3.14, which has known interpreter
> instability on hot loops and lacks this project's pinned ML stack.
> **Do not remove or downgrade Python 3.13** — the Studio App
> (`Studio App/Run Studio App.bat`) and every documented command in this file
> assume it exists. If `py -3.13` ever errors with *"No suitable Python runtime
> found"*, see the recovery block at the bottom of this section.

- Python 3.13.14 is installed at `%LOCALAPPDATA%\Programs\Python\Python313\python.exe`
  (on this machine: `C:\Users\Carillon AC-1\AppData\Local\Programs\Python\Python313\python.exe`).
  Always address it via `py -3.13`, not by full path, so the launcher finds it
  regardless of which `Carillon` user profile runs the build.
- Python 3.13 has `numpy`, `soundfile`, `pywebview` (Studio App), and the ML
  stack installed for this project.
- Python 3.13 ML stack verified on 2026-06-26:
  - `torch 2.12.1+cpu`
  - `torchaudio 2.11.0+cpu`
  - `demucs 4.0.1`
  - `faster-whisper 1.2.1`
- The launcher still marks Python 3.14 as default, so use explicit `py -3.13`
  commands for normal builds and tests.
- Python 3.14 has shown interpreter instability on hot loops. Use `PYTHON_JIT=0`
  only if forced to run 3.14.
- The default template path is configured in `Config\project_builder.json` as:
  `C:\Users\Carillon\Documents\Ableton\User Library\Templates\Ableton Project Set Up 250 Tracks.als`

**Recovery — reinstall Python 3.13 (if it disappears):**

```powershell
# 1. Install Python 3.13.14 (matches this repo's pinned version)
winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements

# 2. Refresh PATH so this shell sees the new install
$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')

# 3. Confirm the launcher can see it
py -0    # should list -V:3.13 alongside 3.14 and 3.12

# 4. Repopulate the per-project packages (engine + Studio App)
py -3.13 -m pip install pywebview numpy soundfile torch torchaudio demucs faster-whisper
```

Then `Studio App\Run Studio App.bat` will come up again without changes.
Verify with `py -3.13 Source\validate_project.py --help` (prints without error).

## Recent Real-World Test

Fallon multi-version radio-edit alignment:

- Input copied from: `C:\Users\Carillon\Wired Masters Dropbox\Sam Wills\2.1. Finished Stem Mixes\Fallon - No Panties [Black Book] Project\Audio`
- Verified output: `Test Builds 2\Fallon - No Panties [Black Book CODEX VERIFY 6] Project`
- Tempo: 128 BPM from Extended.
- Alignment policy: later-version stack is placed at the next phrase slot, then all clips in that version are nudged together so the earliest credible kick-named layer lands on-grid.
- Compared against Sam's manual `SW Fix`: Edit STems clip starts match within about `0.0012` beats.
- Validation command passed on 2026-06-26:
  `py -3.13 Source\validate_project.py "Test Builds 2\Fallon - No Panties [Black Book CODEX VERIFY 6] Project" --expect-tempo 128`

Moby unnamed-stem build:

- Input: `C:\Users\Carillon\Desktop\for now 160 multitracks 24 441`
- Output: `C:\Users\Carillon\Desktop\Mobi Project\Mobi.als`
- Report: `C:\Users\Carillon\Desktop\Mobi Project\ML Classification Report.txt`
- Validated by Codex on 2026-06-26: 62 ALS tracks, grouped Drums/Bass/Music/Vox, rough reference plus flat reference, 55 source WAVs copied plus `Mobi FLAT REF.wav`.
- Fresh rebuild by Codex on 2026-06-26 after Sam deleted the patched project because changing tempo after clip cutting moved the stems. New project was built from scratch at `C:\Users\Carillon\Desktop\Mobi Project\Mobi.als` using Python 3.14 with `PYTHON_JIT=0` so Demucs/Whisper were available.
- Rebuild selected 160 BPM from `hh_03.wav`, wrote both Main tempo and tempo automation at 160 from the start, classified 47/47 unnamed stems by audio, created 56 WAV files including `Mobi FLAT REF.wav`, and produced 146 unwarped audio clips.
- Validation command passed after the fresh rebuild on 2026-06-26:
  `py -3.13 Source\validate_project.py "C:\Users\Carillon\Desktop\Mobi Project" --expect-tempo 160`
