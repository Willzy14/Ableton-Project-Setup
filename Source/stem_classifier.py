"""Classify stems into mix categories based on filename patterns.

Each stem gets assigned a category which determines its track position,
colour, and grouping in the Ableton project.

Priority order (most specific first): reference > kick > sends > vocals >
bass > music > fx > drums. This ensures compound names like "BREAK CHORDS"
land in music (chord) not drums (break).
"""
import re
from pathlib import Path

CATEGORIES = {
    "kick": {"color": 6, "order": 1, "group": False},
    "drums": {"color": 6, "order": 2, "group": True},
    "bass": {"color": 24, "order": 3, "group": True},
    "music": {"color": 8, "order": 4, "group": True},
    "vocals": {"color": 13, "order": 5, "group": True},
    "fx": {"color": 55, "order": 6, "group": True},
    "sends": {"color": 17, "order": 7, "group": False},
}

KICK_PATTERNS = [
    r"\bkick",
    r"\bkik\b",
    r"\bkck\b",
    r"\bk\b",
    r"\bbd\b",
    r"\bbdrum",
    r"\bbass.?drum",
]

BASS_PATTERNS = [
    r"\bbass",
    r"\bsub\b",
    r"\blow.?end",
]

DRUMS_PATTERNS = [
    r"\bdrum",
    r"\bdrm\b",
    r"\bsnare",
    r"\bsn\b",
    r"\bclaps?\d*\b",
    r"\bhats?\b",
    r"\bhh\b",
    r"\bhi.?hat",
    r"\bpercs?\b",
    r"\bpercussion",
    r"\bshaker",
    r"\btamb",
    r"\bcymbal",
    r"\bcymb\b",
    r"\bconga",
    r"\btop.?loop",
    r"\btop.?drum",
    r"\btops?\b",
    r"\bcabasa",
    r"\bbreaks?\b",
    r"\bbreakbeat",
    r"\brim",
    r"\btoms?\b",
    r"\bcrash",
    r"\bride\b",
    r"\bfills?\b",
    r"\b808\b",
    r"\bloop\b",
    r"\btimp",
]

MUSIC_PATTERNS = [
    r"\bsynth",
    r"\bchords?\b",
    r"\bmelod",
    r"\bpiano",
    r"\bkeys?\b",
    r"\bpads?\b",
    r"\bstring",
    r"\borgan\b",
    r"\bstabs?\b",
    r"\binstrument",
    r"\blead\b",
    r"\barp\b",
    r"\bharps?\b",
    r"\bdrone",
    r"\bmusic\b",
    r"\bsample",
    r"\bguitar",
    r"\bpluck",
    r"\bbells?\b",
    r"\bbrass",
    r"\bhorns?\b",
    r"\bflute",
    r"\bmarimba",
    r"\bchime",
    r"\bmallet",
    r"\bnexus",
    r"\bserum",
    r"\bsylenth",
    r"\bmassive\b",
    r"\belectric.?piano",
    r"\brhodes",
    r"\bwurlitzer",
    r"\bclavinet",
    r"\bsine\b",
    r"\bsounds?\b",
]

VOCAL_PATTERNS = [
    r"\bvocal",
    r"\bvox",
    r"\bacapella",
    r"\bvoice",
    r"\bsinging",
    r"\blead.?v",
    r"\bld.?vx",
    r"\blv\b",
    r"\bbacking",
    r"\bbg.?vx",
    r"\bbgv",
    r"\bbvs?\b",
    r"\bb vs\b",
    r"\bharm\b",
    r"\bchoir",
    r"\bchop",
]

FX_PATTERNS = [
    r"\bfx",
    r"\bsfx",
    r"\beffect",
    r"\briser",
    r"\bimpact",
    r"\bsweep",
    r"\bnoise\b",
    r"\btexture",
    r"\batmosph",
    r"\bambien",
    r"\bvinyl",
    r"\bdownlift",
    r"\buplift",
    r"\btransition",
    r"\bwhoosh",
    r"\bbuild\b",
    r"\bhit\b",
]

SEND_PATTERNS = [
    r"\breverb",
    r"\bdelay\b",
    r"\bchorus\b",
    r"\becho\b",
    r"\breturn\b",
    r"\baux\b",
    r"\bsend\b",
    r"[a-e]\s*-\s*(reverb|delay|chorus|echo|smile|compress)",
    r"\bendless.?smile\b",
]

REFERENCE_PATTERNS = [
    r"\boriginal.?mix",
    r"\breference",
    r"\bref.?bounce",
    r"\btest.?mix",
    r"\brough.?mix",
    r"\bscratch.?mix",
    r"\bcurrent\b",
    r"\bmaster\b",
    r"\bflat.?mix",
    r"\bpre.?master",
    r"\bfull.?mix",
    r"\b2[\s_-]?mix\b",
    r"\bmixdown",
    r"\bsw\s+v\d",
    r"\bsw\s+flat",
]

AUDIO_EXTENSIONS = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".m4a"}

CATEGORY_PREFIX = {
    "kick": "DR",
    "drums": "DR",
    "bass": "Bass",
    "music": "SY",
    "vocals": "Vox",
    "fx": "FX",
    "sends": "Send",
}

WORD_MAP = {
    "kick": "Kick", "kik": "Kick", "bd": "Kick", "bdrum": "Kick",
    "snare": "Snare", "snares": "Snare", "sn": "Snare",
    "clap": "Clap", "claps": "Clap",
    "hat": "HiHat", "hats": "HiHat", "hh": "HiHat", "hihat": "HiHat",
    "perc": "Perc", "percs": "Perc", "percussion": "Perc",
    "cymbal": "Cymbal", "cymb": "Cymbal",
    "ride": "Ride", "crash": "Crash",
    "tom": "Tom", "toms": "Tom",
    "shaker": "Shaker", "tamb": "Tamb", "tambourine": "Tamb",
    "timp": "Timp", "timpani": "Timp", "loop": "Loop",
    "bass": "Bass", "sub": "Sub", "reece": "Reece",
    "synth": "Synth", "string": "String", "strings": "String",
    "piano": "Piano", "keys": "Keys", "key": "Keys",
    "pad": "Pad", "pads": "Pad",
    "organ": "Organ", "stab": "Stab", "stabs": "Stab",
    "lead": "Lead", "arp": "Arp",
    "bell": "Bell", "bells": "Bell",
    "brass": "Brass", "horn": "Horn", "horns": "Horn",
    "flute": "Flute", "guitar": "Guitar", "pluck": "Pluck",
    "marimba": "Marimba", "chime": "Chime", "rhodes": "Rhodes",
    "vocal": "Vocal", "vocals": "Vocal", "vox": "Vox", "voice": "Vocal",
    "lv": "LV", "bgv": "BGV", "backing": "Backing",
    "choir": "Choir", "stacks": "Stacks",
    "fx": "FX", "sfx": "FX",
    "riser": "Riser", "impact": "Impact", "sweep": "Sweep",
    "noise": "Noise", "texture": "Texture",
}


def _matches_any(name_lower, patterns):
    return any(re.search(p, name_lower) for p in patterns)


def _score_category(name):
    """Return (category, is_reference) using priority-ordered matching.

    Order: reference > kick > sends > vocals > bass > music > fx > drums.
    More specific categories checked first so compound names resolve correctly.
    """
    has_kick = _matches_any(name, KICK_PATTERNS)
    has_bass = _matches_any(name, BASS_PATTERNS)
    has_sends = _matches_any(name, SEND_PATTERNS)
    has_vocals = _matches_any(name, VOCAL_PATTERNS)
    has_music = _matches_any(name, MUSIC_PATTERNS)
    has_fx = _matches_any(name, FX_PATTERNS)
    has_drums = _matches_any(name, DRUMS_PATTERNS)

    if has_kick and not has_bass:
        return "kick", False

    if has_sends:
        return "sends", False

    if has_vocals:
        return "vocals", False

    if has_bass:
        return "bass", False

    if has_music:
        return "music", False

    if has_drums:
        return "drums", False

    if has_fx:
        return "fx", False

    if _matches_any(name, REFERENCE_PATTERNS):
        return None, True

    return None, False


def classify_stem(filename):
    """Classify a single stem file into a category.

    Returns (category, is_reference) where category is one of:
    kick, drums, bass, music, vocals, fx, sends, or None.
    """
    name = Path(filename).stem
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)
    name = name.lower()
    name = re.sub(r"[_\-\.]+", " ", name)
    name = " " + name + " "
    return _score_category(name)


def classify_stems(stem_folder):
    """Classify all audio files in a folder.

    Returns:
        classified: dict of {category: [Path, ...]} ordered by track position
        references: list of Path for reference/full mix files
        unclassified: list of Path for files that couldn't be classified
    """
    stem_folder = Path(stem_folder)

    all_files = []
    for f in sorted(stem_folder.iterdir()):
        if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS:
            all_files.append(f)

    for sub in sorted(stem_folder.iterdir()):
        if sub.is_dir():
            for f in sorted(sub.iterdir()):
                if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS:
                    all_files.append(f)

    classified = {cat: [] for cat in CATEGORIES}
    references = []
    unclassified = []

    for f in all_files:
        category, is_ref = classify_stem(f.name)
        if is_ref:
            references.append(f)
        elif category:
            classified[category].append(f)
        else:
            unclassified.append(f)

    classified = {k: v for k, v in classified.items() if v}

    return classified, references, unclassified


def _normalize_stem_name(stem_name):
    """Normalize a stem filename for descriptor extraction."""
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", stem_name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)
    name = re.sub(r"[_\-\.]+", " ", name)
    return name.split()


def _extract_descriptor(words):
    """Find the first category-relevant word and return everything from there."""
    for i, w in enumerate(words):
        wl = w.lower()
        clean = re.sub(r"\d+$", "", wl)
        if wl in WORD_MAP or clean in WORD_MAP:
            return words[i:]
        parts = _try_split_compound(wl)
        if len(parts) > 1:
            return words[i:]
    return words[-1:] if words else []


def _try_split_compound(word):
    """Split a compound word into known WORD_MAP parts."""
    if word in WORD_MAP:
        return [word]
    for key in sorted(WORD_MAP.keys(), key=len, reverse=True):
        if word.startswith(key) and len(key) < len(word):
            rest = word[len(key):]
            rest_parts = _try_split_compound(rest)
            if all(p in WORD_MAP or re.match(r"^\d+$", p) for p in rest_parts):
                return [key] + rest_parts
    return [word]


def _clean_descriptor(raw_words):
    """Merge fragments, split compounds, and map to clean display names."""
    words = [w.lower() for w in raw_words]

    merged = []
    i = 0
    while i < len(words):
        if i + 1 < len(words):
            combined = words[i] + words[i + 1]
            parts = _try_split_compound(combined)
            if len(parts) > 1:
                merged.extend(parts)
                i += 2
                continue
        parts = _try_split_compound(words[i])
        merged.extend(parts)
        i += 1

    result = []
    for w in merged:
        clean = re.sub(r"\d+$", "", w)
        num = w[len(clean):] if clean != w else ""
        if clean in WORD_MAP:
            result.append(WORD_MAP[clean])
            if num:
                result.append(num)
        elif w in WORD_MAP:
            result.append(WORD_MAP[w])
        elif re.match(r"^\d+$", w):
            result.append(w)
        elif len(w) <= 2:
            result.append(w.upper())
        else:
            result.append(w.title())
    return result


def generate_track_name(stem_name, category):
    """Generate a display name for an Ableton track from a stem filename."""
    words = _normalize_stem_name(stem_name)
    desc_words = _extract_descriptor(words)
    parts = _clean_descriptor(desc_words)
    prefix = CATEGORY_PREFIX.get(category, "")
    descriptor = " ".join(parts)

    if category == "kick":
        return "DR Kick"

    if category == "bass":
        if descriptor.startswith("Bass "):
            return descriptor
        if descriptor == "Bass":
            return "Bass"
        return "Bass " + descriptor

    if category in ("vocals", "fx"):
        skip = {"Vox", "Vocal"} if category == "vocals" else {"FX"}
        if parts and parts[0] in skip:
            parts = parts[1:]
        descriptor = " ".join(parts)

    if prefix and descriptor:
        return prefix + " " + descriptor
    return prefix or descriptor


def apply_track_names(stems):
    """Generate display names for a list of stems, numbering duplicates.

    Modifies each stem dict in place, adding a 'display_name' key.
    """
    for s in stems:
        s["display_name"] = generate_track_name(s["name"], s["category"])

    name_counts = {}
    for s in stems:
        n = s["display_name"]
        name_counts[n] = name_counts.get(n, 0) + 1

    name_seen = {}
    for s in stems:
        n = s["display_name"]
        if name_counts[n] > 1:
            idx = name_seen.get(n, 0) + 1
            name_seen[n] = idx
            if idx == 1:
                s["display_name"] = n
            else:
                s["display_name"] = n + " " + str(idx)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python stem_classifier.py <stem_folder>")
        sys.exit(1)

    classified, refs, unknown = classify_stems(sys.argv[1])

    for cat, files in sorted(classified.items(), key=lambda x: CATEGORIES[x[0]]["order"]):
        color = CATEGORIES[cat]["color"]
        print(cat.upper() + " (color " + str(color) + "):")
        for f in files:
            print("  " + f.name)

    if refs:
        print("\nREFERENCES:")
        for f in refs:
            print("  " + f.name)

    if unknown:
        print("\nUNCLASSIFIED:")
        for f in unknown:
            print("  " + f.name)
