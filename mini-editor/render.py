"""
Short-Form Pipeline: 'Create Reel' (Python Engine / 'mini-editor/')
Hyper Copilot & Video Agent Specification

Process Flow:
1. Script & Structure: LLM generates 9:16 vertical video script & timeline structure based on user prompt.
2. Voiceover: Edge-TTS generates audio track.
3. Image Generation: Fetch AI images via Pixabay API using the 'Flux.1 [schnell]' model for scene visuals.
4. Caption Rendering: Check user toggle. If captions = ON, render dynamic animated subtitle overlays; if OFF, skip subtitles.
5. Assembly: Combine audio, Flux images, and optional captions into a vertical .mp4.
"""

import base64
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import requests

def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or "").strip() or default

# Supabase
SUPABASE_URL = env("SUPABASE_URL").rstrip("/")
SERVICE_KEY = env("SUPABASE_SERVICE_ROLE_KEY")
VIDEO_ID = env("VIDEO_ID", "local_test_reel")
USER_ID = env("USER_ID", "local_user")

# User Preferences
PROMPT = env("PROMPT", "Cosmic secrets of deep space nebulae")
NEGATIVE_PROMPT = env("NEGATIVE_PROMPT", "blurry, low quality, watermark, distorted, text")
VOICE_GENDER = env("VOICE_GENDER", "female").lower()
IMAGE_STYLE = env("IMAGE_STYLE", "Cinematic 3D, photorealistic lighting, 8k vertical framing")
MOTION_TEMPLATE = env("MOTION_TEMPLATE", "Auto Zoom-In")
ASPECT_RATIO = "9:16"
WIDTH, HEIGHT = 1080, 1920
FPS = 30
VIDEO_BITRATE = "8M"
FADE = 0.5  # Crossfade overlap duration between scenes

# Captions Toggle & Scale
CAPTIONS_RAW = env("CAPTIONS", "true").lower()
CAPTIONS = CAPTIONS_RAW in {"1", "true", "yes", "on", "small", "medium", "large"}
CAPTION_SIZE = CAPTIONS_RAW if CAPTIONS_RAW in {"small", "medium", "large"} else "medium"

try:
    CAPTION_SCALE = max(1, min(10, int(float(env("CAPTION_SCALE", "4")))))
except ValueError:
    CAPTION_SCALE = 4

try:
    DURATION = max(5, min(60, int(float(env("DURATION_SECONDS", "15")))))
except ValueError:
    DURATION = 15

# Providers
PIXABAY_API_KEY = env("PIXABAY_API_KEY")
PIXAZO_API_KEY = env("PIXAZO_API_KEY")
PIXAZO_BASE_URL = env("PIXAZO_BASE_URL", "https://api.pixazo.ai").rstrip("/")
PIXAZO_IMAGE_MODEL = env("PIXAZO_IMAGE_MODEL", "pixazo-image-free")

NVIDIA_API_KEY = env("NVIDIA_API_KEY")
CF_ACCOUNT_ID = env("CLOUDFLARE_ACCOUNT_ID")
CF_API_TOKEN = env("CLOUDFLARE_API_TOKEN")

CF_IMAGE_MODELS = [
    model.strip()
    for model in env(
        "CF_IMAGE_MODEL",
        "@cf/black-forest-labs/flux-1-schnell,"
        "@cf/stabilityai/stable-diffusion-xl-base-1.0,"
        "@cf/bytedance/stable-diffusion-xl-lightning",
    ).split(",")
    if model.strip()
]

CF_LLM_MODELS = [
    model.strip()
    for model in env(
        "CF_LLM_MODEL",
        "@cf/meta/llama-3.3-70b-instruct-fp8-fast,"
        "@cf/meta/llama-3.1-8b-instruct,"
        "@cf/meta/llama-3.1-8b-instruct-fast,"
        "@cf/mistralai/mistral-small-3.1-24b-instruct",
    ).split(",")
    if model.strip()
]

# Edge TTS
TTS_LANG = env("TTS_LANG", "en").lower()
EDGE_VOICES = {
    ("en", "male"): "en-US-GuyNeural",
    ("en", "female"): "en-US-AriaNeural",
    ("hi", "male"): "hi-IN-MadhurNeural",
    ("hi", "female"): "hi-IN-SwaraNeural",
}
EDGE_VOICE = env(
    "EDGE_TTS_VOICE",
    EDGE_VOICES.get(
        (TTS_LANG[:2], "male" if VOICE_GENDER.startswith("m") else "female"),
        "en-US-AriaNeural",
    ),
)
EDGE_RATE = env("EDGE_TTS_RATE", "+8%")
EDGE_PITCH = env("EDGE_TTS_PITCH", "+0Hz")


# --- Logging & Supabase Status ----------------------------------------------
def patch_supabase(payload: dict) -> None:
    if not (SUPABASE_URL and SERVICE_KEY and VIDEO_ID):
        return
    try:
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/videos?id=eq.{VIDEO_ID}",
            headers={
                "apikey": SERVICE_KEY,
                "Authorization": f"Bearer {SERVICE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=payload,
            timeout=10,
        )
    except Exception as e:
        print(f"[Supabase] Patch notice: {e}", file=sys.stderr)

def log(message: str, step: str | None = None, progress: int | None = None) -> None:
    print(f"[MiniEditor] {message}", flush=True)
    payload: dict = {"logs": message}
    if step:
        payload["step"] = step
    if progress is not None:
        payload["progress"] = progress
    patch_supabase(payload)


# --- Stage 1: Script & Structure (LLM) --------------------------------------
def cloudflare_run(model: str, body: dict, *, timeout: int = 180) -> requests.Response:
    if not (CF_ACCOUNT_ID and CF_API_TOKEN):
        raise RuntimeError("CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN are not configured")
    response = requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{model}",
        headers={"Authorization": f"Bearer {CF_API_TOKEN}"},
        json={key: value for key, value in body.items() if value not in (None, "")},
        timeout=timeout,
    )
    if not response.ok:
        raise RuntimeError(f"Workers AI {model} failed ({response.status_code}): {response.text[:200]}")
    return response

def cf_chat(system: str, user: str, *, max_tokens: int = 800) -> str:
    body = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
    }
    for model in CF_LLM_MODELS:
        try:
            raw = cloudflare_run(model, body).json()
            result = raw.get("result") if isinstance(raw, dict) else None
            if not isinstance(result, dict):
                result = raw if isinstance(raw, dict) else {}
            candidate = result.get("response") or result.get("result")
            if isinstance(candidate, dict):
                candidate = candidate.get("response") or candidate.get("text")
            text = str(candidate).strip() if candidate else ""
            if text and text.lower() != "none":
                return text
        except Exception:
            continue
    return ""

def generate_script_and_timeline() -> tuple[str, list[dict]]:
    """
    Generates 9:16 vertical video script & timeline structure based on user prompt.
    Produces an attention-grabbing hook in the first 2-3s, fluid pacing, and 3-5 scenes.
    """
    num_scenes = max(3, min(6, round(DURATION / 4.0)))
    target_words = max(10, round(DURATION * 2.5))

    system_prompt = (
        "You are an elite short-form video director specializing in viral 9:16 vertical reels.\n"
        f"Generate a {DURATION}-second vertical reel script and structured timeline.\n"
        "Rules:\n"
        "1. Hook: The opening sentence must immediately hook viewers within the first 2 seconds.\n"
        f"2. Word count: Total narration MUST be between {target_words - 5} and {target_words + 8} words.\n"
        f"3. Scenes: Exactly {num_scenes} visual scenes for vertical 9:16 composition.\n"
        "4. Respond with valid JSON ONLY in this format:\n"
        "{\n"
        '  "narration": "Full spoken voiceover script...",\n'
        '  "scenes": [\n'
        '    {"id": 1, "visual_description": "...", "pixabay_query": "..."},\n'
        '    {"id": 2, "visual_description": "...", "pixabay_query": "..."}\n'
        "  ]\n"
        "}"
    )
    user_prompt = f"Topic/Prompt: {PROMPT}\nStyle: {IMAGE_STYLE}\nDuration: {DURATION}s"

    raw_json = ""
    # 1. Try Cloudflare Workers AI
    if CF_ACCOUNT_ID and CF_API_TOKEN:
        try:
            raw_json = cf_chat(system_prompt, user_prompt)
        except Exception as e:
            log(f"Workers AI script notice: {e}")

    # 2. Try NVIDIA NIM if available
    if not raw_json and NVIDIA_API_KEY:
        try:
            headers = {"Authorization": f"Bearer {NVIDIA_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": "meta/llama-3.1-70b-instruct",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.6,
                "max_tokens": 800,
            }
            res = requests.post("https://integrate.api.nvidia.com/v1/chat/completions", headers=headers, json=payload, timeout=30)
            if res.ok:
                raw_json = res.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log(f"NVIDIA script notice: {e}")

    # Parse JSON or fallback
    script = ""
    scenes = []
    if raw_json:
        try:
            cleaned = raw_json.strip()
            if "```json" in cleaned:
                cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in cleaned:
                cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()
            data = json.loads(cleaned)
            script = data.get("narration", "").strip()
            scenes = data.get("scenes", [])
        except Exception:
            pass

    # Procedural Fallback if LLM parsing failed
    if not script or not scenes:
        log("Running procedural vertical screenwriter fallback...", "Structuring Reel", 15)
        clean_topic = PROMPT.strip().rstrip(".")
        script = (
            f"What if the secrets of {clean_topic} are far more profound than we ever imagined? "
            f"Beneath the visible surface lies a hidden dimension of power, mystery, and awe. "
            f"Every single detail reshapes our understanding of reality."
        )
        scenes = [
            {"id": 1, "visual_description": f"{clean_topic}, opening hook, hyperrealistic vertical cinematic lighting", "pixabay_query": f"{clean_topic} landscape"},
            {"id": 2, "visual_description": f"{clean_topic}, hidden depth, dramatic atmosphere", "pixabay_query": f"{clean_topic} nature"},
            {"id": 3, "visual_description": f"{clean_topic}, grand finale reveal, majestic vista 8k", "pixabay_query": f"{clean_topic} cosmic"}
        ]

    log(f"Reel script generated ({len(script.split())} words, {len(scenes)} scenes)", "Script & Structure ready", 20)
    return script, scenes


# --- Stage 2: Voiceover (Edge-TTS) ------------------------------------------
def generate_voiceover(script: str, output_path: str = "voice.mp3") -> float:
    log(f"Generating voiceover via Edge-TTS ({EDGE_VOICE})", "Generating Voiceover", 35)
    clean_text = script.strip()[:4000]
    result = subprocess.run(
        [
            sys.executable, "-m", "edge_tts",
            "--voice", EDGE_VOICE,
            "--rate", EDGE_RATE,
            "--pitch", EDGE_PITCH,
            "--text", clean_text,
            "--write-media", output_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Edge-TTS failed: {result.stderr or result.stdout}")

    dur = get_media_duration(output_path)
    log(f"Voiceover track ready ({dur:.2f}s)", progress=45)
    return dur

def get_media_duration(path: str) -> float:
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ]
        out = subprocess.check_output(cmd, text=True).strip()
        return max(1.0, float(out))
    except Exception:
        return float(DURATION)


# --- Stage 3: Image Generation (Pixabay API & Flux.1 [schnell]) -------------
def upscale_to_canvas(source: str, target: str) -> None:
    """Upscales visual to exact 9:16 vertical canvas (1080x1920) with headroom for pan/zoom."""
    w_head = round(WIDTH * 1.15)
    h_head = round(HEIGHT * 1.15)
    cmd = [
        "ffmpeg", "-y", "-i", source,
        "-vf",
        f"scale={w_head}:{h_head}:force_original_aspect_ratio=increase:flags=lanczos,crop={w_head}:{h_head},unsharp=3:3:0.4",
        "-q:v", "2", target,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        shutil.copyfile(source, target)

def save_binary_or_b64(response: requests.Response, path: str, keys: tuple[str, ...]) -> None:
    content_type = response.headers.get("Content-Type", "")
    if "image" in content_type:
        with open(path, "wb") as f:
            f.write(response.content)
        return

    try:
        body = response.json()
    except Exception:
        with open(path, "wb") as f:
            f.write(response.content)
        return

    candidates = [body]
    if isinstance(body.get("result"), dict):
        candidates.insert(0, body["result"])
    if isinstance(body.get("output"), dict):
        candidates.insert(0, body["output"])

    for item in candidates:
        for key in ("url", "image_url"):
            if isinstance(item.get(key), str) and item[key].startswith("http"):
                res = requests.get(item[key], timeout=120)
                with open(path, "wb") as f:
                    f.write(res.content)
                return
        for key in keys:
            val = item.get(key)
            if isinstance(val, str) and val:
                payload = val.split(",", 1)[-1] if val.startswith("data:") else val
                with open(path, "wb") as f:
                    f.write(base64.b64decode(payload))
                return
    raise RuntimeError("Provider response contained no valid image data")

def fetch_pixabay_vertical_image(query: str, path: str) -> bool:
    if not PIXABAY_API_KEY:
        return False
    try:
        url = "https://pixabay.com/api/"
        params = {
            "key": PIXABAY_API_KEY,
            "q": query[:100],
            "image_type": "photo",
            "orientation": "vertical",
            "safesearch": "true",
            "per_page": 5,
        }
        res = requests.get(url, params=params, timeout=15)
        if res.ok:
            hits = res.json().get("hits", [])
            if hits:
                img_url = hits[0].get("largeImageURL") or hits[0].get("imageURL") or hits[0].get("webformatURL")
                if img_url:
                    img_data = requests.get(img_url, timeout=30).content
                    raw_path = f"raw_{path}"
                    with open(raw_path, "wb") as f:
                        f.write(img_data)
                    upscale_to_canvas(raw_path, path)
                    return True
    except Exception as e:
        log(f"Pixabay visual search notice: {e}")
    return False

def generate_flux_schnell_image(prompt: str, path: str) -> bool:
    """Generates AI scene visual using Flux.1 [schnell] model."""
    full_prompt = f"vertical 9:16 framing, {prompt}, {IMAGE_STYLE}, high resolution, award winning, masterpiece"[:1900]
    seed = int(hashlib.sha256(full_prompt.encode("utf-8")).hexdigest()[:8], 16)

    # 1. Try Cloudflare Workers AI FLUX.1 [schnell]
    if CF_ACCOUNT_ID and CF_API_TOKEN:
        try:
            body = {"prompt": full_prompt, "seed": seed, "steps": 6}
            res = cloudflare_run("@cf/black-forest-labs/flux-1-schnell", body)
            raw_path = f"raw_{path}"
            save_binary_or_b64(res, raw_path, ("b64_json", "image", "image_base64"))
            upscale_to_canvas(raw_path, path)
            return True
        except Exception as e:
            log(f"Cloudflare Flux.1 [schnell] notice: {e}")

    # 2. Try Pixazo API Flux
    if PIXAZO_API_KEY:
        try:
            res = requests.post(
                f"{PIXAZO_BASE_URL}/v1/images/generations",
                headers={"Authorization": f"Bearer {PIXAZO_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": PIXAZO_IMAGE_MODEL,
                    "prompt": full_prompt,
                    "negative_prompt": NEGATIVE_PROMPT,
                    "width": WIDTH,
                    "height": HEIGHT,
                    "n": 1,
                },
                timeout=180,
            )
            if res.ok:
                raw_path = f"raw_{path}"
                save_binary_or_b64(res, raw_path, ("b64_json", "image", "image_base64"))
                upscale_to_canvas(raw_path, path)
                return True
        except Exception as e:
            log(f"Pixazo Flux image notice: {e}")

    return False

def source_scene_visuals(scenes: list[dict]) -> list[str]:
    """
    Fetches scene visuals using Pixabay API and Flux.1 [schnell] AI image generation.
    Ensures every scene has a gorgeous, 9:16 vertical asset ready.
    """
    log(f"Sourcing {len(scenes)} scene visuals (Pixabay API + Flux.1 [schnell])...", "Generating Visuals", 50)
    image_paths = []
    os.makedirs("assets/reel_scenes", exist_ok=True)

    for idx, sc in enumerate(scenes):
        target_path = f"assets/reel_scenes/scene_{idx:02d}.jpg"
        desc = sc.get("visual_description", PROMPT)
        query = sc.get("pixabay_query", PROMPT)

        success = False
        # 1. Fetch via Pixabay API using query
        if PIXABAY_API_KEY:
            success = fetch_pixabay_vertical_image(query, target_path)
            if success:
                log(f"Scene {idx+1}/{len(scenes)} fetched via Pixabay API ('{query}')")

        # 2. Fetch AI visual using Flux.1 [schnell] model
        if not success:
            success = generate_flux_schnell_image(desc, target_path)
            if success:
                log(f"Scene {idx+1}/{len(scenes)} generated via Flux.1 [schnell]")

        # 3. Fallback: Solid procedural gradient with vignette
        if not success:
            log(f"Scene {idx+1}: applying procedural visual fallback")
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "lavfi",
                    "-i", f"color=c=0x111625:s={round(WIDTH*1.15)}x{round(HEIGHT*1.15)}:d=1",
                    "-vf", "drawbox=x=0:y=0:w=iw:h=ih:color=white@0.05:t=fill",
                    "-frames:v", "1", target_path,
                ],
                check=True,
                capture_output=True,
            )

        image_paths.append(target_path)

    return image_paths


# --- Stage 4: Caption Rendering (Dynamic Animated Subtitles) ----------------
def ass_timestamp(seconds: float) -> str:
    centis = int(round(seconds * 100))
    hours, centis = divmod(centis, 360_000)
    minutes, centis = divmod(centis, 6_000)
    secs, centis = divmod(centis, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"

def generate_animated_ass_captions(script: str, total_duration: float, path: str = "captions.ass") -> str:
    """
    Renders dynamic animated subtitle overlays for 9:16 vertical reels.
    Features:
    - 2-4 words per cue for viral reel pacing
    - Dynamic scale-pop on entry: {\\t(0, 100, \\fscx115\\fscy115)\\t(100, 220, \\fscx100\\fscy100)}
    - High-visibility font with dark outline and drop shadow in safe zone
    """
    words = script.split()
    if not words:
        words = [PROMPT]

    cues: list[list[str]] = []
    curr: list[str] = []
    for w in words:
        curr.append(w)
        if len(curr) >= 3 or len(" ".join(curr)) >= 18:
            cues.append(curr)
            curr = []
    if curr:
        if cues and len(curr) < 2:
            cues[-1].extend(curr)
        else:
            cues.append(curr)

    weight = sum(len(" ".join(c)) for c in cues) or 1
    font_size = round(56 * (CAPTION_SCALE / 4.0))
    margin_v = round(HEIGHT * 0.16)  # Safe bottom area above UI controls
    margin_h = round(WIDTH * 0.08)

    # Style: Yellow primary (&H0000FFFF) with black outline (&H00000000)
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        f"PlayResX: {WIDTH}\n"
        f"PlayResY: {HEIGHT}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: ReelPopup,DejaVu Sans,{font_size},&H0000FFFF,&H0000FFFF,&H00000000,"
        f"&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,{margin_h},{margin_h},{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    clock = 0.0
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        for cue in cues:
            raw_text = " ".join(cue).upper()
            span = max(0.45, total_duration * (len(raw_text) / weight))
            start_t = clock
            end_t = min(total_duration, clock + span)
            clock = end_t
            # Dynamic animated scale pop effect
            animated_text = f"{{\\t(0,90,\\fscx118\\fscy118)\\t(90,190,\\fscx100\\fscy100)}}{raw_text}"
            f.write(
                f"Dialogue: 0,{ass_timestamp(start_t)},{ass_timestamp(end_t)},ReelPopup,,0,0,0,,{animated_text}\n"
            )

    log(f"Dynamic animated captions compiled ({len(cues)} cues)", "Rendering Captions", 70)
    return path


# --- Stage 5: Assembly (FFmpeg Vertical .mp4) --------------------------------
def zoom_filter(index: int, frames: int) -> str:
    span = 0.12
    zoom_in = (index % 2 == 0)
    if zoom_in:
        return f"1.0+{span}*on/{frames}"
    return f"{1.0+span}-{span}*on/{frames}"

def assemble_reel(scenes: list[str], voice_path: str, script: str, audio_dur: float) -> str:
    log("Assembling vertical 9:16 reel with FFmpeg...", "Compiling Reel", 75)
    total_dur = round(audio_dur + 0.5, 3)
    num_scenes = len(scenes)
    per_scene = (total_dur + FADE * (num_scenes - 1)) / num_scenes

    inputs = []
    for p in scenes:
        inputs += ["-loop", "1", "-t", f"{per_scene + 0.6:.3f}", "-i", p]
    inputs += ["-i", voice_path]

    chains = []
    for i in range(num_scenes):
        frames = max(2, int(round(per_scene * FPS)))
        z = zoom_filter(i, frames)
        chain = (
            f"[{i}:v]"
            f"scale={round(WIDTH * 1.15)}:{round(HEIGHT * 1.15)}:force_original_aspect_ratio=increase,"
            f"crop={round(WIDTH * 1.15)}:{round(HEIGHT * 1.15)},"
            f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
            f"trim=duration={per_scene:.3f},setpts=PTS-STARTPTS,fps={FPS},format=yuv420p[v{i}]"
        )
        chains.append(chain)

    last = "v0"
    offset = per_scene - FADE
    for i in range(1, num_scenes):
        out_tag = f"x{i}"
        chains.append(
            f"[{last}][v{i}]xfade=transition=fade:duration={FADE}:offset={offset:.3f}[{out_tag}]"
        )
        last = out_tag
        offset += per_scene - FADE

    video_tail = ["fade=t=in:st=0:d=0.4", f"fade=t=out:st={max(0.0, total_dur - 0.5):.3f}:d=0.5"]

    # Check User Captions Toggle
    if CAPTIONS:
        ass_path = generate_animated_ass_captions(script, audio_dur)
        video_tail.append(f"subtitles={ass_path}")
        log("Captions = ON: dynamic animated subtitles embedded in video stream")
    else:
        log("Captions = OFF: skipping subtitle overlay")

    video_tail.append("format=yuv420p")
    chains.append(f"[{last}]{','.join(video_tail)}[vout]")
    chains.append(
        f"[{num_scenes}:a]apad,atrim=0:{total_dur:.3f},"
        f"afade=t=out:st={max(0.0, total_dur - 0.4):.3f}:d=0.4,asetpts=N/SR/TB[aout]"
    )

    out_file = "out.mp4"
    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(chains),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-b:v", VIDEO_BITRATE,
        "-c:a", "aac", "-b:a", "192k",
        "-r", str(FPS), "-t", f"{total_dur:.3f}", "-movflags", "+faststart",
        out_file,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg render error: {res.stderr[-500:]}")

    log(f"Reel assembly finished ({total_dur:.1f}s, 1080x1920 @ {FPS}fps)", progress=88)
    return out_file


# --- Main Execution ---------------------------------------------------------
def main() -> int:
    try:
        log("Starting Short-Form Pipeline: 'Create Reel' (Python Engine / 'mini-editor/')", "Initializing Reel Pipeline", 5)
        log(f"Target: 9:16 Vertical (1080x1920) · Captions: {'ON (Animated)' if CAPTIONS else 'OFF'}")

        # 1. Script & Structure
        script, scenes = generate_script_and_timeline()

        # 2. Voiceover (Edge-TTS)
        voice_path = "voice.mp3"
        audio_dur = generate_voiceover(script, voice_path)

        # 3. Image Generation (Pixabay API + Flux.1 [schnell])
        visual_paths = source_scene_visuals(scenes)

        # 4 & 5. Caption Rendering (Conditional) & Assembly
        out_mp4 = assemble_reel(visual_paths, voice_path, script, audio_dur)

        log("Reel render complete!", "Render Complete", 92)
        return 0
    except Exception as e:
        err = f"Reel pipeline error: {e}"
        log(err, "failed")
        patch_supabase({"status": "failed", "step": "failed", "error": err})
        return 1

if __name__ == "__main__":
    sys.exit(main())
