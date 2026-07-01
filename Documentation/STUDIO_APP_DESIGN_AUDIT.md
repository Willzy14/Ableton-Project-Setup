# Stem → Ableton — Design Audit

*Design director's cut. Grounded in the real HTML/CSS/JS + Python stack (verified against `Studio App/Web/app.js`, `styles.css`, `Source/stem_analysis.py`, `Studio App/engine_api.py`, `Source/project_builder.py`).*

---

## Where the app is

You've built a genuinely clever engine wearing a competent web form. Under the hood: filename + ML classification, kick-derived BPM with confidence, non-negative matching-pursuit group-bus detection, wet/dry pairing, singer-first nested sub-groups, a summed flat reference, multi-version handling. On screen: a glassy dark form with a static preview panel whose waveforms are **fake** — `waveBars()` in `app.js` seeds bars from an integer (`seed * 9301 + 49297`). Meanwhile `stem_analysis.py` computes a real 9-band spectrum at line 96 and **discards it one line before the return** (only `active_bands`, a count, survives). `build_project` returns a bare folder path and throws away every count, bus reason and peak it computed. `get_status` returns opaque `{state, message}` strings.

The gap between the intelligence computed and the intelligence shown is the entire opportunity.

---

## North-star vision — THE CONSOLE

Reframe the app as **one milled-anodised mastering unit rendered in software**, lit by a single raking light, engraved in IBM Plex Mono, with one teal indicator lamp — whose meters read **live off real audio analysis**.

- Dropped stems **seat** into labelled, colour-lit channel slots, each with a truthful 9-band spectral fingerprint and a one-line WHY.
- A pre-flight **QC lamp** goes green/amber/red on the real health of the pack.
- You commit the batch by throwing one weighted, detented **PROCESS fader** that lands with a sampled console *thunk*.
- On completion the faceplate freezes into an exportable, re-brandable **Session Card**.

Every flourish is backed by data the engine truly computes. Nothing is skeuomorphic kitsch. The compass for every decision: *does this make the displays more truthful and more tactile — and would a 6,000-credit engineer trust it and a label want it?*

---

## Signature bets — the three "wow" moves

1. **The Anodised Faceplate.** Retire the stack of floating glass cards; render the whole window as ONE brushed-anodised plate — chamfered edges, corner screws, recessed wells, engraved mono labels, one raking top-left light, a custom frameless titlebar with a serial-number version plate. Pure CSS/SVG, zero engine change. *This is the identity; everything hangs off it.*
2. **Truthful meters + spectra.** The fake sine-bars die. Real 9-band fingerprints, spring-ballistic VU needles, a visible beat-grid lock, driven by numbers the engine already has. *Converts the app's biggest weakness into its credibility hook.*
3. **The PROCESS throw + the QC lamp.** A weighted detented fader you throw to commit the batch, with a sampled console thunk and a lamp walking pending→running→done — paired with a green/amber/red QC verdict written into the folder. *Changes the pitch from "it made a session" to "it caught the flipped bass before you opened the file."*

---

## Roadmap

### QUICK WINS — cheap, high-taste, ship first
- **Auto-title from folder name** — pre-fill the title from the dropped folder, normalised; most cards flip build-ready with zero typing. *(impact 5 / wow 3 / S)*
- **Shared motion + reduced-motion + Motion toggle** — one easing token set replaces the ad-hoc `.15s/.08s/.7s` timings; `prefers-reduced-motion` block + an in-app toggle is the load-bearing silent-fast path for session #9. *(impact 5 / wow 2 / S)*
- **Engraved mono typography** — small labels become milled (1px light bottom-edge + dark top shadow); whisper-subtle only. *(impact 4 / wow 3 / S)*
- **Bespoke engraved icon set** — replace every emoji (☕ ⟳ ✕ +) with a tight ~8-glyph SVG set; the coffee-cup emoji on the primary action is an off-brand liability. *(impact 4 / wow 2 / M)*
- **Beat-grid lock** — `detect_bpm` already returns `period` + `first_beat_sec`; draw an animated grid that snaps to lock with a counting-up BPM readout. *(impact 4 / wow 4 / S)*
- **Crest/sustain texture on the spectrum** — `crest` and `active_frac` are already returned; map them to spiky-vs-smooth so a kick reads punchy and a pad reads glued, for zero new data. *(impact 4 / wow 3 / S)*
- **'What the engine caught' amber notes** — serialise the bus-parked / wet-dry / full-mix / low-confidence calls already made. *(impact 4 / wow 3 / S)*
- **Reveal / Retry / Open-in-Ableton + 'Undo' toast** — the worker already captures folder + traceback; surface it. Undo toast catches a fat-fingered ✕. *(impact 5 / wow 3 / M)*
- **Keyboard layer + Enter-to-build + real `:focus-visible`** — plain shortcuts only (no Ctrl+K palette — that's SaaS furniture). Fixes the wrong-pseudo-class focus bug too. *(impact 4 / wow 2 / M)*
- **Written Session Report.txt in the folder** — reuse the existing `_write_ml_report` pattern; the record Sam reads weeks later. *(impact 4 / wow 3 / S)*

### SIGNATURE MOVES — the identity
- **The Anodised Faceplate** — one milled surface, single raking light, physically-consistent shadows (no blur soup). *(impact 5 / wow 5 / L)*
- **Truthful 9-band spectra** — one-line change to RETURN `band_pow`, a thin `analyze_folder()` endpoint over the existing `analyze_stem`, Canvas fingerprints per slot. *(impact 5 / wow 4 / M–L)*
- **Category colour language as a first-class system** — elevate the 9px `--cat-*` dots into a jewel-LED chip component + a machined colour-key strip, driven by the active profile so it mirrors Ableton exactly. *(impact 4 / wow 3 / M)*
- **The Result Card** — build the per-project receipt (parsed artist/title/label, BPM+confidence, category tally, group tree, flat-ref peak+headroom) from data `build_project` currently prints and discards. *(impact 5 / wow 4 / M)*
- **Structured per-stem event stream** — refactor the opaque status strings into `staging → classified → meter-ready → bus-parked → done`; the keystone that makes every meter and lamp honest. *(impact 5 / wow 3 / M)*
- **Non-blocking ingest with a 'reading…' state** — move `prepare_stem_folder` (AIFF→WAV, ZIP) off the API thread; a frozen white window on a 40-stem pack is the moment the tool gets filed under "toy". *(impact 5 / wow 3 / M)*
- **High-DPI-correct, resize-aware Canvas** — `devicePixelRatio` backing store, ResizeObserver, 30fps cap, static faceplate layer. A blurry needle at 150% Windows scaling kills the $4k illusion. *(impact 4 / wow 2 / M)*
- **Live meter needles (spring ballistics)** + **bus-absorption micro-animation** — real VU settle, and member lanes visibly pulled into a parked bus as a QA explanation. *(impact 4 / wow 4–5 / M–L, gated on the event stream)*
- **The PROCESS throw** — weighted detented fader + sampled console thunk, behind the Motion toggle, with a fast press-and-hold fallback. *(impact 4 / wow 5 / L)*

### AMBITIOUS — showpieces
- **Pre-flight QC Verdict engine** — true-peak/LUFS on the flat-ref sum, kick-vs-sub phase/polarity, DC offset, dead/clipped exports, SR/bit-depth mismatch. The one net-new capability that changes the pitch. **This is genuinely new DSP — validate against golden known-bad packs + Sam's ear, never ship on vibes.** *(impact 5 / wow 5 / L, research)*
- **The Sonified Verdict** — hear the flipped bass un-flip in an A/B; strictly downstream of the QC engine, behind the Motion+Sound toggle. *(impact 7 / wow 8 / M, gated on QC)*
- **Scrub-to-Hear** — hover/drag a lane to audition the real stem via WebAudio; the truest expression of the console thesis for an audio pro. Decode lazily per-lane, never all 40 at once. *(impact 9 / wow 9 / M)*
- **Smart drop router** — throw five sibling pack folders at the app → one auto-titled card each. The most satisfying batch gesture. *(impact 4 / wow 4 / M)*
- **Live steerable queue** — reorder/pause/skip/add while a batch runs; reads as a real console transport. *(impact 4 / wow 4 / L)*
- **Re-Sync (revision handling)** — detect a revised delivery and offer a diff + report. **De-scope to detection+diff+report only** — never do in-place `.als` surgery on a session Sam has hand-mixed. *(impact 9 / wow 7 / split; diff-only is M–L)*
- **Learned House Style** — remember per-label overrides ("Defected = drums-forward") as a dismissible provenance chip. Frame v1 honestly as *remembered preferences*, not trained AI. *(impact 9 / wow 8 / L, sequence last)*

### PRODUCTIZATION — the samwillsmixing → Wired Masters → labels spine
- **brand.json one-file re-skin** — accent, lamp colour, engraving text, studio photo, letterhead, EXE name; `get_bootstrap()` already exists as the injection point. Ship 3 presets. *(impact 5 / wow 4 / M)*
- **Exportable Session Card (PNG)** — the re-brandable leave-behind; a spec sheet for a hardware unit, NOT a social-media flex card. *(impact 4–5 / wow 4–5 / M)*
- **Session Library** — SQLite/JSONL ledger of every build, label-filterable ("everything I built for Defected"); ties into outreach. "200 sessions prepped" is a concrete pitch asset. *(impact 5 / wow 3 / M)*
- **Recipes / Presets** — bundle profile + sub-groups + naming + output into a named recipe; a label's EXE ships pre-seeded with their recipe. *(impact 5 / wow 3 / S)*
- **The Accuracy Ledger** — "47/50 this pack, 94% lifetime". Honest track record; sequence AFTER review-chips log corrections, or the numbers are fabricated. *(impact 8 / wow 6 / S, dependency)*
- **Deep Dropbox integration** — read Sam's real taxonomy, wire the latest SW V3 / AMENDED render as reference, always COPY never move; closes a logged bug. Keep the folder map as config. *(impact 5 / wow 3 / M)*
- **Portable settings + crash capture** — kill hardcoded `C:\Users\Carillon\` paths (two-OS Dropbox user), write crash tracebacks + a local usage ledger for the time-saved pitch number. *(impact 4 / wow 2 / S–M)*

---

## What we deliberately cut — taste guardrails

- **The 12-second cinematic cold-open and per-build fold animations** (from THE ROOM). The motion-fatigue trap; clashes with the calm-instrument register. A working pro on session #9 does not want a movie.
- **The Ctrl+K command palette.** SaaS/Notion furniture. A unit has a hard commit action, not a verb-list.
- **The full undo/redo stack.** Over-engineering for a ~6-card pre-build queue — one "Removed — Undo" toast is enough.
- **Colour-blind notching on the colour chips.** Muddies the clean colour read; colour + label is enough.
- **In-place `.als` surgery on revised packs.** Dangerous once Sam has hand-mixed. Diff + report + optional new version project only.
- **"Trained/learning AI" language before it's real.** Frame memory as remembered preferences + honest tallies first. Under-claim, never over-claim — a confidently-wrong co-engineer erodes trust fastest.
- **Embossed / glowing-bevel skeuomorphism.** Engraved not embossed, matte not glossy, one lamp not RGB. Reference real mastering hardware, not plugin-GUI cliché.

---

## If you only do five things

1. **RETURN `band_pow` + `analyze_folder()` → kill the fake waveforms.** One line + one thin endpoint turns the biggest lie into the biggest credibility hook.
2. **Reskin to the Anodised Faceplate** (with the shared motion tokens + reduced-motion baked in). The identity, and the demo.
3. **Kill every alert() and raw traceback; add Reveal/Retry.** A raw Python error in front of a label ends the pitch.
4. **Build the Result Card + 'what the engine caught' + Session Card export** from data already computed. The payoff Sam reads and the leave-behind you sell.
5. **Wire brand.json.** One file makes a "Defected Edition" a 60-second job — the whole productisation play, made real.

*Do these five and the tool crosses the line from "built" to "bought" — and every one of them stands on data the engine already computes.*