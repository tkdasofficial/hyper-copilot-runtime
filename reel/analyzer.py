"""
Visual Analyzer (Nemotron 3 Nano Omni 30B) + NASA Image & Video Library source.

Every clip is judged on frames extracted from the DOWNLOADED file (never on titles, tags or the search query).
One multi-image request per clip returns scores + ACCEPT/REJECT; the same model runs the final per-scene QA
on frames of the rendered reel. When the analyzer is unreachable nothing is auto-accepted: callers get None
and must treat the footage as unverified.
"""
import base64, json, os, re, subprocess, threading, time
from pathlib import Path

import requests

NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
OMNI = os.environ.get("VISUAL_ANALYZER_MODEL", "").strip() or "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
STATE = {"calls": 0, "fails": 0, "down": False, "last_error": "", "think_flag": True, "seconds": 0.0}
_LOCK = threading.Semaphore(int(os.environ.get("ANALYZER_CONCURRENCY", "2") or 2))
ACCEPT_BAR = 0.6


# ---------------------------------------------------------------- NASA Image & Video Library
def search_nasa(q, cfg, photos=False):
    """images-api.nasa.gov search -> candidates with a real media file URL (resolved from the asset manifest)."""
    try:
        r = requests.get("https://images-api.nasa.gov/search",
                         params={"q": q[:100], "media_type": "image" if photos else "video", "page_size": 12},
                         timeout=30)
        items = r.json().get("collection", {}).get("items", [])
    except Exception as e:
        print("[nasa] search failed:", str(e)[:100])
        return []
    out = []
    for it in items[:12]:
        d = (it.get("data") or [{}])[0]
        nid = d.get("nasa_id")
        if not nid:
            continue
        label = " ".join([str(d.get("title", "")), " ".join(d.get("keywords") or []),
                          str(d.get("description", ""))[:300]]).lower()
        thumb = next((l.get("href") for l in it.get("links") or [] if l.get("rel") == "preview"), None)
        out.append({"id": f"na{re.sub(r'[^A-Za-z0-9]', '', nid)[:40]}", "nasa_id": nid, "label": label,
                    "kind": "image" if photos else "video", "src": "nasa", "thumb": thumb, "url": None,
                    "short": 1080, "portrait": False, "dur": 0})
    return out


def resolve_nasa(c):
    """Pick a 720p-1080p mp4 (or large jpg) from the NASA asset manifest; sets c['url']."""
    if c.get("url"):
        return c["url"]
    try:
        hrefs = [x.get("href", "") for x in requests.get(f"https://images-api.nasa.gov/asset/{c['nasa_id']}",
                                                          timeout=30).json().get("collection", {}).get("items", [])]
    except Exception:
        return None
    hrefs = [h.replace("http://", "https://").replace(" ", "%20") for h in hrefs]
    if c["kind"] == "video":
        pref = ["~medium.mp4", "~large.mp4", "~orig.mp4", "~mobile.mp4"]
        pick = next((h for p in pref for h in hrefs if h.lower().endswith(p)), None) or \
            next((h for h in hrefs if h.lower().endswith(".mp4")), None)
    else:
        pick = next((h for p in ("~large.jpg", "~orig.jpg", "~medium.jpg") for h in hrefs if h.lower().endswith(p)), None)
    c["url"] = pick
    return pick


# ---------------------------------------------------------------- frames
def _duration(path: Path) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                              "default=nw=1:nk=1", str(path)], capture_output=True, text=True, timeout=30).stdout
        return float(out.strip())
    except Exception:
        return 0.0


def frames(path: Path, kind: str, n=4, start=0.0, end=None, width=448):
    """n JPEG frames (base64) spread across [start, end] of the file, plus their dHashes."""
    import visuals
    if kind != "video":
        b = visuals.jpeg_b64(path, "image")
        return ([b] if b else []), [visuals.dhash(path, "image")]
    end = end if end is not None else _duration(path)
    span = max(0.2, (end or 1.0) - start)
    out, hashes = [], []
    for k in range(n):
        at = f"{start + span * (k + 0.5) / n:.2f}"
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", at, "-i", str(path), "-frames:v", "1",
                            "-vf", f"scale={width}:-2", "-q:v", "5", "-f", "image2", "-c:v", "mjpeg", "-"],
                           capture_output=True, timeout=40)
        if r.stdout:
            out.append(base64.b64encode(r.stdout).decode())
            hashes.append(visuals.dhash(path, "video", at=at))
    return out, hashes


# ---------------------------------------------------------------- model call
def _parse(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    m = re.findall(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("no JSON in analyzer reply: " + text[:120])
    raw = m[-1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", raw))


def _call(prompt: str, images: list, max_tokens=900) -> dict:
    """One Omni request (text + images). Retries 429/5xx with back-off; raises on terminal errors."""
    key = os.environ.get("NVIDIA_API_KEY", "")
    content = [{"type": "text", "text": prompt}] + [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}"}} for b in images]
    last = None
    for wait in (0, 5, 12, 25, 45):
        if wait:
            time.sleep(wait)
        body = {"model": OMNI, "temperature": 0.1, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": "/no_think"}, {"role": "user", "content": content}]}
        if STATE["think_flag"]:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        t0 = time.time()
        with _LOCK:
            try:
                r = requests.post(NIM_URL, json=body, timeout=(20, 150),
                                  headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            except requests.RequestException as e:
                last = e
                continue
            finally:
                STATE["seconds"] += time.time() - t0
        STATE["calls"] += 1
        if r.status_code == 400 and STATE["think_flag"] and "chat_template" in r.text:
            STATE["think_flag"] = False  # model build without the flag: rely on /no_think only
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            last = RuntimeError(f"{r.status_code} {r.text[:120]}")
            ra = r.headers.get("Retry-After", "")
            if ra.isdigit():
                time.sleep(min(40, int(ra)))
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"analyzer {r.status_code}: {r.text[:200]}")
        msg = r.json()["choices"][0]["message"]
        text = msg.get("content") or ""
        if "{" not in text:
            text = (msg.get("reasoning_content") or "") + text
        return _parse(text)
    raise RuntimeError(f"analyzer unavailable: {last}")


def _guard(fn):
    def inner(*a, **kw):
        if STATE["down"]:
            return None
        try:
            v = fn(*a, **kw)
            STATE["fails"] = 0
            return v
        except Exception as e:
            STATE["fails"] += 1
            STATE["last_error"] = str(e)[:200]
            print("[analyzer] failed:", str(e)[:200])
            if STATE["fails"] >= 5:
                STATE["down"] = True
                print("[analyzer] marked down after repeated failures; footage will be reported unverified")
            return None
    return inner


KEYS = ("subject_match", "semantic_relevance", "object_visibility", "action_context", "shot_suitability",
        "temporal_consistency", "visual_quality")


def _req_text(req: dict) -> str:
    return "\n".join(f"- {k}: {v}" for k, v in (
        ("Reel topic", req.get("topic")), ("Narration", req.get("narration")), ("Factual claim", req.get("claim")),
        ("Visual objective", req.get("visual_objective")), ("Required subject/object", req.get("required_subject")),
        ("Required action/context", req.get("required_action")), ("Preferred shot type", req.get("shot_type")),
        ("Must NOT appear", ", ".join(req.get("must_not") or []) or "none")) if v)


BLIND = (
    "Describe ONLY what is literally visible in these {n} frames (time order, one clip). You are NOT told what the "
    "clip is supposed to show - do not guess a topic, do not name a planet unless it is unmistakably visible.\n"
    'Reply with JSON only: {{"description": "<=25 words, literal", "main_subject": "<=6 words", '
    '"setting": "outer space" | "earth outdoors" | "indoors" | "abstract graphic" | "diagram or chart" | "text slide", '
    '"real_photo_or_footage": true/false, "celestial_body_visible": true/false, '
    '"body_features": "e.g. banded gas planet with rings / cratered grey moon / none", '
    '"text_or_watermark_dominant": true/false, "earth_scenery_visible": true/false}}')


def _blind(images: list) -> dict:
    """Context-free caption first: the judge later cannot talk itself into 'this purple swirl is Saturn'."""
    return _call(BLIND.format(n=len(images)), images, max_tokens=400)


def _hard_reject(b: dict, req: dict):
    for k in ("text_or_watermark_dominant", "celestial_body_visible", "earth_scenery_visible", "real_photo_or_footage"):
        if isinstance(b.get(k), str):
            b[k] = b[k].strip().lower() == "true"
    setting = str(b.get("setting", "")).lower()
    if setting == "text slide":
        return "text slide"
    if b.get("text_or_watermark_dominant"):
        return "text/caption plate dominates the frame"
    if req.get("space"):
        if b.get("earth_scenery_visible") or setting in ("earth outdoors", "indoors"):
            return f"earth scene ({b.get('main_subject', '')}) for an astronomy line"
        if setting == "abstract graphic":
            return "abstract graphic, not the real subject"
        if not b.get("celestial_body_visible") and setting != "diagram or chart":
            return "no planet/moon/rings visible"
    return None


@_guard
def analyze_clip(images: list, req: dict) -> dict:
    """Frames of ONE candidate clip (in time order) vs the scene requirements -> scores 0..1 + verdict."""
    prompt = (
        "You are the visual analyzer of a factual documentary editor. Judge ONLY what is actually visible in these "
        f"{len(images)} frames (sampled in time order from one stock clip). Ignore any title or search keyword.\n"
        f"SCENE REQUIREMENTS:\n{_req_text(req)}\n\n"
        "Score each 0-10: subject_match (is the required subject itself visible, e.g. the actual planet Saturn, not "
        "another planet/object), semantic_relevance (does it support the narration), object_visibility, "
        "action_context, shot_suitability, temporal_consistency (all frames stay on-subject; no cut to unrelated "
        "content), visual_quality. Anything listed under Must NOT appear, visible text/logos/watermarks as the "
        "main content, people/offices/cars for an astronomy line, a planet photoshopped over an Earth landscape/sky (fantasy composite presented as real), toys/models/props instead of the real object, or the wrong object => REJECT.\n"
        'Reply with JSON only: {"seen": "what the frames really show, <=15 words", "subject_match": n, '
        '"semantic_relevance": n, "object_visibility": n, "action_context": n, "shot_suitability": n, '
        '"temporal_consistency": n, "visual_quality": n, "verdict": "ACCEPT" or "REJECT", "reason": "<=20 words"}')
    b = _blind(images)
    hard = _hard_reject(b, req)
    if hard:
        print(f"[analyzer] blind: {b.get('description', '')[:90]} -> REJECT ({hard})")
        return {"scores": {k: 0.0 for k in KEYS}, "overall": 0.0, "accept": False,
                "seen": str(b.get("description", ""))[:120], "reason": hard, "blind": b}
    prompt += ("\nAn independent viewer who was NOT told the topic described these frames as: "
               f"\"{b.get('description', '')}\" (main subject: {b.get('main_subject', '')}; features: "
               f"{b.get('body_features', '')}). Treat that description as ground truth; if it does not match the "
               "required subject (e.g. a grey cratered moon is not Titan's orange haze, a generic planet is not "
               "Saturn unless rings/bands are described), REJECT.")
    j = _call(prompt, images)
    s = {k: max(0.0, min(1.0, float(j.get(k, 0) or 0) / 10)) for k in KEYS}
    overall = round(0.3 * s["subject_match"] + 0.25 * s["semantic_relevance"] + 0.1 * s["object_visibility"]
                    + 0.1 * s["action_context"] + 0.08 * s["shot_suitability"] + 0.1 * s["temporal_consistency"]
                    + 0.07 * s["visual_quality"], 3)
    seen = str(j.get("seen", "")).lower()
    # The analyzer's own description is binding: an astronomy shot it describes as sitting on Earth scenery
    # (water, shore, sky, cockpit...) is a composite or a wrong object, whatever score it gave.
    earthly = bool(req.get("space")) and re.search(
        r"\b(water|ocean|sea|shore|beach|lake|land|desert|snow|sky|cloudy sky|cockpit|room|street|city|people|person|model|toy|globe)\b", seen) \
        and not re.search(r"\b(water (ice|vapou?r|plumes?)|ice|space|orbit)\b", seen)
    ok = (not earthly and str(j.get("verdict", "")).upper().startswith("ACCEPT") and overall >= ACCEPT_BAR
          and s["subject_match"] >= 0.6 and s["temporal_consistency"] >= 0.5)
    return {"scores": s, "overall": overall, "accept": ok, "seen": str(b.get("description", ""))[:120],
            "reason": str(j.get("reason", ""))[:160]}


@_guard
def qa_scene(images: list, req: dict) -> dict:
    """Frames of a RENDERED scene (captions included) vs its narration -> PASS/FAIL + reason."""
    prompt = (
        "You are the final visual QA reviewer of a factual vertical reel. These frames come from ONE rendered scene, "
        "in time order (burned-in captions are expected; ignore them). Decide whether the visuals genuinely support "
        f"the narration.\nSCENE:\n{_req_text(req)}\n\n"
        "Abstract facts (density, mass, distance, temperature) cannot be filmed literally: a clear real shot of the "
        "required subject IS valid support; do not fail a scene for not depicting the impossible literally.\n"
        "FAIL when: the required subject is absent, the footage is unrelated/generic/misleading, a Must-NOT item "
        "appears, the frames are black/blank/corrupted, or the scene is a static image that stays irrelevant.\n"
        'Reply with JSON only: {"seen": "<=15 words", "relevance": 0-10, "result": "PASS" or "FAIL", "reason": "<=20 words"}')
    b = _blind(images)
    hard = _hard_reject(b, req) if not str(req.get("required_subject", "")).startswith("readable infographic") else None
    if hard:
        return {"result": "FAIL", "relevance": 0.0, "seen": str(b.get("description", ""))[:120], "reason": hard}
    prompt += ("\nAn independent viewer who was NOT told the topic described these frames as: "
               f"\"{b.get('description', '')}\" (features: {b.get('body_features', '')}). Treat it as ground truth.")
    j = _call(prompt, images, max_tokens=500)
    j["seen"] = b.get("description", j.get("seen", ""))
    rel = max(0.0, min(1.0, float(j.get("relevance", 0) or 0) / 10))
    ok = str(j.get("result", "")).upper().startswith("PASS") and rel >= 0.6
    return {"result": "PASS" if ok else "FAIL", "relevance": round(rel, 2), "seen": str(j.get("seen", ""))[:120],
            "reason": str(j.get("reason", ""))[:160]}


def ready() -> bool:
    """Probe once with a tiny generated frame so a dead analyzer is known before the expensive steps."""
    if STATE.get("probed") is not None:
        return STATE["probed"]
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=1", "-frames:v", "1",
                        "-f", "image2", "-c:v", "mjpeg", "-"], capture_output=True, timeout=30)
    t0 = time.time()
    try:
        j = _call('What is shown? Reply JSON only: {"seen": "..."}', [base64.b64encode(r.stdout).decode()], 200)
        print(f"[analyzer] {OMNI} ready ({time.time() - t0:.1f}s): {str(j)[:80]}")
        STATE["probed"] = True
    except Exception as e:
        print(f"[analyzer] {OMNI} NOT available: {str(e)[:200]}")
        STATE["last_error"] = str(e)[:200]
        STATE["probed"] = False
        STATE["down"] = True
    return STATE["probed"]
