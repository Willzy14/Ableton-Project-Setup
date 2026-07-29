"""Classifier patterns mined from Sam's finished projects (2.1. Finished Stem
Mixes). Each case is a real stem name whose clip colour told us the true
category; these were mis-classified before and are now fixed. The guards below
must NOT regress — they're the false-positives those additions could cause.

(Analysis tool: Scripts/audit_classifier_vs_projects.py — re-run to re-measure
agreement against the project corpus after any classifier change.)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))
from stem_classifier import classify_stem


def _cat(name):
    return classify_stem(name)[0]


def _is_ref(name):
    return classify_stem(name)[1]


# name -> expected category, drawn from real projects the classifier used to miss
GROUND_TRUTH = {
    # guitar / piano abbreviations (were falling through to a 2MIX "reference")
    "CA_KYRIE_2MIX_gtr.wav": "music",
    "CA_Rewind_2MIX_pno_01.wav": "music",
    "GTR Lead.wav": "music",
    "PNO Chord.wav": "music",
    # percussion the pattern list missed
    "CA_KYRIE_2MIX_cymbs.wav": "drums",   # cymbs (plural abbrev)
    "Cowbell.wav": "drums",
    "_ HAT2.wav": "drums",                # trailing digit must not break the match
    "Open Hat 3.wav": "drums",
    "08_Sd Roll.wav": "drums",            # sd = snare drum
    # fx
    "Ambiance.wav": "fx",                 # spelling of ambient
    "_ UPFILTER.wav": "fx",
    # vocals
    "Extra Voc.wav": "vocals",            # bare "voc"
    "Harmonies.wav": "vocals",
    "HARMONIES.wav": "vocals",
    # bass
    "big reese.wav": "bass",
    "B Line.wav": "bass",
    "Bline.wav": "bass",
    "HR Renegades Wobble.wav": "bass",
    # Sam's rulings: an instrument/vocal name beats a send-effect word, and a
    # "delay throw" is a thrown vocal.
    "Chorus Synth.wav": "music",
    "Post Chorus Synth.wav": "music",
    "Vox Lead Delay Throw.wav": "vocals",
    "Delay Throw.wav": "vocals",          # bare throw reads as vocals
    "Main Hook Delay Throws.wav": "vocals",
    # an FX fill is a transition FX, not a drum fill (Sam, HARTY project) — and it
    # must classify the same whichever way the producer orders the words.
    "FX_FILLS.wav": "fx",
    "FILLS_FX.wav": "fx",
    "FX Fills.wav": "fx",
    # SNAG-002 production failures: "2MIX" is the export-set prefix, not the
    # stem type. These working tracks were incorrectly made red/muted/Ext. Out.
    "WynStarks_COCO_DA_2MIX_loop1.wav": "drums",
    "WynStarks_COCO_DA_2MIX_loop2.wav": "drums",
    "LR_OneWayTicket_DA_2MIX_ohh.wav": "drums",
    "LR_OneWayTicket_DA_2MIX_GTRS.wav": "music",
    # A bare "chop" is a VOCAL chop, not instrumental — confirmed against
    # real-corpus evidence (Sam, 2026-07-29): every bare Chop/Chops with no
    # instrument name attached, across 147+ finished projects, was coloured
    # vocals (incl. a stem literally just named "CHOP"). Sam hit this exact stem
    # misclassified + parked at the bottom on this real project.
    "WynStarks_COCO_DA_2MIX_CHOP.wav": "vocals",
    "LR_OneWayTicket_DA_2MIX_CHOPS.wav": "vocals",
    "CHOP.wav": "vocals",
    "Guitar Chop.wav": "music",         # an explicit instrument name still wins
    "Synth Chop.wav": "music",
    "SMF-  24guitar chop.wav": "music",  # a digit glued to a word (no space) is
                                        # split so \bguitar still matches
}

# These must stay put — the additions above must not steal them.
GUARDS = {
    "Harmonic Synth.wav": "music",        # harmon(y) must not catch "harmonic"
    "byline note.wav": None,              # "b line" must not catch "byline"
    "Vocoder Lead.wav": "music",          # bare-voc must not catch "vocoder"
    "Guitar.wav": "music",
    "Sub Bass.wav": "bass",
    # sends is a fallback, but a BARE send stem must still classify as sends
    "Reverb.wav": "sends",
    "Delay.wav": "sends",
    "Chorus.wav": "sends",
    "Reverb Snare.wav": "drums",          # instrument beats the send word
    "Snare Throw.wav": "drums",           # throw-guard yields to a real instrument
    "Drum Fill.wav": "drums",             # a real drum fill stays drums (only FX fills -> fx)
    "Snare Fills.wav": "drums",
    "Tom Fill.wav": "drums",
}


def test_ground_truth_names_classify_correctly():
    wrong = {n: (_cat(n), exp) for n, exp in GROUND_TRUTH.items() if _cat(n) != exp}
    assert not wrong, "misclassified: " + str(wrong)


def test_new_patterns_do_not_regress_guards():
    wrong = {n: (_cat(n), exp) for n, exp in GUARDS.items() if _cat(n) != exp}
    assert not wrong, "guard broken: " + str(wrong)


def test_2mix_only_marks_terminal_reference_forms():
    cases = {
        "Artist_Title_2MIX.wav": True,
        "Artist_Title_2MIX_REF.wav": True,
        "Artist_Title_2MIX_reference.wav": True,
        "Artist_Title_2MIX_bounce.wav": True,
        "Artist_Title_2MIX_master.wav": True,
        "Artist_Title_2MIX_unknownstem.wav": False,
        "Artist_Title_2MIX_loop1.wav": False,
    }
    wrong = {n: (_is_ref(n), exp) for n, exp in cases.items() if _is_ref(n) != exp}
    assert not wrong, "2MIX reference boundary broken: " + str(wrong)


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
