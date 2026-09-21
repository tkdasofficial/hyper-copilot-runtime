"""
Long-Form Video Pipeline for Hyper Copilot.
Orchestrates:
1. Brain: NVIDIA API Key (NVIDIA NIM - meta/llama-3.1-70b-instruct) for documentary scriptwriting & scene planning
2. Stock Footages: Pexels & Pixabay APIs for 1080p video sourcing
3. Audio: Edge-TTS narration & ambient soundtrack with DSP Auto-Ducking
4. Editor: Native C++ Headless Editor (HyperEditor) for 1080p @ 60fps rendering
5. Export: Direct Google Drive export & Supabase video status streaming
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
NVIDIA_API_KEY = env("NVIDIA_API_KEY")
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

# --- Stage 1: Narrative Brain (NVIDIA API / NIM) ----------------------------
def get_edge_tts_voice(gender: str) -> str:
    if gender.startswith("f"):
        return "en-US-JennyNeural"
    return "en-US-ChristopherNeural"

def generate_script_with_nvidia_brain() -> tuple[str, list[dict]]:
    """
    Uses NVIDIA NIM API as the director brain to generate:
    1. Documentary voiceover narration script matching target duration.
    2. Scene-by-scene breakdown with targeted Pexels & Pixabay search queries.
    """
    approx_words = int(TARGET_DURATION_SEC * 2.2)
    min_words = int(MIN_DURATION_SEC * 2.0)
    max_words = int(MAX_DURATION_SEC * 2.4)
    target_scenes = max(4, min(30, int(TARGET_DURATION_SEC / 8.0)))

    log(f"Consulting NVIDIA AI Brain for documentary blueprint ({approx_words} words, ~{target_scenes} scenes)...", "Writing script", 10)

    system_prompt = (
        "You are an award-winning cinematic documentary director, screenwriter, and visual curator. "
        "You produce world-class nature, cosmic, and science documentaries without humans or talking heads. "
        "Your output must be strictly valid JSON with no preamble or markdown wrappers."
    )

    user_prompt = f"""Create a comprehensive long-form documentary plan.
Topic: "{PROMPT}"
Visual Style: {IMAGE_STYLE}. Exclude: {NEGATIVE_PROMPT}.
Target Runtime: {TARGET_MINUTES} minutes (duration window: {MIN_DURATION_SEC/60:.1f} to {MAX_DURATION_SEC/60:.1f} minutes).
Target Narration Words: approximately {approx_words} words (minimum {min_words}, maximum {max_words} words).

Provide your response as a valid JSON object strictly matching this schema:
{{
  "title": "Documentary Title",
  "narration": "Full, uninterrupted, poetic documentary voiceover narration...",
  "scenes": [
    {{
      "scene_id": 1,
      "duration": 8.0,
      "visual_description": "Descriptive visual",
      "search_queries": ["query 1 for pexels", "query 2 for pixabay"]
    }}
  ]
}}
Ensure the 'scenes' array has approximately {target_scenes} distinct scenes covering the entire narrative arc.
The 'search_queries' for each scene must be highly specific English terms optimized for stock video search (e.g. 'deep ocean hydrothermal vent 4k', 'nebula cosmic stars timelapse').
"""

    models_to_try = [
        "meta/llama-3.1-70b-instruct",
        "nvidia/llama-3.1-nemotron-70b-instruct",
        "meta/llama-3.3-70b-instruct",
        "meta/llama-3.1-8b-instruct",
    ]

    for model in models_to_try:
        try:
            log(f"Calling NVIDIA NIM Brain ({model})...")
            url = "https://integrate.api.nvidia.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {NVIDIA_API_KEY}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
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
                # Clean potential markdown wrapping
                if content.startswith("```"):
                    content = content.split("\n", 1)[-1]
                    if content.endswith("```"):
                        content = content.rsplit("```", 1)[0]
                    content = content.strip()

                parsed = json.loads(content)
                narration = parsed.get("narration", "").strip()
                scenes = parsed.get("scenes", [])
                if narration and len(narration.split()) >= min_words * 0.7:
                    log(f"NVIDIA Brain successfully generated screenplay: {len(narration.split())} words, {len(scenes)} scenes.", progress=20)
                    return narration, scenes
        except Exception as e:
            log(f"NVIDIA model {model} attempt notice: {e}")

    # Fallback if NVIDIA API is not configured or fails
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
    # Generate procedural scenes
    target_scenes = max(4, min(24, int(TARGET_DURATION_SEC / 8.0)))
    keywords = extract_keywords(PROMPT)
    scenes = []
    for s_idx in range(target_scenes):
        kw = keywords[s_idx % len(keywords)]
        scenes.append({
            "scene_id": s_idx + 1,
            "duration": 8.0,
            "visual_description": f"Cinematic {kw} vista",
            "search_queries": [f"{kw} 4k landscape", f"nature {kw} aerial drone", f"{kw} cinematic cinematic"]
        })
    return narration, scenes

# --- Stage 2: Narration Voice Synthesis (Edge TTS) -------------------------
def generate_voiceover(script: str, output_path: str = "assets/voice.mp3") -> float:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    voice = get_edge_tts_voice(VOICE_GENDER)
    log(f"Synthesizing high-definition narration with Edge TTS ({voice})", "Generating voice", 30)

    clean_text = " ".join(script.split())
    cmd = [
        "edge-tts",
        "--voice", voice,
        "--text", clean_text,
        "--write-media", output_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        log(f"Edge TTS fallback triggered: {res.stderr}")
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"anullsrc=r=48000:cl=stereo",
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

# --- Stage 3: Stock Footage Sourcing (Pexels & Pixabay 1080p) ---------------
def extract_keywords(prompt: str) -> list[str]:
    stop_words = {"the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "with", "about", "into", "of"}
    words = [w.strip(".,;:!?()\"'") for w in prompt.lower().split() if w not in stop_words and len(w) > 2]
    return words or ["nature", "galaxy", "ocean", "landscape", "stars", "nebula"]

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
                # 1. Look for exact 1080p
                for f in files:
                    if f.get("width") == 1920 and f.get("height") == 1080 and f.get("link"):
                        return f["link"]
                # 2. Look for any HD file (1280+)
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

def download_and_normalize_clip(url: str, output_path: str, duration: float, fps: float = 60.0) -> bool:
    temp_download = output_path + ".download"
    try:
        r = requests.get(url, stream=True, timeout=30)
        if not r.ok:
            return False
        with open(temp_download, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)

        # Transcode & normalize to exact 1920x1080 @ target fps with color grading
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
    c1, c2 = colors[scene_idx % len(colors)]
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
    os.makedirs("assets/scenes", exist_ok=True)
    scene_clips = []
    
    # Calculate scene distribution
    num_scenes = max(3, len(scenes_plan))
    per_scene_dur = max(6.0, total_duration / num_scenes)
    
    log(f"Sourcing stock footage for {num_scenes} scenes via Pexels & Pixabay (1080p @ {fps:.0f} FPS)...", "Sourcing stock footage", 50)
    
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
        
        # 1. Try Pexels Video Search with queries
        for q in queries:
            video_url = search_pexels_video(q)
            if video_url:
                source_provider = f"Pexels ('{q}')"
                break
                
        # 2. Try Pixabay Video Search if not found
        if not video_url:
            for q in queries:
                video_url = search_pixabay_video(q)
                if video_url:
                    source_provider = f"Pixabay ('{q}')"
                    break

        # 3. Download and normalize clip
        success = False
        if video_url:
            success = download_and_normalize_clip(video_url, clip_path, scene_dur, fps=fps)
            if success:
                log(f"Scene {idx+1}/{num_scenes}: Sourced 1080p footage from {source_provider} ({scene_dur:.1f}s)")

        # 4. Fallback if stock footage download failed
        if not success:
            generate_procedural_scene(clip_path, scene_dur, idx, fps=fps)
            log(f"Scene {idx+1}/{num_scenes}: Generated cinematic procedural canvas ({scene_dur:.1f}s)")

        scene_clips.append({
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
        })
        current_time += scene_dur

    return scene_clips

# --- Stage 4: Soundtrack with Auto-Ducking -----------------------------------
def generate_ambient_soundtrack(duration: float, output_path: str = "assets/soundtrack.wav") -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    log(f"Synthesizing dynamic documentary ambient score with DSP auto-ducking ({duration:.1f}s)", "Generating score", 65)
    
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"sine=frequency=110:duration={duration + 2.0}",
        "-f", "lavfi",
        "-i", f"sine=frequency=165:duration={duration + 2.0}",
        "-f", "lavfi",
        "-i", f"sine=frequency=220:duration={duration + 2.0}",
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
                "file": os.path.abspath(voice_path),
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
        log("Compiling native C++ Headless Editor engine...", "Compiling C++ engine", 70)
        os.makedirs("editor/build", exist_ok=True)
        subprocess.run(["cmake", "-DCMAKE_BUILD_TYPE=Release", ".."], cwd="editor/build", check=True)
        subprocess.run(["make", "-j4"], cwd="editor/build", check=True)
    return engine_bin

def execute_cpp_engine(engine_bin: str, timeline_path: str, fps: float = 60.0) -> bool:
    log(f"Launching C++ Headless Editor @ {fps:.0f} FPS (1080p Master Canvas)", "Rendering video", 75)
    cmd = [engine_bin, "--timeline", timeline_path, "--output", "out.mp4"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0 and os.path.exists("out.mp4") and os.path.getsize("out.mp4") > 1000:
        log(f"C++ Headless rendering completed successfully @ {fps:.0f} FPS!", progress=90)
        return True
    print(f"[HyperEditor] Notice: {proc.stderr}", file=sys.stderr)
    return False

# --- Stage 7: Export to Google Drive ---------------------------------------
def export_video_to_google_drive(video_path: str = "out.mp4") -> str | None:
    """
    Exports the rendered MP4 to Google Drive via the Supabase upload-to-drive Edge Function.
    """
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
        log("Google Drive Export skipped: Supabase credentials not found.")
        return None

    clean_name = "".join(c for c in PROMPT if c.isalnum() or c in (" ", "-", "_")).strip()
    filename = (clean_name[:45] or "documentary").replace(" ", "_") + ".mp4"

    log(f"Exporting rendered video to Google Drive ('{filename}')...", "Exporting to Drive", 96)
    
    url = f"{SUPABASE_URL}/functions/v1/upload-to-drive"
    try:
        with open(video_path, "rb") as f:
            files = {"file": (filename, f, "video/mp4")}
            data = {"folder": "Videos"}
            headers = {"Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"}
            res = requests.post(url, headers=headers, files=files, data=data, timeout=300)

        if res.ok:
            data = res.json()
            file_obj = data.get("file") or {}
            drive_link = file_obj.get("webViewLink") or file_obj.get("directDownloadUrl") or f"https://drive.google.com/file/d/{file_obj.get('id')}/view"
            log(f"Exported to Google Drive successfully: {drive_link}", "Exported to Drive", 98)
            
            # Write to GitHub Step Summary if running in Actions
            summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
            if summary_path:
                try:
                    with open(summary_path, "a", encoding="utf-8") as sf:
                        sf.write(f"\n### 🎬 Video Exported to Google Drive\n")
                        sf.write(f"- **Filename**: `{filename}`\n")
                        sf.write(f"- **Google Drive**: [Open Video in Google Drive]({drive_link})\n\n")
                except Exception:
                    pass
            return drive_link
        else:
            log(f"Google Drive export notice ({res.status_code}): {res.text[:200]}")
    except Exception as e:
        log(f"Google Drive export notice: {e}")
    return None

# --- Main Pipeline Orchestrator --------------------------------------------
def main() -> int:
    try:
        log("Starting Dual-Engine Long-Form Video Pipeline", "Initializing Video Engine", 5)
        log(f"Config: 16:9 Canvas (1920x1080) · Target {TARGET_MINUTES} min ({MIN_DURATION_SEC:.0f}s - {MAX_DURATION_SEC:.0f}s)")
        log(f"Style: {IMAGE_STYLE} · Voice: {VOICE_GENDER.title()} ({VOICE_PERSONA})")

        # 1. NVIDIA Brain Screenplay & Scene Planning
        if NVIDIA_API_KEY:
            script, scenes_plan = generate_script_with_nvidia_brain()
        else:
            log("NVIDIA_API_KEY not supplied; running procedural screenwriter fallback...")
            script, scenes_plan = write_procedural_fallback_script()

        # 2. Narration TTS
        voice_path = "assets/voice.mp3"
        audio_dur = generate_voiceover(script, voice_path)

        # Enforce output duration within flexible window
        total_duration = max(MIN_DURATION_SEC, min(MAX_DURATION_SEC, audio_dur))
        log(f"Final composition timeline locked at {total_duration:.1f} seconds ({total_duration/60:.2f} mins)", progress=48)

        # 3. Assets via Pexels & Pixabay
        scene_clips = source_1080p_assets(scenes_plan, total_duration, fps=60.0)

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

        # Mark completed in Supabase
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
        patch_supabase({
            "status": "failed",
            "step": "failed",
            "error": err_msg
        })
        return 1

if __name__ == "__main__":
    sys.exit(main())
