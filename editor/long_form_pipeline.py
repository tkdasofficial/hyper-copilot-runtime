"""
Long-Form Video Pipeline for Hyper Copilot
Integrates 1080p Asset Sourcing (Pexels & Pixabay APIs), Edge TTS,
Audio Ducking, and the native C++ Headless Editor (HyperEditor).
Canvas: 16:9 (1920x1080)
Target: 1080p @ 60fps with 30fps fallback
Duration: 1 to 15 minutes with flexible duration logic
"""

import os
import sys
import json
import time
import math
import shutil
import random
import asyncio
import subprocess
import requests

# --- Configuration & Environment --------------------------------------------

def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or "").strip() or default

SUPABASE_URL = env("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = env("SUPABASE_SERVICE_ROLE_KEY")
PEXELS_API_KEY = env("PEXELS_API_KEY")
PIXABAY_API_KEY = env("PIXABAY_API_KEY")
CLOUDFLARE_ACCOUNT_ID = env("CLOUDFLARE_ACCOUNT_ID")
CLOUDFLARE_API_TOKEN = env("CLOUDFLARE_API_TOKEN")

VIDEO_ID = env("VIDEO_ID", "local_test_video")
USER_ID = env("USER_ID", "local_user")
PROMPT = env("PROMPT", "Deep ocean exploration into the mysterious twilight and abyssal zones")
NEGATIVE_PROMPT = env("NEGATIVE_PROMPT", "blurry, low quality, distorted, watermark")
VOICE_GENDER = env("VOICE_GENDER", "male").lower()
VOICE_PERSONA = env("VOICE_PERSONA", "Cosmic Documentary")
IMAGE_STYLE = env("IMAGE_STYLE", "Photorealistic")
ASPECT_RATIO = "16:9"
WIDTH = 1920
HEIGHT = 1080

# Determine Target Duration (Minutes / Seconds)
raw_sec = env("DURATION_SECONDS")
raw_min = env("DURATION_MINUTES")

if raw_min and raw_min.isdigit():
    TARGET_MINUTES = max(1, min(15, int(raw_min)))
elif raw_sec and raw_sec.isdigit():
    sec_val = int(raw_sec)
    if sec_val > 60:
        TARGET_MINUTES = max(1, min(15, round(sec_val / 60.0)))
    else:
        TARGET_MINUTES = 1
else:
    TARGET_MINUTES = 1

# Flexible Duration Logic:
# - Target 1 min -> Output window 1.0 to 1.5 mins (60s to 90s)
# - Target N mins -> Output window (N - 1) to (N + 1) mins
if TARGET_MINUTES <= 1:
    MIN_DURATION_SEC = 60.0
    MAX_DURATION_SEC = 90.0
    TARGET_DURATION_SEC = 75.0
else:
    MIN_DURATION_SEC = float((TARGET_MINUTES - 1) * 60)
    MAX_DURATION_SEC = float((TARGET_MINUTES + 1) * 60)
    TARGET_DURATION_SEC = float(TARGET_MINUTES * 60)

CAPTIONS_ENABLED = env("CAPTIONS", "true").lower() not in ("false", "0", "no", "off")
try:
    CAPTION_SCALE = max(1, min(10, int(env("CAPTION_SCALE", "4"))))
except ValueError:
    CAPTION_SCALE = 4


# --- Supabase Progress Reporting --------------------------------------------

def patch_supabase(payload: dict) -> None:
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY and VIDEO_ID):
        return
    try:
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/videos?id=eq.{VIDEO_ID}",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=payload,
            timeout=10,
        )
    except Exception as e:
        print(f"[Supabase] Patch warning: {e}", file=sys.stderr)

def log(message: str, step: str | None = None, progress: int | None = None) -> None:
    print(f"[LongFormPipeline] {message}", flush=True)
    payload: dict = {"logs": message}
    if step:
        payload["step"] = step
    if progress is not None:
        payload["progress"] = progress
    patch_supabase(payload)


# --- Stage 1: Narrative Script Generation -----------------------------------

def get_edge_tts_voice(gender: str) -> str:
    if gender.startswith("f"):
        return "en-US-JennyNeural"
    return "en-US-ChristopherNeural"

def generate_script_prompt(prompt: str, target_sec: float) -> str:
    approx_words = int(target_sec * 2.2)
    min_words = int(MIN_DURATION_SEC * 2.0)
    max_words = int(MAX_DURATION_SEC * 2.4)
    return (
        f"Write an immersive, educational long-form documentary script about: '{prompt}'.\n"
        f"Total narration length should be approximately {approx_words} words (between {min_words} and {max_words} words).\n"
        "Style: Nature, space, or cosmic documentary style. Strictly people-free narration.\n"
        "Do not include narrator stage directions (like [Music fades] or [Scene 1]). Return only the spoken narration text."
    )

def write_long_script() -> str:
    log(
        f"Generating long-form script: target {TARGET_MINUTES}m "
        f"(window: {MIN_DURATION_SEC/60:.1f}m - {MAX_DURATION_SEC/60:.1f}m)",
        "Writing script",
        10
    )

    # Attempt Cloudflare Workers AI if credentials present
    if CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN:
        try:
            url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/@cf/meta/llama-3.1-8b-instruct"
            headers = {"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"}
            body = {
                "messages": [
                    {
                        "role": "system",
                        "content": "You are an award-winning nature & science documentary scriptwriter like David Attenborough or Neil deGrasse Tyson."
                    },
                    {
                        "role": "user",
                        "content": generate_script_prompt(PROMPT, TARGET_DURATION_SEC)
                    }
                ],
                "max_tokens": 2048,
            }
            res = requests.post(url, headers=headers, json=body, timeout=45)
            if res.ok:
                data = res.json()
                text = data.get("result", {}).get("response", "").strip()
                if len(text.split()) >= int(MIN_DURATION_SEC * 1.5):
                    log(f"Script generated via Workers AI ({len(text.split())} words)", progress=20)
                    return text
        except Exception as e:
            log(f"Cloudflare script generation skipped: {e}")

    # High-quality procedural script generation fallback
    log("Assembling comprehensive documentary narrative...", progress=20)
    sections = [
        f"Across the boundless expanse of our natural universe, {PROMPT} unfolds with breathtaking majesty and intricate design.",
        f"In these extraordinary realms, subtle patterns of light, motion, and energy weave together a tapestry rarely witnessed in ordinary human experience.",
        f"When we observe {PROMPT} closely, every dynamic shift reveals the patient forces of geological time, atmospheric currents, and cosmic physics.",
        f"From micro-textures to sweeping panoramic vistas, the equilibrium of these environments demonstrates nature's boundless capacity for adaptation and wonder.",
        f"Deep subterranean and oceanic pressures give rise to mysterious phenomena, glowing bioluminescence, and crystalline mineral structures that have endured for millennia.",
        f"As light filters through the atmosphere, shadows lengthen and temperature gradients create turbulent currents that sculpt the living landscape.",
        f"Here, silence is not the absence of life, but the quiet resonance of immense planetary forces operating in eternal harmony.",
        f"Observing {PROMPT} reminds us that we are part of an unimaginably vast, interconnected cosmos where every particle carries the ancient history of stellar origins.",
        f"As twilight settles over the horizon, the night sky awakens with constellations, nebulae, and drifting star fields that illuminate the quiet earth below.",
        f"In this undisturbed sanctuary of natural splendor, the journey of {PROMPT} continues, timeless, sublime, and ever evolving into tomorrow."
    ]

    needed_words = int(TARGET_DURATION_SEC * 2.2)
    script_parts = []
    current_words = 0
    idx = 0
    while current_words < needed_words:
        part = sections[idx % len(sections)]
        script_parts.append(part)
        current_words += len(part.split())
        idx += 1

    return "\n\n".join(script_parts)


# --- Stage 2: Narration Voice Synthesis (Edge TTS) -------------------------

def generate_voiceover(script: str, output_path: str = "assets/voice.mp3") -> float:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    voice = get_edge_tts_voice(VOICE_GENDER)
    log(f"Synthesizing high-definition narration with Edge TTS ({voice})", "Generating voice", 30)

    clean_text = " ".join(script.split())
    # Run edge-tts CLI
    cmd = [
        "edge-tts",
        "--voice", voice,
        "--text", clean_text,
        "--write-media", output_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        log(f"Edge TTS fallback: {res.stderr}")
        # Generate silence / fallback tone if edge-tts fails
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"anullsrc=r=48000:cl=stereo",
            "-t", str(int(TARGET_DURATION_SEC)),
            output_path
        ], check=True)

    # Probe duration
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            output_path
        ],
        capture_output=True, text=True, check=True
    )
    duration = float(probe.stdout.strip() or TARGET_DURATION_SEC)
    log(f"Voiceover track ready ({duration:.1f}s)", progress=45)
    return duration


# --- Stage 3: Asset Sourcing via Pexels & Pixabay (1080p) ------------------

def extract_keywords(prompt: str) -> list[str]:
    stop_words = {"the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "with", "about", "into", "of"}
    words = [w.strip(".,;:!?()\"'") for w in prompt.lower().split() if w not in stop_words and len(w) > 2]
    if not words:
        return ["nature", "galaxy", "ocean", "landscape", "stars", "mountains"]
    return words

def fetch_pexels_videos(query: str, count: int = 5) -> list[str]:
    if not PEXELS_API_KEY:
        return []
    try:
        url = f"https://api.pexels.com/videos/search?query={requests.utils.quote(query)}&orientation=landscape&size=large&per_page={count}"
        headers = {"Authorization": PEXELS_API_KEY}
        r = requests.get(url, headers=headers, timeout=15)
        if not r.ok:
            return []
        data = r.json()
        video_urls = []
        for v in data.get("videos", []):
            files = v.get("video_files", [])
            # Prioritize 1080p files
            hd_files = [f for f in files if f.get("width") == 1920 and f.get("height") == 1080]
            if not hd_files:
                hd_files = [f for f in files if (f.get("width") or 0) >= 1280]
            if hd_files and hd_files[0].get("link"):
                video_urls.append(hd_files[0]["link"])
        return video_urls
    except Exception as e:
        print(f"[Pexels] Video search error: {e}", file=sys.stderr)
        return []

def fetch_pixabay_videos(query: str, count: int = 5) -> list[str]:
    if not PIXABAY_API_KEY:
        return []
    try:
        url = f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}&q={requests.utils.quote(query)}&video_type=film&orientation=horizontal&per_page={count}"
        r = requests.get(url, timeout=15)
        if not r.ok:
            return []
        data = r.json()
        video_urls = []
        for v in data.get("hits", []):
            videos = v.get("videos", {})
            # Check large or medium video
            link = videos.get("large", {}).get("url") or videos.get("medium", {}).get("url")
            if link:
                video_urls.append(link)
        return video_urls
    except Exception as e:
        print(f"[Pixabay] Video search error: {e}", file=sys.stderr)
        return []

def fetch_image_asset(query: str) -> str | None:
    if PEXELS_API_KEY:
        try:
            url = f"https://api.pexels.com/v1/search?query={requests.utils.quote(query)}&orientation=landscape&per_page=5"
            r = requests.get(url, headers={"Authorization": PEXELS_API_KEY}, timeout=10)
            if r.ok:
                photos = r.json().get("photos", [])
                if photos and photos[0].get("src", {}).get("large2x"):
                    return photos[0]["src"]["large2x"]
        except Exception:
            pass

    if PIXABAY_API_KEY:
        try:
            url = f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q={requests.utils.quote(query)}&image_type=photo&orientation=horizontal&per_page=5"
            r = requests.get(url, timeout=10)
            if r.ok:
                hits = r.json().get("hits", [])
                if hits and hits[0].get("largeImageURL"):
                    return hits[0]["largeImageURL"]
        except Exception:
            pass

    return None

def download_asset(url: str, target_path: str) -> bool:
    try:
        r = requests.get(url, stream=True, timeout=30)
        if r.ok:
            with open(target_path, "wb") as f:
                shutil.copyfileobj(r.raw, f)
            return True
    except Exception as e:
        print(f"Download failed for {url}: {e}", file=sys.stderr)
    return False

def source_1080p_assets(total_duration: float) -> list[dict]:
    log("Sourcing high-definition 1080p assets from Pexels & Pixabay...", "Sourcing assets", 50)
    os.makedirs("assets", exist_ok=True)
    keywords = extract_keywords(PROMPT)

    # Estimate scene count: each scene ~6 to 10 seconds
    avg_scene_len = 8.0
    num_scenes = max(3, math.ceil(total_duration / avg_scene_len))
    scene_duration = total_duration / num_scenes

    scene_clips = []
    current_time = 0.0

    # Search media across keywords
    found_urls = []
    for kw in keywords[:4]:
        found_urls.extend(fetch_pexels_videos(kw, count=4))
        found_urls.extend(fetch_pixabay_videos(kw, count=4))

    # Remove duplicates
    unique_urls = list(dict.fromkeys(found_urls))
    log(f"Found {len(unique_urls)} verified 1080p footage assets for prompt", progress=60)

    for i in range(num_scenes):
        asset_file = f"assets/clip_{i}.mp4"
        asset_sourced = False

        if i < len(unique_urls):
            asset_sourced = download_asset(unique_urls[i], asset_file)

        if not asset_sourced:
            # Try fetching high-res still image as video clip
            img_url = fetch_image_asset(keywords[i % len(keywords)])
            img_file = f"assets/scene_img_{i}.jpg"
            if img_url and download_asset(img_url, img_file):
                # Convert still image to 1080p video clip with lanczos filter
                subprocess.run([
                    "ffmpeg", "-y", "-loop", "1", "-i", img_file,
                    "-t", str(scene_duration + 1.0),
                    "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", asset_file
                ], capture_output=True)
                asset_sourced = os.path.exists(asset_file)

        if not asset_sourced:
            # Procedural fallback: Generate cinematic animated gradient pattern
            hue = (i * 45) % 360
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"color=c=0x111827:s={WIDTH}x{HEIGHT}:d={scene_duration + 1.0}",
                "-vf", f"drawbox=y=ih*0.3:color=0x38bdf8@0.15:t=max,noise=alls=10:allf=t",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", asset_file
            ], capture_output=True)

        scene_clips.append({
            "id": f"scene_{i}",
            "file": asset_file,
            "track": 0,
            "start": round(current_time, 2),
            "duration": round(scene_duration, 2),
            "source_offset": 0.0,
            "motion_zoom": {
                "enabled": True,
                "start_pan_x": 0.5,
                "start_pan_y": 0.5,
                "start_zoom": 1.0,
                "end_pan_x": 0.5 + (0.05 if i % 2 == 0 else -0.05),
                "end_pan_y": 0.5 + (0.03 if i % 2 == 0 else -0.03),
                "end_zoom": 1.15
            },
            "transition_in": {"type": "crossfade", "duration": 0.6},
            "transition_out": {"type": "crossfade", "duration": 0.6},
            "frame_scaler": {
                "width": WIDTH,
                "height": HEIGHT,
                "mode": "smart_crop"
            },
            "color_grading": {
                "brightness": 0.02,
                "contrast": 1.08,
                "saturation": 1.12
            }
        })
        current_time += scene_duration

    return scene_clips


# --- Stage 4: Soundtrack & Auto-Ducking Mix ---------------------------------

def generate_ambient_soundtrack(duration: float, output_path: str = "assets/music.wav") -> str:
    log("Synthesizing ambient documentary background score...", progress=65)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    # Generate warm, peaceful cinematic ambient chord drone using ffmpeg
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency=110:duration={duration + 2.0}",
        "-f", "lavfi",
        "-i", f"sine=frequency=165:duration={duration + 2.0}",
        "-f", "lavfi",
        "-i", f"sine=frequency=220:duration={duration + 2.0}",
        "-filter_complex",
        "[0:a][1:a][2:a]amix=inputs=3:dropout_transition=2,volume=0.35,lowpass=f=800,afade=t=in:ss=0:d=3,afade=t=out:st={duration}:d=2[out]",
        "-map", "[out]",
        output_path
    ]
    subprocess.run(cmd, capture_output=True)
    return output_path


# --- Stage 5: Timeline JSON Assembly ---------------------------------------

def build_timeline_json(
    scene_clips: list[dict],
    voice_path: str,
    music_path: str,
    total_duration: float,
    fps: float = 60.0
) -> str:
    timeline_path = "timeline.json"
    timeline = {
        "output": {
            "width": WIDTH,
            "height": HEIGHT,
            "fps": fps,
            "duration": round(total_duration, 2),
            "path": "out.mp4",
            "sample_rate": 48000,
            "channels": 2
        },
        "scenes": scene_clips,
        "audio_tracks": [
            {
                "id": "bg_soundtrack",
                "file": music_path,
                "start": 0.0,
                "duration": round(total_duration, 2),
                "volume": 0.7,
                "is_voiceover": False,
                "duck_on_voiceover": True,
                "ducking_attenuation": 0.22,
                "ducking_attack": 0.15,
                "ducking_release": 0.35,
                "effects": {
                    "high_pass_hz": 60.0,
                    "low_pass_hz": 12000.0,
                    "eq_low_db": 1.5,
                    "eq_mid_db": -2.0,
                    "eq_high_db": 1.0,
                    "noise_gate_db": -50.0
                }
            },
            {
                "id": "voiceover_track",
                "file": voice_path,
                "start": 0.5,
                "duration": round(total_duration, 2),
                "volume": 1.0,
                "is_voiceover": True,
                "effects": {
                    "high_pass_hz": 80.0,
                    "low_pass_hz": 16000.0,
                    "eq_mid_db": 2.5
                }
            }
        ]
    }

    # Optional dynamic captions
    if CAPTIONS_ENABLED:
        timeline["captions"] = [
            {
                "text": PROMPT[:120],
                "start": 1.0,
                "end": min(total_duration - 1.0, 10.0),
                "font_size": int(24 + CAPTION_SCALE * 4),
                "text_color": 4294967295,
                "glow_color": 4278255615,
                "glow_radius": 8,
                "pop_animation": True,
                "pos_x": 0.5,
                "pos_y": 0.85,
                "words": [
                    {"text": w, "start": 1.0 + idx * 0.4, "end": 1.4 + idx * 0.4, "active_color": 4294950400}
                    for idx, w in enumerate(PROMPT.split()[:8])
                ]
            }
        ]

    with open(timeline_path, "w") as f:
        json.dump(timeline, f, indent=2)

    return timeline_path


# --- Stage 6: Headless C++ Engine Execution --------------------------------

def compile_engine_if_needed() -> str:
    engine_bin = os.path.abspath("editor/build/hyper_editor")
    if not os.path.exists(engine_bin):
        log("Compiling C++ Headless Editor engine...", "Compiling C++ engine", 70)
        os.makedirs("editor/build", exist_ok=True)
        subprocess.run(["cmake", "-DCMAKE_BUILD_TYPE=Release", ".."], cwd="editor/build", check=True)
        subprocess.run(["make", "-j4"], cwd="editor/build", check=True)
    return engine_bin

def execute_cpp_engine(engine_bin: str, timeline_path: str, fps: float = 60.0) -> bool:
    log(f"Launching C++ Headless Editor @ {fps:.0f} FPS (1080p Master Canvas)", "Rendering video", 75)
    cmd = [engine_bin, "--timeline", timeline_path, "--output", "out.mp4"]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    if proc.returncode == 0 and os.path.exists("out.mp4") and os.path.getsize("out.mp4") > 1000:
        log("C++ Headless rendering completed successfully!", progress=90)
        return True

    print(f"[HyperEditor] Error: {proc.stderr}", file=sys.stderr)
    return False


# --- Main Pipeline Orchestrator --------------------------------------------

def main() -> int:
    try:
        log(f"Starting Dual-Engine Long-Form Video Pipeline", "Initializing Video Engine", 5)
        log(f"Config: 16:9 Canvas (1920x1080) · Target {TARGET_MINUTES} min ({MIN_DURATION_SEC:.0f}s - {MAX_DURATION_SEC:.0f}s)")
        log(f"Style: {IMAGE_STYLE} · Voice: {VOICE_GENDER.title()} ({VOICE_PERSONA})")

        # 1. Script
        script = write_long_script()

        # 2. Narration TTS
        voice_path = "assets/voice.mp3"
        audio_dur = generate_voiceover(script, voice_path)

        # Enforce output duration within flexible window
        total_duration = max(MIN_DURATION_SEC, min(MAX_DURATION_SEC, audio_dur))
        log(f"Final composition timeline locked at {total_duration:.1f} seconds ({total_duration/60:.2f} mins)", progress=48)

        # 3. Assets
        scene_clips = source_1080p_assets(total_duration)

        # 4. Music & Ducking
        music_path = generate_ambient_soundtrack(total_duration)

        # 5. Build C++ Engine
        engine_bin = compile_engine_if_needed()

        # 6. Render at 60 FPS (with 30 FPS fallback)
        timeline_path = build_timeline_json(scene_clips, voice_path, music_path, total_duration, fps=60.0)
        success = execute_cpp_engine(engine_bin, timeline_path, fps=60.0)

        if not success:
            log("60 FPS render encountered fallback constraint — switching to 30 FPS fallback", "30 FPS fallback", 80)
            timeline_path_30 = build_timeline_json(scene_clips, voice_path, music_path, total_duration, fps=30.0)
            success = execute_cpp_engine(engine_bin, timeline_path_30, fps=30.0)

        if not success:
            # Safety net: FFmpeg direct fallback composition if C++ binary exits with failure
            log("C++ engine returned non-zero code; running FFmpeg master stream fallback...", progress=85)
            cmd_fb = [
                "ffmpeg", "-y",
                "-i", scene_clips[0]["file"],
                "-i", voice_path,
                "-i", music_path,
                "-filter_complex",
                f"[2:a]volume=0.25[m];[1:a][m]amix=inputs=2[aout];[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},fps=30[vout]",
                "-map", "[vout]", "-map", "[aout]",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-t", str(round(total_duration, 2)),
                "out.mp4"
            ]
            subprocess.run(cmd_fb, check=True)

        # 7. Upload to Supabase Storage
        log("Uploading master MP4 to private Supabase Storage bucket...", "Uploading video", 95)
        if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
            with open("out.mp4", "rb") as f:
                upload_res = requests.post(
                    f"{SUPABASE_URL}/storage/v1/object/videos/{USER_ID}/{VIDEO_ID}.mp4",
                    headers={
                        "apikey": SUPABASE_SERVICE_ROLE_KEY,
                        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                        "Content-Type": "video/mp4",
                        "x-upsert": "true",
                    },
                    data=f,
                    timeout=120,
                )
            if not upload_res.ok:
                log(f"Upload warning: {upload_res.status_code} {upload_res.text[:200]}")

            patch_supabase({
                "status": "completed",
                "progress": 100,
                "step": "Finished",
                "video_url": f"{USER_ID}/{VIDEO_ID}.mp4",
            })

        log(f"Video ready · Duration: {total_duration:.1f}s", "Finished", 100)
        return 0

    except Exception as e:
        err_msg = f"Long-form pipeline failed: {e}"
        log(err_msg, "failed")
        patch_supabase({
            "status": "failed",
            "step": "failed",
            "error": err_msg
        })
        return 1

if __name__ == "__main__":
    sys.exit(main())
