"""M1 refactor safety harness — prove the head/tail extraction changes nothing.

Builds two real fixtures (Admonic = single-version, Fallon = multi-version) into
FIXED, freshly-wiped output folders (fixed path so the .als absolute paths match
between runs), decompresses each .als to XML, and snapshots the XML + report.

  snapshot  -> build both fixtures, save baseline XML+report (run on CURRENT code)
  compare   -> build both fixtures, diff against the saved baseline (run after each
               pure-extraction stage; a pure refactor MUST produce identical XML)

Determinism: use_ml=False (no Demucs), same source, fixed output path. Any XML
diff after a pure extraction = a behaviour change = a bug.
"""
import sys
import gzip
import json
import shutil
import difflib
from pathlib import Path

REPO = Path(r"C:\Users\Carillon\Wired Masters Dropbox\Sam Wills\0.1---GIT HUB---\Ableton Project Setup")
sys.path.insert(0, str(REPO / "Source"))
from project_builder import build_project

HERE = Path(__file__).resolve().parent
OUT = HERE / "m1_builds"        # fixed output base (path-stable across runs)
BASE = HERE / "m1_baseline"     # saved baseline snapshots
SAM = REPO.parents[1]           # ...\Sam Wills

FIXTURES = {
    "single": {
        "source": SAM / "2.1. Finished Stem Mixes" / "Admonic - Sunbeam [Adam Weiner] Project" / "Audio",
        "artist": "Admonic", "title": "Sunbeam", "label": "Adam Weiner",
    },
    "multi": {
        "source": SAM / "2.1. Finished Stem Mixes" / "Fallon - No Panties [Black Book] Project" / "Audio",
        "artist": "Fallon", "title": "No Panties", "label": "Black Book",
    },
}


def _build(key):
    """Build a fixture into a fixed, freshly-wiped folder; return (als_xml, report)."""
    fx = FIXTURES[key]
    out = OUT / key
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    folder = Path(build_project(str(fx["source"]), fx["artist"], fx["title"], fx["label"],
                                bpm="auto", output_base=str(out), use_ml=False))
    als = next(folder.glob("*.als"))
    xml = gzip.open(als, "rt", encoding="utf-8", errors="replace").read()
    rep_path = folder / "Reports" / "Session Report.json"
    report = json.loads(rep_path.read_text(encoding="utf-8")) if rep_path.exists() else {}
    return xml, report


def snapshot():
    BASE.mkdir(parents=True, exist_ok=True)
    for key in FIXTURES:
        xml, report = _build(key)
        (BASE / (key + ".als.xml")).write_text(xml, encoding="utf-8")
        (BASE / (key + ".report.json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("snapshot %-7s: %d XML chars, report keys=%d" % (key, len(xml), len(report)))
    print("baseline saved ->", BASE)


def compare():
    ok = True
    for key in FIXTURES:
        base_xml = (BASE / (key + ".als.xml")).read_text(encoding="utf-8")
        base_rep = json.loads((BASE / (key + ".report.json")).read_text(encoding="utf-8"))
        xml, report = _build(key)
        xml_same = (xml == base_xml)
        rep_same = (report == base_rep)
        print("compare %-7s: XML %s | report %s"
              % (key, "MATCH" if xml_same else "DIFF", "MATCH" if rep_same else "DIFF"))
        if not xml_same:
            ok = False
            diff = list(difflib.unified_diff(base_xml.splitlines(), xml.splitlines(),
                                             "baseline", "current", lineterm="", n=1))
            print("  --- first XML diffs (%d diff lines) ---" % len(diff))
            for line in diff[:40]:
                print("  " + line[:160])
        if not rep_same:
            ok = False
            bk, ck = set(base_rep), set(report)
            print("  report key diffs:", (bk ^ ck) or "(same keys, values differ)")
            for k in sorted(bk & ck):
                if base_rep[k] != report[k]:
                    print("   ", k, ":", repr(base_rep[k])[:80], "->", repr(report[k])[:80])
    print("=== ALL MATCH (behaviour preserved) ===" if ok else "=== DIFFERENCES FOUND ===")
    return ok


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
    if mode == "compare":
        sys.exit(0 if compare() else 1)
    snapshot()
