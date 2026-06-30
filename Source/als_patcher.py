"""Core ALS patcher — reads a template, assigns stems to tracks, writes the result.

All edits are line-level text operations. Never use XML parsing libraries.
Line endings are always \r\n.
"""
import gzip
import math
import re
import os
from pathlib import Path

try:
    import numpy as _np
except ImportError:  # pragma: no cover
    _np = None

CRLF = "\r\n"
_NEXT_ID = 50000


def _alloc_id():
    global _NEXT_ID
    _NEXT_ID += 1
    return _NEXT_ID


def _xml_escape(value):
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def decompress_als(als_path):
    with gzip.open(als_path, "rb") as f:
        content = f.read().decode("utf-8")
    return content.splitlines(keepends=True)


def compress_als(lines, output_path):
    content = "".join(lines)
    raw_bytes = content.encode("utf-8")
    with gzip.open(output_path, "wb") as f:
        f.write(raw_bytes)
    return output_path


def find_track_ranges(lines):
    """Find all AudioTrack and MainTrack line ranges.

    Returns list of dicts: {type, id, name, color, start, end}
    """
    tracks = []
    stack = []

    for i, line in enumerate(lines):
        for tt in ["AudioTrack", "MainTrack"]:
            if "<" + tt + " " in line or ("<" + tt + ">" in line and tt == "MainTrack"):
                tid = ""
                m = re.search(r'Id="(\d+)"', line)
                if m:
                    tid = m.group(1)
                stack.append({"type": tt, "start": i, "name": "", "color": "", "id": tid})
                break

        if stack:
            current = stack[-1]
            if "<EffectiveName" in line and not current["name"]:
                m = re.search(r'Value="([^"]*)"', line)
                if m:
                    current["name"] = m.group(1)
            if "<Color Value=" in line and not current["color"] and i < current["start"] + 30:
                m = re.search(r'Value="(\d+)"', line)
                if m:
                    current["color"] = m.group(1)

            for tt in ["AudioTrack", "MainTrack"]:
                if "</" + tt + ">" in line:
                    finished = stack.pop()
                    finished["end"] = i
                    tracks.append(finished)
                    break

    return tracks


def set_track_name(lines, track):
    """Set EffectiveName and UserName for a track."""
    start = track["start"]
    end = min(start + 30, track["end"])
    for i in range(start, end):
        if "<EffectiveName" in lines[i]:
            lines[i] = re.sub(r'Value="[^"]*"', 'Value="' + _xml_escape(track["_new_name"]) + '"', lines[i])
        if "<UserName" in lines[i] and "Name>" not in lines[i - 1] if i > start else False:
            if i > start + 5:
                lines[i] = re.sub(r'Value="[^"]*"', 'Value="' + _xml_escape(track["_new_name"]) + '"', lines[i])
                break


def set_track_color(lines, track, color):
    """Set the track's Color Value."""
    start = track["start"]
    end = min(start + 30, track["end"])
    for i in range(start, end):
        if "<Color Value=" in lines[i]:
            lines[i] = re.sub(r'Value="\d+"', 'Value="' + str(color) + '"', lines[i])
            break


def set_track_output_external(lines, track):
    """Route a track's audio output to Ext. Out 1/2 (bypasses the master chain).

    Matches Sam's real reference/master tracks: AudioOut/External/S0.
    """
    in_block = False
    for i in range(track["start"], track["end"] + 1):
        if "<AudioOutputRouting>" in lines[i]:
            in_block = True
        elif "</AudioOutputRouting>" in lines[i]:
            break
        elif in_block:
            if "<Target Value=" in lines[i]:
                lines[i] = re.sub(r'Value="[^"]*"', 'Value="AudioOut/External/S0"', lines[i])
            elif "<UpperDisplayString Value=" in lines[i]:
                lines[i] = re.sub(r'Value="[^"]*"', 'Value="Ext. Out"', lines[i])
            elif "<LowerDisplayString Value=" in lines[i]:
                lines[i] = re.sub(r'Value="[^"]*"', 'Value="1/2"', lines[i])


def set_track_muted(lines, track, muted=True):
    """Set a track's Speaker (mixer on/off). muted=True -> Manual=false (off)."""
    val = "false" if muted else "true"
    in_spk = False
    for i in range(track["start"], track["end"] + 1):
        if "<Speaker>" in lines[i]:
            in_spk = True
        elif in_spk and "<Manual Value=" in lines[i]:
            lines[i] = re.sub(r'Value="[^"]*"', 'Value="' + val + '"', lines[i])
            break


def set_track_output_group(lines, track):
    """Route a track's audio output to its parent group (AudioOut/GroupTrack)."""
    in_block = False
    for i in range(track["start"], track["end"] + 1):
        if "<AudioOutputRouting>" in lines[i]:
            in_block = True
        elif "</AudioOutputRouting>" in lines[i]:
            break
        elif in_block:
            if "<Target Value=" in lines[i]:
                lines[i] = re.sub(r'Value="[^"]*"', 'Value="AudioOut/GroupTrack"', lines[i])
            elif "<UpperDisplayString Value=" in lines[i]:
                lines[i] = re.sub(r'Value="[^"]*"', 'Value="Group"', lines[i])
            elif "<LowerDisplayString Value=" in lines[i]:
                lines[i] = re.sub(r'Value="[^"]*"', 'Value=""', lines[i])


CLIP_START_BEATS = 128  # bar 33 in 4/4


def _read_wav_header(wav_path):
    """Parse WAV header supporting PCM (1) and IEEE float (3) formats."""
    import struct as _struct
    with open(str(wav_path), "rb") as f:
        riff = f.read(12)
        if riff[:4] != b"RIFF" or riff[8:12] != b"WAVE":
            raise ValueError("Not a WAV file: " + str(wav_path))
        fmt_tag = 0
        n_channels = 0
        sample_rate = 0
        bits_per_sample = 0
        data_offset = 0
        data_size = 0
        while True:
            chunk_hdr = f.read(8)
            if len(chunk_hdr) < 8:
                break
            chunk_id = chunk_hdr[:4]
            chunk_size = _struct.unpack("<I", chunk_hdr[4:8])[0]
            if chunk_id == b"fmt ":
                fmt_data = f.read(chunk_size)
                fmt_tag = _struct.unpack("<H", fmt_data[0:2])[0]
                n_channels = _struct.unpack("<H", fmt_data[2:4])[0]
                sample_rate = _struct.unpack("<I", fmt_data[4:8])[0]
                bits_per_sample = _struct.unpack("<H", fmt_data[14:16])[0]
            elif chunk_id == b"data":
                data_offset = f.tell()
                data_size = chunk_size
                break
            else:
                f.seek(chunk_size, 1)
    bytes_per_sample = bits_per_sample // 8
    n_frames = data_size // (n_channels * bytes_per_sample) if bytes_per_sample else 0
    return {
        "fmt": fmt_tag, "channels": n_channels, "rate": sample_rate,
        "bits": bits_per_sample, "bps": bytes_per_sample,
        "n_frames": n_frames, "data_offset": data_offset,
        "data_size": data_size,
    }


def get_wav_info(wav_path):
    """Read sample count, sample rate, and file size from a WAV file."""
    file_size = os.path.getsize(wav_path)
    hdr = _read_wav_header(wav_path)
    return hdr["n_frames"], hdr["rate"], file_size


def _rms_windows_np(raw, n_ch, bps, is_float, window_frames):
    """Per-window RMS in dBFS via numpy (vectorised) — same values as the
    pure-Python loop, but C-level (fast, and dodges the 3.14 interpreter
    miscompiling the per-sample Python loops). Returns a list of dB floats.
    """
    if is_float and bps == 4:
        a = _np.frombuffer(raw, "<f4").astype(_np.float64)
    elif bps == 2:
        a = _np.frombuffer(raw, "<i2").astype(_np.float64) / 32768.0
    elif bps == 4:
        a = _np.frombuffer(raw, "<i4").astype(_np.float64) / 2147483648.0
    elif bps == 3:
        u = _np.frombuffer(raw, _np.uint8)
        m = (u.size // 3) * 3
        u = u[:m].reshape(-1, 3).astype(_np.int32)
        v = u[:, 0] | (u[:, 1] << 8) | (u[:, 2] << 16)
        v = _np.where(v >= 0x800000, v - 0x1000000, v)
        a = v.astype(_np.float64) / 8388608.0
    else:
        return []
    ws = window_frames * n_ch
    if ws <= 0 or a.size == 0:
        return []
    out = []
    nfull = a.size // ws
    if nfull:
        body = a[:nfull * ws].reshape(nfull, ws)
        rms = _np.sqrt((body * body).mean(axis=1))
        db = _np.where(rms > 0, 20.0 * _np.log10(_np.maximum(rms, 1e-12)), -120.0)
        out = db.tolist()
    rem = a[nfull * ws:]
    if rem.size:
        r = float(_np.sqrt((rem * rem).mean()))
        out.append(20.0 * math.log10(r) if r > 0 else -120.0)
    return out


# Absolute floor (dB rel. full scale) below which a whole stem counts as having
# no audio in it — an empty/silent export. find_audio_regions uses a RELATIVE
# threshold (peak - headroom) so a silent file reads as one big region, not as
# empty; this absolute peak floor is what flags a truly silent stem.
SILENCE_FLOOR_DB = -60.0


def find_audio_regions(wav_path, headroom_db=55, window_sec=0.1,
                       min_gap_sec=2.5, tail_sec=1.0, head_sec=0.0,
                       return_peak=False):
    """Find regions of audio content in a WAV file.

    Uses an adaptive threshold: peak_rms - headroom_db. A wide headroom (55 dB)
    keeps the region alive through quiet decays — reverb/crash/fill tails are
    followed down rather than chopped — so clips hug the audio tightly while a
    small tail_sec safety margin catches the very end. Active windows separated
    by less than min_gap_sec are merged into one region (so a continuous groove
    stays one clip; real silence >min_gap splits into tight separate clips).
    Returns a list of (start_sec, end_sec) tuples, or (regions, peak_rms_db) when
    return_peak=True (peak window RMS in dB — below SILENCE_FLOOR_DB = silent).
    """
    import struct as _struct
    import math as _math

    hdr = _read_wav_header(wav_path)
    sr = hdr["rate"]
    n_frames = hdr["n_frames"]
    n_ch = hdr["channels"]
    bps = hdr["bps"]
    is_float = hdr["fmt"] == 3
    total_sec = n_frames / sr
    frame_bytes = n_ch * bps

    window_frames = int(sr * window_sec)
    rms_values = None

    # Fast path: read all samples and compute per-window RMS in numpy.
    if _np is not None:
        try:
            with open(str(wav_path), "rb") as f:
                f.seek(hdr["data_offset"])
                raw_all = f.read(n_frames * frame_bytes)
            rms_values = _rms_windows_np(raw_all, n_ch, bps, is_float, window_frames)
        except Exception:  # noqa: BLE001 — fall back to the stdlib loop
            rms_values = None

    if not rms_values:
        rms_values = []
        with open(str(wav_path), "rb") as f:
            f.seek(hdr["data_offset"])
            pos = 0
            while pos < n_frames:
                count = min(window_frames, n_frames - pos)
                raw = f.read(count * frame_bytes)
                if not raw:
                    break
                if is_float and bps == 4:
                    floats = _struct.unpack("<" + "f" * (len(raw) // 4), raw)
                    sum_sq = sum(v * v for v in floats)
                    n_samples = len(floats)
                elif bps == 3:
                    sum_sq = 0.0
                    n_samples = 0
                    for k in range(0, len(raw) - 2, 3):
                        v = raw[k] | (raw[k + 1] << 8) | (raw[k + 2] << 16)
                        if v >= 0x800000:
                            v -= 0x1000000
                        sum_sq += v * v
                        n_samples += 1
                elif bps == 2:
                    shorts = _struct.unpack("<" + "h" * (len(raw) // 2), raw)
                    sum_sq = sum(v * v for v in shorts)
                    n_samples = len(shorts)
                else:
                    n_samples = 0
                    sum_sq = 0.0

                if n_samples > 0:
                    rms = _math.sqrt(sum_sq / n_samples)
                    if is_float:
                        rms_db = 20 * _math.log10(rms) if rms > 0 else -120.0
                    else:
                        max_val = 2 ** (bps * 8 - 1)
                        rms_db = 20 * _math.log10(rms / max_val) if rms > 0 else -120.0
                else:
                    rms_db = -120.0
                rms_values.append(rms_db)
                pos += window_frames

    peak_rms = max(rms_values) if rms_values else -120.0
    threshold_db = peak_rms - headroom_db

    active = [v > threshold_db for v in rms_values]

    min_gap_windows = int(min_gap_sec / window_sec)
    regions = []
    in_region = False
    region_start = 0
    gap_count = 0

    for idx, is_active in enumerate(active):
        if is_active:
            if not in_region:
                region_start = idx
                in_region = True
            gap_count = 0
        else:
            if in_region:
                gap_count += 1
                if gap_count >= min_gap_windows:
                    region_end = idx - gap_count
                    regions.append((region_start * window_sec,
                                    (region_end + 1) * window_sec))
                    in_region = False
                    gap_count = 0

    if in_region:
        regions.append((region_start * window_sec,
                        min(len(active) * window_sec, total_sec)))

    if not regions:
        result = [(0.0, total_sec)]
    else:
        if tail_sec > 0 or head_sec > 0:
            padded = []
            for i, (start, end) in enumerate(regions):
                new_start = max(start - head_sec, 0.0)
                if i > 0:
                    new_start = max(new_start, padded[-1][1])
                new_end = min(end + tail_sec, total_sec)
                if i + 1 < len(regions):
                    new_end = min(new_end, regions[i + 1][0])
                padded.append((new_start, new_end))
            regions = padded
        result = regions

    return (result, peak_rms) if return_peak else result


def _build_clip_xml(stem_name, clip_color, rel_path, abs_path, sample_count,
                    sample_rate, file_size, bpm, indent,
                    loop_start_sec=0.0, loop_end_sec=None,
                    base_start_beat=CLIP_START_BEATS):
    """Build AudioClip XML lines for a single stem.

    base_start_beat is the arrangement position (in beats) of bar 1 of this
    clip's section — CLIP_START_BEATS (bar 33) for the primary version; later
    versions pass a larger offset so they sit further down the timeline.
    """
    clip_id = _alloc_id()
    take_id = _alloc_id()
    wm_id1 = _alloc_id()
    wm_id2 = _alloc_id()

    full_duration_sec = sample_count / sample_rate
    if loop_end_sec is None:
        loop_end_sec = full_duration_sec

    safe_name = _xml_escape(stem_name)
    safe_rel = _xml_escape(rel_path.replace("\\", "/"))
    safe_abs = _xml_escape(abs_path.replace("\\", "/"))

    t = indent
    t2 = indent + "\t"
    t3 = indent + "\t\t"
    t4 = indent + "\t\t\t"

    clip_start = base_start_beat + (loop_start_sec / 60.0) * bpm
    clip_end = base_start_beat + (loop_end_sec / 60.0) * bpm

    clip_lines = [
        t + '<AudioClip Id="' + str(clip_id) + '" Time="' + str(clip_start) + '">' + CRLF,
        t2 + '<LomId Value="0" />' + CRLF,
        t2 + '<LomIdView Value="0" />' + CRLF,
        t2 + '<CurrentStart Value="' + str(clip_start) + '" />' + CRLF,
        t2 + '<CurrentEnd Value="' + str(clip_end) + '" />' + CRLF,
        t2 + '<Loop>' + CRLF,
        t3 + '<LoopStart Value="' + str(loop_start_sec) + '" />' + CRLF,
        t3 + '<LoopEnd Value="' + str(loop_end_sec) + '" />' + CRLF,
        t3 + '<StartRelative Value="0" />' + CRLF,
        t3 + '<LoopOn Value="false" />' + CRLF,
        t3 + '<OutMarker Value="' + str(loop_end_sec) + '" />' + CRLF,
        t3 + '<HiddenLoopStart Value="' + str(loop_start_sec) + '" />' + CRLF,
        t3 + '<HiddenLoopEnd Value="' + str(loop_end_sec) + '" />' + CRLF,
        t2 + '</Loop>' + CRLF,
        t2 + '<Name Value="' + safe_name + '" />' + CRLF,
        t2 + '<Annotation Value="" />' + CRLF,
        t2 + '<Color Value="' + str(clip_color) + '" />' + CRLF,
        t2 + '<LaunchMode Value="0" />' + CRLF,
        t2 + '<LaunchQuantisation Value="0" />' + CRLF,
        t2 + '<TimeSignature>' + CRLF,
        t3 + '<TimeSignatures>' + CRLF,
        t4 + '<RemoteableTimeSignature Id="0">' + CRLF,
        t4 + '\t<Numerator Value="4" />' + CRLF,
        t4 + '\t<Denominator Value="4" />' + CRLF,
        t4 + '\t<Time Value="0" />' + CRLF,
        t4 + '</RemoteableTimeSignature>' + CRLF,
        t3 + '</TimeSignatures>' + CRLF,
        t2 + '</TimeSignature>' + CRLF,
        t2 + '<Envelopes>' + CRLF,
        t3 + '<Envelopes />' + CRLF,
        t2 + '</Envelopes>' + CRLF,
        t2 + '<ScrollerTimePreserver>' + CRLF,
        t3 + '<LeftTime Value="' + str(loop_start_sec) + '" />' + CRLF,
        t3 + '<RightTime Value="' + str(loop_end_sec) + '" />' + CRLF,
        t2 + '</ScrollerTimePreserver>' + CRLF,
        t2 + '<TimeSelection>' + CRLF,
        t3 + '<AnchorTime Value="0" />' + CRLF,
        t3 + '<OtherTime Value="0" />' + CRLF,
        t2 + '</TimeSelection>' + CRLF,
        t2 + '<Legato Value="false" />' + CRLF,
        t2 + '<Ram Value="false" />' + CRLF,
        t2 + '<GrooveSettings>' + CRLF,
        t3 + '<GrooveId Value="-1" />' + CRLF,
        t2 + '</GrooveSettings>' + CRLF,
        t2 + '<Disabled Value="false" />' + CRLF,
        t2 + '<VelocityAmount Value="0" />' + CRLF,
        t2 + '<FollowAction>' + CRLF,
        t3 + '<FollowTime Value="4" />' + CRLF,
        t3 + '<IsLinked Value="true" />' + CRLF,
        t3 + '<LoopIterations Value="1" />' + CRLF,
        t3 + '<FollowActionA Value="4" />' + CRLF,
        t3 + '<FollowActionB Value="0" />' + CRLF,
        t3 + '<FollowChanceA Value="100" />' + CRLF,
        t3 + '<FollowChanceB Value="0" />' + CRLF,
        t3 + '<JumpIndexA Value="1" />' + CRLF,
        t3 + '<JumpIndexB Value="1" />' + CRLF,
        t3 + '<FollowActionEnabled Value="false" />' + CRLF,
        t2 + '</FollowAction>' + CRLF,
        t2 + '<Grid>' + CRLF,
        t3 + '<FixedNumerator Value="1" />' + CRLF,
        t3 + '<FixedDenominator Value="16" />' + CRLF,
        t3 + '<GridIntervalPixel Value="20" />' + CRLF,
        t3 + '<Ntoles Value="2" />' + CRLF,
        t3 + '<SnapToGrid Value="true" />' + CRLF,
        t3 + '<Fixed Value="false" />' + CRLF,
        t2 + '</Grid>' + CRLF,
        t2 + '<FreezeStart Value="0" />' + CRLF,
        t2 + '<FreezeEnd Value="0" />' + CRLF,
        t2 + '<IsWarped Value="false" />' + CRLF,
        t2 + '<TakeId Value="' + str(take_id) + '" />' + CRLF,
        t2 + '<IsInKey Value="true" />' + CRLF,
        t2 + '<ScaleInformation>' + CRLF,
        t3 + '<Root Value="0" />' + CRLF,
        t3 + '<Name Value="0" />' + CRLF,
        t2 + '</ScaleInformation>' + CRLF,
        t2 + '<SampleRef>' + CRLF,
        t3 + '<FileRef>' + CRLF,
        t4 + '<RelativePathType Value="3" />' + CRLF,
        t4 + '<RelativePath Value="' + safe_rel + '" />' + CRLF,
        t4 + '<Path Value="' + safe_abs + '" />' + CRLF,
        t4 + '<Type Value="1" />' + CRLF,
        t4 + '<LivePackName Value="" />' + CRLF,
        t4 + '<LivePackId Value="" />' + CRLF,
        t4 + '<OriginalFileSize Value="' + str(file_size) + '" />' + CRLF,
        t4 + '<OriginalCrc Value="0" />' + CRLF,
        t4 + '<SourceHint Value="" />' + CRLF,
        t3 + '</FileRef>' + CRLF,
        t3 + '<LastModDate Value="0" />' + CRLF,
        t3 + '<SourceContext />' + CRLF,
        t3 + '<SampleUsageHint Value="0" />' + CRLF,
        t3 + '<DefaultDuration Value="' + str(sample_count) + '" />' + CRLF,
        t3 + '<DefaultSampleRate Value="' + str(sample_rate) + '" />' + CRLF,
        t3 + '<SamplesToAutoWarp Value="0" />' + CRLF,
        t2 + '</SampleRef>' + CRLF,
        t2 + '<Onsets>' + CRLF,
        t3 + '<UserOnsets />' + CRLF,
        t3 + '<HasUserOnsets Value="false" />' + CRLF,
        t2 + '</Onsets>' + CRLF,
        t2 + '<WarpMode Value="0" />' + CRLF,
        t2 + '<GranularityTones Value="30" />' + CRLF,
        t2 + '<GranularityTexture Value="65" />' + CRLF,
        t2 + '<FluctuationTexture Value="25" />' + CRLF,
        t2 + '<TransientResolution Value="6" />' + CRLF,
        t2 + '<TransientLoopMode Value="2" />' + CRLF,
        t2 + '<TransientEnvelope Value="100" />' + CRLF,
        t2 + '<ComplexProFormants Value="100" />' + CRLF,
        t2 + '<ComplexProEnvelope Value="128" />' + CRLF,
        t2 + '<Sync Value="true" />' + CRLF,
        t2 + '<HiQ Value="true" />' + CRLF,
        t2 + '<Fade Value="false" />' + CRLF,
        t2 + '<Fades>' + CRLF,
        t3 + '<FadeInLength Value="0" />' + CRLF,
        t3 + '<FadeOutLength Value="0" />' + CRLF,
        t3 + '<ClipFadesAreInitialized Value="true" />' + CRLF,
        t3 + '<CrossfadeInState Value="0" />' + CRLF,
        t3 + '<FadeInCurveSkew Value="0" />' + CRLF,
        t3 + '<FadeInCurveSlope Value="0" />' + CRLF,
        t3 + '<FadeOutCurveSkew Value="0" />' + CRLF,
        t3 + '<FadeOutCurveSlope Value="0" />' + CRLF,
        t3 + '<IsDefaultFadeIn Value="false" />' + CRLF,
        t3 + '<IsDefaultFadeOut Value="false" />' + CRLF,
        t2 + '</Fades>' + CRLF,
        t2 + '<PitchCoarse Value="0" />' + CRLF,
        t2 + '<PitchFine Value="0" />' + CRLF,
        t2 + '<SampleVolume Value="1" />' + CRLF,
        t2 + '<WarpMarkers>' + CRLF,
        t3 + '<WarpMarker Id="' + str(wm_id1) + '" SecTime="0" BeatTime="0" />' + CRLF,
        t3 + '<WarpMarker Id="' + str(wm_id2) + '" SecTime="0.015" BeatTime="0.03125" />' + CRLF,
        t2 + '</WarpMarkers>' + CRLF,
        t2 + '<SavedWarpMarkersForStretched />' + CRLF,
        t2 + '<MarkersGenerated Value="true" />' + CRLF,
        t2 + '<IsSongTempoLeader Value="false" />' + CRLF,
        t + '</AudioClip>' + CRLF,
    ]

    return clip_lines


def insert_clip_into_track(lines, track, stem_name, clip_color, rel_path,
                           abs_path, sample_count, sample_rate, file_size, bpm,
                           regions=None, base_start_beat=CLIP_START_BEATS):
    """Insert AudioClips into a track's MainSequencer Events block.

    regions is a list of (start_sec, end_sec) tuples. One clip per region.
    base_start_beat offsets the clips down the arrangement (for later versions).
    Can be called more than once on the same track — subsequent calls append
    their clips into the now-open Events block (used to stack versions on one
    track). Returns the number of lines inserted.
    """
    if regions is None:
        full_sec = sample_count / sample_rate
        regions = [(0.0, full_sec)]

    start = track["start"]
    end = track["end"]

    empty_line = open_line = close_line = None
    in_main_sequencer = False
    for i in range(start, end + 1):
        if "<MainSequencer>" in lines[i]:
            in_main_sequencer = True
        elif "</MainSequencer>" in lines[i]:
            in_main_sequencer = False
        if not in_main_sequencer:
            continue
        if "<Events />" in lines[i]:
            empty_line = i
            break
        if "<Events>" in lines[i] and open_line is None:
            open_line = i
        elif open_line is not None and "</Events>" in lines[i]:
            close_line = i
            break

    indent = "\t\t\t\t\t\t\t"
    all_clip_lines = []
    for region_start, region_end in regions:
        all_clip_lines.extend(_build_clip_xml(
            stem_name, clip_color, rel_path, abs_path,
            sample_count, sample_rate, file_size, bpm, indent,
            loop_start_sec=region_start, loop_end_sec=region_end,
            base_start_beat=base_start_beat
        ))

    if empty_line is not None:
        events_open = lines[empty_line].replace("<Events />", "<Events>")
        new_lines = [events_open] + all_clip_lines + ["\t\t\t\t\t\t</Events>" + CRLF]
        lines[empty_line:empty_line + 1] = new_lines
        return len(new_lines) - 1
    if close_line is not None:
        # Events already populated (a previous version's clips) — append before </Events>.
        lines[close_line:close_line] = all_clip_lines
        return len(all_clip_lines)
    return 0


def remove_tracks_by_indices(lines, track_ranges_to_remove):
    """Remove tracks from lines by their (start, end) ranges.

    Process in REVERSE order so earlier indices stay valid.
    """
    for start, end in sorted(track_ranges_to_remove, reverse=True):
        del lines[start:end + 1]


_GROUP_TRACK_TEMPLATE = '''\t\t\t<GroupTrack Id="{GID}" SelectedToolPanel="7" SelectedTransformationName="" SelectedGeneratorName="">
\t\t\t\t<LomId Value="0" />
\t\t\t\t<LomIdView Value="0" />
\t\t\t\t<IsContentSelectedInDocument Value="false" />
\t\t\t\t<PreferredContentViewMode Value="0" />
\t\t\t\t<TrackDelay>
\t\t\t\t\t<Value Value="0" />
\t\t\t\t\t<IsValueSampleBased Value="false" />
\t\t\t\t</TrackDelay>
\t\t\t\t<Name>
\t\t\t\t\t<EffectiveName Value="{NAME}" />
\t\t\t\t\t<UserName Value="{NAME}" />
\t\t\t\t\t<Annotation Value="" />
\t\t\t\t\t<MemorizedFirstClipName Value="" />
\t\t\t\t</Name>
\t\t\t\t<Color Value="{COLOR}" />
\t\t\t\t<AutomationEnvelopes>
\t\t\t\t\t<Envelopes />
\t\t\t\t</AutomationEnvelopes>
\t\t\t\t<TrackGroupId Value="{TGID}" />
\t\t\t\t<TrackUnfolded Value="{UNFOLDED}" />
\t\t\t\t<DevicesListWrapper LomId="0" />
\t\t\t\t<ClipSlotsListWrapper LomId="0" />
\t\t\t\t<ArrangementClipsListWrapper LomId="0" />
\t\t\t\t<TakeLanesListWrapper LomId="0" />
\t\t\t\t<ViewData Value="{{}}" />
\t\t\t\t<TakeLanes>
\t\t\t\t\t<TakeLanes />
\t\t\t\t\t<AreTakeLanesFolded Value="true" />
\t\t\t\t</TakeLanes>
\t\t\t\t<LinkedTrackGroupId Value="-1" />
\t\t\t\t<Slots>
\t\t\t\t\t<GroupTrackSlot Id="0">
\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t</GroupTrackSlot>
\t\t\t\t\t<GroupTrackSlot Id="1">
\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t</GroupTrackSlot>
\t\t\t\t\t<GroupTrackSlot Id="2">
\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t</GroupTrackSlot>
\t\t\t\t\t<GroupTrackSlot Id="3">
\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t</GroupTrackSlot>
\t\t\t\t\t<GroupTrackSlot Id="4">
\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t</GroupTrackSlot>
\t\t\t\t\t<GroupTrackSlot Id="5">
\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t</GroupTrackSlot>
\t\t\t\t\t<GroupTrackSlot Id="6">
\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t</GroupTrackSlot>
\t\t\t\t\t<GroupTrackSlot Id="7">
\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t</GroupTrackSlot>
\t\t\t\t</Slots>
\t\t\t\t<Freeze Value="false" />
\t\t\t\t<DeviceChain>
\t\t\t\t\t<AutomationLanes>
\t\t\t\t\t\t<AutomationLanes>
\t\t\t\t\t\t\t<AutomationLane Id="0">
\t\t\t\t\t\t\t\t<SelectedDevice Value="1" />
\t\t\t\t\t\t\t\t<SelectedEnvelope Value="0" />
\t\t\t\t\t\t\t\t<IsContentSelectedInDocument Value="false" />
\t\t\t\t\t\t\t\t<LaneHeight Value="17" />
\t\t\t\t\t\t\t</AutomationLane>
\t\t\t\t\t\t</AutomationLanes>
\t\t\t\t\t\t<AreAdditionalAutomationLanesFolded Value="false" />
\t\t\t\t\t</AutomationLanes>
\t\t\t\t\t<ClipEnvelopeChooserViewState>
\t\t\t\t\t\t<SelectedDevice Value="0" />
\t\t\t\t\t\t<SelectedEnvelope Value="0" />
\t\t\t\t\t\t<PreferModulationVisible Value="false" />
\t\t\t\t\t</ClipEnvelopeChooserViewState>
\t\t\t\t\t<AudioInputRouting>
\t\t\t\t\t\t<Target Value="AudioIn/External/S0" />
\t\t\t\t\t\t<UpperDisplayString Value="Ext. In" />
\t\t\t\t\t\t<LowerDisplayString Value="1/2" />
\t\t\t\t\t\t<MpeSettings>
\t\t\t\t\t\t\t<ZoneType Value="0" />
\t\t\t\t\t\t\t<FirstNoteChannel Value="1" />
\t\t\t\t\t\t\t<LastNoteChannel Value="15" />
\t\t\t\t\t\t</MpeSettings>
\t\t\t\t\t\t<MpePitchBendUsesTuning Value="true" />
\t\t\t\t\t</AudioInputRouting>
\t\t\t\t\t<MidiInputRouting>
\t\t\t\t\t\t<Target Value="MidiIn/External.All/-1" />
\t\t\t\t\t\t<UpperDisplayString Value="Ext: All Ins" />
\t\t\t\t\t\t<LowerDisplayString Value="" />
\t\t\t\t\t\t<MpeSettings>
\t\t\t\t\t\t\t<ZoneType Value="0" />
\t\t\t\t\t\t\t<FirstNoteChannel Value="1" />
\t\t\t\t\t\t\t<LastNoteChannel Value="15" />
\t\t\t\t\t\t</MpeSettings>
\t\t\t\t\t\t<MpePitchBendUsesTuning Value="true" />
\t\t\t\t\t</MidiInputRouting>
\t\t\t\t\t<AudioOutputRouting>
\t\t\t\t\t\t<Target Value="{OUT_TARGET}" />
\t\t\t\t\t\t<UpperDisplayString Value="{OUT_UPPER}" />
\t\t\t\t\t\t<LowerDisplayString Value="{OUT_LOWER}" />
\t\t\t\t\t\t<MpeSettings>
\t\t\t\t\t\t\t<ZoneType Value="0" />
\t\t\t\t\t\t\t<FirstNoteChannel Value="1" />
\t\t\t\t\t\t\t<LastNoteChannel Value="15" />
\t\t\t\t\t\t</MpeSettings>
\t\t\t\t\t\t<MpePitchBendUsesTuning Value="true" />
\t\t\t\t\t</AudioOutputRouting>
\t\t\t\t\t<MidiOutputRouting>
\t\t\t\t\t\t<Target Value="MidiOut/None" />
\t\t\t\t\t\t<UpperDisplayString Value="None" />
\t\t\t\t\t\t<LowerDisplayString Value="" />
\t\t\t\t\t\t<MpeSettings>
\t\t\t\t\t\t\t<ZoneType Value="0" />
\t\t\t\t\t\t\t<FirstNoteChannel Value="1" />
\t\t\t\t\t\t\t<LastNoteChannel Value="15" />
\t\t\t\t\t\t</MpeSettings>
\t\t\t\t\t\t<MpePitchBendUsesTuning Value="true" />
\t\t\t\t\t</MidiOutputRouting>
\t\t\t\t\t<Mixer>
\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t\t<LomIdView Value="0" />
\t\t\t\t\t\t<IsExpanded Value="true" />
\t\t\t\t\t\t<BreakoutIsExpanded Value="false" />
\t\t\t\t\t\t<On>
\t\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t\t\t<Manual Value="true" />
\t\t\t\t\t\t\t<AutomationTarget Id="{ID_MIX_ON}">
\t\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t\t</AutomationTarget>
\t\t\t\t\t\t\t<MidiCCOnOffThresholds>
\t\t\t\t\t\t\t\t<Min Value="64" />
\t\t\t\t\t\t\t\t<Max Value="127" />
\t\t\t\t\t\t\t</MidiCCOnOffThresholds>
\t\t\t\t\t\t</On>
\t\t\t\t\t\t<ModulationSourceCount Value="0" />
\t\t\t\t\t\t<ParametersListWrapper LomId="0" />
\t\t\t\t\t\t<Pointee Id="{ID_MIX_POINTEE}" />
\t\t\t\t\t\t<LastSelectedTimeableIndex Value="0" />
\t\t\t\t\t\t<LastSelectedClipEnvelopeIndex Value="0" />
\t\t\t\t\t\t<LastPresetRef>
\t\t\t\t\t\t\t<Value />
\t\t\t\t\t\t</LastPresetRef>
\t\t\t\t\t\t<LockedScripts />
\t\t\t\t\t\t<IsFolded Value="false" />
\t\t\t\t\t\t<ShouldShowPresetName Value="false" />
\t\t\t\t\t\t<UserName Value="" />
\t\t\t\t\t\t<Annotation Value="" />
\t\t\t\t\t\t<SourceContext>
\t\t\t\t\t\t\t<Value />
\t\t\t\t\t\t</SourceContext>
\t\t\t\t\t\t<MpePitchBendUsesTuning Value="true" />
\t\t\t\t\t\t<ViewData Value="{{}}" />
\t\t\t\t\t\t<Sends />
\t\t\t\t\t\t<Speaker>
\t\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t\t\t<Manual Value="{SPK_ON}" />
\t\t\t\t\t\t\t<AutomationTarget Id="{ID_SPK}">
\t\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t\t</AutomationTarget>
\t\t\t\t\t\t\t<MidiCCOnOffThresholds>
\t\t\t\t\t\t\t\t<Min Value="64" />
\t\t\t\t\t\t\t\t<Max Value="127" />
\t\t\t\t\t\t\t</MidiCCOnOffThresholds>
\t\t\t\t\t\t</Speaker>
\t\t\t\t\t\t<SoloSink Value="false" />
\t\t\t\t\t\t<PanMode Value="0" />
\t\t\t\t\t\t<Pan>
\t\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t\t\t<Manual Value="0" />
\t\t\t\t\t\t\t<MidiControllerRange>
\t\t\t\t\t\t\t\t<Min Value="-1" />
\t\t\t\t\t\t\t\t<Max Value="1" />
\t\t\t\t\t\t\t</MidiControllerRange>
\t\t\t\t\t\t\t<AutomationTarget Id="{ID_PAN_AT}">
\t\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t\t</AutomationTarget>
\t\t\t\t\t\t\t<ModulationTarget Id="{ID_PAN_MT}">
\t\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t\t</ModulationTarget>
\t\t\t\t\t\t</Pan>
\t\t\t\t\t\t<SplitStereoPanL>
\t\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t\t\t<Manual Value="-1" />
\t\t\t\t\t\t\t<MidiControllerRange>
\t\t\t\t\t\t\t\t<Min Value="-1" />
\t\t\t\t\t\t\t\t<Max Value="1" />
\t\t\t\t\t\t\t</MidiControllerRange>
\t\t\t\t\t\t\t<AutomationTarget Id="{ID_SPL_AT}">
\t\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t\t</AutomationTarget>
\t\t\t\t\t\t\t<ModulationTarget Id="{ID_SPL_MT}">
\t\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t\t</ModulationTarget>
\t\t\t\t\t\t</SplitStereoPanL>
\t\t\t\t\t\t<SplitStereoPanR>
\t\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t\t\t<Manual Value="1" />
\t\t\t\t\t\t\t<MidiControllerRange>
\t\t\t\t\t\t\t\t<Min Value="-1" />
\t\t\t\t\t\t\t\t<Max Value="1" />
\t\t\t\t\t\t\t</MidiControllerRange>
\t\t\t\t\t\t\t<AutomationTarget Id="{ID_SPR_AT}">
\t\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t\t</AutomationTarget>
\t\t\t\t\t\t\t<ModulationTarget Id="{ID_SPR_MT}">
\t\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t\t</ModulationTarget>
\t\t\t\t\t\t</SplitStereoPanR>
\t\t\t\t\t\t<Volume>
\t\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t\t\t<Manual Value="1" />
\t\t\t\t\t\t\t<MidiControllerRange>
\t\t\t\t\t\t\t\t<Min Value="0.0003162277571" />
\t\t\t\t\t\t\t\t<Max Value="1.99526227" />
\t\t\t\t\t\t\t</MidiControllerRange>
\t\t\t\t\t\t\t<AutomationTarget Id="{ID_VOL_AT}">
\t\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t\t</AutomationTarget>
\t\t\t\t\t\t\t<ModulationTarget Id="{ID_VOL_MT}">
\t\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t\t</ModulationTarget>
\t\t\t\t\t\t</Volume>
\t\t\t\t\t\t<ViewStateSessionTrackWidth Value="93" />
\t\t\t\t\t\t<CrossFadeState>
\t\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t\t\t<Manual Value="1" />
\t\t\t\t\t\t\t<AutomationTarget Id="{ID_XF}">
\t\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t\t</AutomationTarget>
\t\t\t\t\t\t\t<MidiControllerRange>
\t\t\t\t\t\t\t\t<Min Value="0" />
\t\t\t\t\t\t\t\t<Max Value="2" />
\t\t\t\t\t\t\t</MidiControllerRange>
\t\t\t\t\t\t</CrossFadeState>
\t\t\t\t\t\t<SendsListWrapper LomId="0" />
\t\t\t\t\t</Mixer>
\t\t\t\t\t<DeviceChain>
\t\t\t\t\t\t<Devices />
\t\t\t\t\t\t<SignalModulations />
\t\t\t\t\t</DeviceChain>
\t\t\t\t\t<FreezeSequencer>
\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t\t<LomIdView Value="0" />
\t\t\t\t\t\t<IsExpanded Value="true" />
\t\t\t\t\t\t<BreakoutIsExpanded Value="false" />
\t\t\t\t\t\t<On>
\t\t\t\t\t\t\t<LomId Value="0" />
\t\t\t\t\t\t\t<Manual Value="true" />
\t\t\t\t\t\t\t<AutomationTarget Id="{ID_FZ_ON}">
\t\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t\t</AutomationTarget>
\t\t\t\t\t\t\t<MidiCCOnOffThresholds>
\t\t\t\t\t\t\t\t<Min Value="64" />
\t\t\t\t\t\t\t\t<Max Value="127" />
\t\t\t\t\t\t\t</MidiCCOnOffThresholds>
\t\t\t\t\t\t</On>
\t\t\t\t\t\t<ModulationSourceCount Value="0" />
\t\t\t\t\t\t<ParametersListWrapper LomId="0" />
\t\t\t\t\t\t<Pointee Id="{ID_FZ_POINTEE}" />
\t\t\t\t\t\t<LastSelectedTimeableIndex Value="0" />
\t\t\t\t\t\t<LastSelectedClipEnvelopeIndex Value="0" />
\t\t\t\t\t\t<LastPresetRef>
\t\t\t\t\t\t\t<Value />
\t\t\t\t\t\t</LastPresetRef>
\t\t\t\t\t\t<LockedScripts />
\t\t\t\t\t\t<IsFolded Value="false" />
\t\t\t\t\t\t<ShouldShowPresetName Value="true" />
\t\t\t\t\t\t<UserName Value="" />
\t\t\t\t\t\t<Annotation Value="" />
\t\t\t\t\t\t<SourceContext>
\t\t\t\t\t\t\t<Value />
\t\t\t\t\t\t</SourceContext>
\t\t\t\t\t\t<MpePitchBendUsesTuning Value="true" />
\t\t\t\t\t\t<ViewData Value="{{}}" />
\t\t\t\t\t\t<ClipSlotList />
\t\t\t\t\t\t<MonitoringEnum Value="1" />
\t\t\t\t\t\t<KeepRecordMonitoringLatency Value="true" />
\t\t\t\t\t\t<Sample>
\t\t\t\t\t\t\t<ArrangerAutomation>
\t\t\t\t\t\t\t\t<Events />
\t\t\t\t\t\t\t\t<AutomationTransformViewState>
\t\t\t\t\t\t\t\t\t<IsTransformPending Value="false" />
\t\t\t\t\t\t\t\t\t<TimeAndValueTransforms />
\t\t\t\t\t\t\t\t</AutomationTransformViewState>
\t\t\t\t\t\t\t</ArrangerAutomation>
\t\t\t\t\t\t</Sample>
\t\t\t\t\t\t<VolumeModulationTarget Id="{ID_FZ_VOL}">
\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t</VolumeModulationTarget>
\t\t\t\t\t\t<TranspositionModulationTarget Id="{ID_FZ_TRANS}">
\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t</TranspositionModulationTarget>
\t\t\t\t\t\t<TransientEnvelopeModulationTarget Id="{ID_FZ_TRENV}">
\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t</TransientEnvelopeModulationTarget>
\t\t\t\t\t\t<GrainSizeModulationTarget Id="{ID_FZ_GRAIN}">
\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t</GrainSizeModulationTarget>
\t\t\t\t\t\t<FluxModulationTarget Id="{ID_FZ_FLUX}">
\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t</FluxModulationTarget>
\t\t\t\t\t\t<SampleOffsetModulationTarget Id="{ID_FZ_OFF}">
\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t</SampleOffsetModulationTarget>
\t\t\t\t\t\t<ComplexProFormantsModulationTarget Id="{ID_FZ_FORM}">
\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t</ComplexProFormantsModulationTarget>
\t\t\t\t\t\t<ComplexProEnvelopeModulationTarget Id="{ID_FZ_ENV}">
\t\t\t\t\t\t\t<LockEnvelope Value="0" />
\t\t\t\t\t\t</ComplexProEnvelopeModulationTarget>
\t\t\t\t\t\t<PitchViewScrollPosition Value="-1073741824" />
\t\t\t\t\t\t<SampleOffsetModulationScrollPosition Value="-1073741824" />
\t\t\t\t\t\t<Recorder>
\t\t\t\t\t\t\t<IsArmed Value="false" />
\t\t\t\t\t\t\t<TakeCounter Value="1" />
\t\t\t\t\t\t</Recorder>
\t\t\t\t\t</FreezeSequencer>
\t\t\t\t</DeviceChain>
\t\t\t</GroupTrack>
'''


def insert_group_track(lines, insert_before_line, group_name, group_id,
                       color=14, num_scenes=8, muted=True, unfolded=False,
                       parent_group_id=-1):
    """Insert a properly-structured GroupTrack matching Ableton 12.4 format.

    `muted` sets the Speaker (False = audible, for working submix groups; True =
    muted). `unfolded` sets expanded (True) vs collapsed.

    `parent_group_id` nests this group inside another GroupTrack: -1 = top-level
    (TrackGroupId -1, output routed to Main); any other id makes this a SUB-group
    whose TrackGroupId points at the parent and whose audio is routed up into it
    (AudioOut/GroupTrack). Returns the number of lines inserted.
    """
    nested = parent_group_id is not None and int(parent_group_id) != -1
    block = _GROUP_TRACK_TEMPLATE.format(
        GID=group_id,
        NAME=_xml_escape(group_name),
        COLOR=color,
        TGID=parent_group_id if parent_group_id is not None else -1,
        OUT_TARGET="AudioOut/GroupTrack" if nested else "AudioOut/Main",
        OUT_UPPER="Group" if nested else "Main",
        OUT_LOWER="",
        SPK_ON="false" if muted else "true",
        UNFOLDED="true" if unfolded else "false",
        ID_MIX_ON=_alloc_id(),
        ID_MIX_POINTEE=_alloc_id(),
        ID_SPK=_alloc_id(),
        ID_PAN_AT=_alloc_id(),
        ID_PAN_MT=_alloc_id(),
        ID_SPL_AT=_alloc_id(),
        ID_SPL_MT=_alloc_id(),
        ID_SPR_AT=_alloc_id(),
        ID_SPR_MT=_alloc_id(),
        ID_VOL_AT=_alloc_id(),
        ID_VOL_MT=_alloc_id(),
        ID_XF=_alloc_id(),
        ID_FZ_ON=_alloc_id(),
        ID_FZ_POINTEE=_alloc_id(),
        ID_FZ_VOL=_alloc_id(),
        ID_FZ_TRANS=_alloc_id(),
        ID_FZ_TRENV=_alloc_id(),
        ID_FZ_GRAIN=_alloc_id(),
        ID_FZ_FLUX=_alloc_id(),
        ID_FZ_OFF=_alloc_id(),
        ID_FZ_FORM=_alloc_id(),
        ID_FZ_ENV=_alloc_id(),
    )
    gt = [line + CRLF for line in block.split("\n") if line]
    lines[insert_before_line:insert_before_line] = gt
    return len(gt)


def set_track_group_id(lines, track, group_id):
    """Set TrackGroupId on a track."""
    for i in range(track["start"], track["end"] + 1):
        if "<TrackGroupId" in lines[i]:
            lines[i] = re.sub(
                r'Value="[^"]*"',
                'Value="' + str(group_id) + '"',
                lines[i]
            )
            return


def set_track_lane_height(lines, track, height):
    """Set the first LaneHeight value inside a track's AutomationLanes."""
    for i in range(track["start"], track["end"] + 1):
        if "<LaneHeight" in lines[i]:
            lines[i] = re.sub(
                r'Value="\d+"',
                'Value="' + str(height) + '"',
                lines[i]
            )
            return


def set_track_unfolded(lines, track, value):
    """Set the TrackUnfolded value (true = expanded, false = collapsed)."""
    val_str = "true" if value else "false"
    for i in range(track["start"], track["end"] + 1):
        if "<TrackUnfolded" in lines[i]:
            lines[i] = re.sub(
                r'Value="[^"]*"',
                'Value="' + val_str + '"',
                lines[i]
            )
            return


def clear_all_selections(lines):
    """Set IsContentSelectedInDocument=false everywhere. Multi-selected tracks
    inside a group force the group to open expanded on load.
    """
    for i, line in enumerate(lines):
        if "<IsContentSelectedInDocument" in line:
            lines[i] = re.sub(
                r'Value="[^"]*"',
                'Value="false"',
                lines[i]
            )


def set_global_tempo(lines, bpm):
    """Set the global tempo on the MainTrack.

    Updates both the Manual value and the tempo automation FloatEvent
    (PointeeId 8), which Ableton uses as the actual display tempo.
    """
    in_main = False
    in_tempo = False
    tempo_target_id = None
    manual_done = False
    for i, line in enumerate(lines):
        if "<MainTrack " in line or "<MainTrack>" in line:
            in_main = True
        if in_main and "<Tempo>" in line and not in_tempo:
            in_tempo = True
        if in_main and in_tempo and "<Manual Value=" in line and not manual_done:
            lines[i] = re.sub(
                r'Value="[^"]*"',
                'Value="' + str(int(bpm)) + '"',
                lines[i]
            )
            manual_done = True
        if in_main and in_tempo and "<AutomationTarget Id=" in line:
            m = re.search(r'Id="(\d+)"', line)
            if m:
                tempo_target_id = m.group(1)
            in_tempo = False
        if in_main and "</MainTrack>" in line:
            break

    if tempo_target_id:
        in_envelope = False
        found_pointee = False
        for i, line in enumerate(lines):
            if "<AutomationEnvelope " in line:
                in_envelope = True
                found_pointee = False
            if in_envelope and "<PointeeId Value=" in line:
                m = re.search(r'Value="(\d+)"', line)
                if m and m.group(1) == tempo_target_id:
                    found_pointee = True
            if in_envelope and found_pointee and "<FloatEvent " in line and "63072000" in line:
                lines[i] = re.sub(
                    r'Value="[^"]*"(\s*/>)',
                    'Value="' + str(int(bpm)) + '"\\1',
                    lines[i]
                )
                return
            if "</AutomationEnvelope>" in line:
                in_envelope = False
                found_pointee = False


def insert_locators(lines, locators):
    """Fill the arrangement Locators (markers). locators = [(time_beat, name)].

    Replaces the empty <Locators /> with named locator entries.
    """
    if not locators:
        return
    block = []
    for time_beat, name in locators:
        lid = _alloc_id()
        tval = ("%d" % round(time_beat)) if abs(time_beat - round(time_beat)) < 1e-6 else ("%.6f" % time_beat)
        block.extend([
            '\t\t\t\t<Locator Id="' + str(lid) + '">' + CRLF,
            '\t\t\t\t\t<LomId Value="0" />' + CRLF,
            '\t\t\t\t\t<Time Value="' + tval + '" />' + CRLF,
            '\t\t\t\t\t<Name Value="' + _xml_escape(name) + '" />' + CRLF,
            '\t\t\t\t\t<Annotation Value="" />' + CRLF,
            '\t\t\t\t\t<IsSongStart Value="false" />' + CRLF,
            '\t\t\t\t</Locator>' + CRLF,
        ])
    for i, line in enumerate(lines):
        if "<Locators>" in line:
            # the inner empty list is the next line: <Locators />
            for j in range(i + 1, min(i + 4, len(lines))):
                if "<Locators />" in lines[j]:
                    indent = lines[j][:len(lines[j]) - len(lines[j].lstrip())]
                    new = [indent + "<Locators>" + CRLF] + block + [indent + "</Locators>" + CRLF]
                    lines[j:j + 1] = new
                    return
            return


def _apply_track_groups(lines, stems):
    """Wrap tagged working stems in (optionally nested) GroupTracks.

    A stem's `group_key` marks its top-level category submix (Drums/Vox/...);
    an optional `subgroup_key` nests it one level deeper inside a named
    sub-group (e.g. a singer under Vox, Kit/Percussion under Drums). Stems
    sharing a key must be contiguous (project_builder lays them out that way).
    The group_*/subgroup_* fields carry each header's name/color/muted/unfolded.

    GroupTrack headers are invisible to find_track_ranges, so audio-track
    indices stay aligned to `stems` (track i+1 == stems[i]) throughout —
    Session Time is audio track 0. We set each child's TrackGroupId in place
    first, then insert the headers; inserting top-to-bottom and re-finding the
    audio tracks before every insert keeps a parent header above its sub-group.
    """
    # 1. Parent runs: consecutive stems sharing a group_key.
    parent_runs = []
    i = 0
    while i < len(stems):
        if stems[i].get("group_key"):
            j = i
            gk = stems[i]["group_key"]
            while j < len(stems) and stems[j].get("group_key") == gk:
                j += 1
            parent_runs.append((i, j))
            i = j
        else:
            i += 1
    if not parent_runs:
        return

    # 2. Allocate group ids, map each child stem to its DIRECT parent group,
    #    and collect the headers to insert.
    direct_parent = {}   # stem index -> id of its immediate containing group
    headers = []         # (first_stem_index, depth, gid, parent_gid, name, color, muted, unfolded)
    for (a, b) in parent_runs:
        pid = _alloc_id()
        s0 = stems[a]
        headers.append((a, 0, pid, -1,
                        s0.get("group_name", "Group"),
                        s0.get("group_color", s0["color"]),
                        s0.get("group_muted", False),
                        s0.get("group_unfolded", True)))
        k = a
        while k < b:
            sk = stems[k].get("subgroup_key")
            if sk:
                m = k
                while m < b and stems[m].get("subgroup_key") == sk:
                    m += 1
                sid = _alloc_id()
                sub0 = stems[k]
                headers.append((k, 1, sid, pid,
                                sub0.get("subgroup_name", "Group"),
                                sub0.get("subgroup_color",
                                         sub0.get("group_color", sub0["color"])),
                                sub0.get("subgroup_muted", False),
                                sub0.get("subgroup_unfolded", True)))
                for s in range(k, m):
                    direct_parent[s] = sid
                k = m
            else:
                direct_parent[k] = pid
                k += 1

    # 3. Route each child into its immediate parent (in place — no line shift).
    audio_g = [t for t in find_track_ranges(lines) if t["type"] == "AudioTrack"]
    for si, gid in direct_parent.items():
        tidx = si + 1
        if tidx < len(audio_g):
            set_track_group_id(lines, audio_g[tidx], gid)
            set_track_output_group(lines, audio_g[tidx])

    # 4. Insert headers. (first_index asc, depth asc) + re-find before each
    #    insert => a parent header lands above its own first sub-group header.
    for (first_idx, _depth, gid, parent_gid, name, color, muted, unfolded) in sorted(
            headers, key=lambda h: (h[0], h[1])):
        audio_g = [t for t in find_track_ranges(lines) if t["type"] == "AudioTrack"]
        tidx = first_idx + 1
        if tidx < len(audio_g):
            insert_group_track(
                lines, audio_g[tidx]["start"], name, gid,
                color=color, muted=muted, unfolded=unfolded,
                parent_group_id=parent_gid,
            )


def patch_project(template_path, output_path, stems, bpm, project_audio_dir,
                  locators=None):
    """Main entry point: patch a template with stems and write the result.

    Args:
        template_path: Path to the template .als file
        output_path: Path for the output .als file
        stems: list of dicts with keys:
            name: display name for the track
            category: from stem_classifier (kick, drums, bass, etc.)
            color: Ableton palette index
            file_path: absolute Path to the audio file
            rel_path: path relative to the .als file (e.g. "Audio/kick.wav")
        bpm: project tempo
        project_audio_dir: absolute path to the project's Audio/ folder

    Returns:
        Path to the written .als file
    """
    global _NEXT_ID
    _NEXT_ID = 50000

    lines = decompress_als(template_path)
    tracks = find_track_ranges(lines)

    audio_tracks = [t for t in tracks if t["type"] == "AudioTrack"]

    if len(stems) > len(audio_tracks) - 1:
        raise ValueError(
            "Template has " + str(len(audio_tracks)) + " audio tracks but " +
            str(len(stems)) + " stems need tracks (plus Session Time)"
        )

    set_global_tempo(lines, bpm)

    used_track_indices = set()
    used_track_indices.add(0)

    offset = 0
    for stem_idx, stem in enumerate(stems):
        track_idx = stem_idx + 1
        if track_idx >= len(audio_tracks):
            break

        used_track_indices.add(track_idx)
        track = audio_tracks[track_idx]
        track["start"] += offset
        track["end"] += offset
        track["_new_name"] = stem["name"]

        set_track_name(lines, track)
        set_track_color(lines, track, stem["color"])

        sample_count, sample_rate, file_size = get_wav_info(stem["file_path"])
        abs_path = str(stem["file_path"]).replace("\\", "/")
        rel_path = stem["rel_path"].replace("\\", "/")

        regions = stem.get("regions", None)

        clip_name = stem.get("clip_name", stem["name"])
        base_beat = stem.get("base_start_beat", CLIP_START_BEATS)
        inserted = insert_clip_into_track(
            lines, track, clip_name, stem["color"],
            rel_path, abs_path,
            sample_count, sample_rate, file_size, bpm,
            regions=regions, base_start_beat=base_beat
        )
        track["end"] += inserted
        total_inserted = inserted

        # extra_clips = later versions of the same element stacked on this track
        # (radio edit, dub...) placed further down the arrangement.
        for ec in stem.get("extra_clips", []):
            ec_sc, ec_sr, ec_fs = get_wav_info(ec["file_path"])
            ec_abs = str(ec["file_path"]).replace("\\", "/")
            ec_rel = ec["rel_path"].replace("\\", "/")
            n = insert_clip_into_track(
                lines, track, ec.get("clip_name", clip_name), stem["color"],
                ec_rel, ec_abs, ec_sc, ec_sr, ec_fs, bpm,
                regions=ec.get("regions"), base_start_beat=ec["start_beat"]
            )
            track["end"] += n
            total_inserted += n

        offset += total_inserted

    all_tracks_pre = find_track_ranges(lines)
    audio_pre = [t for t in all_tracks_pre if t["type"] == "AudioTrack"]
    for stem_idx, stem in enumerate(stems):
        track_idx = stem_idx + 1
        if track_idx < len(audio_pre) and stem.get("category") not in ("reference", "bus"):
            set_track_lane_height(lines, audio_pre[track_idx], 17)
            set_track_unfolded(lines, audio_pre[track_idx], True)

    # Reference tracks (flat bounce + any supplied ref/riff/master) sit at the
    # bottom as standalone tracks: routed to Ext. Out and muted, so they're
    # there for A/B but don't run through the master chain. No GroupTrack.
    # Group buses sit at the very bottom (below the refs): muted, own colour,
    # routed to Main (unmute one to grab it back) — kept for recall, not summed.
    all_tracks_ref = find_track_ranges(lines)
    audio_ref = [t for t in all_tracks_ref if t["type"] == "AudioTrack"]
    for stem_idx, stem in enumerate(stems):
        cat = stem.get("category")
        tidx = stem_idx + 1
        if tidx >= len(audio_ref):
            continue
        if cat == "reference":
            set_track_output_external(lines, audio_ref[tidx])
            set_track_muted(lines, audio_ref[tidx])
        elif cat == "bus":
            set_track_muted(lines, audio_ref[tidx])

    # Working-track groups: wrap each groupable category with 2+ stems in a
    # GroupTrack (audible, routed to Main, expanded), and optionally nest
    # sub-groups (e.g. a singer under Vox) one level deeper. group_key/
    # subgroup_key are tagged on the working stems by project_builder.
    _apply_track_groups(lines, stems)

    tracks_to_remove = []
    all_tracks = find_track_ranges(lines)
    audio_only = [t for t in all_tracks if t["type"] == "AudioTrack"]
    for i, t in enumerate(audio_only):
        if i not in used_track_indices:
            tracks_to_remove.append((t["start"], t["end"]))

    remove_tracks_by_indices(lines, tracks_to_remove)

    clear_all_selections(lines)
    insert_locators(lines, locators)

    for i, line in enumerate(lines):
        if "<NextPointeeId" in line:
            lines[i] = re.sub(
                r'Value="\d+"',
                'Value="' + str(_NEXT_ID + 1) + '"',
                lines[i]
            )
            break

    compress_als(lines, output_path)
    return output_path
