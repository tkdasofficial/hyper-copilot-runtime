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
TEXT_MODELS = ["nvidia/nemotron-3-ultra-550b-a55b"]
VISION_MODELS = ["meta/llama-3.2-90b-vision-instruct", "meta/llama-3.2-11b-vision-instruct"]
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


_VISION_DEAD: set = set()


def vision_score(image_b64: str, narration: str, subject: str):
    """0..1 relevance of a frame to the narration; None when no vision model answers."""
    key = os.environ.get("NVIDIA_API_KEY", "")
    prompt = (f"Narration: \"{narration}\"\nIntended visual: {subject}\n"
              "Does this frame visually support the narration? Also penalise anything that contradicts it "
              "(wrong planet, wrong object, wrong place). Reply with JSON only: {\"score\": 0-10, \"why\": \"...\"}")
    for model in VISION_MODELS:
        if model in _VISION_DEAD:
            continue
        try:
            r = requests.post(NIM_URL, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                              json={"model": model, "temperature": 0.1, "max_tokens": 200,
                                    "messages": [{"role": "user", "content": [
                                        {"type": "text", "text": prompt},
                                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}]}]},
                              timeout=25)
            if r.status_code in (400, 404, 422):
                _VISION_DEAD.add(model)
                print(f"[director] vision model {model} unavailable ({r.status_code})")
                continue
            if not r.ok:
                continue
            text = r.json()["choices"][0]["message"].get("content") or ""
            m = re.search(r"\"?score\"?\s*[:=]\s*(\d+(?:\.\d+)?)", text) or re.search(r"\b(\d+(?:\.\d+)?)\s*/\s*10", text)
            if m:
                return max(0.0, min(1.0, float(m.group(1)) / 10))
        except Exception as e:
            print("[director] vision check failed:", str(e)[:120])
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


def research(cfg) -> list:
    """Collect sources for the topic. Returns [{id,url,title,text,authority}]."""
    depth = str(cfg.get("research_depth", "standard")).lower()
    if depth == "off":
        return []
    topic = re.sub(r"\b(top|\d+|facts?|about|amazing|interesting|reel|video)\b", " ", str(cfg["prompt"]), flags=re.I)
    topic = re.sub(r"\s+", " ", topic).strip() or str(cfg["prompt"])
    n_wiki, n_web = (2, 2) if depth == "light" else (4, 5) if depth == "deep" else (3, 3)
    sources = _wiki(topic, n_wiki) + _web(f"{topic} facts", n_web)
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


def verify_claims(plan: dict, sources: list) -> list:
    """Traceable claims: verified = >=2 sources, or 1 authoritative / Wikipedia source."""
    by_id = {s["id"]: s for s in sources}
    report = []
    for i, sc in enumerate(plan.get("scenes", [])):
        ids = [x for x in (sc.get("sources") or []) if x in by_id]
        strong = len(ids) >= 2 or any(by_id[x]["authority"] or "wikipedia.org" in by_id[x]["url"] for x in ids)
        status = "verified" if strong else ("single-source" if ids else ("no-claim" if not sc.get("claim") else "unverified"))
        sc["verification"] = status
        report.append({"scene": i, "claim": sc.get("claim", ""), "status": status,
                       "sources": [{"id": x, "url": by_id[x]["url"]} for x in ids]})
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


def critique_script(plan: dict, cfg, verification: list) -> dict:
    """Pass 1 (before voice): hook, story, ending, unverified claims -> rewrite fixes."""
    brief = [{"i": i, "purpose": s.get("purpose"), "narration": s.get("narration"), "verification": s.get("verification")}
             for i, s in enumerate(plan.get("scenes", []))]
    user = f"""Language: {cfg['language']}. Hook chosen: {json.dumps(plan.get('hook', {}), ensure_ascii=False)}
Scenes: {json.dumps(brief, ensure_ascii=False)}
Check: is the first scene a compelling 1-3 second hook (no "Fact number 1" opener, no greeting)? Does it escalate to a strongest
reveal and end on a payoff/curiosity line (not just stopping)? Any scene whose factual claim is "unverified" must be rewritten to a
safer, well-established statement or softened. Keep the language rules and voice-ready text rules (numbers as words, no symbols).
Return {{"score": 0-10, "issues": ["..."], "rewrites": [{{"i": scene_index, "narration": "new narration"}}]}}. Empty rewrites if fine."""
    try:
        return llm_json(CRITIC_SYSTEM, user, temperature=0.3, retries=2, timeout=240)
    except Exception as e:
        print("[critic] script review skipped:", e)
        return {"score": None, "issues": [], "rewrites": []}


def critique_edit(summary: list, cfg) -> dict:
    """Pass 2 (after visuals): relevance, repetition, pacing -> per-scene visual fixes."""
    user = f"""Edited timeline of a {cfg['language']} fact reel (per scene: narration, chosen footage label, vision relevance 0-1,
similarity to previous shot 0-1, shot type, duration seconds):
{json.dumps(summary, ensure_ascii=False)}
Find scenes where the visual does not support the narration, repeats the previous shot, or a long section feels static.
For each, return a better English stock-footage query (specific subject + shot type) or ask for an infographic when the
line is numeric/abstract. Return {{"score": 0-10, "issues": ["..."],
"fixes": [{{"i": scene_index, "action": "revisual" | "infographic", "query": "...", "shot_type": "..."}}]}}"""
    try:
        return llm_json(CRITIC_SYSTEM, user, temperature=0.3, retries=2, timeout=240)
    except Exception as e:
        print("[critic] edit review skipped:", e)
        return {"score": None, "issues": [], "fixes": []}
