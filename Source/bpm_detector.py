"""Pure-stdlib BPM detection from an isolated percussive stem (kick preferred).

Algorithm borrowed in spirit from the Automated DJ Mixes project
(attack_onsets + lattice_fit), but adapted to pure Python — no numpy, scipy,
or librosa, so the tool stays install-free. It works here because our stems
arrive already isolated: the DJ project has to run Demucs to separate a kick
out of a full mix first; we skip that entire step and feed the kick stem in.

Method:
  1. Read the stem as a ~1 kHz mean-absolute envelope (rectify + boxcar
     decimate; the averaging doubles as a crude lowpass that favours a kick's
     sustained low-end over the brief spikes of hats/percussion).
  2. Pick attack onsets: threshold at 0.25 * 99th-percentile of the envelope,
     enforce a 250 ms minimum gap, and backtrack each peak to its
     10%-of-peak rising edge (the true attack).
  3. Seed a beat period from the median inter-onset interval, folded into the
     dance range.
  4. Least-squares lattice fit of (first_beat, period) with outlier rejection
     — far more robust than a raw median of intervals.
  5. Fold the result into the dance BPM range and round.

Usage:
    python bpm_detector.py "<kick stem>.wav" ["<another stem>.wav" ...]
"""
import struct as _struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from als_patcher import _read_wav_header

ENV_RATE = 1000          # envelope samples per second (1 ms resolution)
MAX_SECONDS = 120.0      # cap analysis window — 2 min of kicks is plenty
MIN_BPM = 90.0
MAX_BPM = 180.0
MIN_ONSETS = 8           # fewer than this → not enough to trust


def _read_envelope(wav_path, env_rate=ENV_RATE, max_seconds=MAX_SECONDS):
    """Read channel 0 as a rectified, boxcar-decimated envelope.

    Returns (env, env_rate) where env is a list of mean-abs amplitudes
    (normalised to roughly 0..1), one per 1/env_rate seconds.
    """
    hdr = _read_wav_header(wav_path)
    sr = hdr["rate"]
    n_ch = hdr["channels"]
    bps = hdr["bps"]
    is_float = hdr["fmt"] == 3
    frame_bytes = n_ch * bps
    if frame_bytes == 0 or sr == 0:
        return [], env_rate

    n_frames = hdr["n_frames"]
    if max_seconds:
        n_frames = min(n_frames, int(max_seconds * sr))

    hop = max(1, round(sr / env_rate))
    norm = 1.0 if is_float else float(2 ** (bps * 8 - 1))

    with open(str(wav_path), "rb") as f:
        f.seek(hdr["data_offset"])
        data = f.read(n_frames * frame_bytes)

    env = []
    block_bytes = hop * frame_bytes
    total = len(data) - (len(data) % frame_bytes)
    pos = 0
    while pos < total:
        end = min(pos + block_bytes, total)
        s = 0.0
        cnt = 0
        if is_float and bps == 4:
            for fo in range(pos, end - frame_bytes + 1, frame_bytes):
                s += abs(_struct.unpack_from("<f", data, fo)[0])
                cnt += 1
        elif bps == 2:
            for fo in range(pos, end - frame_bytes + 1, frame_bytes):
                s += abs(_struct.unpack_from("<h", data, fo)[0])
                cnt += 1
        elif bps == 3:
            for fo in range(pos, end - frame_bytes + 1, frame_bytes):
                v = data[fo] | (data[fo + 1] << 8) | (data[fo + 2] << 16)
                if v >= 0x800000:
                    v -= 0x1000000
                s += abs(v)
                cnt += 1
        elif bps == 4 and not is_float:
            for fo in range(pos, end - frame_bytes + 1, frame_bytes):
                s += abs(_struct.unpack_from("<i", data, fo)[0])
                cnt += 1
        pos = end
        if cnt:
            env.append((s / cnt) / norm)
    return env, env_rate


def _median(vals):
    if not vals:
        return 0.0
    srt = sorted(vals)
    n = len(srt)
    mid = n // 2
    if n % 2:
        return srt[mid]
    return 0.5 * (srt[mid - 1] + srt[mid])


def _percentile(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    idx = int(round((p / 100.0) * (len(sorted_vals) - 1)))
    idx = min(max(idx, 0), len(sorted_vals) - 1)
    return sorted_vals[idx]


def _smooth(vals, taps):
    """Centred moving average via cumulative sum."""
    if taps <= 1 or len(vals) < 2:
        return list(vals)
    n = len(vals)
    cs = [0.0] * (n + 1)
    for i in range(n):
        cs[i + 1] = cs[i] + vals[i]
    half = taps // 2
    out = [0.0] * n
    for i in range(n):
        a = max(0, i - half)
        b = min(n, i + half + 1)
        out[i] = (cs[b] - cs[a]) / (b - a)
    return out


def _pick_onsets(env, env_rate, min_gap_s=0.25):
    """Threshold, peak-pick with a minimum gap, backtrack to the rising edge."""
    n = len(env)
    if n < 10:
        return []
    sm = _smooth(env, max(1, int(0.005 * env_rate)))
    p99 = _percentile(sorted(sm), 99)
    thresh = 0.25 * p99
    if thresh <= 0:
        return []
    gap = max(1, int(min_gap_s * env_rate))
    back = int(0.08 * env_rate)
    onsets = []
    i = 1
    while i < n - 1:
        if sm[i] >= thresh and sm[i] > sm[i - 1]:
            seg_end = min(n, i + gap)
            peak_i = i
            peak = sm[i]
            for j in range(i, seg_end):
                if sm[j] > peak:
                    peak = sm[j]
                    peak_i = j
            floor = 0.1 * peak
            j = peak_i
            lo = max(0, peak_i - back)
            while j > lo and sm[j] > floor:
                j -= 1
            onsets.append(j / float(env_rate))
            i = peak_i + gap
        else:
            i += 1
    return onsets


def _seed_period(onsets, min_bpm, max_bpm):
    """Median inter-onset interval, folded into the beat-period range."""
    if len(onsets) < 4:
        return None
    diffs = [onsets[k + 1] - onsets[k] for k in range(len(onsets) - 1)]
    med = _median(diffs)
    if med <= 0:
        return None
    lo = 60.0 / max_bpm   # shortest beat period
    hi = 60.0 / min_bpm   # longest beat period
    p = med
    while p < lo:
        p *= 2
    while p > hi:
        p /= 2
    return p


def _linfit(xs, ys):
    """Ordinary least squares: returns (slope, intercept)."""
    n = len(xs)
    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(xs[i] * ys[i] for i in range(n))
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, (sy / n if n else 0.0)
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


def _lattice_fit(onsets, period0, max_iter=4, inlier_s=0.040, keep_s=0.060):
    """Least-squares (first, period) so onsets ~= first + k*period.

    Coarse-centres the phase first, then iterates a tight inlier fit with
    outlier rejection. Returns (first, period, residuals_ms).
    """
    period = float(period0)
    first = float(onsets[0])
    k = [round((t - first) / period) for t in onsets]
    coarse = [onsets[i] - (first + k[i] * period) for i in range(len(onsets))]
    first += _median(coarse)

    keep = list(onsets)
    for _ in range(max_iter):
        kk = []
        tt = []
        for t in keep:
            kr = round((t - first) / period)
            if abs(t - (first + kr * period)) <= inlier_s:
                kk.append(kr)
                tt.append(t)
        if len(kk) < MIN_ONSETS:
            break
        slope, intercept = _linfit(kk, tt)
        if slope <= 0:
            break
        period, first = slope, intercept
        keep = [t for t in keep
                if abs(t - (first + round((t - first) / period) * period)) <= keep_s]

    res = [(t - (first + round((t - first) / period) * period)) * 1000.0
           for t in onsets]
    return first, period, res


def detect_bpm(wav_path, min_bpm=MIN_BPM, max_bpm=MAX_BPM):
    """Detect BPM from an isolated percussive stem.

    Returns a dict with keys: bpm (float, 2dp), bpm_rounded (int),
    period (sec), first_beat_sec (the fitted beat-grid phase — where the kick
    grid starts in the file, used to align later versions to the bar),
    n_onsets, n_inliers, residual_ms. Returns None when there aren't enough
    onsets to trust.
    """
    env, er = _read_envelope(wav_path)
    onsets = _pick_onsets(env, er)
    if len(onsets) < MIN_ONSETS:
        return None
    period0 = _seed_period(onsets, min_bpm, max_bpm)
    if not period0:
        return None
    first, period, res = _lattice_fit(onsets, period0)
    if not period or period <= 0:
        return None

    bpm = 60.0 / period
    while bpm < min_bpm - 1e-9:
        bpm *= 2
    while bpm > max_bpm + 1e-9:
        bpm /= 2

    inliers = [abs(r) for r in res if abs(r) <= 20.0]
    # Where the kick grid starts in the file (its pre-roll). Use the fitted
    # beat-0 directly so the FIRST kick aligns to the bar; fold only if the
    # lattice anchored it absurdly far from the start.
    first_beat_sec = first
    if period and (first_beat_sec < 0 or first_beat_sec > 8 * period):
        first_beat_sec = first % period
    first_beat_sec = max(first_beat_sec, 0.0)
    return {
        "bpm": round(bpm, 2),
        "bpm_rounded": int(round(bpm)),
        "period": period,
        "first_beat_sec": round(first_beat_sec, 4),
        "first_actual_onset_sec": round(onsets[0], 4),
        "n_onsets": len(onsets),
        "n_inliers": len(inliers),
        "residual_ms": round(_median(inliers), 2) if inliers else None,
    }


def _main():
    if len(sys.argv) < 2:
        print("Usage: python bpm_detector.py <stem.wav> [more.wav ...]")
        return 1
    for arg in sys.argv[1:]:
        p = Path(arg)
        try:
            r = detect_bpm(p)
        except Exception as e:  # noqa: BLE001 — surface read/parse errors per file
            print(f"{p.name[:50]:<50}  ERROR: {e}")
            continue
        if r is None:
            print(f"{p.name[:50]:<50}  (too few onsets — not a percussive stem?)")
        else:
            print(f"{p.name[:50]:<50}  {r['bpm_rounded']:>3} BPM "
                  f"(raw {r['bpm']:.2f}, {r['n_inliers']}/{r['n_onsets']} kicks, "
                  f"±{r['residual_ms']}ms)")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
