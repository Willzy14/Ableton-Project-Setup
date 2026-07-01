"""Detect the SHAPE of a stem package.

Producers deliver stems in several shapes; this resolves the folder tree so the
builder can lay them out correctly:

  - VERSIONS (extended / radio edit / dub): the same song in different
    arrangements. A subfolder whose element names MIRROR the top-level stems is
    an alternate version -> laid out as a separate timeline section on shared
    tracks. (Same-folder name-token versions, e.g. "S16" vs "S17 SHRT EDIT",
    are a later detector.)
  - CATEGORY subfolders (drum stems / vox stems / instruments): one version
    split by type. Their elements are UNIQUE (don't mirror), so they're
    flattened ("stacked up") into the version.

Returns an ordered list of versions [{name, files:[Path]}] (primary first), or
None for a single flat version (caller uses the normal path).
"""
import re
from pathlib import Path

AUDIO_EXT = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".m4a"}

# Tokens that mark an alternate VERSION rather than a different element — a
# session/version code (Sam's "S16"/"S17"), or an arrangement keyword. Stripping
# these lets the same element pair across versions (kick-on-kick), and is what
# splits a single flat folder into name-token versions (Get Right S16 vs S17).
_VERSION_TOKEN_RE = re.compile(
    r"(?i)\b(?:s\d{1,3}|v\d{1,3}|radio|shrt|short|edit|dub|instrumental|inst|extended)\b")

# Cut-down keywords — a version carrying one of these is a shorter edit, so it's
# never the primary (fullest) arrangement.
_CUTDOWN_KW = ("radio", "shrt", "short", "edit", "dub")


def element_key(path):
    """The element name, stripped of the producer's '<prefix>_<element>' tag
    AND of any version token, so the same element pairs across versions."""
    name = Path(path).stem
    elem = name.rsplit("_", 1)[1] if "_" in name else name
    stripped = re.sub(r"\s+", " ", _VERSION_TOKEN_RE.sub(" ", elem)).strip().lower()
    # Don't collapse an element that is ONLY a version token to empty.
    return stripped or re.sub(r"\s+", " ", elem).strip().lower()


def _audio_in(folder):
    return [f for f in sorted(Path(folder).iterdir())
            if f.is_file() and f.suffix.lower() in AUDIO_EXT]


def _pick_base(subdirs):
    """Choose the primary (longest) version among version subfolders.

    Prefer a name that reads as the full arrangement (extended/full/club/
    original), de-prefer the cut-downs (radio/edit/dub), then fall back to the
    folder with the most stems — the extended cut is normally the fullest.
    """
    def score(d):
        n = d.name.lower()
        if any(k in n for k in ("extend", "full", "club", "original")):
            kw = 2
        elif any(k in n for k in ("radio", "edit", "dub", "short")):
            kw = 0
        else:
            kw = 1
        return (kw, len(_audio_in(d)))
    return max(subdirs, key=score)


def _detect_subfolder_versions(subdirs, mirror_threshold):
    """Versions that live entirely in subfolders (no top-level stems).

    The fullest/extended subfolder is the baseline; another subfolder whose
    element keys mirror it (>= threshold) is an alternate version, and one that
    doesn't is a category subfolder flattened into the primary.
    """
    if len(subdirs) < 2:
        return None
    base = _pick_base(subdirs)
    base_elems = {element_key(f) for f in _audio_in(base)}
    versions = []
    primary_extra = []
    for d in subdirs:
        if d == base:
            continue
        files = _audio_in(d)
        elems = {element_key(f) for f in files}
        overlap = len(base_elems & elems) / len(elems) if elems else 0
        if overlap >= mirror_threshold:
            versions.append({"name": d.name, "files": files})
        else:
            primary_extra.extend(files)  # category subfolder -> flatten in
    if not versions:
        return None
    return [{"name": base.name, "files": _audio_in(base) + primary_extra}] + versions


def _strip_export_index(stem):
    """Drop a leading producer export index ('01_', '03 - ') from a filename."""
    return re.sub(r"^\s*\d{1,3}[_\-\s.]+", "", stem).strip()


def _nametoken_parts(path):
    """(base, variant) for a flat-folder stem: the element identity with version
    tokens removed, and the version tokens themselves joined as the variant."""
    core = _strip_export_index(Path(path).stem)
    tokens = _VERSION_TOKEN_RE.findall(core)
    base = re.sub(r"[_\-]", " ", _VERSION_TOKEN_RE.sub(" ", core))
    base = re.sub(r"\s+", " ", base).strip().lower()
    variant = re.sub(r"\s+", " ", " ".join(tokens)).strip().lower()
    return base, variant


def _detect_nametoken_versions(top_files, mirror_threshold, min_stems=3):
    """Split a single flat folder into versions distinguished by a name token.

    Get Right ships "…S16…" and "…S17 SHRT EDIT…" stems in ONE folder — the same
    song, two arrangements, told apart by a token rather than a subfolder. This
    groups the stems by their version token and returns them as versions when the
    groups cleanly MIRROR each other (same elements, different arrangement).

    Deliberately conservative — it returns None unless 2+ token groups each hold
    `min_stems`, cover most of the folder, and mirror each other in BOTH
    directions — so a normal pack with an incidental "edit"/"dub" stem is never
    mis-split (and its files are never dropped).
    """
    if len(top_files) < min_stems * 2:
        return None
    groups = {}
    for f in top_files:
        base, variant = _nametoken_parts(f)
        groups.setdefault(variant, []).append((f, base))

    qualifying = {v: items for v, items in groups.items() if len(items) >= min_stems}
    if len(qualifying) < 2:
        return None
    if sum(len(i) for i in qualifying.values()) < 0.6 * len(top_files):
        return None

    ref_v = max(qualifying, key=lambda v: len({b for _f, b in qualifying[v]}))
    ref_bases = {b for _f, b in qualifying[ref_v]}
    for v, items in qualifying.items():
        bases = {b for _f, b in items}
        inter = len(ref_bases & bases)
        # Symmetric mirror: an alt version covers most of the primary's elements
        # AND is mostly made of them — a small fragment fails the ref direction.
        if not bases or inter / len(ref_bases) < mirror_threshold \
                or inter / len(bases) < mirror_threshold:
            return None

    def score(v):
        return (0 if any(k in v for k in _CUTDOWN_KW) else 1, len(qualifying[v]))

    ordered = sorted(qualifying, key=score, reverse=True)
    return [{"name": (v.upper() if v else "Main"),
             "files": [f for f, _b in qualifying[v]]} for v in ordered]


def detect_versions(stem_folder, mirror_threshold=0.5):
    """Return ordered versions [{name, files}] or None for a single version.

    A subfolder is an alternate VERSION when >= mirror_threshold of its element
    keys also appear in the baseline stems; otherwise it's a CATEGORY subfolder
    and its files are flattened into the primary version. The baseline is the
    top-level stems when present, or — when the pack is ALL subfolders with
    nothing at the top level (e.g. "Extended/" + "Radio/") — the fullest
    subfolder.
    """
    folder = Path(stem_folder)
    top = _audio_in(folder)
    subdirs = [d for d in sorted(folder.iterdir())
               if d.is_dir() and _audio_in(d)]

    if not top:
        # No top-level baseline: versions may live entirely in subfolders.
        return _detect_subfolder_versions(subdirs, mirror_threshold)

    if not subdirs:
        # Pure flat folder — versions may be distinguished by a name token
        # (Get Right "S16" vs "S17 SHRT EDIT") rather than a subfolder.
        return _detect_nametoken_versions(top, mirror_threshold)

    base_elems = {element_key(f) for f in top}
    versions = []
    primary_extra = []
    for d in subdirs:
        files = _audio_in(d)
        elems = {element_key(f) for f in files}
        overlap = len(base_elems & elems) / len(elems)
        if overlap >= mirror_threshold:
            versions.append({"name": d.name, "files": files})
        else:
            primary_extra.extend(files)  # category subfolder -> flatten in

    if not versions:
        return None
    return [{"name": "Extended", "files": top + primary_extra}] + versions
