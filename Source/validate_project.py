"""Validate generated Ableton project outputs.

Usage:
    py -3.13 Source\validate_project.py "<project-folder-or-als>" --expect-tempo 160
"""
from __future__ import annotations

import argparse
import gzip
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TrackInfo:
    type: str
    name: str
    color: str | None
    speaker: str | None
    output_target: str | None
    has_clip: bool
    file_refs: list[Path] = field(default_factory=list)

    @property
    def is_reference(self) -> bool:
        return self.color == "14" and self.has_clip


@dataclass
class ValidationResult:
    input_path: Path
    als_path: Path | None = None
    project_dir: Path | None = None
    tempo: float | None = None
    tempo_automation: float | None = None
    track_count: int = 0
    audio_ref_count: int = 0
    flat_ref_track: TrackInfo | None = None
    reference_tracks: list[TrackInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _value(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    return element.attrib.get("Value")


def _id(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    return element.attrib.get("Id")


def _open_als(als_path: Path) -> ET.Element:
    with gzip.open(als_path, "rb") as handle:
        content = handle.read().decode("utf-8-sig")
    return ET.fromstring(content)


def _resolve_als_path(path: Path) -> tuple[Path | None, list[str]]:
    if path.is_file():
        if path.suffix.lower() != ".als":
            return None, [f"input file is not an .als: {path}"]
        return path, []

    if path.is_dir():
        als_files = sorted(path.glob("*.als"))
        if not als_files:
            return None, [f"no .als file found in project folder: {path}"]
        if len(als_files) > 1:
            names = ", ".join(p.name for p in als_files)
            return None, [f"multiple .als files found; pass one explicitly: {names}"]
        return als_files[0], []

    return None, [f"path does not exist: {path}"]


def _resolve_file_ref(project_dir: Path, file_ref: ET.Element) -> Path | None:
    absolute = _value(file_ref.find("./Path"))
    if absolute:
        absolute_path = Path(absolute)
        if absolute_path.exists():
            return absolute_path

    relative = _value(file_ref.find("./RelativePath"))
    if relative:
        return project_dir / Path(relative.replace("/", "\\"))

    if absolute:
        return Path(absolute)
    return None


def _track_name(track: ET.Element) -> str:
    return _value(track.find("./Name/EffectiveName")) or ""


def _parse_track(track: ET.Element, project_dir: Path) -> TrackInfo:
    file_refs = []
    for file_ref in track.findall(".//FileRef"):
        resolved = _resolve_file_ref(project_dir, file_ref)
        if resolved is not None:
            file_refs.append(resolved)

    return TrackInfo(
        type=track.tag,
        name=_track_name(track),
        color=_value(track.find("./Color")),
        speaker=_value(track.find(".//Speaker/Manual")),
        output_target=_value(track.find(".//AudioOutputRouting/Target")),
        has_clip=track.find(".//AudioClip") is not None,
        file_refs=file_refs,
    )


def _direct_tracks(root: ET.Element, project_dir: Path) -> list[TrackInfo]:
    tracks_node = root.find(".//LiveSet/Tracks")
    if tracks_node is None:
        return []
    return [
        _parse_track(track, project_dir)
        for track in list(tracks_node)
        if track.tag in {"AudioTrack", "GroupTrack"}
    ]


def _main_tempo(root: ET.Element) -> float | None:
    value = _value(root.find(".//MainTrack//Tempo/Manual"))
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _main_tempo_automation(root: ET.Element) -> float | None:
    main = root.find(".//MainTrack")
    if main is None:
        return None

    target_id = _id(main.find(".//Tempo/AutomationTarget"))
    if target_id is None:
        return None

    for envelope in main.findall(".//AutomationEnvelope"):
        pointee_id = _value(envelope.find("./EnvelopeTarget/PointeeId"))
        if pointee_id != target_id:
            continue
        event = envelope.find(".//FloatEvent")
        value = _value(event)
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None
    return None


def validate_path(path: str | Path, expected_tempo: float | None = None) -> ValidationResult:
    input_path = Path(path)
    als_path, path_errors = _resolve_als_path(input_path)
    result = ValidationResult(input_path=input_path, als_path=als_path)
    if path_errors:
        result.errors.extend(path_errors)
        return result

    assert als_path is not None
    result.project_dir = als_path.parent

    try:
        root = _open_als(als_path)
    except OSError as exc:
        result.errors.append(f"ALS gzip could not be decompressed: {exc}")
        return result
    except ET.ParseError as exc:
        result.errors.append(f"ALS XML could not be parsed: {exc}")
        return result

    result.tempo = _main_tempo(root)
    if result.tempo is None:
        result.errors.append("main tempo not found")
    elif expected_tempo is not None and abs(result.tempo - expected_tempo) > 0.01:
        result.errors.append(f"tempo mismatch: expected {expected_tempo:g}, found {result.tempo:g}")

    result.tempo_automation = _main_tempo_automation(root)
    if result.tempo is not None and result.tempo_automation is not None:
        if abs(result.tempo - result.tempo_automation) > 0.01:
            result.errors.append(
                "tempo automation mismatch: "
                f"manual {result.tempo:g}, automation {result.tempo_automation:g}"
            )
    if expected_tempo is not None and result.tempo_automation is not None:
        if abs(result.tempo_automation - expected_tempo) > 0.01:
            result.errors.append(
                "tempo automation mismatch: "
                f"expected {expected_tempo:g}, found {result.tempo_automation:g}"
            )

    tracks = _direct_tracks(root, result.project_dir)
    result.track_count = len(tracks)
    if not tracks:
        result.errors.append("no tracks found")
    elif tracks[0].name != "Session Time":
        result.errors.append(f"first track should be Session Time, found {tracks[0].name or '<blank>'}")

    result.reference_tracks = [track for track in tracks if track.is_reference]
    flat_refs = [track for track in tracks if track.name.upper() == "FLAT REF"]
    if not flat_refs:
        result.errors.append("FLAT REF track not found")
    else:
        result.flat_ref_track = flat_refs[0]
        if not result.flat_ref_track.has_clip:
            result.errors.append("FLAT REF has no audio clip")
        if not result.flat_ref_track.file_refs:
            result.errors.append("FLAT REF has no file reference")

    for track in result.reference_tracks:
        if track.speaker != "false":
            result.errors.append(f"reference track is not muted: {track.name}")
        if not (track.output_target or "").startswith("AudioOut/External"):
            result.errors.append(f"reference track is not routed to Ext. Out: {track.name}")

    for track in tracks:
        if track.has_clip and not track.file_refs:
            result.warnings.append(f"track has an audio clip but no file reference: {track.name}")
        for ref in track.file_refs:
            result.audio_ref_count += 1
            if not ref.exists():
                result.errors.append(f"missing audio file for {track.name}: {ref}")

    report_path = result.project_dir / "ML Classification Report.txt"
    if not report_path.exists():
        result.warnings.append("ML Classification Report.txt not found")

    return result


def _print_result(result: ValidationResult) -> None:
    print(f"Input: {result.input_path}")
    if result.als_path:
        print(f"ALS: {result.als_path}")
    if result.tempo is not None:
        print(f"Tempo: {result.tempo:g}")
    if result.tempo_automation is not None:
        print(f"Tempo automation: {result.tempo_automation:g}")
    print(f"Tracks: {result.track_count}")
    print(f"Audio file refs: {result.audio_ref_count}")
    print(f"Reference tracks: {len(result.reference_tracks)}")
    if result.flat_ref_track:
        print("FLAT REF: found")

    if result.errors:
        print("\nErrors:")
        for error in result.errors:
            print(f"- {error}")
    if result.warnings:
        print("\nWarnings:")
        for warning in result.warnings:
            print(f"- {warning}")

    print("\nResult: PASS" if result.ok else "\nResult: FAIL")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a generated Ableton project or ALS file.")
    parser.add_argument("path", help="Project folder or .als file")
    parser.add_argument("--expect-tempo", type=float, default=None, help="Expected project BPM")
    args = parser.parse_args(argv)

    result = validate_path(args.path, expected_tempo=args.expect_tempo)
    _print_result(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
