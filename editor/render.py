#!/usr/bin/env python3
"""
Hyper Copilot / Video Agent Engine — Video Renderer
Executes the Script-to-Video Mapper, dynamic visual storyboard generation (12-15+ search queries per 60s),
strict non-looping stock footage fetching, and burned-in karaoke subtitle rendering.
"""

import os
import sys
import json
import math
import time
import random
import asyncio
import subprocess
import requests
from pathlib import Path

def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or "").strip() or default

VIDEO_ID = env("VIDEO_ID", f"vid_{int(time.time())}")
USER_ID = env("USER_ID", "local_user")
PROMPT = env("PROMPT", "Nature and cosmic phenomena")
NEGATIVE_PROMPT = env("NEGATIVE_PROMPT", "blurry, low quality, glitch")
VOICE_GENDER = env("VOICE_GENDER", "male").lower()
ASPECT_RATIO = env("ASPECT_RATIO", "9:16")
RESOLUTION = env("RESOLUTION", "1080p")
FPS = int(env("FPS", "60").replace("FPS", "").strip() or "60")
CAPTIONS = env("CAPTIONS", "true").lower() in ("true", "1", "yes")

raw_dur_sec = env("DURATION_SECONDS")
if raw_dur_sec and raw_dur_sec.isdigit() and int(raw_dur_sec) > 0:
    TOTAL_DURATION = int(raw_dur_sec)
else:
    TOTAL_DURATION = 15 if ASPECT_RATIO == "9:16" else 60

# Caption size parsing
raw_caption_scale = env("CAPTION_SCALE", "4")
raw_caption_size = env("CAPTION_SIZE", "")
if raw_caption_size.lower() in ("small", "medium", "large"):
    CAPTION_SIZE = raw_caption_size.capitalize()
elif raw_caption_scale == "2":
    CAPTION_SIZE = "Small"
elif raw_caption_scale == "6":
    CAPTION_SIZE = "Large"
else:
    CAPTION_SIZE = "Medium"

CAPTION_STYLE = env("CAPTION_STYLE", "Dynamic").capitalize()

PEXELS_API_KEY = env("PEXELS_API_KEY")
PIXABAY_API_KEY = env("PIXABAY_API_KEY")
CLOUDFLARE_ACCOUNT_ID = env("CLOUDFLARE_ACCOUNT_ID")
CLOUDFLARE_API_TOKEN = env("CLOUDFLARE_API_TOKEN")
SUPABASE_URL = env("SUPABASE_URL").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = env("SUPABASE_SERVICE_ROLE_KEY")

if ASPECT_RATIO == "9:16":
    TARGET_WIDTH = 1080 if "1080" in RESOLUTION else 720
    TARGET_HEIGHT = 1920 if "1080" in RESOLUTION else 1280
else:
    TARGET_WIDTH = 1920 if "1080" in RESOLUTION else 1280
    TARGET_HEIGHT = 1080 if "1080" in RESOLUTION else 720

WORKDIR = Path(f"/tmp/video_agent_{VIDEO_ID}")
WORKDIR.mkdir(parents=True, exist_ok=True)
ASSETS_DIR = WORKDIR / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

def update_supabase(progress: int, step: str, status: str = "processing"):
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        return
    try:
        url = f"{SUPABASE_URL}/rest/v1/videos?id=eq.{VIDEO_ID}"
        headers = {
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        data = {"status": status, "step": step, "progress": progress}
        requests.patch(url, headers=headers, json=data, timeout=5)
    except Exception as e:
        print(f"[Supabase] Progress error: {e}", file=sys.stderr)

def generate_storyboard(prompt: str, total_duration: int) -> list:
    """12-15 distinct keyword search terms for 60s video, 3-5 seconds per scene."""
    target_dur = 4.0
    num_scenes = max(15, math.ceil(total_duration / target_dur)) if total_duration >= 45 else max(4, math.ceil(total_duration / 3.5))
    
    base_keywords = [
        ("deep ocean hydrothermal vent bubbling water cinematic macro", "deep sea glowing bioluminescent jellyfish"),
        ("macro coral reef glowing sunbeams underwater", "exotic tropical sea turtles gliding ocean"),
        ("majestic manta ray swimming clear blue water", "giant humpback whale breaching open ocean"),
        ("ancient geological rock strata canyon aerial", "dramatic volcanic lava flow night cinematic"),
        ("starry nebula cosmic galaxy hubble telescope", "deep space telescope distant star cluster"),
        ("dense foggy misty pine forest morning sun", "sunlight breaking through forest canopy trees"),
        ("cascading waterfall lush green jungle aerial 4k", "crystal clear mountain river stream stones"),
        ("snowy mountain peak clouds timelapse 4k", "cinematic glacier ice breaking ocean arctic"),
        ("northern lights aurora borealis starry night sky", "glowing green aurora reflections calm lake"),
        ("mysterious underwater submarine searchlights", "deep ocean floor rover exploration robotic"),
        ("stormy ocean waves crashing dark cliff rock", "turbulent stormy sea waves dramatic lighting"),
        ("vibrant jellyfish drifting glowing dark water", "microscopic plankton glowing marine biology"),
        ("golden sunset over vast calm open ocean", "coastal shoreline waves receding golden hour"),
        ("desert sand dunes shifting wind aerial cinematic", "vast arid desert landscape sunset rocks"),
        ("sparkling galaxy cosmic dust nebula deep cosmos", "supernova explosion concept astronomy 4k")
    ]

    prompt_words = [w for w in prompt.lower().replace(",", " ").split() if len(w) > 3 and w not in ("about", "video", "documentary", "short", "epic", "reel")]
    scenes = []
    accum_time = 0.0
    clip_dur = total_duration / num_scenes

    for i in range(num_scenes):
        start_t = accum_time
        end_t = min(total_duration, accum_time + clip_dur) if i < num_scenes - 1 else total_duration
        actual_dur = end_t - start_t
        accum_time = end_t

        kw_pair = base_keywords[i % len(base_keywords)]
        if prompt_words:
            p_tag = prompt_words[i % len(prompt_words)]
            primary = f"{p_tag} {kw_pair[0]}"
            secondary = f"{p_tag} {kw_pair[1]}"
        else:
            primary = kw_pair[0]
            secondary = kw_pair[1]

        scenes.append({
            "index": i,
            "start_time": round(start_t, 2),
            "end_time": round(end_t, 2),
            "duration": round(actual_dur, 2),
            "primary_query": primary,
            "secondary_query": secondary,
            "narration": f"Journeying into the depths of {primary} and unraveling hidden wonders.",
            "transition": "fade"
        })

    return scenes

async def synthesize_narration(full_script: str, out_file: Path) -> list:
    voice = "en-US-ChristopherNeural" if VOICE_GENDER == "male" else "en-US-JennyNeural"
    word_timings = []
    try:
        import edge_tts
        communicate = edge_tts.Communicate(full_script, voice)
        with open(out_file, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    st = chunk["offset"] / 10000000.0
                    dur = chunk["duration"] / 10000000.0
                    word_timings.append({
                        "word": chunk["text"],
                        "start_time": round(st, 3),
                        "end_time": round(st + dur, 3)
                    })
        return word_timings
    except Exception:
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(TOTAL_DURATION), "-q:a", "9", "-acodec", "libmp3lame", str(out_file)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        words = full_script.split()
        if words:
            wd = TOTAL_DURATION / len(words)
            for idx, w in enumerate(words):
                word_timings.append({"word": w, "start_time": round(idx * wd, 3), "end_time": round((idx + 0.9) * wd, 3)})
        return word_timings

USED_VIDEOS = set()

def fetch_clip(query: str, orientation: str) -> dict | None:
    if PEXELS_API_KEY:
        try:
            r = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": PEXELS_API_KEY},
                params={"query": query, "orientation": "portrait" if orientation == "9:16" else "landscape", "per_page": 8},
                timeout=10
            )
            if r.ok:
                for v in r.json().get("videos", []):
                    vid = f"pexels_{v.get('id')}"
                    if vid not in USED_VIDEOS:
                        USED_VIDEOS.add(vid)
                        files = v.get("video_files", [])
                        files.sort(key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
                        for f in files:
                            if f.get("link") and f.get("file_type") == "video/mp4":
                                return {"url": f["link"], "duration": float(v.get("duration", 5.0))}
        except Exception:
            pass

    if PIXABAY_API_KEY:
        try:
            r = requests.get("https://pixabay.com/api/videos/", params={"key": PIXABAY_API_KEY, "q": query, "per_page": 8}, timeout=10)
            if r.ok:
                for hit in r.json().get("hits", []):
                    vid = f"pixabay_{hit.get('id')}"
                    if vid not in USED_VIDEOS:
                        USED_VIDEOS.add(vid)
                        vids = hit.get("videos", {})
                        chosen = vids.get("large") or vids.get("medium")
                        if chosen and chosen.get("url"):
                            return {"url": chosen["url"], "duration": float(hit.get("duration", 5.0))}
        except Exception:
            pass

    return None

def acquire_scene_clips(scene: dict, s_idx: int) -> list:
    needed = scene["duration"]
    clips = []
    filled = 0.0
    sub = 0

    while filled < needed - 0.05:
        rem = needed - filled
        q = scene["primary_query"] if sub == 0 else scene["secondary_query"]
        clip_path = ASSETS_DIR / f"clip_{s_idx}_{sub}.mp4"
        info = fetch_clip(q, ASPECT_RATIO)

        if info:
            try:
                with requests.get(info["url"], stream=True, timeout=25) as res:
                    res.raise_for_status()
                    with open(clip_path, "wb") as f:
                        for chunk in res.iter_content(chunk_size=65536):
                            f.write(chunk)
                # Check duration
                probe = subprocess.run([
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(clip_path)
                ], stdout=subprocess.PIPE, text=True)
                actual_dur = float(probe.stdout.strip())
            except Exception:
                actual_dur = 5.0

            use_dur = min(rem, actual_dur)
            clips.append({"file": str(clip_path), "duration": round(use_dur, 2), "trim_start": 0.0})
            filled += use_dur
            if actual_dur < rem:
                print(f"[Strict No-Looping] Clip is shorter than segment ({actual_dur:.1f}s < {rem:.1f}s). Fetching secondary distinct clip!")
        else:
            # Procedural visual fallback
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"color=c=0x101b2a:s={TARGET_WIDTH}x{TARGET_HEIGHT}:d={rem}:r={FPS}",
                "-vf", f"drawtext=font='DejaVu Sans':text='{q[:25]}':fontsize=36:fontcolor=white@0.2:x=(w-text_w)/2:y=(h-text_h)/2",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(clip_path)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            clips.append({"file": str(clip_path), "duration": round(rem, 2), "trim_start": 0.0})
            filled += rem

        sub += 1

    return clips

def write_karaoke_ass(word_timings: list, ass_file: Path):
    if ASPECT_RATIO == "9:16":
        font_size = 48 if CAPTION_SIZE == "Small" else (96 if CAPTION_SIZE == "Large" else 72)
        margin_v = int(TARGET_HEIGHT * 0.18)
    else:
        font_size = 28 if CAPTION_SIZE == "Small" else (56 if CAPTION_SIZE == "Large" else 42)
        margin_v = int(TARGET_HEIGHT * 0.08)

    outline = 4 if TARGET_HEIGHT >= 1080 else 3
    highlight_color = "&H0000E6FF" if CAPTION_STYLE == "Dynamic" else "&H0000FFFF"

    def fmt_t(sec: float) -> str:
        sec = max(0.0, sec)
        cs = int(round(sec * 100)) % 100
        tot_s = int(sec)
        return f"{tot_s // 3600}:{(tot_s % 3600) // 60:02d}:{tot_s % 60:02d}.{cs:02d}"

    header = f"""[Script Info]
Title: Hyper Copilot Dynamic Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {TARGET_WIDTH}
PlayResY: {TARGET_HEIGHT}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,{font_size},&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},2,2,30,30,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for i in range(0, len(word_timings), 4):
        chunk = word_timings[i:i+4]
        for w_idx, active_w in enumerate(chunk):
            w_start = active_w["start_time"]
            w_end = max(w_start + 0.25, active_w["end_time"])
            line_text = "{\\an2}"
            for c_idx, w in enumerate(chunk):
                word_str = w["word"]
                if c_idx == w_idx:
                    line_text += f"{{\\c{highlight_color}}}{{\\b1}}{word_str}{{\\b0}}{{\\c&H00FFFFFF&}} "
                elif c_idx < w_idx:
                    line_text += f"{{\\c&H00FFFFFF&}}{word_str} "
                else:
                    line_text += f"{{\\c&H00C0C0C0&}}{word_str}{{\\c&H00FFFFFF&}} "
            lines.append(f"Dialogue: 0,{fmt_t(w_start)},{fmt_t(w_end)},Default,,0,0,0,,{line_text.strip()}\n")

    with open(ass_file, "w", encoding="utf-8") as f:
        f.writelines(lines)

async def main():
    print(f"[Render] Video Agent starting. Target duration: {TOTAL_DURATION}s, Resolution: {TARGET_WIDTH}x{TARGET_HEIGHT}")
    update_supabase(10, "Writing storyboard & keyword queries")
    storyboard = generate_storyboard(PROMPT, TOTAL_DURATION)
    full_script = " ".join([s["narration"] for s in storyboard])

    update_supabase(25, "Synthesizing voiceover")
    audio_path = WORKDIR / "narration.mp3"
    word_timings = await synthesize_narration(full_script, audio_path)

    update_supabase(40, "Acquiring stock footage (Strict No-Looping)")
    all_clips = []
    for s_idx, scene in enumerate(storyboard):
        clips = acquire_scene_clips(scene, s_idx)
        all_clips.extend(clips)

    captions_path = WORKDIR / "captions.ass"
    if CAPTIONS:
        update_supabase(65, "Rendering karaoke subtitles")
        write_karaoke_ass(word_timings, captions_path)

    update_supabase(80, "Building filter graph & burning captions")
    # Build filter complex
    fc_parts = []
    for i, c in enumerate(all_clips):
        fc_parts.append(
            f"[{i}:v]trim=start=0:duration={c['duration']},setpts=PTS-STARTPTS,"
            f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={TARGET_WIDTH}:{TARGET_HEIGHT},setsar=1,fps={FPS},format=yuv420p[v{i}];"
        )
    curr = "[v0]"
    if len(all_clips) > 1:
        accum = all_clips[0]["duration"]
        for i in range(1, len(all_clips)):
            td = 0.4
            offset = max(0.1, accum - td)
            nxt = f"[vx{i}]"
            fc_parts.append(f"{curr}[v{i}]xfade=transition=fade:duration={td:.2f}:offset={offset:.2f}{nxt};")
            curr = nxt
            accum = offset + all_clips[i]["duration"]

    if CAPTIONS and captions_path.exists():
        escaped = str(captions_path).replace(":", "\\:").replace("'", "\\'")
        fc_parts.append(f"{curr}ass='{escaped}'[vout]")
    else:
        fc_parts.append(f"{curr}copy[vout]")

    cmd = ["ffmpeg", "-y"]
    for c in all_clips:
        cmd.extend(["-i", c["file"]])
    cmd.extend(["-i", str(audio_path)])
    cmd.extend([
        "-filter_complex", "".join(fc_parts),
        "-map", "[vout]",
        "-map", f"{len(all_clips)}:a:0",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-shortest", "out.mp4"
    ])
    subprocess.run(cmd, check=True)
    update_supabase(95, "Video rendered successfully")
    print("[Render] Complete! Output saved to out.mp4")

if __name__ == "__main__":
    asyncio.run(main())
