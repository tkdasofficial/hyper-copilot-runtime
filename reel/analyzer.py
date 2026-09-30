"""
Visual Analyzer (Nemotron 3 Nano Omni 30B) + NASA Image & Video Library source.

Every clip is judged on frames extracted from the DOWNLOADED file (never on titles, tags or the search query).
One multi-image request per clip returns structured scores (0-100) + ACCEPT/REJECT decision.
The same model runs the final per-scene QA on frames of the complete rendered reel.
When the primary Nemotron model encounters provider resource exhaustion (503), it falls back to
verified vision models (e.g. meta/llama-3.2-11b-vision-instruct) so visual verification NEVER degrades
into unverified keyword matching.
"""
import base64, json, os, random, re, subprocess, threading, time
from pathlib import Path
import requests

NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
OMNI_PRIMARY = os.environ.get("VISUAL_ANALYZER_MODEL", "").strip() or "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
OMNI_BACKUPS = ["meta/llama-3.2-11b-vision-instruct", "meta/llama-3.2-90b-vision-instruct"]

STATE = {
    "calls": 0,
    "fails": 0,
    "down": False,
    "active_model": OMNI_PRIMARY,
    "last_error": "",
    "think_flag": True,
    "seconds": 0.0,
    "probed": None,
}

# Strict serialization lock prevents "Worker local total request limit reached (16/16)" on NVIDIA NIM
_LOCK = threading.Lock()
ACCEPT_THRESHOLD = 65  # Overall score out of 100 required for acceptance


# ---------------------------------------------------------------- NASA Image & Video Library
def search_nasa(q, cfg, photos=False):
    """images-api.nasa.gov search -> candidates with a real media file URL (resolved from the asset manifest)."""
    try:
        r = requests.get(
            "https://images-api.nasa.gov/search",
            params={"q": q[:100], "media_type": "image" if photos else "video", "page_size": 14},
            timeout=30,
        )
        items = r.json().get("collection", {}).get("items", [])
    except Exception as e:
        print("[nasa] search failed:", str(e)[:100])
        return []
    out = []
    for it in items[:14]:
        d = (it.get("data") or [{}])[0]
        nid = d.get("nasa_id")
        if not nid:
            continue
        label = " ".join([
            str(d.get("title", "")),
            " ".join(d.get("keywords") or []),
            str(d.get("description", ""))[:300],
        ]).lower()
        thumb = next((l.get("href") for l in it.get("links") or [] if l.get("rel") == "preview"), None)
        out.append({
            "id": f"na{re.sub(r'[^A-Za-z0-9]', '', nid)[:40]}",
            "nasa_id": nid,
            "label": label,
            "kind": "image" if photos else "video",
            "src": "nasa",
            "thumb": thumb,
            "url": None,
            "short": 1080,
            "portrait": False,
            "dur": 0,
        })
    return out


def resolve_nasa(c):
    """Pick a 720p-1080p mp4 (or large jpg) from the NASA asset manifest; sets c['url']."""
    if c.get("url"):
        return c["url"]
    try:
        hrefs = [
            x.get("href", "")
            for x in requests.get(
                f"https://images-api.nasa.gov/asset/{c['nasa_id']}",
                timeout=30,
            ).json().get("collection", {}).get("items", [])
        ]
    except Exception:
        return None
    hrefs = [h.replace("http://", "https://").replace(" ", "%20") for h in hrefs]
    if c["kind"] == "video":
        pref = ["~medium.mp4", "~large.mp4", "~orig.mp4", "~mobile.mp4"]
        pick = next((h for p in pref for h in hrefs if h.lower().endswith(p)), None) or next(
            (h for h in hrefs if h.lower().endswith(".mp4")), None
        )
    else:
        pick = next((h for p in ("~large.jpg", "~orig.jpg", "~medium.jpg") for h in hrefs if h.lower().endswith(p)), None)
    c["url"] = pick
    return pick


# ---------------------------------------------------------------- frames
def _duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        return float(out.strip())
    except Exception:
        return 0.0


def frames(path: Path, kind: str, n=6, start=0.0, end=None, width=448):
    """5-8 representative JPEG frames (base64) spread across [start, end] of the file, plus their dHashes."""
    import visuals
    if kind != "video":
        b = visuals.jpeg_b64(path, "image")
        return ([b] if b else []), [visuals.dhash(path, "image")]
    end = end if end is not None else _duration(path)
    span = max(0.2, (end or 1.0) - start)
    # Target 5 to 8 frames as required by specification
    n_frames = max(5, min(8, n))
    out, hashes = [], []
    for k in range(n_frames):
        at = f"{start + span * (k + 0.5) / n_frames:.2f}"
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", at, "-i", str(path), "-frames:v", "1",
             "-vf", f"scale={width}:-2", "-q:v", "5", "-f", "image2", "-c:v", "mjpeg", "-"],
            capture_output=True,
            timeout=40,
        )
        if r.stdout:
            out.append(base64.b64encode(r.stdout).decode())
            hashes.append(visuals.dhash(path, "video", at=at))
    return out, hashes


# ---------------------------------------------------------------- model call
def _parse(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    m = re.findall(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("no JSON in analyzer reply: " + text[:140])
    raw = m[-1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", raw))


def _call(prompt: str, images: list, max_tokens=1000) -> dict:
    """One Omni request (text + images). Handles 429/503 with back-off and fails over to backup vision models."""
    key = os.environ.get("NVIDIA_API_KEY", "")
    content = [{"type": "text", "text": prompt}] + [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}"}} for b in images
    ]

    candidate_models = [STATE["active_model"]] + [m for m in [OMNI_PRIMARY] + OMNI_BACKUPS if m != STATE["active_model"]]
    last_err = None

    for model in candidate_models:
        for attempt, wait in enumerate((0, 3, 7, 15)):
            if wait:
                time.sleep(wait + random.uniform(0.1, 0.5))
            body = {
                "model": model,
                "temperature": 0.1,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": "/no_think"},
                    {"role": "user", "content": content},
                ],
            }
            if "nemotron" in model and STATE["think_flag"]:
                body["chat_template_kwargs"] = {"enable_thinking": False}

            t0 = time.time()
            with _LOCK:
                try:
                    r = requests.post(
                        NIM_URL,
                        json=body,
                        timeout=(20, 150),
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    )
                except requests.RequestException as e:
                    last_err = e
                    continue
                finally:
                    STATE["seconds"] += time.time() - t0

            STATE["calls"] += 1

            if r.status_code == 400 and STATE["think_flag"] and "chat_template" in r.text:
                STATE["think_flag"] = False
                continue

            if r.status_code in (429, 503):
                # 503 Worker local total request limit reached or 429 rate limit
                last_err = RuntimeError(f"{r.status_code} on {model}: {r.text[:120]}")
                ra = r.headers.get("Retry-After", "")
                if ra.isdigit():
                    time.sleep(min(30, int(ra)))
                continue

            if r.status_code in (500, 502, 504):
                last_err = RuntimeError(f"{r.status_code} {r.text[:120]}")
                continue

            if r.status_code >= 400:
                print(f"[analyzer] model {model} returned {r.status_code}, trying next model")
                last_err = RuntimeError(f"{model} error {r.status_code}: {r.text[:200]}")
                break  # try next model

            try:
                msg = r.json()["choices"][0]["message"]
                text = msg.get("content") or ""
                if "{" not in text:
                    text = (msg.get("reasoning_content") or "") + text
                parsed = _parse(text)
                if model != STATE["active_model"]:
                    print(f"[analyzer] active model switched to {model}")
                    STATE["active_model"] = model
                return parsed
            except Exception as e:
                last_err = e
                continue

    raise RuntimeError(f"analyzer unavailable across models: {last_err}")


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
            if STATE["fails"] >= 8:
                STATE["down"] = True
                print("[analyzer] marked down after repeated failures; footage will be reported unverified")
            return None
    return inner


def _req_text(req: dict) -> str:
    lines = [
        f"- Reel topic: {req.get('topic')}",
        f"- Scene narration: {req.get('narration')}",
        f"- Factual claim: {req.get('claim') or 'none'}",
        f"- Visual objective: {req.get('visual_objective')}",
        f"- Primary required subject: {req.get('primary_subject') or req.get('required_subject')}",
        f"- Action/Context: {req.get('action_or_context') or req.get('required_action') or 'none'}",
        f"- Required visual elements: {', '.join(req.get('required_visual_elements') or []) or 'none'}",
        f"- Preferred shot type: {req.get('preferred_shot_type') or req.get('shot_type') or 'none'}",
        f"- Must NOT appear (PROHIBITED): {', '.join(req.get('prohibited_visual_elements') or req.get('must_not') or []) or 'none'}",
    ]
    return "\n".join(l for l in lines if l)


BLIND = (
    "Describe ONLY what is literally visible in these {n} frames (time order, one clip). You are NOT told what the "
    "clip is supposed to show - do not guess a topic, do not name a planet unless it is unmistakably visible.\n"
    'Reply with JSON only: {{"description": "<=25 words, literal", "main_subject": "<=6 words", '
    '"setting": "outer space" | "earth outdoors" | "indoors" | "abstract graphic" | "diagram or chart" | "text slide", '
    '"real_photo_or_footage": true/false, "celestial_body_visible": true/false, '
    '"body_features": "e.g. banded gas planet with rings / cratered grey moon / none", '
    '"text_or_watermark_dominant": true/false, "earth_scenery_visible": true/false}}'
)


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
            return f"earth scene ({b.get('main_subject', '')}) for an astronomy scene"
        if setting == "abstract graphic":
            return "abstract graphic, not the real subject"
        if not b.get("celestial_body_visible") and setting != "diagram or chart":
            return "no planet/moon/rings visible"
    return None


@_guard
def analyze_clip(images: list, req: dict) -> dict:
    """
    Frames of ONE candidate clip (in time order) vs the scene requirements.
    Evaluates:
      1. Subject match (0-100)
      2. Semantic relevance to narration (0-100)
      3. Required-object visibility (0-100)
      4. Action/context match (0-100)
      5. Shot suitability (0-100)
      6. Temporal consistency across frames (0-100)
      7. Visual quality/usability (0-100)
      8. Prohibited-element detection (list)
    Returns structured output with ACCEPT/REJECT decision.
    """
    b = _blind(images)
    hard = _hard_reject(b, req)
    if hard:
        print(f"[analyzer] blind: {b.get('description', '')[:90]} -> REJECT ({hard})")
        return {
            "decision": "REJECT",
            "score": 0,
            "subject_match": 0,
            "semantic_relevance": 0,
            "required_elements": 0,
            "action_context": 0,
            "shot_suitability": 0,
            "temporal_consistency": 0,
            "quality": 0,
            "prohibited_elements_detected": [hard],
            "missing_requirements": [req.get("primary_subject") or "subject missing"],
            "reason": hard,
            "seen": str(b.get("description", ""))[:120],
            "overall": 0.0,
            "accept": False,
            "scores": {k: 0.0 for k in ("subject_match", "semantic_relevance", "object_visibility",
                                       "action_context", "shot_suitability", "temporal_consistency", "visual_quality")},
        }

    prompt = (
        "You are the visual analyzer of a factual documentary editor. Judge ONLY what is actually visible in these "
        f"{len(images)} frames (sampled in time order from one candidate clip). Ignore any search keyword or title.\n\n"
        f"SCENE REQUIREMENTS:\n{_req_text(req)}\n\n"
        f"INDEPENDENT GROUND TRUTH OBSERVATION: \"{b.get('description', '')}\" "
        f"(main subject: {b.get('main_subject', '')}; features: {b.get('body_features', '')})\n\n"
        "Evaluate on a 0-100 scale:\n"
        "- subject_match: Is the exact required primary subject visible (e.g. the actual planet Saturn, not another planet or Earth landscape)?\n"
        "- semantic_relevance: Does the imagery genuinely support the factual narration and claim?\n"
        "- required_elements: Are the required visual elements visible in the frames?\n"
        "- action_context: Does the motion, angle, or context match the visual objective?\n"
        "- shot_suitability: Is the shot composition appropriate for this scene?\n"
        "- temporal_consistency: Do all frames stay consistently on-subject throughout the clip?\n"
        "- quality: High clarity, no black borders, no ugly digital watermarks, no blurry/corrupt frames.\n"
        "- prohibited_elements_detected: List any prohibited or contradictory items visible (e.g. Saturn V rocket, Earth sky, cars, people, toys/models). Return [] if none.\n"
        "- missing_requirements: List any required elements that are completely absent.\n"
        "- decision: 'ACCEPT' only if score >= 65 and subject_match >= 65 and semantic_relevance >= 60 and temporal_consistency >= 50 and NO prohibited elements. Otherwise 'REJECT'.\n\n"
        "Reply with JSON only:\n"
        "{\n"
        '  "decision": "ACCEPT" | "REJECT",\n'
        '  "score": 0-100,\n'
        '  "subject_match": 0-100,\n'
        '  "semantic_relevance": 0-100,\n'
        '  "required_elements": 0-100,\n'
        '  "action_context": 0-100,\n'
        '  "shot_suitability": 0-100,\n'
        '  "temporal_consistency": 0-100,\n'
        '  "quality": 0-100,\n'
        '  "prohibited_elements_detected": [],\n'
        '  "missing_requirements": [],\n'
        '  "seen": "<=20 words literal description",\n'
        '  "reason": "<=25 words explanation"\n'
        "}"
    )

    j = _call(prompt, images, max_tokens=600)

    # Normalize scores 0-100
    sm = max(0, min(100, int(float(j.get("subject_match", 0) or 0))))
    sr = max(0, min(100, int(float(j.get("semantic_relevance", 0) or 0))))
    re_score = max(0, min(100, int(float(j.get("required_elements", 0) or 0))))
    ac = max(0, min(100, int(float(j.get("action_context", 0) or 0))))
    ss = max(0, min(100, int(float(j.get("shot_suitability", 0) or 0))))
    tc = max(0, min(100, int(float(j.get("temporal_consistency", 0) or 0))))
    qu = max(0, min(100, int(float(j.get("quality", 0) or 0))))

    weighted_score = round(
        0.30 * sm + 0.25 * sr + 0.12 * re_score + 0.10 * ac + 0.08 * ss + 0.08 * tc + 0.07 * qu
    )
    score = j.get("score")
    if isinstance(score, (int, float)) and score > 0:
        final_score = int(score)
    else:
        final_score = weighted_score

    prohibited = [str(x) for x in (j.get("prohibited_elements_detected") or []) if str(x).strip()]
    missing = [str(x) for x in (j.get("missing_requirements") or []) if str(x).strip()]
    seen = str(j.get("seen", "")).lower()

    # Rule checks
    earthly = bool(req.get("space")) and re.search(
        r"\b(water|ocean|sea|shore|beach|lake|land|desert|snow|sky|cloudy sky|cockpit|room|street|city|people|person|model|toy|globe)\b",
        seen,
    ) and not re.search(r"\b(water (ice|vapou?r|plumes?)|ice|space|orbit)\b", seen)

    if earthly:
        prohibited.append("earthly scenery detected for space subject")

    dec = str(j.get("decision", "")).strip().upper()
    ok = (
        dec == "ACCEPT"
        and final_score >= ACCEPT_THRESHOLD
        and sm >= 60
        and sr >= 55
        and tc >= 50
        and len(prohibited) == 0
        and not earthly
    )

    reason = str(j.get("reason", ""))[:160]
    if not ok and dec == "ACCEPT":
        dec = "REJECT"
        if prohibited:
            reason = f"Prohibited elements: {', '.join(prohibited)}"
        elif sm < 60:
            reason = f"Subject match ({sm}/100) below threshold"
        elif sr < 55:
            reason = f"Semantic relevance ({sr}/100) below threshold"
        else:
            reason = f"Score ({final_score}/100) below threshold {ACCEPT_THRESHOLD}"

    legacy_scores = {
        "subject_match": sm / 100.0,
        "semantic_relevance": sr / 100.0,
        "object_visibility": re_score / 100.0,
        "action_context": ac / 100.0,
        "shot_suitability": ss / 100.0,
        "temporal_consistency": tc / 100.0,
        "visual_quality": qu / 100.0,
    }

    return {
        "decision": "ACCEPT" if ok else "REJECT",
        "score": final_score,
        "subject_match": sm,
        "semantic_relevance": sr,
        "required_elements": re_score,
        "action_context": ac,
        "shot_suitability": ss,
        "temporal_consistency": tc,
        "quality": qu,
        "prohibited_elements_detected": prohibited,
        "missing_requirements": missing,
        "seen": str(b.get("description", j.get("seen", "")))[:120],
        "reason": reason,
        "overall": round(final_score / 100.0, 3),
        "accept": ok,
        "scores": legacy_scores,
    }


@_guard
def qa_scene(images: list, req: dict) -> dict:
    """
    Critical Final Rendered-Video QA:
    Frames of a completed RENDERED scene (with burn-in captions) vs its narration and requirements.
    Compares:
      - actual narration
      - factual claim
      - scene visual requirements
      - actual rendered frames
    Produces PASS/FAIL decision with reason.
    """
    b = _blind(images)
    hard = (
        _hard_reject(b, req)
        if not str(req.get("primary_subject", "")).startswith("readable infographic")
        else None
    )
    if hard:
        return {
            "result": "FAIL",
            "relevance": 0.0,
            "seen": str(b.get("description", ""))[:120],
            "reason": f"Final rendered frames show {hard}",
            "score": 0,
        }

    prompt = (
        "You are the final visual QA reviewer of a factual documentary vertical reel.\n"
        "These frames come directly from the COMPLETED RENDERED OUTPUT for ONE scene (time order).\n"
        "(Burned-in subtitles/captions are expected on the video; focus on what footage is shown underneath).\n\n"
        f"SCENE SPECIFICATION:\n{_req_text(req)}\n\n"
        f"INDEPENDENT GROUND TRUTH OBSERVATION: \"{b.get('description', '')}\"\n\n"
        "Evaluation criteria:\n"
        "1. Does the footage shown on screen legitimately depict the required subject or astronomical context?\n"
        "2. Does it semantically support what the narration says?\n"
        "3. Did any prohibited element or wrong object make it into the final render?\n"
        "4. Is the footage corrupted, black, frozen, or showing generic irrelevant filler?\n\n"
        "Abstract facts (density, mass, speed, age) cannot be filmed literally: showing the real subject "
        "(e.g. Saturn in space) while the narration explains the fact IS valid.\n"
        "FAIL when: the required subject is absent, the footage is unrelated (wrong planet, Earth park, city, cars, models), "
        "or a prohibited element appears.\n\n"
        "Reply with JSON only:\n"
        "{\n"
        '  "seen": "<=20 words literal description",\n'
        '  "relevance": 0-100,\n'
        '  "result": "PASS" | "FAIL",\n'
        '  "reason": "<=25 words explanation",\n'
        '  "prohibited_detected": []\n'
        "}"
    )

    j = _call(prompt, images, max_tokens=500)
    seen = str(b.get("description", j.get("seen", "")))[:120]
    rel = max(0, min(100, int(float(j.get("relevance", 0) or 0))))
    res = str(j.get("result", "")).strip().upper()
    proh = [str(x) for x in (j.get("prohibited_detected") or []) if str(x).strip()]

    ok = (res == "PASS" and rel >= 60 and len(proh) == 0)
    reason = str(j.get("reason", ""))[:160]
    if not ok and res == "PASS":
        res = "FAIL"
        reason = f"Relevance score ({rel}/100) below threshold or prohibited elements: {proh}"

    return {
        "result": "PASS" if ok else "FAIL",
        "relevance": round(rel / 100.0, 2),
        "score": rel,
        "seen": seen,
        "reason": reason,
        "prohibited_detected": proh,
    }


def ready() -> bool:
    """Probe once with a tiny generated frame to verify visual analysis availability."""
    if STATE.get("probed") is not None:
        return STATE["probed"]
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=1", "-frames:v", "1",
         "-f", "image2", "-c:v", "mjpeg", "-"],
        capture_output=True,
        timeout=30,
    )
    t0 = time.time()
    try:
        j = _call('What is shown? Reply JSON only: {"seen": "..."}', [base64.b64encode(r.stdout).decode()], 200)
        print(f"[analyzer] active model {STATE['active_model']} ready ({time.time() - t0:.1f}s): {str(j)[:80]}")
        STATE["probed"] = True
    except Exception as e:
        print(f"[analyzer] visual analyzer NOT available: {str(e)[:200]}")
        STATE["last_error"] = str(e)[:200]
        STATE["probed"] = False
        STATE["down"] = True
    return STATE["probed"]
