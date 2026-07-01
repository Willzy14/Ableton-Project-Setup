# Multi-DAW Export — Future Direction

*Captured 2026-07-01. No work planned yet — this is the architectural read for when we want the tool to output Logic Pro / Pro Tools sessions alongside Ableton, via a DAW selector.*

## The core principle
**The engine is the moat; each DAW is a swappable exporter.** Everything smart in this tool is already DAW-agnostic — classification, BPM detection, grouping/sub-groups, wet-dry, group-bus detection, updated-stem A/B, ref detection, the energetic-part finder, and the abstract layout plan (which track, what colour, what position, which markers/keys). Only one module — `Source/als_patcher.py` — actually writes Ableton.

So adding a DAW = writing a **new output backend** that consumes the same layout plan. The selector/switch in the UI is trivial (an afternoon). The work is each backend.

## Why Ableton was the easy one
Ableton's `.als` is **gzipped XML** — readable, patchable, forgiving. It's the most hackable native project format in the industry, which is the whole reason this tool exists as a file-patcher.

- **Logic** (`.logicx`) — proprietary **binary** bundle. Undocumented, version-fragile. Cannot be written directly.
- **Pro Tools** (`.ptx`) — proprietary **binary**. Cannot be written directly.

Neither can be "patched." The realistic universal path is an interchange format both import: **AAF** (Advanced Authoring Format). One AAF backend serves Logic *and* Pro Tools (and Premiere/Resolve/Nuendo etc.). Write it with something like `pyaaf2`.

## Fidelity via AAF (the ~60–80% version)
| Feature | Ableton (now) | Logic / PT via AAF |
| --- | --- | --- |
| Tracks + audio at exact positions | ✅ | ✅ (AAF's core purpose) |
| No-warp / correct-BPM placement | ✅ | ✅ |
| Track colours | ✅ | ⚠️ patchy |
| Groups / nested sub-groups | ✅ | ⚠️ folders don't always survive |
| External-out ref routing | ✅ | ❌ not carried |
| Numbered "jump to drop" markers | ✅ (key-mapped) | mixed — but see PT below |

## Per-DAW notes
- **Pro Tools fits the jump-to-ref idea *better* than Ableton.** PT "Memory Locations" are natively recalled by typing their number on the keypad — so the "hit 1/2/3 → ref drop" workflow is a native PT concept, not a hack. PT may be the nicest target for that feature.
- **Pro Tools has a real scripting SDK** (PTSL — a gRPC API) that can build tracks, import audio, and create memory locations directly in a *running* PT. Higher fidelity than AAF, at the cost of needing PT open. A candidate **premium PT backend** later.
- **Logic** has no comparable project-building API; AAF import is the realistic route, accepting the reduced feature set.

## Effort verdict
- Selector + wiring the engine to pick a backend: **an afternoon.**
- A working AAF backend (tracks + audio + basic markers) covering Logic *and* PT: **a real sub-project** (~a couple of focused weeks of AAF trial-and-error) for the 80% version.
- Full parity (colours, groups, routing, key-markers matching Ableton): **hard-to-impossible** on the closed formats — non-Ableton DAWs get a deliberately reduced feature set.

## Strategic value
Logic (producers) and Pro Tools (pro studios) are massive markets — multi-DAW is a strong selling point for the productisation play (samwillsmixing → Wired Masters → labels). Architecture is already right for it: **additive, not a rewrite.** Ableton stays the flagship exporter; AAF is the "everything else" exporter; a PT-SDK exporter is a premium add-on.
