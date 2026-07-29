# Snag List — Ableton Project Setup (Studio App)

Running list of issues found in real-world use of the shipped EXE. Deliberately
**batched** — we collect snags here and fold them into a single update rather than
cutting a release per bug. Newest first.

**Status key:** 🔴 open · 🟡 investigating · 🟢 fixed (note the release, e.g. `fixed v0.1.1`)

Baseline in the wild: **v0.1.0** (first distribution, 2026-07-14).

---

## SNAG-002 — Working tracks incorrectly routed to External Out
- **Status:** 🟢 fixed (2026-07-29, not yet released — pending next EXE build)
- **Root cause (confirmed via the two real affected projects' actual filenames, three
  independent contributors, all fixed):**
  1. `REFERENCE_PATTERNS`' "2MIX" regex matched ANYWHERE in a filename, not just as the
     terminal token — so every stem in a pack sharing a `..._2MIX_loop1` / `..._2MIX_GTRS`
     style export-set prefix got swept into "reference" (muted, Ext. Out), even though 2MIX
     was just the producer's shared export tag, not a real full-mix bounce. Fixed: the
     pattern now only matches "2MIX" as the last token, optionally followed by an explicit
     ref/reference/bounce/master qualifier.
  2. The numpy full-mix "audio safety net" was also being run on stems the FILENAME had
     already confidently classified as `music` (not just genuinely unclassified ones) — a
     loud/dense synth or guitar can share full-mix acoustic features and got second-guessed
     into a reference purely on audio content. Fixed: the safety net now only considers
     genuinely unclassified stems.
  3. Defense in depth: every non-reference/non-bus working track is now EXPLICITLY routed to
     Main (`als_patcher.set_track_output_main`) rather than trusting whatever routing the
     reused template slot happened to already have.
- **Validator hardened:** `validate_project.py` now hard-fails if any non-reference/
  non-refcompare working track is routed to Ext. Out.
- **Tests:** `Tests/test_external_routing.py` (new — reproduces the exact real-project
  filenames, incl. a poisoned-template-slot adversarial test proving fix #3 actively
  corrects stale routing, not just happens to work) + `Tests/test_validate_project.py` +
  `Tests/test_classifier_ground_truth.py` (both extended). Full suite 28/28.
- **Investigated + fixed by Codex** (`/peer-comms-headless`, high effort, workspace-write),
  reviewed + independently re-verified by Claude before commit.
- **Found:** 2026-07-17 — occurred across two real projects in studio use (Sam).
- **Severity:** High. The project appears normal during setup, but affected tracks bypass
  the Main/Master channel and are silently missing from the final exported master.
- **Setup:** Two separate projects built by the shipped Studio App. One project had one
  affected track; another had five affected tracks.
- **Symptom:** Some normal working tracks are unexpectedly routed to **External Out**
  instead of their group or the Main channel. This is difficult to spot before export:
  the problem may only become apparent after bouncing, when those tracks are absent from
  the final master.
- **Expected:** Only dedicated reference/A/B tracks should use External Out. Every working
  stem must route through its assigned group or directly through Main.
- **Hypothesis (unconfirmed):** A cloned/template track may sometimes retain the routing
  intended for a reference track, or some working stems may be incorrectly processed as
  references during track creation.
- **Info to gather before fixing:**
  - The two affected project folders and names of the incorrectly routed tracks.
  - Whether the affected tracks share a category, group, source folder, or naming pattern.
  - Whether they are ordinary working stems, updated stems, or version-shared tracks.
- **Likely fix location:** routing assignment in `Source/als_patcher.py`, especially
  `set_track_output_external` and inserted-track routing. Add validation in
  `Source/validate_project.py` that fails when any non-reference working track is routed
  to `AudioOut/External`.

---

## SNAG-001 — Extended mix clip lands slightly off-grid
- **Status:** 🔴 open
- **Found:** 2026-07-14 — first real distribution, in-studio (Sam).
- **Severity:** Low. Not a roadblock — the clip is a hair off the bar line and can be
  nudged by hand. BPM itself is correct.
- **Setup:** A project with two versions — **Extended Mix** + **Radio Edit**.
- **Symptom:**
  - BPM detected correctly. ✓
  - **Radio Edit** placed **on grid**. ✓
  - **Extended Mix** placed **shifted slightly off grid**. ✗
- **Hypothesis (unconfirmed):** the two versions are laid out independently, and the
  Extended version's clip start is anchoring to its first detected audio onset rather
  than snapping to the bar — or a per-version start-offset rounding differs. Radio edits
  usually hit the downbeat cleanly; extended mixes often have a longer/quieter intro
  whose first onset sits just off the bar, which would show as this exact drift.
- **Info to gather before fixing:**
  - How far off (ms / ticks) and which direction (early or late)?
  - The actual project folder (or the two stem sets) to reproduce.
  - Are the clips warped or placed at a fixed BPM? Does one Global-start nudge fix both?
  - Does it happen on every Extended+Radio pair, or just this one track?
- **Likely fix location:** version placement in `Source/project_builder.py`; region start
  detection in `Source/als_patcher.py` (`find_audio_regions`).

---

<!-- Add new snags above this line. Template:

## SNAG-00N — one-line title
- **Status:** 🔴 open
- **Found:** YYYY-MM-DD — where/how.
- **Severity:** Low / Medium / High (roadblock?).
- **Setup:** what kind of project/stems.
- **Symptom:** what happened vs. expected.
- **Hypothesis:** best guess at cause.
- **Info to gather before fixing:** what we need to repro.
- **Likely fix location:** file(s)/function(s).
-->
