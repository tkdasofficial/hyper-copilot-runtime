#!/usr/bin/env python3
"""
Hyper Copilot — Reel engine (short form, 9:16).

Reads the grouped dispatch payload (PAYLOAD_JSON, <= 10 top-level keys with
sub-properties) and builds a real video:
  script (NVIDIA NIM) -> stock footage (Pexels + Pixabay) -> edge-tts voice
  (English / Hindi / Bengali) -> Drive Audio Library music -> editing template
  (zoom, pan/keyframes, speed, vignette/mask, overlays, captions) -> Google
  Drive "Videos" folder. Progress is written to the Supabase `videos` row.
"""
import asyncio, json, math, os, random, re, shutil, subprocess, sys, time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
WORK = Path(os.environ.get("WORK_DIR", "/tmp/reel_work"))
WORK.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- payload
def load_payload() -> dict:
    raw = os.environ.get("PAYLOAD_JSON") or "{}"
    try:
        p = json.loads(raw) or {}
    except Exception:
        p = {}
    g = lambda *keys, default=None: next(
        (v for v in (_dig(p, k) for k in keys) if v not in (None, "")), default
    )
    env = os.environ.get
    cfg = {
        "video_id": g("identity.video_id", "video_id", default=env("VIDEO_ID", str(int(time.time())))),
        "user_id": g("identity.user_id", "user_id", default=env("USER_ID", "")),
        "prompt": g("content.prompt", "prompt", default=env("PROMPT", "Top 5 facts about the Universe")),
        "negative": g("content.negative_prompt", "negative_prompt", default=env("NEGATIVE_PROMPT", "")),
        "category": g("content.category", "voice_persona", default="News & Facts"),
        "format": g("content.format", default="auto"),
        "visual_type": g("visual.visual_type", default="Stock footage"),
        "style": g("visual.style", "image_style", default="Cinematic"),
        "aspect": g("visual.aspect_ratio", "aspect_ratio", default="9:16"),
        "resolution": g("visual.resolution", default="1080p"),
        "fps": int(re.sub(r"\D", "", str(g("visual.fps", default="30"))) or 30),
        "language": g("audio.language", default="English"),
        "gender": str(g("audio.voice_gender", "voice_gender", default="male")).lower(),
        "music_on": str(g("music.enabled", default="true")).lower() in ("true", "1", "yes"),
        "music_id": g("music.track_id", default=""),
        "music_name": g("music.track_name", default=""),
        "captions": str(g("captions.enabled", "captions", default="true")).lower() not in ("false", "0", "no", "off"),
        "caption_style": g("captions.style", default="Dynamic"),
        "caption_size": g("captions.size", default="Medium"),
        "template": g("edit.template", default="Dynamic"),
        "duration": int(float(g("timing.duration_seconds", "duration_seconds", default=env("DURATION_SECONDS", "30")))),
        "sources": g("stock.sources", default="pexels,pixabay"),
    }
    cfg["duration"] = max(10, min(90, cfg["duration"]))
    cfg["fps"] = 60 if cfg["fps"] >= 60 else 30
    return cfg


def _dig(obj, dotted):
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


# ---------------------------------------------------------------- supabase
SB_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SB_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""


def update_row(video_id: str, **fields):
    print(f"[reel] {fields.get('progress', '')}% {fields.get('step', '')}", flush=True)
    if not SB_URL or not SB_KEY:
        return
    try:
        requests.patch(
            f"{SB_URL}/rest/v1/videos?id=eq.{video_id}",
            headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}", "Content-Type": "application/json"},
            json=fields,
            timeout=20,
        )
    except Exception as e:
        print("[reel] supabase update failed:", e)


# ---------------------------------------------------------------- helpers
def run(cmd: list, quiet=True):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        tail = (r.stderr or "")[-1500:]
        raise RuntimeError(f"command failed: {' '.join(cmd[:4])}...\n{tail}")
    return r.stdout


def probe_duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)])
    try:
        return float(out.strip())
    except ValueError:
        return 0.0


def dims(cfg):
    small = "720" in str(cfg["resolution"])
    if cfg["aspect"] == "16:9":
        return (1280, 720) if small else (1920, 1080)
    return (720, 1280) if small else (1080, 1920)


# ---------------------------------------------------------------- script
NIM_MODELS = ["nvidia/nemotron-3-ultra-550b-a55b"]


def write_script(cfg) -> dict:
    facts = "news" in str(cfg["category"]).lower() or "fact" in str(cfg["category"]).lower()
    words_per_sec = 2.55 if cfg["language"] == "English" else 2.3
    total_words = int(cfg["duration"] * words_per_sec)
    scenes = max(3, min(15, round(cfg["duration"] / 3.5)))
    system = (
        "You write accurate, original short-video narration in a natural conversational voice. "
        "Respect user and negative prompts above all style guidance. Reply with JSON only, no markdown."
    )
    user = f"""
Topic / user instructions: {cfg['prompt']}
Things to avoid (negative prompt): {cfg['negative'] or 'none'}
Category: {cfg['category']}   Visual style: {cfg['style']}
Narration language: {cfg['language']} (narrate ONLY in {cfg['language']}, native script).
Target about {total_words} spoken words across about {scenes} short scenes for a {cfg['duration']}-second video.

{'FACT VIDEO STYLE:' if facts else 'VIDEO STYLE:'}
- Open immediately with a strong, specific curiosity hook. No greeting, intro, filler, or closing request to follow/subscribe.
- Sound energetic, conversational and original, like a good Indian fact-video presenter. Use short, punchy sentences with minimal pauses, and natural punctuation for vocal emphasis on striking words.
- Use "Did you know?" / "क्या आपको पता है?" only when it sounds natural; do not force or repeat it.
- Structure each fact: hook → fact → one short explanation → surprising twist/payoff. Every line must move the story forward.
- For Top N/list requests, exactly N distinct facts, say "Fact number 1", "Fact number 2", etc. in the requested language (Hindi: "फैक्ट नंबर 1", "फैक्ट नंबर 2" etc). Do not count down unless user asks. A very short first hook is allowed; no separate outro scene.
- For one focused topic, explain that topic with connected scenes and a strong final payoff, not a numbered list.
- Make factual claims precise; never invent numbers, quotations, or unsupported superlatives. Follow user instructions and exclusions.
- Each scene must have a SPECIFIC visual subject matching exactly what is spoken at that moment. Provide 3 concrete English stock-search phrases ordered most relevant first: named subject and visible action/object, not vague scenery. Search stock for real footage; do not request AI artwork.
- Keep badge and headline optional and brief; headline 1-3 words, not narration repeated. Captions will follow word timing.

Return JSON:
{{"title": "short title in {cfg['language']}",
  "format": "list" | "explainer",
  "scenes": [{{"narration": "...", "badge": "short fact number or empty", "headline": "1-3 word label or empty",
              "keywords": ["specific English visual stock query", "alternative specific query", "third specific query"]}}]}}
"""
    key = os.environ.get("NVIDIA_API_KEY", "")
    last_err = None
    for model in NIM_MODELS:
        for attempt in range(2):
            try:
                r = requests.post(
                    "https://integrate.api.nvidia.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                        "temperature": 0.6,
                        "max_tokens": 4000,
                    },
                    timeout=180,
                )
                if r.status_code >= 400:
                    raise RuntimeError(f"NIM {r.status_code}: {r.text[:300]}")
                text = r.json()["choices"][0]["message"]["content"] or ""
                text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
                m = re.search(r"\{.*\}", text, flags=re.S)
                data = json.loads(m.group(0))
                scenes_out = [s for s in data.get("scenes", []) if str(s.get("narration", "")).strip()]
                if len(scenes_out) < 2:
                    raise RuntimeError("script had too few scenes")
                data["scenes"] = scenes_out
                return data
            except Exception as e:
                last_err = e
                print(f"[reel] script attempt failed ({model}):", e)
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Could not write the script: {last_err}")


# ---------------------------------------------------------------- voice
VOICES = {
    "english": ("en-US-AndrewNeural", "en-US-AvaNeural"),
    "hindi": ("hi-IN-MadhurNeural", "hi-IN-SwaraNeural"),
    "bengali": ("bn-IN-BashkarNeural", "bn-IN-TanishaaNeural"),
}


async def _tts(text, voice, out: Path, rate: str, pitch: str):
    import edge_tts

    # Edge TTS supports rate, pitch, volume and WordBoundary via its own SSML.
    # It does not support arbitrary nested <emphasis> or <break> tags; punctuation
    # and short scene boundaries produce natural emphasis without broken SSML.
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume="+0%", boundary="WordBoundary")
    words = []
    with open(out, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append((chunk["offset"] / 1e7, chunk["duration"] / 1e7, chunk["text"]))
    return words


def trim_voice(out: Path, words: list) -> list:
    """Trim only outside the spoken words; preserve internal prosody and alignment."""
    if not words:
        return words
    duration = probe_duration(out)
    start = max(0.0, words[0][0] - 0.055)
    end = min(duration, words[-1][0] + words[-1][1] + 0.105)
    if start < 0.045 and duration - end < 0.18:
        return words
    trimmed = out.with_name(out.stem + "_trim.mp3")
    run(["ffmpeg", "-y", "-i", str(out), "-ss", f"{start:.3f}", "-t", f"{max(0.15, end-start):.3f}",
         "-c:a", "libmp3lame", "-q:a", "2", str(trimmed)])
    trimmed.replace(out)
    return [(max(0.0, ws-start), wd, text) for ws, wd, text in words]


def tts(text, cfg, out: Path, rate: str):
    male, female = VOICES.get(str(cfg["language"]).lower(), VOICES["english"])
    voice = female if cfg["gender"].startswith("f") else male
    # Modest pitch lift on emphatic lines; never distort the speaker's identity.
    pitch = "+3Hz" if re.search(r"[!?！？]|\b(?:shocking|incredible)\b", text, re.I) else "+0Hz"
    for attempt in range(3):
        try:
            words = asyncio.run(_tts(text, voice, out, rate, pitch))
            if out.exists() and out.stat().st_size > 1000:
                if words:
                    words = trim_voice(out, words)
                else:
                    d = probe_duration(out)
                    toks = text.split()
                    step = d / max(1, len(toks))
                    words = [(i * step, step, t) for i, t in enumerate(toks)]
                return words
        except Exception as e:
            print("[reel] tts retry:", e)
            time.sleep(2)
    raise RuntimeError("Voice generation failed")


# ---------------------------------------------------------------- footage
USED = set()


def _neg_terms(cfg):
    return [t.strip().lower() for t in re.split(r"[,;\n]", cfg["negative"] or "") if t.strip()]


def search_pexels(q, cfg, photos=False):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    orient = "portrait" if cfg["aspect"] == "9:16" else "landscape"
    url = "https://api.pexels.com/v1/search" if photos else "https://api.pexels.com/videos/search"
    try:
        r = requests.get(url, headers={"Authorization": key}, params={"query": q, "per_page": 12, "orientation": orient}, timeout=30)
        items = r.json().get("photos" if photos else "videos", [])
    except Exception:
        return []
    out = []
    for it in items:
        label = (it.get("url", "") + " " + str(it.get("alt", ""))).lower()
        if photos:
            out.append({"id": f"px{it['id']}", "url": it["src"]["large2x"], "label": label, "kind": "image"})
            continue
        files = [f for f in it.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("height")]
        if not files:
            continue
        target = 1920 if cfg["aspect"] == "9:16" else 1080
        files.sort(key=lambda f: abs((f["height"] if cfg["aspect"] == "9:16" else f["height"]) - target))
        out.append({"id": f"pv{it['id']}", "url": files[0]["link"], "label": label, "kind": "video", "dur": it.get("duration", 0)})
    return out


def search_pixabay(q, cfg, photos=False):
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return []
    url = "https://pixabay.com/api/" if photos else "https://pixabay.com/api/videos/"
    params = {"key": key, "q": q[:100], "per_page": 12, "safesearch": "true"}
    if photos:
        params["orientation"] = "vertical" if cfg["aspect"] == "9:16" else "horizontal"
    try:
        items = requests.get(url, params=params, timeout=30).json().get("hits", [])
    except Exception:
        return []
    out = []
    for it in items:
        label = str(it.get("tags", "")).lower()
        if photos:
            out.append({"id": f"xi{it['id']}", "url": it.get("largeImageURL"), "label": label, "kind": "image"})
            continue
        v = it.get("videos", {})
        pick = v.get("large") if v.get("large", {}).get("url") else v.get("medium")
        if pick and pick.get("url"):
            out.append({"id": f"xv{it['id']}", "url": pick["url"], "label": label, "kind": "video", "dur": it.get("duration", 0)})
    return out


def unusable_asset(path: Path, kind: str) -> bool:
    # Reject black footage/images; a caption over blank black is not a visual.
    try:
        probe = ["-ss", "1", "-i", str(path)] if kind == "video" else ["-i", str(path)]
        result = subprocess.run(["ffmpeg", "-v", "error", *probe, "-frames:v", "1", "-vf", "scale=32:32,format=gray", "-f", "rawvideo", "-"], capture_output=True, timeout=20)
        pixels = result.stdout
        return not pixels or (len(pixels) >= 1024 and sum(pixels[:1024]) / 1024 < 12)
    except Exception:
        return True


def fetch_asset(keywords, cfg, idx) -> dict:
    photos = str(cfg["visual_type"]).lower().startswith("stock photo")
    neg = _neg_terms(cfg)
    sources = str(cfg["sources"]).lower()
    for q in [str(k).strip() for k in keywords if str(k).strip()]:
        cands = []
        for use_photos in ([True] if photos else [False, True]):
            if "pexels" in sources:
                cands += search_pexels(q, cfg, use_photos)
            if "pixabay" in sources:
                cands += search_pixabay(q, cfg, use_photos)
        cands = [c for c in cands if c["id"] not in USED and not any(n in c["label"] for n in neg)]
        terms = [w for w in re.findall(r"[a-z0-9]+", q.lower()) if len(w) > 3 and w not in ("real", "footage", "video", "stock", "planet", "space")]
        if terms:
            cands = [c for c in cands if any(w in c["label"] for w in terms)]
        cands.sort(key=lambda c: (sum(w in c["label"] for w in terms), c["kind"] == "video"), reverse=True)
        for c in cands[:4]:
            ext = "jpg" if c["kind"] == "image" else "mp4"
            dest = WORK / f"asset_{idx}.{ext}"
            try:
                with requests.get(c["url"], stream=True, timeout=120) as r:
                    r.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                if dest.stat().st_size > 20_000 and not unusable_asset(dest, c["kind"]):
                    USED.add(c["id"])
                    return {"path": dest, "kind": c["kind"]}
            except Exception as e:
                print("[reel] download failed:", e)
    raise RuntimeError(f"No relevant stock media found for scene {idx + 1}; try a more visually searchable topic")


# ---------------------------------------------------------------- music (Drive)
def drive_token():
    rt = os.environ.get("GDRIVE_REFRESH_TOKEN")
    cid = os.environ.get("GDRIVE_OAUTH_CLIENT_ID") or os.environ.get("GOOGLE_CLOUD_API_ID")
    cs = os.environ.get("GDRIVE_OAUTH_CLIENT_SECRET") or os.environ.get("GOOGLE_CLOUD_API_SECRET")
    if not (rt and cid and cs):
        raise RuntimeError("Google Drive credentials are missing in the runtime")
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={"client_id": cid, "client_secret": cs, "refresh_token": rt, "grant_type": "refresh_token"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def download_music(cfg) -> Path | None:
    if not cfg["music_on"] or not cfg["music_id"]:
        return None
    try:
        tok = drive_token()
        dest = WORK / "music_src"
        with requests.get(
            f"https://www.googleapis.com/drive/v3/files/{cfg['music_id']}?alt=media&supportsAllDrives=true",
            headers={"Authorization": f"Bearer {tok}"}, stream=True, timeout=120,
        ) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        print("[reel] music:", cfg["music_name"])
        return dest
    except Exception as e:
        print("[reel] music unavailable:", e)
        return None


# ---------------------------------------------------------------- editing
def load_template(name: str) -> dict:
    slug = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_") or "dynamic"
    for cand in (slug, "dynamic"):
        p = ROOT / "templates" / f"{cand}.json"
        if p.exists():
            return json.loads(p.read_text())
    return {}


def scene_filter(t: dict, i: int, dur: float, W: int, H: int, fps: int, kind: str) -> str:
    zoom = t.get("zoom", {})
    motion = zoom.get("pattern", ["in", "out"])
    mode = motion[i % len(motion)] if isinstance(motion, list) else motion
    amount = float(zoom.get("amount", 0.12))
    speed_cfg = t.get("speed", {})
    speed = float(speed_cfg.get("factor", 1.0))
    if speed_cfg.get("ramp_every") and i % int(speed_cfg["ramp_every"]) == int(speed_cfg["ramp_every"]) - 1:
        speed = float(speed_cfg.get("ramp_factor", 1.25))
    frames = max(1, int(dur * fps))
    k = amount / frames
    if mode == "in":
        z, x, y = f"min(1+{k:.6f}*on,{1 + amount:.3f})", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif mode == "out":
        z, x, y = f"max({1 + amount:.3f}-{k:.6f}*on,1)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif mode in ("pan_left", "pan_right"):  # keyframed horizontal pan at fixed zoom
        z = f"{1 + amount:.3f}"
        span = f"(iw-iw/zoom)"
        x = f"{span}*on/{frames}" if mode == "pan_right" else f"{span}*(1-on/{frames})"
        y = "ih/2-(ih/zoom/2)"
    else:
        z, x, y = "1", "0", "0"
    parts = []
    if kind == "video" and abs(speed - 1.0) > 0.01:
        parts.append(f"setpts=PTS/{speed:.3f}")
    parts += [
        f"scale={W}:{H}:force_original_aspect_ratio=increase",
        f"crop={W}:{H}",
        "setsar=1",
        f"fps={fps}",
        f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps={fps}",
    ]
    grade = t.get("grade", {})
    if grade:
        parts.append(
            f"eq=contrast={grade.get('contrast', 1.05)}:saturation={grade.get('saturation', 1.1)}:brightness={grade.get('brightness', 0)}"
        )
    mask = t.get("mask", {})
    if mask.get("vignette") and not t.get("fact_style"):
        parts.append(f"vignette=angle={mask.get('angle', 0.6)}")
    if mask.get("letterbox") and not t.get("fact_style"):
        bar = int(H * float(mask.get("letterbox", 0.06)))
        parts.append(f"drawbox=x=0:y=0:w=iw:h={bar}:color=black@1:t=fill,drawbox=x=0:y=ih-{bar}:w=iw:h={bar}:color=black@1:t=fill")
    fade = float(t.get("transitions", {}).get("fade", 0.25))
    if fade > 0:
        parts.append(f"fade=t=in:st=0:d={fade},fade=t=out:st={max(0, dur - fade):.3f}:d={fade}")
    parts.append("format=yuv420p")
    return ",".join(parts)


def render_scene(asset, t, i, dur, W, H, fps) -> Path:
    out = WORK / f"scene_{i:02d}.mp4"
    vf = scene_filter(t, i, dur, W, H, fps, asset["kind"])
    if asset["kind"] == "image":
        inp = ["-loop", "1", "-i", str(asset["path"])]
    else:
        inp = ["-stream_loop", "-1", "-i", str(asset["path"])]
    run(["ffmpeg", "-y", *inp, "-t", f"{dur:.3f}", "-vf", vf, "-an", "-r", str(fps),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(out)])
    return out


# ---------------------------------------------------------------- captions + overlays (ASS)
def ass_time(s: float) -> str:
    s = max(0.0, s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{sec:05.2f}"


def ass_escape(txt: str) -> str:
    return txt.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(cfg, t, timeline, W, H) -> Path:
    size_mult = {"small": 0.038, "medium": 0.05, "large": 0.064}.get(str(cfg["caption_size"]).lower(), 0.05)
    fs = int(H * size_mult * (0.62 if cfg["aspect"] == "16:9" else 1.0))
    style = str(cfg["caption_style"]).lower()
    outline = {"minimal": 2, "bold": 6, "dynamic": 5}.get(style, 5)
    font = "Noto Sans"
    margin_v = int(H * (0.22 if cfg["aspect"] == "9:16" else 0.1))
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{fs},&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,{-1 if style != 'minimal' else 0},0,0,0,100,100,0,0,1,{outline},{2 if style != 'minimal' else 1},2,{int(W*0.07)},{int(W*0.07)},{margin_v},1
Style: Badge,{font},{int(H*0.07)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H9600A5FF,-1,0,0,0,100,100,0,0,3,{int(H*0.012)},0,8,20,20,{int(H*0.09)},1
Style: Head,{font},{int(H*0.034)},&H00FFFFFF,&H00FFFFFF,&H00000000,&HB4000000,-1,0,0,0,100,100,1,0,3,{int(H*0.01)},0,8,40,40,{int(H*0.17)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    ov = t.get("overlay", {})
    hl = "&H0000E5FF&" if style == "dynamic" else "&H00FFFFFF&"
    latin = str(cfg["language"]).lower() == "english"
    for sc in timeline:
        s0, s1 = sc["start"], sc["end"]
        if ov.get("badge", True) and sc.get("badge"):
            lines.append(f"Dialogue: 2,{ass_time(s0+0.1)},{ass_time(s1-0.1)},Badge,,0,0,0,,{{\\fad(200,150)}}{ass_escape(sc['badge'])}")
        if ov.get("headline", True) and sc.get("headline"):
            lines.append(f"Dialogue: 2,{ass_time(s0+0.2)},{ass_time(min(s1, s0+3.2))},Head,,0,0,0,,{{\\fad(250,250)}}{ass_escape(sc['headline'])}")
        if not cfg["captions"]:
            continue
        words = sc["words"]
        per = int(t.get("captions", {}).get("words_per_line", 3))
        # One short, bold phrase at a time; never stack full narration paragraphs.
        per = min(3, max(1, per))
        for gi in range(0, len(words), per):
            group = words[gi:gi + per]
            if not group:
                continue
            start = s0 + group[0][0]
            last = group[-1]
            end = min(s1, s0 + last[0] + last[1] + 0.11)
            if end <= start:
                continue
            phrase = " ".join(ass_escape(tok.upper() if latin and style == "bold" else tok) for _, _, tok in group)
            lines.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Cap,,0,0,0,,{phrase}")
    path = WORK / "overlay.ass"
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------- drive upload
def upload_to_drive(path: Path, title: str) -> str:
    tok = drive_token()
    h = {"Authorization": f"Bearer {tok}"}
    root = os.environ.get("GDRIVE_ROOT_FOLDER_ID") or os.environ.get("GDRIVE_MAIN_FOLDER_ID")
    q = f"name='Videos' and mimeType='application/vnd.google-apps.folder' and '{root}' in parents and trashed=false"
    found = requests.get("https://www.googleapis.com/drive/v3/files", headers=h,
                         params={"q": q, "fields": "files(id)", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}, timeout=30).json()
    folder = (found.get("files") or [{}])[0].get("id")
    if not folder:
        folder = requests.post("https://www.googleapis.com/drive/v3/files?supportsAllDrives=true", headers=h,
                               json={"name": "Videos", "mimeType": "application/vnd.google-apps.folder", "parents": [root]}, timeout=30).json()["id"]
    safe = re.sub(r"[\\/:*?\"<>|]+", " ", title).strip()[:80] or "Reel"
    meta = {"name": f"{safe}.mp4", "parents": [folder], "mimeType": "video/mp4"}
    init = requests.post("https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true",
                         headers={**h, "Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": "video/mp4"},
                         json=meta, timeout=30)
    init.raise_for_status()
    with open(path, "rb") as f:
        up = requests.put(init.headers["Location"], headers={"Content-Type": "video/mp4"}, data=f, timeout=900)
    up.raise_for_status()
    return up.json()["id"]


# ---------------------------------------------------------------- main
def main():
    cfg = load_payload()
    vid = cfg["video_id"]
    W, H = dims(cfg)
    fps = cfg["fps"]
    t = load_template(cfg["template"])
    if "news" in str(cfg["category"]).lower() or "fact" in str(cfg["category"]).lower():
        t = {**t, "fact_style": True, "voice_rate": "+13%", "scene_gap": 0.07,
             "music_volume": 0.10, "speed": {"factor": 1.0},
             "zoom": {"pattern": ["in", "out", "pan_right"], "amount": 0.07},
             "transitions": {"fade": 0.08}, "overlay": {"badge": True, "headline": False},
             "captions": {"words_per_line": 2}}

    print(json.dumps({k: v for k, v in cfg.items() if k not in ("user_id",)}, ensure_ascii=False, indent=1))
    try:
        update_row(vid, status="processing", step="Writing the script", progress=8)
        script = write_script(cfg)
        scenes = script["scenes"]
        title = script.get("title") or cfg["prompt"][:60]
        update_row(vid, step=f"Script ready: {len(scenes)} scenes", progress=18, title=title)

        rate = t.get("voice_rate", "+8%")
        timeline, cursor = [], 0.0
        audio_parts = []
        for i, sc in enumerate(scenes):
            update_row(vid, step=f"Voiceover {i + 1}/{len(scenes)}", progress=18 + int(22 * i / len(scenes)))
            a = WORK / f"voice_{i:02d}.mp3"
            words = tts(sc["narration"], cfg, a, rate)
            d = probe_duration(a) + float(t.get("scene_gap", 0.2))
            audio_parts.append((a, d))
            timeline.append({"start": cursor, "end": cursor + d, "dur": d, "words": words,
                             "badge": sc.get("badge", ""), "headline": sc.get("headline", ""),
                             "keywords": sc.get("keywords") or [cfg["prompt"]]})
            cursor += d

        clips = []
        for i, sc in enumerate(timeline):
            update_row(vid, step=f"Stock footage & editing {i + 1}/{len(timeline)}", progress=40 + int(35 * i / len(timeline)))
            # Cut within longer narration scenes, keeping footage tied to this fact.
            segments = max(1, math.ceil(sc["dur"] / 3.4)) if t.get("fact_style") else 1
            clip_len = sc["dur"] / segments
            queries = [str(k) for k in sc["keywords"] if str(k).strip()][:3]
            for j in range(segments):
                ordered = queries[j % len(queries):] + queries[:j % len(queries)] if queries else [cfg["prompt"]]
                asset = fetch_asset(ordered, cfg, len(clips))
                clips.append(render_scene(asset, t, len(clips), clip_len, W, H, fps))

        update_row(vid, step="Mixing voice and music", progress=78)
        concat = WORK / "concat.txt"
        concat.write_text("".join(f"file '{c}'\n" for c in clips))
        video = WORK / "video.mp4"
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(video)])

        # Narration track with per-scene padding.
        inputs, filt = [], []
        for i, (a, d) in enumerate(audio_parts):
            inputs += ["-i", str(a)]
            filt.append(f"[{i}:a]aresample=44100,apad,atrim=0:{d:.3f}[a{i}]")
        filt.append("".join(f"[a{i}]" for i in range(len(audio_parts))) + f"concat=n={len(audio_parts)}:v=0:a=1[narr]")
        narr = WORK / "narration.wav"
        run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filt), "-map", "[narr]", str(narr)])

        total = cursor
        music = download_music(cfg)
        mixed = WORK / "mix.m4a"
        if music:
            vol = float(t.get("music_volume", 0.18))
            run(["ffmpeg", "-y", "-i", str(narr), "-stream_loop", "-1", "-i", str(music), "-filter_complex",
                 f"[1:a]aresample=44100,volume={vol},atrim=0:{total:.3f},afade=t=out:st={max(0, total - 1.5):.3f}:d=1.5[m];"
                 f"[m][0:a]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=300[duck];"
                 f"[0:a][duck]amix=inputs=2:duration=first:normalize=0[out]",
                 "-map", "[out]", "-c:a", "aac", "-b:a", "192k", str(mixed)])
        else:
            run(["ffmpeg", "-y", "-i", str(narr), "-c:a", "aac", "-b:a", "192k", str(mixed)])

        update_row(vid, step="Captions, overlays & final render", progress=85)
        ass = build_ass(cfg, t, timeline, W, H)
        final = WORK / "final.mp4"
        run(["ffmpeg", "-y", "-i", str(video), "-i", str(mixed), "-vf", f"ass={ass}",
             "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-shortest",
             "-movflags", "+faststart", str(final)])

        (WORK / "result.json").write_text(json.dumps({"path": str(final), "title": title}), encoding="utf-8")
        update_row(vid, step="Rendered, uploading to Google Drive", progress=92, title=title)
        print("[reel] rendered:", final, round(final.stat().st_size / 1e6, 2), "MB")
    except Exception as e:
        msg = str(e)[:500]
        print("[reel] FAILED:", msg, file=sys.stderr)
        update_row(vid, status="failed", step="failed", error=msg)
        sys.exit(1)


def upload_main():
    cfg = load_payload()
    vid = cfg["video_id"]
    try:
        info = json.loads((WORK / "result.json").read_text(encoding="utf-8"))
        final = Path(info["path"])
        if not final.exists() or final.stat().st_size < 10000:
            raise RuntimeError("rendered video is missing")
        update_row(vid, step="Saving to Google Drive", progress=95)
        file_id = upload_to_drive(final, info["title"])
        update_row(vid, status="completed", step="Finished", progress=100, file_id=file_id,
                   video_url=f"drive:{file_id}", error=None, title=info["title"])
        print("[reel] uploaded to Google Drive Videos folder:", file_id)
    except Exception as e:
        msg = f"Google Drive upload failed: {str(e)[:450]}"
        print("[reel] FAILED:", msg, file=sys.stderr)
        update_row(vid, status="failed", step="failed", error=msg)
        sys.exit(1)


if __name__ == "__main__":
    upload_main() if "--upload" in sys.argv else main()
