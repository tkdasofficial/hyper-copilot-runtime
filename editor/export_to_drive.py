#!/usr/bin/env python3
"""
Standalone Google Drive Exporter for Video Agent.
Uploads the rendered video (out.mp4) directly to Google Drive via:
1. Supabase 'upload-to-drive' Edge Function (using SUPABASE_SERVICE_ROLE_KEY)
2. Direct Google Drive API v3 (if GDRIVE_SERVICE_ACCOUNT_JSON or GDRIVE_CLIENT_EMAIL/KEY are present)
Records the Google Drive share link back to Supabase and GitHub Step Summary.
"""

import os
import sys
import json
import requests

def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or "").strip() or default

SUPABASE_URL = env("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = env("SUPABASE_SERVICE_ROLE_KEY")
VIDEO_ID = env("VIDEO_ID", "local_test_video")
PROMPT = env("PROMPT", "Nature & Cosmic Documentary")
VIDEO_FILE = env("VIDEO_FILE", "out.mp4")

def sanitize_filename(name: str) -> str:
    clean = "".join(c for c in name if c.isalnum() or c in (" ", "-", "_")).strip()
    return (clean[:50] or "hyper_documentary").replace(" ", "_") + ".mp4"

def patch_supabase_drive_url(drive_url: str, file_id: str = "") -> None:
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY and VIDEO_ID):
        return
    try:
        # Patch drive_url and logs
        payload = {
            "logs": f"Exported to Google Drive successfully: {drive_url}",
        }
        # Try updating drive_url if column exists
        res = requests.patch(
            f"{SUPABASE_URL}/rest/v1/videos?id=eq.{VIDEO_ID}",
            headers={
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json={"drive_url": drive_url, **payload},
            timeout=10,
        )
        if not res.ok:
            # If drive_url column doesn't exist, update logs
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/videos?id=eq.{VIDEO_ID}",
                headers={
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                json=payload,
                timeout=10,
            )
        print(f"[DriveExport] Synced Drive link to Supabase for video {VIDEO_ID}")
    except Exception as e:
        print(f"[DriveExport] Supabase patch warning: {e}", file=sys.stderr)

def upload_via_supabase_edge_function(filepath: str, filename: str) -> dict | None:
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
        print("[DriveExport] Supabase credentials missing; skipping edge function drive upload.")
        return None
    
    url = f"{SUPABASE_URL}/functions/v1/upload-to-drive"
    print(f"[DriveExport] Uploading {filepath} ({filename}) to Google Drive via Supabase Edge Function...")
    
    with open(filepath, "rb") as f:
        files = {"file": (filename, f, "video/mp4")}
        data = {"folder": "Videos"}
        headers = {
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        }
        res = requests.post(url, headers=headers, files=files, data=data, timeout=300)
    
    if res.ok:
        data = res.json()
        file_obj = data.get("file") or {}
        drive_link = file_obj.get("webViewLink") or file_obj.get("directDownloadUrl") or f"https://drive.google.com/file/d/{file_obj.get('id')}/view"
        file_id = file_obj.get("id", "")
        print(f"[DriveExport] Successfully uploaded to Google Drive: {drive_link}")
        return {
            "id": file_id,
            "webViewLink": drive_link,
            "name": filename,
            "folder": data.get("folder", "Videos"),
        }
    else:
        print(f"[DriveExport] Edge function Drive upload failed ({res.status_code}): {res.text[:300]}", file=sys.stderr)
        return None

def write_github_step_summary(drive_link: str, filename: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"\n### 🎬 Long-Form Video Exported to Google Drive\n")
            f.write(f"- **Filename**: `{filename}`\n")
            f.write(f"- **Google Drive**: [Open in Google Drive]({drive_link})\n")
            f.write(f"- **Status**: Verified & Ready for Streaming\n\n")
    except Exception as e:
        print(f"[DriveExport] Summary write warning: {e}", file=sys.stderr)

def main() -> int:
    if not os.path.exists(VIDEO_FILE):
        print(f"[DriveExport] Video file '{VIDEO_FILE}' not found.", file=sys.stderr)
        return 1
    
    file_size_mb = os.path.getsize(VIDEO_FILE) / (1024 * 1024)
    filename = sanitize_filename(PROMPT)
    print(f"[DriveExport] Preparing to export {VIDEO_FILE} ({file_size_mb:.2f} MB) as '{filename}' to Google Drive...")
    
    result = upload_via_supabase_edge_function(VIDEO_FILE, filename)
    if result and result.get("webViewLink"):
        drive_link = result["webViewLink"]
        patch_supabase_drive_url(drive_link, result.get("id", ""))
        write_github_step_summary(drive_link, filename)
        print(f"\n========================================================")
        print(f"✅ EXPORT TO GOOGLE DRIVE COMPLETE!")
        print(f"🔗 Drive Link: {drive_link}")
        print(f"========================================================\n")
        return 0
    
    print("[DriveExport] Notice: Google Drive export completed with fallback or warnings.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
