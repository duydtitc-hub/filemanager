import os
import json
import time
import requests
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from DiscordMethod import send_discord_message
from urllib.parse import quote

# ================== CONFIG ==================
CLIENT_ID = os.environ.get("ONEDRIVE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("ONEDRIVE_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("ONEDRIVE_REDIRECT_URI", "http://localhost:8000/auth/callback")

if not CLIENT_ID or not CLIENT_SECRET:
    raise RuntimeError("Missing ONEDRIVE_CLIENT_ID or ONEDRIVE_CLIENT_SECRET in environment")

AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

VIDEO_FILE = "Ong_noi_toi_noi_loan_o_dia_phu_Tap_1.nar.mp4"
ONEDRIVE_FOLDER = "Videos"
TOKEN_FILE = "OneDrivetoken.json"
CHUNK_SIZE = 10 * 1024 * 1024  # 10MB

app = FastAPI()

# ================== TOKEN STORE ==================
def save_token(data):
    data["expires_at"] = time.time() + data["expires_in"] - 60
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_token():
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def refresh_token(token):
    send_discord_message(f"🔁 OneDrive: refreshing token for client_id={CLIENT_ID}")
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": token["refresh_token"]
    }

    r = requests.post(TOKEN_URL, data=payload)
    r.raise_for_status()
    new_token = r.json()

    token["access_token"] = new_token["access_token"]
    token["expires_at"] = time.time() + new_token["expires_in"] - 60

    if "refresh_token" in new_token:
        token["refresh_token"] = new_token["refresh_token"]

    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token, f, indent=2)

    return token

def get_access_token():
    token = load_token()
    if not token:
        send_discord_message("⚠️ OneDrive: token missing, login required")
        raise Exception("Chưa login Microsoft")

    if time.time() >= token["expires_at"]:
        send_discord_message("ℹ️ OneDrive: access token expired, refreshing...")
        token = refresh_token(token)

    return token["access_token"]

# ================== AUTH ROUTES ==================
@app.get("/login")
def login():
    url = (
        f"{AUTH_URL}"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope=offline_access Files.ReadWrite User.Read"
    )
    return RedirectResponse(url)

@app.get("/auth/callback")
def auth_callback(code: str):
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI
    }

    r = requests.post(TOKEN_URL, data=payload)
    r.raise_for_status()
    save_token(r.json())

    return {"status": "login_success"}

# ================== ONEDRIVE ==================
def create_upload_session(access_token,path, filename):
    send_discord_message(f"ℹ️ OneDrive: creating upload session for {path}/{filename}")
    url = (
        f"https://graph.microsoft.com/v1.0/me/drive/root:"
        f"/{ONEDRIVE_FOLDER}/{path}/{filename}:/createUploadSession"
    )

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    r = requests.post(url, headers=headers, json={})
    r.raise_for_status()
    send_discord_message(f"✅ OneDrive: upload session created for {filename}")
    return r.json()["uploadUrl"]


def create_public_link(access_token, path):
    """Create an anonymous public view link for a OneDrive item at `path`.

    `path` should be a path relative to drive root, e.g. "Videos/My%20Folder/file.mp4"
    Returns the webUrl string on success.
    """
    url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{path}:/createLink"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    body = {
        "type": "view",
        "scope": "anonymous"
    }

    r = requests.post(url, headers=headers, json=body)
    r.raise_for_status()

    return r.json()["link"]["webUrl"]

def upload_large_file(upload_url, path):
    size = os.path.getsize(path)
    send_discord_message(f"⬆️ OneDrive: start upload {path} ({size} bytes)")

    with open(path, "rb") as f:
        start = 0
        while start < size:
            end = min(start + CHUNK_SIZE, size) - 1
            chunk = f.read(end - start + 1)

            headers = {
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {start}-{end}/{size}"
            }

            r = requests.put(upload_url, headers=headers, data=chunk)
            if r.status_code not in (200, 201, 202):
                send_discord_message(f"❌ OneDrive: upload chunk failed {start}-{end}: {r.status_code} {r.text}")
                raise Exception(r.text)

            # If finalised (200 or 201) the response contains the item metadata
            if r.status_code in (200, 201):
                try:
                    data = r.json()
                except Exception:
                    data = None

                # Final progress report
                try:
                    pct = (end + 1) / size * 100
                except Exception:
                    pct = None
                if pct is not None:
                    send_discord_message(f"🔁 OneDrive: uploaded {start}-{end} ({pct:.1f}%)")
                else:
                    send_discord_message(f"🔁 OneDrive: uploaded {start}-{end}")

                return data

            # Progress report for non-final chunk (202)
            try:
                pct = (end + 1) / size * 100
            except Exception:
                pct = None
            if pct is not None:
                send_discord_message(f"🔁 OneDrive: uploaded {start}-{end} ({pct:.1f}%)")
            else:
                send_discord_message(f"🔁 OneDrive: uploaded {start}-{end}")
            start = end + 1

# ================== UPLOAD API ==================

def uploadOneDrive(folderPath: str, fileName: str):
    max_attempts = 3
    backoff_base = 2
    send_discord_message(f"▶️ OneDrive: upload requested: folder={folderPath} file={fileName}")
    for attempt in range(1, max_attempts + 1):
        try:
            send_discord_message(f"ℹ️ OneDrive: upload attempt {attempt}/{max_attempts} for {fileName}")
            access_token = get_access_token()
            send_discord_message("ℹ️ OneDrive: obtained access token")

            upload_url = create_upload_session(access_token, folderPath, fileName)
            uploaded_meta = upload_large_file(upload_url, fileName)
            send_discord_message(f"✅ OneDrive: upload completed: {fileName}")

            # Build item path relative to drive root and URL-encode parts
            if folderPath and str(folderPath).strip():
                encoded_folder = quote(str(folderPath).strip(), safe='')
                item_path = f"{ONEDRIVE_FOLDER}/{encoded_folder}/{quote(fileName, safe='')}"
            else:
                item_path = f"{ONEDRIVE_FOLDER}/{quote(fileName, safe='')}"

            # Create anonymous public link and return metadata where possible
            try:
                web_link = create_public_link(access_token, item_path)
            except Exception as e:
                send_discord_message(f"⚠️ OneDrive: create public link failed for {fileName}: {e}")
                web_link = None

            result = {
                "status": "uploaded_success",
                "name": fileName,
                "meta": uploaded_meta,
            }
            if web_link:
                result["webViewLink"] = web_link

            return result
        except Exception as e:
            send_discord_message(f"⚠️ OneDrive: attempt {attempt} failed for {fileName}: {e}")
            if attempt < max_attempts:
                wait = backoff_base ** (attempt - 1)
                send_discord_message(f"⏳ OneDrive: retrying in {wait}s...")
                try:
                    time.sleep(wait)
                except Exception:
                    pass
                continue
            else:
                send_discord_message(f"❌ OneDrive: upload failed after {max_attempts} attempts: {fileName}")
                raise
