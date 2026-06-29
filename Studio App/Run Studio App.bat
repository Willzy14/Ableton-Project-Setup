@echo off
REM Stem -> Ableton — studio launcher.
REM Runs from the Dropbox-synced source so updates flow automatically: when a
REM new version is committed and Dropbox syncs it here, the next launch is
REM already up to date. Pin a desktop shortcut to this file.
cd /d "%~dp0"

REM Best-effort: grab the newest code if this is a git checkout and online.
REM (Harmless if offline or not a git repo — the app still launches.)
where git >nul 2>nul && if exist "..\.git" git -C ".." pull --ff-only 1>nul 2>nul

py -3.13 "%~dp0app.py" %*
