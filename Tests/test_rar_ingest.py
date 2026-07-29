"""Studio App: a .rar stem pack must extract and build, not silently produce an
empty folder that then fails with a baffling "no usable rhythmic stem" BPM error
(Sam hit this live on a real pack — 'Slot Machine STEMS.rar').
"""
import sys
import zipfile
import tempfile
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Source"))
sys.path.insert(0, str(ROOT / "Studio App"))
import engine_api as E


def _make_rar(rar_path, members):
    """Build a real .rar via whatever extractor's paired archiver is on this
    machine (WinRAR's Rar.exe, if present) so the test exercises the real
    extraction path. Falls back to skipping if nothing can create one."""
    exe, kind = E._find_rar_extractor()
    if not exe:
        return False
    rar_exe = str(Path(exe).with_name("Rar.exe")) if kind == "unrar" else exe
    src_dir = Path(tempfile.mkdtemp())
    for name, data in members.items():
        (src_dir / name).write_bytes(data)
    if kind == "unrar" and Path(rar_exe).exists():
        cmd = [rar_exe, "a", "-y", str(rar_path)] + [str(src_dir / n) for n in members]
    else:
        cmd = [exe, "a", str(rar_path)] + [str(src_dir / n) for n in members]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return r.returncode == 0 and rar_path.exists()


def test_extractor_detection_does_not_crash():
    # Just proves the probe runs cleanly; result depends on the machine.
    exe, kind = E._find_rar_extractor()
    assert (exe is None) == (kind is None)


def test_rar_extraction_and_ingest():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        rar_path = tmp / "pack.rar"
        wav = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
        made = _make_rar(rar_path, {"Kick.wav": wav, "Bass.wav": wav})
        if not made:
            print("SKIP: no RAR archiver available on this machine to build a test fixture")
            return
        staged = tmp / "staged"
        result = E.prepare_stem_folder([rar_path], staged)
        found = list(result.rglob("*.wav"))
        assert len(found) == 2, "expected both stems extracted, got: " + str(found)


def test_no_extractor_raises_clear_error(monkeypatch=None):
    """When no extractor is found, the error must be actionable, not a silent
    empty-folder build-later-fails-mysteriously."""
    orig = E._find_rar_extractor
    E._find_rar_extractor = lambda: (None, None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                E._extract_rar(Path(tmp) / "fake.rar", Path(tmp) / "out")
                raised = False
            except ValueError as e:
                raised = True
                assert "no rar extractor" in str(e).lower() or "extractor" in str(e).lower()
            assert raised, "expected a clear ValueError when no extractor is present"
    finally:
        E._find_rar_extractor = orig


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
        except Exception:  # noqa: BLE001
            failed += 1
            print("FAIL", fn.__name__)
            traceback.print_exc()
    print(("ALL PASS" if not failed else str(failed) + " FAILED"))
    sys.exit(1 if failed else 0)
