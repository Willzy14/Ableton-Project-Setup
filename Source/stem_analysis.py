"""Audio-content analysis for stem classification (numpy-only fallback).

When a filename is ambiguous, analyse the audio to decide what a stem is:
  - a FULL MIX / sub-group bounce (broadband + sustained energy) — must be kept
    OUT of the flat-reference sum or it pollutes the bounce;
  - a KICK (low-frequency-dominant + transient).

The approach is borrowed from the band-energy analysis in Loudness Leveller
(`measure_tonal`) and the low-end detection in Automated DJ Mixes
(`bass_detection`), but implemented with numpy's FFT only so this tool stays
install-free. If numpy is absent, the public helpers return None and the
caller falls back to filename-only classification.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from als_patcher import _read_wav_header

try:
    import numpy as _np
except ImportError:  # pragma: no cover
    _np = None

# Octave-ish analysis bands (Hz).
_BANDS = [(20, 60), (60, 120), (120, 250), (250, 500), (500, 1000),
          (1000, 2000), (2000, 4000), (4000, 8000), (8000, 16000)]
_LOW_HZ = 150.0
_BAND_FLOOR_DB = 25.0   # a band is "active" if within this many dB of the loudest
_SUSTAIN_DB = 30.0      # a frame is "loud" if within this many dB of the peak frame


def _load_mono(wav_path, max_seconds=300.0):
    hdr = _read_wav_header(wav_path)
    sr = hdr["rate"]
    n_ch = hdr["channels"]
    bps = hdr["bps"]
    is_float = hdr["fmt"] == 3
    if sr == 0 or n_ch == 0:
        return None, 0
    n = hdr["n_frames"]
    if max_seconds:
        n = min(n, int(max_seconds * sr))
    with open(str(wav_path), "rb") as f:
        f.seek(hdr["data_offset"])
        raw = f.read(n * n_ch * bps)
    if is_float and bps == 4:
        a = _np.frombuffer(raw, "<f4").astype(_np.float32)
    elif bps == 2:
        a = _np.frombuffer(raw, "<i2").astype(_np.float32) / 32768.0
    elif bps == 4:
        a = _np.frombuffer(raw, "<i4").astype(_np.float32) / 2147483648.0
    elif bps == 3:
        u = _np.frombuffer(raw, _np.uint8)
        m = (u.size // 3) * 3
        u = u[:m].reshape(-1, 3).astype(_np.int32)
        v = u[:, 0] | (u[:, 1] << 8) | (u[:, 2] << 16)
        v = _np.where(v >= 0x800000, v - 0x1000000, v)
        a = v.astype(_np.float32) / 8388608.0
    else:
        return None, sr
    fr = a.size // n_ch
    if fr == 0:
        return None, sr
    return a[:fr * n_ch].reshape(fr, n_ch).mean(axis=1), sr


def analyze_stem(wav_path, max_seconds=300.0):
    """Return content features, or None if numpy is unavailable / unreadable.

    Keys: active_bands (0-9), low_ratio (<150 Hz / total), active_frac (fraction
    of time within 30 dB of peak — sustain), crest (peak/RMS), duration_sec.
    """
    if _np is None:
        return None
    y, sr = _load_mono(wav_path, max_seconds)
    if y is None or y.size < sr // 2:
        return None

    # Averaged power spectrum (Welch-ish).
    win = 8192
    if y.size < win:
        spec = _np.abs(_np.fft.rfft(y * _np.hanning(y.size))) ** 2
        freqs = _np.fft.rfftfreq(y.size, 1.0 / sr)
    else:
        w = _np.hanning(win)
        acc = _np.zeros(win // 2 + 1)
        cnt = 0
        for i in range(0, y.size - win + 1, win):
            acc += _np.abs(_np.fft.rfft(y[i:i + win] * w)) ** 2
            cnt += 1
        spec = acc / max(cnt, 1)
        freqs = _np.fft.rfftfreq(win, 1.0 / sr)

    total = float(spec.sum()) or 1e-12
    band_pow = _np.array([float(spec[(freqs >= lo) & (freqs < hi)].sum())
                          for lo, hi in _BANDS])
    peak_band = float(band_pow.max()) or 1e-12
    active_bands = int(_np.sum(band_pow >= peak_band * 10 ** (-_BAND_FLOOR_DB / 10)))
    low_ratio = float(spec[freqs < _LOW_HZ].sum() / total)

    fr_len = max(1, int(sr * 0.1))
    nfr = y.size // fr_len
    if nfr > 0:
        env = _np.sqrt((y[:nfr * fr_len].reshape(nfr, fr_len) ** 2).mean(axis=1))
        env_peak = float(env.max()) or 1e-12
        active_frac = float(_np.mean(env >= env_peak * 10 ** (-_SUSTAIN_DB / 10)))
    else:
        active_frac = 0.0

    rms = float(_np.sqrt((y ** 2).mean())) or 1e-12
    crest = float(_np.max(_np.abs(y))) / rms
    return {
        "active_bands": active_bands,
        "low_ratio": round(low_ratio, 3),
        "active_frac": round(active_frac, 3),
        "crest": round(crest, 2),
        "duration_sec": round(y.size / sr, 1),
    }


def audio_label(wav_path):
    """Best-effort content label: 'full_mix' or None.

    A full mix / master / sub-bounce is mastered-loud (low crest), sustained
    for the whole arrangement, and broadband. Validated on real packs: every
    real full mix sat at crest <=5 + sustain >=0.85 + 6+ active bands, and
    every individual stem sat above crest 5 — clean separation. (Audio kick
    detection was dropped: kick vs bass overlap too much; filenames handle it.)

    crest<=5 + bands>=6 is the real discriminator (mastered-loud + broadband);
    active_frac>=0.6 is a mild guard against a one-shot that happens to be
    compressed and broadband.
    """
    f = analyze_stem(wav_path)
    if not f:
        return None
    if f["crest"] <= 5.0 and f["active_bands"] >= 6 and f["active_frac"] >= 0.6:
        return "full_mix"
    return None


def find_group_buses(stem_paths, sr_target=3000, max_seconds=180.0,
                     residual_thresh=0.12, min_members=2, min_coef=0.25,
                     return_detail=False):
    """Find stems that are a (near-)exact sum of >=2 OTHER stems — i.e. group
    bus / sub-mix bounces left in among the individual stems.

    Stems are sample-aligned (one session export), so a bus == sum of its
    members in the time domain. For each candidate we run a non-negative greedy
    matching pursuit over the other stems: if a positive-coefficient sum of >=2
    of them reconstructs >=(1-residual_thresh) of the candidate's energy, it's a
    bus. Non-negativity is what flags the bus and not its members (a member
    would need to SUBTRACT the others, which is disallowed).

    Returns a set of bus paths (or, if return_detail, a dict path -> {residual,
    members[]}). Empty without numpy or with <3 stems.
    """
    if _np is None or len(stem_paths) < 3:
        return {} if return_detail else set()

    arrs = []
    for p in stem_paths:
        y, sr = _load_mono(p, max_seconds)
        if y is None or y.size == 0:
            arrs.append(None)
            continue
        factor = max(1, int(round(sr / sr_target)))
        n = (y.size // factor) * factor
        arrs.append(y[:n].reshape(-1, factor).mean(axis=1).astype(_np.float32)
                    if n else None)

    valid = [i for i, a in enumerate(arrs) if a is not None and a.size]
    if len(valid) < 3:
        return {} if return_detail else set()
    L = max(arrs[i].size for i in valid)
    S = _np.zeros((len(arrs), L), dtype=_np.float32)
    for i in valid:
        S[i, :arrs[i].size] = arrs[i]

    G = S @ S.T
    diag = _np.diag(G).copy()
    detail = {}
    for i in valid:
        if diag[i] <= 1e-9:
            continue
        proj = G[i].copy()
        res_e = float(diag[i])
        chosen = []
        for _ in range(24):
            best, best_score = -1, 0.0
            for j in valid:
                if j == i or j in chosen or diag[j] <= 1e-9 or proj[j] <= 0:
                    continue
                score = proj[j] / (diag[j] ** 0.5)
                if score > best_score:
                    best_score, best = score, j
            if best < 0:
                break
            coef = proj[best] / diag[best]
            if coef < min_coef:
                break
            res_e -= coef * proj[best]
            proj = proj - coef * G[best]
            chosen.append(best)
            if res_e / diag[i] < residual_thresh and len(chosen) >= min_members:
                detail[stem_paths[i]] = {
                    "residual": round(max(res_e, 0.0) / diag[i], 3),
                    "members": [Path(stem_paths[m]).name for m in chosen],
                }
                break
    return detail if return_detail else set(detail.keys())


def _main():
    import json
    for p in sys.argv[1:]:
        print(Path(p).name, "->", audio_label(p), json.dumps(analyze_stem(p)))


if __name__ == "__main__":
    _main()
