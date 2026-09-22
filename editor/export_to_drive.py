#!/usr/bin/env python3
"""
Storage Push Module for Hyper Copilot & Video Agent Pipelines.
Directly uploads generated video files to Google Drive inside the dedicated 'Videos' folder
under GDRIVE_MAIN_FOLDER_ID using Service Account Domain-Wide Delegation:
- GDRIVE_DELEGATED_USER = tusharkantidasofficial@gmail.com
- GDRIVE_MAIN_FOLDER_ID (Main Drive Folder ID)
- Service Account Credentials JSON (via GDRIVE_PRIVATE_KEY, SERVICE_ACCOUNT_JSON, or GOOGLE_SERVICE_ACCOUNT_JSON)

Rules:
1. Do NOT push video files to Supabase Storage.
2. Store ONLY lightweight metadata (file_id, title, direct_download_url) in Supabase Database.
3. The direct_download_url triggers instant direct download / in-app preview without redirecting to Google Drive web UI.
"""

import os
import sys
import json
import time
import base64
import subprocess
import requests

DEFAULT_MAIN_FOLDER_ID = "1JGjibA287ds3SFoT_Fl2z8cJ96eCDUFs"
DEFAULT_DELEGATED_USER = "tusharkantidasofficial@gmail.com"

def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or "").strip() or default

# Target File & Metadata
VIDEO_FILE = env("VIDEO_FILE", "out.mp4")
VIDEO_ID = env("VIDEO_ID", "local_test_video")
USER_ID = env("USER_ID", "local_user")
PROMPT = env("PROMPT", "Nature & Cosmic Documentary")

# Google Drive Secret Credentials
GDRIVE_CLIENT_EMAIL = env("GDRIVE_CLIENT_EMAIL")
GDRIVE_PRIVATE_KEY = env("GDRIVE_PRIVATE_KEY")
GDRIVE_MAIN_FOLDER_ID = env("GDRIVE_MAIN_FOLDER_ID") or env("GDRIVE_FOLDER_ID") or DEFAULT_MAIN_FOLDER_ID
GDRIVE_VIDEOS_FOLDER_ID = env("GDRIVE_VIDEOS_FOLDER_ID")
GDRIVE_DELEGATED_USER = env("GDRIVE_DELEGATED_USER") or env("GDRIVE_USER_EMAIL") or DEFAULT_DELEGATED_USER

# Alternate credentials JSON secret names
ALT_SA_JSON = (
    env("SERVICE_ACCOUNT_JSON")
    or env("GOOGLE_SERVICE_ACCOUNT_JSON")
    or env("GDRIVE_SERVICE_ACCOUNT_JSON")
    or env("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    or env("GDRIVE_CREDENTIALS")
)

# Supabase Bridge (Metadata only)
SUPABASE_URL = env("SUPABASE_URL").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = env("SUPABASE_SERVICE_ROLE_KEY")

def sanitize_filename(name: str) -> str:
    clean = "".join(c for c in name if c.isalnum() or c in (" ", "-", "_")).strip()
    return (clean[:60] or "rendered_video").replace(" ", "_") + ".mp4"

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")

def parse_service_account_credentials() -> tuple[str, str]:
    """
    Extracts (client_email, private_key_pem) from any configured secret format
    including full Service Account JSON strings, base64 blobs, or raw PEM keys.
    """
    client_email = GDRIVE_CLIENT_EMAIL
    raw_key = GDRIVE_PRIVATE_KEY or ALT_SA_JSON

    # Check if ALT_SA_JSON contains credentials
    for candidate in [ALT_SA_JSON, GDRIVE_PRIVATE_KEY]:
        if not candidate:
            continue
        c = candidate.strip()
        if c.startswith("{"):
            try:
                parsed = json.loads(c)
                if parsed.get("client_email") and not client_email:
                    client_email = parsed["client_email"]
                if parsed.get("private_key"):
                    raw_key = parsed["private_key"]
                    break
            except Exception:
                pass

    if not raw_key:
        return client_email, ""

    k = raw_key.strip()
    # Check if raw_key itself is JSON
    if k.startswith("{"):
        try:
            parsed = json.loads(k)
            if parsed.get("client_email") and not client_email:
                client_email = parsed["client_email"]
            if parsed.get("private_key"):
                k = parsed["private_key"]
        except Exception:
            pass

    # Strip surrounding quotes or backticks
    if (k.startswith('"') and k.endswith('"')) or \
       (k.startswith("'") and k.endswith("'")) or \
       (k.startswith("`") and k.endswith("`")):
        k = k[1:-1]

    # Handle escaped newlines
    k = k.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\r").strip()

    # Base64 decode check
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

    return client_email.strip(), k.strip()

def get_google_access_token_via_service_account(
    client_email: str,
    private_key_pem: str,
    delegated_user: str = "",
) -> str | None:
    """
    Generates a Google OAuth2 access token directly using Service Account RS256 JWT grant.
    Applies Domain-Wide Delegation (sub = delegated_user) for quota and permissions.
    """
    if not client_email or not private_key_pem:
        print("[DriveExport] Missing client email or private key for Service Account.", file=sys.stderr)
        return None

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": client_email,
        "scope": "https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/drive.file",
        "aud": "https://oauth2.googleapis.com/token",
        "exp": now + 3600,
        "iat": now,
    }
    if delegated_user:
        claims["sub"] = delegated_user
        print(f"[DriveExport] Using Domain-Wide Delegation (sub: {delegated_user})")

    header_b64 = b64url(json.dumps(header).encode("utf-8"))
    claims_b64 = b64url(json.dumps(claims).encode("utf-8"))
    signing_input = f"{header_b64}.{claims_b64}".encode("utf-8")

    sig_b64 = None

    # Method 1: Try Python cryptography package if available
    try:
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        private_key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        sig_b64 = b64url(signature)
    except Exception:
        # Method 2: Fallback to OpenSSL CLI natively on Linux runner
        key_file = f"/tmp/_sa_key_{os.getpid()}_{int(time.time())}.pem"
        try:
            with open(key_file, "w", encoding="utf-8") as f:
                f.write(private_key_pem + "\n")
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
            print(f"[DriveExport] OAuth token exchange refused ({res.status_code}): {res.text[:250]}", file=sys.stderr)
            # If delegation failed (e.g. user not in domain), retry without 'sub'
            if delegated_user and "unauthorized_client" in res.text:
                print("[DriveExport] Retrying Service Account token without subject delegation...", file=sys.stderr)
                return get_google_access_token_via_service_account(client_email, private_key_pem, delegated_user="")
    except Exception as e:
        print(f"[DriveExport] OAuth token request error: {e}", file=sys.stderr)

    return None

def get_or_create_videos_folder(access_token: str, main_folder_id: str) -> str:
    """
    Finds or creates the dedicated 'Videos' subfolder inside GDRIVE_MAIN_FOLDER_ID.
    Ensures all videos are placed into the 'Videos' subfolder.
    """
    if GDRIVE_VIDEOS_FOLDER_ID:
        return GDRIVE_VIDEOS_FOLDER_ID

    if not main_folder_id:
        return ""

    headers = {"Authorization": f"Bearer {access_token}"}

    # Search for existing 'Videos' folder inside main_folder_id
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
                print(f"[DriveExport] Found existing 'Videos' subfolder: {videos_id}")
                return videos_id
    except Exception as e:
        print(f"[DriveExport] Notice searching 'Videos' folder: {e}", file=sys.stderr)

    # Create 'Videos' folder inside main_folder_id if not found
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
            print(f"[DriveExport] Created new 'Videos' subfolder: {videos_id}")
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
    Performs Google Drive v3 Resumable Upload for large video files.
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

        print(f"[DriveExport] Uploading '{filename}' ({file_size / (1024*1024):.2f} MB) via resumable stream directly to 'Videos' folder...")
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
                    # Make file publicly readable for in-app preview and instant direct download
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
    Uploads the video file directly into Google Drive 'Videos' folder.
    """
    file_size = os.path.getsize(filepath)

    # For files > 5MB, use Resumable Upload
    if file_size > 5 * 1024 * 1024:
        result = upload_resumable_to_google_drive(access_token, filepath, filename, folder_id)
        if result:
            return result

    # Multipart Upload for smaller files
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

    print(f"[DriveExport] Uploading '{filename}' ({len(file_bytes) / (1024*1024):.2f} MB) directly to Google Drive 'Videos' folder...")
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
            print(f"[DriveExport] Google Drive upload failed ({res.status_code}): {err_text[:300]}", file=sys.stderr)
    except Exception as e:
        print(f"[DriveExport] Direct Drive upload exception: {e}", file=sys.stderr)

    return None

def upload_via_supabase_edge_function(filepath: str, filename: str, target_folder_id: str = "") -> dict | None:
    """
    Fallback using upload-to-drive Supabase Edge Function directly targeting 'Videos' folder.
    """
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
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
            file_id = file_obj.get("id", "")
            return {
                "id": file_id,
                "webViewLink": file_obj.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view",
                "directDownloadUrl": file_obj.get("directDownloadUrl") or f"https://drive.google.com/uc?export=download&id={file_id}",
                "name": filename,
            }
        else:
            print(f"[DriveExport] Edge function fallback failed ({res.status_code}): {res.text[:300]}", file=sys.stderr)
    except Exception as e:
        print(f"[DriveExport] Edge function exception: {e}", file=sys.stderr)

    return None

def store_lightweight_metadata_in_supabase(
    file_id: str,
    title: str,
    direct_download_url: str,
    web_view_link: str = "",
) -> None:
    """
    Stores ONLY lightweight metadata (file_id, title, direct_download_url) in the Supabase Database table.
    Ensures video_url points to direct_download_url for in-app preview & instant download.
    Does NOT push any video file binary to Supabase Storage.
    """
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY and VIDEO_ID):
        return

    print(f"[DriveExport] Syncing lightweight metadata to Supabase 'videos' table (ID: {VIDEO_ID})...")
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    metadata_log = {
        "file_id": file_id,
        "title": title,
        "direct_download_url": direct_download_url,
        "web_view_link": web_view_link,
        "uploaded_to": "Google Drive",
        "folder": "Videos",
    }

    # Full payload with dedicated columns (added in migration) + video_url
    full_payload = {
        "status": "completed",
        "step": "Finished",
        "progress": 100,
        "file_id": file_id,
        "title": title,
        "direct_download_url": direct_download_url,
        "video_url": direct_download_url,
        "logs": [
            f"Uploaded directly to Google Drive (folder: Videos): {direct_download_url}",
            metadata_log,
        ],
    }

    patch_url = f"{SUPABASE_URL}/rest/v1/videos?id=eq.{VIDEO_ID}"
    try:
        res = requests.patch(patch_url, headers=headers, json=full_payload, timeout=15)
        if res.ok:
            print(f"[DriveExport] Successfully stored lightweight metadata in Supabase videos table!")
            return
        else:
            print(f"[DriveExport] Notice updating full payload ({res.status_code}): {res.text[:200]}", file=sys.stderr)
            # Fallback payload with core columns if columns differ
            fallback_payload = {
                "status": "completed",
                "step": "Finished",
                "progress": 100,
                "video_url": direct_download_url,
                "logs": [
                    f"Uploaded directly to Google Drive: {direct_download_url}",
                    metadata_log,
                ],
            }
            res2 = requests.patch(patch_url, headers=headers, json=fallback_payload, timeout=15)
            if res2.ok:
                print(f"[DriveExport] Synced fallback metadata to Supabase videos table.")
    except Exception as e:
        print(f"[DriveExport] Supabase metadata sync error: {e}", file=sys.stderr)

def write_github_step_summary(
    file_id: str,
    title: str,
    direct_download_url: str,
    web_view_link: str,
    folder_name: str = "Videos",
) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"\n### 🎬 Video Uploaded Directly to Google Drive\n")
            f.write(f"- **Title**: `{title}`\n")
            f.write(f"- **File ID**: `{file_id}`\n")
            f.write(f"- **Folder**: Google Drive `{folder_name}` Subfolder\n")
            f.write(f"- **Direct Download / Preview**: [Download Video File]({direct_download_url})\n")
            f.write(f"- **Google Drive View**: [Open in Google Drive]({web_view_link})\n")
            f.write(f"- **Supabase Storage**: Bypassed (Only lightweight metadata stored in Database)\n\n")
    except Exception as e:
        print(f"[DriveExport] Step summary write notice: {e}", file=sys.stderr)

def main() -> int:
    if not os.path.exists(VIDEO_FILE):
        print(f"[DriveExport] Video file '{VIDEO_FILE}' not found.", file=sys.stderr)
        return 1

    file_size_mb = os.path.getsize(VIDEO_FILE) / (1024 * 1024)
    title = PROMPT or "Rendered Video"
    filename = sanitize_filename(title)
    print(f"[DriveExport] Preparing Google Drive upload for {VIDEO_FILE} ({file_size_mb:.2f} MB) as '{filename}'...")

    drive_result: dict | None = None
    target_videos_folder_id = GDRIVE_VIDEOS_FOLDER_ID

    client_email, private_key_pem = parse_service_account_credentials()

    # 1. Try Direct Google Drive API using Service Account + Domain-Wide Delegation
    if client_email and private_key_pem:
        print(f"[DriveExport] Authenticating Google Service Account ({client_email}) for user '{GDRIVE_DELEGATED_USER}'...")
        token = get_google_access_token_via_service_account(
            client_email, private_key_pem, GDRIVE_DELEGATED_USER
        )
        if token:
            target_videos_folder_id = get_or_create_videos_folder(token, GDRIVE_MAIN_FOLDER_ID)
            print(f"[DriveExport] Uploading video to 'Videos' folder ({target_videos_folder_id})...")
            drive_result = upload_direct_to_google_drive(
                token, VIDEO_FILE, filename, folder_id=target_videos_folder_id
            )

    # 2. Try Fallback via Supabase Edge Function
    if not drive_result or not (drive_result.get("id") or drive_result.get("webViewLink")):
        drive_result = upload_via_supabase_edge_function(
            VIDEO_FILE, filename, target_folder_id=target_videos_folder_id
        )

    if drive_result and (drive_result.get("id") or drive_result.get("webViewLink")):
        file_id = drive_result.get("id", "")
        # Construct instant direct download / in-app preview URL
        direct_download_url = (
            drive_result.get("directDownloadUrl")
            or f"https://drive.google.com/uc?export=download&id={file_id}"
        )
        web_view_link = (
            drive_result.get("webViewLink")
            or f"https://drive.google.com/file/d/{file_id}/view"
        )

        # Store ONLY lightweight metadata in Supabase
        store_lightweight_metadata_in_supabase(file_id, title, direct_download_url, web_view_link)
        write_github_step_summary(file_id, title, direct_download_url, web_view_link, "Videos")

        print(f"\n========================================================")
        print(f"✅ UPLOAD DIRECTLY TO GOOGLE DRIVE COMPLETE!")
        print(f"📁 Target Subfolder: Videos ({target_videos_folder_id or 'Configured Folder'})")
        print(f"🆔 File ID: {file_id}")
        print(f"📥 Direct Download URL: {direct_download_url}")
        print(f"🔗 Drive View URL: {web_view_link}")
        print(f"🗄️ Supabase Storage: Not used (Lightweight DB metadata only)")
        print(f"========================================================\n")
        return 0

    print("[DriveExport] Notice: Video rendered, but Google Drive credentials were not configured or export finished with warnings.")
    # Mark in Supabase if not yet marked
    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY and VIDEO_ID:
        try:
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/videos?id=eq.{VIDEO_ID}",
                headers={
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                },
                json={"status": "completed", "step": "Finished", "progress": 100},
                timeout=10,
            )
        except Exception:
            pass
    return 0

if __name__ == "__main__":
    sys.exit(main())
