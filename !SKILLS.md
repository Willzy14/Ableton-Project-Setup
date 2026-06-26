# Ableton Project Setup Skills

This repo follows Sam's shared AI workflow from the global `AGENTS.md`.
Use this file as the local quick reference when opening the project cold.

## Required Session Flow

1. Read `Documentation/AI_CONTEXT.md`.
2. Read `.github/memory.json`.
3. Read the last entries in `.github/ai-activity-log.md`.
4. Skim `.github/copilot-instructions.md`.
5. Run `git status --short` and check recent commits.
6. If the last activity-log entry is `STARTED` without a matching `DONE`, inspect `git diff` before changing anything.

## Local Commands

- `/bootstrap` - repair or create project context files.
- `/session-start` - summarise current state and pending work.
- `/session-end` - update docs/logs, validate, commit, push if requested.
- `/audit` - check docs against actual code.
- `/validate` - prove a change or generated ALS output works before reporting success.
- `/conventional-commit` - create a conventional commit from current changes.

## Project-Specific Validation

Syntax check:

```powershell
py -3.13 -m py_compile Source\project_builder.py Source\stem_classifier.py Source\audio_ml_classify.py
```

Build command:

```powershell
py -3.13 Source\project_builder.py "<stem_folder>" "<Artist>" "<Title>" "<Label>" [bpm]
```

Validate a generated project:

```powershell
py -3.13 Source\validate_project.py "<project-folder-or-als>" --expect-tempo 128
```

Generated ALS files are gzip-compressed XML but must be patched as raw text. Do not use XML rewriting libraries for writes.

## Current Priority

1. Review the Fallon CODEX VERIFY 6 and Moby projects in Ableton.
2. Add ML subprocess timeout/temp cleanup.
3. Add same-folder version-token detection.
4. Add wet/dry handling.
5. Decide precise-BPM policy for long unwarped versions.
