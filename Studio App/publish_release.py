"""Version-bump + publish a release to the PRIVATE releases repo via `gh`.

    # 1. Bump the version (edits VERSION only):
    py -3.13 "Studio App/publish_release.py" --bump patch
    # 2. Build the EXE (bakes the bumped VERSION + the read-only token):
    py -3.13 "Studio App/build_exe.py"
    # 3. Publish: cut a GitHub Release on the PRIVATE repo + upload the EXE:
    py -3.13 "Studio App/publish_release.py" --publish --notes "What changed"

The EXE + a sha256 go to the private repo's Releases; the app self-updates from
there using its baked read-only token (see updater.py). Publishing uses the `gh`
CLI with Sam's own GitHub login — no token is baked for publishing. The source
repo stays private; the release repo is ALSO private (the tool must not be
publicly downloadable).
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
VERSION_FILE = APP_DIR / "VERSION"
FEED_CONFIG = APP_DIR / "update_feed.json"
DIST = APP_DIR / "dist"
EXE_NAME = "StemToAbleton.exe"


def _read_version():
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return "0.0.0"


def _bump(version, part):
    nums = [int(x) for x in (version.split(".") + ["0", "0", "0"])[:3]]
    idx = {"major": 0, "minor": 1, "patch": 2}[part]
    nums[idx] += 1
    for j in range(idx + 1, 3):
        nums[j] = 0
    return ".".join(str(n) for n in nums)


def _repo():
    try:
        return (json.loads(FEED_CONFIG.read_text(encoding="utf-8"))
                .get("repo") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _publish(notes):
    """Cut a GitHub Release on the private repo (tag = current VERSION) and upload
    the built EXE + its sha256, via `gh`. Returns an exit code."""
    repo = _repo()
    if not repo:
        print("REFUSED: no 'repo' set in update_feed.json.")
        return 2
    exe = DIST / EXE_NAME
    if not exe.exists():
        print("REFUSED: no built EXE at " + str(exe) + " — run build_exe.py first.")
        return 2
    if subprocess.run(["gh", "--version"], capture_output=True).returncode != 0:
        print("REFUSED: the GitHub CLI `gh` isn't available/logged in. "
              "Install it + `gh auth login`, then retry.")
        return 2
    version = _read_version()
    tag = version if version.startswith("v") else "v" + version
    sha = _sha256(exe)
    body = "sha256: " + sha + ("\n\n" + notes if notes else "")
    cmd = ["gh", "release", "create", tag, str(exe),
           "--repo", repo, "--title", "v" + version.lstrip("v"),
           "--notes", body]
    print("Publishing v%s to PRIVATE repo %s ..." % (version, repo))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("gh release create FAILED:\n" + (res.stderr or res.stdout))
        return 1
    print("Released: " + (res.stdout.strip() or tag))
    print("sha256:   " + sha)
    print("The packaged app will now see v%s at %s and self-update." % (version, repo))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bump + publish a Studio App release.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--bump", choices=["major", "minor", "patch"])
    g.add_argument("--set", dest="set_version")
    ap.add_argument("--publish", action="store_true",
                    help="cut a GitHub Release on the private repo + upload the EXE")
    ap.add_argument("--notes", default="")
    args = ap.parse_args(argv)

    # Guard the self-update loop: --bump changes VERSION, but the EXE bakes its
    # VERSION at BUILD time. Bump BEFORE building; publish (at the current VERSION)
    # AFTER. Doing both in one call would tag a release newer than any built EXE.
    if (args.bump or args.set_version) and args.publish:
        print("REFUSED: don't bump AND publish in one call — the release would be "
              "newer than the built EXE (update loop). Bump first, build, THEN "
              "run again with --publish only.")
        return 2

    if args.bump or args.set_version:
        current = _read_version()
        new = args.set_version or _bump(current, args.bump)
        VERSION_FILE.write_text(new + "\n", encoding="utf-8")
        print("VERSION: %s -> %s" % (current, new))
        print("Next: build the EXE (build_exe.py), then --publish.")
        return 0

    if args.publish:
        return _publish(args.notes)

    print("Nothing to do. Use --bump/--set to version, or --publish to release.")
    print("Current VERSION: " + _read_version())
    return 0


if __name__ == "__main__":
    sys.exit(main())
