"""Reference render script for tkdasofficial/video-agent.

Copy to the repo root as `render.py` (alongside `requirements.txt`).

Pipeline
--------
1. Cloudflare Workers AI (Llama instruct models) writes the narration script and
   the per-scene image prompts (the "brain").
2. Images: FLUX.1 [schnell] on Cloudflare Workers AI (free tier). Pixazo AI is an
   optional fallback when PIXAZO_API_KEY is configured.
3. Narration: Microsoft Edge TTS (`edge-tts`) - free, no API key, neural voices.
4. FFmpeg composes the scenes with smooth Ken Burns zoom in/out, cross-fade
   transitions between scenes, and white captions (3-5 words per cue) burned in.

The selected duration is a target window, not a hard stretch: narration is never
sped up, slowed down or clipped mid-sentence, so Edge TTS output stays natural.

Progress is written back to Supabase so the Lovable UI terminal streams it live.
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

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
VIDEO_ID = os.environ["VIDEO_ID"]


def env(name: str, default: str = "") -> str:
    """Unset or blank GitHub Action inputs arrive as empty strings."""
    return (os.environ.get(name) or "").strip() or default


PROMPT = env("PROMPT")
NEGATIVE_PROMPT = env("NEGATIVE_PROMPT")
VOICE_GENDER = env("VOICE_GENDER", "female").lower()
IMAGE_STYLE = env("IMAGE_STYLE", "realistic photography with natural colors, lit by natural sunlight")
MOTION_TEMPLATE = env("MOTION_TEMPLATE", "Auto Zoom-In")
ASPECT_RATIO = env("ASPECT_RATIO", "9:16")
QUALITY = env("QUALITY", "1080p")
BITRATE = env("BITRATE", "High")

# `CAPTIONS` doubles as the caption size switch so the GitHub dispatch payload
# stays inside the 10-property limit: false | true/small | medium | large.
CAPTIONS_RAW = env("CAPTIONS", "false").lower()
CAPTIONS = CAPTIONS_RAW in {"1", "true", "yes", "on", "small", "medium", "large"}
CAPTION_SIZE = CAPTIONS_RAW if CAPTIONS_RAW in {"small", "medium", "large"} else "small"

try:
    CAPTION_SCALE = max(1, min(10, int(float(env("CAPTION_SCALE", "4")))))
except ValueError:
    CAPTION_SCALE = 4

try:
    DURATION = max(1, min(60, int(float(env("DURATION_SECONDS", "15")))))
except ValueError:
    DURATION = 15

# --- Providers -------------------------------------------------------------
# Images: FLUX.1 [schnell] on Workers AI is primary (free). Pixazo is optional.
PIXAZO_API_KEY = env("PIXAZO_API_KEY")
PIXAZO_BASE_URL = env("PIXAZO_BASE_URL", "https://api.pixazo.ai").rstrip("/")
if not PIXAZO_BASE_URL.startswith(("http://", "https://")):
    PIXAZO_BASE_URL = f"https://{PIXAZO_BASE_URL}"
PIXAZO_IMAGE_MODEL = env("PIXAZO_IMAGE_MODEL", "pixazo-image-free")

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
# Workers AI retires older model ids (HTTP 410 Gone), so try current ones in order.
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

# --- Edge TTS (free, key-less neural voices) --------------------------------
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
# Energetic short-form delivery without sounding rushed.
EDGE_RATE = env("EDGE_TTS_RATE", "+8%")
EDGE_PITCH = env("EDGE_TTS_PITCH", "+0Hz")

SIZES_1080 = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}
SIZES_720 = {"9:16": (720, 1280), "16:9": (1280, 720), "1:1": (720, 720)}
SIZES = SIZES_720 if QUALITY == "720p" else SIZES_1080
WIDTH, HEIGHT = SIZES.get(ASPECT_RATIO, SIZES["9:16"])
VIDEO_BITRATE = "5M" if BITRATE == "High" else "2500k"

FPS = 30
# Cross-fade length between two scenes.
FADE = 0.6

# One scene per ~5 seconds, at least two, at most eight.
SCENE_COUNT = max(2, min(8, math.ceil(DURATION / 5)))


# --- Supabase progress -----------------------------------------------------
def patch(payload: dict) -> None:
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/videos?id=eq.{VIDEO_ID}",
        headers={
            "apikey": SERVICE_KEY,
            "Authorization": f"Bearer {SERVICE_KEY}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload),
        timeout=30,
    )


def log(message: str, step: str | None = None, progress: int | None = None) -> None:
    print(message, flush=True)
    payload: dict = {"logs": message}
    if step:
        payload["step"] = step
    if progress is not None:
        payload["progress"] = progress
    patch(payload)


# --- Stage A: the brain (Cloudflare Workers AI) -----------------------------
def cloudflare_run(model: str, body: dict, *, timeout: int = 180) -> requests.Response:
    if not (CF_ACCOUNT_ID and CF_API_TOKEN):
        raise RuntimeError("CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN are not configured")
    response = requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{model}",
        headers={"Authorization": f"Bearer {CF_API_TOKEN}"},
        # Workers AI rejects null values, so never send empty fields.
        json={key: value for key, value in body.items() if value not in (None, "")},
        timeout=timeout,
    )
    if not response.ok:
        raise RuntimeError(
            f"Workers AI {model} failed ({response.status_code}): {response.text[:300]}"
        )
    return response


# Edge TTS speaks at roughly 150 wpm with the rate above. The script is written
# for the middle of a flexible window so the finished audio lands naturally
# inside it instead of being stretched or clipped.
WPM = 150
TOLERANCE = 0.20  # +/-20%: a 30s target accepts ~25-36s of narration


def word_window(duration: int) -> tuple[int, int, int]:
    """(minimum, target, maximum) words for a flexible duration window."""
    duration = max(1, min(60, int(duration)))
    target = max(6, round(duration * WPM / 60))
    return (
        max(5, round(target * (1 - TOLERANCE))),
        target,
        max(8, round(target * (1 + TOLERANCE))),
    )


WORD_MIN, WORD_TARGET, WORD_MAX = word_window(DURATION)

NATURE_STYLE_PREFIX = (
    "humanless scenery with realistic composition, natural textures and believable light, no people"
)
HUMANLESS_NEGATIVE = "human, person, face, character, crowd, watermark, text"


def image_prompt(scene_prompt: str) -> str:
    """Humanless scene prompt builder shared by every image provider."""
    return f"{NATURE_STYLE_PREFIX}, {scene_prompt}, {IMAGE_STYLE}"[:1900]


def image_negative_prompt() -> str:
    extra = NEGATIVE_PROMPT.strip().strip(",")
    return f"{HUMANLESS_NEGATIVE}, {extra}" if extra else HUMANLESS_NEGATIVE


def trim_to_window(script: str) -> str:
    """Trim only when the script overruns the flexible window, at a sentence end."""
    words = script.split()
    if len(words) <= WORD_MAX:
        return script.strip()
    kept: list[str] = []
    last_sentence_end = 0
    for index, word in enumerate(words[:WORD_MAX]):
        kept.append(word)
        if word.endswith((".", "!", "?")):
            last_sentence_end = index + 1
    if last_sentence_end >= WORD_MIN:
        kept = kept[:last_sentence_end]
    trimmed = " ".join(kept).rstrip(" ,;:-")
    if not trimmed.endswith((".", "!", "?")):
        trimmed += "."
    log(f"Script trimmed to {len(trimmed.split())} words for the {DURATION}s window")
    return trimmed


def cf_chat(system: str, user: str, *, max_tokens: int = 700) -> str:
    """Runs a chat prompt through the first Workers AI model that answers."""
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
        except Exception as error:  # noqa: BLE001 - retired/unavailable model, try the next
            log(f"Script model {model} unavailable ({error}); trying the next one")
            continue

        # Workers AI response shapes: {"result":{"response":"..."}} or {"response":"..."}
        result = raw.get("result") if isinstance(raw, dict) else None
        if not isinstance(result, dict):
            result = raw if isinstance(raw, dict) else {}
        candidate = result.get("response")
        if candidate is None:
            candidate = result.get("result")
        if isinstance(candidate, dict):
            candidate = candidate.get("response") or candidate.get("text")
        text = "" if candidate is None else str(candidate).strip()
        if text and text.lower() != "none":
            return text
    return ""


def clean_script(text: str) -> str:
    """Strips list markers, labels and quotes an instruct model likes to add."""
    if not text:
        return ""
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict) and parsed.get("script"):
                text = str(parsed["script"])
        except json.JSONDecodeError:
            pass
    lines = []
    for line in text.splitlines():
        line = line.strip().strip("`").strip()
        low = line.lower()
        if not line or low.startswith(("script:", "narration:", "here", "note:", "scene")):
            continue
        lines.append(line.lstrip("-*0123456789. ").strip('"'))
    return " ".join(lines).strip()


def ensure_script_length(script: str, minimum_words: int) -> str:
    """Keep narration dense enough to fill the lower edge of the window."""
    if len(script.split()) >= minimum_words:
        return trim_to_window(script)

    expanded = clean_script(
        cf_chat(
            "You expand narration for humanless nature and cosmic short films. "
            "Reply with narration sentences only.",
            f"Topic: {PROMPT}\nCurrent narration: {script}\n"
            f"Rewrite this as {minimum_words} to {WORD_TARGET} flowing words. "
            "Keep the meaning, use no humans, labels, lists, or stage directions.",
            max_tokens=500,
        )
    )
    if len(expanded.split()) >= minimum_words:
        return trim_to_window(expanded)

    pieces = [script or PROMPT]
    bridges = [
        "Across this vast scene, light and motion reveal details shaped quietly through time.",
        "Colors drift through the landscape while distant forms create depth, rhythm, and wonder.",
        "Every changing texture invites a closer look at the beauty held within this world.",
        "The view continues beyond the horizon, calm, immense, and alive with subtle movement.",
    ]
    index = 0
    while len(" ".join(pieces).split()) < minimum_words:
        pieces.append(bridges[index % len(bridges)])
        index += 1
    return trim_to_window(" ".join(pieces))


def parse_scenes(text: str) -> list[str]:
    """Reads one image prompt per line (or from a JSON array) out of the reply."""
    scenes: list[str] = []
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, list):
                scenes = [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            scenes = []
    if not scenes:
        for line in text.splitlines():
            line = line.strip().lstrip("-*0123456789. ").strip('"').strip()
            if len(line) > 12 and not line.lower().startswith(("here", "note", "scene prompts")):
                scenes.append(line)
    return scenes


SCENE_VARIATIONS = [
    "sweeping establishing wide shot",
    "close orbital detail shot",
    "dramatic low-angle vista",
    "glowing nebula backdrop with depth",
    "macro texture detail",
    "silhouetted horizon at golden light",
    "top-down aerial perspective",
    "distant scale shot with layered depth",
]


def write_script() -> tuple[str, list[str]]:
    """Returns (narration script, one image prompt per scene)."""
    log(f"Writing the ~{DURATION}s script with Cloudflare Workers AI", "Writing script", 12)

    script = clean_script(
        cf_chat(
            "You are a narrator for short visual stories without human characters. "
            "Reply with the narration sentences only — no titles, labels, lists or notes.",
            f"Topic: {PROMPT}\n"
            f"Write flowing narration of about {WORD_TARGET} words (between {WORD_MIN} and "
            f"{WORD_MAX}) so it reads aloud in roughly {DURATION} seconds. "
            "End on a complete sentence. No humans or characters, no stage directions, "
            "no hashtags.",
            max_tokens=500,
        )
    )
    if not script:
        log("Script model gave no usable text; narrating the prompt directly", None, None)
        script = PROMPT
    script = ensure_script_length(script, WORD_MIN)
    log(f"Script ready ({len(script.split())} words · window {WORD_MIN}-{WORD_MAX})")

    scenes = parse_scenes(
        cf_chat(
            "You write image-generation prompts. Reply with one prompt per line, nothing else.",
            f"Story: {script}\n"
            f"Write exactly {SCENE_COUNT} distinct image prompts in the '{IMAGE_STYLE}' style "
            "covering different moments of this story. Each prompt is one line, 15-30 words, "
            "showing clear, believable scenery that follows the story — never humans, faces, "
            "characters or text.\n"
            f"Avoid: {NEGATIVE_PROMPT or 'nothing in particular'}.",
            max_tokens=700,
        )
    )
    while len(scenes) < SCENE_COUNT:
        variation = SCENE_VARIATIONS[len(scenes) % len(SCENE_VARIATIONS)]
        scenes.append(f"{PROMPT}, {variation}, {IMAGE_STYLE}")
    return script, scenes[:SCENE_COUNT]


# --- Stage B: FLUX.1 [schnell] images + Edge TTS narration ------------------
def save_binary_or_b64(response: requests.Response, path: str, keys: tuple[str, ...]) -> None:
    """Writes a provider response to `path`, accepting raw bytes, base64 or a URL."""
    if "application/json" not in response.headers.get("content-type", ""):
        with open(path, "wb") as handle:
            handle.write(response.content)
        return

    body = response.json()
    candidates: list[dict] = [body]
    if isinstance(body.get("data"), list) and body["data"]:
        candidates.insert(0, body["data"][0])
    if isinstance(body.get("result"), dict):
        candidates.insert(0, body["result"])
    if isinstance(body.get("output"), dict):
        candidates.insert(0, body["output"])

    for item in candidates:
        for key in ("url", "image_url"):
            if isinstance(item.get(key), str) and item[key].startswith("http"):
                with open(path, "wb") as handle:
                    handle.write(requests.get(item[key], timeout=240).content)
                return
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value:
                payload = value.split(",", 1)[-1] if value.startswith("data:") else value
                with open(path, "wb") as handle:
                    handle.write(base64.b64decode(payload))
                return
    raise RuntimeError(f"Provider response contained no media: {json.dumps(body)[:300]}")


def cloudflare_image(scene_prompt: str, path: str) -> None:
    """FLUX.1 [schnell] first (free tier), then the SDXL models as fallback."""
    prompt = image_prompt(scene_prompt)
    errors: list[str] = []
    for model in CF_IMAGE_MODELS:
        if "flux" in model:
            # FLUX.1 [schnell] on Workers AI accepts prompt + steps + seed only.
            seed = int(hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8], 16)
            body = {"prompt": prompt, "seed": seed, "steps": 6}
        else:
            body = {
                "prompt": prompt,
                "negative_prompt": image_negative_prompt(),
                "width": min(WIDTH, 1024),
                "height": min(HEIGHT, 1024),
            }
        try:
            response = cloudflare_run(model, body)
            save_binary_or_b64(response, f"raw_{path}", ("b64_json", "image", "image_base64"))
            upscale_to_canvas(f"raw_{path}", path)
            return
        except Exception as error:  # noqa: BLE001 - try the next image model
            errors.append(f"{model}: {error}")
    raise RuntimeError("no Workers AI image model succeeded — " + " | ".join(errors))


def upscale_to_canvas(source: str, target: str) -> None:
    """Lanczos-upscale a model image to the exact Full HD vertical/landscape canvas."""
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", source,
            "-vf",
            # A little headroom (1.15x) so the Ken Burns zoom never shows an edge.
            f"scale={round(WIDTH * 1.15)}:{round(HEIGHT * 1.15)}:"
            "force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={round(WIDTH * 1.15)}:{round(HEIGHT * 1.15)},unsharp=3:3:0.4",
            "-q:v", "2", target,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Fall back to the raw image rather than failing the whole render.
        shutil.copyfile(source, target)


def pixazo_image(scene_prompt: str, path: str) -> None:
    if not PIXAZO_API_KEY:
        raise RuntimeError("PIXAZO_API_KEY is not configured")
    response = requests.post(
        f"{PIXAZO_BASE_URL}/v1/images/generations",
        headers={
            "Authorization": f"Bearer {PIXAZO_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": PIXAZO_IMAGE_MODEL,
            "prompt": image_prompt(scene_prompt),
            "negative_prompt": image_negative_prompt(),
            "width": WIDTH,
            "height": HEIGHT,
            "n": 1,
        },
        timeout=240,
    )
    response.raise_for_status()
    save_binary_or_b64(response, f"raw_{path}", ("b64_json", "image", "image_base64"))
    upscale_to_canvas(f"raw_{path}", path)


def generate_scenes(scene_prompts: list[str]) -> list[str]:
    log(
        f"Generating {len(scene_prompts)} scene images at {WIDTH}x{HEIGHT} "
        "with FLUX.1 [schnell]",
        "Generating scenes",
        28,
    )
    paths: list[str] = []
    for index, scene_prompt in enumerate(scene_prompts):
        path = f"scene_{index}.jpg"
        try:
            cloudflare_image(scene_prompt, path)
        except Exception as error:  # noqa: BLE001 - optional Pixazo fallback
            log(f"FLUX images unavailable ({error}); trying Pixazo AI")
            pixazo_image(scene_prompt, path)
        paths.append(path)
        log(f"scene {index + 1}/{len(scene_prompts)} ready")
    return paths


def generate_voice(script: str) -> str:
    """Narration via Microsoft Edge TTS — free, no API key, neural voices."""
    log(f"Synthesising narration with Edge TTS ({EDGE_VOICE})", "Generating voice", 52)
    path = "voice.mp3"
    text = script.strip()[:4000]
    result = subprocess.run(
        [
            sys.executable, "-m", "edge_tts",
            "--voice", EDGE_VOICE,
            "--rate", EDGE_RATE,
            "--pitch", EDGE_PITCH,
            "--text", text,
            "--write-media", path,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not os.path.exists(path) or os.path.getsize(path) < 1024:
        detail = (result.stderr or result.stdout or "").strip()[-300:]
        raise RuntimeError(f"Edge TTS failed: {detail}")
    return path


# --- Stage C: captions + FFmpeg composition --------------------------------
def audio_duration(path: str) -> float:
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path,
        ],
        capture_output=True, text=True, check=True,
    )
    try:
        return max(float(probe.stdout.strip()), 1.0)
    except ValueError:
        return float(DURATION)


def ass_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    centis = int(round(seconds * 100))
    hours, centis = divmod(centis, 360_000)
    minutes, centis = divmod(centis, 6_000)
    secs, centis = divmod(centis, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"


# White-only caption sizing, measured on a 1080x1920 canvas.
CAPTION_SIZES = {"small": 44, "medium": 58, "large": 74}


def write_ass(script: str, total: float, path: str = "captions.ass") -> str:
    """Bottom-centre white captions, 3-5 words per cue, sized by CAPTION_SIZE.

    An ASS file is generated directly (instead of an SRT + force_style) because
    force_style sizes are relative to libass' default 384x288 script resolution.
    """
    words = script.split()
    if not words:
        words = [PROMPT or "…"]

    # 3-5 words per cue: pack up to 5 short words, break earlier on long ones.
    cues: list[list[str]] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        chars = len(" ".join(current))
        if len(current) >= 5 or (len(current) >= 3 and chars > 22):
            cues.append(current)
            current = []
    if current:
        if len(current) < 3 and cues:
            cues[-1].extend(current)
        else:
            cues.append(current)
    weight = sum(len(" ".join(c)) for c in cues) or 1

    base = CAPTION_SIZES.get(CAPTION_SIZE, CAPTION_SIZES["small"])
    font_size = max(22, round(HEIGHT * base / 1920 * (CAPTION_SCALE / 4)))
    # Alignment 2 = bottom centre; the baseline sits at roughly 88% of the canvas.
    margin_v = max(24, round(HEIGHT * 0.10))
    margin_h = max(40, round(WIDTH * 0.08))

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
        # Pure white text (&H00FFFFFF) with a black outline for dark cosmic footage.
        f"Style: Caption,DejaVu Sans,{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,"
        f"&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,{margin_h},{margin_h},{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    clock = 0.0
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(header)
        for cue in cues:
            text = " ".join(cue).replace("\n", " ")
            span = max(0.5, total * (len(text) / weight))
            start, end = clock, min(total, clock + span)
            clock = end
            handle.write(
                f"Dialogue: 0,{ass_timestamp(start)},{ass_timestamp(end)},Caption,,0,0,0,,{text}\n"
            )
    log(f"Burning {len(cues)} white caption cues ({CAPTION_SIZE})", "Rendering captions", 68)
    return path


def zoom_expression(index: int, frames: int) -> str:
    """Smooth linear Ken Burns that starts and ends exactly with the scene.

    Linear in `on` (frame number) rather than incremental, so there is no
    stutter, no accumulation drift and no abrupt jump at the scene boundary.
    """
    span = 0.14
    if MOTION_TEMPLATE == "Pan & Scan":
        return "1.08"
    if MOTION_TEMPLATE == "Fade Transitions":
        span = 0.06
    if MOTION_TEMPLATE == "Auto Zoom-In":
        zoom_in = True
    else:
        # Dynamic Keyframe (and Pan & Scan panning) alternate in / out per scene.
        zoom_in = index % 2 == 0
    if zoom_in:
        return f"1.0+{span}*on/{frames}"
    return f"{1.0 + span}-{span}*on/{frames}"


def scene_filter(index: int, seconds: float) -> str:
    """Per-scene chain: canvas fit, smooth zoom, frame rate, pixel format."""
    frames = max(2, int(round(seconds * FPS)))
    zoom = zoom_expression(index, frames)
    pan_x = (
        f"iw/2-(iw/zoom/2)+sin(on/{max(20, frames)}*3.14159)*(iw*0.04)"
        if MOTION_TEMPLATE == "Pan & Scan"
        else "iw/2-(iw/zoom/2)"
    )
    return (
        f"scale={round(WIDTH * 1.15)}:{round(HEIGHT * 1.15)}:"
        "force_original_aspect_ratio=increase,"
        f"crop={round(WIDTH * 1.15)}:{round(HEIGHT * 1.15)},"
        f"zoompan=z='{zoom}':x='{pan_x}':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
        f"trim=duration={seconds:.3f},setpts=PTS-STARTPTS,"
        f"fps={FPS},format=yuv420p"
    )


def compose(scenes: list[str], voice: str, script: str) -> None:
    log("Composing final video with FFmpeg", "Rendering video", 78)
    narration = audio_duration(voice)

    # The narration is never stretched or clipped: it defines the runtime, with a
    # short breathing tail. The selected duration is only a target window.
    total = round(narration + 0.6, 3)
    count = len(scenes)
    # Scenes overlap by FADE, so each clip is a little longer than its share.
    per_scene = (total + FADE * (count - 1)) / count

    inputs: list[str] = []
    for path in scenes:
        inputs += ["-loop", "1", "-t", f"{per_scene + 0.5:.3f}", "-i", path]
    inputs += ["-i", voice]

    chains = [f"[{i}:v]{scene_filter(i, per_scene)}[v{i}]" for i in range(count)]

    # Cross-fade each scene into the next for a polished switch.
    last = "v0"
    offset = per_scene - FADE
    for i in range(1, count):
        out = f"x{i}"
        chains.append(
            f"[{last}][v{i}]xfade=transition=fade:duration={FADE}:offset={offset:.3f}[{out}]"
        )
        last = out
        offset += per_scene - FADE

    video_tail = [f"fade=t=in:st=0:d=0.5", f"fade=t=out:st={max(0.0, total - 0.6):.3f}:d=0.6"]
    if CAPTIONS:
        video_tail.append(f"subtitles={write_ass(script, narration)}")
    else:
        log("Captions disabled for this render", None, None)
    video_tail.append("format=yuv420p")
    chains.append(f"[{last}]{','.join(video_tail)}[v]")

    chains.append(
        f"[{count}:a]apad,atrim=0:{total:.3f},"
        f"afade=t=out:st={max(0.0, total - 0.5):.3f}:d=0.5,asetpts=N/SR/TB[a]"
    )

    command = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(chains),
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-b:v", VIDEO_BITRATE,
        "-c:a", "aac", "-b:a", "192k",
        "-r", str(FPS), "-t", f"{total:.3f}", "-movflags", "+faststart",
        "out.mp4",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()[-6:]
        raise RuntimeError("FFmpeg failed: " + " | ".join(detail))
    log(f"Final video {total:.1f}s (narration {narration:.1f}s · target {DURATION}s)")


def main() -> int:
    try:
        log(
            f"Video Agent starting · ~{DURATION}s · {ASPECT_RATIO} · {QUALITY} · "
            f"captions {CAPTION_SIZE if CAPTIONS else 'off'}",
            "Initializing",
            5,
        )
        script, scene_prompts = write_script()
        scenes = generate_scenes(scene_prompts)
        voice = generate_voice(script)
        compose(scenes, voice, script)
        log("Render complete", "Finished", 95)
        return 0
    except Exception as error:  # noqa: BLE001
        log(f"Render failed: {error}")
        patch({"status": "failed", "error": str(error)[:500]})
        return 1


if __name__ == "__main__":
    sys.exit(main())
