# M1 refactor plan — unify the single/multi-version build paths

Status: **CLEARED to start (with changes).** Three-brain review complete:
- **Codex** (high effort, code-grounded): direction right; narrow the head; split the tail; wet/dry must be
  per-version not union; +updated-stems parity gap; validate structurally into a fresh folder.
- **MiniMax** (code-grounded): **GO-WITH-CHANGES**. Caught a real bug in the first dry rule (see §Parity-b),
  gave the two-track fix, +~10 more parity gaps to verify, and the full harness invariant list.
- **Claude**: concur; full independent diff-map confirms the shared-track collision risk.

Do this as its own focused effort — it touches core build orchestration. Each stage its own bisectable commit.

## Direction
Extract the shared **HEAD** and **TAIL** into helpers. Keep the two middle *logics* separate (single = one
timeline; multi = versions stacked on shared element-tracks), but make **both middles emit the same `pv`
data shape** so the tail is genuinely shared — single-version is just `pv = [one_version_dict]`. Do NOT
merge the middle logic (a full pv-unification would drag Fallon's alignment into simple builds).

## HEAD — `_make_project_context(...)`
Produces (and is the SINGLE source of): `project_name` (`_safe_filename`), `project_folder`, `audio_folder`,
subfolders, `preseeded`, `source_names`, `refcompare_files`/`updated_files` (WAV-normalised), `category_colors`,
`subgroup_categories`. **NOT** normalise-to-WAV of the stems or BPM (multi does those per-version) — keeping
those out is what makes it a pure extraction.

## TAIL — `_patch_and_validate(...)` + `_finish_project(...)` (two helpers, not one mega-helper)
Common tail: `patch_project` → `_validate_als_flags` → write report → `apply_ableton_folder_icon` → rmtree
staging. **Report ASSEMBLY stays per-path** (schemas differ). Both paths first build a `pv` list whose dicts
share fields: `mix, refs, buses, bounce_path, bounce_rel, length_beats, first_beat_sec, dry_parks, silents,
skipped`. Single sets `length_beats`/`first_beat_sec` too (so the shape matches).

## Parity gaps

**(a) Silent-stem parking — per version, park-if-ALL-silent.** ✓ rule confirmed by MiniMax. Multi region
detection must pass `return_peak=True` (it doesn't — single does). A version that's silent for an element just
contributes no clip at its offset; park the element as a silent track ONLY if it's silent in EVERY version.

**(b) Wet/dry parking — NOT YET DONE. Complication found (2026-07-08):** `element_key` COLLIDES on
wet/dry tokens — `Lead_Vox_DRY` and `BGV_Vox_DRY` both key to `'dry'` (rsplit last segment), and both
`_WET` → `'wet'`. So dry-park pairing across versions can't use `element_key` as-is (two different dry
vocals would land on one track). Do it with a DEDICATED wet/dry-stripped key (additive, like
`sorted_element_key`), find_dry_stems PER VERSION (not union — avoids the false-pair below), and
SEPARATE the dry stems out of `p["mix"]` before the per-version bounce (model on how buses are already
separated/parked/excluded-from-sum). This is the hardest remaining stage — give it fresh focus.

**TWO-TRACK-PER-ELEMENT (my "all-dry" rule was WRONG).** ⚠ A union or "park only if dry
in every version" silently DROPS a mixed dry clip (`v0=wet, v1=dry` → v1's dry lands nowhere). Correct design
(MiniMax): for each element, a `working` track AND an independent `dry_park` track, never sharing clips. Per
version, classify each stem `{silent, active, dry}` and route its clip:
- `silent` → add nothing; `active`(wet) → `working[E].extra_clips` at `offsets[k]`; `dry` → `dry_park[E].extra_clips` at `offsets[k]`.
- Build `dry_park[E]` iff **≥1** version is dry. Base = the FIRST dry version's clip; `base_start_beat = offsets[k_first_dry]`. `muted=True`, parked colour, grouped in "Dry".
- The `extra_only` path (elements only in later versions) must ALSO honour silent/active/dry — a v_k-only dry goes to a dry_park, not a working track.
- Order in `all_stems`: working → refs → buses → preseeded → refcompare → **dry_parks** → updated.
- This is a strict superset of single behaviour (wet-only→working only; dry-only→dry_park only; both→both).

**(c) Updated stems — key by `(version_index, element_key)`, matched to the working track.** Multi currently
appends every updated file as a muted `music` track at the bottom AND mislabels them to `_collect_flags` as
unmatched. Fix: build one parked track per unique `(version, element)`, matched to its working track's group,
same as single.

**Verify-parity (may already be fine — confirm, fix only if divergent):** FLAT-REF auto-bounce for stems-only
packs; `length_beats` set in both; preseeded dedup conditions identical; `v_skipped` surfaced in both (single
now does); subgroup default scope (shared `SUBGROUP_CATEGORIES`); FX `head_sec=2.0` in both; locator list
construction. The silent/dry/updated DETECTORS are already shared module fns (`find_dry_stems`,
`SILENCE_FLOOR_DB`, `_match_key`) — the gap is multi not *calling* them, not defining them twice.

## Validation harness (before/after)
- **Pure-extraction stages (HEAD/TAIL): decompressed-XML equality.** `gunzip(before.als)` XML text ==
  `gunzip(after.als)` XML (decompress first — gzip mtime differs) + report deep-equal + icon byte-equal +
  Audio tree equal. Rebuild into a **FRESH** folder (rebuilding into an existing folder changes preseeded
  behaviour). Fixtures: **Admonic - Sunbeam** (single) + **Fallon - No Panties** (multi).
- **Parity stages: targeted structural tests** per fixture — track list, per-track (name/clip_name/category/
  color/base_start_beat/muted/updated), `extra_clips` (file_path/start_beat/clip_name), locators, dry_park +
  silent tracks present with the right clips/base per §(a)/(b).
- **Nondeterminism check:** build the same input 3× → decompressed-XML identical (catches dict/set ordering).
- New synthetic fixtures: multi 3-version mixed wet/dry; multi silent-in-v1; multi with updated stem; multi
  v0-missing-element (exercises the `extra_only` dry rule).

## Execution order (each a commit, gated by the harness)
0. **Harness** (offload to MiniMax → Claude review) — build/decompress/compare + fixtures. No engine change.
1. **HEAD extract** `_make_project_context`, both paths call it. Prove: decompressed-XML equal on both fixtures.
2. **Common `pv` shape + TAIL extract** (`_patch_and_validate`/`_finish_project`). Prove: XML equal on both.
3. **Parity (a) silent** — per-version + `return_peak=True`. New tests.
4. **Parity (b) dry two-track.** New tests (the mixed-wet/dry fixture is the key one).
5. **Parity (c) updated-stem keying.** New tests.
6. Verify the §Verify-parity items; fix any real divergence.

## What NOT to touch
The MIDDLE alignment — clip offsets, phrase-slot placement, kick-grid nudge (Fallon). Head/tail + the named
parity gaps only.
