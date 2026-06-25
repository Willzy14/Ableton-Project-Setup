"""Pure-stdlib flat reference bounce — sum a set of stems into one stereo WAV.

Used for the flat-reference track at the bottom of the session: a straight,
unprocessed sum of the mix stems (NOT any supplied "ref"/"riff"/master file —
those can't be trusted to equal the stem sum, so we always print our own).

No numpy/scipy — keeps the tool install-free. Audio is mixed in float and
written as 32-bit IEEE-float WAV, so the summed signal is preserved with no
hard clipping (the track is muted and routed to Ext. Out for A/B anyway, so
absolute level is rode on the fader, not baked in).

Mixing is done in 1-second lockstep chunks across all stems at once, so memory
stays flat regardless of how many stems or how long they are.
"""
import struct as _struct
import sys
from array import array
from operator import add
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from als_patcher import _read_wav_header


def _stem_chunk_stereo(f, hdr, n):
    """Read up to n frames from open file f, return interleaved stereo floats.

    Always returns a list of length 2*n (zero-padded if the stem ran out).
    Mono is duplicated to both channels; >2 channels uses the first two.
    """
    bps = hdr["bps"]
    n_ch = hdr["channels"]
    is_float = hdr["fmt"] == 3
    frame_bytes = n_ch * bps
    out = [0.0] * (2 * n)
    raw = f.read(n * frame_bytes)
    got = len(raw) // frame_bytes
    if got == 0:
        return out
    usable = got * frame_bytes

    if is_float and bps == 4:
        vals = _struct.unpack("<%df" % (got * n_ch), raw[:usable])
        norm = 1.0
    elif bps == 2:
        vals = _struct.unpack("<%dh" % (got * n_ch), raw[:usable])
        norm = 32768.0
    elif bps == 4 and not is_float:
        vals = _struct.unpack("<%di" % (got * n_ch), raw[:usable])
        norm = 2147483648.0
    elif bps == 3:
        vals = [0] * (got * n_ch)
        idx = 0
        for k in range(0, usable, 3):
            v = raw[k] | (raw[k + 1] << 8) | (raw[k + 2] << 16)
            if v >= 0x800000:
                v -= 0x1000000
            vals[idx] = v
            idx += 1
        norm = 8388608.0
    else:
        return out

    if n_ch == 1:
        for fr in range(got):
            s = vals[fr] / norm
            out[2 * fr] = s
            out[2 * fr + 1] = s
    else:
        for fr in range(got):
            base = fr * n_ch
            out[2 * fr] = vals[base] / norm
            out[2 * fr + 1] = vals[base + 1] / norm
    return out


def _write_float_wav_header(f, n_frames, sample_rate, channels=2):
    """Write a spec-compliant 32-bit IEEE-float WAV header (fmt + fact)."""
    bits = 32
    block_align = channels * (bits // 8)
    byte_rate = sample_rate * block_align
    data_size = n_frames * block_align
    riff_size = 4 + (8 + 18) + (8 + 4) + (8 + data_size)
    f.write(b"RIFF")
    f.write(_struct.pack("<I", riff_size))
    f.write(b"WAVE")
    f.write(b"fmt ")
    f.write(_struct.pack("<IHHIIHHH", 18, 3, channels, sample_rate,
                         byte_rate, block_align, bits, 0))
    f.write(b"fact")
    f.write(_struct.pack("<II", 4, n_frames))
    f.write(b"data")
    f.write(_struct.pack("<I", data_size))


def sum_stems_to_wav(stem_paths, output_path, chunk_seconds=1.0):
    """Sum stems into one 32-bit float stereo WAV.

    Returns a dict: {path, n_frames, sample_rate, channels, peak, n_summed,
    skipped}. Stems whose sample rate differs from the first are skipped
    (reported in 'skipped') rather than misaligned.
    """
    paths = [Path(p) for p in stem_paths]
    if not paths:
        raise ValueError("no stems to sum")

    headers = [(p, _read_wav_header(p)) for p in paths]
    sr0 = headers[0][1]["rate"]
    included = []
    skipped = []
    for p, hdr in headers:
        if hdr["rate"] != sr0 or hdr["n_frames"] == 0:
            skipped.append(p.name)
        else:
            included.append((p, hdr))
    if not included:
        raise ValueError("no stems share the first stem's sample rate")

    n_frames_out = max(hdr["n_frames"] for _, hdr in included)
    chunk_frames = max(1, int(sr0 * chunk_seconds))
    peak = 0.0

    handles = []
    try:
        for p, hdr in included:
            fh = open(str(p), "rb")
            fh.seek(hdr["data_offset"])
            handles.append((fh, hdr))

        with open(str(output_path), "wb") as out:
            _write_float_wav_header(out, n_frames_out, sr0, channels=2)
            pos = 0
            while pos < n_frames_out:
                n = min(chunk_frames, n_frames_out - pos)
                acc = array("f", bytes(4 * 2 * n))  # zero-filled
                for fh, hdr in handles:
                    sf = _stem_chunk_stereo(fh, hdr, n)
                    acc = array("f", map(add, acc, sf))
                for v in acc:
                    av = v if v >= 0 else -v
                    if av > peak:
                        peak = av
                out.write(_struct.pack("<%df" % len(acc), *acc))
                pos += n
    finally:
        for fh, _ in handles:
            fh.close()

    return {
        "path": Path(output_path),
        "n_frames": n_frames_out,
        "sample_rate": sr0,
        "channels": 2,
        "peak": peak,
        "n_summed": len(included),
        "skipped": skipped,
    }
