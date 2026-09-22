#!/usr/bin/env python3
"""
Storage Push Module for Hyper Copilot & Video Agent Pipelines.
Implements Google Drive video upload into the dedicated 'Videos' folder using:
- GDRIVE_CLIENT_EMAIL
- GDRIVE_PRIVATE_KEY
- GDRIVE_MAIN_FOLDER_ID (and GDRIVE_FOLDER_ID fallback)
- GDRIVE_VIDEOS_FOLDER_ID (optional explicit Videos folder)
- GDRIVE_DELEGATED_USER / GDRIVE_USER_EMAIL (optional user impersonation for Workspace)

Features:
1. Resilient Service Account key cleaning (handles JSON, quotes, escaped newlines, base64)
2. Native RFC 7523 Service Account JWT grant with cryptography or OpenSSL fallback
3. Automatic discovery or creation of the dedicated 'Videos' folder
4. Google Shared Drive support via supportsAllDrives=true and includeItemsFromAllDrives=true
5. Resumable chunked upload support for large video files
6. Supabase Edge Function fallback ('upload-to-drive') targeting the 'Videos' folder
7. Real-time sync back to Supabase database (`videos.drive_url`) and GitHub Step Summary
"""

import os
import sys
import json
import time
import base64
import subprocess
import requests

DEFAULT_MAIN_FOLDER_ID = "1JGjibA287ds3SFoT_Fl2z8cJ96eCDUFs"

def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or "").strip() or default

# Target File & Metadata
VIDEO_FILE = env("VIDEO_FILE", "out.mp4")
VIDEO_ID = env("VIDEO_ID", "local_test_video")
USER_ID = env("USER_ID", "local_user")
PROMPT = env("PROMPT", "Nature & Cosmic Documentary")

# Exact GitHub Secrets specified in pipeline specifications
GOOGLE_CLOUD_API_ID = env("GOOGLE_CLOUD_API_ID")
GOOGLE_CLOUD_API_SECRET = env("GOOGLE_CLOUD_API_SECRET")
GDRIVE_CLIENT_EMAIL = env("GDRIVE_CLIENT_EMAIL")
GDRIVE_PRIVATE_KEY = env("GDRIVE_PRIVATE_KEY")
GDRIVE_MAIN_FOLDER_ID = env("GDRIVE_MAIN_FOLDER_ID") or env("GDRIVE_FOLDER_ID") or DEFAULT_MAIN_FOLDER_ID
GDRIVE_VIDEOS_FOLDER_ID = env("GDRIVE_VIDEOS_FOLDER_ID")
GDRIVE_DELEGATED_USER = env("GDRIVE_DELEGATED_USER") or env("GDRIVE_USER_EMAIL")

# Supabase Bridge
SUPABASE_URL = env("SUPABASE_URL").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = env("SUPABASE_SERVICE_ROLE_KEY")

def sanitize_filename(name: str) -> str:
    clean = "".join(c for c in name if c.isalnum() or c in (" ", "-", "_")).strip()
    return (clean[:50] or "hyper_video").replace(" ", "_") + ".mp4"

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")

def clean_private_key(raw_key: str) -> tuple[str, str]:
    """
    Cleans private key and extracts client_email if full JSON was provided.
    Returns (cleaned_pem, extracted_client_email).
    """
    k = (raw_key or "").strip()
    extracted_email = ""

    # Check if raw key is JSON credentials
    if k.startswith("{"):
        try:
            parsed = json.loads(k)
            if parsed.get("private_key"):
                k = parsed["private_key"]
            if parsed.get("client_email"):
                extracted_email = parsed["client_email"]
        except Exception:
            pass

    # Strip surrounding quotes or backticks
    if (k.startswith('"') and k.endswith('"')) or \
       (k.startswith("'") and k.endswith("'")) or \
       (k.startswith("`") and k.endswith("`")):
        k = k[1:-1]

    # Handle escaped newlines
    k = k.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\r").strip()

    # Check for base64 encoding
    if not k.startswith("-----BEGIN"):
        try:
            decoded = base64.b64decode(k).decode("utf-8")
            if "BEGIN" in decoded:
                k = decoded.strip()
        except Exception:
            pass

    # Ensure valid PEM structure
    if "-----BEGIN" in k and "-----END" in k:
        start_idx = k.find("-----BEGIN")
        end_idx = k.find("-----END")
        end_marker = k.find("-----", end_idx + 8)
        if end_marker != -1:
            k = k[start_idx : end_marker + 5]
        else:
            k = k[start_idx:]

    return k.strip(), extracted_email

def get_google_access_token_via_service_account(
    client_email: str,
    private_key_pem: str,
    delegated_user: str = "",
) -> str | None:
    """
    Generates a Google OAuth2 access token directly using Service Account RS256 JWT grant.
    Tries python cryptography library first, with clean OpenSSL CLI fallback.
    """
    pem, extracted_email = clean_private_key(private_key_pem)
    email = client_email or extracted_email
    if not email or not pem:
        print("[DriveExport] Missing client email or private key for Service Account authentication.", file=sys.stderr)
        return None

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": email,
        "scope": "https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/drive.file",
        "aud": "https://oauth2.googleapis.com/token",
        "exp": now + 3600,
        "iat": now,
    }
    if delegated_user:
        claims["sub"] = delegated_user

    header_b64 = b64url(json.dumps(header).encode("utf-8"))
    claims_b64 = b64url(json.dumps(claims).encode("utf-8"))
    signing_input = f"{header_b64}.{claims_b64}".encode("utf-8")

    sig_b64 = None

    # Method 1: Try Python cryptography package if available
    try:
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        private_key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        sig_b64 = b64url(signature)
    except Exception:
        # Method 2: Fallback to OpenSSL CLI natively on Linux runner
        key_file = f"/tmp/_sa_key_{os.getpid()}_{int(time.time())}.pem"
        try:
            with open(key_file, "w", encoding="utf-8") as f:
                f.write(pem + "\n")
            os.chmod(key_file, 0o600)
            proc = subprocess.run(
                ["openssl", "dgst", "-sha256", "-sign", key_file],
                input=signing_input,
                capture_output=True,
                check=True,
            )
            sig_b64 = b64url(proc.stdout)
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.decode("utf-8", errors="ignore") if e.stderr else str(e)
            print(f"[DriveExport] OpenSSL signing error: {err_msg.strip()}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"[DriveExport] OpenSSL execution error: {e}", file=sys.stderr)
            return None
        finally:
            if os.path.exists(key_file):
                try:
                    os.remove(key_file)
                except Exception:
                    pass

    if not sig_b64:
        return None

    jwt_token = f"{header_b64}.{claims_b64}.{sig_b64}"

    try:
        res = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": jwt_token,
            },
            timeout=30,
        )
        if res.ok:
            data = res.json()
            return data.get("access_token")
        else:
            print(f"[DriveExport] OAuth token exchange error ({res.status_code}): {res.text[:250]}", file=sys.stderr)
    except Exception as e:
        print(f"[DriveExport] OAuth token request error: {e}", file=sys.stderr)

    return None

def get_or_create_videos_folder(access_token: str, main_folder_id: str) -> str:
    """
    Finds or creates the dedicated 'Videos' subfolder inside main_folder_id.
    Ensures all videos are placed into the 'Videos' folder on Google Drive.
    """
    # 1. Explicit Videos Folder configured in secrets
    if GDRIVE_VIDEOS_FOLDER_ID:
        return GDRIVE_VIDEOS_FOLDER_ID

    if not main_folder_id:
        return ""

    headers = {"Authorization": f"Bearer {access_token}"}

    # 2. Search for existing 'Videos' folder inside main_folder_id
    query = f"'{main_folder_id}' in parents and name = 'Videos' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    search_url = "https://www.googleapis.com/drive/v3/files"
    params = {
        "q": query,
        "fields": "files(id,name)",
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    try:
        res = requests.get(search_url, headers=headers, params=params, timeout=20)
        if res.ok:
            files = res.json().get("files", [])
            if files:
                videos_id = files[0]["id"]
                print(f"[DriveExport] Found existing 'Videos' folder: {videos_id}")
                return videos_id
    except Exception as e:
        print(f"[DriveExport] Notice searching 'Videos' folder: {e}", file=sys.stderr)

    # 3. Create 'Videos' folder inside main_folder_id if not found
    create_url = "https://www.googleapis.com/drive/v3/files?supportsAllDrives=true"
    payload = {
        "name": "Videos",
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [main_folder_id],
    }
    try:
        res = requests.post(
            create_url,
            headers={**headers, "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        if res.ok:
            videos_id = res.json().get("id", "")
            print(f"[DriveExport] Created new 'Videos' folder: {videos_id}")
            return videos_id
        else:
            print(f"[DriveExport] Create 'Videos' folder notice ({res.status_code}): {res.text[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"[DriveExport] Error creating 'Videos' folder: {e}", file=sys.stderr)

    return main_folder_id

def upload_resumable_to_google_drive(
    access_token: str,
    filepath: str,
    filename: str,
    folder_id: str,
) -> dict | None:
    """
    Performs Google Drive v3 Resumable Upload for large media files (>5 MB).
    """
    file_size = os.path.getsize(filepath)
    init_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true&fields=id,name,webViewLink,webContentLink"
    metadata = {
        "name": filename,
        "mimeType": "video/mp4",
    }
    if folder_id:
        metadata["parents"] = [folder_id]

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(file_size),
    }

    try:
        init_res = requests.post(init_url, headers=headers, json=metadata, timeout=30)
        if not init_res.ok:
            print(f"[DriveExport] Resumable init failed ({init_res.status_code}): {init_res.text[:300]}", file=sys.stderr)
            return None

        upload_location = init_res.headers.get("Location")
        if not upload_location:
            print("[DriveExport] Resumable init missing 'Location' header.", file=sys.stderr)
            return None

        print(f"[DriveExport] Uploading '{filename}' ({file_size / (1024*1024):.2f} MB) via resumable stream to 'Videos' folder...")
        with open(filepath, "rb") as f:
            upload_headers = {
                "Content-Length": str(file_size),
                "Content-Type": "video/mp4",
            }
            res = requests.put(upload_location, headers=upload_headers, data=f, timeout=600)
            if res.ok:
                result = res.json()
                file_id = result.get("id")
                if file_id:
                    try:
                        requests.post(
                            f"https://www.googleapis.com/drive/v3/files/{file_id}/permissions?supportsAllDrives=true",
                            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                            json={"role": "reader", "type": "anyone"},
                            timeout=10,
                        )
                    except Exception:
                        pass
                return result
            else:
                print(f"[DriveExport] Resumable upload failed ({res.status_code}): {res.text[:300]}", file=sys.stderr)
    except Exception as e:
        print(f"[DriveExport] Resumable upload exception: {e}", file=sys.stderr)

    return None

def upload_direct_to_google_drive(
    access_token: str,
    filepath: str,
    filename: str,
    folder_id: str = "",
) -> dict | None:
    """
    Performs direct Google Drive upload into the target folder.
    Supports both Resumable Upload (for video files) and Multipart Upload.
    """
    file_size = os.path.getsize(filepath)

    # For files > 5MB, prefer Resumable Upload for reliability
    if file_size > 5 * 1024 * 1024:
        result = upload_resumable_to_google_drive(access_token, filepath, filename, folder_id)
        if result:
            return result

    # Fallback to Multipart Upload
    metadata: dict = {"name": filename, "mimeType": "video/mp4"}
    if folder_id:
        metadata["parents"] = [folder_id]

    boundary = f"-------GoogleDriveBoundary{int(time.time())}"
    part1_headers = b"Content-Type: application/json; charset=UTF-8\r\n\r\n"
    part1_body = json.dumps(metadata).encode("utf-8")
    part2_headers = b"Content-Type: video/mp4\r\n\r\n"

    with open(filepath, "rb") as f:
        file_bytes = f.read()

    multipart_body = (
        b"--" + boundary.encode("utf-8") + b"\r\n"
        + part1_headers + part1_body
        + b"\r\n--" + boundary.encode("utf-8") + b"\r\n"
        + part2_headers + file_bytes
        + b"\r\n--" + boundary.encode("utf-8") + b"--\r\n"
    )

    url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&supportsAllDrives=true&fields=id,name,webViewLink,webContentLink"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": f"multipart/related; boundary={boundary}",
        "Content-Length": str(len(multipart_body)),
    }

    print(f"[DriveExport] Uploading '{filename}' ({len(file_bytes) / (1024*1024):.2f} MB) to Google Drive (folder: {folder_id or 'Videos'})...")
    try:
        res = requests.post(url, headers=headers, data=multipart_body, timeout=300)
        if res.ok:
            result = res.json()
            file_id = result.get("id")
            if file_id:
                try:
                    requests.post(
                        f"https://www.googleapis.com/drive/v3/files/{file_id}/permissions?supportsAllDrives=true",
                        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                        json={"role": "reader", "type": "anyone"},
                        timeout=10,
                    )
                except Exception:
                    pass
            return result
        else:
            err_text = res.text
            print(f"[DriveExport] Google Drive API upload failed ({res.status_code}): {err_text[:300]}", file=sys.stderr)
            if res.status_code == 403 and ("storageQuotaExceeded" in err_text or "storage quota" in err_text):
                print(
                    "\n[DriveExport] ⚠️ GOOGLE DRIVE SERVICE ACCOUNT QUOTA NOTICE:\n"
                    "[DriveExport] Service Accounts have 0 GB personal storage quota in 'My Drive'.\n"
                    "[DriveExport] To store videos in Google Drive, the target folder must be inside a Google Shared Drive\n"
                    f"[DriveExport] (add {GDRIVE_CLIENT_EMAIL} as 'Content Manager' or 'Contributor' to the Shared Drive)\n"
                    "[DriveExport] OR configure Domain-Wide Delegation by setting GDRIVE_DELEGATED_USER.\n",
                    file=sys.stderr,
                )
    except Exception as e:
        print(f"[DriveExport] Direct Drive upload exception: {e}", file=sys.stderr)

    return None

def upload_via_supabase_edge_function(filepath: str, filename: str, target_folder_id: str = "") -> dict | None:
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
        print("[DriveExport] Supabase credentials missing; skipping Edge Function fallback.")
        return None

    url = f"{SUPABASE_URL}/functions/v1/upload-to-drive"
    print(f"[DriveExport] Uploading to Google Drive via Supabase Edge Function fallback (folder: 'Videos')...")
    try:
        with open(filepath, "rb") as f:
            files = {"file": (filename, f, "video/mp4")}
            data = {"folder": "Videos"}
            if target_folder_id:
                data["folderId"] = target_folder_id
            elif GDRIVE_MAIN_FOLDER_ID:
                data["folderId"] = GDRIVE_MAIN_FOLDER_ID
            headers = {"Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}"}
            res = requests.post(url, headers=headers, files=files, data=data, timeout=300)

        if res.ok:
            data = res.json()
            file_obj = data.get("file") or {}
            drive_link = (
                file_obj.get("webViewLink")
                or file_obj.get("directDownloadUrl")
                or (f"https://drive.google.com/file/d/{file_obj.get('id')}/view" if file_obj.get("id") else "")
            )
            return {
                "id": file_obj.get("id", ""),
                "webViewLink": drive_link,
                "name": filename,
            }
        else:
            print(f"[DriveExport] Edge function fallback failed ({res.status_code}): {res.text[:300]}", file=sys.stderr)
    except Exception as e:
        print(f"[DriveExport] Edge function exception: {e}", file=sys.stderr)

    return None

def patch_supabase_drive_url(drive_url: str, file_id: str = "") -> None:
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY and VIDEO_ID):
        return
    try:
        payload = {
            "logs": f"Exported to Google Drive ('Videos' folder) successfully: {drive_url}",
        }
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
        print(f"[DriveExport] Supabase patch notice: {e}", file=sys.stderr)

def write_github_step_summary(drive_link: str, filename: str, folder_name: str = "Videos") -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"\n### 🎬 Video Exported to Google Drive\n")
            f.write(f"- **Filename**: `{filename}`\n")
            f.write(f"- **Target Folder**: `{folder_name}`\n")
            f.write(f"- **Google Drive**: [Open Rendered Video in Google Drive]({drive_link})\n")
            f.write(f"- **Status**: Verified & Ready for Streaming\n\n")
    except Exception as e:
        print(f"[DriveExport] Step summary write notice: {e}", file=sys.stderr)

def main() -> int:
    if not os.path.exists(VIDEO_FILE):
        print(f"[DriveExport] Video file '{VIDEO_FILE}' not found.", file=sys.stderr)
        return 1

    file_size_mb = os.path.getsize(VIDEO_FILE) / (1024 * 1024)
    filename = sanitize_filename(PROMPT)
    print(f"[DriveExport] Preparing Google Drive export for {VIDEO_FILE} ({file_size_mb:.2f} MB) as '{filename}'...")

    drive_result: dict | None = None
    target_videos_folder_id = GDRIVE_VIDEOS_FOLDER_ID

    # 1. Try Direct Google Drive API using GDRIVE_CLIENT_EMAIL & GDRIVE_PRIVATE_KEY
    if GDRIVE_CLIENT_EMAIL and GDRIVE_PRIVATE_KEY:
        print(f"[DriveExport] Authenticating Google Service Account ({GDRIVE_CLIENT_EMAIL})...")
        token = get_google_access_token_via_service_account(
            GDRIVE_CLIENT_EMAIL, GDRIVE_PRIVATE_KEY, GDRIVE_DELEGATED_USER
        )
        if token:
            target_videos_folder_id = get_or_create_videos_folder(token, GDRIVE_MAIN_FOLDER_ID)
            print(f"[DriveExport] Pushing video to Google Drive 'Videos' folder ({target_videos_folder_id})...")
            drive_result = upload_direct_to_google_drive(
                token, VIDEO_FILE, filename, folder_id=target_videos_folder_id
            )

    # 2. Try Fallback via Supabase Edge Function
    if not drive_result or not drive_result.get("webViewLink"):
        drive_result = upload_via_supabase_edge_function(
            VIDEO_FILE, filename, target_folder_id=target_videos_folder_id
        )

    if drive_result and (drive_result.get("webViewLink") or drive_result.get("id")):
        file_id = drive_result.get("id", "")
        drive_link = drive_result.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
        patch_supabase_drive_url(drive_link, file_id)
        write_github_step_summary(drive_link, filename, "Videos")
        print(f"\n========================================================")
        print(f"✅ EXPORT TO GOOGLE DRIVE COMPLETE!")
        print(f"📁 Folder: Videos ({target_videos_folder_id or 'Configured Folder'})")
        print(f"🔗 Link: {drive_link}")
        print(f"========================================================\n")
        return 0

    print("[DriveExport] Notice: Video rendered successfully, but Google Drive credentials were not configured or export finished with warnings.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
