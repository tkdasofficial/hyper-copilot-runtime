"""
Sound design: whoosh / impact / riser / reveal SFX (Drive "Audio Library/SFX"
files when present, otherwise synthesised with ffmpeg), placed from the
storyboard, sparingly. Music intensity follows storyboard beats, ducked under
the narration, with a limiter and loudness normalisation at the end.
"""
import os, subprocess
from pathlib import Path

import requests

SYNTH = {  # ffmpeg lavfi sources (ffmpeg 4.4 compatible)
    "whoosh": "anoisesrc=d=0.55:c=pink:a=0.6,highpass=f=350,lowpass=f=5000,afade=t=in:st=0:d=0.3,afade=t=out:st=0.3:d=0.25",
    "impact": "aevalsrc='0.95*sin(2*PI*(58-26*t)*t)*exp(-4.5*t)+0.25*(random(0)-0.5)*exp(-18*t)':d=1.1:s=44100",
    "riser": "aevalsrc='0.35*sin(2*PI*(180+620*t*t)*t)*(t/1.6)':d=1.6:s=44100,afade=t=out:st=1.5:d=0.1",
    "reveal": "aevalsrc='0.4*sin(2*PI*880*t)*exp(-3*t)+0.3*sin(2*PI*1320*t)*exp(-4*t)':d=1.2:s=44100",
}
LEVELS = {"off": 0.0, "low": 0.35, "medium": 0.6, "high": 0.85}
MUSIC_LEVELS = {"off": 0.0, "low": 0.06, "medium": 0.09, "high": 0.13}


def _drive_sfx(token_fn) -> dict:
    """Tagged SFX files in Audio Library/SFX, e.g. 'whoosh fast.mp3', 'impact [reveal].wav'."""
    try:
        tok = token_fn()
        h = {"Authorization": f"Bearer {tok}"}
        root = os.environ.get("GDRIVE_ROOT_FOLDER_ID") or os.environ.get("GDRIVE_MAIN_FOLDER_ID")

        def folder(name, parent):
            q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and '{parent}' in parents and trashed=false"
            f = requests.get("https://www.googleapis.com/drive/v3/files", headers=h, timeout=20,
                             params={"q": q, "fields": "files(id)", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}).json()
            return (f.get("files") or [{}])[0].get("id")

        lib = folder("Audio Library", root)
        sfx = folder("SFX", lib) if lib else None
        if not sfx:
            return {}
        q = f"'{sfx}' in parents and trashed=false and mimeType contains 'audio/'"
        files = requests.get("https://www.googleapis.com/drive/v3/files", headers=h, timeout=20,
                             params={"q": q, "fields": "files(id,name)", "pageSize": 200, "supportsAllDrives": "true",
                                     "includeItemsFromAllDrives": "true"}).json().get("files", [])
        found = {}
        for f in files:
            for kind in SYNTH:
                if kind in f["name"].lower() and kind not in found:
                    found[kind] = (f["id"], h)
        return found
    except Exception as e:
        print("[sound] Drive SFX lookup failed:", e)
        return {}


def prepare_sfx(work: Path, token_fn) -> dict:
    lib = _drive_sfx(token_fn)
    out = {}
    for kind, src in SYNTH.items():
        dest = work / f"sfx_{kind}.wav"
        try:
            if kind in lib:
                fid, h = lib[kind]
                r = requests.get(f"https://www.googleapis.com/drive/v3/files/{fid}?alt=media&supportsAllDrives=true", headers=h, timeout=60)
                raw = work / f"sfx_{kind}_src"
                raw.write_bytes(r.content)
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-t", "2.5", "-ar", "44100", "-ac", "1", str(dest)], check=True)
                print(f"[sound] {kind}: Drive library")
            else:
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", src, "-ar", "44100", "-ac", "1", str(dest)], check=True)
            out[kind] = dest
        except Exception as e:
            print(f"[sound] {kind} unavailable:", e)
    return out


def plan_cues(timeline: list, level: str) -> list:
    """[(time, kind)] from storyboard sfx + purpose. Sparse: never on every cut."""
    if LEVELS.get(level, 0.6) == 0:
        return []
    cues, last_whoosh = [], -99.0
    for i, sc in enumerate(timeline):
        want = str(sc.get("sfx") or "").lower()
        purpose = str(sc.get("purpose") or "").lower()
        t0 = sc["start"]
        if purpose == "payoff" and i > 0:
            cues.append((max(0.0, t0 - 1.5), "riser"))
        if purpose == "reveal" or want == "impact":
            cues.append((t0 + sc.get("lead", 0.0), "impact"))
        elif want == "reveal":
            cues.append((t0, "reveal"))
        elif i > 0 and (want == "whoosh" or str(sc.get("transition", "")).lower() == "whoosh") and t0 - last_whoosh > 5.0:
            cues.append((max(0.0, t0 - 0.25), "whoosh"))
            last_whoosh = t0
    return cues[: max(3, len(timeline) // 2 + 2)]


def mix(narr: Path, total: float, out: Path, music, music_level: str, sfx: dict, cues: list,
        sfx_level: str, timeline: list):
    inputs = ["-i", str(narr)]
    filt, mixin, idx = [], ["[0:a]"], 1
    mvol = MUSIC_LEVELS.get(music_level, 0.09)
    if music and mvol > 0:
        # Music intensity follows the beats: louder on high-intensity scenes, quieter on low.
        gain = {"high": 1.25, "low": 0.75}
        expr = "+".join(f"between(t,{sc['start']:.2f},{sc['end']:.2f})*{gain.get(str(sc.get('music_intensity', '')).lower(), 1.0)}"
                        for sc in timeline) or "1"
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        filt.append(f"[1:a]aresample=44100,atrim=0:{total:.3f},volume='{mvol}*({expr})':eval=frame,"
                    f"afade=t=in:st=0:d=1.0,afade=t=out:st={max(0, total - 1.8):.3f}:d=1.8[m]")
        filt.append("[m][0:a]sidechaincompress=threshold=0.04:ratio=7:attack=15:release=320[duck]")
        mixin.append("[duck]")
        idx = 2
    lvl = LEVELS.get(sfx_level, 0.6)
    for t, kind in cues:
        if kind not in sfx:
            continue
        inputs += ["-i", str(sfx[kind])]
        ms = int(t * 1000)
        filt.append(f"[{idx}:a]volume={lvl * (0.55 if kind == 'whoosh' else 0.8):.2f},adelay={ms}|{ms}[s{idx}]")
        mixin.append(f"[s{idx}]")
        idx += 1
    filt.append("".join(mixin) + f"amix=inputs={len(mixin)}:duration=first:normalize=0,"
                "alimiter=limit=0.89:level=false,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[out]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filt), "-map", "[out]",
                    "-t", f"{total:.3f}", "-c:a", "aac", "-b:a", "192k", str(out)], check=True, timeout=900)
