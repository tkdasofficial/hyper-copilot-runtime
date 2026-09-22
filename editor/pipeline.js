#!/usr/bin/env node

/**
 * Native Video Pipeline Orchestrator (Zero Python)
 * Bridges AI screenplay generation, stock footage acquisition, TTS narration,
 * and passes the rendered timeline into the Native C++ Engine (hyper_editor) / FFmpeg.
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');
const { execSync, spawn } = require('child_process');

function env(name, fallback = '') {
  return (process.env[name] || '').trim() || fallback;
}

const SUPABASE_URL = env('SUPABASE_URL').replace(/\/+$/, '');
const SUPABASE_SERVICE_ROLE_KEY = env('SUPABASE_SERVICE_ROLE_KEY');
const VIDEO_ID = env('VIDEO_ID', 'video_' + Date.now());
const USER_ID = env('USER_ID', 'github_actions');

const PROMPT = env('PROMPT', 'Epic journey through neon cyberpunk megacity');
const NEGATIVE_PROMPT = env('NEGATIVE_PROMPT', 'blurry, distorted, low quality, glitch, watermark');
const VOICE_GENDER = (env('VOICE_GENDER') || 'female').toLowerCase();
const VOICE_PERSONA = env('VOICE_PERSONA') || 'Dynamic Storyteller';
const VIDEO_STYLE = env('VIDEO_STYLE') || env('IMAGE_STYLE') || 'Cinematic';
const PIPELINE_MODE = (env('PIPELINE_MODE') || 'short').toLowerCase();
const TARGET_RATIO = env('TARGET_RATIO') || (PIPELINE_MODE === 'short' ? '9:16' : '16:9');
const RENDER_FPS = parseInt(env('RENDER_FPS') || '30', 10);

const PEXELS_API_KEY = env('PEXELS_API_KEY');
const PIXABAY_API_KEY = env('PIXABAY_API_KEY');
const NVIDIA_API_KEY = env('NVIDIA_API_KEY');
const CLOUDFLARE_ACCOUNT_ID = env('CLOUDFLARE_ACCOUNT_ID');
const CLOUDFLARE_API_TOKEN = env('CLOUDFLARE_API_TOKEN');

const IS_VERTICAL = TARGET_RATIO.includes('9:16') || TARGET_RATIO.includes('vertical');
const WIDTH = IS_VERTICAL ? 1080 : 1920;
const HEIGHT = IS_VERTICAL ? 1920 : 1080;

const DURATION_SECONDS = Math.max(10, Math.min(1800, parseInt(env('DURATION_SECONDS') || (PIPELINE_MODE === 'short' ? '15' : '180'), 10)));

const WORKDIR = path.resolve('assets');
if (!fs.existsSync(WORKDIR)) fs.mkdirSync(WORKDIR, { recursive: true });

async function updateSupabase(progress, step, status = 'processing') {
  console.log(`[Progress ${progress}%] [${step}]`);
  if (!SUPABASE_URL || !SUPABASE_SERVICE_ROLE_KEY || !VIDEO_ID) return;
  try {
    const url = new URL(`${SUPABASE_URL}/rest/v1/videos?id=eq.${VIDEO_ID}`);
    const data = JSON.stringify({ progress, step, status, updated_at: new Date().toISOString() });
    
    await fetch(url.toString(), {
      method: 'PATCH',
      headers: {
        'apikey': SUPABASE_SERVICE_ROLE_KEY,
        'Authorization': `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal'
      },
      body: data
    });
  } catch (err) {
    console.warn(`Supabase status sync error: ${err.message}`);
  }
}

async function requestJson(urlStr, options = {}) {
  const url = new URL(urlStr);
  const client = url.protocol === 'https:' ? https : http;
  
  return new Promise((resolve, reject) => {
    const req = client.request(url, options, (res) => {
      let body = '';
      res.on('data', chunk => body += chunk);
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve(JSON.parse(body));
          } catch (e) {
            resolve(body);
          }
        } else {
          reject(new Error(`HTTP ${res.statusCode}: ${body}`));
        }
      });
    });
    req.on('error', reject);
    if (options.body) req.write(options.body);
    req.end();
  });
}

async function downloadFile(urlStr, destPath) {
  const file = fs.createWriteStream(destPath);
  return new Promise((resolve, reject) => {
    https.get(urlStr, (res) => {
      if (res.statusCode === 301 || res.statusCode === 302) {
        return downloadFile(res.headers.location, destPath).then(resolve).catch(reject);
      }
      res.pipe(file);
      file.on('finish', () => file.close(resolve));
    }).on('error', (err) => {
      fs.unlink(destPath, () => {});
      reject(err);
    });
  });
}

function cleanScriptToWords(text) {
  return text.replace(/[^\w\s]/g, '').trim().split(/\s+/).filter(Boolean);
}

function generateScriptStoryboard(prompt, duration) {
  const sceneCount = Math.max(2, Math.min(12, Math.round(duration / 5)));
  const sceneDuration = duration / sceneCount;
  
  const keywords = prompt.toLowerCase()
    .replace(/[^\w\s]/g, '')
    .split(/\s+/)
    .filter(w => !['the','and','a','in','of','to','is','for','with','on','at'].includes(w));
  
  const scenes = [];
  for (let i = 0; i < sceneCount; ++i) {
    const q1 = keywords[i % keywords.length] || 'cinematic scenery';
    const q2 = keywords[(i + 1) % keywords.length] || 'dramatic background';
    scenes.push({
      index: i,
      duration: sceneDuration,
      query: `${q1} ${q2}`,
      fallbackQuery: q1,
      narration: `Visualizing ${prompt}, scene ${i + 1} with high fidelity cinematic detail.`
    });
  }
  return scenes;
}

const USED_CLIP_IDS = new Set();

async function searchStockClip(query) {
  if (PEXELS_API_KEY) {
    try {
      const pexelsUrl = `https://api.pexels.com/videos/search?query=${encodeURIComponent(query)}&per_page=10&orientation=${IS_VERTICAL ? 'portrait' : 'landscape'}`;
      const data = await requestJson(pexelsUrl, {
        headers: { 'Authorization': PEXELS_API_KEY }
      });
      if (data && data.videos && data.videos.length > 0) {
        for (const v of data.videos) {
          const id = `pexels_${v.id}`;
          if (!USED_CLIP_IDS.has(id)) {
            USED_CLIP_IDS.add(id);
            const files = (v.video_files || []).filter(f => f.file_type === 'video/mp4');
            files.sort((a, b) => (b.width * b.height) - (a.width * a.height));
            if (files[0] && files[0].link) {
              return { url: files[0].link, duration: v.duration || 5 };
            }
          }
        }
      }
    } catch (e) {
      console.warn(`Pexels fetch notice: ${e.message}`);
    }
  }

  if (PIXABAY_API_KEY) {
    try {
      const pixabayUrl = `https://pixabay.com/api/videos/?key=${PIXABAY_API_KEY}&q=${encodeURIComponent(query)}&per_page=10`;
      const data = await requestJson(pixabayUrl);
      if (data && data.hits && data.hits.length > 0) {
        for (const h of data.hits) {
          const id = `pixabay_${h.id}`;
          if (!USED_CLIP_IDS.has(id)) {
            USED_CLIP_IDS.add(id);
            const vids = h.videos || {};
            const chosen = vids.large || vids.medium || vids.small;
            if (chosen && chosen.url) {
              return { url: chosen.url, duration: h.duration || 5 };
            }
          }
        }
      }
    } catch (e) {
      console.warn(`Pixabay fetch notice: ${e.message}`);
    }
  }

  return null;
}

async function synthesizeNarration(text, destAudioPath) {
  const audioDir = path.dirname(destAudioPath);
  if (!fs.existsSync(audioDir)) {
    fs.mkdirSync(audioDir, { recursive: true });
  }

  const voice = VOICE_GENDER === 'female' ? 'en-US-AriaNeural' : 'en-US-GuyNeural';
  const scriptPath = path.join(audioDir, 'narration_script.txt');
  fs.writeFileSync(scriptPath, text, 'utf-8');

  // Try edge-tts CLI tool if available
  try {
    execSync(`edge-tts --voice "${voice}" -f "${scriptPath}" --write-media "${destAudioPath}"`, { stdio: 'ignore' });
    if (fs.existsSync(destAudioPath) && fs.statSync(destAudioPath).size > 1000) {
      console.log(`[TTS] Edge-TTS synthesized narration successfully (${fs.statSync(destAudioPath).size} bytes).`);
      return true;
    }
  } catch (err) {
    console.warn(`[TTS] Edge-TTS notice: ${err.message}`);
  }

  // Fallback: procedural audio tone correctly encoded for MP3 container
  console.warn(`[TTS] Creating procedural audio tone for MP3...`);
  const duration = Math.max(3, DURATION_SECONDS);
  try {
    execSync(`ffmpeg -y -f lavfi -i "sine=frequency=440:duration=${duration}" -c:a libmp3lame -b:a 128k "${destAudioPath}"`, { stdio: 'ignore' });
    return false;
  } catch (toneErr) {
    console.warn(`[TTS] Procedural tone retry without explicit codec...`);
    execSync(`ffmpeg -y -f lavfi -i "sine=frequency=440:duration=${duration}" "${destAudioPath}"`, { stdio: 'ignore' });
    return false;
  }
}

function writeSubtitlesAss(scenes, assPath) {
  const fontSize = IS_VERTICAL ? 64 : 38;
  const marginV = IS_VERTICAL ? Math.round(HEIGHT * 0.18) : Math.round(HEIGHT * 0.08);

  let assContent = `[Script Info]
Title: Hyper Copilot Dynamic Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: ${WIDTH}
PlayResY: ${HEIGHT}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,${fontSize},&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,2,2,30,30,${marginV},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n`;

  let curTime = 0.0;
  for (const scene of scenes) {
    const startStr = formatTimestamp(curTime);
    const endStr = formatTimestamp(curTime + scene.duration);
    assContent += `Dialogue: 0,${startStr},${endStr},Default,,0,0,0,,{\\b1}{\\c&H0000E6FF&}${scene.narration}{\\b0}\n`;
    curTime += scene.duration;
  }

  fs.writeFileSync(assPath, assContent, 'utf-8');
}

function formatTimestamp(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const cs = Math.floor((seconds % 1) * 100);
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(cs).padStart(2, '0')}`;
}

async function run() {
  console.log(`=== Hyper Copilot Native Pipeline (Zero-Python / C++ Engine) ===`);
  console.log(`Mode: ${PIPELINE_MODE}, Duration: ${DURATION_SECONDS}s, Ratio: ${TARGET_RATIO} (${WIDTH}x${HEIGHT})`);

  await updateSupabase(10, 'Writing screenplay & scene storyboard');
  const scenes = generateScriptStoryboard(PROMPT, DURATION_SECONDS);
  const fullNarration = scenes.map(s => s.narration).join(' ');

  await updateSupabase(25, 'Synthesizing voiceover narration');
  const audioPath = path.join(WORKDIR, 'narration.mp3');
  await synthesizeNarration(fullNarration, audioPath);

  await updateSupabase(40, 'Acquiring stock footage clips');
  const clips = [];
  for (let i = 0; i < scenes.length; ++i) {
    const sc = scenes[i];
    const clipDest = path.join(WORKDIR, `clip_${i}.mp4`);
    const fetched = await searchStockClip(sc.query);
    if (fetched) {
      console.log(`Downloading stock video for scene ${i + 1}...`);
      await downloadFile(fetched.url, clipDest);
      clips.push({ file: clipDest, duration: sc.duration });
    } else {
      console.log(`Generating visual procedural plate for scene ${i + 1}...`);
      const safePlateText = (sc.query || 'Scene ' + (i + 1)).replace(/[^a-zA-Z0-9_\-\s]/g, ' ').substring(0, 50);
      try {
        execSync(`ffmpeg -y -f lavfi -i "color=c=0x0d1527:s=${WIDTH}x${HEIGHT}:d=${sc.duration}:r=${RENDER_FPS}" -vf "drawtext=text='${safePlateText}':fontsize=48:fontcolor=white@0.3:x=(w-text_w)/2:y=(h-text_h)/2" -c:v libx264 -preset ultrafast -pix_fmt yuv420p "${clipDest}"`, { stdio: 'ignore' });
      } catch (vfErr) {
        execSync(`ffmpeg -y -f lavfi -i "color=c=0x0d1527:s=${WIDTH}x${HEIGHT}:d=${sc.duration}:r=${RENDER_FPS}" -c:v libx264 -preset ultrafast -pix_fmt yuv420p "${clipDest}"`, { stdio: 'ignore' });
      }
      clips.push({ file: clipDest, duration: sc.duration });
    }
  }

  const assPath = path.join(WORKDIR, 'captions.ass');
  writeSubtitlesAss(scenes, assPath);

  // Check C++ native engine compilation
  await updateSupabase(65, 'Building timeline for C++ Native Engine / FFmpeg');
  const timelineSpec = {
    resolution: { width: WIDTH, height: HEIGHT },
    fps: RENDER_FPS,
    duration: DURATION_SECONDS,
    outputPath: path.resolve('out.mp4'),
    tracks: [
      {
        type: 'video',
        clips: clips.map((c, idx) => ({
          path: c.file,
          duration: c.duration,
          startTime: idx * (DURATION_SECONDS / clips.length)
        }))
      },
      {
        type: 'audio',
        clips: [{ path: audioPath, startTime: 0, duration: DURATION_SECONDS }]
      }
    ]
  };

  const timelineJsonPath = path.join(WORKDIR, 'timeline.json');
  fs.writeFileSync(timelineJsonPath, JSON.stringify(timelineSpec, null, 2), 'utf-8');

  // Attempt C++ native engine rendering if compiled
  const cppEngineBin = path.resolve('editor/build/hyper_editor');
  let renderedByCpp = false;
  if (fs.existsSync(cppEngineBin)) {
    try {
      console.log(`[C++ Native Engine] Executing ${cppEngineBin} with ${timelineJsonPath}...`);
      await updateSupabase(75, 'Executing C++ Native Engine Renderer');
      execSync(`"${cppEngineBin}" --timeline "${timelineJsonPath}" -o out.mp4`, { stdio: 'inherit' });
      if (fs.existsSync('out.mp4') && fs.statSync('out.mp4').size > 1000) {
        renderedByCpp = true;
      }
    } catch (e) {
      console.warn(`[C++ Native Engine] Run note: ${e.message}`);
    }
  }

  if (!renderedByCpp) {
    console.log(`[FFmpeg Native Engine] Compiling multi-scene master video with burned subtitles...`);
    await updateSupabase(80, 'Compiling master video render');

    const fcParts = [];
    for (let i = 0; i < clips.length; ++i) {
      fcParts.push(
        `[${i}:v]trim=start=0:duration=${clips[i].duration},setpts=PTS-STARTPTS,` +
        `scale=${WIDTH}:${HEIGHT}:force_original_aspect_ratio=increase,` +
        `crop=${WIDTH}:${HEIGHT},setsar=1,fps=${RENDER_FPS},format=yuv420p[v${i}];`
      );
    }

    let curr = '[v0]';
    if (clips.length > 1) {
      let accum = clips[0].duration;
      for (let i = 1; i < clips.length; ++i) {
        const td = 0.4;
        const offset = Math.max(0.1, accum - td);
        const nxt = `[vx${i}]`;
        fcParts.push(`${curr}[v${i}]xfade=transition=fade:duration=${td.toFixed(2)}:offset=${offset.toFixed(2)}${nxt};`);
        curr = nxt;
        accum = offset + clips[i].duration;
      }
    }

    const escapedAss = assPath.replace(/\\/g, '/').replace(/:/g, '\\:').replace(/'/g, "\\'");
    fcParts.push(`${curr}ass='${escapedAss}'[vout]`);

    const ffmpegArgs = ['-y'];
    for (const c of clips) ffmpegArgs.push('-i', c.file);
    ffmpegArgs.push('-i', audioPath);
    ffmpegArgs.push(
      '-filter_complex', fcParts.join(''),
      '-map', '[vout]',
      '-map', `${clips.length}:a:0`,
      '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
      '-c:a', 'aac', '-b:a', '192k',
      '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
      '-shortest', 'out.mp4'
    );

    execSync(`ffmpeg ${ffmpegArgs.join(' ')}`, { stdio: 'inherit' });
  }

  if (fs.existsSync('out.mp4') && fs.statSync('out.mp4').size > 1000) {
    console.log(`[Success] Video generated at out.mp4 (${fs.statSync('out.mp4').size} bytes)`);
    await updateSupabase(95, 'Video rendering complete');
  } else {
    throw new Error('Output video file out.mp4 was not generated.');
  }
}

run().catch(async (err) => {
  console.error(`Fatal Pipeline Error: ${err.message}`);
  await updateSupabase(0, `Render failed: ${err.message}`, 'failed');
  process.exit(1);
});
