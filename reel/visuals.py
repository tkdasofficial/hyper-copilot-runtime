"""
Visual quality helpers: perceptual hashes (repetition detection), frame
sampling for vision relevance, shot-type query shaping, colour grades from the
visual bible, and animated infographic scenes (ffmpeg + libass only).
"""
import base64, subprocess
from pathlib import Path

SHOT_MODIFIERS = {
    "establishing": "aerial wide", "wide": "wide shot", "macro": "macro close up", "close-up": "close up",
    "closeup": "close up", "tracking": "tracking shot", "orbital": "orbit rotating", "top-down": "top view",
    "low-angle": "low angle", "reveal": "reveal", "comparison": "", "environmental": "landscape", "timelapse": "timelapse",
}
SHOT_ROTATION = ["establishing", "close-up", "tracking", "macro", "wide", "low-angle", "top-down", "orbital"]

GRADES = {  # ffmpeg eq/colorbalance per visual bible grade (ffmpeg 4.4 compatible)
    "teal_orange": "eq=contrast=1.08:saturation=1.12,colorbalance=rs=0.04:bs=-0.04:rh=0.03:bh=-0.05",
    "cool": "eq=contrast=1.06:saturation=1.05,colorbalance=bs=0.05:bm=0.03:rs=-0.02",
    "warm": "eq=contrast=1.06:saturation=1.1,colorbalance=rs=0.05:rm=0.03:bs=-0.03",
    "moody": "eq=contrast=1.12:saturation=0.9:brightness=-0.03",
    "neutral": "eq=contrast=1.05:saturation=1.08",
}


def grade_filter(bible: dict) -> str:
    return GRADES.get(str((bible or {}).get("grade", "neutral")).lower(), GRADES["neutral"])


def shape_query(q: str, shot: str) -> str:
    mod = SHOT_MODIFIERS.get(str(shot or "").lower(), "")
    return f"{q} {mod}".strip() if mod and mod.split()[0] not in q.lower() else q


def enforce_shot_variety(scenes: list) -> None:
    """No two consecutive scenes share a shot type."""
    prev = None
    for i, sc in enumerate(scenes):
        st = str(sc.get("shot_type") or "").lower() or SHOT_ROTATION[i % len(SHOT_ROTATION)]
        if st == prev:
            st = next(s for s in SHOT_ROTATION if s != prev)
        sc["shot_type"] = st
        prev = st


def _frame(path: Path, kind: str, size: str, at="1") -> bytes:
    pre = ["-ss", at, "-i", str(path)] if kind == "video" else ["-i", str(path)]
    return subprocess.run(["ffmpeg", "-v", "error", *pre, "-frames:v", "1", "-vf", f"scale={size},format=gray",
                           "-f", "rawvideo", "-"], capture_output=True, timeout=30).stdout


def dhash(path: Path, kind: str, at="1"):
    px = _frame(path, kind, "9:8", at=at)
    if len(px) < 72:
        return None
    bits = 0
    for r in range(8):
        for c in range(8):
            bits = (bits << 1) | (1 if px[r * 9 + c] > px[r * 9 + c + 1] else 0)
    return bits


def similarity(a, b) -> float:
    if a is None or b is None:
        return 0.0
    return 1.0 - bin(a ^ b).count("1") / 64.0


def jpeg_b64(path: Path, kind: str, at="1"):
    pre = ["-ss", at, "-i", str(path)] if kind == "video" else ["-i", str(path)]
    r = subprocess.run(["ffmpeg", "-v", "error", *pre, "-frames:v", "1", "-vf", "scale=384:-2", "-q:v", "5",
                        "-f", "image2", "-c:v", "mjpeg", "-"], capture_output=True, timeout=30)
    return base64.b64encode(r.stdout).decode() if r.stdout else None


# ---------------------------------------------------------------- infographics
def _ass_color(hex_rgb: str) -> str:
    h = str(hex_rgb).lstrip("#")
    if len(h) != 6:
        h = "FFD400"
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}&"


def _esc(t) -> str:
    return str(t).replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _t(s):
    m, sec = divmod(max(0.0, s), 60)
    return f"0:{int(m):02d}:{sec:05.2f}"


def infographic_ass(info: dict, dur: float, W: int, H: int, accent="#FFD400", font="Noto Sans") -> str:
    kind = str(info.get("type", "stat")).lower()
    title = _esc(info.get("title", ""))
    items = [i for i in (info.get("items") or []) if str(i.get("value", "")).strip()][:5]
    ac = _ass_color(accent)
    fs_title, fs_big, fs_lab = int(H * 0.046), int(H * 0.11), int(H * 0.042)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: T,{font},{fs_title},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,2,0,1,3,0,8,60,60,{int(H*0.16)},1
Style: Big,{font},{fs_big},{ac},{ac},&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,0,5,40,40,0,1
Style: L,{font},{fs_lab},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,7,0,0,0,1
Style: Bar,{font},10,{ac},{ac},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev, end = [], _t(dur)
    if title:
        ev.append(f"Dialogue: 2,{_t(0)},{end},T,,0,0,0,,{{\\fad(150,100)}}{title.upper()}")
    if kind == "stat" or len(items) <= 1:
        it = items[0] if items else {"value": info.get("title", ""), "label": ""}
        val = _esc(it.get("value", "")) + _esc(it.get("unit", ""))
        lab = _esc(it.get("label", ""))
        ev.append(f"Dialogue: 3,{_t(0.05)},{end},Big,,0,0,0,,{{\\pos({W//2},{int(H*0.45)})\\fscx40\\fscy40\\t(0,260,\\fscx108\\fscy108)\\t(260,380,\\fscx100\\fscy100)}}{val}")
        if lab:
            ev.append(f"Dialogue: 3,{_t(0.3)},{end},T,,0,0,0,,{{\\an5\\pos({W//2},{int(H*0.55)})\\fad(200,0)}}{lab}")
        return head + "\n".join(ev) + "\n"
    nums = []
    for it in items:
        try:
            nums.append(float("".join(ch for ch in str(it.get("value")) if ch.isdigit() or ch == ".") or 0))
        except ValueError:
            nums.append(0)
    top = max(nums) or 1
    y0, row = int(H * 0.30), int(H * 0.11)
    bw_max, x0 = int(W * 0.78), int(W * 0.11)
    for k, it in enumerate(items):
        y = y0 + k * row
        st = 0.15 + k * min(0.35, dur / (len(items) * 3))
        ev.append(f"Dialogue: 3,{_t(st)},{end},L,,0,0,0,,{{\\pos({x0},{y})\\fad(150,0)}}{_esc(it.get('label', ''))}"
                  f"  {{\\c{ac}}}{_esc(it.get('value', ''))}{_esc(it.get('unit', ''))}")
        if kind == "bars":
            bw = max(12, int(bw_max * (nums[k] / top)))
            bh = int(row * 0.28)
            ev.append(f"Dialogue: 2,{_t(st)},{end},Bar,,0,0,0,,{{\\pos({x0},{y + int(fs_lab * 1.35)})\\p1\\fscx0\\t(0,450,\\fscx100)}}"
                      f"m 0 0 l {bw} 0 {bw} {bh} 0 {bh}{{\\p0}}")
    return head + "\n".join(ev) + "\n"


def render_infographic(info: dict, dur: float, W: int, H: int, fps: int, out: Path, work: Path,
                       background=None, bg_kind="video", accent="#FFD400") -> Path:
    ass = work / f"{out.stem}.ass"
    ass.write_text(infographic_ass(info, dur, W, H, accent), encoding="utf-8")
    frames = max(1, round(dur * fps))
    if background is not None:
        inp = (["-stream_loop", "-1", "-i", str(background)] if bg_kind == "video" else ["-loop", "1", "-i", str(background)])
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={fps},"
              f"boxblur=24:2,eq=brightness=-0.28:saturation=0.7,vignette=PI/4,ass={ass},format=yuv420p")
    else:
        inp = ["-f", "lavfi", "-i", f"color=c=0x0b1020:s={W}x{H}:r={fps}"]
        vf = f"noise=alls=6:allf=t,vignette=PI/4,ass={ass},format=yuv420p"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inp, "-frames:v", str(frames), "-vf", vf, "-an", "-r", str(fps),
                    "-c:v", "libx264", "-preset", "fast", "-crf", "17", "-pix_fmt", "yuv420p", str(out)], check=True, timeout=600)
    return out
