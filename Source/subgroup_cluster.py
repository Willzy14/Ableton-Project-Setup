"""Cluster a working category's stems into nested sub-groups by filename tokens.

Singer-first for vocals (Vox -> singer; one/no singer -> Lead vs BGV by role);
Kit vs Percussion for drums; by-instrument for music. Only the vocals axis is
the headline feature — drums/music are offered and stay conservative.

A sub-group is only emitted with 2+ members; everything else stays loose inside
the parent group. `cluster_subgroups` returns the category's stems REORDERED
(sub-grouped stems first, in sub-group order, then loose stems) with
subgroup_key/subgroup_name/subgroup_color/subgroup_muted/subgroup_unfolded
tagged on the grouped stems — or None when no useful sub-grouping applies (the
caller then leaves the category as one flat group).
"""
import re

# Tokens that are never a singer's name (roles, sections, processing, glue).
VOCAL_NONNAME = {
    "lead", "leads", "ld", "lv", "main", "bgv", "bgvs", "bg", "backing", "back",
    "bv", "bvs", "harmony", "harmonies", "harm", "choir", "stack", "stacks",
    "double", "doubles", "dbl", "adlib", "adlibs", "ad", "lib", "libs",
    "vox", "vocal", "vocals", "voc", "vocs", "voice", "verse", "chorus", "pre",
    "hook", "bridge", "intro", "outro", "dry", "wet", "fx", "reverb", "verb",
    "delay", "throw", "throws", "echo", "tuned", "comp", "low", "high", "lo",
    "hi", "oct", "octave", "unison", "run", "runs", "falsetto", "whisper",
    "spoken", "rap", "gang", "response", "call", "all", "full", "sum", "mix",
    "master", "feat", "ft", "vp", "hpf", "sub", "top", "the", "and", "of",
}

LEAD_TOKENS = {"lead", "leads", "ld", "lv", "main"}
BGV_TOKENS = {"bgv", "bgvs", "backing", "back", "bv", "bvs", "harmony",
              "harmonies", "harm", "choir", "stack", "stacks", "double",
              "doubles", "dbl"}
FX_TOKENS = {"fx", "reverb", "verb", "delay", "throw", "throws", "echo"}

KIT_TOKENS = {"snare", "snares", "sn", "snr", "clap", "claps", "hat", "hats",
              "hh", "hihat", "hihats", "openhat", "closedhat", "tom", "toms",
              "rim", "crash", "ride", "cymbal", "cymbals", "cymb", "kit"}
PERC_TOKENS = {"perc", "percs", "percussion", "shaker", "shakers", "tamb",
               "tambourine", "conga", "congas", "bongo", "bongos", "cabasa",
               "clave", "claves", "cowbell", "woodblock", "timbale", "timbales",
               "guiro", "agogo", "triangle", "djembe", "tabla", "block"}

# Ordered so the first matching family wins for a given stem.
MUSIC_FAMILIES = [
    ("Keys", {"piano", "pianos", "keys", "key", "rhodes", "wurlitzer", "wurli",
              "organ", "clav", "clavinet", "epiano"}),
    ("Synth", {"synth", "synths", "pad", "pads", "arp", "arps", "pluck",
               "plucks", "saw", "stab", "stabs", "sine", "supersaw", "poly",
               "lead", "leads"}),
    ("Guitar", {"guitar", "guitars", "gtr", "gtrs"}),
    ("Strings", {"string", "strings", "violin", "cello", "viola", "orchestra"}),
    ("Brass", {"brass", "horn", "horns", "trumpet", "sax", "trombone", "tuba"}),
    ("Bells", {"bell", "bells", "chime", "chimes", "marimba", "mallet", "glock",
               "glockenspiel", "vibes", "vibraphone", "kalimba", "celesta"}),
]


def _words(stem):
    """Lowercased word tokens of a stem's ORIGINAL filename (camel/punct split)."""
    name = stem["file_path"].stem
    name = re.sub(r"_\d+$", "", name)                      # drop export counter
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", name)
    name = re.sub(r"[^A-Za-z0-9]+", " ", name)
    return [w.lower() for w in name.split() if w]


def _toks(stem):
    return set(_words(stem))


def _is_fx(stem):
    return bool(_toks(stem) & FX_TOKENS)


def _vrole(stem):
    t = _toks(stem)
    has_lead = bool(t & LEAD_TOKENS)
    has_bgv = bool(t & BGV_TOKENS)
    if has_bgv and not has_lead:
        return "bgv"
    if has_lead:
        return "lead"
    return None


def _role_rank(stem):
    """Lead, Lead-FX, BGV, BGV-FX, other — so each role's FX follows it."""
    role = _vrole(stem)
    fx = _is_fx(stem)
    if role == "lead":
        return 1 if fx else 0
    if role == "bgv":
        return 3 if fx else 2
    return 4


def _order_by_role(members):
    # sorted() is stable, so equal ranks keep their original order.
    return sorted(members, key=_role_rank)


def _cluster_vocals(stems):
    word_lists = [_words(s) for s in stems]
    tok_sets = [set(wl) for wl in word_lists]
    common = set.intersection(*tok_sets) if len(tok_sets) >= 2 else set()

    def is_name_tok(w):
        return (w.isalpha() and len(w) > 1
                and w not in VOCAL_NONNAME and w not in common)

    # A singer name appears in 2+ stems (and isn't common to ALL of them, which
    # would make it a title/artist token rather than a singer).
    freq = {}
    for wl in word_lists:
        for w in {t for t in wl if is_name_tok(t)}:
            freq[w] = freq.get(w, 0) + 1
    singers = {w for w, c in freq.items() if c >= 2}

    assign = []
    order = []
    for wl in word_lists:
        sg = next((w for w in wl if w in singers), None)
        assign.append(sg)
        if sg and sg not in order:
            order.append(sg)

    counts = {}
    for sg in assign:
        if sg:
            counts[sg] = counts.get(sg, 0) + 1
    kept = [sg for sg in order if counts.get(sg, 0) >= 2]

    if len(kept) >= 2:
        subgroups = []
        for sg in kept:
            members = [stems[i] for i in range(len(stems)) if assign[i] == sg]
            subgroups.append((sg.title(), _order_by_role(members)))
        loose = [stems[i] for i in range(len(stems)) if assign[i] not in kept]
        return subgroups, loose

    # One / no singer -> group by role directly.
    leads = _order_by_role([s for s in stems if _vrole(s) == "lead"])
    bgvs = _order_by_role([s for s in stems if _vrole(s) == "bgv"])
    others = [s for s in stems if _vrole(s) is None]
    return [("Lead", leads), ("BGV", bgvs)], others


def _cluster_drums(stems):
    kit, perc, loose = [], [], []
    for s in stems:
        t = _toks(s)
        if t & PERC_TOKENS:
            perc.append(s)
        elif t & KIT_TOKENS:
            kit.append(s)
        else:
            loose.append(s)
    return [("Kit", kit), ("Percussion", perc)], loose


def _cluster_music(stems):
    fam_members = {}
    order = []
    loose = []
    for s in stems:
        t = _toks(s)
        fam = next((name for name, toks in MUSIC_FAMILIES if t & toks), None)
        if fam:
            if fam not in fam_members:
                fam_members[fam] = []
                order.append(fam)
            fam_members[fam].append(s)
        else:
            loose.append(s)
    return [(f, fam_members[f]) for f in order], loose


def _emit(subgroups, loose, category, color):
    out = []
    for name, members in subgroups:
        key = category + "::" + name
        for s in members:
            s["subgroup_key"] = key
            s["subgroup_name"] = name
            s["subgroup_color"] = color
            s["subgroup_muted"] = False
            s["subgroup_unfolded"] = True
        out.extend(members)
    out.extend(loose)
    return out


def cluster_subgroups(stems, category, color=None):
    """Return `stems` reordered + subgroup-tagged, or None for no sub-grouping.

    `stems` are one category's working stems (already a flat group). `color`
    defaults to the parent group's colour so sub-group headers read as family.
    """
    if len(stems) < 3:
        return None     # too few stems to be worth nesting
    if color is None:
        color = stems[0].get("group_color", stems[0].get("color"))

    if category == "vocals":
        res = _cluster_vocals(stems)
    elif category == "drums":
        res = _cluster_drums(stems)
    elif category == "music":
        res = _cluster_music(stems)
    else:
        return None
    if not res:
        return None

    subgroups, loose = res
    loose = list(loose)
    kept = []
    for name, members in subgroups:
        if len(members) >= 2:
            kept.append((name, members))
        else:
            loose.extend(members)   # a 1-member sub-group stays loose, not dropped
    subgroups = kept
    if not subgroups:
        return None
    # A single sub-group that swallows every stem just duplicates the parent.
    if len(subgroups) == 1 and not loose:
        return None
    return _emit(subgroups, loose, category, color)
