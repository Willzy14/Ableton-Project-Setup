"""Regression tests for the canonical ALS/project validator."""
import gzip
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Source"))

from validate_project import validate_path  # noqa: E402


def _track(name, color, speaker, output_target, audio_file=None):
    file_ref = ""
    if audio_file:
        file_ref = f"""
                <SampleRef>
                    <FileRef>
                        <RelativePath Value="Audio/{audio_file}" />
                        <Path Value="" />
                    </FileRef>
                </SampleRef>"""
    return f"""
            <AudioTrack Id="{abs(hash(name)) % 10000}">
                <Name><EffectiveName Value="{name}" /></Name>
                <Color Value="{color}" />
                <ArrangementClips>
                    <AudioClip Id="{abs(hash(name)) % 10000 + 1}">
                        {file_ref}
                    </AudioClip>
                </ArrangementClips>
                <DeviceChain>
                    <Mixer>
                        <Speaker><Manual Value="{speaker}" /></Speaker>
                        <AudioOutputRouting>
                            <Target Value="{output_target}" />
                            <UpperDisplayString Value="{output_target}" />
                        </AudioOutputRouting>
                    </Mixer>
                </DeviceChain>
            </AudioTrack>"""


def _write_project(project_dir, flat_ref_exists=True, automation_tempo="160",
                   working_output="AudioOut/Main", include_refcompare=False):
    audio_dir = project_dir / "Audio"
    audio_dir.mkdir()
    (audio_dir / "kick.wav").write_bytes(b"fake")
    if include_refcompare:
        (audio_dir / "reference.wav").write_bytes(b"fake")
    if flat_ref_exists:
        (audio_dir / "Flat Ref.wav").write_bytes(b"fake")

    refcompare = (
        _track("References", 26, "true", "AudioOut/External/S0", "reference.wav")
        if include_refcompare else ""
    )
    als_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Ableton>
    <LiveSet>
        <Tracks>
            {_track("Session Time", 27, "true", "AudioOut/Main")}
            {_track("Kick 01", 4, "true", working_output, "kick.wav")}
            {refcompare}
            {_track("FLAT REF", 14, "false", "AudioOut/External/S0", "Flat Ref.wav")}
        </Tracks>
        <MainTrack>
            <Name><EffectiveName Value="Main" /></Name>
            <AutomationEnvelopes>
                <Envelopes>
                    <AutomationEnvelope Id="0">
                        <EnvelopeTarget><PointeeId Value="8" /></EnvelopeTarget>
                        <Automation>
                            <Events>
                                <FloatEvent Id="0" Time="-63072000" Value="{automation_tempo}" />
                            </Events>
                        </Automation>
                    </AutomationEnvelope>
                </Envelopes>
            </AutomationEnvelopes>
            <DeviceChain>
                <Mixer>
                    <Tempo>
                        <Manual Value="160" />
                        <AutomationTarget Id="8" />
                    </Tempo>
                </Mixer>
            </DeviceChain>
        </MainTrack>
    </LiveSet>
</Ableton>"""
    als_path = project_dir / "Example.als"
    with gzip.open(als_path, "wb") as handle:
        handle.write(als_xml.encode("utf-8"))
    return als_path


def test_valid_project_folder_passes_reference_and_tempo_checks():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _write_project(project_dir)

        result = validate_path(project_dir, expected_tempo=160)

        assert result.ok, result.errors
        assert result.tempo == 160
        assert result.track_count == 3
        assert result.flat_ref_track is not None


def test_missing_referenced_audio_fails():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _write_project(project_dir, flat_ref_exists=False)

        result = validate_path(project_dir, expected_tempo=160)

        assert not result.ok
        assert any("missing audio file" in error for error in result.errors)


def test_stale_tempo_automation_fails_even_when_manual_tempo_matches():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _write_project(project_dir, automation_tempo="104")

        result = validate_path(project_dir, expected_tempo=160)

        assert not result.ok
        assert any("tempo automation mismatch" in error for error in result.errors)


def test_working_track_routed_external_fails():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _write_project(project_dir, working_output="AudioOut/External/S0")

        result = validate_path(project_dir, expected_tempo=160)

        assert not result.ok
        assert any(
            "working track is incorrectly routed to Ext. Out: Kick 01" in error
            for error in result.errors
        ), result.errors


def test_refcompare_track_is_allowed_on_external():
    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        _write_project(project_dir, include_refcompare=True)

        result = validate_path(project_dir, expected_tempo=160)

        assert result.ok, result.errors


if __name__ == "__main__":
    test_valid_project_folder_passes_reference_and_tempo_checks()
    test_missing_referenced_audio_fails()
    test_stale_tempo_automation_fails_even_when_manual_tempo_matches()
    test_working_track_routed_external_fails()
    test_refcompare_track_is_allowed_on_external()
    print("project validator tests passed")
