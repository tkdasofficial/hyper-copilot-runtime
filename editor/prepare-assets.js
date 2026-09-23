#!/usr/bin/env node
/**
 * Step 3: Import Stock Footages & Run Editor Asset Preparation
 * - AI Screenplay / Storyboard generation
 * - Voiceover generation with edge-tts and word-level timestamp extraction
 * - Word-by-word active highlight ASS / SRT / JSON subtitle generation with bounding highlight boxes
 * - Stock footage acquisition (Pexels / Pixabay / AI visuals)
 * - Automatic Audio Ducking (BGM attenuated to 15-20% during speech)
 */

const fs = require("fs");
const path = require("path");
const https = require("https");
const { execSync } = require("child_process");

// Helper to parse CLI hyphenated flags or environment variables
function getParam(hyphenKey, envKey, fallback = "") {
  const args = process.argv.slice(2);
  for (let i = 0; i < args.length; i++) {
    if (args[i] === `--${hyphenKey}` && i + 1 < args.length) {
      return args[i + 1].trim();
    }
    if (args[i].startsWith(`--${hyphenKey}=`)) {
      return args[i].split("=")[1].trim();
    }
  }
  return (
    process.env[envKey] ||
    process.env[hyphenKey] ||
    process.env[envKey.toLowerCase()] ||
    fallback
  ).trim();
}

const PROMPT = getParam("prompt", "PROMPT", "The Wonders of the Universe");
const VIDEO_ID = getParam("video-id", "VIDEO_ID", "vid-" + Date.now());
const DURATION_SECONDS = Math.max(
  10,
  parseInt(getParam("duration-seconds", "DURATION_SECONDS", "180"), 10) || 180
);
const VOICE_GENDER = getParam("voice-gender", "VOICE_GENDER", "male").toLowerCase();
const VOICE_PERSONA = getParam("voice-persona", "VOICE_PERSONA", "Documentary");
const PEXELS_KEY = getParam("pexels-api-key", "PEXELS_API_KEY");
const PIXABAY_KEY = getParam("pixabay-api-key", "PIXABAY_API_KEY");
const CLOUDFLARE_ID = getParam("cloudflare-account-id", "CLOUDFLARE_ACCOUNT_ID");
const CLOUDFLARE_TOKEN = getParam("cloudflare-api-token", "CLOUDFLARE_API_TOKEN");
const NVIDIA_KEY = getParam("nvidia-api-key", "NVIDIA_API_KEY");
const SUPABASE_URL = (getParam("supabase-url", "SUPABASE_URL")).replace(/\/+$/, "");
const SUPABASE_KEY = getParam("supabase-service-role-key", "SUPABASE_SERVICE_ROLE_KEY");

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
        }
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
  const sceneDuration = 5;
  const numScenes = Math.max(3, Math.round(targetDuration / sceneDuration));
  console.log(`[Storyboard] Planning ${numScenes} scenes for ${targetDuration}s video on: "${promptText}"`);

  // Try Cloudflare Workers AI LLaMA-3.1
  if (CLOUDFLARE_ID && CLOUDFLARE_TOKEN) {
    try {
      console.log("[Storyboard] Querying Cloudflare LLaMA-3.1...");
      const cfUrl = `https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ID}/ai/run/@cf/meta/llama-3.1-8b-instruct`;
      const systemPrompt = `You are a world-class documentary director and screenplay writer.
For the topic: "${promptText}", generate a JSON object with a "scenes" array of exactly ${numScenes} scenes.
Each scene must have:
- "query": 3-5 high-relevance search keywords for stock footage on Pexels/Pixabay (NO punctuation).
- "narration": 1-2 captivating sentences of documentary voiceover.
Output ONLY valid JSON.`;

      const cfRes = await new Promise((resolve, reject) => {
        const req = https.request(
          cfUrl,
          {
            method: "POST",
            headers: {
              Authorization: `Bearer ${CLOUDFLARE_TOKEN}`,
              "Content-Type": "application/json",
            },
          },
          (res) => {
            let body = "";
            res.on("data", (chunk) => (body += chunk));
            res.on("end", () => {
              try {
                resolve(JSON.parse(body));
              } catch (e) {
                reject(e);
              }
            });
          }
        );
        req.on("error", reject);
        req.write(
          JSON.stringify({
            messages: [
              { role: "system", content: systemPrompt },
              { role: "user", content: `Topic: ${promptText}` },
            ],
          })
        );
        req.end();
      });

      let rawResponse = "";
      if (cfRes.result && cfRes.result.response) {
        rawResponse = cfRes.result.response;
      }

      const jsonMatch = rawResponse.match(/\{[\s\S]*"scenes"[\s\S]*\}/);
      if (jsonMatch) {
        const parsed = JSON.parse(jsonMatch[0]);
        if (parsed.scenes && Array.isArray(parsed.scenes) && parsed.scenes.length >= 3) {
          console.log(`[Storyboard] Successfully generated ${parsed.scenes.length} scenes via Cloudflare AI.`);
          return parsed.scenes.slice(0, numScenes);
        }
      }
    } catch (err) {
      console.warn(`[Storyboard] Cloudflare AI note: ${err.message}. Moving to topic storyboard.`);
    }
  }

  // Resilient Topic Storyboard Fallback
  console.log("[Storyboard] Generating high-production screenplay storyboard...");
  const cleanTopic = promptText.replace(/[^a-zA-Z0-9\s]/g, "").trim();
  const archetypes = [
    {
      q: `${cleanTopic} universe space cosmos`,
      n: `Throughout human history, few phenomena have captured our collective imagination quite like the enigmatic beauty of ${promptText}.`,
    },
    {
      q: `${cleanTopic} cinematic discovery research`,
      n: `Deep within the fabric of modern inquiry, groundbreaking discoveries continue to challenge our understanding of reality.`,
    },
    {
      q: `${cleanTopic} future technology visionary`,
      n: `Every moment opens a window into uncharted territory, revealing patterns hidden beneath the surface of the natural world.`,
    },
    {
      q: `${cleanTopic} majesty exploration landscape`,
      n: `As our instruments peer deeper across space and time, the boundaries between the known and the unknown begin to blur.`,
    },
    {
      q: `${cleanTopic} revelation illumination horizon`,
      n: `In the final reckoning, exploring this frontier reminds us that the universe is not only stranger than we imagine, but stranger than we can imagine.`,
    },
  ];

  const scenes = [];
  for (let i = 0; i < numScenes; i++) {
    const arc = archetypes[i % archetypes.length];
    scenes.push({
      query: arc.q,
      narration: arc.n,
    });
  }
  return scenes;
}

// -------------------------------------------------------------
// 2. Voiceover & Word-by-Word Active Highlight Subtitles
// -------------------------------------------------------------
async function synthesizeNarrationAndSubtitles(scenes) {
  console.log("[TTS] Synthesizing voiceover with edge-tts and extracting word-level timestamps...");
  const voice = VOICE_GENDER === "female" ? "en-US-JennyNeural" : "en-US-ChristopherNeural";
  const fullText = scenes.map((s) => s.narration).join(" ");
  const scriptPath = path.join(ASSETS_DIR, "narration-script.txt");
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
        { stdio: "inherit" }
      );
    } catch (e2) {
      console.warn(`[TTS] Secondary edge-tts failed. Generating procedural voice placeholder.`);
      execSync(
        `ffmpeg -y -f lavfi -i "sine=frequency=300:duration=${Math.max(10, scenes.length * 5)}" -c:a libmp3lame -b:a 192k "${mp3Path}"`,
        { stdio: "ignore" }
      );
    }
  }

  // Parse word-level timing
  let words = [];
  if (fs.existsSync(vttPath)) {
    const vttContent = fs.readFileSync(vttPath, "utf-8");
    words = parseVttWords(vttContent);
  }

  // Fallback word timestamps based on scene narration if needed
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

  // Generate Structured Subtitles (JSON, SRT, and Word-by-Word Active Highlight ASS with bounding box)
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
      /(\d{2}:\d{2}:\d{2}[\.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[\.,]\d{3})/
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
  // Use supported system fonts: DejaVu Sans and Noto Sans
  const fontName = "DejaVu Sans,Noto Sans CJK SC,FreeSans,Arial";
  const fontSize = 44;
  const highlightColor = "&H002EFFFF&"; // Radiant Gold / Neon Amber
  const textColor = "&H00FFFFFF&";      // Pure Crisp White
  const boxBgColor = "&HA0101014&";     // Sleek Dark Opaque Highlight Box
  const outlineColor = "&H00000000&";

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
Style: WordActive,${fontName},${fontSize},${textColor},${highlightColor},${boxBgColor},${outlineColor},-1,0,0,0,100,100,1.2,0,3,10,0,2,100,100,95,1

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

  return header + events.join("\n") + "\n";
}

// -------------------------------------------------------------
// 3. Stock Footage Acquisition (Pexels / Pixabay / Procedural)
// -------------------------------------------------------------
const usedClipIds = new Set();

async function searchStockClip(query, index) {
  const destPath = path.join(ASSETS_DIR, `scene-${String(index).padStart(2, "0")}.mp4`);

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
                `[Pexels] Found clip for "${query}" (ID: ${vid.id}, ${best.width}x${best.height})`
              );
              await downloadBinary(best.link, destPath);
              if (fs.existsSync(destPath) && fs.statSync(destPath).size > 10000) {
                return destPath;
              }
            }
          }
        }
      }
    } catch (err) {
      console.warn(`[Pexels] Search note: ${err.message}`);
    }
  }

  // Pixabay API
  if (PIXABAY_KEY) {
    try {
      const encQuery = encodeURIComponent(query.replace(/[^a-zA-Z0-9\s]/g, ""));
      const pixUrl = `https://pixabay.com/api/videos/?key=${PIXABAY_KEY}&q=${encQuery}&orientation=horizontal&per_page=10`;
      const res = await httpsGet(pixUrl);
      if (res && res.hits && res.hits.length > 0) {
        for (const hit of res.hits) {
          if (!usedClipIds.has(String(hit.id))) {
            const vidObj = hit.videos || {};
            const link =
              (vidObj.large && vidObj.large.url) ||
              (vidObj.medium && vidObj.medium.url) ||
              (vidObj.small && vidObj.small.url);
            if (link) {
              usedClipIds.add(String(hit.id));
              console.log(`[Pixabay] Found clip for "${query}" (ID: ${hit.id})`);
              await downloadBinary(link, destPath);
              if (fs.existsSync(destPath) && fs.statSync(destPath).size > 10000) {
                return destPath;
              }
            }
          }
        }
      }
    } catch (err) {
      console.warn(`[Pixabay] Search note: ${err.message}`);
    }
  }

  // High-Quality Procedural Cinematic Gradient Motion Background
  console.log(`[Visuals] Synthesizing cinematic motion backdrop for scene ${index + 1}: "${query}"`);
  const colors = [
    "#0b132b",
    "#1c2541",
    "#3a506b",
    "#0d1b2a",
    "#1b263b",
    "#415a77",
    "#10002b",
    "#240046",
    "#1b1b2f",
    "#1f4068",
    "#162447",
  ];
  const col = colors[index % colors.length];
  execSync(
    `ffmpeg -y -f lavfi -i "color=c=${col}:s=1920x1080:d=6,drawbox=x=0:y=0:w=1920:h=1080:color=white@0.03:t=fill" -c:v libx264 -preset ultrafast -pix_fmt yuv420p "${destPath}"`,
    { stdio: "ignore" }
  );
  return destPath;
}

// -------------------------------------------------------------
// 4. Audio Ducking (Reduce BGM to 15-20% gain during voiceover)
// -------------------------------------------------------------
async function mixAudioWithDucking(narrationMp3Path, targetDuration) {
  const mixedAudioPath = path.join(ASSETS_DIR, "mixed-audio.aac");
  console.log(
    "[Audio] Mixing Voiceover and Cinematic BGM with dynamic Audio Ducking (sidechaincompress)..."
  );

  // Synthesize harmonic ambient pad and duck it under voiceover
  // Voiceover triggers sidechain attenuation (threshold 0.07, ratio 5.5 down to ~18% gain, attack 40ms, release 350ms)
  const duckingCmd = `ffmpeg -y \
    -i "${narrationMp3Path}" \
    -f lavfi -i "aevalsrc=0.06*sin(2*PI*110*t)+0.04*sin(2*PI*164.81*t)+0.03*sin(2*PI*220*t)+0.02*sin(2*PI*329.63*t):d=${Math.ceil(targetDuration + 5)}:s=48000" \
    -filter_complex "\
      [0:a]aformat=channel_layouts=stereo:sample_rates=48000,asplit=2[v_sc][v_mix]; \
      [1:a]aformat=channel_layouts=stereo:sample_rates=48000,volume=0.28[v_bgm]; \
      [v_bgm][v_sc]sidechaincompress=threshold=0.07:ratio=5.5:attack=40:release=350[ducked_bgm]; \
      [ducked_bgm][v_mix]amix=inputs=2:duration=first:weights=1 1[aout]" \
    -map "[aout]" -c:a aac -b:a 192k "${mixedAudioPath}"`;

  try {
    execSync(duckingCmd, { stdio: "inherit" });
    console.log("[Audio] Successfully synthesized and ducked BGM audio track at:", mixedAudioPath);
  } catch (err) {
    console.warn(`[Audio] Ducking filter note: ${err.message}. Using voice audio.`);
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
      `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "${mp3Path}"`
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
      zoomType: i % 3 === 0 ? "zoom-in" : i % 3 === 1 ? "pan-lr" : "zoom-out",
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

  // Create compatible timeline.json for C++ native engine
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
    "utf-8"
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
