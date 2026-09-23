#!/usr/bin/env node
/**
 * Step 5: Drive Upload & Supabase Sync
 * - Authenticates to Google Drive via OAuth or Service Account
 * - Uploads master out.mp4 to Google Drive 'Videos' folder
 * - Obtains direct download URL and view URL
 * - Always updates Supabase database status (completed or failed)
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const crypto = require('crypto');

function env(name, fallback = '') {
  return (process.env[name] || '').trim() || fallback;
}

const VIDEO_PATH = path.resolve('out.mp4');
const PROMPT = env('PROMPT', 'Generated Video');
const VIDEO_ID = env('VIDEO_ID', 'video_' + Date.now());
const TARGET_FOLDER_ID = env('GDRIVE_MAIN_FOLDER_ID', '1JGjibA287ds3SFoT_Fl2z8cJ96eCDUFs');
const SUPABASE_URL = env('SUPABASE_URL').replace(/\/+$/, '');
const SUPABASE_SERVICE_ROLE_KEY = env('SUPABASE_SERVICE_ROLE_KEY');
const GOOGLE_CLIENT_ID = env('GOOGLE_CLIENT_ID');
const GOOGLE_CLIENT_SECRET = env('GOOGLE_CLIENT_SECRET');
const GOOGLE_REFRESH_TOKEN = env('GOOGLE_REFRESH_TOKEN');
const GDRIVE_CLIENT_EMAIL = env('GDRIVE_CLIENT_EMAIL');
const GDRIVE_PRIVATE_KEY = env('GDRIVE_PRIVATE_KEY').replace(/\\n/g, '\n');

async function request(urlStr, options = {}, data = null) {
  const url = new URL(urlStr);
  return new Promise((resolve, reject) => {
    const req = https.request(url, options, (res) => {
      let body = '';
      res.on('data', chunk => (body += chunk));
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve(JSON.parse(body));
          } catch {
            resolve(body);
          }
        } else {
          reject(new Error(`HTTP ${res.statusCode}: ${body}`));
        }
      });
    });
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

async function patchSupabase(fields) {
  const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(VIDEO_ID);
  if (!SUPABASE_URL || !SUPABASE_SERVICE_ROLE_KEY || !isUuid) {
    console.log(`[Supabase] Skipping update (UUID: ${isUuid}, URL: ${!!SUPABASE_URL})`);
    return;
  }
  try {
    const patchData = JSON.stringify({
      ...fields,
      updated_at: new Date().toISOString()
    });
    await request(`${SUPABASE_URL}/rest/v1/videos?id=eq.${VIDEO_ID}`, {
      method: 'PATCH',
      headers: {
        apikey: SUPABASE_SERVICE_ROLE_KEY,
        Authorization: `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
        'Content-Type': 'application/json',
        Prefer: 'return=minimal'
      }
    }, patchData);
    console.log(`[Supabase] Successfully patched video record ${VIDEO_ID}:`, fields);
  } catch (err) {
    console.warn(`[Supabase Error] ${err.message}`);
  }
}

async function getAccessToken() {
  if (GOOGLE_CLIENT_ID && GOOGLE_CLIENT_SECRET && GOOGLE_REFRESH_TOKEN) {
    console.log('[Auth] Authenticating via Google OAuth Refresh Token...');
    const params = new URLSearchParams({
      client_id: GOOGLE_CLIENT_ID,
      client_secret: GOOGLE_CLIENT_SECRET,
      refresh_token: GOOGLE_REFRESH_TOKEN,
      grant_type: 'refresh_token'
    });
    const res = await request('https://oauth2.googleapis.com/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    }, params.toString());
    if (res && res.access_token) return res.access_token;
  }

  if (GDRIVE_CLIENT_EMAIL && GDRIVE_PRIVATE_KEY) {
    console.log('[Auth] Authenticating via Google Service Account JWT...');
    const now = Math.floor(Date.now() / 1000);
    const header = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT' })).toString('base64url');
    const claimSet = Buffer.from(JSON.stringify({
      iss: GDRIVE_CLIENT_EMAIL,
      scope: 'https://www.googleapis.com/auth/drive',
      aud: 'https://oauth2.googleapis.com/token',
      exp: now + 3600,
      iat: now
    })).toString('base64url');

    const sign = crypto.createSign('RSA-SHA256');
    sign.update(`${header}.${claimSet}`);
    const signature = sign.sign(GDRIVE_PRIVATE_KEY, 'base64url');
    const jwt = `${header}.${claimSet}.${signature}`;

    const params = new URLSearchParams({
      grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
      assertion: jwt
    });
    const res = await request('https://oauth2.googleapis.com/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    }, params.toString());
    if (res && res.access_token) return res.access_token;
  }

  throw new Error('No valid Google Drive credentials provided (OAuth or Service Account).');
}

async function findOrCreateVideosFolder(accessToken, parentFolderId) {
  try {
    const q = encodeURIComponent(`mimeType='application/vnd.google-apps.folder' and name='Videos' and '${parentFolderId}' in parents and trashed=false`);
    const listRes = await request(`https://www.googleapis.com/drive/v3/files?q=${q}&supportsAllDrives=true&includeItemsFromAllDrives=true&fields=files(id,name)`, {
      headers: { Authorization: `Bearer ${accessToken}` }
    });
    if (listRes && listRes.files && listRes.files.length > 0) {
      console.log(`[Drive] Found existing 'Videos' folder: ${listRes.files[0].id}`);
      return listRes.files[0].id;
    }
  } catch (e) {
    console.warn(`[Drive] Folder lookup notice: ${e.message}`);
  }

  try {
    console.log(`[Drive] Creating 'Videos' folder inside parent: ${parentFolderId}`);
    const createRes = await request('https://www.googleapis.com/drive/v3/files?supportsAllDrives=true', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json'
      }
    }, JSON.stringify({
      name: 'Videos',
      mimeType: 'application/vnd.google-apps.folder',
      parents: [parentFolderId]
    }));
    return createRes.id;
  } catch (e) {
    console.warn(`[Drive] Folder creation fallback: ${e.message}`);
    return parentFolderId;
  }
}

async function uploadVideoToDrive() {
  if (!fs.existsSync(VIDEO_PATH)) {
    throw new Error(`Master video out.mp4 not found at ${VIDEO_PATH}`);
  }

  const fileSize = fs.statSync(VIDEO_PATH).size;
  if (fileSize < 50000) {
    throw new Error(`Master video out.mp4 is incomplete or corrupt (${fileSize} bytes).`);
  }

  console.log(`[Drive] Starting upload for ${VIDEO_PATH} (${(fileSize / (1024 * 1024)).toFixed(2)} MB)...`);
  const token = await getAccessToken();
  const folderId = await findOrCreateVideosFolder(token, TARGET_FOLDER_ID);

  const cleanTitle = PROMPT.replace(/[^a-zA-Z0-9_\-\s]/g, '').trim().substring(0, 50) || 'Hyper_Copilot_Video';
  const fileName = `${cleanTitle}_${Date.now()}.mp4`;

  console.log(`[Drive] Initiating multipart upload: ${fileName}`);
  const boundary = '-------314159265358979323846';
  const metadata = JSON.stringify({
    name: fileName,
    parents: [folderId]
  });

  const header = `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${metadata}\r\n--${boundary}\r\nContent-Type: video/mp4\r\n\r\n`;
  const footer = `\r\n--${boundary}--`;
  const totalLength = Buffer.byteLength(header) + fileSize + Buffer.byteLength(footer);

  return new Promise((resolve, reject) => {
    const uploadReq = https.request(new URL('https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true'), {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': `multipart/related; boundary=${boundary}`,
        'Content-Length': totalLength
      }
    }, (res) => {
      let body = '';
      res.on('data', chunk => (body += chunk));
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            const uploaded = JSON.parse(body);
            const downloadUrl = `https://drive.google.com/uc?export=download&id=${uploaded.id}`;
            const viewUrl = `https://drive.google.com/file/d/${uploaded.id}/view`;
            console.log(`[Drive] Upload complete! File ID: ${uploaded.id}`);
            console.log(`[Drive Download URL] ${downloadUrl}`);
            console.log(`[Drive View URL] ${viewUrl}`);
            resolve({ id: uploaded.id, downloadUrl, viewUrl });
          } catch {
            reject(new Error(`Invalid JSON response: ${body}`));
          }
        } else {
          reject(new Error(`Drive upload failed: HTTP ${res.statusCode} ${body}`));
        }
      });
    });

    uploadReq.on('error', reject);
    uploadReq.write(header);
    const stream = fs.createReadStream(VIDEO_PATH);
    stream.pipe(uploadReq, { end: false });
    stream.on('end', () => {
      uploadReq.end(footer);
    });
  });
}

async function main() {
  console.log('====================================================');
  console.log('STEP 5: Drive Upload & Supabase Sync');
  console.log('====================================================');

  const videoExists = fs.existsSync(VIDEO_PATH) && fs.statSync(VIDEO_PATH).size > 50000;

  if (!videoExists) {
    console.error('[Step 5] Rendered video out.mp4 not found or empty.');
    await patchSupabase({
      status: 'failed',
      error: 'Video rendering failed or out.mp4 was not produced. Check GitHub Actions logs.',
      progress: 0,
      step: 'Failed'
    });
    process.exit(1);
  }

  try {
    const uploadResult = await uploadVideoToDrive();
    await patchSupabase({
      status: 'completed',
      video_url: uploadResult.downloadUrl,
      progress: 100,
      step: 'Finished'
    });
    console.log('Step 5: Drive upload and Supabase sync successfully completed.');
  } catch (err) {
    console.error(`[Step 5 Upload Error] ${err.message}`);
    await patchSupabase({
      status: 'failed',
      error: `Drive export failed: ${err.message}`,
      progress: 0,
      step: 'Upload Failed'
    });
    process.exit(1);
  }
}

if (require.main === module) {
  main().catch((err) => {
    console.error(`Fatal Step 5 Error: ${err.message}`);
    process.exit(1);
  });
}

module.exports = {
  main,
  uploadVideoToDrive
};
