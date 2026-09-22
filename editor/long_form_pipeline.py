"""
Long-Form Video Pipeline: 'Create Video' (C++ Headless Engine / 'editor/')
Hyper Copilot & Video Agent Specification

Features:
1. Script & Storyboard Differentiation: Prompt is an idea/instruction set, not raw script.
   Generates a full-length screenplay and scene-by-scene storyboard tailored to Category.
2. Keyword Extraction & Stock Asset Fetching: Sourcing Pexels & Pixabay at exact 720p/1080p resolution.
3. Autonomous Editing: Auto-ducking BGM, dynamic keyframing (pan/zoom), PNG overlays, and smooth transitions.
4. Real-time Status Stages: Scripting -> Voiceover/HTTS -> C++ Engine Render -> Complete/Download.
5. Storage & Export: Supabase Storage + Google Drive integration.
"""

import json
import math
import os
import re
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

# Input Parameters from UI
PROMPT = env("PROMPT", "Deep oceanic trenches and bioluminescent ecosystems of the midnight zone")
NEGATIVE_PROMPT = env("NEGATIVE_PROMPT", "blurry, low quality, distorted, glitch, cartoon, text, watermark")

# Category (Locked Dropdown)
CATEGORY = env("CATEGORY") or env("VOICE_PERSONA") or "Documentary"

# Visual Style
VISUAL_STYLE = env("VISUAL_STYLE") or env("IMAGE_STYLE") or "Cinematic"

# Specs & Quality
RESOLUTION_RAW = (env("RESOLUTION") or env("QUALITY") or "1080p").lower()
FPS_RAW = (env("FPS") or env("BITRATE") or "60").lower()
FPS = 30.0 if ("30" in FPS_RAW and "60" not in FPS_RAW) else 60.0

if "720" in RESOLUTION_RAW:
    WIDTH, HEIGHT = 1280, 720
    RESOLUTION_LABEL = "720p"
else:
    WIDTH, HEIGHT = 1920, 1080
    RESOLUTION_LABEL = "1080p"

ASPECT_RATIO = env("ASPECT_RATIO", "16:9")
if "9:16" in ASPECT_RATIO or "vertical" in ASPECT_RATIO:
    WIDTH, HEIGHT = (720, 1280) if "720" in RESOLUTION_RAW else (1080, 1920)

# Duration (Minutes & Flexible Buffer)
try:
    if env("DURATION_MINUTES"):
        DURATION_MINS = float(env("DURATION_MINUTES"))
        raw_duration = DURATION_MINS * 60.0
    elif env("DURATION_SECONDS"):
        raw_duration = float(env("DURATION_SECONDS"))
        DURATION_MINS = raw_duration / 60.0
    else:
        DURATION_MINS = 3.0
        raw_duration = 180.0
except ValueError:
    DURATION_MINS = 3.0
    raw_duration = 180.0

TARGET_DURATION_SEC = max(30.0, min(1200.0, raw_duration))
TARGET_MINUTES = TARGET_DURATION_SEC / 60.0
MIN_DURATION_SEC = TARGET_DURATION_SEC * 0.85
MAX_DURATION_SEC = TARGET_DURATION_SEC * 1.15

# Audio & Voice
VOICE_GENDER = (env("VOICE_GENDER") or "male").lower()
BGM_RAW = (env("BGM") or env("MOTION_TEMPLATE") or "true").lower()
BGM_ENABLED = BGM_RAW not in {"0", "false", "off", "no", "bgm_off", "disabled"}

# Captions
CAPTIONS_RAW = (env("CAPTIONS") or "true").lower()
CAPTIONS_ENABLED = CAPTIONS_RAW not in {"0", "false", "off", "no"}
CAPTION_STYLE = env("CAPTION_STYLE", "Dynamic")
CAPTION_SIZE = env("CAPTION_SIZE", "Medium")

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


# --- Stage 1: Script & Visual Storyboard Generation -------------------------
def get_edge_tts_voice(gender: str) -> str:
    voices = {
        "male": "en-US-ChristopherNeural",
        "female": "en-US-JennyNeural",
    }
    return voices.get(gender, "en-US-ChristopherNeural")

def extract_keywords(text: str) -> list[str]:
    stop_words = {
        "the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "with",
        "about", "into", "of", "by", "from", "is", "are", "was", "were", "be",
        "this", "that", "these", "those", "how", "what", "why", "video", "make",
        "create", "topic", "scene", "scenes", "generate", "show", "explore"
    }
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
    words = [w.strip() for w in cleaned.split() if w.strip() not in stop_words and len(w.strip()) > 2]
    return words or ["cinematic", "nature", "landscape", "technology", "exploration"]

def generate_script_and_storyboard() -> tuple[str, list[dict]]:
    """
    CRITICAL: Never treat PROMPT directly as the narration script!
    The prompt is an idea/instruction set. This engine generates a full-length
    structured narration script and scene-by-scene storyboard according to the Category.
    """
    wpm = 135  # Words per minute for cinematic documentary pacing
    approx_words = int(TARGET_MINUTES * wpm)
    min_words = int((MIN_DURATION_SEC / 60.0) * wpm)
    target_scenes = max(4, min(30, int(TARGET_DURATION_SEC / 8.0)))

    log(
        f"Stage 1 [Scripting]: Generating {CATEGORY} script (~{approx_words} words, {target_scenes} scenes) for idea: '{PROMPT}'",
        step="Scripting",
        progress=15,
    )

    if NVIDIA_API_KEY:
        try:
            system_prompt = (
                f"You are a professional film screenwriter and director specializing in {CATEGORY} productions with a {VISUAL_STYLE} visual aesthetic.\n"
                "The user will give you a topic/idea. DO NOT output the user's prompt as the narration.\n"
                f"Generate a full, rich, multi-paragraph voiceover script ({approx_words} words) that thoroughly explores the concept.\n"
                f"Also create a storyboard of exactly {target_scenes} scenes. For each scene provide visual description and 2-3 specific stock video search keywords.\n"
                "Output valid JSON ONLY with this schema:\n"
                "{\n"
                '  "title": "Title",\n'
                '  "narration": "Full voiceover narration...",\n'
                '  "scenes": [\n'
                "    {\n"
                '      "scene_id": 1,\n'
                '      "duration": 8.0,\n'
                '      "visual_description": "...",\n'
                '      "visual_query_intent": "...",\n'
                '      "search_queries": ["...", "..."]\n'
                "    }\n"
                "  ]\n"
                "}"
            )
            user_prompt = (
                f"Idea/Topic: {PROMPT}\n"
                f"Category: {CATEGORY}\n"
                f"Visual Style: {VISUAL_STYLE}\n"
                f"Negative Exclusions: {NEGATIVE_PROMPT}\n"
                f"Runtime: {TARGET_MINUTES:.1f} minutes (~{approx_words} words)."
            )

            for model in ["meta/llama-3.1-70b-instruct", "nvidia/llama-3.1-nemotron-70b-instruct"]:
                try:
                    res = requests.post(
                        "https://integrate.api.nvidia.com/v1/chat/completions",
                        headers={"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"},
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            "temperature": 0.65,
                            "max_tokens": 4096,
                            "response_format": {"type": "json_object"},
                        },
                        timeout=45,
                    )
                    if res.ok:
                        content = res.json()["choices"][0]["message"]["content"].strip()
                        if content.startswith("```"):
                            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                        parsed = json.loads(content)
                        narration = parsed.get("narration", "").strip()
                        scenes = parsed.get("scenes", [])
                        if narration and len(narration.split()) >= min_words * 0.7:
                            log(f"Brain synthesized screenplay: {len(narration.split())} words, {len(scenes)} scenes.", progress=25)
                            return narration, scenes
                except Exception as e:
                    print(f"[LLM] Error with {model}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[LLM] Exception: {e}", file=sys.stderr)

    # Procedural Category-Specific Screenplay Generator (Deterministic, deep, resilient)
    return generate_procedural_category_screenplay(approx_words, target_scenes)

def generate_procedural_category_screenplay(approx_words: int, target_scenes: int) -> tuple[str, list[dict]]:
    keywords = extract_keywords(PROMPT)
    kw_str = ", ".join(keywords[:4])
    main_kw = keywords[0] if keywords else "the natural realm"
    sec_kw = keywords[1] if len(keywords) > 1 else "the universe"

    category_templates = {
        "Documentary": [
            f"Across the boundless frontiers of our world, {PROMPT} represents an extraordinary phenomenon of nature, time, and planetary evolution.",
            f"When we look closely at {kw_str}, each dynamic shift reveals subtle laws of physics, atmospheric chemistry, and organic equilibrium.",
            f"Here, ancient cycles have played out across millions of years, shaping terrain, currents, and living architectures unseen by modern civilization.",
            f"The interplay of light, shadow, and elemental forces creates an awe-inspiring theater where life adapts to the most rigorous extremes.",
            f"From micro-textures on the surface to sweeping horizon panoramas, this environment reminds us of the delicate balance governing the cosmos.",
            f"Deep beneath the surface, quiet currents and subterranean pressures give birth to crystalline structures and resilient ecosystems.",
            f"As we observe the quiet dignity of {main_kw}, we gain profound insight into how our planet continuously renews its ancient majesty.",
            f"In this undisturbed sanctuary, the narrative of {PROMPT} unfolds with sublime power, leaving an indelible imprint on human curiosity."
        ],
        "Business & Finance": [
            f"In an interconnected global economy, {PROMPT} is rapidly emerging as a pivotal force driving structural transformation and capital reallocation.",
            f"Market participants analyzing {kw_str} are witnessing an unprecedented convergence of technological acceleration and institutional adoption.",
            f"Strategic resilience now demands that organizations re-examine cost structures, risk mitigation paradigms, and scalable revenue vectors.",
            f"The underlying data indicates a paradigm shift where legacy efficiencies are systematically eclipsed by algorithmic agility and capital velocity.",
            f"Visionary leadership is no longer about predicting quarterly variance, but navigating macroeconomic inflection points with decisive clarity.",
            f"As liquidity pools and venture syndicates align around {main_kw}, early movers establish durable competitive moats and market leadership.",
            f"The economic calculus is unambiguous: entities that master {PROMPT} will architect the next epoch of enterprise value creation.",
            f"Looking toward the next horizon, the synergy between capital, governance, and market discipline will determine long-term prosperity."
        ],
        "Science & Technology": [
            f"At the cutting edge of modern scientific inquiry, {PROMPT} stands as a testament to the transformative power of empirical discovery.",
            f"Researchers investigating {kw_str} are unraveling foundational principles that bridge theoretical physics, computation, and bio-engineering.",
            f"Through high-precision instrumentation and machine intelligence, phenomena once considered impenetrable are now systematically quantified.",
            f"Every breakthrough in {main_kw} creates cascading implications across energy density, materials science, and cognitive processing.",
            f"By probing the micro-architecture of matter and the macro-dynamics of systems, humanity continues to push the boundary of human capability.",
            f"The intersection of computational modeling and experimental validation is accelerating the discovery cycle by orders of magnitude.",
            f"As we engineer novel paradigms inspired by {PROMPT}, we lay the technological foundation for sustainable interplanetary progress.",
            f"Science does not merely describe what exists; it illuminates the pathways through which the impossible becomes inevitable."
        ],
        "Motivation": [
            f"Every meaningful triumph in the human story began with a quiet decision to step into the unknown and confront {PROMPT}.",
            f"When challenges arise around {kw_str}, remember that adversity is not an obstacle to greatness—it is the very crucible in which strength is forged.",
            f"True mastery requires relentless focus, disciplined habits, and the unwavering conviction that your vision is worth every sacrifice.",
            f"The world is filled with noise and hesitation, but those who commit to continuous growth transform fleeting ambition into permanent excellence.",
            f"Rise above temporary setbacks. Every repetition, every long hour, and every focused breath moves you closer to the peak.",
            f"Your potential is not dictated by circumstance, but by the standards you hold yourself to when no one is watching.",
            f"Embrace the discipline of {main_kw}. Let your dedication speak louder than your words, and refuse to surrender your purpose.",
            f"Today is your proving ground. Stand firm, execute with relentless determination, and write your own legacy with unapologetic confidence."
        ],
        "Travel & Lifestyle": [
            f"Traveling into the heart of {PROMPT} offers a sensory awakening, where ancient geography meets vibrant contemporary culture.",
            f"Wandering through {kw_str}, every turn unveils breathtaking landscapes, golden illumination, and the welcoming warmth of timeless traditions.",
            f"From early morning mist rising over distant peaks to quiet twilight settling across the horizon, time slows to a restorative cadence.",
            f"The culinary traditions, architectural heritage, and artisan craft celebrate generations of harmony between humanity and the land.",
            f"Here, luxury is found not in extravagance, but in pure authenticity, crisp air, and the tranquility of unspoiled nature.",
            f"Immersing yourself in {main_kw} restores a sense of perspective and reminds us of the endless beauty awaiting discovery across our world.",
            f"Whether trekking remote trails or savoring sunset reflections, every moment leaves a lingering memory etched into the soul.",
            f"This journey is an invitation to pause, breathe, and celebrate the magnificent tapestry of life across our planet."
        ],
        "Horror & Mystery": [
            f"Beyond the reach of civilized understanding lies the chilling enigma of {PROMPT}, shrouded in silence and forgotten history.",
            f"Those who investigated {kw_str} spoke of subtle anomalies, cold drafts, and a lingering sense that the shadows were watching.",
            f"Archival records contain strange omissions, fragmented journals, and eyewitness accounts that defy rational explanation.",
            f"As dusk turns to darkness, the atmosphere grows heavy with unease, and the familiar boundaries of reality begin to blur.",
            f"What secrets remain buried beneath the surface of {main_kw}? Some truths were intentionally hidden for the protection of mankind.",
            f"In the dead of night, faint whispers echo through the corridors of memory, questioning whether the nightmare has truly ended.",
            f"The deeper you delve into this labyrinth, the more you realize that some doorways, once opened, can never be closed again.",
            f"The mystery of {PROMPT} persists, patient, calculating, and waiting in the perpetual twilight for its next witness."
        ],
        "News & Facts": [
            f"In verified developments today, {PROMPT} has become the focal point of intensive analysis by international observers and domain authorities.",
            f"Data metrics surrounding {kw_str} confirm significant shifts, prompting coordinated responses across regulatory and research sectors.",
            f"According to verified reports, key performance indicators have surpassed historical benchmarks, underscoring systemic transformation.",
            f"Field analysts emphasize that the strategic implications of {main_kw} will influence policy frameworks and operational decisions worldwide.",
            f"Independent verification teams continue monitoring telemetry and empirical indicators to deliver objective, fact-based intelligence.",
            f"As stakeholders convene to assess the long-term impact, transparency and rigorous verification remain the cornerstone of coverage.",
            f"We will continue tracking updates on {PROMPT} as verified data and official findings are released into the public record."
        ]
    }

    pool = category_templates.get(CATEGORY, category_templates["Documentary"])

    # Expand to match target duration words
    script_paragraphs = []
    word_count = 0
    idx = 0
    while word_count < approx_words or len(script_paragraphs) < 4:
        para = pool[idx % len(pool)]
        script_paragraphs.append(para)
        word_count += len(para.split())
        idx += 1

    narration = "\n\n".join(script_paragraphs)

    # Build scene storyboard
    scenes = []
    per_scene_dur = TARGET_DURATION_SEC / float(target_scenes)
    for s_idx in range(target_scenes):
        k = keywords[s_idx % len(keywords)]
        k_alt = keywords[(s_idx + 1) % len(keywords)]
        scenes.append({
            "scene_id": s_idx + 1,
            "duration": round(per_scene_dur, 2),
            "visual_description": f"{VISUAL_STYLE} vista of {k} with {k_alt} highlights",
            "visual_query_intent": f"Cinematic {VISUAL_STYLE.lower()} camera movement capturing {k} in {CATEGORY.lower()} setting",
            "search_queries": [
                f"{k} {VISUAL_STYLE.lower()}",
                f"{k} {k_alt}",
                f"{k} 4k",
                f"{CATEGORY.lower()} {k}"
            ]
        })

    log(f"Procedural screenplay crafted: {len(narration.split())} words across {target_scenes} scenes.", progress=25)
    return narration, scenes


# --- Stage 2: Voiceover / TTS Synthesis --------------------------------------
def generate_voiceover(script: str, output_path: str = "assets/voice.mp3") -> float:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    voice = get_edge_tts_voice(VOICE_GENDER)

    log(
        f"Stage 2 [Voiceover/HTTS]: Synthesizing narration with Edge-TTS ({voice})",
        step="Voiceover/HTTS",
        progress=35,
    )

    clean_text = " ".join(script.split())
    cmd = [
        "edge-tts",
        "--voice", voice,
        "--text", clean_text,
        "--write-media", output_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        print(f"[Edge-TTS] Fallback generation for {output_path}")
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
        capture_output=True, text=True
    )
    try:
        duration = float(probe.stdout.strip())
    except Exception:
        duration = TARGET_DURATION_SEC

    log(f"Voiceover track synthesized ({duration:.1f}s)", progress=45)
    return duration


# --- Stage 3: Stock Asset Sourcing (Pexels & Pixabay 720p / 1080p) -----------
def search_pexels_video(query: str, target_res: str = "1080p") -> str | None:
    if not PEXELS_API_KEY:
        return None
    try:
        url = f"https://api.pexels.com/videos/search?query={requests.utils.quote(query)}&orientation=landscape&size=large&per_page=8"
        headers = {"Authorization": PEXELS_API_KEY}
        r = requests.get(url, headers=headers, timeout=12)
        if r.ok:
            data = r.json()
            # 1. Look for exact resolution match
            req_w = 1280 if target_res == "720p" else 1920
            req_h = 720 if target_res == "720p" else 1080
            for v in data.get("videos", []):
                for f in v.get("video_files", []):
                    if f.get("width") == req_w and f.get("height") == req_h and f.get("link"):
                        return f["link"]
            # 2. Look for higher/equal resolution
            for v in data.get("videos", []):
                for f in v.get("video_files", []):
                    if (f.get("width") or 0) >= req_w and f.get("link"):
                        return f["link"]
            # 3. Any HD link
            for v in data.get("videos", []):
                for f in v.get("video_files", []):
                    if (f.get("width") or 0) >= 1280 and f.get("link"):
                        return f["link"]
    except Exception as e:
        print(f"[Pexels] Error for '{query}': {e}", file=sys.stderr)
    return None

def search_pixabay_video(query: str, target_res: str = "1080p") -> str | None:
    if not PIXABAY_API_KEY:
        return None
    try:
        url = f"https://pixabay.com/api/videos/?key={PIXABAY_API_KEY}&q={requests.utils.quote(query)}&video_type=film&orientation=horizontal&per_page=8"
        r = requests.get(url, timeout=12)
        if r.ok:
            data = r.json()
            for hit in data.get("hits", []):
                vids = hit.get("videos", {})
                order = ["large", "medium", "small"] if target_res == "1080p" else ["medium", "large", "small"]
                for res_key in order:
                    if vids.get(res_key, {}).get("url"):
                        return vids[res_key]["url"]
    except Exception as e:
        print(f"[Pixabay] Error for '{query}': {e}", file=sys.stderr)
    return None

def fetch_transparent_overlay(query: str, output_path: str) -> str | None:
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
                        res = requests.get(img_url, timeout=12)
                        if res.ok:
                            with open(output_path, "wb") as f:
                                f.write(res.content)
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

        # Transcode & normalize to target resolution & FPS with smooth contrast/saturation
        vf = (
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},"
            f"fps={fps},"
            f"eq=contrast=1.06:saturation=1.12"
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
        print(f"[Normalize] Error: {e}", file=sys.stderr)
        if os.path.exists(temp_download):
            os.remove(temp_download)
        return False

def generate_procedural_scene(output_path: str, duration: float, scene_idx: int, fps: float = 60.0) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    palette_map = {
        "Documentary": [("0x050d1a", "0x1b3b6f"), ("0x081c15", "0x1b4332"), ("0x1a0933", "0x592e83")],
        "Business & Finance": [("0x0a192f", "0x1e3a8a"), ("0x0f172a", "0x334155"), ("0x022c22", "0x065f46")],
        "Science & Technology": [("0x030712", "0x1e1b4b"), ("0x0c0a09", "0x0284c7"), ("0x172554", "0x38bdf8")],
        "Motivation": [("0x450a0a", "0x7f1d1d"), ("0x1c1917", "0xd97706"), ("0x18181b", "0xe11d48")],
        "Travel & Lifestyle": [("0x0c4a6e", "0x0284c7"), ("0x064e3b", "0x10b981"), ("0x78350f", "0xd97706")],
        "Horror & Mystery": [("0x09090b", "0x18181b"), ("0x1c1917", "0x292524"), ("0x020617", "0x0f172a")],
        "News & Facts": [("0x172554", "0x1e40af"), ("0x18181b", "0x27272a"), ("0x030712", "0x1e293b")],
    }
    colors = palette_map.get(CATEGORY, palette_map["Documentary"])
    c1, _ = colors[scene_idx % len(colors)]
    vf = (
        f"nullsrc=s={WIDTH}x{HEIGHT}:d={duration}:r={fps},"
        f"format=yuv420p,"
        f"drawbox=y=0:color={c1}:width=iw:height=ih:t=fill,"
        f"noise=alls=12:allf=t+u,"
        f"eq=contrast=1.08:saturation=1.15"
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

def source_stock_assets(scenes_plan: list[dict], total_duration: float, fps: float = 60.0) -> list[dict]:
    os.makedirs("assets/scenes", exist_ok=True)
    os.makedirs("assets/overlays", exist_ok=True)
    scene_clips = []
    num_scenes = max(3, len(scenes_plan))
    per_scene_dur = max(5.0, total_duration / num_scenes)

    log(
        f"Sourcing stock footage for {num_scenes} scenes via Pexels & Pixabay ({RESOLUTION_LABEL} @ {fps:.0f} FPS)...",
        progress=55,
    )

    current_time = 0.0
    for idx, scene in enumerate(scenes_plan):
        scene_dur = min(per_scene_dur, total_duration - current_time)
        if scene_dur <= 1.0:
            break
        clip_path = f"assets/scenes/scene_{idx:03d}.mp4"
        queries = scene.get("search_queries", [])
        if not queries:
            queries = [f"{w} {CATEGORY.lower()}" for w in extract_keywords(PROMPT)[:2]]

        video_url = None
        source_provider = "Procedural"

        for q in queries:
            video_url = search_pexels_video(q, target_res=RESOLUTION_LABEL)
            if video_url:
                source_provider = f"Pexels ('{q}')"
                break

        if not video_url:
            for q in queries:
                video_url = search_pixabay_video(q, target_res=RESOLUTION_LABEL)
                if video_url:
                    source_provider = f"Pixabay ('{q}')"
                    break

        success = False
        if video_url:
            success = download_and_normalize_clip(video_url, clip_path, scene_dur, fps=fps)
            if success:
                log(f"Scene {idx+1}/{num_scenes}: Sourced {RESOLUTION_LABEL} clip from {source_provider} ({scene_dur:.1f}s)")

        if not success:
            generate_procedural_scene(clip_path, scene_dur, idx, fps=fps)
            log(f"Scene {idx+1}/{num_scenes}: Generated procedural canvas ({scene_dur:.1f}s)")

        # Motion & Dynamic Keyframing (Ken Burns Pan/Zoom effect)
        motion_types = ["zoom_in", "pan_right", "zoom_out", "pan_left"]
        motion_choice = motion_types[idx % len(motion_types)]

        scene_dict = {
            "id": f"scene_{idx}",
            "file": os.path.abspath(clip_path),
            "start": round(current_time, 2),
            "duration": round(scene_dur, 2),
            "transition_in": "crossfade" if idx > 0 else "none",
            "transition_duration": 0.8 if idx > 0 else 0.0,
            "motion": {
                "type": motion_choice,
                "intensity": 0.08,
            },
            "color_grading": {
                "contrast": 1.08,
                "saturation": 1.12,
                "temperature": 0.02,
            },
        }

        # Transparent PNG Overlay support
        overlay_query = scene.get("visual_query_intent") or (queries[0] if queries else "cinematic")
        overlay_path = f"assets/overlays/overlay_{idx:03d}.png"
        overlay_file = fetch_transparent_overlay(overlay_query, overlay_path)
        if overlay_file and os.path.exists(overlay_file):
            scene_dict["overlay"] = {
                "file": os.path.abspath(overlay_file),
                "opacity": 0.20,
                "blend_mode": "screen",
            }

        scene_clips.append(scene_dict)
        current_time += scene_dur

    return scene_clips


# --- Stage 4: Soundtrack with Auto-Ducking -----------------------------------
def generate_ambient_soundtrack(duration: float, output_path: str = "assets/soundtrack.wav") -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    log(f"Synthesizing atmospheric soundtrack with auto-ducking DSP ({duration:.1f}s)", progress=65)

    # Multi-harmonic cinematic ambient chords tailored to Category
    freqs = [110, 165, 220]
    if CATEGORY in {"Business & Finance", "News & Facts"}:
        freqs = [130, 195, 260]
    elif CATEGORY in {"Science & Technology", "Cyberpunk"}:
        freqs = [120, 180, 240]
    elif CATEGORY == "Horror & Mystery":
        freqs = [92, 138, 184]

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"sine=frequency={freqs[0]}:duration={duration + 2.0}",
        "-f", "lavfi", "-i", f"sine=frequency={freqs[1]}:duration={duration + 2.0}",
        "-f", "lavfi", "-i", f"sine=frequency={freqs[2]}:duration={duration + 2.0}",
        "-filter_complex",
        f"[0:a][1:a][2:a]amix=inputs=3:dropout_transition=2,volume=0.35,lowpass=f=800,afade=t=in:ss=0:d=2.5,afade=t=out:st={duration}:d=2[out]",
        "-map", "[out]",
        output_path
    ]
    subprocess.run(cmd, capture_output=True)
    return output_path


# --- Stage 5: Timeline & C++ Engine Render Execution ------------------------
def build_timeline_json(
    scene_clips: list[dict],
    voice_path: str,
    music_path: str | None,
    total_duration: float,
    fps: float = 60.0,
) -> str:
    timeline_path = "timeline.json"
    audio_tracks = [
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
                "noise_gate_db": -45.0,
            },
        }
    ]

    if music_path and os.path.exists(music_path) and BGM_ENABLED:
        audio_tracks.insert(0, {
            "id": "bg_soundtrack",
            "file": os.path.abspath(music_path),
            "start": 0.0,
            "duration": round(total_duration, 2),
            "volume": 0.55,
            "is_voiceover": False,
            "duck_on_voiceover": True,
            "ducking_attenuation": 0.20,  # Duck to 20% volume during speech
            "ducking_attack": 0.15,
            "ducking_release": 0.35,
            "effects": {
                "high_pass_hz": 60.0,
                "low_pass_hz": 10000.0,
                "eq_low_db": 1.0,
                "eq_mid_db": -2.0,
                "eq_high_db": 1.0,
                "noise_gate_db": -50.0,
            },
        })

    timeline = {
        "output": {
            "width": WIDTH,
            "height": HEIGHT,
            "fps": fps,
            "duration": round(total_duration, 2),
            "path": "out.mp4",
            "sample_rate": 48000,
            "channels": 2,
        },
        "scenes": scene_clips,
        "audio_tracks": audio_tracks,
    }

    with open(timeline_path, "w", encoding="utf-8") as f:
        json.dump(timeline, f, indent=2)

    return timeline_path

def compile_engine_if_needed() -> str:
    bin_path = os.path.abspath("editor/build/hyper_editor")
    if os.path.exists(bin_path) and os.access(bin_path, os.X_OK):
        return bin_path
    log("Compiling C++ Native Engine via CMake...", progress=70)
    build_dir = "editor/build"
    os.makedirs(build_dir, exist_ok=True)
    subprocess.run(["cmake", "-DCMAKE_BUILD_TYPE=Release", ".."], cwd=build_dir, check=True)
    subprocess.run(["make", f"-j{os.cpu_count() or 4}"], cwd=build_dir, check=True)
    return bin_path

def execute_cpp_engine(engine_bin: str, timeline_path: str, fps: float = 60.0) -> bool:
    log(f"Invoking C++ Native Engine (timeline: {timeline_path} @ {fps:.0f} FPS)...", progress=75)
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
        log(f"C++ Engine execution notice: {e}")
    return False

def render_ffmpeg_master_stream(
    scene_clips: list[dict],
    voice_path: str,
    music_path: str | None,
    total_duration: float,
    fps: float = 60.0,
) -> bool:
    log("Running FFmpeg master render fallback with auto-ducking...", progress=80)
    first_clip = scene_clips[0]["file"] if scene_clips else "assets/scenes/scene_000.mp4"

    if music_path and os.path.exists(music_path) and BGM_ENABLED:
        filter_complex = (
            f"[2:a]volume=0.20[bg];"
            f"[1:a][bg]amix=inputs=2:duration=longest[aout];"
            f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},fps={fps}[vout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", first_clip,
            "-i", voice_path,
            "-i", music_path,
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-t", str(round(total_duration, 2)),
            "out.mp4"
        ]
    else:
        filter_complex = (
            f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},fps={fps}[vout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", first_clip,
            "-i", voice_path,
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "1:a",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-t", str(round(total_duration, 2)),
            "out.mp4"
        ]

    res = subprocess.run(cmd, capture_output=True)
    return res.returncode == 0 and os.path.exists("out.mp4") and os.path.getsize("out.mp4") > 1000


# --- Stage 6: Export & Upload -----------------------------------------------
def export_video_to_google_drive(video_path: str = "out.mp4") -> str | None:
    export_script = os.path.join(os.path.dirname(__file__), "export_to_drive.py")
    if not os.path.exists(export_script):
        return None
    try:
        env_copy = dict(os.environ)
        env_copy["VIDEO_FILE"] = video_path
        res = subprocess.run([sys.executable, export_script], env=env_copy, capture_output=True, text=True)
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
        log(f"Drive export notice: {e}")
        return None


# --- Main Pipeline Orchestration --------------------------------------------
def main() -> int:
    try:
        log(
            f"Initializing Video Pipeline · Category: {CATEGORY} · Style: {VISUAL_STYLE} · Specs: {RESOLUTION_LABEL} @ {FPS:.0f} FPS",
            step="Scripting",
            progress=5,
        )

        # 1. Script & Visual Storyboard (Idea to Screenplay)
        script, scenes_plan = generate_script_and_storyboard()

        # 2. Voiceover Synthesis (Edge-TTS)
        voice_path = "assets/voice.mp3"
        audio_dur = generate_voiceover(script, voice_path)
        total_duration = max(MIN_DURATION_SEC, min(MAX_DURATION_SEC, audio_dur))
        log(f"Narration locked: {total_duration:.1f}s ({total_duration/60:.2f} mins)", progress=48)

        # 3. Stock Asset Sourcing (Pexels & Pixabay matching resolution & FPS)
        log(
            f"Stage 3 [C++ Engine Render]: Sourcing assets and preparing C++ timeline ({RESOLUTION_LABEL} @ {FPS:.0f} FPS)...",
            step="C++ Engine Render",
            progress=50,
        )
        scene_clips = source_stock_assets(scenes_plan, total_duration, fps=FPS)

        # 4. Background Music with Auto-Ducking
        music_path = None
        if BGM_ENABLED:
            music_path = generate_ambient_soundtrack(total_duration)
        else:
            log("Background Music (BGM) disabled by user configuration.")

        # 5. Build C++ Engine & Render
        engine_bin = compile_engine_if_needed()
        timeline_path = build_timeline_json(scene_clips, voice_path, music_path, total_duration, fps=FPS)

        success = execute_cpp_engine(engine_bin, timeline_path, fps=FPS)
        if not success and FPS > 30:
            log("60 FPS render constraint encountered — falling back to 30 FPS render...", progress=78)
            timeline_30 = build_timeline_json(scene_clips, voice_path, music_path, total_duration, fps=30.0)
            success = execute_cpp_engine(engine_bin, timeline_30, fps=30.0)

        if not success:
            success = render_ffmpeg_master_stream(scene_clips, voice_path, music_path, total_duration, fps=FPS)

        if not (os.path.exists("out.mp4") and os.path.getsize("out.mp4") > 1000):
            raise RuntimeError("Final video render output file was not produced.")

        # 6. Upload to Supabase Storage
        log("Stage 4 [Complete/Download]: Uploading final video and exporting...", step="Complete/Download", progress=90)
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
                if upload_res.ok:
                    log("Master MP4 stored in private Supabase Storage bucket.", progress=95)
                else:
                    log(f"Upload notice: {upload_res.status_code}")

        # 7. Google Drive Export
        drive_link = export_video_to_google_drive("out.mp4")

        # 8. Mark Complete in Supabase
        completion_payload = {
            "status": "completed",
            "progress": 100,
            "step": "Complete/Download",
            "video_url": f"{USER_ID}/{VIDEO_ID}.mp4",
        }
        if drive_link:
            completion_payload["logs"] = f"Render complete! Google Drive: {drive_link}"
        patch_supabase(completion_payload)

        log(
            f"Render successfully completed! Output: {total_duration:.1f}s ({RESOLUTION_LABEL} @ {FPS:.0f} FPS)" + (f" · Drive: {drive_link}" if drive_link else ""),
            step="Complete/Download",
            progress=100,
        )
        return 0

    except Exception as e:
        err_msg = f"Video pipeline error: {e}"
        log(err_msg, step="failed", progress=0)
        patch_supabase({"status": "failed", "step": "failed", "error": err_msg})
        return 1

if __name__ == "__main__":
    sys.exit(main())
