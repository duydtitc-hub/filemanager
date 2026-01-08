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


def upload_bytes_to_drive(file_path: str,
                         folder_id=None,
                          max_retries: int = 3, retry_delay: int = 3):
    with open(file_path, "rb") as f:
        file_data = f.read()    
    filename=os.path.basename(file_path)
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type is None:
        mime_type = "application/octet-stream"  # fallback nếu không đoán được
    attempt = 0
    last_error = None

    while attempt < max_retries:
        try:
            attempt += 1
            send_discord_message(f"📤 Đang upload ({attempt}/{max_retries})...")

            service = get_drive_service()

            file_metadata = {'name': filename}
            if folder_id:
                file_metadata['parents'] = [folder_id]

            media = MediaIoBaseUpload(
                BytesIO(file_data),
                mimetype=mime_type,
                resumable=True
            )

            uploaded = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink'
            ).execute()
          
            file_id = uploaded['id']
            service.permissions().create(
                fileId=file_id,
                body={'type': 'anyone', 'role': 'reader'}
            ).execute()
            view_link = uploaded.get('webViewLink')
            download_link = f"https://drive.google.com/uc?export=download&id={file_id}"

            send_discord_message(f"✅ Uploaded: {uploaded['name']}")
            send_discord_message(f"🔗 Xem trực tiếp: {view_link}")
            send_discord_message(f"⬇️ Tải về: {download_link}")

            uploaded['downloadLink'] = download_link
            uploaded['viewLink'] = view_link

            return uploaded

        except HttpError as e:
            last_error = e
            send_discord_message(f"⚠️ Lỗi HTTP ({e.resp.status if e.resp else 'Unknown'}): {e}")
        except Exception as e:
            last_error = e
            send_discord_message(f"⚠️ Lỗi khác: {e}")

        if attempt < max_retries:
            send_discord_message(f"⏳ Chờ {retry_delay} giây trước khi thử lại...")
            time.sleep(retry_delay)

    send_discord_message("❌ Upload thất bại sau 3 lần thử.")
    raise last_error

# --- Ví dụ sử dụng ---

