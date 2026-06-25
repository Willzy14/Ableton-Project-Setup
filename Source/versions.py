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


def detect_versions(stem_folder, mirror_threshold=0.5):
    """Return ordered versions [{name, files}] or None for a single version.

    A subfolder is an alternate VERSION when >= mirror_threshold of its element
    keys also appear in the top-level stems; otherwise it's a CATEGORY subfolder
    and its files are flattened into the primary version.
    """
    folder = Path(stem_folder)
    top = _audio_in(folder)
    if not top:
        return None  # no top-level baseline — caller's flatten handles this

    base_elems = {element_key(f) for f in top}
    versions = []
    primary_extra = []
    for d in sorted(folder.iterdir()):
        if not d.is_dir():
            continue
        files = _audio_in(d)
        if not files:
            continue
        elems = {element_key(f) for f in files}
        overlap = len(base_elems & elems) / len(elems)
        if overlap >= mirror_threshold:
            versions.append({"name": d.name, "files": files})
        else:
            primary_extra.extend(files)  # category subfolder -> flatten in

    if not versions:
        return None
    return [{"name": "Extended", "files": top + primary_extra}] + versions
