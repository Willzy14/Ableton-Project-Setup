"""Stamp a release: bump VERSION and write latest.json for the public feed.

    py -3.13 "Studio App/publish_release.py" --bump patch  --notes "What changed"
    py -3.13 "Studio App/publish_release.py" --set 0.2.0   --notes "..."

Writes Studio App/dist/latest.json describing the build. The download_url is
taken from --url, else from the `release_base` in update_feed.json (the public
folder/repo the EXE is hosted in), else left as a TODO placeholder. Publishing
itself (uploading StemToAbleton.exe + latest.json to the public feed) stays a
manual/your-call step — this script just prepares the metadata. The code repo
stays PRIVATE; only the EXE + latest.json go to the public feed.
"""
import argparse
import json
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


def _release_base():
    try:
        return (json.loads(FEED_CONFIG.read_text(encoding="utf-8"))
                .get("release_base") or "").strip().rstrip("/")
    except Exception:  # noqa: BLE001
        return ""


def main(argv=None):
    ap = argparse.ArgumentParser(description="Prepare a Studio App release.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--bump", choices=["major", "minor", "patch"])
    g.add_argument("--set", dest="set_version")
    ap.add_argument("--notes", default="")
    ap.add_argument("--url", default="", help="explicit download URL for the EXE")
    args = ap.parse_args(argv)

    current = _read_version()
    if args.set_version:
        new = args.set_version
    elif args.bump:
        new = _bump(current, args.bump)
    else:
        new = current
    VERSION_FILE.write_text(new + "\n", encoding="utf-8")

    base = _release_base()
    download_url = args.url or ((base + "/" + EXE_NAME) if base else
                                "TODO-set-release_base-in-update_feed.json")

    DIST.mkdir(parents=True, exist_ok=True)
    latest = {"version": new, "download_url": download_url, "notes": args.notes}
    (DIST / "latest.json").write_text(json.dumps(latest, indent=2) + "\n",
                                      encoding="utf-8")

    print("VERSION: %s -> %s" % (current, new))
    print("Wrote " + str(DIST / "latest.json") + ":")
    print(json.dumps(latest, indent=2))
    print("\nNext steps (manual — the feed is public, the code repo is not):")
    print("  1. Build the EXE:  py -3.13 \"Studio App/build_exe.py\"")
    print("  2. Upload dist/" + EXE_NAME + " AND dist/latest.json to the public")
    print("     releases feed; set feed_url (and release_base) in update_feed.json")
    print("     to point at that latest.json once, then commit that.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
