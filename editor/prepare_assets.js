#!/usr/bin/env node
/**
 * Step 3: Import Stock Footages & Run Editor Asset Preparation
 * - AI Screenplay / Storyboard generation
 * - Voiceover generation with edge-tts and word-level timestamp extraction
 * - Word-by-word active highlight ASS / SRT / JSON subtitle generation
 * - Stock footage acquisition (Pexels / Pixabay)
 * - Automatic Audio Ducking (BGM attenuated to 15-20% during speech)
 */

const fs = require("fs");
const path = require("path");
const https = require("https");
const { execSync, spawnSync } = require("child_process");

function env(name, fallback = "") {
  return (process.env[name] || "").trim() || fallback;
}

const PROMPT = env("PROMPT", "The Wonders of the Universe");
const VIDEO_ID = env("VIDEO_ID", "vid_" + Date.now());
const DURATION_SECONDS = Math.max(10, parseInt(env("DURATION_SECONDS", "180"), 10) || 180);
const VOICE_GENDER = env("VOICE_GENDER", "male").toLowerCase();
const VOICE_PERSONA = env("VOICE_PERSONA", "Documentary");
const PEXELS_KEY = env("PEXELS_API_KEY");
const PIXABAY_KEY = env("PIXABAY_API_KEY");
const CLOUDFLARE_ID = env("CLOUDFLARE_ACCOUNT_ID");
const CLOUDFLARE_TOKEN = env("CLOUDFLARE_API_TOKEN");
const NVIDIA_KEY = env("NVIDIA_API_KEY");
const SUPABASE_URL = env("SUPABASE_URL").replace(/\/+$/, "");
const SUPABASE_KEY = env("SUPABASE_SERVICE_ROLE_KEY");

const ASSETS_DIR = path.resolve("assets");
if (!fs.existsSync(ASSETS_DIR)) {
  fs.mkdirSync(ASSETS_DIR, { recursive: true });
}

async function updateSupabase(progress, step, status = "processing", extra = {}) {
  const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(VIDEO_ID);
  if (!SUPABASE_URL || !SUPABASE_KEY || !isUuid) return;
  try {
    const payload = JSON.stringify({
      progress,
      step,
      status,
      updated_at: new Date().toISOString(),
      ...extra,
    });
    const url = new URL(`${SUPABASE_URL}/rest/v1/videos?id=eq.${VIDEO_ID}`);
    await new Promise((resolve) => {
      const req = https.request(
        url,
        {
          method: "PATCH",
          headers: {
            apikey: SUPABASE_KEY,
            Authorization: `Bearer ${SUPABASE_KEY}`,
            "Content-Type": "application/json",
            Prefer: "return=minimal",
          },
        },
        (res) => {
          res.on("data", () => {});
          res.on("end", resolve);
        },
      );
      req.on("error", () => resolve());
      req.write(payload);
      req.end();
    });
  } catch (err) {
    console.warn(`[Supabase Status] ${err.message}`);
  }
}

async function httpsGet(urlStr, headers = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlStr);
    const req = https.get(url, { headers }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        return httpsGet(res.headers.location, headers).then(resolve).catch(reject);
      }
      let body = "";
      res.on("data", (chunk) => (body += chunk));
      res.on("end", () => {
        try {
          resolve(JSON.parse(body));
        } catch {
          resolve(body);
        }
      });
    });
    req.on("error", reject);
  });
}

async function downloadBinary(urlStr, destPath) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(destPath);
    const getReq = (u) => {
      https
        .get(u, (res) => {
          if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
            return getReq(res.headers.location);
          }
          if (res.statusCode !== 200) {
            return reject(new Error(`Failed to download: HTTP ${res.statusCode}`));
          }
          res.pipe(file);
          file.on("finish", () => file.close(resolve));
        })
        .on("error", (err) => {
          fs.unlink(destPath, () => {});
          reject(err);
        });
    };
    getReq(urlStr);
  });
}

// -------------------------------------------------------------
// 1. Storyboard & Screenplay Generator
// -------------------------------------------------------------
async function generateStoryboard(promptText, targetDuration) {
  const sceneDuration = 5; // ~5 seconds per cut for cinematic pacing
  const numScenes = Math.max(3, Math.round(targetDuration / sceneDuration));
  console.log(
    `[Storyboard] Planning ${numScenes} scenes for ${targetDuration}s video on: "${promptText}"`,
  );

  // Cloudflare Workers AI
  if (CLOUDFLARE_ID && CLOUDFLARE_TOKEN) {
    try {
      console.log("[Storyboard] Querying Cloudflare LLaMA-3.1...");
      const cfUrl = `https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ID}/ai/run/@cf/meta/llama-3.1-8b-instruct`;
      const systemPrompt = `You are a world-class documentary director and screenplay writer.
For the topic: "${promptText}", generate a JSON object with a "scenes" array of exactly ${numScenes} scenes.
Each scene must have:
- "query": 3-5 high-relevance search keywords for stock footage on Pexels/Pixabay (NO punctuation).
- "narration": 1-2 captivating sentences of documentary voiceover.
Respond ONLY with valid JSON in the format: {"scenes": [{"query": "...", "narration": "..."}]}`;

      const res = await new Promise((resolve, reject) => {
        const req = https.request(
          new URL(cfUrl),
          {
            method: "POST",
            headers: {
              Authorization: `Bearer ${CLOUDFLARE_TOKEN}`,
              "Content-Type": "application/json",
            },
          },
          (resp) => {
            let b = "";
            resp.on("data", (d) => (b += d));
            resp.on("end", () => resolve(JSON.parse(b)));
          },
        );
        req.on("error", reject);
        req.write(JSON.stringify({ prompt: systemPrompt, max_tokens: 2048, temperature: 0.7 }));
        req.end();
      });

      const raw = res?.result?.response || "";
      const match = raw.match(/\{[\s\S]*"scenes"[\s\S]*\}/);
      if (match) {
        const parsed = JSON.parse(match[0]);
        if (Array.isArray(parsed.scenes) && parsed.scenes.length >= numScenes - 2) {
          console.log(
            `[Storyboard] Successfully acquired ${parsed.scenes.length} scenes from Cloudflare AI`,
          );
          return parsed.scenes.slice(0, numScenes);
        }
      }
    } catch (e) {
      console.warn(`[Storyboard] Cloudflare AI notice: ${e.message}`);
    }
  }

  // Domain-Specific Storyboard Engine
  return buildDomainStoryboard(promptText, numScenes);
}

function buildDomainStoryboard(promptText, count) {
  const p = promptText.toLowerCase();

  if (
    p.includes("milky way") ||
    p.includes("galaxy") ||
    p.includes("space") ||
    p.includes("universe") ||
    p.includes("cosmos") ||
    p.includes("star")
  ) {
    const spacePool = [
      {
        q: "deep space dark matter cosmic web universe",
        n: "Over thirteen billion years ago, in the violent dawn of the cosmos, primordial gas drifted across halos of invisible dark matter.",
      },
      {
        q: "nebula glowing star birth space hubble",
        n: "Vast pockets of hydrogen and helium collapsed under immense gravity, igniting the very first generation of stars.",
      },
      {
        q: "protogalaxy cosmic collision space dust",
        n: "Protogalactic fragments collided and coalesced, sparking intense gravitational shockwaves across the early universe.",
      },
      {
        q: "spiral galaxy spin stars astronomy cosmos",
        n: "Angular momentum caused the colossal maelstrom of gas and stars to flatten into an expansive rotating cosmic disc.",
      },
      {
        q: "supermassive black hole accretion disk gravity",
        n: "At the nucleus, an immense gravitational titan formed: Sagittarius A*, anchoring the evolving galaxy.",
      },
      {
        q: "stellar nursery glowing nebula cosmic dust",
        n: "Dense molecular clouds formed along spiral density waves, continuously birthing generations of new stellar systems.",
      },
      {
        q: "supernova cosmic explosion star death nebula",
        n: "Massive stars reached the end of their lifespans, detonating as supernovae and seeding space with heavy elements.",
      },
      {
        q: "interstellar medium dust clouds galaxy 4k",
        n: "These enriched stellar remnants formed complex planetary nebulae, preparing the cosmos for rocky planets.",
      },
      {
        q: "solar system sun planets forming space",
        n: "Five billion years ago, in the Orion spiral arm, our Solar System condensed from a spinning protoplanetary disk.",
      },
      {
        q: "milky way galaxy spiral arms cosmos 4k",
        n: "Today, the Milky Way thrives as a majestic stellar metropolis, harboring over one hundred billion stars.",
      },
      {
        q: "earth night sky milky way stars timelapse",
        n: "From our vantage point on Earth, this breathtaking galactic river arcs across our clear night skies.",
      },
      {
        q: "andromeda galaxy collision space future",
        n: "In four billion years, our galaxy will merge with Andromeda in an epic dance, forming a colossal elliptical supergalaxy.",
      },
      {
        q: "infinite universe galaxies deep field hubble",
        n: "The Milky Way remains an enduring testament to the wondrous, creative force of cosmic evolution.",
      },
    ];
    return interpolateScenes(spacePool, count);
  }

  if (
    p.includes("sea") ||
    p.includes("ocean") ||
    p.includes("deep sea") ||
    p.includes("marine") ||
    p.includes("underwater")
  ) {
    const oceanPool = [
      {
        q: "deep ocean underwater sunbeams blue water",
        n: "Beneath the restless surface of the open ocean lies Earth's most enigmatic and untouched frontier.",
      },
      {
        q: "coral reef tropical fish marine ecosystem",
        n: "Sunlit coral reefs burst with dazzling biodiversity, functioning as vibrant underwater cities of life.",
      },
      {
        q: "twilight zone deep ocean dark blue waters",
        n: "Descending deeper into the twilight zone, sunlight vanishes, surrendering to eternal darkness and pressure.",
      },
      {
        q: "bioluminescent jellyfish glowing deep sea creature",
        n: "Bioluminescent organisms illuminate the black depths with spectral living light to hunt and communicate.",
      },
      {
        q: "hydrothermal vent deep ocean volcanic smoke",
        n: "Along the ocean floor, hydrothermal vents spew superheated minerals, sustaining otherworldly chemosynthetic communities.",
      },
      {
        q: "giant squid deep sea abyss creature underwater",
        n: "In the immense abyssal plains, stealthy predators navigate the quiet expanse of extreme cold and pressure.",
      },
      {
        q: "whale migrating deep ocean marine life",
        n: "Great marine mammals traverse thousands of miles across oceanic highways, connecting global marine ecosystems.",
      },
      {
        q: "underwater kelp forest sea otters sunlight",
        n: "Towering kelp forests sway in rhythm with coastal currents, sheltering countless marine species.",
      },
      {
        q: "ocean waves sunset aerial drone cinematic",
        n: "The deep sea remains the vital life support system of our planet, driving our climate and supporting life on Earth.",
      },
    ];
    return interpolateScenes(oceanPool, count);
  }

  // Universal Documentary Pool
  const genericPool = [
    {
      q: `${promptText} cinematic documentary 4k`,
      n: `From the beginning of recorded understanding, ${promptText} has captivated our collective imagination.`,
    },
    {
      q: `${promptText} details perspective macro cinematic`,
      n: `Beneath the surface lies a rich complexity that shapes our modern perception and history.`,
    },
    {
      q: `${promptText} motion atmosphere majestic`,
      n: `Every subtle shift and dynamic transformation reveals another layer of this extraordinary subject.`,
    },
    {
      q: `${promptText} light shadow contrast cinematic`,
      n: `Through innovative exploration and focused observation, new revelations continue to unfold.`,
    },
    {
      q: `${promptText} wide view landscape horizon`,
      n: `As we look to the horizon, the enduring significance of this subject inspires our future vision.`,
    },
  ];
  return interpolateScenes(genericPool, count);
}

function interpolateScenes(pool, count) {
  const result = [];
  for (let i = 0; i < count; i++) {
    const item = pool[i % pool.length];
    result.push({
      query: item.q,
      narration: item.n,
    });
  }
  return result;
}

// -------------------------------------------------------------
// 2. Voiceover & Word-by-Word Active Captions
// -------------------------------------------------------------
async function synthesizeNarrationAndSubtitles(scenes) {
  console.log("[TTS] Synthesizing voiceover with edge-tts and extracting word-level timestamps...");
  const voice = VOICE_GENDER === "female" ? "en-US-JennyNeural" : "en-US-ChristopherNeural";

  const fullText = scenes.map((s) => s.narration).join(" ");
  const scriptPath = path.join(ASSETS_DIR, "narration_script.txt");
  const mp3Path = path.join(ASSETS_DIR, "narration.mp3");
  const vttPath = path.join(ASSETS_DIR, "narration.vtt");
  fs.writeFileSync(scriptPath, fullText, "utf-8");

  // Generate audio and word timestamps using edge-tts
  const ttsCmd = `edge-tts --voice "${voice}" --rate="+0%" -f "${scriptPath}" --write-media "${mp3Path}" --write-subtitles "${vttPath}" --words-in-cue 1`;
  console.log(`[TTS] Executing: ${ttsCmd}`);
  try {
    execSync(ttsCmd, { stdio: "inherit" });
  } catch (err) {
    console.warn(`[TTS] edge-tts error: ${err.message}. Falling back to default edge-tts run.`);
    try {
      execSync(
        `edge-tts --voice "${voice}" -f "${scriptPath}" --write-media "${mp3Path}" --write-subtitles "${vttPath}"`,
        { stdio: "inherit" },
      );
    } catch (e2) {
      console.warn(`[TTS] Secondary edge-tts failed. Generating procedural voice placeholder.`);
      execSync(
        `ffmpeg -y -f lavfi -i "sine=frequency=300:duration=${Math.max(10, scenes.length * 5)}" -c:a libmp3lame -b:a 192k "${mp3Path}"`,
        { stdio: "ignore" },
      );
    }
  }

  // Parse word-level timing
  let words = [];
  if (fs.existsSync(vttPath)) {
    const vttContent = fs.readFileSync(vttPath, "utf-8");
    words = parseVttWords(vttContent);
  }

  // If no words parsed, synthesize fallback word timestamps based on scene durations
  if (words.length === 0) {
    console.log("[TTS] Interpolating word timestamps from scene screenplay...");
    let curTime = 0.5;
    for (const sc of scenes) {
      const tokens = sc.narration.split(/\s+/).filter(Boolean);
      const durPerWord = Math.max(0.3, 4.5 / Math.max(1, tokens.length));
      for (const tok of tokens) {
        words.push({
          word: tok,
          start: curTime,
          end: curTime + durPerWord,
        });
        curTime += durPerWord;
      }
      curTime += 0.4;
    }
  }

  // Generate Structured Subtitles (JSON, SRT, and Word-by-Word Active Highlight ASS)
  const jsonPath = path.join(ASSETS_DIR, "subtitles.json");
  fs.writeFileSync(jsonPath, JSON.stringify(words, null, 2), "utf-8");

  const srtPath = path.join(ASSETS_DIR, "subtitles.srt");
  fs.writeFileSync(srtPath, generateSrt(words), "utf-8");

  const assPath = path.join(ASSETS_DIR, "captions.ass");
  const assContent = generateWordActiveAss(words);
  fs.writeFileSync(assPath, assContent, "utf-8");
  console.log(`[Captions] Generated active word-by-word highlight ASS subtitles at: ${assPath}`);

  return { mp3Path, words, assPath, srtPath, jsonPath };
}

function parseVttWords(vttContent) {
  const lines = vttContent.split(/\r?\n/);
  const words = [];
  let currentTimes = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line || line.startsWith("WEBVTT") || line.startsWith("NOTE")) continue;

    const timeMatch = line.match(
      /(\d{2}:\d{2}:\d{2}[\.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[\.,]\d{3})/,
    );
    if (timeMatch) {
      currentTimes = {
        start: timeToSeconds(timeMatch[1]),
        end: timeToSeconds(timeMatch[2]),
      };
    } else if (currentTimes) {
      const text = line.replace(/<[^>]+>/g, "").trim();
      if (text) {
        const split = text.split(/\s+/).filter(Boolean);
        const durPerWord = (currentTimes.end - currentTimes.start) / Math.max(1, split.length);
        split.forEach((w, idx) => {
          words.push({
            word: w,
            start: currentTimes.start + idx * durPerWord,
            end: currentTimes.start + (idx + 1) * durPerWord,
          });
        });
      }
      currentTimes = null;
    }
  }
  return words;
}

function timeToSeconds(tStr) {
  const parts = tStr.replace(",", ".").split(":");
  return parseFloat(parts[0]) * 3600 + parseFloat(parts[1]) * 60 + parseFloat(parts[2]);
}

function formatAssTime(seconds) {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  const s = Math.floor(secs);
  const cs = Math.floor((secs - s) * 100);
  return `${hrs}:${String(mins).padStart(2, "0")}:${String(s).padStart(2, "0")}.${String(cs).padStart(2, "0")}`;
}

function formatSrtTime(seconds) {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  const s = Math.floor(secs);
  const ms = Math.floor((secs - s) * 1000);
  return `${String(hrs).padStart(2, "0")}:${String(mins).padStart(2, "0")}:${String(s).padStart(2, "0")},${String(ms).padStart(3, "0")}`;
}

function generateSrt(words) {
  const CHUNK_SIZE = 5;
  const chunks = [];
  let cur = [];
  for (const w of words) {
    cur.push(w);
    if (cur.length >= CHUNK_SIZE || /[.!?]$/.test(w.word)) {
      chunks.push(cur);
      cur = [];
    }
  }
  if (cur.length > 0) chunks.push(cur);

  return chunks
    .map((c, i) => {
      const start = formatSrtTime(c[0].start);
      const end = formatSrtTime(c[c.length - 1].end);
      const text = c.map((item) => item.word).join(" ");
      return `${i + 1}\n${start} --> ${end}\n${text}\n`;
    })
    .join("\n");
}

function generateWordActiveAss(words) {
  const fontName = "DejaVu Sans,Noto Sans,FreeSans,Arial";
  const fontSize = 42;
  const highlightColor = "&H002EFFFF&"; // Glowing yellow/gold
  const textColor = "&H00FFFFFF&";
  const outlineColor = "&H00000000&";
  const backColor = "&H90000000&";

  const header = `[Script Info]
Title: Active Highlight Captions
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: WordActive,${fontName},${fontSize},${textColor},${highlightColor},${outlineColor},${backColor},-1,0,0,0,100,100,1.2,0,1,3.2,2.0,2,100,100,95,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
`;

  const CHUNK_SIZE = 4;
  const chunks = [];
  let cur = [];
  for (const w of words) {
    cur.push(w);
    if (cur.length >= CHUNK_SIZE || /[.!?]$/.test(w.word)) {
      chunks.push(cur);
      cur = [];
    }
  }
  if (cur.length > 0) chunks.push(cur);

  const events = [];
  for (const chunk of chunks) {
    for (let i = 0; i < chunk.length; i++) {
      const activeWord = chunk[i];
      const startTime = formatAssTime(activeWord.start);
      const rawEnd = i < chunk.length - 1 ? chunk[i + 1].start : activeWord.end;
      const endTime = formatAssTime(Math.max(activeWord.start + 0.1, rawEnd));

      const lineParts = chunk.map((item, idx) => {
        if (idx === i) {
          return `{\\c${highlightColor}}{\\b1}${item.word.toUpperCase()}{\\b0}{\\c${textColor}}`;
        }
        return item.word;
      });

      events.push(`Dialogue: 0,${startTime},${endTime},WordActive,,0,0,0,,${lineParts.join(" ")}`);
    }
  }

  return header + events.join("\n");
}

// -------------------------------------------------------------
// 3. Stock Footage Fetching (Pexels / Pixabay)
// -------------------------------------------------------------
const usedClipIds = new Set();

async function searchStockClip(query, index) {
  const destPath = path.join(ASSETS_DIR, `scene_${String(index).padStart(2, "0")}.mp4`);

  // Pexels API
  if (PEXELS_KEY) {
    try {
      const encQuery = encodeURIComponent(query.replace(/[^a-zA-Z0-9\s]/g, ""));
      const pexUrl = `https://api.pexels.com/videos/search?query=${encQuery}&orientation=landscape&per_page=10`;
      const res = await httpsGet(pexUrl, { Authorization: PEXELS_KEY });
      if (res && res.videos && res.videos.length > 0) {
        for (const vid of res.videos) {
          if (!usedClipIds.has(String(vid.id))) {
            const files = vid.video_files || [];
            files.sort((a, b) => (b.width || 0) - (a.width || 0));
            const best = files.find((f) => f.width && f.width >= 1280 && f.link) || files[0];
            if (best && best.link) {
              usedClipIds.add(String(vid.id));
              console.log(
                `[Pexels] Found clip for "${query}" (ID: ${vid.id}, ${best.width}x${best.height})`,
              );
              await downloadBinary(best.link, destPath);
              if (fs.existsSync(destPath) && fs.statSync(destPath).size > 10000) {
                return destPath;
              }
            }
          }
        }
      }
    } catch (e) {
      console.warn(`[Pexels] Search error: ${e.message}`);
    }
  }

  // Pixabay API
  if (PIXABAY_KEY) {
    try {
      const encQuery = encodeURIComponent(query.replace(/[^a-zA-Z0-9\s]/g, ""));
      const pxbUrl = `https://pixabay.com/api/videos/?key=${PIXABAY_KEY}&q=${encQuery}&orientation=horizontal&per_page=10`;
      const res = await httpsGet(pxbUrl);
      if (res && res.hits && res.hits.length > 0) {
        for (const hit of res.hits) {
          if (!usedClipIds.has(String(hit.id))) {
            const vids = hit.videos || {};
            const chosen = vids.large?.url
              ? vids.large
              : vids.medium?.url
                ? vids.medium
                : vids.small;
            if (chosen && chosen.url) {
              usedClipIds.add(String(hit.id));
              console.log(`[Pixabay] Found clip for "${query}" (ID: ${hit.id})`);
              await downloadBinary(chosen.url, destPath);
              if (fs.existsSync(destPath) && fs.statSync(destPath).size > 10000) {
                return destPath;
              }
            }
          }
        }
      }
    } catch (e) {
      console.warn(`[Pixabay] Search error: ${e.message}`);
    }
  }

  // Procedural 1080p Cinematic Backdrop
  console.log(`[Generator] Generating procedural 1080p backdrop for: "${query}"`);
  const colors = [
    "#0a1128",
    "#001f54",
    "#034078",
    "#1282a2",
    "#00293c",
    "#1b1b2f",
    "#1f4068",
    "#162447",
  ];
  const col = colors[index % colors.length];
  execSync(
    `ffmpeg -y -f lavfi -i "color=c=${col}:s=1920x1080:d=6,drawbox=x=0:y=0:w=1920:h=1080:color=white@0.03:t=fill" -c:v libx264 -preset ultrafast -pix_fmt yuv420p "${destPath}"`,
    { stdio: "ignore" },
  );
  return destPath;
}

// -------------------------------------------------------------
// 4. Audio Ducking (Reduce BGM to 15-20% during voiceover)
// -------------------------------------------------------------
async function mixAudioWithDucking(narrationMp3Path, targetDuration) {
  const mixedAudioPath = path.join(ASSETS_DIR, "mixed_audio.aac");
  console.log(
    "[Audio] Mixing Voiceover and Cinematic BGM with dynamic Audio Ducking (sidechaincompress)...",
  );

  // Create an ethereal harmonic ambient BGM pad and duck it under the voiceover
  // Voiceover triggers sidechain attenuation (ratio=5.5 down to ~18% gain, attack 40ms, release 350ms)
  const duckingCmd = `ffmpeg -y \
    -i "${narrationMp3Path}" \
    -f lavfi -i "aevalsrc=0.06*sin(2*PI*110*t)+0.04*sin(2*PI*164.81*t)+0.03*sin(2*PI*220*t)+0.02*sin(2*PI*329.63*t):d=${Math.ceil(targetDuration + 5)}:s=48000" \
    -filter_complex "\
      [0:a]aformat=channel_layouts=stereo:sample_rates=48000,asplit=2[v_sc][v_mix]; \
      [1:a]aformat=channel_layouts=stereo:sample_rates=48000,volume=0.28[v_bgm]; \
      [v_bgm][v_sc]sidechaincompress=threshold=0.08:ratio=5.5:attack=40:release=350[ducked_bgm]; \
      [ducked_bgm][v_mix]amix=inputs=2:duration=first:weights=1 1[aout]" \
    -map "[aout]" -c:a aac -b:a 192k "${mixedAudioPath}"`;

  try {
    execSync(duckingCmd, { stdio: "inherit" });
    console.log("[Audio] Successfully synthesized and ducked BGM audio track at:", mixedAudioPath);
  } catch (err) {
    console.warn(`[Audio] Ducking filter note: ${err.message}. Using standard voice audio.`);
    execSync(`ffmpeg -y -i "${narrationMp3Path}" -c:a aac -b:a 192k "${mixedAudioPath}"`, {
      stdio: "ignore",
    });
  }

  return mixedAudioPath;
}

// -------------------------------------------------------------
// Main Execution for Step 3
// -------------------------------------------------------------
async function main() {
  console.log("====================================================");
  console.log("STEP 3: Import Stock Footages & Run Editor Preparation");
  console.log(`Prompt: "${PROMPT}"`);
  console.log(`Target Duration: ${DURATION_SECONDS}s`);
  console.log("====================================================");

  await updateSupabase(25, "Generating Screenplay & Storyboard");
  const scenes = await generateStoryboard(PROMPT, DURATION_SECONDS);

  await updateSupabase(40, "Synthesizing Voiceover & Active Captions");
  const { mp3Path, words, assPath, srtPath, jsonPath } =
    await synthesizeNarrationAndSubtitles(scenes);

  // Determine actual audio duration
  let voiceDuration = DURATION_SECONDS;
  try {
    const probe = execSync(
      `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "${mp3Path}"`,
    )
      .toString()
      .trim();
    const parsedD = parseFloat(probe);
    if (!isNaN(parsedD) && parsedD > 5) {
      voiceDuration = Math.ceil(parsedD);
    }
  } catch {}
  console.log(`[Audio] Voiceover duration: ${voiceDuration}s`);

  // Download stock video for each scene
  await updateSupabase(50, "Importing Stock Footage & Visual Assets");
  const sceneList = [];
  const secPerScene = Math.max(3, voiceDuration / scenes.length);

  for (let i = 0; i < scenes.length; i++) {
    const sc = scenes[i];
    console.log(`[Scene ${i + 1}/${scenes.length}] Acquiring footage: "${sc.query}"`);
    const filePath = await searchStockClip(sc.query, i);
    sceneList.push({
      index: i,
      query: sc.query,
      narration: sc.narration,
      file: filePath,
      duration: secPerScene,
      zoomType: i % 3 === 0 ? "zoom_in" : i % 3 === 1 ? "pan_lr" : "zoom_out",
    });
  }

  // Perform Audio Ducking
  await updateSupabase(65, "Mixing Audio with Dynamic Ducking");
  const mixedAudioFile = await mixAudioWithDucking(mp3Path, voiceDuration);

  // Write Manifest for Step 4
  const manifest = {
    prompt: PROMPT,
    videoId: VIDEO_ID,
    totalDuration: voiceDuration,
    width: 1920,
    height: 1080,
    fps: 30,
    scenes: sceneList,
    voiceFile: mp3Path,
    audioFile: mixedAudioFile,
    captionsAss: assPath,
    subtitlesSrt: srtPath,
    subtitlesJson: jsonPath,
  };

  const manifestPath = path.join(ASSETS_DIR, "manifest.json");
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), "utf-8");
  console.log(`[Assets] Wrote asset manifest to: ${manifestPath}`);

  // Create compatible timeline.json for C++ native engine if needed
  const timelineData = {
    output: {
      width: 1920,
      height: 1080,
      fps: 30,
      duration: voiceDuration,
      path: "out.mp4",
    },
    scenes: sceneList.map((s) => ({
      file: s.file,
      duration: s.duration,
      query: s.query,
    })),
    audio_tracks: [
      {
        file: mixedAudioFile,
        is_voiceover: true,
        volume: 1.0,
      },
    ],
  };
  fs.writeFileSync(
    path.join(ASSETS_DIR, "timeline.json"),
    JSON.stringify(timelineData, null, 2),
    "utf-8",
  );

  console.log("Step 3: Asset preparation successfully completed.");
}

if (require.main === module) {
  main().catch((err) => {
    console.error(`Fatal Step 3 Error: ${err.message}`);
    updateSupabase(0, `Asset prep failed: ${err.message}`, "failed").finally(() => {
      process.exit(1);
    });
  });
}

module.exports = {
  main,
  generateStoryboard,
  synthesizeNarrationAndSubtitles,
  searchStockClip,
  mixAudioWithDucking,
};
