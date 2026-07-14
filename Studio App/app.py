"""Studio App launcher — a native window wrapping the engine.

Renders Web/index.html in a PyWebView window and bridges it to the Python
engine via engine_api.Api. Run:  py -3.13 "Studio App/app.py"
Package to a single EXE with PyInstaller (see README.md).
"""
import json
import sys
import traceback
from pathlib import Path

# Headless build-worker mode: the batch runner spawns this same program with
# --build-worker <job.json> so each project builds in an isolated process (a
# native crash costs one project, not the whole app). Intercept BEFORE any
# window/webview work.
if "--build-worker" in sys.argv:
    from build_worker import main as _worker_main
    sys.exit(_worker_main())

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
                # ALWAYS deliver (even an empty list) so the front-end's FIFO
                # queue shift stays 1:1 with card drops — a text/URL drop that
                # pushed a target must be consumed here, not left to misroute the
                # next real stem drop. JSON-encode so paths survive the literal.
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


def _webview2_installed():
    """True if the Edge WebView2 runtime is present (Windows only). Without it,
    pywebview falls back to the ancient MSHTML/IE11 engine, which can't run this
    UI's modern JS — so we warn instead of opening a broken, blank window."""
    if sys.platform != "win32":
        return True
    import winreg
    guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    # The per-machine 64-bit install lives under WOW6432Node; per-user under the
    # plain path. Check both, under HKLM and HKCU. (Getting this wrong is worse
    # than no check — it would falsely block a machine that HAS the runtime.)
    subkeys = (r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\%s" % guid,
               r"SOFTWARE\Microsoft\EdgeUpdate\Clients\%s" % guid)
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for sk in subkeys:
            try:
                with winreg.OpenKey(root, sk, 0, winreg.KEY_READ) as k:
                    pv, _ = winreg.QueryValueEx(k, "pv")
                    if pv and pv != "0.0.0.0":
                        return True
            except OSError:
                continue
    return False


def _warn_no_webview2():
    msg = ("Stem -> Ableton needs the Microsoft Edge WebView2 Runtime, which "
           "isn't installed on this PC.\n\nInstall it (free) from:\n"
           "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
           "then reopen the app.")
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "Stem -> Ableton", 0x10)
    except Exception:  # noqa: BLE001
        print(msg)


def main():
    # A BUNDLED WebView2 Fixed Version runtime (self-contained EXE) wins: point
    # pywebview at it so the app renders even on a machine with no system WebView2.
    # Only fall back to the machine's own runtime + the install prompt when there's
    # no bundle.
    bundled_wv2 = _BASE / "webview2"
    if getattr(sys, "frozen", False) and (bundled_wv2 / "msedgewebview2.exe").exists():
        import os
        os.environ["WEBVIEW2_BROWSER_EXECUTABLE_FOLDER"] = str(bundled_wv2)
    elif not _webview2_installed():
        _warn_no_webview2()
        return
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
