#!/usr/bin/env node

/**
 * Native Google Drive Exporter (Zero Python)
 * Supports User OAuth Refresh Token and Service Account credentials.
 * Uploads master video directly to the 'Videos' folder in Google Drive.
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
let GDRIVE_PRIVATE_KEY = env('GDRIVE_PRIVATE_KEY').replace(/\\n/g, '\n');

async function request(urlStr, options = {}, data = null) {
  const url = new URL(urlStr);
  return new Promise((resolve, reject) => {
    const req = https.request(url, options, (res) => {
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
    if (data) req.write(data);
    req.end();
  });
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
    if (res.access_token) return res.access_token;
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
    if (res.access_token) return res.access_token;
  }

  throw new Error('No valid Google Drive credentials provided (OAuth or Service Account).');
}

async function findOrCreateVideosFolder(accessToken, parentFolderId) {
  try {
    const q = encodeURIComponent(`mimeType='application/vnd.google-apps.folder' and name='Videos' and '${parentFolderId}' in parents and trashed=false`);
    const listRes = await request(`https://www.googleapis.com/drive/v3/files?q=${q}&supportsAllDrives=true&includeItemsFromAllDrives=true&fields=files(id,name)`, {
      headers: { 'Authorization': `Bearer ${accessToken}` }
    });
    if (listRes.files && listRes.files.length > 0) {
      console.log(`[Drive] Found existing 'Videos' folder: ${listRes.files[0].id}`);
      return listRes.files[0].id;
    }
  } catch (e) {
    console.warn(`[Drive] Folder lookup notice: ${e.message}`);
  }

  try {
    console.log(`[Drive] Creating 'Videos' subfolder inside parent: ${parentFolderId}`);
    const createRes = await request('https://www.googleapis.com/drive/v3/files?supportsAllDrives=true', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json'
      }
    }, JSON.stringify({
      name: 'Videos',
      mimeType: 'application/vnd.google-apps.folder',
      parents: [parentFolderId]
    }));
    return createRes.id;
  } catch (e) {
    console.warn(`[Drive] Folder creation notice: ${e.message}. Using root parent.`);
    return parentFolderId;
  }
}

async function uploadVideo() {
  if (!fs.existsSync(VIDEO_PATH)) {
    console.log('[Export] No video file found at out.mp4 to upload.');
    return;
  }

  const fileSize = fs.statSync(VIDEO_PATH).size;
  console.log(`[Export] Starting upload for ${VIDEO_PATH} (${(fileSize / (1024 * 1024)).toFixed(2)} MB)...`);

  const token = await getAccessToken();
  const folderId = await findOrCreateVideosFolder(token, TARGET_FOLDER_ID);

  const cleanTitle = PROMPT.replace(/[^a-zA-Z0-9_\-\s]/g, '').trim().substring(0, 50) || 'Hyper_Copilot_Video';
  const fileName = `${cleanTitle}_${Date.now()}.mp4`;

  console.log(`[Drive] Initiating resumable multipart upload for: ${fileName}`);
  const boundary = '-------314159265358979323846';
  const metadata = JSON.stringify({
    name: fileName,
    parents: [folderId]
  });

  const header = `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${metadata}\r\n--${boundary}\r\nContent-Type: video/mp4\r\n\r\n`;
  const footer = `\r\n--${boundary}--`;

  const totalLength = Buffer.byteLength(header) + fileSize + Buffer.byteLength(footer);

  const uploadReq = https.request(new URL('https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true'), {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': `multipart/related; boundary=${boundary}`,
      'Content-Length': totalLength
    }
  }, (res) => {
    let body = '';
    res.on('data', chunk => body += chunk);
    res.on('end', () => {
      if (res.statusCode >= 200 && res.statusCode < 300) {
        try {
          const uploaded = JSON.parse(body);
          console.log(`[Drive Upload Success] File ID: ${uploaded.id}`);
          const directDownloadUrl = `https://drive.google.com/uc?export=download&id=${uploaded.id}`;
          const viewUrl = `https://drive.google.com/file/d/${uploaded.id}/view`;
          console.log(`[Drive Download URL] ${directDownloadUrl}`);
          console.log(`[Drive View URL] ${viewUrl}`);

          if (SUPABASE_URL && SUPABASE_SERVICE_ROLE_KEY && VIDEO_ID) {
            try {
              const patchData = JSON.stringify({
                video_url: directDownloadUrl,
                status: 'completed',
                progress: 100,
                step: 'Finished',
                updated_at: new Date().toISOString()
              });
              await request(`${SUPABASE_URL}/rest/v1/videos?id=eq.${VIDEO_ID}`, {
                method: 'PATCH',
                headers: {
                  'apikey': SUPABASE_SERVICE_ROLE_KEY,
                  'Authorization': `Bearer ${SUPABASE_SERVICE_ROLE_KEY}`,
                  'Content-Type': 'application/json',
                  'Prefer': 'return=minimal'
                }
              }, patchData);
              console.log(`[Supabase] Recorded video_url and completed status for video: ${VIDEO_ID}`);
            } catch (syncErr) {
              console.warn(`[Supabase] Metadata sync notice: ${syncErr.message}`);
            }
          }
        } catch (e) {
          console.log(`[Drive Upload Complete] Response: ${body}`);
        }
      } else {
        console.error(`[Drive Upload Failed] HTTP ${res.statusCode}: ${body}`);
      }
    });
  });

  uploadReq.on('error', (err) => {
    console.error(`[Drive Upload Error] ${err.message}`);
  });

  uploadReq.write(header);
  const stream = fs.createReadStream(VIDEO_PATH);
  stream.pipe(uploadReq, { end: false });
  stream.on('end', () => {
    uploadReq.end(footer);
  });
}

uploadVideo().catch(err => {
  console.error(`Fatal Export Error: ${err.message}`);
});
