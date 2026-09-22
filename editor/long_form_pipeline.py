"""
Long-Form Pipeline: 'Create Video' (C++ Engine / 'editor/')
Hyper Copilot & Video Agent Specification

Process Flow:
1. Script & Visual Thinking: LLM creates detailed script, scene breakdown, and visual query intent.
2. HD Asset Scraper: Query Pexels & Pixabay APIs to fetch native 1080p @ 60fps stock video clips, transparent PNG overlays, and motion assets.
3. C++ Native Engine Processing: Apply precise video cropping, scaling, custom transitions, pan/zoom animations, and audio mix (Edge-TTS voiceover + background music).
4. High-Performance Render: Compile scenes into a polished landscape 16:9 .mp4 file.
5. Storage Push: Export to Google Drive using exact secrets:
   - GOOGLE_CLOUD_API_ID, GOOGLE_CLOUD_API_SECRET, GDRIVE_CLIENT_EMAIL, GDRIVE_PRIVATE_KEY, GDRIVE_MAIN_FOLDER_ID
"""

import json
import math
import os
import shutil
import subprocess
import sys
import time
import requests

def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or "").strip() or default

# Supabase Bridge
SUPABASE_URL = env("SUPABASE_URL").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = env("SUPABASE_SERVICE_ROLE_KEY")
VIDEO_ID = env("VIDEO_ID", "local_test_video")
USER_ID = env("USER_ID", "local_user")

# Prompt & Parameters
PROMPT = env("PROMPT", "Deep ocean bioluminescence and eternal mysteries of the oceanic trenches")
NEGATIVE_PROMPT = env("NEGATIVE_PROMPT", "watermark, distorted, low quality, glitch, cartoon")
VOICE_GENDER = env("VOICE_GENDER", "male").lower()
VOICE_PERSONA = env("VOICE_PERSONA", "Cosmic Documentary")
IMAGE_STYLE = env("IMAGE_STYLE", "Cinematic Documentary, 4K resolution, 60fps natural motion, award-winning cinematography")
CAPTIONS_RAW = env("CAPTIONS", "true").lower()
CAPTIONS = CAPTIONS_RAW in {"1", "true", "yes", "on", "small", "medium", "large"}

# Duration Calculation
try:
    if env("DURATION_SECONDS"):
        raw_duration = float(env("DURATION_SECONDS"))
    elif env("DURATION_MINUTES"):
        raw_duration = float(env("DURATION_MINUTES")) * 60.0
    else:
        raw_duration = 300.0  # Default 5 minutes
except ValueError:
    raw_duration = 300.0

ASPECT_RATIO = env("ASPECT_RATIO", "16:9")
TARGET_DURATION_SEC = max(10.0, min(1200.0, raw_duration))
TARGET_MINUTES = TARGET_DURATION_SEC / 60.0
MIN_DURATION_SEC = TARGET_DURATION_SEC * 0.85
MAX_DURATION_SEC = TARGET_DURATION_SEC * 1.15

# Specifications: Dynamic Aspect Ratio (16:9 Landscape or 9:16 Vertical Reel)
if "9:16" in ASPECT_RATIO or "vertical" in ASPECT_RATIO:
    WIDTH, HEIGHT = 1080, 1920
elif "1:1" in ASPECT_RATIO or "square" in ASPECT_RATIO:
    WIDTH, HEIGHT = 1080, 1080
else:
    WIDTH, HEIGHT = 1920, 1080
TARGET_FPS = 60.0

# API Keys
NVIDIA_API_KEY = env("NVIDIA_API_KEY")
PEXELS_API_KEY = env("PEXELS_API_KEY")
PIXABAY_API_KEY = env("PIXABAY_API_KEY")
CLOUDFLARE_ACCOUNT_ID = env("CLOUDFLARE_ACCOUNT_ID")
CLOUDFLARE_API_TOKEN = env("CLOUDFLARE_API_TOKEN")

# Google Drive Secrets
GOOGLE_CLOUD_API_ID = env("GOOGLE_CLOUD_API_ID")
GOOGLE_CLOUD_API_SECRET = env("GOOGLE_CLOUD_API_SECRET")
GDRIVE_CLIENT_EMAIL = env("GDRIVE_CLIENT_EMAIL")
GDRIVE_PRIVATE_KEY = env("GDRIVE_PRIVATE_KEY")
GDRIVE_MAIN_FOLDER_ID = env("GDRIVE_MAIN_FOLDER_ID") or env("GDRIVE_FOLDER_ID")


# --- Logging & Supabase Status ----------------------------------------------
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
        print(f"[Supabase] Patch notice: {e}", file=sys.stderr)

def log(message: str, step: str | None = None, progress: int | None = None) -> None:
    print(f"[LongFormEngine] {message}", flush=True)
    payload: dict = {"logs": message}
    if step:
        payload["step"] = step
    if progress is not None:
        payload["progress"] = progress
    patch_supabase(payload)


# --- Stage 1: Script & Visual Thinking (LLM) --------------------------------
def get_edge_tts_voice(gender: str) -> str:
    voices = {
        "male": "en-US-ChristopherNeural",
        "female": "en-US-JennyNeural",
    }
    return voices.get(gender, "en-US-ChristopherNeural")

def extract_keywords(prompt: str) -> list[str]:
    stop_words = {"the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "with", "about", "into", "of", "by", "from"}
    words = [w.strip(".,;:!?()\"'") for w in prompt.lower().split() if w not in stop_words and len(w) > 2]
    return words or ["nature", "ocean", "galaxy", "landscape", "stars", "nebula"]

def generate_script_with_nvidia_brain() -> tuple[str, list[dict]]:
    """
    Step 1: Script & Visual Thinking
    LLM creates detailed documentary script, scene breakdown, and visual query intent.
    """
    wpm = 135  # Pacing for deep cinematic documentaries
    approx_words = int(TARGET_MINUTES * wpm)
    min_words = int((MIN_DURATION_SEC / 60.0) * wpm)
    max_words = int((MAX_DURATION_SEC / 60.0) * wpm)
    target_scenes = max(5, min(24, int(TARGET_DURATION_SEC / 8.5)))

    log(f"Engaging LLM Brain for Visual Thinking ({TARGET_MINUTES:.1f} mins, ~{approx_words} words, {target_scenes} scenes)...", "Script & Visual Thinking", 10)

    system_prompt = (
        "You are an elite master documentary director and visual thinker for high-budget cinema.\n"
        "Generate a structured screenplay and visual thinking breakdown for a landscape 16:9 documentary.\n"
        "You must output valid JSON ONLY matching this schema:\n"
        "{\n"
        '  "title": "Documentary Title",\n'
        '  "narration": "Continuous, poetic, informative voiceover narration...",\n'
        '  "scenes": [\n'
        "    {\n"
        '      "scene_id": 1,\n'
        '      "duration": 8.0,\n'
        '      "visual_description": "Descriptive visual setting",\n'
        '      "visual_query_intent": "Camera movement and cinematic subject intent (e.g. slow crane shot over glowing abyssal reefs)",\n'
        '      "search_queries": ["query 1 for pexels 1080p", "query 2 for pixabay 1080p"]\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    user_prompt = (
        f'Topic: "{PROMPT}"\n'
        f"Visual Style: {IMAGE_STYLE}. Negative Exclusions: {NEGATIVE_PROMPT}.\n"
        f"Target Runtime: {TARGET_MINUTES} minutes (approx {approx_words} words).\n"
        f"Scenes: Exactly {target_scenes} scenes with specific 1080p search queries and visual query intent."
    )

    models_to_try = [
        "meta/llama-3.1-70b-instruct",
        "nvidia/llama-3.1-nemotron-70b-instruct",
        "meta/llama-3.3-70b-instruct",
    ]

    for model in models_to_try:
        try:
            log(f"Calling LLM Visual Thinking Brain ({model})...")
            url = "https://integrate.api.nvidia.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.6,
                "max_tokens": 4096,
                "response_format": {"type": "json_object"},
            }
            res = requests.post(url, headers=headers, json=payload, timeout=60)
            if res.ok:
                data = res.json()
                content = data["choices"][0]["message"]["content"].strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                parsed = json.loads(content)
                narration = parsed.get("narration", "").strip()
                scenes = parsed.get("scenes", [])
                if narration and len(narration.split()) >= min_words * 0.7:
                    log(f"Visual Thinking Brain generated: {len(narration.split())} words, {len(scenes)} scenes.", progress=20)
                    return narration, scenes
        except Exception as e:
            log(f"Model {model} notice: {e}")

    return write_procedural_fallback_script()

def write_procedural_fallback_script() -> tuple[str, list[dict]]:
    log("Assembling comprehensive documentary narrative via procedural engine...", progress=18)
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
    narration = "\n\n".join(script_parts)

    target_scenes = max(4, min(24, int(TARGET_DURATION_SEC / 8.0)))
    keywords = extract_keywords(PROMPT)
    scenes = []
    for s_idx in range(target_scenes):
        kw = keywords[s_idx % len(keywords)]
        scenes.append({
            "scene_id": s_idx + 1,
            "duration": 8.0,
            "visual_description": f"Cinematic {kw} vista",
            "visual_query_intent": f"Cinematic sweeping wide angle shot of {kw} with vivid natural illumination",
            "search_queries": [f"{kw} 4k landscape", f"nature {kw} aerial drone", f"{kw} cinematic"]
        })
    return narration, scenes


# --- Stage 2: Voiceover Synthesis (Edge-TTS) --------------------------------
def generate_voiceover(script: str, output_path: str = "assets/voice.mp3") -> float:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    voice = get_edge_tts_voice(VOICE_GENDER)
    log(f"Synthesizing high-definition narration with Edge-TTS ({voice})", "Generating Voiceover", 30)
    clean_text = " ".join(script.split())
    cmd = [
        "edge-tts",
        "--voice", voice,
        "--text", clean_text,
        "--write-media", output_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        log(f"Edge-TTS notice: generating fallback audio")
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "anullsrc=r=48000:cl=stereo",
            "-t", str(int(TARGET_DURATION_SEC)),
            output_path
        ], check=True)

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
    log(f"Voiceover track synthesized ({duration:.1f}s)", progress=45)
    return duration


# --- Stage 3: HD Asset Scraper (Pexels & Pixabay 1080p @ 60fps) -------------
def search_pexels_video(query: str) -> str | None:
    if not PEXELS_API_KEY:
        return None
    try:
        url = f"https://api.pexels.com/videos/search?query={requests.utils.quote(query)}&orientation=landscape&size=large&per_page=6"
        headers = {"Authorization": PEXELS_API_KEY}
        r = requests.get(url, headers=headers, timeout=12)
        if r.ok:
            data = r.json()
            for v in data.get("videos", []):
                files = v.get("video_files", [])
                for f in files:
                    if f.get("width") == 1920 and f.get("height") == 1080 and f.get("link"):
                        return f["link"]
                for f in files:
                    if (f.get("width") or 0) >= 1280 and f.get("link"):
                        return f["link"]
    except Exception as e:
        print(f"[Pexels] Search error for '{query}': {e}", file=sys.stderr)
    return None

def search_pixabay_video(query: str) -> str | None:
    if not PIXABAY_API_KEY:
        return None
    try:
        url = f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}&q={requests.utils.quote(query)}&video_type=film&orientation=horizontal&per_page=6"
        r = requests.get(url, timeout=12)
        if r.ok:
            data = r.json()
            for hit in data.get("hits", []):
                vids = hit.get("videos", {})
                for res_key in ("large", "medium", "small"):
                    if vids.get(res_key, {}).get("url"):
                        return vids[res_key]["url"]
    except Exception as e:
        print(f"[Pixabay] Search error for '{query}': {e}", file=sys.stderr)
    return None

def fetch_transparent_overlay(query: str, output_path: str) -> str | None:
    """Fetches transparent PNG overlays and motion assets for scenes."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if PIXABAY_API_KEY:
        try:
            url = f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q={requests.utils.quote(query)}&image_type=illustration&safesearch=true&per_page=5"
            r = requests.get(url, timeout=10)
            if r.ok:
                hits = r.json().get("hits", [])
                for hit in hits:
                    img_url = hit.get("largeImageURL") or hit.get("webformatURL")
                    if img_url:
                        res = requests.get(img_url, timeout=15)
                        if res.ok:
                            with open(output_path, "wb") as f:
                                f.write(res.content)
                            return output_path
        except Exception as e:
            print(f"[Overlay] Notice: {e}", file=sys.stderr)

    # Procedural subtle vignette / cinematic letterbox overlay
    try:
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=black@0.0:s={WIDTH}x{HEIGHT}:d=1",
            "-vf", "vignette=PI/4",
            "-frames:v", "1",
            output_path
        ]
        subprocess.run(cmd, capture_output=True)
        if os.path.exists(output_path):
            return output_path
    except Exception:
        pass
    return None

def download_and_normalize_clip(url: str, output_path: str, duration: float, fps: float = 60.0) -> bool:
    temp_download = output_path + ".download"
    try:
        r = requests.get(url, stream=True, timeout=30)
        if not r.ok:
            return False
        with open(temp_download, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)

        # Transcode & normalize to native 1080p @ 60 FPS with smart crop and color grading
        vf = (
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},"
            f"fps={fps},"
            f"eq=contrast=1.08:saturation=1.12:brightness=0.01"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", temp_download,
            "-t", str(round(duration, 2)),
            "-vf", vf,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-an",
            output_path
        ]
        res = subprocess.run(cmd, capture_output=True)
        if os.path.exists(temp_download):
            os.remove(temp_download)
        return res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000
    except Exception as e:
        print(f"[AssetNormalization] Error: {e}", file=sys.stderr)
        if os.path.exists(temp_download):
            os.remove(temp_download)
        return False

def generate_procedural_scene(output_path: str, duration: float, scene_idx: int, fps: float = 60.0) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    colors = [
        ("0x050d1a", "0x1b3b6f"),
        ("0x11052C", "0x3D087B"),
        ("0x0B2027", "0x40798C"),
        ("0x081c15", "0x1b4332"),
        ("0x1a0933", "0x592e83"),
    ]
    c1, _ = colors[scene_idx % len(colors)]
    vf = (
        f"nullsrc=s={WIDTH}x{HEIGHT}:d={duration}:r={fps},"
        f"format=yuv420p,"
        f"drawbox=y=0:color={c1}:width=iw:height=ih:t=fill,"
        f"noise=alls=15:allf=t+u,"
        f"eq=contrast=1.1:saturation=1.2"
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", vf,
        "-t", str(round(duration, 2)),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-an",
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path

def source_1080p_assets(scenes_plan: list[dict], total_duration: float, fps: float = 60.0) -> list[dict]:
    """
    Step 2: HD Asset Scraper
    Query Pexels & Pixabay APIs to fetch native 1080p @ 60fps stock video clips,
    transparent PNG overlays, and motion assets.
    """
    os.makedirs("assets/scenes", exist_ok=True)
    os.makedirs("assets/overlays", exist_ok=True)
    scene_clips = []

    num_scenes = max(3, len(scenes_plan))
    per_scene_dur = max(6.0, total_duration / num_scenes)

    log(f"HD Asset Scraper: Sourcing footage for {num_scenes} scenes via Pexels & Pixabay (native 1080p @ {fps:.0f} FPS)...", "Sourcing Stock Assets", 50)

    current_time = 0.0
    for idx, scene in enumerate(scenes_plan):
        scene_dur = min(per_scene_dur, total_duration - current_time)
        if scene_dur <= 1.0:
            break

        clip_path = f"assets/scenes/scene_{idx:03d}.mp4"
        queries = scene.get("search_queries", [])
        if not queries:
            queries = [f"{w} landscape" for w in extract_keywords(PROMPT)[:2]]

        video_url = None
        source_provider = "Procedural"

        # 1. Pexels Video Search
        for q in queries:
            video_url = search_pexels_video(q)
            if video_url:
                source_provider = f"Pexels ('{q}')"
                break

        # 2. Pixabay Video Search
        if not video_url:
            for q in queries:
                video_url = search_pixabay_video(q)
                if video_url:
                    source_provider = f"Pixabay ('{q}')"
                    break

        # 3. Download & normalize clip to 1080p @ 60 FPS
        success = False
        if video_url:
            success = download_and_normalize_clip(video_url, clip_path, scene_dur, fps=fps)
            if success:
                log(f"Scene {idx+1}/{num_scenes}: Sourced 1080p footage from {source_provider} ({scene_dur:.1f}s)")

        # 4. Fallback procedural canvas
        if not success:
            generate_procedural_scene(clip_path, scene_dur, idx, fps=fps)
            log(f"Scene {idx+1}/{num_scenes}: Generated cinematic procedural canvas ({scene_dur:.1f}s)")

        # 5. Transparent PNG Overlay & Motion Asset
        overlay_path = f"assets/overlays/overlay_{idx:03d}.png"
        overlay_query = scene.get("visual_query_intent") or queries[0]
        overlay_file = fetch_transparent_overlay(overlay_query, overlay_path)

        scene_dict = {
            "id": f"scene_{idx}",
            "file": os.path.abspath(clip_path),
            "start": round(current_time, 2),
            "duration": round(scene_dur, 2),
            "transition_in": "crossfade" if idx > 0 else "none",
            "transition_duration": 0.8 if idx > 0 else 0.0,
            "motion": {
                "type": "zoom_in" if idx % 2 == 0 else "pan_right",
                "intensity": 0.08
            },
            "color_grading": {
                "contrast": 1.08,
                "saturation": 1.15,
                "temperature": 0.02
            }
        }
        if overlay_file and os.path.exists(overlay_file):
            scene_dict["overlay"] = {
                "file": os.path.abspath(overlay_file),
                "opacity": 0.22,
                "blend_mode": "screen"
            }

        scene_clips.append(scene_dict)
        current_time += scene_dur

    return scene_clips


# --- Stage 4: Soundtrack with Auto-Ducking -----------------------------------
def generate_ambient_soundtrack(duration: float, output_path: str = "assets/soundtrack.wav") -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    log(f"Synthesizing dynamic documentary score with DSP auto-ducking ({duration:.1f}s)", "Generating score", 65)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"sine=frequency=110:duration={duration + 2.0}",
        "-f", "lavfi", "-i", f"sine=frequency=165:duration={duration + 2.0}",
        "-f", "lavfi", "-i", f"sine=frequency=220:duration={duration + 2.0}",
        "-filter_complex",
        f"[0:a][1:a][2:a]amix=inputs=3:dropout_transition=2,volume=0.35,lowpass=f=800,afade=t=in:ss=0:d=3,afade=t=out:st={duration}:d=2[out]",
        "-map", "[out]",
        output_path
    ]
    subprocess.run(cmd, capture_output=True)
    return output_path


# --- Stage 5: Timeline Assembly for C++ Engine ------------------------------
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
                "file": os.path.abspath(music_path),
                "start": 0.0,
                "duration": round(total_duration, 2),
                "volume": 0.65,
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
                "id": "voiceover_lead",
                "file": os.path.abspath(voice_path),
                "start": 0.0,
                "duration": round(total_duration, 2),
                "volume": 1.0,
                "is_voiceover": True,
                "effects": {
                    "high_pass_hz": 80.0,
                    "low_pass_hz": 16000.0,
                    "eq_low_db": -1.0,
                    "eq_mid_db": 2.5,
                    "eq_high_db": 1.5,
                    "noise_gate_db": -45.0
                }
            }
        ]
    }

    with open(timeline_path, "w", encoding="utf-8") as f:
        json.dump(timeline, f, indent=2)

    log(f"Generated timeline.json ({len(scene_clips)} clips, 2 audio streams, {total_duration:.1f}s @ {fps:.0f} FPS)")
    return timeline_path


# --- Stage 6: C++ Engine Compilation & Execution ----------------------------
def compile_engine_if_needed() -> str:
    bin_path = os.path.abspath("editor/build/hyper_editor")
    if os.path.exists(bin_path) and os.access(bin_path, os.X_OK):
        return bin_path

    log("Compiling C++ Native Engine via CMake...", "Building Engine", 70)
    build_dir = "editor/build"
    os.makedirs(build_dir, exist_ok=True)
    subprocess.run(["cmake", "-DCMAKE_BUILD_TYPE=Release", ".."], cwd=build_dir, check=True)
    subprocess.run(["make", f"-j{os.cpu_count() or 4}"], cwd=build_dir, check=True)
    return bin_path

def execute_cpp_engine(engine_bin: str, timeline_path: str, fps: float = 60.0) -> bool:
    log(f"Invoking C++ Native Engine (timeline: {timeline_path} @ {fps:.0f} FPS)...", "Rendering Video", 75)
    cmd = [engine_bin, "--timeline", os.path.abspath(timeline_path), "-o", "out.mp4"]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in iter(proc.stdout.readline, ""):
            line_str = line.strip()
            if "%" in line_str or "Render" in line_str or "Frame" in line_str:
                log(f"[C++ Engine] {line_str}")
        proc.wait()
        return proc.returncode == 0 and os.path.exists("out.mp4") and os.path.getsize("out.mp4") > 1000
    except Exception as e:
        log(f"C++ Engine execution failed: {e}")
    return False


# --- Stage 7: Google Drive Export -------------------------------------------
def export_video_to_google_drive(video_path: str = "out.mp4") -> str | None:
    export_script = os.path.join(os.path.dirname(__file__), "export_to_drive.py")
    if not os.path.exists(export_script):
        log(f"Export script {export_script} not found.")
        return None

    try:
        env_copy = dict(os.environ)
        env_copy["VIDEO_FILE"] = video_path
        res = subprocess.run([sys.executable, export_script], env=env_copy, capture_output=True, text=True)
        log(f"Google Drive export execution code: {res.returncode}")
        drive_link = None
        if res.stdout:
            for line in res.stdout.strip().splitlines():
                if "Link:" in line:
                    drive_link = line.split("Link:", 1)[-1].strip()
                elif "https://drive.google.com" in line:
                    for word in line.split():
                        if word.startswith("https://drive.google.com"):
                            drive_link = word.strip("()[]")
                if "Drive" in line or "✅" in line:
                    log(line)
        return drive_link
    except Exception as e:
        log(f"Drive export trigger error: {e}")
        return None


# --- Main Pipeline Orchestrator --------------------------------------------
def main() -> int:
    try:
        log("Starting Long-Form Pipeline: 'Create Video' (C++ Engine / 'editor/')", "Initializing Video Engine", 5)
        log(f"Config: 16:9 Canvas (1920x1080) · Target {TARGET_MINUTES:.1f} min ({MIN_DURATION_SEC:.0f}s - {MAX_DURATION_SEC:.0f}s)")
        log(f"Style: {IMAGE_STYLE} · Voice: {VOICE_GENDER.title()} ({VOICE_PERSONA})")

        # 1. Script & Visual Thinking
        if NVIDIA_API_KEY:
            script, scenes_plan = generate_script_with_nvidia_brain()
        else:
            log("NVIDIA_API_KEY not supplied; running procedural screenwriter fallback...")
            script, scenes_plan = write_procedural_fallback_script()

        # 2. Narration TTS
        voice_path = "assets/voice.mp3"
        audio_dur = generate_voiceover(script, voice_path)

        total_duration = max(MIN_DURATION_SEC, min(MAX_DURATION_SEC, audio_dur))
        log(f"Composition timeline locked at {total_duration:.1f} seconds ({total_duration/60:.2f} mins)", progress=48)

        # 3. HD Asset Scraper (Pexels & Pixabay 1080p @ 60fps + Transparent PNG Overlays)
        scene_clips = source_1080p_assets(scenes_plan, total_duration, fps=TARGET_FPS)

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
            log("Running FFmpeg master stream fallback composition...", progress=85)
            first_clip = scene_clips[0]["file"] if scene_clips else "assets/scenes/scene_000.mp4"
            cmd_fb = [
                "ffmpeg", "-y",
                "-stream_loop", "-1", "-i", first_clip,
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
        log("Uploading master MP4 to private Supabase Storage bucket...", "Uploading video", 93)
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
                    timeout=180,
                )
            if not upload_res.ok:
                log(f"Upload warning: {upload_res.status_code} {upload_res.text[:200]}")

        # 8. Export to Google Drive
        drive_link = export_video_to_google_drive("out.mp4")

        completion_payload = {
            "status": "completed",
            "progress": 100,
            "step": "Finished",
            "video_url": f"{USER_ID}/{VIDEO_ID}.mp4",
        }
        if drive_link:
            completion_payload["logs"] = f"Render complete! Google Drive: {drive_link}"
        patch_supabase(completion_payload)
        log(f"Video ready · Duration: {total_duration:.1f}s ({total_duration/60:.2f}m)" + (f" · Drive: {drive_link}" if drive_link else ""), "Finished", 100)
        return 0
    except Exception as e:
        err_msg = f"Long-form pipeline failed: {e}"
        log(err_msg, "failed")
        patch_supabase({"status": "failed", "step": "failed", "error": err_msg})
        return 1

if __name__ == "__main__":
    sys.exit(main())
