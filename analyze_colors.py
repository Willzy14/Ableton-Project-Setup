"""Deep-dive into track colors and clip colors in ALS files."""
import gzip
import re
from pathlib import Path


def decompress_als(als_path):
    with gzip.open(als_path, "rb") as f:
        content = f.read().decode("utf-8")
    return content.splitlines(keepends=True)


def analyze_all_colors(lines):
    """Extract track-level color and clip-level colors separately."""
    results = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Detect track start
        for tt in ["GroupTrack", "AudioTrack", "ReturnTrack"]:
            if "<" + tt + " " in line:
                track_type = tt
                track_name = ""
                track_color = ""
                clip_colors = set()
                depth = 1
                j = i + 1

                # Walk the track
                while j < len(lines) and depth > 0:
                    tl = lines[j]

                    # Track name (near the top)
                    if "<EffectiveName" in tl and not track_name:
                        m = re.search(r'Value="([^"]*)"', tl)
                        if m:
                            track_name = m.group(1)

                    # Track-level color (appears before DeviceChain, close to EffectiveName)
                    if "<Color Value=" in tl and not track_color and j < i + 30:
                        m = re.search(r'Value="(\d+)"', tl)
                        if m:
                            track_color = m.group(1)

                    # Clip-level color (inside AudioClip)
                    if "<AudioClip " in tl:
                        # Walk inside the clip to find its color
                        k = j + 1
                        clip_depth = 1
                        while k < len(lines) and clip_depth > 0:
                            cl = lines[k]
                            if "<Color Value=" in cl and clip_depth == 1:
                                m = re.search(r'Value="(\d+)"', cl)
                                if m:
                                    clip_colors.add(m.group(1))
                            if "<AudioClip " in cl:
                                clip_depth += 1
                            if "</AudioClip>" in cl:
                                clip_depth -= 1
                            k += 1

                    # Track depth tracking
                    for t2 in ["GroupTrack", "AudioTrack", "ReturnTrack"]:
                        if "<" + t2 + " " in tl and j != i:
                            depth += 1
                        if "</" + t2 + ">" in tl:
                            depth -= 1
                    j += 1

                results.append({
                    "type": track_type,
                    "name": track_name,
                    "track_color": track_color,
                    "clip_colors": clip_colors,
                })
                i = j
                break
        else:
            i += 1

    return results


def main():
    base = Path(r"C:\Users\Carillon\Wired Masters Dropbox\Sam Wills\2.1. Finished Stem Mixes")

    als_files = [
        base / "2. Ongoing Stem Mixes" / "Ak1ra - The Way [Ramzi Karam] Project" / "Ak1ra - The Way [Ramzi Karam].als",
        base / "RILEY - False Reality [Good Company] Project" / "RILEY - False Reality [Good Company].als",
        base / "Stephani B - Activ-8 (Come With Me) [Perfect Havoc] Project" / "Stephani B - Activ-8 (Come With Me) [Perfect Havoc].als",
        base / "Anja - Forest [Magnifik Musik] Project" / "Anja - Forest [Magnifik Musik].als",
        base / "VASSY - Pretty Lady [Vassy] Project" / "VASSY - Pretty Lady [Vassy].als",
    ]

    for als_path in als_files:
        if not als_path.exists():
            print("SKIPPED: " + als_path.name)
            continue

        print("=" * 70)
        print("FILE: " + als_path.name)
        lines = decompress_als(als_path)

        results = analyze_all_colors(lines)
        all_track_colors = set()
        all_clip_colors = set()

        for r in results:
            tc = r["track_color"] or "?"
            cc = ",".join(sorted(r["clip_colors"])) if r["clip_colors"] else "-"
            all_track_colors.add(tc)
            all_clip_colors.update(r["clip_colors"])
            print("  " + r["type"].ljust(12) + " | TrkCol=" + tc.rjust(3) + " | ClipCol=" + cc.ljust(10) + " | " + r["name"])

        print("\n  Unique track colors: " + str(sorted(all_track_colors)))
        print("  Unique clip colors:  " + str(sorted(all_clip_colors)))
        print()


if __name__ == "__main__":
    main()
