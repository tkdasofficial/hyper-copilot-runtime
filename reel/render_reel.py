#!/usr/bin/env python3
"""
Hyper Copilot — Reel engine (short form, 9:16).

Reads the grouped dispatch payload (PAYLOAD_JSON, <= 10 top-level keys with
sub-properties) and builds a real video:
  script (NVIDIA NIM) -> stock footage (Pexels + Pixabay) -> ElevenLabs voice (Edge TTS
  backup) (English / Hindi / Hinglish / Bengali) -> Drive Audio Library music -> editing template
  (zoom, pan/keyframes, speed, vignette/mask, overlays, captions) -> Google
  Drive "Videos" folder. Progress is written to the Supabase `videos` row.
"""
import asyncio, json, math, os, random, re, shutil, subprocess, sys, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import director, visuals, sound, qa  # noqa: E402

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
        "bitrate_mbps": max(1, min(16, int(float(re.sub(r"[^0-9.]", "", str(g("visual.bitrate_mbps", default="16"))) or 16)))),
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
        "sources": g("visual.sources", "stock.sources", default="pexels,pixabay"),
        "hook_style": str(g("direction.hook_style", default="auto")).lower(),
        "pacing": str(g("direction.pacing", default="dynamic")).lower(),
        "music_level": str(g("direction.music_level", default="medium")).lower(),
        "sfx_level": str(g("direction.sfx_level", default="medium")).lower(),
        "creativity": str(g("direction.creativity", default="balanced")).lower(),
        "research_depth": str(g("direction.research_depth", default="standard")).lower(),
        "retry_scene": int(re.sub(r"[^0-9-]", "", str(g("meta.retry_scene", default="-1"))) or -1),
    }
    topic = re.sub(r"\b(top|\d+|facts?|about|amazing|interesting|unknown|in hinglish|in hindi|in english)\b", " ",
                   str(cfg["prompt"]), flags=re.I)
    cfg["topic"] = re.sub(r"\s+", " ", topic).strip() or str(cfg["prompt"])
    cfg["duration"] = max(10, min(90, cfg["duration"]))
    cfg["fps"] = 60 if cfg["fps"] >= 60 else 30
    if _is_fact(cfg) and cfg["aspect"] == "9:16":
        cfg["duration"] = max(30, min(50, cfg["duration"] if cfg["duration"] >= 30 else 42))
        cfg["fps"] = 60
        cfg["resolution"] = "1080p"
    return cfg


def _is_fact(cfg) -> bool:
    c = str(cfg.get("category", "")).lower()
    return "news" in c or "fact" in c


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


LANG_RULES = {
    "english": "LANGUAGE: Pure, natural spoken English only. No Hindi words at all. Fact label: \"Fact number 1\".",
    "hindi": "LANGUAGE: Pure, natural spoken Hindi only, in Devanagari script. Do not mix English words; use natural Hindi equivalents (numbers in Hindi words or digits). Fact label: \"फैक्ट नंबर 1\" is not allowed; use \"तथ्य नंबर 1\" or \"नंबर 1\". Hook phrase: \"क्या आपको पता है?\".",
    "hinglish": ("LANGUAGE: Hinglish — the natural conversational Hindi + English mix Indian creators actually speak. "
                 "Write Hindi words in Devanagari and English words in Latin script, e.g. "
                 "\"क्या आपको पता है कि human body में एक ऐसा organ है जो खुद को regenerate कर सकता है?\". "
                 "Keep common modern/technical words in English (organ, planet, rocket, engine, brain, speed, record, scientists, data) "
                 "where that is how people naturally say them; keep grammar, connectors and emotion in Hindi. "
                 "Do not force English into every sentence and never translate common technical terms into awkward formal Hindi. "
                 "It must read fluent, not machine-translated. Fact label: \"Fact number 1\". Hook: \"क्या आपको पता है?\" or \"Did you know?\"."),
    "bengali": "LANGUAGE: Natural spoken Bengali only, in Bengali script.",
}


def write_script(cfg, digest="") -> dict:
    facts = "news" in str(cfg["category"]).lower() or "fact" in str(cfg["category"]).lower()
    lang = str(cfg["language"]).strip().lower()
    words_per_sec = 2.9 if lang == "english" else 2.7
    total_words = int(cfg["duration"] * words_per_sec)
    scenes = max(3, min(15, round(cfg["duration"] / 3.5)))
    temp = {"safe": 0.35, "bold": 0.85}.get(cfg.get("creativity", "balanced"), 0.6)
    hook_rule = ("" if cfg.get("hook_style", "auto") == "auto"
                 else f"- The user prefers hook style: {cfg['hook_style']}.\n")
    system = (
        "You are a documentary director and fact-video writer. You write accurate, original short-video narration "
        "in a natural conversational voice and plan every shot. Respect user and negative prompts above all style "
        "guidance. Reply with JSON only, no markdown."
    )
    user = f"""
Topic / user instructions: {cfg['prompt']}
Things to avoid (negative prompt): {cfg['negative'] or 'none'}
Category: {cfg['category']}   Visual style: {cfg['style']}
{LANG_RULES.get(lang, LANG_RULES['english'])}
Target about {total_words} spoken words across about {scenes} short scenes for a {cfg['duration']}-second video.

RESEARCH (use ONLY facts supported by these sources; cite source ids per scene):
{digest or 'none'}

DIRECTION:
- First write 5 hook candidates (curiosity, shock, question, myth-bust, countdown-tease), score each 0-10 for scroll-stopping power, pick the best as scene 1 (1-3 seconds, no greeting). The hook teases the single most surprising fact of the reel (paid off in the reveal) and gives a reason to keep watching; never open with "Fact 1", a list number, the topic name alone or "Did you know" + a plain definition.
- Connect the scenes: each fact scene ends with or leads into the next (a contrast, a "but", a bigger number), so it is one story, not a list of disconnected encyclopedia lines.
{hook_rule}- Story arc: hook -> context -> escalating facts -> strongest reveal (second-to-last) -> payoff/curiosity ending. Label each scene's purpose.
- Visual bible: one colour grade (teal_orange | cool | warm | moody | neutral) and one mood for the whole reel.
- Each scene: shot_type (establishing | close-up | macro | tracking | wide | low-angle | top-down | orbital | timelapse), never the same as the previous scene.
- Footage is the default. Add an "infographic" {{"type":"stat"|"bars"|"compare","title":"...","items":[{{"label":"...","value":"digits","unit":"..."}}]}} ONLY when a comparison or quantity IS the point and real footage cannot show it (e.g. "Saturn is 95 times Earth's mass"). A number merely appearing in a line is NOT a reason. At most 2 infographic scenes per reel, never the hook, never two adjacent scenes; all others "infographic": null.
- sfx: "", "whoosh", "impact" or "reveal" — use sparingly (at most every third scene). music_intensity: low | medium | high.

{'FACT VIDEO STYLE:' if facts else 'VIDEO STYLE:'}
- Open immediately with a strong, specific curiosity hook. No greeting, intro, filler, or closing request to follow/subscribe.
- Sound energetic, conversational and original, like a good Indian fact-video presenter. Use short, punchy sentences with minimal pauses, and natural punctuation for vocal emphasis on striking words.
- Use "Did you know?" / "क्या आपको पता है?" only when it sounds natural; do not force or repeat it.
- Every line must move the story forward. Sound like a real creator talking to a friend, never like an AI article.
- For Top N/list requests, exactly N distinct facts, each introduced with the fact label defined in LANGUAGE. A very short first hook is allowed; no separate outro scene.
- For one focused topic, explain that topic with connected scenes and a strong final payoff, not a numbered list.
- Never invent numbers, quotations, or unsupported superlatives.
- Keep each scene 1-2 short sentences (about 3-6 seconds spoken).
- Each scene must have a SPECIFIC visual subject matching exactly what is spoken. Provide 3 concrete English stock-search phrases, most relevant first.
- VOICE-READY TEXT (read aloud by ElevenLabs TTS, so write exactly what is spoken):
  * Write EVERY number as spoken words in the narration language (English "three hundred eighty-four thousand kilometres"; Hindi/Hinglish "तीन लाख चौरासी हज़ार किलोमीटर"; Bengali in Bengali words). Never digits in narration.
  * Round big numbers naturally; at most one number per sentence, comma before a big number.
  * Years as spoken. Decimals in words.
  * No symbols or abbreviations (%, °, km, kg, ~, /, &, +, brackets, quotes, emoji, hashtags, ellipses). NASA stays NASA.
  * Short sentences (max about 14 words). End every sentence with . ? or ! (Hindi may use ।).
  * Hinglish: Hindi words only in Devanagari and English words only in Latin script.
- Badge and headline optional and brief; headline 1-3 words.

Return JSON:
{{"title": "short title in {cfg['language']}",
  "format": "list" | "explainer",
  "hooks": [{{"text": "...", "type": "...", "score": 0}}],
  "hook": {{"text": "...", "type": "..."}},
  "visual_bible": {{"grade": "...", "mood": "..."}},
  "scenes": [{{"purpose": "hook|context|fact|reveal|payoff", "narration": "...", "claim": "the factual claim in English or empty",
              "sources": ["S1"], "badge": "short fact number or empty", "headline": "1-3 word label or empty",
              "shot_type": "...", "keywords": ["specific English stock query naming the exact subject (e.g. 'Saturn rings Cassini')", "alternative real-footage query", "broader on-topic query"],
              "infographic": null, "sfx": "", "music_intensity": "medium",
              "emphasis": ["1-3 key words/numbers from the narration to highlight"]}}]}}
"""
    key = os.environ.get("NVIDIA_API_KEY", "")
    last_err = None
    for model in NIM_MODELS:
        for attempt in range(3):
            try:
                r = requests.post(
                    "https://integrate.api.nvidia.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                        "temperature": temp,
                        "max_tokens": 16000,
                    },
                    timeout=300,
                )
                if r.status_code >= 400:
                    raise RuntimeError(f"NIM {r.status_code}: {r.text[:300]}")
                msg = r.json()["choices"][0]["message"]
                text = msg.get("content") or ""
                if "{" not in text:
                    print("[reel] script reply had no JSON; finish:", r.json()["choices"][0].get("finish_reason"))
                    text = (msg.get("reasoning_content") or "") + text
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



# ---------------------------------------------------------------- spoken text
HI_NUM = ("शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस "
          "इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस चालीस "
          "इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास पचास इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ "
          "इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उनासी अस्सी "
          "इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे").split()
EN_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
EN_TENS = "  twenty thirty forty fifty sixty seventy eighty ninety".split(" ")


def _en(n: int) -> str:
    if n < 20: return EN_ONES[n]
    if n < 100: return EN_TENS[n // 10] + ("-" + EN_ONES[n % 10] if n % 10 else "")
    if n < 1000: return EN_ONES[n // 100] + " hundred" + (" " + _en(n % 100) if n % 100 else "")
    for v, w in ((10**12, "trillion"), (10**9, "billion"), (10**6, "million"), (1000, "thousand")):
        if n >= v:
            return _en(n // v) + " " + w + (" " + _en(n % v) if n % v else "")
    return str(n)


def _hi(n: int) -> str:
    if n < 100: return HI_NUM[n]
    for v, w in ((10**7, "करोड़"), (10**5, "लाख"), (1000, "हज़ार"), (100, "सौ")):
        if n >= v:
            return _hi(n // v) + " " + w + (" " + _hi(n % v) if n % v else "")
    return str(n)


def _year(n: int, hi: bool) -> str:
    a, b = divmod(n, 100)
    if hi:
        return _hi(n) if a % 10 == 0 else f"{_hi(a)} सौ" + (f" {_hi(b)}" if b else "")
    if a % 10 == 0:
        return _en(n)
    return f"{_en(a)} " + ("hundred" if b == 0 else (f"oh {_en(b)}" if b < 10 else _en(b)))


def spoken_text(text: str, cfg) -> str:
    """Last-mile cleanup so TTS never reads digits, symbols or abbreviations oddly."""
    lang = str(cfg["language"]).lower()
    hi = lang in ("hindi", "hinglish")
    if lang == "bengali":
        return re.sub(r"\s+", " ", re.sub(r"[\"“”#*_~()\[\]{}]|\.\.\.|…", " ", text)).strip()
    unit = {"%": (" percent", " प्रतिशत"), "°C": (" degree Celsius", " डिग्री सेल्सियस"), "°F": (" degree Fahrenheit", " डिग्री फ़ारेनहाइट"),
            "°": (" degree", " डिग्री"), "km/h": (" kilometres per hour", " किलोमीटर प्रति घंटा"), "km": (" kilometres", " किलोमीटर"),
            "kg": (" kilograms", " किलोग्राम"), "cm": (" centimetres", " सेंटीमीटर"), "mm": (" millimetres", " मिलीमीटर"),
            "m": (" metres", " मीटर"), "$": (" dollars", " डॉलर"), "₹": (" rupees", " रुपये")}
    t = text.replace("&", " and " if not hi else " और ").replace("…", ".").replace("...", ".")
    t = re.sub(r"[\"“”#*_~()\[\]{}]", " ", t)
    t = re.sub(r"(\d),(?=\d{2,3}\b)", r"\1", t)  # 3,84,400 / 384,400 -> 384400
    def num(m):
        whole, frac, u = m.group(1), m.group(2), m.group(3) or ""
        cur_pre = m.group(0)[0] in "$₹"
        n = int(whole)
        if not frac and not u and 1100 <= n <= 2099 and len(whole) == 4:
            w = _year(n, hi)
        else:
            w = _hi(n) if hi else _en(n)
            if hi and frac == "5" and n >= 3:
                w, frac = "साढ़े " + w, ""
            elif hi and frac == "5" and n in (1, 2):
                w, frac = ("डेढ़", "ढाई")[n - 1], ""
            if frac:
                w += (" दशमलव " if hi else " point ") + " ".join((HI_NUM if hi else EN_ONES)[int(d)] for d in frac)
        cur = unit[m.group(0)[0]][1 if hi else 0] if cur_pre else ""
        return " " + w + (unit.get(u, ("", ""))[1 if hi else 0]) + cur + " "
    t = re.sub(r"[$₹]?(\d+)(?:\.(\d+))?\s?(km/h|°C|°F|%|°|km|kg|cm|mm|m\b)?", num, t)
    t = re.sub(r"\s*([$₹])\s*", lambda m: unit[m.group(1)][1 if hi else 0] + " ", t)
    t = re.sub(r"\s+([,.!?।])", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()

# ---------------------------------------------------------------- voice
VOICES = {
    "english": ("en-US-AndrewNeural", "en-US-AvaNeural"),
    "hindi": ("hi-IN-MadhurNeural", "hi-IN-SwaraNeural"),
    "hinglish": ("hi-IN-MadhurNeural", "hi-IN-SwaraNeural"),
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
    end = min(duration, words[-1][0] + words[-1][1] + 0.06)
    length = max(0.15, end - start)
    # Lossless sample-exact cut (mp3 re-encode adds padding that bleeds into the next scene) + tiny fades.
    trimmed = out.with_name(out.stem + "_trim.wav")
    run(["ffmpeg", "-y", "-i", str(out), "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
         "-af", f"afade=t=in:st=0:d=0.012,afade=t=out:st={max(0, length-0.04):.3f}:d=0.04",
         "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(trimmed)])
    trimmed.replace(out)
    return [(max(0.0, ws-start), wd, text) for ws, wd, text in words]


def _sentences(text):
    parts = re.split(r"(?<=[.!?।？！])\s+", text.strip())
    return [x for x in (p.strip() for p in parts) if x]


def _pct(rate: str) -> int:
    m = re.search(r"-?\d+", rate or "0")
    return int(m.group(0)) if m else 0


def _one(text, voice, out: Path, rate: str, pitch: str):
    for attempt in range(3):
        try:
            words = asyncio.run(_tts(text, voice, out, rate, pitch))
            if out.exists() and out.stat().st_size > 1000:
                if words:
                    return trim_voice(out, words)
                d = probe_duration(out)
                toks = text.split()
                step = d / max(1, len(toks))
                return [(i * step, step, t) for i, t in enumerate(toks)]
        except Exception as e:
            print("[reel] tts retry:", e)
            time.sleep(2)
    raise RuntimeError("Voice generation failed")


# ---------------------------------------------------------------- ElevenLabs (primary)
# Default ElevenLabs voices per category: (male, female). All are multilingual
# premade voices, so they speak English, Hindi, Hinglish and Bengali.
EL_VOICES = {
    "news":        ("nPczCjzI2devNBz1zQrb", "EXAVITQu4vr4xnSDxMaL"),  # Brian / Sarah
    "fact":        ("nPczCjzI2devNBz1zQrb", "EXAVITQu4vr4xnSDxMaL"),  # Brian / Sarah
    "documentary": ("JBFqnCBsd6RMkjVDRZzb", "Xb7hH8MSUJpSbSDYk0k2"),  # George / Alice
    "history":     ("JBFqnCBsd6RMkjVDRZzb", "Xb7hH8MSUJpSbSDYk0k2"),  # George / Alice
    "science":     ("onwK4e9ZLuTAKqWW03F9", "Xb7hH8MSUJpSbSDYk0k2"),  # Daniel / Alice
    "space":       ("onwK4e9ZLuTAKqWW03F9", "Xb7hH8MSUJpSbSDYk0k2"),  # Daniel / Alice
    "education":   ("onwK4e9ZLuTAKqWW03F9", "XrExE9yKIg1WjnnlVkGX"),  # Daniel / Matilda
    "tech":        ("TX3LPaxmHKxFdv7VOQHJ", "cgSgspJ2msm6clMCkdW9"),  # Liam / Jessica
    "story":       ("N2lVS1w4EtoT3dr4eOWO", "pFZP5JQG7iQjIQuC4Bku"),  # Callum / Lily
    "mystery":     ("N2lVS1w4EtoT3dr4eOWO", "pFZP5JQG7iQjIQuC4Bku"),  # Callum / Lily
    "horror":      ("N2lVS1w4EtoT3dr4eOWO", "pFZP5JQG7iQjIQuC4Bku"),  # Callum / Lily
    "motivation":  ("pqHfZKP75CvOlQylNhV4", "FGY2WhTYpPnrIDTdsKH5"),  # Bill / Laura
    "comedy":      ("IKne3meq5aSn9XLyUdCD", "cgSgspJ2msm6clMCkdW9"),  # Charlie / Jessica
    "entertainment": ("IKne3meq5aSn9XLyUdCD", "cgSgspJ2msm6clMCkdW9"),
    "default":     ("nPczCjzI2devNBz1zQrb", "EXAVITQu4vr4xnSDxMaL"),
}
EL_LANG = {"english": "en", "hindi": "hi", "bengali": "bn"}  # Hinglish: auto-detect


def el_voice(cfg):
    override = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    if override:
        return override
    cat = str(cfg.get("category", "")).lower()
    pair = next((v for k, v in EL_VOICES.items() if k != "default" and k in cat), EL_VOICES["default"])
    return pair[1] if cfg["gender"].startswith("f") else pair[0]


def el_settings(cfg, rate: str):
    cat = str(cfg.get("category", "")).lower()
    speed = max(0.9, min(1.2, 1.0 + _pct(rate) / 150))
    if any(k in cat for k in ("story", "mystery", "horror", "motivation")):
        return {"stability": 0.38, "similarity_boost": 0.8, "style": 0.55, "use_speaker_boost": True, "speed": speed}
    if any(k in cat for k in ("news", "fact", "comedy", "entertainment", "tech")):
        return {"stability": 0.42, "similarity_boost": 0.78, "style": 0.45, "use_speaker_boost": True, "speed": speed}
    return {"stability": 0.55, "similarity_boost": 0.75, "style": 0.3, "use_speaker_boost": True, "speed": speed}


EL_DISABLED = {"off": False}


def el_tts(text, cfg, out: Path, rate: str, ctx=None):
    """ElevenLabs with timestamps -> mp3 + word timings. Raises on any failure."""
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key or EL_DISABLED["off"]:
        raise RuntimeError("ElevenLabs unavailable")
    import base64
    lang = str(cfg["language"]).lower()
    model = os.environ.get("ELEVENLABS_MODEL", "").strip() or ("eleven_v3" if lang == "bengali" else "eleven_multilingual_v2")
    body = {"text": text, "model_id": model, "voice_settings": el_settings(cfg, rate), "apply_text_normalization": "auto"}
    if ctx and model != "eleven_v3":  # request stitching keeps prosody smooth across scenes
        if ctx.get("prev"): body["previous_text"] = ctx["prev"][-300:]
        if ctx.get("next"): body["next_text"] = ctx["next"][:300]
    if lang in EL_LANG and model != "eleven_multilingual_v2":
        body["language_code"] = EL_LANG[lang]
    if model == "eleven_v3":
        body["voice_settings"] = {"stability": 0.5, "similarity_boost": 0.75, "use_speaker_boost": True}
    r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{el_voice(cfg)}/with-timestamps?output_format=mp3_44100_128",
                      headers={"xi-api-key": key, "Content-Type": "application/json"}, json=body, timeout=120)
    if r.status_code in (401, 402, 403):
        EL_DISABLED["off"] = True  # key/quota problem: stop calling for this render
    if not r.ok:
        raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:200]}")
    data = r.json()
    out.write_bytes(base64.b64decode(data["audio_base64"]))
    if out.stat().st_size < 1000:
        raise RuntimeError("ElevenLabs returned empty audio")
    al = data.get("alignment") or data.get("normalized_alignment") or {}
    chars, starts, ends = al.get("characters", []), al.get("character_start_times_seconds", []), al.get("character_end_times_seconds", [])
    words, cur, ws, we = [], "", None, 0.0
    for c, a, b in zip(chars, starts, ends):
        if c.isspace():
            if cur:
                words.append((ws, max(0.05, we - ws), cur))
            cur, ws = "", None
        else:
            if ws is None:
                ws = a
            cur += c
            we = b
    if cur:
        words.append((ws, max(0.05, we - ws), cur))
    if not words:
        d = probe_duration(out)
        toks = text.split()
        step = d / max(1, len(toks))
        words = [(i * step, step, t) for i, t in enumerate(toks)]
    return trim_voice(out, words)


def tts(text, cfg, out: Path, rate: str, ctx=None):
    """ElevenLabs first; Edge TTS only if ElevenLabs fails."""
    text = spoken_text(text, cfg)
    for attempt in range(2):
        try:
            w = el_tts(text, cfg, out, rate, ctx)
            print(f"[reel] voice: ElevenLabs ({el_voice(cfg)})")
            return w
        except Exception as e:
            print("[reel] ElevenLabs failed:", e)
            if EL_DISABLED["off"] or not os.environ.get("ELEVENLABS_API_KEY"):
                break
            time.sleep(2)
    print("[reel] voice: Edge TTS backup")
    return edge_tts_voice(text, cfg, out, rate)


def edge_tts_voice(text, cfg, out: Path, rate: str):
    """Sentence-level pacing: each sentence gets its own rate/pitch, then joined tight."""
    male, female = VOICES.get(str(cfg["language"]).lower(), VOICES["english"])
    voice = female if cfg["gender"].startswith("f") else male
    base = _pct(rate)
    sents = _sentences(text) or [text]
    parts, words, cursor = [], [], 0.0
    for k, sent in enumerate(sents):
        hook = k == 0 and re.search(r"[?？]", sent)
        emphatic = re.search(r"[!！]|\d|shocking|incredible|सच|हैरान|सबसे|record|biggest|fastest", sent, re.I)
        r = base + (4 if emphatic else 0) - (3 if len(sent.split()) > 16 else 0)
        pitch = "+6Hz" if hook else ("+5Hz" if emphatic else "+2Hz")
        seg = out.with_name(f"{out.stem}_s{k}.mp3")
        w = _one(sent, voice, seg, f"{r:+d}%", pitch)
        d = probe_duration(seg)
        words += [(ws + cursor, wd, tt) for ws, wd, tt in w]
        parts.append(seg)
        cursor += d + 0.04
    if len(parts) == 1:
        parts[0].replace(out)
        return words
    inputs, filt = [], []
    for i, pth in enumerate(parts):
        inputs += ["-i", str(pth)]
        filt.append(f"[{i}:a]aresample=24000,apad=pad_dur=0.04[p{i}]")
    filt.append("".join(f"[p{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[o]")
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filt), "-map", "[o]", "-c:a", "libmp3lame", "-q:a", "2", str(out)])
    return words


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
            out.append({"id": f"px{it['id']}", "url": it["src"]["large2x"], "label": label, "kind": "image",
                        "thumb": it["src"].get("medium"), "src": "pexels", "short": 1080, "portrait": it.get("height", 0) > it.get("width", 1)})
            continue
        files = [f for f in it.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("height") and f.get("width")]
        files = [f for f in files if min(f["width"], f["height"]) >= 720]
        if not files:
            continue
        # 1080p target: closest short side to 1080, never 4K when 1080 exists.
        files.sort(key=lambda f: abs(min(f["width"], f["height"]) - 1080))
        f0 = files[0]
        out.append({"id": f"pv{it['id']}", "url": f0["link"], "label": label, "kind": "video", "dur": it.get("duration", 0),
                    "src": "pexels", "short": min(f0["width"], f0["height"]), "portrait": f0["height"] > f0["width"],
                    "thumb": it.get("image")})
    return out


def search_pixabay(q, cfg, photos=False):
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return []
    url = "https://pixabay.com/api/" if photos else "https://pixabay.com/api/videos/"
    params = {"key": key, "q": q[:100], "per_page": 15, "safesearch": "true", "order": "popular"}
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
            out.append({"id": f"xi{it['id']}", "url": it.get("largeImageURL"), "label": label, "kind": "image",
                        "thumb": it.get("webformatURL"), "src": "pixabay", "short": 1080,
                        "portrait": it.get("imageHeight", 0) > it.get("imageWidth", 1)})
            continue
        v = it.get("videos", {})
        opts = [v.get(k) for k in ("large", "medium") if (v.get(k) or {}).get("url") and (v.get(k) or {}).get("width")]
        opts = [o for o in opts if min(o["width"], o["height"]) >= 720]
        if opts:
            pick = opts[0]
            out.append({"id": f"xv{it['id']}", "url": pick["url"], "label": label, "kind": "video", "dur": it.get("duration", 0),
                        "src": "pixabay", "short": min(pick["width"], pick["height"]), "portrait": pick["height"] > pick["width"],
                        "thumb": pick.get("thumbnail") or (v.get("medium") or {}).get("thumbnail")})
    return out


def unusable_asset(path: Path, kind: str) -> bool:
    """Reject black/blank and blurry footage (edge-energy probe on a mid frame)."""
    try:
        probe = ["-ss", "1", "-i", str(path)] if kind == "video" else ["-i", str(path)]
        base = ["ffmpeg", "-v", "error", *probe, "-frames:v", "1"]
        gray = subprocess.run([*base, "-vf", "scale=32:32,format=gray", "-f", "rawvideo", "-"], capture_output=True, timeout=20).stdout
        if not gray or (len(gray) >= 1024 and sum(gray[:1024]) / 1024 < 14):
            print("[stock] reject: blank/dark frame")
            return True
        edges = subprocess.run([*base, "-vf", "scale=270:480,format=gray,edgedetect=low=0.08:high=0.2", "-f", "rawvideo", "-"], capture_output=True, timeout=20).stdout
        if edges:
            density = sum(1 for b in edges if b > 128) / len(edges)
            if density < 0.012:
                print(f"[stock] reject: blurry/flat (edge density {density:.4f})")
                return True
        return False
    except Exception:
        return True


STOP = {"real", "footage", "video", "stock", "planet", "space", "with", "from", "that", "this", "into", "over",
        "close", "view", "shot", "clip", "background", "beautiful", "the", "and"}


def _terms(q):
    return [w for w in re.findall(r"[a-z0-9]+", q.lower()) if len(w) > 2 and w not in STOP]


def _relevance(c, terms):
    if not terms:
        return 0.0
    hits = sum(1 for w in terms if w in c["label"] or (len(w) > 4 and w[:-1] in c["label"]))
    return hits / len(terms)


def _score(c, terms, cfg):
    rel = _relevance(c, terms)
    quality = 1.0 if c.get("short", 0) >= 1080 else 0.6
    comp = 1.0 if (c.get("portrait") == (cfg["aspect"] == "9:16")) else 0.8
    return (round(rel, 2), quality, comp, c["kind"] == "video")


def _download(c, dest):
    with requests.get(c["url"], stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


def _try_provider(name, q, cfg, idx, photos, neg):
    search = search_pixabay if name == "pixabay" else search_pexels
    terms = _terms(q)
    need = 0.5 if len(terms) >= 2 else 1.0
    cands = []
    for use_photos in ([True] if photos else [False]):
        cands += search(q, cfg, use_photos)
    cands = [c for c in cands if c["id"] not in USED and not any(n in c["label"] for n in neg)]
    good = [c for c in cands if _relevance(c, terms) >= need]
    if not good:
        print(f"[stock] {name}: no relevant result for '{q}' ({len(cands)} candidates rejected as off-topic)")
        return None
    good.sort(key=lambda c: _score(c, terms, cfg), reverse=True)
    for c in good[:4]:
        ext = "jpg" if c["kind"] == "image" else "mp4"
        dest = WORK / f"asset_{idx}.{ext}"
        try:
            _download(c, dest)
            if dest.stat().st_size > 20_000 and not unusable_asset(dest, c["kind"]):
                USED.add(c["id"])
                print(f"[stock] accept {name} {c['id']} rel={_relevance(c, terms):.2f} {c.get('short', '?')}p for '{q}'")
                return {"path": dest, "kind": c["kind"], "src": name}
            print(f"[stock] {name}: rejected {c['id']} on quality")
        except Exception as e:
            print("[reel] download failed:", e)
    return None


_SEARCH_CACHE: dict = {}


def search_cached(prov, q, cfg, photos):
    key = (prov, q.lower(), photos)
    if key not in _SEARCH_CACHE:
        _SEARCH_CACHE[key] = (search_pixabay if prov == "pixabay" else search_pexels)(q, cfg, photos)
    return _SEARCH_CACHE[key]


_THUMB: dict = {}


def _thumb(c):
    """(jpeg base64, dHash) of the provider preview image; lets us judge a clip before downloading it."""
    if c["id"] in _THUMB:
        return _THUMB[c["id"]]
    b64, h = None, None
    try:
        if c.get("thumb"):
            r = requests.get(c["thumb"], timeout=20)
            if r.ok and len(r.content) > 2000:
                tp = WORK / "thumbs" / f"{c['id']}.jpg"
                tp.parent.mkdir(exist_ok=True)
                tp.write_bytes(r.content)
                b64 = visuals.jpeg_b64(tp, "image")
                h = visuals.dhash(tp, "image")
    except Exception as e:
        print("[stock] thumb failed:", str(e)[:80])
    _THUMB[c["id"]] = (b64, h)
    return b64, h


_VSCORE: dict = {}


def select_asset(queries, cfg, idx, subject, claim, used_hashes, shot="", min_score=0.6, exclude=()):
    """Semantic stock selection: search -> label pre-filter -> vision score + repetition check on previews
    (parallel, before any download) -> download the best -> quality probe. Returns asset dict or None.
    The returned asset carries weak=True when nothing met the relevance bar (reported, never hidden)."""
    photos_only = str(cfg["visual_type"]).lower().startswith("stock photo")
    neg = _neg_terms(cfg)
    order = [p for p in ("pexels", "pixabay") if p in str(cfg["sources"]).lower()] or ["pexels", "pixabay"]
    qs, seen_q = [], set()
    for q in [visuals.shape_query(queries[0], shot)] + list(queries) + [r for q in queries[:2] for r in _refine(q)]:
        if q and q.lower() not in seen_q:
            seen_q.add(q.lower())
            qs.append(q)
    scored, seen = [], set()
    for batch_start in range(0, len(qs), 2):
        batch = qs[batch_start:batch_start + 2]
        fresh = []
        for q in batch:
            terms = _terms(q)
            for photos in ([True] if photos_only else [False, True] if batch_start >= 2 else [False]):
                for prov in order:
                    for c in search_cached(prov, q, cfg, photos):
                        if c["id"] in seen or c["id"] in USED or c["id"] in exclude or any(n in c["label"] for n in neg):
                            continue
                        seen.add(c["id"])
                        lab = _relevance(c, terms)
                        if lab >= (0.34 if len(terms) >= 2 else 1.0):
                            fresh.append({**c, "label_rel": round(lab, 2), "query": q})
        fresh.sort(key=lambda c: (c["label_rel"], c.get("short", 0) >= 1080, c.get("portrait") == (cfg["aspect"] == "9:16"),
                                  c["kind"] == "video"), reverse=True)
        fresh = fresh[:8]
        if not fresh:
            continue

        def judge(c):
            b64, h = _thumb(c)
            if c["id"] not in _VSCORE:
                _VSCORE[c["id"]] = director.vision_score(b64, subject, claim) if b64 else None
            return c, _VSCORE[c["id"]], h

        with ThreadPoolExecutor(max_workers=8) as ex:
            for c, v, h in ex.map(judge, fresh):
                sim = max([visuals.similarity(h, u) for u in used_hashes] or [0.0])
                base = v if v is not None else c["label_rel"] * 0.8
                c.update(vision=v, sim=round(sim, 2), thumb_hash=h,
                         final=round(base - max(0.0, sim - 0.7) * 2 + (0.03 if c["kind"] == "video" else 0), 3))
                c["ok"] = sim < 0.88 and ((v >= min_score) if v is not None else c["label_rel"] >= 0.5)
                scored.append(c)
        if any(c["ok"] for c in scored):
            break
        print(f"[visual] no candidate met the bar for {batch} (best: " +
              ", ".join(f"{c['id']} v={c['vision']} sim={c['sim']}" for c in sorted(scored, key=lambda c: -c['final'])[:3]) + ")")
    # A weak (loosely related) fallback is allowed and reported; a repeat of an existing shot never is.
    scored = [c for c in scored if c["sim"] < 0.88]
    scored.sort(key=lambda c: (c["ok"], c["final"]), reverse=True)
    for c in scored[:5]:
        ext = "jpg" if c["kind"] == "image" else "mp4"
        dest = WORK / f"asset_{idx}_{c['id']}.{ext}"
        try:
            _download(c, dest)
            if dest.stat().st_size > 20_000 and not unusable_asset(dest, c["kind"]):
                USED.add(c["id"])
                fh = visuals.dhash(dest, c["kind"])
                print(f"[visual] pick {c['id']} ({c['src']}) vision={c['vision']} label={c['label_rel']} sim={c['sim']} "
                      f"q='{c['query']}'{' WEAK' if not c['ok'] else ''}")
                return {"path": dest, "kind": c["kind"], "src": c["src"], "id": c["id"], "url": c["url"],
                        "query": c["query"], "score": c["vision"], "label": c["label_rel"], "sim": c["sim"],
                        "hash": fh, "thumb_hash": c["thumb_hash"], "weak": not c["ok"]}
        except Exception as e:
            print("[stock] download failed:", str(e)[:120])
    return None


def _refine(q):
    t = _terms(q)
    out = []
    if len(t) > 2:
        out.append(" ".join(t[:2]))
    if len(t) > 1:
        out.append(t[-1] if len(t[-1]) > len(t[0]) else t[0])
    return out


def fetch_asset(keywords, cfg, idx) -> dict:
    """Script -> query -> Pixabay -> relevance/quality check -> Pexels fallback -> refine query."""
    photos = str(cfg["visual_type"]).lower().startswith("stock photo")
    neg = _neg_terms(cfg)
    sources = str(cfg["sources"]).lower()
    order = [p for p in ("pixabay", "pexels") if p in sources] or ["pixabay", "pexels"]
    queries = [str(k).strip() for k in keywords if str(k).strip()]
    tried = []
    for q in queries + [r for q in queries[:2] for r in _refine(q)]:
        if q in tried:
            continue
        tried.append(q)
        for prov in order:
            got = _try_provider(prov, q, cfg, idx, photos, neg)
            if got:
                return got
            if prov == "pixabay" and "pexels" in order:
                print(f"[stock] pixabay rejected for '{q}' -> trying pexels")
    if not photos:
        for q in queries[:2]:
            for prov in order:
                got = _try_provider(prov, q, cfg, idx, True, neg)
                if got:
                    return got
    return None


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


GRADE = {"vf": ""}


def render_scene(asset, t, i, dur, W, H, fps, name=None) -> Path:
    out = WORK / f"{name or f'scene_{i:02d}'}.mp4"
    vf = scene_filter(t, i, dur, W, H, fps, asset["kind"])
    if GRADE["vf"]:
        vf = f"{vf},{GRADE['vf']},format=yuv420p"
    if asset["kind"] == "image":
        inp = ["-loop", "1", "-i", str(asset["path"])]
    else:
        inp = ["-stream_loop", "-1", "-i", str(asset["path"])]
    run(["ffmpeg", "-y", *inp, "-frames:v", str(max(1, round(dur * fps))), "-vf", vf, "-an", "-r", str(fps),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-threads", "2", "-pix_fmt", "yuv420p", str(out)])
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
            emph = [e.lower() for e in sc.get("emphasis", [])]
            toks = []
            for _, _, tok in group:
                txt = ass_escape(tok.upper() if latin and style != "minimal" else tok)
                key = re.sub(r"[^\w]", "", tok.lower())
                if key and (any(key in e or e in key for e in emph if e) or re.search(r"\d", tok)):
                    txt = f"{{\\c&H0000E5FF&\\fscx110\\fscy110}}{txt}{{\\r}}"
                toks.append(txt)
            phrase = " ".join(toks)
            lines.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Cap,,0,0,0,,{{\\fad(60,40)}}{phrase}")
    path = WORK / "overlay.ass"
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------- drive upload
def upload_to_drive(path: Path, title: str, replace_id: str | None = None) -> str:
    tok = drive_token()
    h = {"Authorization": f"Bearer {tok}"}
    if replace_id:  # scene retry: replace the file content, keep the same Drive file / links
        init = requests.patch(f"https://www.googleapis.com/upload/drive/v3/files/{replace_id}?uploadType=resumable&supportsAllDrives=true",
                              headers={**h, "Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": "video/mp4"},
                              json={}, timeout=30)
        if init.ok:
            with open(path, "rb") as f:
                up = requests.put(init.headers["Location"], headers={"Content-Type": "video/mp4"}, data=f, timeout=900)
            up.raise_for_status()
            return up.json()["id"]
        print("[drive] in-place update failed, uploading a new file:", init.status_code, init.text[:200])
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
def _fact_template(cfg, t):
    if "news" in str(cfg["category"]).lower() or "fact" in str(cfg["category"]).lower():
        t = {**t, "fact_style": True, "voice_rate": "+24%", "scene_gap": 0.0,
             "music_volume": 0.09, "speed": {"factor": 1.0},
             "zoom": {"pattern": ["in", "out", "pan_right"], "amount": 0.07},
             "transitions": {"fade": 0.08}, "overlay": {"badge": True, "headline": False},
             "captions": {"words_per_line": 2}}
    if cfg["pacing"] == "fast":
        t["voice_rate"] = "+28%"
    elif cfg["pacing"] == "relaxed":
        t["voice_rate"] = "+12%"
    return t


PROJECT = WORK / "project"
INFO_MAX = 2


class Planner:
    """Chooses every shot before anything is rendered, so the critic and scene retries can change a scene's
    visuals without touching the voice, timing or the other scenes."""

    def __init__(self, cfg, t, W, H, fps, title):
        self.cfg, self.t, self.W, self.H, self.fps, self.title = cfg, t, W, H, fps, title
        self.cut_len = {"fast": 1.8, "relaxed": 3.0}.get(cfg["pacing"], 2.2)
        self.plans = {}
        self.seq = 0

    # -- infographic budget: max 2 per reel, never the hook, never adjacent to another chart
    def info_scenes(self, skip=None):
        return {k for k, p in self.plans.items() if p["type"] == "infographic" and k != skip}

    def info_ok(self, k):
        cur = self.info_scenes(skip=k)
        return k != 0 and len(cur) < INFO_MAX and (k - 1) not in cur and (k + 1) not in cur

    def used_hashes(self, skip=None):
        out = []
        for k, p in self.plans.items():
            if k == skip:
                continue
            for seg in p.get("segments", []):
                out += [h for h in (seg["asset"].get("hash"), seg["asset"].get("thumb_hash")) if h is not None]
        return out

    def _nidx(self):
        self.seq += 1
        return self.seq

    def plan(self, i, sc, override=None, exclude=()):
        override = override or {}
        nframes = round(sc["dur"] * self.fps)
        subject = str((override.get("queries") or sc["keywords"] or [self.cfg["prompt"]])[0])
        claim = sc.get("claim") or ""
        info = override.get("infographic")
        if info and self.info_ok(i):
            return self._info_plan(i, sc, info, subject, claim, nframes)
        queries = [str(k) for k in (override.get("queries") or sc["keywords"]) if str(k).strip()][:4] or [self.cfg["prompt"]]
        segs_n = max(1, math.ceil(sc["dur"] / self.cut_len)) if self.t.get("fact_style") else 1
        cuts = [round(nframes * k / segs_n) for k in range(segs_n + 1)]
        used = self.used_hashes(skip=i)
        segments = []
        for j in range(segs_n):
            ordered = queries[j % len(queries):] + queries[:j % len(queries)]
            asset = select_asset(ordered, self.cfg, self._nidx(), subject, claim, used, sc["shot_type"] if j == 0 else "",
                                 exclude=exclude)
            if asset is None and j == 0:
                asset = select_asset([f"{self.cfg['topic']} {queries[0]}", self.cfg["topic"]], self.cfg, self._nidx(),
                                     subject, claim, used, exclude=exclude)
            if asset is None:
                if segments:  # extend the previous shot instead of repeating it
                    segments[-1]["frames"] += cuts[j + 1] - cuts[j]
                    continue
                if sc.get("infographic") and self.info_ok(i):
                    return self._info_plan(i, sc, sc["infographic"], subject, claim, nframes)
                raise RuntimeError(f"no usable footage for scene {i + 1} ('{subject}')")
            if j == 0 and asset.get("weak") and sc.get("infographic") and self.info_ok(i):
                USED.discard(asset["id"])
                return self._info_plan(i, sc, sc["infographic"], subject, claim, nframes)
            used += [h for h in (asset.get("hash"), asset.get("thumb_hash")) if h is not None]
            segments.append({"asset": asset, "frames": cuts[j + 1] - cuts[j]})
        p = {"type": "footage", "segments": segments}
        self.plans[i] = p
        return p

    def _info_plan(self, i, sc, info, subject, claim, nframes):
        bg = select_asset(sc["keywords"][:2], self.cfg, self._nidx(), subject, claim, self.used_hashes(skip=i), min_score=0.5)
        p = {"type": "infographic", "info": info, "frames": nframes, "segments": [{"asset": bg, "frames": nframes}] if bg else []}
        self.plans[i] = p
        return p

    def meta(self, i):
        p = self.plans[i]
        if p["type"] == "infographic":
            return [{"type": "infographic", "title": p["info"].get("title", ""),
                     "background": (p["segments"][0]["asset"].get("id") if p["segments"] else None)}]
        return [{"type": s["asset"]["kind"], "id": s["asset"].get("id"), "src": s["asset"].get("src"),
                 "query": s["asset"].get("query"), "relevance": s["asset"].get("score"), "label": s["asset"].get("label"),
                 "similarity": s["asset"].get("sim"), "weak": bool(s["asset"].get("weak")),
                 "seconds": round(s["frames"] / self.fps, 2)} for s in p["segments"]]

    def render(self, i):
        """Render one scene's clips (ffmpeg); returns list of mp4 paths."""
        p = self.plans[i]
        if p["type"] == "infographic":
            out = WORK / f"info_{i:02d}_{self._nidx()}.mp4"
            bg = p["segments"][0]["asset"] if p["segments"] else None
            visuals.render_infographic(p["info"], p["frames"] / self.fps, self.W, self.H, self.fps, out, WORK,
                                       background=bg["path"] if bg else None, bg_kind=bg["kind"] if bg else "video")
            return [out]
        outs = []
        for s in p["segments"]:
            outs.append(render_scene(s["asset"], self.t, self._nidx(), s["frames"] / self.fps, self.W, self.H, self.fps,
                                     name=f"scene_{i:02d}_{len(outs)}_{self._nidx()}"))
        return outs


def hard_checks(timeline, planner, fps) -> list:
    """Objective problems the AI critic must not be allowed to miss."""
    issues = []
    first = str(timeline[0]["narration"]).strip().lower() if timeline else ""
    if re.match(r"^(fact|फैक्ट|नंबर|number|पहला|first|नमस्ते|hello|hi\b|आज हम|today)", first):
        issues.append("hook: opens with a label/greeting instead of a curiosity hook")
    if timeline and timeline[0]["dur"] > 5.5:
        issues.append(f"hook: first scene is {timeline[0]['dur']:.1f}s (should be under 5s)")
    purposes = [str(sc.get("purpose", "")).lower() for sc in timeline]
    if purposes and purposes[0] != "hook":
        issues.append("story: first scene is not a hook")
    if not any(p in ("reveal", "payoff") for p in purposes[-2:]):
        issues.append("story: no reveal/payoff at the end")
    infos = sorted(planner.info_scenes())
    if len(infos) > INFO_MAX:
        issues.append(f"infographics: {len(infos)} charts (max {INFO_MAX})")
    if any(b - a == 1 for a, b in zip(infos, infos[1:])):
        issues.append("infographics: two charts back to back")
    hashes = []
    for i in sorted(planner.plans):
        for seg in planner.plans[i].get("segments", []):
            a = seg["asset"]
            if a.get("weak"):
                issues.append(f"visual: scene {i + 1} footage is only loosely related (relevance {a.get('score')})")
            h = a.get("hash")
            for (k, hh) in hashes:
                if h is not None and hh is not None and visuals.similarity(h, hh) >= 0.9:
                    issues.append(f"repetition: scene {i + 1} looks like scene {k + 1}")
                    break
            hashes.append((i, h))
            if seg["frames"] / fps > planner.cut_len * 1.8 and planner.plans[i]["type"] == "footage":
                issues.append(f"pacing: scene {i + 1} holds one shot for {seg['frames'] / fps:.1f}s")
    return list(dict.fromkeys(issues))


def _voice_all(cfg, t, scenes, fps, vid):
    rate = t.get("voice_rate", "+8%")

    def one(i):
        sc = scenes[i]
        a = WORK / f"voice_{i:02d}.mp3"
        ctx = {"prev": scenes[i - 1]["narration"] if i else "", "next": scenes[i + 1]["narration"] if i + 1 < len(scenes) else ""}
        words = tts(director.pronounce(sc["narration"], cfg), cfg, a, rate, ctx)
        return a, director.restore_display(words, cfg)

    update_row(vid, step=f"Voiceover (ElevenLabs) for {len(scenes)} scenes", progress=20)
    with ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(one, range(len(scenes))))
    timeline, audio_parts, cursor = [], [], 0.0
    for i, (sc, (a, words)) in enumerate(zip(scenes, results)):
        d = math.ceil((probe_duration(a) + float(t.get("scene_gap", 0.2))) * fps) / fps
        audio_parts.append((a, d))
        timeline.append({"start": cursor, "end": cursor + d, "dur": d, "words": words,
                         "badge": sc.get("badge", ""), "headline": sc.get("headline", ""),
                         "emphasis": [str(e) for e in (sc.get("emphasis") or [])][:3],
                         "keywords": sc.get("keywords") or [cfg["prompt"]], "claim": sc.get("claim", ""),
                         "purpose": sc.get("purpose", ""), "shot_type": sc.get("shot_type", ""),
                         "infographic": sc.get("infographic") if isinstance(sc.get("infographic"), dict) else None,
                         "sfx": sc.get("sfx", ""), "music_intensity": sc.get("music_intensity", "medium"),
                         "narration": sc["narration"]})
        cursor += d
    return timeline, audio_parts, cursor


def _encode_final(cfg, fps, video, mixed, ass, final):
    run(["ffmpeg", "-y", "-i", str(video), "-i", str(mixed), "-vf", f"ass={ass}",
         "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium",
         "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p", "-r", str(fps), "-b:v", f"{cfg['bitrate_mbps']}M",
         "-minrate", f"{cfg['bitrate_mbps']}M", "-maxrate", f"{cfg['bitrate_mbps']}M", "-bufsize", f"{cfg['bitrate_mbps'] * 2}M",
         "-x264-params", "nal-hrd=cbr", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(final)])


def _concat(clips, out):
    lst = WORK / "concat.txt"
    lst.write_text("".join(f"file '{c}'\n" for c in clips))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)])


def _scene_rows(timeline, planner, verification):
    return [{"i": i, "start": round(sc["start"], 2), "end": round(sc["end"], 2), "purpose": sc["purpose"],
             "narration": sc["narration"], "claim": sc.get("claim", ""), "shot_type": sc["shot_type"],
             "clips": planner.meta(i),
             "verification": verification[i]["status"] if i < len(verification) else "no-claim",
             "sources": verification[i]["sources"] if i < len(verification) else []} for i, sc in enumerate(timeline)]


def _save_project(state, scene_clips, mixed, ass, final):
    """Everything a scene retry needs, uploaded as a workflow artifact by the next step."""
    if PROJECT.exists():
        shutil.rmtree(PROJECT)
    (PROJECT / "clips").mkdir(parents=True)
    names = {}
    for i, group in scene_clips.items():
        names[str(i)] = []
        for n, c in enumerate(group):
            dst = PROJECT / "clips" / f"s{i:02d}_{n}.mp4"
            shutil.copy2(c, dst)
            names[str(i)].append(dst.name)
    shutil.copy2(mixed, PROJECT / "mix.m4a")
    shutil.copy2(ass, PROJECT / "overlay.ass")
    shutil.copy2(final, PROJECT / "final.mp4")
    state["clips"] = names
    (PROJECT / "state.json").write_text(json.dumps(state, ensure_ascii=False, default=str), encoding="utf-8")


def _asset_state(a):
    return {k: (str(v) if isinstance(v, Path) else v) for k, v in a.items()} if a else None


def main():
    cfg = load_payload()
    if cfg.get("retry_scene", -1) >= 0:
        return retry_main(cfg)
    vid = cfg["video_id"]
    W, H = dims(cfg)
    fps = cfg["fps"]
    t = _fact_template(cfg, load_template(cfg["template"]))
    clock = {"start": time.time()}
    lap = lambda k: clock.__setitem__(k, round(time.time() - clock["start"], 1))

    print(json.dumps({k: v for k, v in cfg.items() if k not in ("user_id",)}, ensure_ascii=False, indent=1))
    try:
        update_row(vid, status="processing", step="Researching the topic", progress=4)
        sources = director.research(cfg)
        update_row(vid, sources=[{"id": s["id"], "url": s["url"], "title": s["title"]} for s in sources])
        lap("research")

        update_row(vid, step="Writing the story & storyboard", progress=8)
        script = write_script(cfg, director.sources_digest(sources))
        scenes = script["scenes"]
        verification = director.verify_claims(script, sources)
        lap("script")

        update_row(vid, step="Director review of the script", progress=12)
        pre = hard_checks([{**s, "dur": 3.0} for s in scenes], Planner(cfg, t, W, H, fps, ""), fps)
        review = director.critique_script(script, cfg, verification, pre)
        rewritten = []
        for fx in review.get("rewrites") or []:
            try:
                k = int(fx.get("i"))
                if 0 <= k < len(scenes) and str(fx.get("narration", "")).strip():
                    scenes[k]["narration"] = str(fx["narration"]).strip()
                    if fx.get("claim") is not None:
                        scenes[k]["claim"] = str(fx.get("claim") or "")
                    rewritten.append(k)
            except (TypeError, ValueError):
                continue
        if rewritten:  # re-verify rewritten claims against the sources instead of assuming they are now safe
            verification = director.verify_claims(script, sources)
        print("[director] script score:", review.get("score"), review.get("issues"), "rewrote", rewritten)
        visuals.enforce_shot_variety(scenes)
        GRADE["vf"] = visuals.grade_filter(script.get("visual_bible"))
        title = script.get("title") or cfg["prompt"][:60]
        update_row(vid, step=f"Script ready: {len(scenes)} scenes", progress=18, title=title)
        lap("review")

        for sc in scenes:
            sc["narration"] = spoken_text(str(sc["narration"]), cfg)
        timeline, audio_parts, total = _voice_all(cfg, t, scenes, fps, vid)
        lap("voice")

        planner = Planner(cfg, t, W, H, fps, title)
        for i, sc in enumerate(timeline):
            update_row(vid, step=f"Choosing visuals {i + 1}/{len(timeline)}", progress=40 + int(22 * i / len(timeline)))
            for attempt in range(2):
                try:
                    planner.plan(i, sc)
                    break
                except Exception as e:
                    print(f"[scene {i}] planning attempt {attempt + 1} failed:", e)
                    if attempt:
                        raise
        lap("visual_select")

        update_row(vid, step="Director review of the edit", progress=63)
        pre_issues = hard_checks(timeline, planner, fps)
        summary = [{"i": i, "narration_gist": sc.get("claim") or sc["narration"], "purpose": sc["purpose"],
                    "footage": planner.meta(i), "dur": round(sc["dur"], 2)} for i, sc in enumerate(timeline)]
        edit_review = director.critique_edit(summary, cfg, pre_issues)
        fixed = []
        for fx in (edit_review.get("fixes") or [])[:3]:
            try:
                k = int(fx.get("i"))
                if not 0 <= k < len(timeline) or k in fixed:
                    continue
                old = planner.plans[k]
                if fx.get("action") == "infographic" and timeline[k]["infographic"] and planner.info_ok(k):
                    ov = {"infographic": timeline[k]["infographic"]}
                elif fx.get("query"):
                    ov = {"queries": [fx["query"]] + timeline[k]["keywords"][:2]}
                else:
                    continue
                try:
                    planner.plan(k, timeline[k], ov)
                    fixed.append(k)
                    print(f"[critic] replanned scene {k + 1}: {fx}")
                except Exception as e:
                    planner.plans[k] = old
                    print(f"[critic] fix for scene {k + 1} not possible:", e)
            except (TypeError, ValueError):
                continue
        lap("critic")

        update_row(vid, step="Editing the scenes", progress=68)
        with ThreadPoolExecutor(max_workers=3) as ex:
            rendered = dict(zip(range(len(timeline)), ex.map(planner.render, range(len(timeline)))))
        video = WORK / "video.mp4"
        _concat([c for i in range(len(timeline)) for c in rendered[i]], video)
        lap("render_scenes")

        update_row(vid, step="Mixing voice, music & sound design", progress=78)
        inputs, filt = [], []
        for i, (a, d) in enumerate(audio_parts):
            inputs += ["-i", str(a)]
            filt.append(f"[{i}:a]aresample=44100,apad,atrim=end_sample={round(d * 44100)}[a{i}]")
        filt.append("".join(f"[a{i}]" for i in range(len(audio_parts))) + f"concat=n={len(audio_parts)}:v=0:a=1[narr]")
        narr = WORK / "narration.wav"
        run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filt), "-map", "[narr]", str(narr)])
        music = download_music(cfg) if cfg["music_level"] != "off" else None
        mixed = WORK / "mix.m4a"
        sfx = sound.prepare_sfx(WORK, drive_token) if cfg["sfx_level"] != "off" else {}
        cues = sound.plan_cues(timeline, cfg["sfx_level"])
        try:
            sound.mix(narr, total, mixed, music, cfg["music_level"], sfx, cues, cfg["sfx_level"], timeline)
        except Exception as e:
            print("[sound] advanced mix failed, plain mix:", e)
            run(["ffmpeg", "-y", "-i", str(narr), "-c:a", "aac", "-b:a", "192k", str(mixed)])

        update_row(vid, step="Captions, overlays & final render", progress=85)
        ass = build_ass(cfg, t, timeline, W, H)
        final = WORK / "final.mp4"
        _encode_final(cfg, fps, video, mixed, ass, final)
        lap("final_render")

        update_row(vid, step="Quality check", progress=90)
        sims = [s["asset"].get("sim") or 0.0 for i in sorted(planner.plans) for s in planner.plans[i].get("segments", [])]
        report = qa.check(final, cfg, W, H, fps, total, sims, verification)
        post = hard_checks(timeline, planner, fps)
        report["warnings"] = list(dict.fromkeys(report["warnings"] + post))
        report["director"] = {"hook": script.get("hook"), "script_score": review.get("score"),
                              "edit_score": edit_review.get("score"),
                              "issues": (review.get("issues") or []) + (edit_review.get("issues") or []),
                              "script_rewrites": rewritten, "visual_fixes": [k + 1 for k in fixed],
                              "hard_checks_before_fix": pre_issues, "hard_checks_final": post}
        report["visuals"] = {"vision_model": director.VISION_STATE["model"], "vision_calls": director.VISION_STATE["calls"],
                             "vision_disabled": director.VISION_STATE["disabled"],
                             "infographic_scenes": [k + 1 for k in sorted(planner.info_scenes())]}
        lap("qa")
        report["timing_s"] = clock | {"start": None}
        rows = _scene_rows(timeline, planner, verification)
        print("[qa]", json.dumps(report, ensure_ascii=False))
        update_row(vid, qa_report=report, scenes=rows)
        if not report["passed"]:
            raise RuntimeError("Quality check failed: " + "; ".join(report["issues"]))
        _save_project({"cfg": {k: v for k, v in cfg.items()}, "title": title, "timeline": timeline, "fps": fps,
                       "total": total, "verification": verification, "report": report, "grade": GRADE["vf"],
                       "plans": {str(k): {"type": p["type"], "info": p.get("info"), "frames": p.get("frames"),
                                          "segments": [{"asset": _asset_state(s["asset"]), "frames": s["frames"]}
                                                       for s in p.get("segments", [])]} for k, p in planner.plans.items()},
                       "used": sorted(USED)}, rendered, mixed, ass, final)
        (WORK / "result.json").write_text(json.dumps({"path": str(final), "title": title}), encoding="utf-8")
        update_row(vid, step="Rendered, uploading to Google Drive", progress=92, title=title)
        print("[reel] rendered:", final, round(final.stat().st_size / 1e6, 2), "MB", "timing:", report["timing_s"])
    except Exception as e:
        msg = str(e)[:500]
        print("[reel] FAILED:", msg, file=sys.stderr)
        update_row(vid, status="failed", step="failed", error=msg)
        sys.exit(1)


def _fetch_project(vid):
    """Download the saved project of a previous render (GitHub Actions artifact) into WORK/project."""
    if (PROJECT / "state.json").exists():
        return
    tok, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (tok and repo):
        raise RuntimeError("scene retry needs the saved project, but no GitHub token is available")
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    arts = requests.get(f"https://api.github.com/repos/{repo}/actions/artifacts", headers=h,
                        params={"name": f"reel-project-{vid}", "per_page": 5}, timeout=30).json().get("artifacts", [])
    arts = [a for a in arts if not a.get("expired")]
    if not arts:
        raise RuntimeError("the saved project for this reel has expired; render it again to enable Redo shot")
    arts.sort(key=lambda a: a["created_at"], reverse=True)
    z = WORK / "project.zip"
    with requests.get(arts[0]["archive_download_url"], headers=h, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(z, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    PROJECT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(PROJECT)
    print("[retry] restored project artifact", arts[0]["id"], arts[0]["created_at"])


def retry_main(cfg):
    """Redo ONE scene: re-choose and re-render only that scene's visuals; reuse every other rendered clip, the
    voice/music mix and the caption track (timing is unchanged, so nothing else needs re-timing)."""
    vid, k = cfg["video_id"], cfg["retry_scene"]
    t0 = time.time()
    try:
        update_row(vid, status="processing", step=f"Redoing scene {k + 1}: loading the project", progress=10)
        _fetch_project(vid)
        state = json.loads((PROJECT / "state.json").read_text(encoding="utf-8"))
        timeline, fps = state["timeline"], state["fps"]
        if not 0 <= k < len(timeline):
            raise RuntimeError(f"scene {k + 1} does not exist (reel has {len(timeline)} scenes)")
        scfg = {**state["cfg"], **{x: cfg[x] for x in ("video_id",)}}
        W, H = dims(scfg)
        t = _fact_template(scfg, load_template(scfg["template"]))
        GRADE["vf"] = state.get("grade", "")
        USED.update(state.get("used", []))
        planner = Planner(scfg, t, W, H, fps, state["title"])
        for key, p in state["plans"].items():
            segs = [{"asset": {**s["asset"], "path": Path(s["asset"]["path"])}, "frames": s["frames"]}
                    for s in p["segments"] if s.get("asset")]
            planner.plans[int(key)] = {"type": p["type"], "info": p.get("info"), "frames": p.get("frames"), "segments": segs}
        before = planner.meta(k)
        old_ids = {m.get("id") for m in before if m.get("id")} | {m.get("background") for m in before if m.get("background")}
        sc = timeline[k]
        update_row(vid, step=f"Redoing scene {k + 1}: choosing new visuals", progress=30)
        queries = list(dict.fromkeys((sc.get("keywords") or [])[1:] + (sc.get("keywords") or [])[:1])) or [scfg["prompt"]]
        was_info = planner.plans[k]["type"] == "infographic"
        del planner.plans[k]
        planner.plan(k, sc, {"queries": queries} if not was_info else {"queries": queries}, exclude=old_ids)
        update_row(vid, step=f"Redoing scene {k + 1}: rendering", progress=55)
        new_clips = planner.render(k)
        clips = []
        for i in range(len(timeline)):
            clips += new_clips if i == k else [PROJECT / "clips" / n for n in state["clips"][str(i)]]
        video = WORK / "video.mp4"
        _concat(clips, video)
        update_row(vid, step=f"Redoing scene {k + 1}: final render", progress=75)
        final = WORK / "final.mp4"
        _encode_final(scfg, fps, video, PROJECT / "mix.m4a", PROJECT / "overlay.ass", final)
        update_row(vid, step="Quality check", progress=88)
        sims = [s["asset"].get("sim") or 0.0 for i in sorted(planner.plans) for s in planner.plans[i].get("segments", [])]
        report = qa.check(final, scfg, W, H, fps, state["total"], sims, state["verification"])
        post = hard_checks(timeline, planner, fps)
        report["warnings"] = list(dict.fromkeys(report["warnings"] + post))
        prev = state.get("report") or {}
        for key in ("director", "visuals"):
            if key in prev:
                report[key] = prev[key]
        after = planner.meta(k)
        report["retry"] = {"scene": k + 1, "before": before, "after": after, "seconds": round(time.time() - t0, 1),
                           "reused_scenes": len(timeline) - 1}
        report["director"] = {**report.get("director", {}), "hard_checks_final": post}
        rows = _scene_rows(timeline, planner, state["verification"])
        update_row(vid, qa_report=report, scenes=rows)
        print("[retry]", json.dumps(report["retry"], ensure_ascii=False))
        if not report["passed"]:
            raise RuntimeError("Quality check failed: " + "; ".join(report["issues"]))
        rendered = {i: ([c for c in new_clips] if i == k else [PROJECT / "clips" / n for n in state["clips"][str(i)]])
                    for i in range(len(timeline))}
        tmp = {i: [WORK / f"keep_{i:02d}_{n}.mp4" for n in range(len(g))] for i, g in rendered.items()}
        for i, g in rendered.items():
            for src, dst in zip(g, tmp[i]):
                shutil.copy2(src, dst)
        mix_keep, ass_keep = WORK / "mix_keep.m4a", WORK / "overlay_keep.ass"
        shutil.copy2(PROJECT / "mix.m4a", mix_keep)
        shutil.copy2(PROJECT / "overlay.ass", ass_keep)
        state["plans"] = {str(i): {"type": p["type"], "info": p.get("info"), "frames": p.get("frames"),
                                   "segments": [{"asset": _asset_state(s["asset"]), "frames": s["frames"]}
                                                for s in p.get("segments", [])]} for i, p in planner.plans.items()}
        state["used"], state["report"] = sorted(USED), report
        _save_project(state, tmp, mix_keep, ass_keep, final)
        (WORK / "result.json").write_text(json.dumps({"path": str(final), "title": state["title"], "retry": k}), encoding="utf-8")
        update_row(vid, step="Rendered, uploading to Google Drive", progress=92)
    except Exception as e:
        msg = f"Redo scene {k + 1} failed: {str(e)[:450]}"
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
        existing = None
        if info.get("retry") is not None and SB_URL and SB_KEY:
            row = requests.get(f"{SB_URL}/rest/v1/videos?id=eq.{vid}&select=file_id", timeout=20,
                               headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}).json()
            existing = (row or [{}])[0].get("file_id")
        file_id = upload_to_drive(final, info["title"], existing)
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
