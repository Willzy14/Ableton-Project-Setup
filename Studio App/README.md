# Studio App — Stem → Ableton

A sleek desktop front-end (PyWebView) that wraps the `project_builder` engine so
the studio team can set up a whole day's projects without the command line.

## The flow
1. Pick your **profile** (top-right) — each profile carries its own Ableton
   colours for drums / bass / music / vox / fx / sends. A junior in someone
   else's room just flicks to that partner's profile.
2. **Output folder** is set once (top-right) and remembered.
3. For each project: **drop stems** (a folder, WAV/AIFF files, or a `.zip`),
   type the **title** as `Artist - Title [Label]`, optionally set a BPM
   (blank = auto-detect). Hit **+** to add more projects.
4. **Build all** → go make a cup of tea → come back to a folder of finished,
   validated Ableton projects.

Each project shows a live status chip (running / done / check / failed); a bad
pack flags itself and does **not** stop the rest of the batch.

## Run (dev)
```
py -3.13 -m pip install -r "Studio App/requirements.txt"
py -3.13 "Studio App/app.py"          # add --debug to open dev tools
```

## Build the EXE (PyInstaller)
```
py -3.13 -m PyInstaller --noconfirm --windowed --name "StemToAbleton" ^
  --add-data "Studio App/Web;Web" ^
  --add-data "Source;Source" ^
  "Studio App/app.py"
```
Notes:
- `--windowed` = no console; `--add-data` bundles the Web UI and the engine.
- **ML stack (Demucs/Whisper/torch) is huge (~GBs).** For a lean EXE, ship with
  the ML classifier **off** (set `ENABLE_ML_CLASSIFIER=0` or in
  `Config/project_builder.json`) — filename classification already covers
  properly-named packs. To keep ML, point `PYTHON_ML_EXE` at a full 3.13 with
  the ML deps rather than bundling them.
- First run writes `Studio App/Config/profiles.json` + `settings.json`.

## Config
- `Config/profiles.json` — saved colour profiles (per user/partner).
- `Config/settings.json` — output folder + active profile.

## What's wired vs next
- Wired: profiles + colour picker, folder/file/zip ingest (AIFF→WAV via
  soundfile), title parsing, per-project BPM, batch runner with per-project
  validation, live progress.
- Next: native OS drag-drop of real paths (currently click-to-browse is the
  reliable path; drag-drop falls back to the picker), packaged-EXE smoke test,
  optional logo/branding pass.
