# Scripts — one-off dev / analysis scaffolding

Ad-hoc tools written while reverse-engineering the Ableton `.als` format and
building the pipeline. **None of these are part of the build pipeline** — the
canonical code lives in `Source/` and the real tests in `Tests/`. They're kept
for reference (inspecting a template, dumping colours, checking a generated
project by eye). Many have hardcoded paths.

| Script | What it does |
| ------ | ------------ |
| `analyze_als.py` / `analyze_colors.py` / `analyze_template.py` | Dump structure / clip colours / track layout from an `.als`. |
| `extract_clip.py` / `extract_group_track.py` / `inspect_template_track.py` | Pull the raw XML for a clip / GroupTrack / track out of the template. |
| `verify_grouptrack.py` / `verify_heights.py` / `verify_output.py` | Eyeball checks on a generated project. **Superseded by `Source/validate_project.py`** — prefer that; `verify_output.py` has a hardcoded path. |
| `find_tempo.py` / `find_tempo2.py` | Early tempo probes. **Superseded by `Source/bpm_detector.py`.** |
| `test_build.py` / `test_classifier.py` | Early ad-hoc smoke scripts. **Superseded by the `Tests/` suite.** |
