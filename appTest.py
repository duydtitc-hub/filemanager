from io import BytesIO
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError
import os
import time
from DiscordMethod import send_discord_message
import requests
import mimetypes
SCOPES = ['https://www.googleapis.com/auth/drive']
TOKEN_FILE = 'tokenDrive.json'
CREDS_FILE = 'cre.json'


def get_drive_service():
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        refreshed = False
        if creds and creds.expired and creds.refresh_token:
            try:
                send_discord_message("🔄 Token hết hạn, đang thử refresh...")
                creds.refresh(Request())
                refreshed = True
                send_discord_message("✅ Refresh token thành công.")
            except Exception as e:
                send_discord_message(f"❌ Refresh token thất bại: {e}")

        if not refreshed:
            send_discord_message("⚠️ Đang yêu cầu xác thực lại...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
            send_discord_message("✅ Đăng nhập thành công, đã tạo token mới.")

        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())

    return build('drive', 'v3', credentials=creds)


def safe_filename(name: str, max_length: int = 100) -> str:
    # Simplified safe filename implementation used for OneDrive folder names
    import re
    if not name:
        return 'untitled'
    s = str(name).strip()
    # replace invalid chars with underscore
    s = re.sub(r"[\\/*?:\"<>|]", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    if max_length and len(s) > max_length:
        s = s[:max_length]
    return s


def uploadOneDrive(file_path: str, title: str | None = None, max_retries: int = 3, retry_delay: int = 3):
    """Upload a local file to OneDrive into folder = safe_filename(title).

    Returns a dict with at least 'id' and 'name' and 'viewLink' if successful.
    """
    from urllib.parse import quote
    try:
        import OneDriveUpload as od
    except Exception:
        send_discord_message("❌ OneDrive helper module not available")
        raise

    filename = os.path.basename(file_path)
    folder_label = safe_filename(title) if title else safe_filename(os.path.splitext(filename)[0])

    attempt = 0
    last_error = None
    while attempt < max_retries:
        try:
            attempt += 1
            send_discord_message(f"📤 OneDrive upload ({attempt}/{max_retries}): {file_path} -> /{folder_label}/{filename}")

            access_token = od.get_access_token()

            # create upload session
            upload_url = od.create_upload_session(access_token, folder_label, filename)

            # perform resumable upload (same chunking as OneDriveUpload)
            size = os.path.getsize(file_path)
            last_resp = None
            with open(file_path, 'rb') as fh:
                start = 0
                while start < size:
                    end = min(start + od.CHUNK_SIZE, size) - 1 if hasattr(od, 'CHUNK_SIZE') else min(start + 10 * 1024 * 1024, size) - 1
                    chunk = fh.read(end - start + 1)
                    headers = {
                        'Content-Length': str(len(chunk)),
                        'Content-Range': f'bytes {start}-{end}/{size}'
                    }
                    r = requests.put(upload_url, headers=headers, data=chunk)
                    if r.status_code not in (200, 201, 202):
                        raise Exception(f"upload chunk failed: {r.status_code} {r.text}")
                    try:
                        last_resp = r.json()
                    except Exception:
                        last_resp = None
                    # progress log
                    try:
                        pct = (end + 1) / size * 100
                        send_discord_message(f"🔁 OneDrive: uploaded {start}-{end} ({pct:.1f}%)")
                    except Exception:
                        send_discord_message(f"🔁 OneDrive: uploaded {start}-{end}")
                    start = end + 1

            # After upload, fetch item metadata
            item_path = f"/{od.ONEDRIVE_FOLDER}/{quote(folder_label)}/{quote(filename)}"
            meta_url = f"https://graph.microsoft.com/v1.0/me/drive/root:{item_path}"
            headers = {'Authorization': f'Bearer {access_token}'}
            mr = requests.get(meta_url, headers=headers)
            if mr.status_code not in (200, 201):
                send_discord_message(f"⚠️ OneDrive: failed to fetch item metadata: {mr.status_code} {mr.text}")
                meta = None
            else:
                meta = mr.json()

            view_link = None
            if meta and meta.get('id'):
                # create anonymous view link
                try:
                    link_url = f"https://graph.microsoft.com/v1.0/me/drive/items/{meta['id']}/createLink"
                    pr = requests.post(link_url, headers=headers, json={'type': 'view', 'scope': 'anonymous'})
                    if pr.ok:
                        j = pr.json()
                        view_link = j.get('link', {}).get('webUrl')
                except Exception as e:
                    send_discord_message(f"⚠️ OneDrive: could not create share link: {e}")

            result = {'name': filename}
            if meta and meta.get('id'):
                result['id'] = meta['id']
            if view_link:
                result['webViewLink'] = view_link
                result['downloadLink'] = view_link

            send_discord_message(f"✅ OneDrive: uploaded {filename} -> /{folder_label}/{filename}")
            if view_link:
                send_discord_message(f"🔗 View: {view_link}")

            return result

        except Exception as e:
            last_error = e
            send_discord_message(f"⚠️ OneDrive upload attempt {attempt} failed: {e}")
            if attempt < max_retries:
                send_discord_message(f"⏳ Waiting {retry_delay}s before retry...")
                time.sleep(retry_delay)
                continue
            else:
                send_discord_message(f"❌ OneDrive: upload failed after {max_retries} attempts: {file_path}")
                raise

# --- Ví dụ sử dụng ---

