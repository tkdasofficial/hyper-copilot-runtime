"""
Director layer for the reel engine: research + claim verification, hook
selection, story structure, storyboard/visual bible, pronunciation and the
AI critic. Every function degrades gracefully: if research or the critic is
unavailable the render still proceeds with the previous behaviour.
"""
import json, os, re, time
from urllib.parse import quote

import requests

NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
TEXT_MODELS = ["nvidia/nemotron-3-ultra-550b-a55b", "meta/llama-3.3-70b-instruct"]
UA = {"User-Agent": "HyperCopilotReel/3.0 (research bot; contact via github.com/tkdasofficial)"}
AUTHORITY = ("nasa.gov", "esa.int", "noaa.gov", "nih.gov", "who.int", ".gov", ".edu", ".ac.", "isro.gov.in",
             "britannica.com", "nationalgeographic.com", "nature.com", "science.org", "si.edu", "wikipedia.org")


# ---------------------------------------------------------------- LLM
def llm_json(system: str, user: str, temperature=0.5, retries=3, timeout=300) -> dict:
    key = os.environ.get("NVIDIA_API_KEY", "")
    last = None
    for model in TEXT_MODELS:
        for attempt in range(retries):
            try:
                r = requests.post(NIM_URL, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                                  json={"model": model, "temperature": temperature, "max_tokens": 16000,
                                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
                                  timeout=timeout)
                if r.status_code >= 400:
                    raise RuntimeError(f"NIM {r.status_code}: {r.text[:300]}")
                msg = r.json()["choices"][0]["message"]
                text = msg.get("content") or ""
                if "{" not in text:
                    text = (msg.get("reasoning_content") or "") + text
                text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
                m = re.search(r"\{.*\}", text, flags=re.S)
                return json.loads(m.group(0))
            except Exception as e:
                last = e
                print(f"[director] llm attempt {attempt + 1} failed:", str(e)[:200])
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"AI request failed: {last}")


VISION_STATE = {"model": None, "dead": set(), "fails": 0, "disabled": False, "calls": 0}
VISION_MODELS = ["meta/llama-4-maverick-17b-128e-instruct", "meta/llama-3.2-90b-vision-instruct",
                 "microsoft/phi-4-multimodal-instruct", "meta/llama-3.2-11b-vision-instruct",
                 "@cf/meta/llama-3.2-11b-vision-instruct", "@cf/llava-hf/llava-1.5-7b-hf"]
_CF_AGREED = set()


_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _parse_score(text):
    m = re.search(r"\"?score\"?\s*[:=]\s*(\d+(?:\.\d+)?)", text) or re.search(r"\b(\d+(?:\.\d+)?)\s*/\s*10", text)
    if not m:
        m = re.search(r"\b(?:score|rate|rating)\D{0,12}(\d+(?:\.\d+)?)\b", text, re.I)
    if not m:
        w = re.search(r"\b(" + "|".join(_WORDS) + r")\s*(?:out of|/)\s*(?:10|ten)\b", text, re.I)
        if w:
            return _WORDS[w.group(1).lower()] / 10
        raise ValueError("no score in reply: " + text[:80])
    return max(0.0, min(1.0, float(m.group(1)) / 10))


def _cf_vision(model, image_b64, prompt, timeout):
    """Cloudflare Workers AI vision fallback (independent of NVIDIA availability)."""
    acc, tok = os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""), os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if not acc or not tok:
        raise LookupError("cloudflare not configured")
    url = f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{model}"
    h = {"Authorization": f"Bearer {tok}"}
    if "llama-3.2" in model and model not in _CF_AGREED:  # one-time Meta license acceptance required by Workers AI
        requests.post(url, headers=h, json={"prompt": "agree"}, timeout=timeout)
        _CF_AGREED.add(model)
    import base64 as _b
    body = ({"image": list(_b.b64decode(image_b64)), "prompt": prompt, "max_tokens": 120} if "llava" in model else
            {"prompt": prompt, "image": list(_b.b64decode(image_b64)), "max_tokens": 120})
    r = requests.post(url, headers=h, json=body, timeout=timeout)
    if r.status_code in (400, 401, 403, 404, 422):
        raise LookupError(f"{r.status_code} {r.text[:120]}")
    r.raise_for_status()
    res = r.json().get("result") or {}
    out = res.get("response") or res.get("description") or ""
    return _parse_score(out if isinstance(out, str) else json.dumps(out))


import threading
_VLOCK = threading.Lock()


def _vision_call(model, image_b64, prompt, timeout):
    # One vision request at a time with 429 back-off: parallel bursts made NVIDIA rate-limit every check.
    with _VLOCK:
        for wait in (0, 4, 10, 20):
            if wait:
                time.sleep(wait)
            try:
                return _vision_once(model, image_b64, prompt, timeout)
            except requests.HTTPError as e:
                if getattr(e.response, "status_code", 0) not in (429, 500, 502, 503) or wait == 20:
                    raise
                ra = e.response.headers.get("Retry-After", "")
                if ra.isdigit():
                    time.sleep(min(30, int(ra)))


def _vision_once(model, image_b64, prompt, timeout):
    if model.startswith("@cf/"):
        return _cf_vision(model, image_b64, prompt, timeout)
    key = os.environ.get("NVIDIA_API_KEY", "")
    r = requests.post(NIM_URL, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json={"model": model, "temperature": 0.1, "max_tokens": 120,
                            "messages": [{"role": "user", "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}]}]},
                      timeout=timeout)
    if r.status_code in (400, 401, 403, 404, 422):
        raise LookupError(f"{r.status_code}")
    r.raise_for_status()
    return _parse_score(r.json()["choices"][0]["message"].get("content") or "")


def vision_ready(sample_b64: str) -> bool:
    """Pick the first vision model that answers quickly; disable vision for the render if none does."""
    if VISION_STATE["model"] or VISION_STATE["disabled"]:
        return bool(VISION_STATE["model"])
    for model in [m for m in VISION_MODELS if m not in VISION_STATE["dead"]]:
        t0 = time.time()
        try:
            try:
                _vision_call(model, sample_b64, 'Rate 0-10 how sharp this image is. Reply JSON only: {"score": n}', 30)
            except ValueError:
                pass  # the model answered (just not in JSON): it is reachable and can see the image
            VISION_STATE["model"] = model
            print(f"[vision] using {model} ({time.time() - t0:.1f}s probe)")
            return True
        except Exception as e:
            VISION_STATE["dead"].add(model)
            print(f"[vision] {model} unavailable: {str(e)[:100]}")
    VISION_STATE["disabled"] = True
    print("[vision] no vision model available: relevance falls back to stock labels")
    return False


def vision_score(image_b64: str, subject: str, claim: str = ""):
    """0..1: does this frame show what the narrator is talking about? None when vision is unavailable."""
    if not image_b64 or VISION_STATE["disabled"] or not vision_ready(image_b64):
        return None
    prompt = (f"A short documentary scene is about: {subject}.\n" + (f"The narrator says (English gist): {claim}\n" if claim else "") +
              "Score how well THIS image shows that exact subject, 0-10. 9-10: clearly the exact subject. 6-8: the subject, "
              "loosely framed. 3-5: generic/related mood only. 0-2: unrelated or contradicting (wrong planet, wrong object, "
              "people/office when the topic is astronomy, text-heavy thumbnails). Reply with JSON only, no other words: {\"score\": n}")
    for attempt in range(2):
        if not VISION_STATE["model"] and not vision_ready(image_b64):
            return None
        try:
            VISION_STATE["calls"] += 1
            v = _vision_call(VISION_STATE["model"], image_b64, prompt, 35)
            VISION_STATE["fails"] = 0
            return v
        except Exception as e:
            VISION_STATE["fails"] += 1
            print("[vision] check failed:", str(e)[:100])
            if VISION_STATE["fails"] >= 4:  # circuit breaker: switch model, never let a dead model stall the render
                VISION_STATE["dead"].add(VISION_STATE["model"])
                print(f"[vision] {VISION_STATE['model']} dropped after repeated failures")
                VISION_STATE.update(model=None, fails=0)
                if not vision_ready(image_b64):
                    return None
    return None


# ---------------------------------------------------------------- research
def _get(url, **kw):
    return requests.get(url, headers=UA, timeout=kw.pop("timeout", 20), **kw)


def _strip_html(html: str) -> str:
    html = re.sub(r"<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _wiki(topic: str, n=3) -> list:
    out = []
    try:
        s = _get("https://en.wikipedia.org/w/api.php", params={"action": "query", "list": "search", "srsearch": topic,
                                                                "srlimit": n, "format": "json"}).json()
        for hit in s.get("query", {}).get("search", [])[:n]:
            t = hit["title"]
            ex = _get("https://en.wikipedia.org/w/api.php", params={"action": "query", "prop": "extracts", "explaintext": 1,
                                                                     "exsectionformat": "plain", "titles": t, "format": "json"}).json()
            page = next(iter(ex.get("query", {}).get("pages", {}).values()), {})
            text = (page.get("extract") or "")[:5000]
            if text:
                out.append({"url": f"https://en.wikipedia.org/wiki/{quote(t.replace(' ', '_'))}", "title": t, "text": text})
    except Exception as e:
        print("[research] wikipedia failed:", e)
    return out


def _web(topic: str, n=4) -> list:
    """DuckDuckGo HTML results, authoritative domains first."""
    out = []
    try:
        html = requests.post("https://html.duckduckgo.com/html/", data={"q": topic}, headers=UA, timeout=20).text
        links = re.findall(r'class="result__a" href="([^"]+)"', html)
        urls = []
        for l in links:
            m = re.search(r"uddg=([^&]+)", l)
            u = requests.utils.unquote(m.group(1)) if m else l
            if u.startswith("http") and "wikipedia.org" not in u and "youtube.com" not in u and u not in urls:
                urls.append(u)
        urls.sort(key=lambda u: 0 if any(a in u for a in AUTHORITY) else 1)
        for u in urls[: n + 3]:
            if len(out) >= n:
                break
            try:
                r = _get(u, timeout=15)
                if r.ok and "html" in r.headers.get("content-type", ""):
                    text = _strip_html(r.text[:400_000])[:4000]
                    if len(text) > 400:
                        out.append({"url": u, "title": u.split("/")[2], "text": text})
            except Exception:
                continue
    except Exception as e:
        print("[research] web search failed:", e)
    return out


_STOPW = set("the and for that with from this were have has was are its which their also into more than such other about "
             "been when after first most over only there these they them some what where while would could between".split())


def _tf(text: str) -> dict:
    tf = {}
    for w in re.findall(r"[a-z]{4,}", text.lower()):
        if w not in _STOPW:
            tf[w] = tf.get(w, 0) + 1
    return tf


def _cos(a: dict, b: dict) -> float:
    num = sum(v * b.get(k, 0) for k, v in a.items())
    den = (sum(v * v for v in a.values()) ** 0.5) * (sum(v * v for v in b.values()) ** 0.5)
    return num / den if den else 0.0


def research(cfg) -> list:
    """Collect sources for the topic, keeping only ones that are actually about it (no 'Sega Saturn' for the planet)."""
    depth = str(cfg.get("research_depth", "standard")).lower()
    if depth == "off":
        return []
    topic = re.sub(r"\b(top|\d+|facts?|about|amazing|interesting|unknown|reel|video|in hinglish|in hindi)\b", " ",
                   str(cfg["prompt"]), flags=re.I)
    topic = re.sub(r"\s+", " ", topic).strip() or str(cfg["prompt"])
    n_wiki, n_web = (2, 2) if depth == "light" else (4, 5) if depth == "deep" else (3, 3)
    wiki = _wiki(topic, n_wiki + 3)
    web = _web(f"{topic} facts", n_web + 2)
    sources = []
    if wiki:
        # Compare content WITHOUT the shared topic word, otherwise "Saturn V" and "Sega Saturn" look on-topic.
        tw = {w.lower() for w in re.findall(r"\w+", topic)}
        _strip = lambda d: {k: v for k, v in d.items() if k not in tw}
        main = _strip(_tf(wiki[0]["text"]))
        sources.append(wiki[0])
        for s in wiki[1:]:
            c = _cos(main, _strip(_tf(s["text"])))
            if c >= 0.35 and len(sources) < n_wiki:
                sources.append(s)
            else:
                print(f"[research] dropped off-topic source '{s['title']}' (similarity {c:.2f})")
        for s in web:
            c = _cos(main, _strip(_tf(s["text"])))
            if c >= 0.2 and len(sources) < n_wiki + n_web:
                sources.append(s)
            else:
                print(f"[research] dropped off-topic source {s['url']} (similarity {c:.2f})")
    else:
        sources = web[:n_web]
    for i, s in enumerate(sources):
        s["id"] = f"S{i + 1}"
        s["authority"] = any(a in s["url"] for a in AUTHORITY if a != "wikipedia.org")
    print(f"[research] {len(sources)} sources:", [s["url"] for s in sources])
    return sources


def sources_digest(sources: list, budget=14000) -> str:
    if not sources:
        return "NO SOURCES AVAILABLE — use only well-established, widely documented facts and avoid precise statistics you are not sure about."
    per = max(800, budget // len(sources))
    return "\n\n".join(f"[{s['id']}] {s['title']} ({s['url']}){' [AUTHORITATIVE]' if s['authority'] else ''}\n{s['text'][:per]}"
                       for s in sources)


def _nums(text: str) -> list:
    return [n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]


def _support(claim: str, text: str):
    """Best 2-sentence window of a source for this claim: (score 0..1, snippet). Numbers in the claim must appear."""
    terms = [w for w in _tf(claim)]
    nums = _nums(claim)
    if not terms and not nums:
        return 0.0, ""
    sents = re.split(r"(?<=[.!?])\s+", text)
    best, snip = 0.0, ""
    for k in range(len(sents)):
        win = " ".join(sents[k:k + 2])
        low = win.lower()
        hit = sum(1 for w in terms if w in low or (len(w) > 5 and w[:-2] in low))
        score = hit / max(1, len(terms))
        wn = set(_nums(win))
        if nums and not all(n in wn for n in nums):
            score *= 0.4  # the number itself is not in this passage
        if score > best:
            best, snip = score, win[:240]
    return round(best, 2), snip


def verify_claims(plan: dict, sources: list) -> list:
    """Checks each scene's claim against the text of its cited sources (and every other source).
    verified = supported by >=2 sources, or by one authoritative/Wikipedia source with strong overlap.
    single-source = one weaker supporting passage. unverified = no source text supports it."""
    report = []
    for i, sc in enumerate(plan.get("scenes", [])):
        claim = str(sc.get("claim") or "").strip()
        if not claim:
            sc["verification"] = "no-claim"
            report.append({"scene": i, "claim": "", "status": "no-claim", "sources": []})
            continue
        support = []
        for s in sources:
            score, snip = _support(claim, s["text"])
            if score >= 0.5:
                support.append({"id": s["id"], "url": s["url"], "score": score, "evidence": snip,
                                "strong": score >= 0.65 and (s["authority"] or "wikipedia.org" in s["url"])})
        support.sort(key=lambda x: -x["score"])
        status = ("verified" if len(support) >= 2 or any(x["strong"] for x in support)
                  else "single-source" if support else "unverified")
        sc["verification"] = status
        report.append({"scene": i, "claim": claim, "status": status, "cited": sc.get("sources") or [],
                       "sources": support[:3]})
    counts = {k: sum(1 for r in report if r["status"] == k) for k in ("verified", "single-source", "unverified")}
    print("[facts]", counts)
    return report


# ---------------------------------------------------------------- pronunciation
# TTS-only spellings; captions keep the original word (see restore_display).
PRONOUNCE = {
    "english": {"Phobos": "Foh-bos", "Deimos": "Day-mos", "Perseverance": "Per-seh-veer-ance",
                "ESA": "E-S-A", "CO2": "carbon dioxide", "CO₂": "carbon dioxide",
                "Betelgeuse": "Beetle-juice", "Uranus": "Yoor-a-nus", "Andromeda": "An-drom-eh-da"},
    "hindi": {"NASA": "नासा", "ISRO": "इसरो", "CO2": "कार्बन डाइऑक्साइड", "CO₂": "कार्बन डाइऑक्साइड"},
}
PRONOUNCE["hinglish"] = dict(PRONOUNCE["english"])


def _table(cfg, extra):
    return {**PRONOUNCE.get(str(cfg["language"]).lower(), {}), **(extra or {})}


def pronounce(text: str, cfg, extra=None) -> str:
    table = _table(cfg, extra)
    for word in sorted(table, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", table[word], text)
    return text


def restore_display(words: list, cfg, extra=None) -> list:
    """Map TTS spellings in word timings back to the display spelling for captions."""
    rev = {say.lower(): disp for disp, say in _table(cfg, extra).items()
           if len(say.split()) == 1 and len(disp.split()) == 1}
    out = []
    for ws, wd, tok in words:
        core = re.sub(r"[^\w\-]", "", tok)
        if core.lower() in rev:
            tok = tok.replace(core, rev[core.lower()])
        out.append((ws, wd, tok))
    return out


# ---------------------------------------------------------------- critic
CRITIC_SYSTEM = ("You are a strict short-form video editor and fact checker. You review a planned reel and return "
                 "concrete fixes as JSON only.")


def critique_script(plan: dict, cfg, verification: list, known_issues=None) -> dict:
    """Pass 1 (before voice): hook, story, ending, unverified claims -> rewrite fixes."""
    brief = [{"i": i, "purpose": s.get("purpose"), "narration": s.get("narration"), "claim": s.get("claim"),
              "verification": s.get("verification")} for i, s in enumerate(plan.get("scenes", []))]
    user = f"""Language: {cfg['language']}. Hook chosen: {json.dumps(plan.get('hook', {}), ensure_ascii=False)}
Scenes: {json.dumps(brief, ensure_ascii=False)}
Automatic checks already found (you MUST fix each of these): {json.dumps(known_issues or [], ensure_ascii=False)}
Check: is the first scene a compelling 1-3 second hook (no "Fact number 1" opener, no greeting)? Does it escalate to a strongest
reveal and end on a payoff/curiosity line (not just stopping)? Any scene whose factual claim is "unverified" must be rewritten to a
safer, well-established statement or softened. Keep the language rules and voice-ready text rules (numbers as words, no symbols).
Also check that scenes connect into one escalating story (not five disconnected encyclopedia lines) and that no claim is
exaggerated beyond what sources say. Do not give 9-10 if any issue remains.
Return {{"score": 0-10, "issues": ["..."], "rewrites": [{{"i": scene_index, "narration": "new narration", "claim": "updated English claim"}}]}}. Empty rewrites if fine."""
    try:
        return llm_json(CRITIC_SYSTEM, user, temperature=0.3, retries=2, timeout=240)
    except Exception as e:
        print("[critic] script review skipped:", e)
        return {"score": None, "issues": [], "rewrites": []}


def critique_edit(summary: list, cfg, known_issues=None) -> dict:
    """Pass 2 (after visual selection, before rendering): relevance, repetition, pacing -> per-scene visual fixes."""
    user = f"""Planned edit of a {cfg['language']} fact reel about {cfg.get('topic')}. Per scene: English gist, purpose,
footage clips (stock query, vision relevance 0-1 = does the frame show the subject, similarity to other shots 0-1,
weak flag, seconds), duration:
{json.dumps(summary, ensure_ascii=False)}
Automatic checks found: {json.dumps(known_issues or [], ensure_ascii=False)} — every scene listed there needs a fix.
Treat relevance below 0.6 as a wrong visual even if the stock query sounds right.
Find scenes where the visual does not support the narration, repeats the previous shot, or a long section feels static.
For each, return a better English stock-footage query (specific subject + shot type) or ask for an infographic when the
line is numeric/abstract. Return {{"score": 0-10, "issues": ["..."],
"fixes": [{{"i": scene_index, "action": "revisual" | "infographic", "query": "...", "shot_type": "..."}}]}}"""
    try:
        return llm_json(CRITIC_SYSTEM, user, temperature=0.3, retries=2, timeout=240)
    except Exception as e:
        print("[critic] edit review skipped:", e)
        return {"score": None, "issues": [], "fixes": []}
