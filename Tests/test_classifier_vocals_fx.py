"""Vocal hooks and transition FX classify correctly (Cole Horton project).

Hook-family stems (Hook Main / Hook BG / Hook Low / Hook Response / Hook V2)
are vocals, not synths; transition FX (Downer, Sub Drop, Riser) belong in FX,
not music/bass — but a named instrument ("Synth Hook") or a real "Sub Bass"
must still win.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

from stem_classifier import classify_stem, generate_track_name


def _cat(fname):
    cat, is_ref = classify_stem(fname)
    return "reference" if is_ref else cat


# --- the Cole Horton vocals: all should be vocals ---------------------------

def test_hook_family_is_vocals():
    for name in ("Hook Main.wav", "Hook BG 1.wav", "Hook BG 2.wav",
                 "Hook BG 3.wav", "Hook Low 1.wav", "Hook Low 2.wav",
                 "Hook Response 1.wav", "Hook Response 2.wav",
                 "Hook V2.wav", "Hook V3.wav"):
        assert _cat(name) == "vocals", name + " -> " + str(_cat(name))


def test_topline_is_vocals_but_guarded():
    assert _cat("Topline.wav") == "vocals"
    assert _cat("Top Line 2.wav") == "vocals"
    # a named instrument overrides the weak topline signal
    assert _cat("Guitar Topline.wav") == "music"
    assert _cat("Synth Topline.wav") == "music"


# --- transition FX: Downer / Sub Drop / Riser -> fx -------------------------

def test_downer_and_subdrop_and_riser_are_fx():
    for name in ("Downer 1.wav", "Downer 2.wav", "Downer 3.wav",
                 "Sub Drop.wav", "SubDrop.wav", "Sub_Drop.wav",
                 "Riser.wav", "Synth Riser.wav", "Uplifter.wav", "Whoosh.wav"):
        assert _cat(name) == "fx", name + " -> " + str(_cat(name))


# --- guards: named instruments and real sub bass must still win -------------

def test_instrument_named_hook_stays_music():
    assert _cat("Synth Hook.wav") == "music"
    assert _cat("Piano Hook.wav") == "music"
    # instruments the classifier now knows (sax/whistle/riff) also override hook
    assert _cat("Sax Hook.wav") == "music"
    assert _cat("Whistle Hook.wav") == "music"
    assert _cat("Riff Hook.wav") == "music"


def test_uplifting_adjective_is_not_fx():
    # "uplifting" is a mood adjective, not the "uplifter" transition FX
    assert _cat("Uplifting Lead.wav") == "music"
    assert _cat("Uplifting Chords.wav") == "music"
    # the actual transition FX still lands in fx
    assert _cat("Uplifter.wav") == "fx"
    assert _cat("Uplift.wav") == "fx"


def test_bass_hook_stays_bass():
    assert _cat("Bass Hook.wav") == "bass"


def test_real_sub_bass_is_still_bass():
    assert _cat("Sub Bass.wav") == "bass"
    assert _cat("Sub.wav") == "bass"


def test_existing_categories_unregressed():
    assert _cat("Kick.wav") == "kick"
    assert _cat("Reverb.wav") == "sends"
    assert _cat("Vocal Chops.wav") == "vocals"
    assert _cat("Chords.wav") == "music"
    assert _cat("Clap 2.wav") == "drums"


# --- clean display names ----------------------------------------------------

def test_display_names():
    assert generate_track_name("Hook Main", "vocals") == "Vox Hook Main"
    assert generate_track_name("Hook BG 1", "vocals") == "Vox Hook BG 1"
    assert generate_track_name("Hook Response 2", "vocals") == "Vox Hook Response 2"
    assert generate_track_name("Downer 1", "fx") == "FX Downer 1"
    assert generate_track_name("Sub Drop", "fx") == "FX Sub Drop"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print("PASS", fn.__name__)
        except Exception:  # noqa: BLE001
            failed += 1
            print("FAIL", fn.__name__)
            traceback.print_exc()
    print("ALL PASS" if not failed else str(failed) + " FAILED")
    sys.exit(1 if failed else 0)
