"""Studio App launcher — a native window wrapping the engine.

Renders Web/index.html in a PyWebView window and bridges it to the Python
engine via engine_api.Api. Run:  py -3.13 "Studio App/app.py"
Package to a single EXE with PyInstaller (see README.md).
"""
import sys
from pathlib import Path

import webview

from engine_api import Api

APP_DIR = Path(__file__).resolve().parent
# When frozen by PyInstaller, bundled data (Web/) is extracted under _MEIPASS.
_BASE = Path(getattr(sys, "_MEIPASS", APP_DIR)) if getattr(sys, "frozen", False) else APP_DIR
INDEX = _BASE / "Web" / "index.html"


def main():
    api = Api()
    window = webview.create_window(
        "Stem → Ableton  ·  Studio Setup",
        url=str(INDEX),
        js_api=api,
        width=1180,
        height=820,
        min_size=(960, 680),
        background_color="#0E0F13",
    )
    api._window = window  # enable native folder-picker dialogs
    webview.start(debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
