"""Wet/dry pairing: only park a DRY stem when a non-dry sibling exists."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

from stem_classifier import find_dry_stems, is_dry_stem, _element_base_key


def names(paths):
    return sorted(p for p in paths)


def test_explicit_wet_dry_pair_parks_the_dry_one():
    # The rule: one stem says WET, one says DRY, same element -> park the DRY.
    files = ["12_Lauren Lead Vocal (WET).wav", "13_Lauren Lead Vocal (DRY).wav"]
    assert names(find_dry_stems(files)) == ["13_Lauren Lead Vocal (DRY).wav"]


def test_dry_with_plain_sibling_not_parked():
    # DRY + plain (sibling does NOT say WET) is NOT a pair -> leave it alone.
    # (e.g. ARP DRY + ARP, which is also why the rule is vocals-only.)
    files = ["24_Re-Lig-Ion - ARP DRY.wav", "25_Re-Lig-Ion - ARP.wav"]
    assert find_dry_stems(files) == []


def test_orphan_dry_is_left_alone():
    # A dry stem with no sibling at all IS the working track — don't park it.
    files = ["01_Pad DRY.wav", "02_Bass.wav"]
    assert find_dry_stems(files) == []


def test_wet_label_without_dry_sibling_not_parked():
    # A (WET) stem with no dry counterpart stays as a normal working track.
    files = ["36_Lauren Lead Vocal1 (WET).wav", "37_Lauren Adlib1.wav"]
    assert find_dry_stems(files) == []


def test_index_difference_does_not_block_pairing():
    # Export indices differ but the element is the same -> still a pair.
    files = ["08_Vox (WET).wav", "21_Vox (DRY).wav"]
    assert names(find_dry_stems(files)) == ["21_Vox (DRY).wav"]


def test_wet_dry_base_keys_match_and_arp2_differs():
    assert _element_base_key("12_Vocal (WET).wav") \
        == _element_base_key("13_Vocal (DRY).wav")
    assert _element_base_key("23_Re-Lig-Ion - ARP 2.wav") \
        != _element_base_key("24_Re-Lig-Ion - ARP DRY.wav")


def test_is_dry_token_is_word_bounded():
    assert is_dry_stem("Synth DRY.wav")
    assert is_dry_stem("12_Vocal_dry.wav")
    assert not is_dry_stem("Dryer Synth.wav")     # 'dryer' is not the word 'dry'
    assert not is_dry_stem("Hydra Lead.wav")


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
