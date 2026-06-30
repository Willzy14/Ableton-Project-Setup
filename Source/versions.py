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


def element_key(path):
    """The element name, stripped of the producer's '<prefix>_<element>' tag."""
    name = Path(path).stem
    elem = name.rsplit("_", 1)[1] if "_" in name else name
    return re.sub(r"\s+", " ", elem).strip().lower()


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
