@echo off
REM Stem -> Ableton — studio launcher.
REM Runs from the Dropbox-synced source so updates flow automatically: when a
REM new version is committed and Dropbox syncs it here, the next launch is
REM already up to date. Pin a desktop shortcut to this file.
cd /d "%~dp0"

REM Best-effort: grab the newest code if this is a git checkout and online.
REM (Harmless if offline or not a git repo — the app still launches.)
where git >nul 2>nul && if exist "..\.git" git -C ".." pull --ff-only 1>nul 2>nul

REM First run needs the native-window library; install it if it's missing so
REM the app doesn't just flash and vanish.
py -3.13 -c "import webview" 1>nul 2>nul
if errorlevel 1 (
  echo Installing the window library ^(pywebview^) - first run only...
  py -3.13 -m pip install pywebview
)

py -3.13 "%~dp0app.py" %*

REM If the app exited with an error, keep this window open so the message is
REM readable instead of disappearing.
if errorlevel 1 (
  echo.
  echo ============================================================
  echo  The app closed with an error ^(see the message above^).
  echo  If this keeps happening, send the text above to Claude.
  echo ============================================================
  pause
)
