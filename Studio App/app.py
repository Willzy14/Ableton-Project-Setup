"""Studio App launcher — a native window wrapping the engine.

Renders Web/index.html in a PyWebView window and bridges it to the Python
engine via engine_api.Api. Run:  py -3.13 "Studio App/app.py"
Package to a single EXE with PyInstaller (see README.md).
"""
import json
import sys
import traceback
from pathlib import Path

import webview
import webview.dom  # DOMEventHandler + document event bridge for OS drag-drop

from engine_api import Api

APP_DIR = Path(__file__).resolve().parent
# When frozen by PyInstaller, bundled data (Web/) is extracted under _MEIPASS.
_BASE = Path(getattr(sys, "_MEIPASS", APP_DIR)) if getattr(sys, "frozen", False) else APP_DIR
INDEX = _BASE / "Web" / "index.html"


def _wire_native_drop(window):
    """Register a document-level OS drag-drop handler.

    HTML5 drag-drop in a webview does NOT expose real filesystem paths
    (Chromium/WebView2 blanks File.path). pywebview 6.x solves this: when a drop
    handler is registered through its *Python* DOM API, the backend captures the
    dropped files' true paths and attaches them to each file as
    ``pywebviewFullPath`` in the Python-side event. We register on ``document``
    so a drop anywhere in the window is caught, pull the real paths, and hand
    them back to the front-end (which routes them to the card the user dropped
    on — see app.js __wmActiveDropCard / __wmReceiveDrop).

    Must run after the page has loaded (the DOM element bridge needs a live DOM).
    """
    try:
        document = window.dom.document

        def _on_drop(event):
            try:
                files = (event.get("dataTransfer") or {}).get("files") or []
                paths = [f.get("pywebviewFullPath") for f in files
                         if f.get("pywebviewFullPath")]
                if not paths:
                    return
                # Hand the real OS paths to the front-end for routing. JSON-encode
                # so backslashes/spaces survive the JS string literal intact.
                payload = json.dumps(paths)
                window.evaluate_js(
                    f"window.__wmReceiveDrop && window.__wmReceiveDrop({payload})"
                )
            except Exception:  # noqa: BLE001 — never let a bad drop kill the app
                traceback.print_exc()

        # DOMEventHandler lets us preventDefault so the webview doesn't try to
        # navigate to / open the dropped file itself. dragover must also be
        # prevented for the drop event to fire at all.
        document.on("dragover", webview.dom.DOMEventHandler(
            lambda e: None, prevent_default=True))
        document.on("drop", webview.dom.DOMEventHandler(
            _on_drop, prevent_default=True))
    except Exception:  # noqa: BLE001 — drop is a nicety; picker still works
        traceback.print_exc()


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
    # Wire OS drag-drop once the DOM is live (needs the loaded event).
    window.events.loaded += lambda: _wire_native_drop(window)
    webview.start(debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
