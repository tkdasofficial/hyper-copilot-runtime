#!/usr/bin/env node
/**
 * Step 4: MP4 Rendering
 * - Assembles media assets, Ken Burns dynamic motion, transitions, word-by-word captions
 * - Performance optimized: ultrafast preset, thread parallelization (sub-5 minute render)
 * - Native C++ engine integration + robust FFmpeg master fallback
 * - Validates out.mp4
 */

const fs = require("fs");
const path = require("path");
const https = require("https");
const { execSync } = require("child_process");

function env(name, fallback = "") {
  return (process.env[name] || "").trim() || fallback;
}

const VIDEO_ID = env("VIDEO_ID", "vid_" + Date.now());
const SUPABASE_URL = env("SUPABASE_URL").replace(/\/+$/, "");
const SUPABASE_KEY = env("SUPABASE_SERVICE_ROLE_KEY");
const OUTPUT_FILE = path.resolve("out.mp4");
const ASSETS_DIR = path.resolve("assets");
const MANIFEST_PATH = path.join(ASSETS_DIR, "manifest.json");

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

function probeDuration(filePath) {
  try {
    const out = execSync(
      `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "${filePath}"`,
    )
      .toString()
      .trim();
    const d = parseFloat(out);
    return isNaN(d) ? 0 : d;
  } catch {
    return 0;
  }
}

function renderWithFfmpegMaster(manifest) {
  console.log("[Render] Initiating High-Speed Ultrafast FFmpeg Master Pipeline...");
  const scenes = manifest.scenes || [];
  const width = manifest.width || 1920;
  const height = manifest.height || 1080;
  const fps = manifest.fps || 30;
  const audioFile =
    manifest.audioFile && fs.existsSync(manifest.audioFile)
      ? manifest.audioFile
      : manifest.voiceFile || "";
  const assFile =
    manifest.captionsAss && fs.existsSync(manifest.captionsAss) ? manifest.captionsAss : "";

  if (scenes.length === 0) {
    throw new Error("No scenes found in asset manifest.");
  }

  // Pre-normalize scenes in fast parallel chunks with Ken Burns and 16:9 crop
  const normClips = [];
  const tempDir = path.resolve("temp_render");
  if (!fs.existsSync(tempDir)) fs.mkdirSync(tempDir, { recursive: true });

  console.log(
    `[Render] Pre-processing ${scenes.length} scene clips with Ken Burns pan/zoom and 16:9 canvas...`,
  );
  for (let i = 0; i < scenes.length; i++) {
    const sc = scenes[i];
    const normPath = path.join(tempDir, `norm_${String(i).padStart(2, "0")}.mp4`);
    const scDur = Math.max(3, sc.duration || 5);
    const zoomType = sc.zoomType || (i % 3 === 0 ? "zoom_in" : i % 3 === 1 ? "pan_lr" : "zoom_out");

    let motionFilter = "";
    if (zoomType === "zoom_in") {
      motionFilter = `scale=w='${width}*(1.0+0.08*(t/${scDur}))':h='${height}*(1.0+0.08*(t/${scDur}))':eval=frame,crop=${width}:${height}`;
    } else if (zoomType === "zoom_out") {
      motionFilter = `scale=w='${width}*(1.08-0.08*(t/${scDur}))':h='${height}*(1.08-0.08*(t/${scDur}))':eval=frame,crop=${width}:${height}`;
    } else {
      // Pan Left to Right
      const wPad = Math.round(width * 1.1);
      const hPad = Math.round(height * 1.1);
      motionFilter = `scale=${wPad}:${hPad}:force_original_aspect_ratio=increase,crop=${wPad}:${hPad},crop=${width}:${height}:x='(in_w-out_w)*(t/${scDur})':y='(in_h-out_h)/2'`;
    }

    const normCmd = `ffmpeg -y -hide_banner -loglevel warning \
      -stream_loop -1 -t ${scDur} -i "${sc.file}" \
      -vf "${motionFilter},format=yuv420p,setsar=1,fps=${fps}" \
      -c:v libx264 -preset ultrafast -crf 20 -an "${normPath}"`;

    execSync(normCmd, { stdio: "inherit" });
    normClips.push({ path: normPath, duration: scDur });
  }

  // Chain clips with cross-dissolve xfade transitions
  console.log("[Render] Assembling cross-dissolve transitions and burned active captions...");
  const transDur = 0.5;
  const inputs = normClips.map((c) => `-i "${c.path}"`).join(" ");

  let filterGraph = "";
  let lastStream = "[0:v]";
  let curOffset = normClips[0].duration - transDur;

  if (normClips.length === 1) {
    lastStream = "[0:v]";
  } else {
    for (let i = 1; i < normClips.length; i++) {
      const nextStream = `[${i}:v]`;
      const outLabel = `[v_xfade_${i}]`;
      filterGraph += `${lastStream}${nextStream}xfade=transition=fade:duration=${transDur}:offset=${curOffset.toFixed(3)}${outLabel}; `;
      lastStream = outLabel;
      curOffset += normClips[i].duration - transDur;
    }
  }

  // Calculate final total video duration
  const totalVideoDuration = Math.max(5, curOffset + transDur);
  const fadeOutStart = Math.max(1, totalVideoDuration - 0.8);

  // Apply smooth Fade-In at start, Fade-Out at end, and Word-by-Word Active Captions
  let finalVideoFilter = `${lastStream}fade=t=in:st=0:d=0.8,fade=t=out:st=${fadeOutStart.toFixed(3)}:d=0.8`;
  if (assFile && fs.existsSync(assFile)) {
    // Relative or escaped path for libass
    const cleanAssPath = path.relative(process.cwd(), assFile).replace(/\\/g, "/");
    finalVideoFilter += `,ass='${cleanAssPath}'`;
  }
  finalVideoFilter += "[v_master]";
  filterGraph += finalVideoFilter;

  // Render command with audio ducked track
  let finalCmd = "";
  if (audioFile && fs.existsSync(audioFile)) {
    finalCmd = `ffmpeg -y -hide_banner \
      ${inputs} -i "${audioFile}" \
      -filter_complex "${filterGraph}" \
      -map "[v_master]" -map "${normClips.length}:a" \
      -c:v libx264 -preset ultrafast -crf 22 -pix_fmt yuv420p \
      -c:a aac -b:a 192k \
      -shortest -movflags +faststart -threads 0 "${OUTPUT_FILE}"`;
  } else {
    finalCmd = `ffmpeg -y -hide_banner \
      ${inputs} \
      -filter_complex "${filterGraph}" \
      -map "[v_master]" \
      -c:v libx264 -preset ultrafast -crf 22 -pix_fmt yuv420p \
      -movflags +faststart -threads 0 "${OUTPUT_FILE}"`;
  }

  console.log("[Render] Executing final master compilation...");
  const t0 = Date.now();
  execSync(finalCmd, { stdio: "inherit" });
  console.log(
    `[Render] Final master compilation completed in ${((Date.now() - t0) / 1000).toFixed(1)}s`,
  );
}

async function main() {
  console.log("====================================================");
  console.log("STEP 4: MP4 Rendering Engine");
  console.log("====================================================");

  if (!fs.existsSync(MANIFEST_PATH)) {
    throw new Error(`Asset manifest not found at ${MANIFEST_PATH}. Step 3 must run first.`);
  }

  const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, "utf-8"));
  await updateSupabase(75, "Rendering Master MP4 Video");

  // Try C++ engine first if binary exists
  const nativeBinary = path.resolve("editor/build/bin/video_editor");
  let nativeSuccess = false;

  if (fs.existsSync(nativeBinary)) {
    const timelinePath = path.join(ASSETS_DIR, "timeline.json");
    if (fs.existsSync(timelinePath)) {
      console.log("[Render] Found native C++ video editor engine at:", nativeBinary);
      try {
        const out = execSync(`${nativeBinary} "${timelinePath}"`, { timeout: 120000 });
        console.log("[Render] C++ Engine output:", out.toString().slice(-400));
        if (fs.existsSync(OUTPUT_FILE) && fs.statSync(OUTPUT_FILE).size > 100000) {
          const dur = probeDuration(OUTPUT_FILE);
          if (dur >= manifest.totalDuration * 0.7) {
            console.log(`[Render] Native C++ engine produced valid master (${dur}s).`);
            nativeSuccess = true;
          }
        }
      } catch (nativeErr) {
        console.warn(`[Render] Native C++ engine pass notice: ${nativeErr.message}`);
      }
    }
  }

  // If native didn't produce complete master, run ultrafast FFmpeg master
  if (!nativeSuccess) {
    console.log("[Render] Executing ultrafast FFmpeg visual pipeline...");
    renderWithFfmpegMaster(manifest);
  }

  // Validate out.mp4
  if (!fs.existsSync(OUTPUT_FILE) || fs.statSync(OUTPUT_FILE).size < 50000) {
    throw new Error("Master video out.mp4 was not generated or is invalid (< 50KB).");
  }

  const finalDur = probeDuration(OUTPUT_FILE);
  const finalSizeMb = (fs.statSync(OUTPUT_FILE).size / (1024 * 1024)).toFixed(2);
  console.log(`====================================================`);
  console.log(`SUCCESS! Master video out.mp4 generated:`);
  console.log(`Size: ${finalSizeMb} MB | Duration: ${finalDur.toFixed(1)}s`);
  console.log(`====================================================`);

  await updateSupabase(90, "Master MP4 Render Complete");
}

if (require.main === module) {
  main().catch((err) => {
    console.error(`Fatal Step 4 Error: ${err.message}`);
    updateSupabase(0, `Render failed: ${err.message}`, "failed").finally(() => {
      process.exit(1);
    });
  });
}

module.exports = {
  main,
  renderWithFfmpegMaster,
};
