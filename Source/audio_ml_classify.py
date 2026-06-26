"""Audio-content classification for stems the filename classifier can't name.

This is the SECOND stage of a cascade. The filename classifier
(`stem_classifier.classify_stems`) runs first and handles everything with a
recognisable name. Only the genuine unknowns (its `unclassified` list) are
passed here, so we never run heavy ML on a stem we already understand.

Method — Demucs as a classifier (not a separator):
    Each stem is fed through htdemucs, which splits it into
    drums / bass / other / vocals. Whichever output bin holds the most energy
    is the stem's identity. `other` maps to our "music" category. If the energy
    is spread across all four bins the stem is probably a full mix / reference.

Whisper runs ONLY on stems that look vocal (Demucs routes energy to the vocals
bin). It transcribes Demucs's isolated vocal track; real words confirm a vocal,
no words means a melodic instrument leaked into the vocal bin -> reclassify to
music. This keeps Whisper off the ~90% of stems that obviously aren't vocals.

Runs on C:\\Python314\\python.exe (torch 2.11+cu128, demucs 4.0.1,
faster-whisper 1.2.1, all GPU-backed on the RTX 3050). Designed to be called as
a subprocess so the CUDA context and any failure stay isolated from the build:

    python audio_ml_classify.py --in paths.json --out result.json
"""
import argparse
import json
import sys
import time

import numpy as np
import soundfile as sf

# Demucs htdemucs source order; index -> our category.
SOURCE_TO_CATEGORY = {
    "drums": "drums",
    "bass": "bass",
    "other": "music",
    "vocals": "vocals",
}

# A stem whose energy fractions all clear MIN_SPREAD with no single bin above
# MAX_DOMINANT looks like a full mix (all four sources present at once).
FULL_MIX_MIN_SPREAD = 0.12
FULL_MIX_MAX_DOMINANT = 0.55

# Run Whisper when the vocals bin is at least this fraction (catches both
# clear vocals and vocal-ish synths we want to rule out).
WHISPER_VOCAL_TRIGGER = 0.22
# Confirmed vocal needs at least this many transcribed words.
WHISPER_MIN_WORDS = 3

SEGMENT_SECONDS = 24.0


def _load_audio(path):
    """Read an audio file as float32 stereo (2, N) plus its sample rate."""
    data, sr = sf.read(path, always_2d=True, dtype="float32")
    wav = data.T  # (channels, samples)
    if wav.shape[0] == 1:
        wav = np.vstack([wav, wav])
    elif wav.shape[0] > 2:
        wav = wav[:2]
    return np.ascontiguousarray(wav), sr


def _loudest_segment(wav, sr, seconds):
    """Return the `seconds`-long window with the most energy (whole clip if shorter)."""
    seg = int(seconds * sr)
    n = wav.shape[1]
    if n <= seg:
        return wav
    mono = wav.mean(axis=0)
    hop = max(1, sr // 10)  # 0.1s resolution
    env = mono * mono
    # Cumulative-sum trick for a fast sliding window over coarse hops.
    cs = np.concatenate([[0.0], np.cumsum(env)])
    best_start, best_e = 0, -1.0
    for start in range(0, n - seg + 1, hop):
        e = cs[start + seg] - cs[start]
        if e > best_e:
            best_e, best_start = e, start
    return wav[:, best_start:best_start + seg]


def _separate(model, wav, device):
    """Run Demucs; return {source_name: float32 (2, N)} on CPU."""
    import torch
    from demucs.apply import apply_model

    t = torch.from_numpy(wav)
    ref = t.mean(0)
    t = (t - ref.mean()) / (ref.std() + 1e-8)
    with torch.no_grad():
        out = apply_model(model, t[None].to(device), split=True,
                          overlap=0.1, device=device)[0]
    out = out.cpu().numpy()
    return {name: out[i] for i, name in enumerate(model.sources)}


def _energy_fractions(stems):
    """Energy fraction per source (scale-invariant, so de-normalising is unneeded)."""
    energies = {name: float(np.sum(s.astype(np.float64) ** 2)) for name, s in stems.items()}
    total = sum(energies.values()) or 1.0
    return {name: e / total for name, e in energies.items()}


def _classify_fractions(fracs):
    """Map energy fractions to (category, confidence, full_mix_like)."""
    top_source = max(fracs, key=fracs.get)
    confidence = fracs[top_source]
    vals = sorted(fracs.values(), reverse=True)
    full_mix_like = (min(fracs.values()) >= FULL_MIX_MIN_SPREAD
                     and vals[0] <= FULL_MIX_MAX_DOMINANT)
    return SOURCE_TO_CATEGORY[top_source], confidence, full_mix_like


def _resample_mono_16k(wav, sr):
    """Average to mono and linearly resample to 16 kHz for Whisper."""
    mono = wav.mean(axis=0).astype(np.float32)
    if sr == 16000:
        return mono
    n_out = int(round(len(mono) * 16000 / sr))
    if n_out <= 1:
        return mono
    x_old = np.linspace(0.0, 1.0, num=len(mono), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, mono).astype(np.float32)


def _whisper_words(vocal_wav, sr, wmodel):
    """Transcribe an isolated vocal stem; return (word_count, text)."""
    audio = _resample_mono_16k(vocal_wav, sr)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 0:
        audio = audio / peak
    segments, _ = wmodel.transcribe(audio, language="en", vad_filter=True,
                                    beam_size=1, no_speech_threshold=0.6)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    words = [w for w in text.split() if any(c.isalpha() for c in w)]
    return len(words), text


def classify_paths(paths, use_whisper=True, seconds=SEGMENT_SECONDS, device=None):
    """Classify each path by audio content. Returns {path: result dict}."""
    import torch
    from demucs.pretrained import get_model

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    model = get_model("htdemucs")
    model.to(device).eval()

    wmodel = None
    if use_whisper:
        try:
            from faster_whisper import WhisperModel
            compute_type = "float16" if device == "cuda" else "int8"
            wmodel = WhisperModel("base", device=device, compute_type=compute_type)
        except Exception as e:
            sys.stderr.write("whisper unavailable, continuing Demucs-only: %r\n" % (e,))
            wmodel = None

    results = {}
    for i, path in enumerate(paths):
        t0 = time.time()
        rec = {"category": None, "confidence": 0.0, "fractions": {},
               "full_mix_like": False, "whisper_words": 0, "whisper_text": "",
               "source": "ml", "error": None}
        try:
            wav, sr = _load_audio(path)
            seg = _loudest_segment(wav, sr, seconds)
            stems = _separate(model, seg, device)
            fracs = _energy_fractions(stems)
            category, confidence, full_mix = _classify_fractions(fracs)
            rec["fractions"] = {k: round(v, 4) for k, v in fracs.items()}
            rec["full_mix_like"] = bool(full_mix)
            rec["confidence"] = round(float(confidence), 4)

            # Whisper only when the stem looks vocal at all.
            if wmodel is not None and fracs.get("vocals", 0.0) >= WHISPER_VOCAL_TRIGGER:
                try:
                    n_words, text = _whisper_words(stems["vocals"], sr, wmodel)
                    rec["whisper_words"] = n_words
                    rec["whisper_text"] = text[:200]
                    if n_words >= WHISPER_MIN_WORDS:
                        # Real lyrics present -> definitely a vocal.
                        category = "vocals"
                    elif (category == "vocals" and n_words == 0
                          and fracs.get("vocals", 0.0) < 0.6):
                        # Demucs leaned vocal but zero words and not dominant
                        # -> a melodic instrument leaking into the vocal bin.
                        category = "music"
                except Exception as e:
                    sys.stderr.write("whisper failed on %s: %r\n" % (path, e))

            rec["category"] = category
            if device == "cuda":
                torch.cuda.empty_cache()
        except Exception as e:
            rec["error"] = repr(e)
            sys.stderr.write("classify failed on %s: %r\n" % (path, e))

        results[path] = rec
        sys.stderr.write("[%d/%d] %.1fs  %s -> %s (conf %.2f%s)\n" % (
            i + 1, len(paths), time.time() - t0, path.rsplit("\\", 1)[-1],
            rec["category"], rec["confidence"],
            ", FULLMIX" if rec["full_mix_like"] else ""))
        sys.stderr.flush()

    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", required=True,
                    help="JSON file: list of stem paths to classify")
    ap.add_argument("--out", dest="out_path", required=True,
                    help="JSON file to write {path: result}")
    ap.add_argument("--no-whisper", action="store_true")
    ap.add_argument("--seconds", type=float, default=SEGMENT_SECONDS)
    ap.add_argument("--device", default=None)
    args = ap.parse_args()

    with open(args.in_path, "r", encoding="utf-8") as fh:
        paths = json.load(fh)

    results = classify_paths(paths, use_whisper=not args.no_whisper,
                             seconds=args.seconds, device=args.device)

    with open(args.out_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)


if __name__ == "__main__":
    main()
