# Full App Audit — 2026-07-06

Three independent passes — **Claude** (orchestrator), **Codex** (high-effort), **MiniMax** (general) —
over the whole tool, deduped and **verified against the real code** where marked ✓. Goal: holes,
silent-failure risks, and upgrades before packaging. Constraints honoured: no XML-lib rewrite, ML
stays off-by-default, BPM detection frozen (CRNN hand-off pending).

Severity: **Blocker** (breaks/corrupts output) · **High** (wrong project or silent data loss) ·
**Med** (edge cases / maintainability) · **Low** (cosmetic / rare). Consensus = which brains flagged it.

---

## Blocker

**A1 · `.als` write is not crash/lock-safe — a Dropbox lock leaves a corrupt project.** ✓ verified
`compress_als` ([als_patcher.py:43](../Source/als_patcher.py)) is a bare `gzip.open(path,"wb")` — no
retry, no atomic write. `bounce.py` already retries 8× on `PermissionError` ([bounce.py:217](../Source/bounce.py)),
but the `.als` write doesn't. A mid-build Dropbox sync / AV scan aborts the gzip stream and leaves a
half-written `.als` that Ableton can't open, next to a valid `Audio/`. *(MiniMax B1.)*
**Fix:** write to `X.als.tmp` in the same folder, then `os.replace` (atomic on one volume); `unlink` the
target on failure. ~10 lines. Closes it entirely.

---

## High

**A2 · Skipped/unconvertible stems are silently dropped — not in the report or the "needs a look" flags.** ✓ verified
`_normalize_audio_to_wav` and `_ensure_wav_paths` return a skipped list, but the callers discard it
(`_sk` unused, [project_builder.py:1038-1039](../Source/project_builder.py)). A corrupt WAV / unsupported
AIFF in a named category vanishes from the `.als` AND from the flags. *(Codex #1.)*
**Fix:** thread the skipped names into `report["skipped"]` + `_collect_flags`, both build paths.

**A3 · ✅ DONE (2026-07-06) · Cross-version element pairing breaks on ~common naming.** ✓ verified (Claude + MiniMax)
`element_key` ([versions.py:62](../Source/versions.py)) takes only the segment *after the last underscore*:
`Kick_01` → key `"01"`, but `Kick` → `"kick"` — the same kick in two versions becomes two separate,
ungrouped tracks. *(MiniMax H1, Claude.)*
**Fix:** strip a trailing export index from both sides before keying; add pairing tests (`Kick_01`↔`Kick`,
`Drum_Top_Extended`↔`Drum_Top`).

**A4 · ⏳ DEFERRED (needs careful design) · Deep nesting is classified only one subfolder down.** (Codex #2 — verify)
> A naive "claimed vs found" recursive diff false-flags on every pack with refs / buses / version
> subfolders / dupes, so this needs a proper coverage model (correct exclude set + expected-placed
> count) — its own focused session, not a rushed change. Uncommon in Sam's real packs.
`classify_stems` + the Studio App multi-input path resolve one wrapper level; `Stems/Drums/WAV/Kick.wav`
can build without the deep stems and without a flag.
**Fix:** one canonical recursive manifest (`rglob` with `__MACOSX`/dotfile/special-dir excludes), then
diff "all source audio" vs "claimed" and flag the gap.

**A5 · ~~The project folder is set permanently read-only by the icon step.~~ RESOLVED — not a real issue (Sam, 2026-07-06):** he has never hit "access denied" dropping files into a built project folder. A Windows *folder* read-only attribute is a customisation signal (for `Desktop.ini`), not a write-block on the folder's contents. Left as-is. ✓ verified (code) — premise wrong.
[project_builder.py:923](../Source/project_builder.py) sets the folder READONLY. That blocks Sam's own
workflow — dropping a current master into the project's `Audio/` for A/B (the pre-seeded-ref feature)
returns "Access denied" in Explorer. *(MiniMax H6.)*
**Fix:** set the attribute on `Desktop.ini` only (enough for the icon), leave the folder writable; or an
`ABLETON_SET_FOLDER_ICON=0` opt-out.

**A6 · `_wav_staging` tempdir leaks one per build with non-WAV stems.** ✓ verified
`mkdtemp("als_wav_")` at [project_builder.py:1035](../Source/project_builder.py) is never `rmtree`'d
(the recent ML-leak fix was a different dir). AIFF/MP3/FLAC refs are common → steady temp growth.
*(MiniMax H3.)* **Fix:** `try/finally` cleanup; same for the multi-version `_wav_staging` at :1444.

**A7 · ✅ DONE (2026-07-06) · Zip ingest uses `extractall` (zip-slip) and can mis-read a single-`REF/` pack.** (Codex #3 + MiniMax H5)
`prepare_stem_folder` ([engine_api.py:265](../Studio%20App/engine_api.py)) extracts untrusted zip paths
directly; a pack whose audio lives only inside `REF/` gets diverted to A/B refs → build with 0 working tracks.
**Fix:** per-entry extract with a path-traversal guard; refuse/flag a pack whose only audio is under a special folder.

---

## Medium

**M1 · Single- vs multi-version paths duplicate ~150 lines → parity drift.** (MiniMax M1 + brief)
Bus-detect, dry-park (missing in multi!), preseeded-ref, refcompare, report, icon all coded twice
([project_builder.py](../Source/project_builder.py) ~1015-1420 vs ~1503-1818). A change to one silently
skips the other (has happened before). **Fix:** extract a shared `_finalize(pv, ...)`; single-version wraps
its set as a one-element `pv`.

**M2 · ✅ DONE (2026-07-06, lighter fix) · Session-report IO failure hides the whole result card.** (Codex #4 + MiniMax M5)
The report is written then re-read; a Dropbox lock on `Reports/Session Report.json` → the build validates
but the UI shows editable controls / no flags. **Fix:** `build_project` returns the report object; the
worker passes it even if file IO fails; UI shows an explicit "report missing" state.

**M3 · ✅ DONE (2026-07-08) · Full-mix / bus detection failures are swallowed → a full mix summed into the flat ref.** (Codex #5 + MiniMax M6)
If numpy is absent or analysis errors, an ambiguous full mix (e.g. `Current.wav`) stays in `music` and pollutes
the bounce. Bus detection also only sees the first 180 s (a bus silent at the head is missed — known). **Fix:**
flag "safety analysis unavailable for X"; consider parking failed-analysis ambiguities as muted refs; use the
loudest sustained window (not elapsed time) for bus pursuit.

**M4 · ✅ MOSTLY DONE via U1 (inline validate now flags a tempo mismatch) · `set_global_tempo` / `set_track_name` don't confirm the patch landed.** (MiniMax M2/M4)
Both depend on template line layout; a future Ableton/template change can silently no-op (wrong tempo, stale
`UserName`). **Fix:** assert the value changed post-patch and raise a flag if not; see U1.

**M5 · ✅ PARTLY DONE (2026-07-06) · `_read_wav_header` rejects RF64/WAVE64 (>4 GB) and trusts `data_size`.** (Codex #6 + MiniMax L2)
> Done: `data_size` is now capped at the real file bytes (a sentinel `0xFFFFFFFF` can't drive an OOM
> read). Still open: RF64/WAVE64 >4 GB support (a `soundfile` header fallback) — larger, deferred.
A large Pro Tools/Cubase export is skipped as "Not a WAV", or a sentinel `data_size` (0xFFFFFFFF) drives a
giant read → OOM. Region/bounce numpy paths also read the whole file into RAM. **Fix:** cap `data_size` at
file-size−offset; optional `soundfile` fallback for RF64; stream regions above a size threshold.

**M6 · ✅ DONE (2026-07-06) · Timeout misreported as a crash.** (Codex #8)
A build killed by the 30-min watchdog can surface as "the engine crashed". **Fix:** a `timed_out` flag set in
the timer, reported regardless of captured output.

**M7 · ✅ DONE (2026-07-06) · Self-updater trusts `latest.json` + download URL with no hash/signature.** (Codex #7)
Compromised hosting → a swapped EXE is downloaded and run. **Fix:** add `sha256` to the feed, verify before
swap; pin host/scheme.

---

## Low

- **L1 · `BUS_TRACK_COLOR = 2`** but docs/spec say grey **37** ✓ ([project_builder.py:65](../Source/project_builder.py)) — buses don't read as inactive. *(Codex #10.)*
- **L2 · Validator uses `replace("/","\\")`** ([validate_project.py:81](../Source/validate_project.py)) — false "missing audio" on Mac. *(Codex #9.)* Fix: `PurePosixPath(rel).parts`.
- **L3 · ✅ DONE (2026-07-06) · Zero-frame clip** from a header-only WAV renders as a phantom in Ableton. *(MiniMax M3.)* Fixed: the clip loop skips any region with `len ≤ 0`.
- **L4 · ✅ PARTLY DONE (2026-07-08 — safe half; claim-set left on resolve()) · `path.resolve()` in hot loops** can stall on a stale network share. *(MiniMax L1.)* Fix: `.absolute()`.
- **L5 · Pure-numeric stem names** ("01.wav") dedupe to "Vox/Vox 2" display names (clip name still correct — cosmetic). *(MiniMax L3.)*

---

## Upgrades (value vs effort)

- **U1 · ✅ DONE · Inline validate at the end of `patch_project`** (LOW effort, HIGH value) — a CLI build currently has
  no safety net; call `validate_path` and fold errors into flags. Catches every silent template-break (M4).
- **U2 · ✅ DONE · Atomic `.als` write** — the fix for A1; ~10 lines.
- **U3 · ✅ DONE · One `safe_filename()` helper** for user-typed labels becoming FS paths (a `<` in a label shouldn't blow up a build).
- **U4 · ✅ DONE (seam comment) · CRNN hand-off shim in `bpm_detector`** — a documented plug-in point so the Kick Detector drops in with one import + flag (no rewrite now).
- **U5 · Surface "N silent / N skipped" as a card badge** pre-open, not just a buried flag.
- **U6 · Test-gap fill** — `set_track_name` (both name fields), `element_key` pairing, `compress_als` under lock, zip-ingest edge packs, wav_staging leak.

---

## Recommended order

1. **Quick, high-value, low-risk batch (do first):** A1/U2 (atomic write), A6 (staging cleanup), A2 (surface skips),
   L1 (bus colour), L2 (Mac path), A5 (folder read-only), U1 (inline validate). Mostly small, each testable.
2. **Correctness batch:** A3 (element_key), A4 (deep nesting), M3 (full-mix flag), M5 (WAV robustness), L3 (zero-frame).
3. **Studio App batch:** A7 (zip safety), M2 (report-IO UI), M6 (timeout), M7 (updater hash).
4. **Refactor (before it drifts more):** M1 (unify build paths) — do near packaging, well-tested.

Each fix ships with a test (project convention). BPM/kick stays frozen until the CRNN lands (U4 just marks the seam).
