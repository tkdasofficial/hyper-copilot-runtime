"""Final video QA: format, black/frozen frames, clipping, loudness, gaps, duplicates, duration, fact status."""
import json, re, subprocess
from pathlib import Path


def _ff(args, timeout=600) -> str:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *args, "-f", "null", "-"], capture_output=True, text=True, timeout=timeout)
    return r.stderr


def check(final: Path, cfg, W: int, H: int, fps: int, expected: float, clip_sims: list, verification: list) -> dict:
    issues, warnings = [], []
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(final)],
                                     capture_output=True, text=True).stdout or "{}")
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    dur = float(info.get("format", {}).get("duration", 0) or 0)
    num, _, den = str(v.get("r_frame_rate", "0/1")).partition("/")
    real_fps = round(float(num) / float(den or 1)) if num else 0
    if (v.get("width"), v.get("height")) != (W, H):
        issues.append(f"resolution {v.get('width')}x{v.get('height')} != {W}x{H}")
    if real_fps != fps:
        issues.append(f"fps {real_fps} != {fps}")
    if not a:
        issues.append("no audio track")
    if abs(dur - expected) > 1.0:
        warnings.append(f"duration {dur:.1f}s vs planned {expected:.1f}s")

    log = _ff(["-i", str(final), "-vf", "blackdetect=d=0.25:pix_th=0.06,freezedetect=n=0.001:d=2.5",
               "-af", "volumedetect,silencedetect=n=-45dB:d=1.2"])
    blacks = re.findall(r"black_start:([\d.]+)", log)
    freezes = re.findall(r"freeze_start: ([\d.]+)", log)
    silences = re.findall(r"silence_start: ([\d.]+)", log)
    peak = re.search(r"max_volume: (-?[\d.]+) dB", log)
    mean = re.search(r"mean_volume: (-?[\d.]+) dB", log)
    if blacks:
        issues.append(f"black frames at {', '.join(blacks[:4])}s")
    if freezes:
        warnings.append(f"static section at {', '.join(freezes[:4])}s")
    if [s for s in silences if float(s) < dur - 1.5]:
        warnings.append(f"audio gap at {', '.join(silences[:4])}s")
    peak_db = float(peak.group(1)) if peak else None
    if peak_db is not None and peak_db > -0.3:
        issues.append(f"audio clipping (peak {peak_db} dB)")
    dups = [i for i, s in enumerate(clip_sims) if s >= 0.9]
    if dups:
        warnings.append(f"near-duplicate shots at clips {dups[:6]}")
    unverified = [x["scene"] for x in verification if x["status"] == "unverified"]
    if unverified:
        warnings.append(f"unverified claims in scenes {unverified}")
    return {
        "passed": not issues, "issues": issues, "warnings": warnings,
        "format": {"width": v.get("width"), "height": v.get("height"), "fps": real_fps, "duration": round(dur, 2)},
        "audio": {"peak_db": peak_db, "mean_db": float(mean.group(1)) if mean else None},
        "facts": {"verified": sum(1 for x in verification if x["status"] == "verified"),
                  "single_source": sum(1 for x in verification if x["status"] == "single-source"),
                  "unverified": len(unverified)},
    }
