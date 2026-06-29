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

- `Source/project_builder.py` - Orchestrates folder scan, classification, BPM detection, project folder creation, flat-ref bounce, and ALS patching.
- `Config/project_builder.json` - Local defaults for template path, output base, ML interpreter, and ML enablement. Environment variables override it.
- `Source/stem_classifier.py` - Filename-based stem classification and display track-name generation. Also `find_dry_stems()` — detects explicit WET+DRY vocal pairs (used vocals-only by the builder) so the dry copy can be parked.
- `Source/audio_ml_classify.py` - Heavy second-stage audio classifier for unnamed stems; uses Demucs and Whisper when installed.
- `Source/stem_analysis.py` - Lightweight numpy audio analysis for full-mix and group-bus detection.
- `Source/als_patcher.py` - Raw-text ALS patching engine. Do not replace with XML parsing. `find_audio_regions(return_peak=True)` also returns peak window RMS (silence floor `SILENCE_FLOOR_DB`); group runs support per-run muted/unfolded/colour (used by the parked "Dry" group).
- `Source/bounce.py` - Flat-reference WAV summing, numpy fast path plus stdlib fallback.
- `Source/versions.py` - Multi-version package detection.

## Validation Notes

- `Source\validate_project.py` is the canonical project checker. It accepts either a project folder or an `.als` path and checks gzip/XML readability, expected manual tempo, expected tempo automation, Session Time first, FLAT REF/reference routing, and referenced audio files.
- `verify_output.py` has a hardcoded ALS path and does not honor CLI arguments. Do not trust it for arbitrary outputs.
- For Desktop builds, validate the generated `.als` by parsing the gzip XML and checking track count, group layout, file references, and presence of the flat-ref bounce.
- For unnamed-stem ML builds, always inspect `ML Classification Report.txt`; the model can make plausible but still review-worthy calls, especially vocal-vs-music.

## Known Local Environment

- Python 3.13.14 is installed at `C:\Users\Carillon\AppData\Local\Programs\Python\Python313\python.exe`.
- Python 3.13 has `numpy`, `soundfile`, and the ML stack installed for this project.
- Python 3.13 ML stack verified on 2026-06-26:
  - `torch 2.12.1+cpu`
  - `torchaudio 2.11.0+cpu`
  - `demucs 4.0.1`
  - `faster-whisper 1.2.1`
- The launcher still marks Python 3.14 as default, so use explicit `py -3.13` commands for normal builds.
- Python 3.14 has shown interpreter instability on hot loops. Use `PYTHON_JIT=0` only if forced to run 3.14.
- The default template path is configured in `Config\project_builder.json` as:
  `C:\Users\Carillon\Documents\Ableton\User Library\Templates\Ableton Project Set Up 250 Tracks.als`

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
