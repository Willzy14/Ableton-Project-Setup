# Snag List — Ableton Project Setup (Studio App)

Running list of issues found in real-world use of the shipped EXE. Deliberately
**batched** — we collect snags here and fold them into a single update rather than
cutting a release per bug. Newest first.

**Status key:** 🔴 open · 🟡 investigating · 🟢 fixed (note the release, e.g. `fixed v0.1.1`)

Baseline in the wild: **v0.1.0** (first distribution, 2026-07-14).

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
