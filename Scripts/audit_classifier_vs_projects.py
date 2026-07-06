"""Audit the stem classifier against Sam's finished projects (ground truth).

Every AudioClip in a finished mix carries a Name (the stem filename) and a
Color (Sam's category, via his palette). We feed the name to the live
classifier and compare its verdict to the colour. Prints the agreement rate and
the disagreements grouped by (classifier -> Sam), most common first — the
disagreements are the classifier's remaining gaps.

Read-only: gzip + regex, never re-saves an .als. Re-run after any change to
Source/stem_classifier.py to see whether agreement went up.

    py -3.13 Scripts/audit_classifier_vs_projects.py
"""
import gzip
import re
import sys
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parents[1]        # the project root
sys.path.insert(0, str(ROOT / "Source"))
from stem_classifier import classify_stem

# Work folders live next to the "0.1---GIT HUB---" folder, under "Sam Wills".
SAM = ROOT.parents[1]                              # ...\Sam Wills
BASES = [SAM / "2.1. Finished Stem Mixes", SAM / "2. Ongoing Stem Mixes"]

COLOR_CAT = {6: "drums", 24: "bass", 8: "music", 13: "vocals", 55: "fx",
             17: "sends", 14: "reference"}
CLF_FAMILY = {"kick": "drums", "drums": "drums", "bass": "bass", "music": "music",
              "vocals": "vocals", "fx": "fx", "sends": "sends", "reference": "reference",
              None: "music"}  # None falls through to music in the real pipeline

CLIP_RE = re.compile(r"<AudioClip ")
NAME_RE = re.compile(r'<Name Value="([^"]*)"')
COL_RE = re.compile(r'<(?:ColorIndex|Color) Value="(-?\d+)"')


def project_als(folder):
    """Latest non-backup .als in a project folder (by mtime)."""
    cands = [p for p in folder.rglob("*.als")
             if "backup" not in [part.lower() for part in p.parts]]
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def clips_from_als(path):
    try:
        x = gzip.open(path, "rt", encoding="utf-8", errors="replace").read()
    except Exception:  # noqa: BLE001
        return
    for m in CLIP_RE.finditer(x):
        seg = x[m.start():m.start() + 2500]
        nm, col = NAME_RE.search(seg), COL_RE.search(seg)
        if nm and col:
            yield nm.group(1), int(col.group(1))


def strip_common_prefix(names):
    """Drop the artist/title/date prefix shared by every clip (for readable
    reporting only — the FULL name is what we classify, matching the pipeline)."""
    if not names:
        return {}
    toks = [n.split() for n in names]
    common = 0
    for i in range(min(len(t) for t in toks)):
        if len({t[i].lower() for t in toks}) == 1:
            common += 1
        else:
            break
    return {n: " ".join(n.split()[common:]) or n for n in names}


def main():
    seen, proj, total, agree = set(), 0, 0, 0
    disagreements = defaultdict(Counter)
    example = {}
    for base in BASES:
        if not base.exists():
            continue
        for folder in sorted(p for p in base.iterdir() if p.is_dir()):
            als = project_als(folder)
            if not als or als.resolve() in seen:
                continue
            seen.add(als.resolve())
            clips = list(clips_from_als(als))
            if not clips:
                continue
            proj += 1
            names = sorted({n for n, c in clips})
            colour_of = {}
            for n, c in clips:
                colour_of.setdefault(n, c)
            short = strip_common_prefix(names)
            for n in names:
                c = colour_of[n]
                if c not in COLOR_CAT or COLOR_CAT[c] == "reference":
                    continue
                sam = COLOR_CAT[c]
                total += 1
                # WITH an extension — the real pipeline sees stem *files*, so
                # Path.stem won't eat an internal dot ("1.0 - KICK" -> "1").
                cat, is_ref = classify_stem(n + ".wav")
                pred = "reference" if is_ref else CLF_FAMILY.get(cat, "music")
                if pred == sam:
                    agree += 1
                else:
                    tok = short.get(n, n).strip().lower()
                    disagreements[(pred, sam)][tok] += 1
                    example.setdefault(tok, n)

    print("\n==== SUMMARY ====")
    print(f"projects: {proj} | classifiable names: {total} | agree: {agree} | "
          f"disagree: {total - agree} | agreement: {100.0 * agree / max(total, 1):.1f}%")
    print("\n==== DISAGREEMENTS (classifier -> Sam), most common tokens ====")
    for (pred, sam), toks in sorted(disagreements.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"\n[{pred}  ->  should be {sam}]  ({sum(toks.values())} names)")
        for tok, n in toks.most_common(18):
            print(f"    {n:>3}x  {tok[:48]:<48}  e.g. {example.get(tok, '')[-46:]}")


if __name__ == "__main__":
    main()
