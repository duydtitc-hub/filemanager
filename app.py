from fastapi import FastAPI, Query, UploadFile, File, Form, Request, Body, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.responses import StreamingResponse, HTMLResponse, Response
import os, re, logging, hashlib, subprocess, json, math, requests
from GoogleTTS import text_to_wav
from datetime import datetime
from bs4 import BeautifulSoup
from yt_dlp import YoutubeDL
import convert_stt
# Try to import `transcribe_audio` from STTEXT; if unavailable, leave as None and import dynamically at runtime
transcribe_audio = None
def get_transcribe_audio():
    global transcribe_audio
    if transcribe_audio is None:
        try:
            import importlib
            mod = importlib.import_module("STTEXT")
            transcribe_audio = getattr(mod, 'transcribe_audio', None)
        except Exception:
            transcribe_audio = None
    return transcribe_audio
# from pydub import AudioSegment  # Không dùng nữa - dùng ffmpeg thay thế
import shlex
import openai
import tempfile
import cv2

import numpy as np
from base64 import b64encode, b64decode
import json as _json
from google import genai as _genai
from google.genai import types as gen_types
from typing import List, Dict
from datetime import timedelta
from pathlib import Path
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import time
from fastapi import HTTPException
import functools
from google import genai
from google.genai import types
import wave
import base64
import struct
import signal
import random
import shutil
from urllib.parse import urljoin
from urllib.parse import quote, quote_plus
from appTest import uploadOneDrive
from DiscordMethod import send_discord_message
from srt_translate import translate_srt_file
from GetTruyen import get_novel_text_laophatgia, get_novel_text_vivutruyen, get_novel_text, crawl_chapters_until_disabled, get_wattpad_novel
from appYouTube import generatevideoveo3,concat_crop_audio_youtube,upload_video,render_video_only,add_audio_to_video,split_video_by_time_with_title,render_add_audio_and_split
# khởi tạo executor (tùy chỉnh max_workers nếu muốn)
executor = ThreadPoolExecutor(max_workers=4)
TASK_QUEUE: asyncio.Queue = asyncio.Queue()
WORKER_COUNT = 2  # số worker xử lý đồng thời (thay đổi tuỳ ý)
_worker_tasks: List[asyncio.Task] = []
# In-memory set to track task_ids currently queued in TASK_QUEUE to avoid double-enqueue
QUEUED_TASK_IDS: set = set()

# In-memory mapping of running task_id -> asyncio.Task for cooperative cancellation
RUNNING_TASKS: dict = {}

def is_task_cancelled(task_id: str) -> bool:
    try:
        tasks = load_tasks()
        return str(tasks.get(task_id, {}).get('status', '')).lower() == 'cancelled'
    except Exception:
        return False


def should_abort_sync(task_id: str) -> bool:
    """Sync-safe check used inside thread workers to cooperatively abort long-running work.

    Returns True if the task's status in tasks.json is set to 'cancelled'.
    """
    try:
        tasks = load_tasks()
        return str(tasks.get(task_id, {}).get('status', '')).lower() == 'cancelled'
    except Exception:
        return False

def create_tracked_task(task_id: str, coro):
    """Create and track an asyncio.Task tied to `task_id`.

    The task is stored in `RUNNING_TASKS` and removed on completion. If the task
    is cancelled, its status in `tasks.json` will be set to 'cancelled'.
    """
    t = asyncio.create_task(coro)
    try:
        RUNNING_TASKS[task_id] = t
    except Exception:
        pass

    def _on_done(fut: asyncio.Future):
        try:
            RUNNING_TASKS.pop(task_id, None)
        except Exception:
            pass
        try:
            if fut.cancelled():
                tasks_local = load_tasks()
                if task_id in tasks_local:
                    tasks_local[task_id]['status'] = 'cancelled'
                    save_tasks(tasks_local)
        except Exception:
            pass

    t.add_done_callback(_on_done)
    return t


class WebSocketManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active.append(websocket)

    def disconnect(self, websocket: WebSocket):
        try:
            self.active.remove(websocket)
        except Exception:
            pass

    async def broadcast_tasks(self, tasks: dict):
        data = {"type": "tasks", "tasks": tasks}
        txt = json.dumps(data, default=str, ensure_ascii=False)
        for ws in list(self.active):
            try:
                await ws.send_text(txt)
            except Exception:
                try:
                    self.disconnect(ws)
                except Exception:
                    pass


ws_manager = WebSocketManager()

def to_project_relative_posix(p: str) -> str:
    """Convert a file path to a project-relative POSIX path starting at OUTPUT_DIR.

    Examples:
      - "E:\\...\\tiktokad\\20251127_123151\\file.mp4" -> "tiktokad/20251127_123151/file.mp4"
      - "/app/tiktokad/2025.../file.mp4" -> "tiktokad/2025.../file.mp4"
      - fallback: replace backslashes with slashes
    """
    if not p:
        return p
    try:
        norm = os.path.normpath(p)
        parts = norm.split(os.sep)
        if OUTPUT_DIR in parts:
            idx = parts.index(OUTPUT_DIR)
            rel_parts = parts[idx:]
            return "/".join(rel_parts)
        # fallback
        return p.replace('\\', '/')
    except Exception:
        return p.replace('\\', '/')


def _report_and_ignore(e: Exception, ctx: str | None = None):
    try:
        import traceback
        msg = f"⚠️ Ignored exception{': ' + ctx if ctx else ''}: {e}\n{traceback.format_exc()}"
        try:
            send_discord_message(msg)
        except Exception:
            # best-effort logging only
            pass
    except Exception as e:
        _report_and_ignore(e, "ignored")
async def enqueue_task(payload: dict):
    """Helper to enqueue a task payload into TASK_QUEUE while tracking its id.

    This prevents the periodic enqueuer from duplicating tasks that were
    already placed into the in-memory queue by endpoints.
    """
    try:
        tid = payload.get("task_id")
        if tid:
            QUEUED_TASK_IDS.add(tid)
    except Exception as e:
        _report_and_ignore(e, "enqueue_task: add queued id")
    await TASK_QUEUE.put(payload)
# ==============================
# Cấu hình logging
# ==============================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("truyen-video")
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Truyen Video API")
# Allow CORS for album/static frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# album endpoints will be defined later in this file (merged from album_api.py)
# openai and Gemini keys are loaded from `config.py` below (read from env/.env)
POLL_INTERVAL = 5  # giây chờ file audio sẵn sàng
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
music_path = os.path.join(BASE_DIR, "music_folder")
VIDEO_CACHE_DIR = os.path.join(OUTPUT_DIR, "video_cache")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(VIDEO_CACHE_DIR, exist_ok=True)
os.makedirs(VIDEO_CACHE_DIR, exist_ok=True)
# --- Album API (merged from album_api.py) ---
import mimetypes
from pathlib import Path as _Path

# OUTPUTS directory for album endpoints (use existing OUTPUT_DIR)
OUTPUTS = _Path(OUTPUT_DIR)
OUTPUTS.mkdir(parents=True, exist_ok=True)


def safe_path(rel: str) -> _Path:
    target = (OUTPUTS / rel).resolve()
    if not str(target).startswith(str(OUTPUTS.resolve())):
        raise ValueError("invalid path")
    return target


@app.get("/api/list")
async def api_list(path: str = Query('', alias='path'), type: str = Query('all')):
    try:
        p = safe_path(path) if path else OUTPUTS
    except Exception:
        raise HTTPException(status_code=400, detail="invalid path")
    if not p.exists():
        raise HTTPException(status_code=404, detail="not found")

    folders = []
    files = []
    for entry in sorted(p.iterdir()):
        if entry.is_dir():
            folders.append({"name": entry.name})
        else:
            mime, _ = mimetypes.guess_type(str(entry))
            ftype = 'other'
            if mime:
                if mime.split('/')[0] == 'image':
                    ftype = 'image'
                elif mime.split('/')[0] == 'video':
                    ftype = 'video'
            if type == 'all' or type == ftype:
                try:
                    mtime = entry.stat().st_mtime
                except Exception:
                    mtime = None
                files.append({"name": entry.name, "size": entry.stat().st_size, "type": ftype, "mtime": mtime})
    return {"path": path, "folders": folders, "files": files}


@app.get('/files/{filepath:path}')
async def serve_file(filepath: str, request: Request, download: str = Query(None)):
    try:
        p = safe_path(filepath)
    except Exception:
        raise HTTPException(status_code=400, detail='invalid path')
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail='not found')

    file_size = p.stat().st_size
    # support explicit download via ?download=1|true|yes
    download_mode = str(download).lower() in ('1', 'true', 'yes') if download is not None else False
    mime, _ = mimetypes.guess_type(str(p))
    content_disposition = f'attachment; filename="{p.name}"' if download_mode else 'inline'

    # If download mode requested, bypass range handling and serve as attachment
    if download_mode:
        headers = {'Content-Disposition': content_disposition, 'Cache-Control': 'public, max-age=3600'}
        return FileResponse(str(p), media_type=mime or 'application/octet-stream', headers=headers)

    range_header = request.headers.get('range')
    if not range_header:
        headers = {'Content-Disposition': content_disposition, 'Cache-Control': 'public, max-age=3600'}
        return FileResponse(str(p), media_type=mime or 'application/octet-stream', headers=headers)

    # parse range
    try:
        unit, rng = range_header.split('=')
        start_s, end_s = rng.split('-')
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else file_size - 1
    except Exception:
        raise HTTPException(status_code=400, detail='malformed Range')
    if end >= file_size:
        end = file_size - 1
    if start > end:
        raise HTTPException(status_code=416, detail='Requested Range Not Satisfiable')

    length = end - start + 1

    def iter_range(path: _Path, start: int, length: int):
        with open(path, 'rb') as fh:
            fh.seek(start)
            remaining = length
            chunk = globals().get('CHUNK_SIZE', 64 * 1024)
            while remaining > 0:
                read_len = min(chunk, remaining)
                data = fh.read(read_len)
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {
        'Content-Range': f'bytes {start}-{end}/{file_size}',
        'Accept-Ranges': 'bytes',
        'Content-Length': str(length),
        'Content-Disposition': content_disposition,
        'Content-Type': mime or 'application/octet-stream',
        'Cache-Control': 'public, max-age=3600',
    }
    return StreamingResponse(iter_range(p, start, length), status_code=206, media_type=mime or 'application/octet-stream', headers=headers)


@app.post('/api/create_album')
async def create_album(path: str = Form(''), name: str = Form('')):
    if not name:
        raise HTTPException(status_code=400, detail='missing name')
    try:
        parent = safe_path(path) if path else OUTPUTS
    except Exception:
        raise HTTPException(status_code=400, detail='invalid path')
    target = parent / name
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}


@app.post('/api/upload')
async def upload(path: str = Form(''), files: List[UploadFile] = File(...)):
    try:
        dest = safe_path(path) if path else OUTPUTS
    except Exception:
        raise HTTPException(status_code=400, detail='invalid path')
    if not dest.exists():
        raise HTTPException(status_code=404, detail='destination not found')
    saved = []
    for f in files:
        filename = f.filename
        if not filename:
            continue
        target = dest / filename
        with open(target, 'wb') as out:
            shutil.copyfileobj(f.file, out)
        saved.append(filename)
    return {"saved": saved}


@app.get('/api/tiktok_tags')
async def api_tiktok_tags():
    try:
        tags_path = os.path.join(BASE_DIR, 'tiktok_tags.json')
        if os.path.exists(tags_path):
            with open(tags_path, 'r', encoding='utf8') as fh:
                data = json.load(fh)
                if isinstance(data, list):
                    return {"tags": data}
        return {"tags": []}
    except Exception:
        return {"tags": []}


@app.post('/api/tiktok_tags')
async def api_tiktok_tags_add(body: dict):
    """Accept new tag(s) to be stored.

    Body can be: {"tag": "single"} or {"tags": ["a","b"]}
    """
    try:
        tags_path = os.path.join(BASE_DIR, 'tiktok_tags.json')
        new_tags = []
        if isinstance(body, dict):
            if 'tags' in body and isinstance(body.get('tags'), list):
                new_tags = [str(x).strip() for x in body.get('tags') if x]
            elif 'tag' in body and body.get('tag'):
                new_tags = [str(body.get('tag')).strip()]
        # load existing
        existing = []
        if os.path.exists(tags_path):
            try:
                with open(tags_path, 'r', encoding='utf8') as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        existing = [str(x) for x in data if x]
            except Exception:
                existing = []
        # Maintain most-recent-first order: move new/used tags to front
        merged = [str(x).strip() for x in existing if x]
        for t in new_tags:
            tt = t.lstrip('#').strip()
            if not tt:
                continue
            # remove existing occurrence
            merged = [x for x in merged if x != tt]
            # insert at front
            merged.insert(0, tt)
        # optionally limit stored tags to a reasonable number
        MAX_TAGS = 500
        if len(merged) > MAX_TAGS:
            merged = merged[:MAX_TAGS]
        # save
        try:
            with open(tags_path, 'w', encoding='utf8') as fh:
                json.dump(merged, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return {"ok": True, "tags": merged}
    except Exception:
        return {"ok": False, "tags": []}


@app.post('/api/delete')
async def delete(body: dict):
    rel = body.get('path')
    if not rel:
        raise HTTPException(status_code=400, detail='missing path')
    try:
        target = safe_path(rel)
    except Exception:
        raise HTTPException(status_code=400, detail='invalid path')
    try:
        if target.is_dir():
            for child in sorted(target.rglob('*'), reverse=True):
                if child.is_file():
                    child.unlink()
                else:
                    try:
                        child.rmdir()
                    except Exception:
                        pass
            target.rmdir()
        else:
            target.unlink()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}


@app.post('/api/rename')
async def rename(body: dict):
    old = body.get('old')
    new = body.get('new')
    if not old or not new:
        raise HTTPException(status_code=400, detail='missing fields')
    try:
        oldp = safe_path(old)
        newp = safe_path(new)
    except Exception:
        raise HTTPException(status_code=400, detail='invalid path')
    try:
        oldp.rename(newp)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}


@app.get('/api/search')
async def search(q: str = Query(...), path: str = Query(''), type: str = Query('all')):
    if not q:
        raise HTTPException(status_code=400, detail='missing query')
    try:
        base = safe_path(path) if path else OUTPUTS
    except Exception:
        raise HTTPException(status_code=400, detail='invalid path')
    matches = []
    lcq = q.lower()
    for p in base.rglob('*'):
        try:
            name = p.name
        except Exception:
            continue
        if lcq in name.lower():
            rel = str(p.relative_to(OUTPUTS)).replace('\\', '/')
            ftype = 'dir' if p.is_dir() else ('image' if mimetypes.guess_type(str(p))[0] and mimetypes.guess_type(str(p))[0].split('/')[0]=='image' else 'video' if mimetypes.guess_type(str(p))[0] and mimetypes.guess_type(str(p))[0].split('/')[0]=='video' else 'other')
            try:
                mtime = p.stat().st_mtime if p.exists() else None
            except Exception:
                mtime = None
            matches.append({'rel': rel, 'name': name, 'is_dir': p.is_dir(), 'size': p.stat().st_size if p.is_file() else None, 'type': ftype, 'mtime': mtime})
    return {"results": matches}

# --- end album API ---
def _preferred_video_encode_args():
    """Return a list of ffmpeg args for video+audio encoding using the project's preferred compatibility profile.

    This produces H.264 video and AAC audio with settings suitable for iOS/Photos.
    The returned list intentionally includes audio and movflags so callers that extend
    the command with this helper get a consistent encode block.
    """
    return [ "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-profile:v", "high", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", "-pix_fmt", "yuv420p", "-shortest", ]

def _preferred_audio_encode_args():
    # Use AAC LC, 48kHz stereo for compatibility with iOS/Photos
    return ['-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2']
from audio_helpers import _write_concat_list, _concat_audio_from_list, _create_flac_copy, get_tts_part_files, create_final_parts_from_tts, split_audio_by_duration
from config import OUTPUT_DIR, VIDEO_CACHE_DIR, BASE_DIR, GEMINI_API_KEY, POLL_INTERVAL, logger, executor, TASK_QUEUE, WORKER_COUNT, OPENAI_API_KEY
# TTS functions moved to `tts.py`
from tts import (
    generate_audio,
    generate_audio_content,
    generate_audio_summary,
    generate_audio_Gemini,
    split_text_with_space,
    split_text_by_bytes,
    split_text,
)

# If OPENAI_API_KEY is provided via config/env, set openai client
try:
    if OPENAI_API_KEY:
        openai.api_key = OPENAI_API_KEY
except Exception as e:
    try:
        _report_and_ignore(e, "openai.api_key assignment")
    except Exception as e:
        _report_and_ignore(e, "ignored")
class FPTKeyManager:
    def __init__(self, key_file="key.json", limit_per_key=100000):
        self.key_file = key_file
        self.limit_per_key = limit_per_key

        if not os.path.exists(key_file):
            raise Exception(f"Không tìm thấy file key: {key_file}")
        # load số ký tự còn lại của từng key
        with open(key_file, "r") as f:
            self.key_data = json.load(f)
            if not self.key_data:
                raise Exception("File key.json rỗng hoặc không đúng định dạng")

        self.keys = [k for k, v in self.key_data.items() if v > 0]
        if not self.keys:
            raise Exception("Không còn key nào có ký tự khả dụng!")

    def _save(self):
        with open(self.key_file, "w") as f:
            json.dump(self.key_data, f, indent=2)

    def get_key(self, chunk_size=2000):
        # chọn key còn >= chunk_size
        for key in self.keys:
            remaining = self.key_data[key]
            if remaining >= chunk_size:
                self.key_data[key] -= chunk_size
                if self.key_data[key] < chunk_size:
                    # nếu còn < chunk_size, bỏ key này khỏi danh sách tạm thời
                    self.keys.remove(key)
                self._save()
                return key
        raise Exception("Hết giới hạn ký tự tất cả API key!")

    def get_status(self):
        return self.key_data
import os
import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/photoslibrary.appendonly",
    "https://www.googleapis.com/auth/photoslibrary.readonly"
]

TOKEN_FILE = "token.json"
CREDENTIALS_FILE = "credentials.json"

def upload_video_to_photos(file_path: str) -> dict:
    """
    Upload video lên Google Photos (retry tối đa 3 lần nếu thất bại).
    """
    send_discord_message("🚀 Bắt đầu upload video: %s", file_path)

    # --- Lấy credentials ---
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as token_file:
            token_file.write(creds.to_json())

    upload_url = "https://photoslibrary.googleapis.com/v1/uploads"
    create_item_url = "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate"

    for attempt in range(3):
        try:
            send_discord_message("🔄 Lần thử upload #%d...", attempt + 1)

            # --- Upload video để lấy uploadToken ---
            headers = {
                "Authorization": f"Bearer {creds.token}",
                "Content-type": "application/octet-stream",
                "X-Goog-Upload-File-Name": os.path.basename(file_path),
                "X-Goog-Upload-Protocol": "raw",
            }

            with open(file_path, "rb") as f:
                upload_token = requests.post(upload_url, data=f, headers=headers).text.strip()

            if not upload_token:
                raise Exception("Không nhận được upload token.")

            # --- Tạo media item từ uploadToken ---
            payload = {
                "newMediaItems": [
                    {
                        "description": "Video upload qua Google Photos API",
                        "simpleMediaItem": {"uploadToken": upload_token}
                    }
                ]
            }

            response = requests.post(
                create_item_url,
                headers={
                    "Authorization": f"Bearer {creds.token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60
            )

            if response.status_code == 200:
                send_discord_message("✅ Upload thành công video: %s", file_path)
                return response.json()
            else:
                logger.warning("⚠️ Upload thất bại (%d): %s", response.status_code, response.text)
                raise Exception(response.text)

        except Exception as e:
            logger.warning("❌ Lỗi upload lần #%d: %s", attempt + 1, e)
            if attempt < 2:
                delay = random.randint(3, 7)
                send_discord_message("⏳ Chờ %ds trước khi thử lại...", delay)
                time.sleep(delay)
            else:
                logger.error("🚫 Bỏ qua video sau 3 lần upload thất bại: %s", file_path)
                return {"error": str(e)}

    return {"error": "Upload thất bại sau 3 lần thử"}
def download_with_retry(url, dst_path, max_retry=20):
    for attempt in range(max_retry):
        try:
            r = requests.get(url)
            if r.status_code == 200 and r.content:
                with open(dst_path, "wb") as f:
                    f.write(r.content)
                return True
        except Exception as e:
            logger.warning("Lỗi tải audio: %s", e)
        send_discord_message("Chưa có file, chờ %ds...", POLL_INTERVAL)
        time.sleep(POLL_INTERVAL)
    return False

@app.post('/tiktok_upload')
async def scheduler_tiktok_upload(
    video_path: str = Form(..., description="Path to video file (absolute or relative to OUTPUT_DIR)"),
    title: str = Form('', description="Optional title for upload"),
    tags: str | None = Form(None, description="Optional comma-separated tags"),
    cookies: str | None = Form(None, description="Optional cookies file path for uploader"),
    no_headless: bool = Form(False, description="Run uploader with --no-headless flag"),
):
    """Internal handler for TikTok scheduler worker only.

    This endpoint is called by the background worker to process scheduled uploads.
    Do NOT call this directly for manual uploads - use /api/tiktok_upload instead.
    """
    import sys
    import threading
    
    # Resolve provided path relative to OUTPUT_DIR when not absolute
    try:
        if not os.path.isabs(video_path):
            video_path = os.path.join(OUTPUT_DIR, video_path)
    except Exception:
        pass

    if not os.path.exists(video_path):
        send_discord_message(f"❌ TikTok scheduler: video not found: {video_path}")
        return JSONResponse(status_code=404, content={"error": "video not found"})

    tags_list = tags.split(',') if tags else []

    def do_upload():
        # Run Python Playwright uploader in a separate process
        try:
            script = os.path.join(BASE_DIR, 'tiktok_uploader.py')
            cmd = [
                sys.executable,
                script,
                '--video', video_path,
                '--caption', title or '',
            ]
            if tags_list:
                cmd += ['--tags', ','.join(tags_list)]
            # Resolve cookies: if caller provided a name, look under Cookies/ folder
            resolved_cookies = None
            if cookies:
                if os.path.isabs(cookies) and os.path.exists(cookies):
                    resolved_cookies = cookies
                else:
                    # try Cookies/<name> and Cookies/<name>.json
                    cbase = os.path.join(BASE_DIR, 'Cookies')
                    candidate = os.path.join(cbase, cookies)
                    candidate_json = os.path.join(cbase, cookies + '.json')
                    if os.path.exists(candidate):
                        resolved_cookies = candidate
                    elif os.path.exists(candidate_json):
                        resolved_cookies = candidate_json
                    else:
                        # fallback: use provided value as-is
                        resolved_cookies = cookies
            if resolved_cookies:
                cmd += ['--cookies', resolved_cookies]
            if no_headless:
                cmd += ['--no-headless']

            proc = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True)
            try:
                logger.debug('tiktok scheduler uploader stdout: %s', proc.stdout)
                logger.debug('tiktok scheduler uploader stderr: %s', proc.stderr)
            except Exception:
                pass
            return {
                'ok': proc.returncode == 0,
                'rc': proc.returncode,
                'stdout': proc.stdout,
                'stderr': proc.stderr,
            }
        except Exception:
            logger.exception('scheduler do_upload subprocess error')
            return {'ok': False, 'error': 'subprocess failed'}

    # Run the sync Playwright uploader in a dedicated thread
    result = {}
    def _worker():
        try:
            result['resp'] = do_upload()
        except Exception as e:
            result['exc'] = e

    thr = threading.Thread(target=_worker)
    thr.start()
    thr.join()
    
    if 'exc' in result:
        send_discord_message(f"❌ TikTok scheduler upload exception: {result['exc']}")
        return JSONResponse(status_code=500, content={"error": str(result['exc'])})
    
    resp = result.get('resp') or {}
    ok = bool(resp.get('ok'))
    if ok:
        send_discord_message(f"✅ TikTok scheduler upload completed: {os.path.basename(video_path)}")
        return JSONResponse(status_code=200, content={"ok": True, "video": video_path, "stdout": resp.get('stdout', '')})
    else:
        send_discord_message(f"❌ TikTok scheduler upload failed: {os.path.basename(video_path)}")
        return JSONResponse(status_code=500, content={
            "ok": False,
            "error": "upload failed",
            "rc": resp.get('rc'),
            "stdout": resp.get('stdout', ''),
            "stderr": resp.get('stderr', ''),
        })


# Background worker: process TikTok upload schedule file periodically
POLL_TIKTOK_QUEUE_SECONDS = 60


@app.get('/api/tiktok_failed_uploads')
async def api_tiktok_failed_uploads(limit: int = Query(50, description='Maximum number of failed uploads to return')):
    """Get list of failed TikTok uploads from history.
    
    Returns:
        {
            "ok": True,
            "failed_uploads": [
                {
                    "item": {...},  # original queue entry
                    "status": 500,
                    "error": "...",
                    "processed_at": timestamp,
                    "history_index": 123  # index in history array for reference
                }
            ],
            "total": 45
        }
    """
    try:
        history_file = os.path.join(CACHE_DIR, 'tiktok_upload_history.json')
        if not os.path.exists(history_file):
            return {"ok": True, "failed_uploads": [], "total": 0}
        
        try:
            with open(history_file, 'r', encoding='utf8') as fh:
                hist = json.load(fh)
        except Exception:
            hist = []
        
        # Filter failed uploads (status != 200)
        failed = []
        for idx, entry in enumerate(hist):
            try:
                status = entry.get('status', 500)
                if status != 200:
                    entry_copy = entry.copy()
                    entry_copy['history_index'] = idx
                    failed.append(entry_copy)
            except Exception:
                continue
        
        # Sort by processed_at descending (most recent first)
        try:
            failed.sort(key=lambda x: x.get('processed_at', 0), reverse=True)
        except Exception:
            pass
        
        # Limit results
        limited = failed[:limit] if limit > 0 else failed
        
        return {
            "ok": True,
            "failed_uploads": limited,
            "total": len(failed)
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.post('/api/tiktok_retry_upload')
async def api_tiktok_retry_upload(
    history_indices: list[int] = Body(..., description='List of history indices to retry'),
    delay_hours: float = Body(0, description='Delay before upload in hours (optional)')
):
    """Retry failed TikTok uploads by adding them back to the queue.
    
    Args:
        history_indices: List of history_index values from /api/tiktok_failed_uploads response
        delay_hours: Optional delay in hours before scheduling upload
    
    Returns:
        {
            "ok": True,
            "requeued": 3,
            "skipped": 1,
            "errors": ["video not found: ..."]
        }
    """
    try:
        history_file = os.path.join(CACHE_DIR, 'tiktok_upload_history.json')
        schedule_file = os.path.join(CACHE_DIR, 'tiktok_upload_queue.json')
        
        if not os.path.exists(history_file):
            return JSONResponse(status_code=404, content={"ok": False, "error": "history file not found"})
        
        # Load history
        try:
            with open(history_file, 'r', encoding='utf8') as fh:
                hist = json.load(fh)
        except Exception:
            return JSONResponse(status_code=500, content={"ok": False, "error": "failed to load history"})
        
        # Load existing queue
        existing_queue = []
        try:
            if os.path.exists(schedule_file):
                with open(schedule_file, 'r', encoding='utf8') as fh:
                    existing_queue = json.load(fh)
        except Exception:
            existing_queue = []
        
        # Calculate scheduled_at time
        base_time = time.time()
        scheduled_at = int(base_time + (delay_hours * 3600))
        
        requeued = 0
        skipped = 0
        errors = []
        
        for idx in history_indices:
            try:
                if idx < 0 or idx >= len(hist):
                    errors.append(f"Invalid index: {idx}")
                    skipped += 1
                    continue
                
                hist_entry = hist[idx]
                item = hist_entry.get('item', {})
                
                if not item:
                    errors.append(f"Index {idx}: no item data")
                    skipped += 1
                    continue
                
                # Verify video still exists
                video_path = item.get('video_path', '')
                if video_path:
                    # Try to resolve relative path
                    full_path = os.path.join(OUTPUT_DIR, video_path) if not os.path.isabs(video_path) else video_path
                    if not os.path.exists(full_path):
                        errors.append(f"Video not found: {video_path}")
                        skipped += 1
                        continue
                
                # Create new queue entry
                new_entry = {
                    'scheduled_at': scheduled_at,
                    'video_path': video_path,
                    'title': item.get('title', ''),
                    'tags': item.get('tags', []),
                    'cookies': item.get('cookies'),
                    'created_at': int(time.time()),
                    'task_id': item.get('task_id'),
                    'retry_from_history': idx,
                }
                
                existing_queue.append(new_entry)
                requeued += 1
                send_discord_message(f"🔄 Đã thêm lại vào queue: {os.path.basename(video_path)}")
                
            except Exception as e:
                errors.append(f"Index {idx}: {str(e)}")
                skipped += 1
        
        # Save updated queue
        try:
            with open(schedule_file, 'w', encoding='utf8') as fh:
                json.dump(existing_queue, fh, ensure_ascii=False, indent=2)
        except Exception as e:
            return JSONResponse(status_code=500, content={
                "ok": False,
                "error": f"Failed to save queue: {e}",
                "requeued": 0,
                "skipped": len(history_indices)
            })
        
        return {
            "ok": True,
            "requeued": requeued,
            "skipped": skipped,
            "errors": errors
        }
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


async def _process_tiktok_queue_once():
    """Process TikTok upload queue independently.
    
    This worker only processes entries from tiktok_upload_queue.json.
    It does NOT automatically discover tasks from tasks_map.
    Queue entries must be added explicitly via API or other mechanisms.
    """
    schedule_file = os.path.join(CACHE_DIR, 'tiktok_upload_queue.json')
    history_file = os.path.join(CACHE_DIR, 'tiktok_upload_history.json')
    try:
        if not os.path.exists(schedule_file):
            return
        try:
            with open(schedule_file, 'r', encoding='utf8') as fh:
                items = json.load(fh)
        except Exception:
            items = []
        now_ts = int(time.time())
        remaining = []
        processed = []
        for item in items:
            try:
                scheduled_at = int(item.get('scheduled_at', 0) or 0)
            except Exception:
                scheduled_at = 0
            if scheduled_at <= now_ts:
                # process upload
                video_path = item.get('video_path')
                title = item.get('title') or ''
                tags = item.get('tags') or []
                cookies = item.get('cookies') or None
                is_retry = bool(item.get('retry_from_history'))
                
                # Send notification when starting upload
                video_name = os.path.basename(video_path) if video_path else 'unknown'
                if is_retry:
                    send_discord_message(f"🔄 TikTok retry upload: {video_name}")
                else:
                    send_discord_message(f"📤 TikTok scheduled upload: {video_name}")
                
                # convert tags to comma string
                tags_str = ','.join(tags) if isinstance(tags, (list, tuple)) else (str(tags) if tags else '')
                try:
                    # call internal scheduler handler
                    res = await scheduler_tiktok_upload(video_path=video_path, title=title, tags=tags_str, cookies=cookies)
                    # normalize response
                    if isinstance(res, JSONResponse):
                        body = res.body.decode() if hasattr(res, 'body') and isinstance(res.body, (bytes, bytearray)) else None
                        status = res.status_code
                        # Parse body to extract detailed error info
                        error_detail = None
                        if status != 200 and body:
                            try:
                                body_json = json.loads(body)
                                # Build detailed error message from response
                                error_parts = []
                                if body_json.get('error'):
                                    error_parts.append(str(body_json['error']))
                                if body_json.get('stderr'):
                                    stderr = str(body_json['stderr']).strip()
                                    if stderr:
                                        error_parts.append(f"stderr: {stderr}")
                                if body_json.get('rc'):
                                    error_parts.append(f"exit_code: {body_json['rc']}")
                                error_detail = ' | '.join(error_parts) if error_parts else 'Upload failed'
                            except Exception:
                                error_detail = 'Upload failed (parse error)'
                    else:
                        body = None
                        status = 200
                        error_detail = None
                    
                    # Store with detailed error
                    hist_entry = {
                        'item': item,
                        'status': status,
                        'response': body,
                        'processed_at': now_ts
                    }
                    if error_detail:
                        hist_entry['error'] = error_detail
                    processed.append(hist_entry)
                except Exception as e:
                    processed.append({'item': item, 'status': 500, 'error': f'Exception: {str(e)}', 'processed_at': now_ts})
            else:
                remaining.append(item)

        # write remaining back to schedule file
        try:
            with open(schedule_file, 'w', encoding='utf8') as fh:
                json.dump(remaining, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

        # append processed to history
        if processed:
            try:
                hist = []
                if os.path.exists(history_file):
                    try:
                        with open(history_file, 'r', encoding='utf8') as hf:
                            hist = json.load(hf)
                    except Exception:
                        hist = []
                hist.extend(processed)
                with open(history_file, 'w', encoding='utf8') as hf:
                    json.dump(hist, hf, ensure_ascii=False, indent=2)
            except Exception:
                pass
    except Exception:
        return


async def _tiktok_queue_worker_loop():
    while True:
        try:
            await _process_tiktok_queue_once()
        except Exception:
            pass
        await asyncio.sleep(POLL_TIKTOK_QUEUE_SECONDS)



def _add_videos_to_tiktok_queue(task_id: str, video_paths: list[str], task_info: dict):
    """Helper to add completed video(s) to TikTok upload queue.
    
    Args:
        task_id: Task identifier
        video_paths: List of video file paths to upload
        task_info: Task metadata dict containing is_upload_tiktok, upload_duration_hours, tiktok_tags, tiktok_cookies
    """
    try:
        # Coerce is_upload_tiktok to a strict boolean. Some persisted task records
        # may contain string values like 'False' which are truthy in Python.
        raw_flag = task_info.get('is_upload_tiktok')
        is_upload = False
        try:
            if isinstance(raw_flag, str):
                is_upload = raw_flag.strip().lower() in ('1', 'true', 'yes', 'y')
            else:
                is_upload = bool(raw_flag)
        except Exception:
            is_upload = False

        if not is_upload:
            return
        
        schedule_file = os.path.join(CACHE_DIR, 'tiktok_upload_queue.json')
        history_file = os.path.join(CACHE_DIR, 'tiktok_upload_history.json')
        
        # Load existing schedule
        existing_sched = []
        try:
            if os.path.exists(schedule_file):
                with open(schedule_file, 'r', encoding='utf8') as fh:
                    existing_sched = json.load(fh)
        except Exception:
            existing_sched = []
        
        # Determine base scheduling time
        base_time = time.time()
        try:
            spacing_hours = float(task_info.get('upload_duration_hours') or 0)
        except Exception:
            spacing_hours = 0.0
        spacing_sec = spacing_hours * 3600
        
        # Find last scheduled time to avoid conflicts
        last_time = base_time
        try:
            if existing_sched:
                last_time = max(item.get('scheduled_at', base_time) for item in existing_sched)
                if last_time < base_time:
                    last_time = base_time
        except Exception:
            last_time = base_time
        
        # Parse tags
        tags_list = []
        try:
            tiktok_tags = task_info.get('tiktok_tags')
            if tiktok_tags:
                if isinstance(tiktok_tags, list):
                    tags_list = [str(t).strip().lstrip('#') for t in tiktok_tags if t]
                elif isinstance(tiktok_tags, str):
                    tags_list = [t.strip().lstrip('#') for t in re.split(r'[,;\n]+', tiktok_tags) if t.strip()]
        except Exception:
            tags_list = []
        
        # Add each video to queue with incrementing scheduled time
        for idx, video_path in enumerate(video_paths):
            if not video_path or not os.path.exists(video_path):
                continue
            
            scheduled_at = last_time + (idx * spacing_sec)
            
            entry = {
                'scheduled_at': int(scheduled_at),
                'video_path': to_project_relative_posix(video_path),
                'title': task_info.get('title', '') or os.path.splitext(os.path.basename(video_path))[0],
                'tags': tags_list,
                'cookies': task_info.get('tiktok_cookies') or task_info.get('cookies') or None,
                'created_at': int(time.time()),
                'task_id': task_id,
            }
            existing_sched.append(entry)
            send_discord_message(f"📅 Đã thêm vào TikTok queue: {os.path.basename(video_path)} (lên lịch sau {spacing_hours*idx:.1f}h)")
        
        # Save updated schedule
        try:
            with open(schedule_file, 'w', encoding='utf8') as fh:
                json.dump(existing_sched, fh, ensure_ascii=False, indent=2)
        except Exception as e:
            send_discord_message(f"⚠️ Lỗi lưu TikTok queue: {e}")
    
    except Exception as e:
        send_discord_message(f"⚠️ Lỗi thêm vào TikTok queue: {e}")

# ============================== DEPRECATED - Uses AudioSegment ==============================
# def create_audio_chunk_fpt(part: str, part_file: str, api_key: str, voice="banmai"):
#     if os.path.exists(part_file):
#         return AudioSegment.from_file(part_file)
#     
#     headers = {
#         "api_key": api_key,
#         "voice": voice,
#         "Content-Type": "application/json",
#         "speed":2
#     }
#     response = requests.post("https://api.fpt.ai/hmi/tts/v5", headers=headers, data=part)
#     resp_json = response.json()
#     
#     if resp_json.get("error") != 0 or "async" not in resp_json:
#         raise Exception(f"FPT TTS error: {resp_json.get('message')}")
#     
#     async_url = resp_json["async"]
#     success = download_with_retry(async_url, part_file)
#     if not success:
#         raise Exception("Không tải được file audio sau nhiều lần thử")
#     
#     return AudioSegment.from_file(part_file)
# 
# def generate_audio_fpt(text: str, title_slug: str, key_manager: FPTKeyManager, voice="banmai"):
#     final_audio = os.path.join(OUTPUT_DIR, f"{title_slug}.wav")
#     if os.path.exists(final_audio):
#         send_discord_message("🎧 Dùng cache audio: %s", final_audio)
#         return final_audio
# 
#     if not os.path.exists(OUTPUT_DIR):
#         os.makedirs(OUTPUT_DIR)
# 
#     chunk_size = 2000
#     chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
#     audio_segments = []
# 
#     for i, part in enumerate(chunks, 1):
#         part_file = os.path.join(OUTPUT_DIR, f"{title_slug}_part_{i}.mp3")
#         send_discord_message("🎙️ Tạo đoạn audio %d/%d (%s ký tự)...", i, len(chunks), len(part))
#         api_key = key_manager.get_key(chunk_size)
#         seg = create_audio_chunk_fpt(part, part_file, api_key, voice)
#         audio_segments.append(seg)
# 
#     combined = sum(audio_segments, AudioSegment.empty())
#     combined.export(final_audio, format="wav")
#     send_discord_message("✅ Hoàn tất tạo audio: %s", final_audio)
#     return final_audio
# ============================================================================================
# ==============================
# Hàm phụ trợ
# ==============================
TASK_FILE = os.path.join(CACHE_DIR, "tasks.json")
TIKTOK_TASK_FILE = os.path.join(CACHE_DIR, "taskTiktok.json")

def load_tasks():
    # Robust loader: handle empty file, invalid JSON, and unexpected formats.
    if os.path.exists(TASK_FILE):
        try:
            with open(TASK_FILE, "r", encoding="utf-8") as f:
                data = f.read()
            if not data or not data.strip():
                # empty file -> treat as no tasks
                return {}
            parsed = json.loads(data)
            if isinstance(parsed, dict):
                return parsed
            # Unexpected format (e.g., list) -> reset to empty dict to keep format consistent
            send_discord_message("⚠️ tasks file has unexpected format, resetting to empty tasks.")
            try:
                with open(TASK_FILE, "w", encoding="utf-8") as f:
                    json.dump({}, f)
            except Exception as e:
                _report_and_ignore(e, "ignored")
            return {}
        except json.JSONDecodeError:
            # Invalid JSON (maybe truncated). Reset file to empty dict to avoid crashes.
            send_discord_message("⚠️ tasks file contains invalid JSON, resetting to empty tasks.")
            try:
                with open(TASK_FILE, "w", encoding="utf-8") as f:
                    json.dump({}, f)
            except Exception as e:
                _report_and_ignore(e, "ignored")
            return {}
        except Exception as e:
            # Any other error -> log and return empty dict
            send_discord_message(f"⚠️ Error loading tasks file: {e}")
            return {}
    return {}

def save_tasks(tasks):
    with open(TASK_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2, ensure_ascii=False)
    # Broadcast updated tasks to connected WebSocket clients (best-effort)
    try:
        # schedule broadcast in the event loop
        try:
            loop = asyncio.get_event_loop()
            if loop and not loop.is_closed():
                asyncio.ensure_future(ws_manager.broadcast_tasks(tasks))
        except Exception:
            # fallback: attempt synchronous send (rare)
            pass
    except Exception:
        pass

def load_tiktok_tasks():
    if os.path.exists(TIKTOK_TASK_FILE):
        try:
            with open(TIKTOK_TASK_FILE, "r", encoding="utf-8") as f:
                data = f.read()
            if not data or not data.strip():
                return {}
            parsed = json.loads(data)
            if isinstance(parsed, dict):
                return parsed
            send_discord_message("⚠️ tiktok tasks file has unexpected format, resetting to empty tasks.")
            try:
                with open(TIKTOK_TASK_FILE, "w", encoding="utf-8") as f:
                    json.dump({}, f)
            except Exception as e:
                _report_and_ignore(e, "ignored")
            return {}
        except json.JSONDecodeError:
            send_discord_message("⚠️ tiktok tasks file contains invalid JSON, resetting to empty tasks.")
            try:
                with open(TIKTOK_TASK_FILE, "w", encoding="utf-8") as f:
                    json.dump({}, f)
            except Exception as e:
                _report_and_ignore(e, "ignored")
            return {}
        except Exception as e:
            send_discord_message(f"⚠️ Error loading tiktok tasks file: {e}")
            return {}
    return {}

def save_tiktok_tasks(tasks):
    with open(TIKTOK_TASK_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2, ensure_ascii=False)

def cleanup_old_tiktok_tasks(days=30):
    tasks = load_tiktok_tasks()
    now_ts = time.time()
    removed = []
    for task_id, t in list(tasks.items()):
        if now_ts - t.get("created_at", now_ts) > days * 86400:
            removed.append(task_id)
            for fpath in t.get("temp_images", []) + t.get("temp_videos", []):
                try:
                    if os.path.exists(fpath):
                        os.remove(fpath)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
            tasks.pop(task_id, None)
    if removed:
        send_discord_message(f"🧹 Đã xóa TikTok tasks >{days} ngày: {removed}")
        save_tiktok_tasks(tasks)

def cleanup_old_tasks(days=30):
    tasks = load_tasks()
    now_ts = time.time()
    removed = []
    for task_id, t in list(tasks.items()):
        if now_ts - t.get("created_at", now_ts) > days * 86400:
            removed.append(task_id)
            for f in t.get("temp_videos", []):
                if os.path.exists(f):
                    os.remove(f)
            if os.path.exists(t.get("video_path", "")):
                os.remove(t.get("video_path"))
            tasks.pop(task_id, None)
    if removed:
        send_discord_message(f"🧹 Đã xóa các task >{days} ngày: {removed}")
        save_tasks(tasks)


@app.websocket('/ws/tasks')
async def websocket_tasks(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # keep connection alive; clients may send pings
            try:
                msg = await websocket.receive_text()
                # ignore client messages for now
            except WebSocketDisconnect:
                break
            except Exception:
                # continue listening
                await asyncio.sleep(0.1)
    finally:
        try:
            ws_manager.disconnect(websocket)
        except Exception:
            pass


@app.post('/api/task_stop')
async def api_task_stop(body: dict = Body(...)):
    task_id = body.get('task_id')
    action = body.get('action', 'stop')
    if not task_id:
        return JSONResponse(status_code=400, content={"error": "task_id required"})
    tasks = load_tasks()
    if task_id not in tasks:
        return JSONResponse(status_code=404, content={"error": "task not found"})
    # stop: cancel running asyncio task if present
    if action == 'stop':
        t = RUNNING_TASKS.get(task_id)
        try:
            if t and not t.done():
                t.cancel()
        except Exception:
            pass
        tasks[task_id]['status'] = 'cancelled'
        save_tasks(tasks)
        return {"ok": True}
    elif action == 'resume':
        # set to pending — consumer can decide how to resume
        tasks[task_id]['status'] = 'pending'
        save_tasks(tasks)
        return {"ok": True}
    else:
        return JSONResponse(status_code=400, content={"error": "unknown action"})
def enhance_audio(input_path: str, bg_choice: str | None = None) -> str:
    """
    [DEPRECATED] Hàm này không còn được sử dụng trong flow mới.
    Sử dụng prepare_audio_for_video() thay thế.
    
    Dùng ffmpeg để tăng tốc và tinh chỉnh giọng giống CapCut.
    """
    send_discord_message("⚠️ Cảnh báo: enhance_audio() đã deprecated, nên dùng prepare_audio_for_video()")
    return prepare_audio_for_video(input_path, bg_choice)

def prepare_audio_for_video(input_path: str, bg_choice: str | None = None, narration_boost_db: float = 6.0, use_gemini: bool = False) -> str:
    """
    Chuẩn bị audio để render video:
    1. Tăng tốc + filter giọng đọc (như CapCut)
    2. Mix với nhạc nền (nếu có) - DÙNG FFMPEG 100%
    3. Điều chỉnh âm lượng: giọng đọc lớn, nhạc nền nhỏ
    
    Args:
        input_path: đường dẫn file .wav gốc (chỉ có giọng đọc)
        bg_choice: tên file nhạc nền hoặc None
        narration_boost_db: tăng âm lượng giọng đọc (dB)
    
    Returns:
        đường dẫn file _capcut.wav đã xử lý
    """
    # support input .wav or .flac (or other audio extensions). Output is a FLAC file (_capcut.flac)
    base_noext, _ext = os.path.splitext(input_path)
    timestamp = int(time.time())
    output_path = base_noext + f"_capcut.flac"
    
    # Nếu file đã tồn tại, dùng luôn
    if os.path.exists(output_path):
        send_discord_message("🎧 Dùng cache audio đã xử lý: %s", output_path)
        return output_path

    send_discord_message("⚙️ Đang xử lý audio cho video (tăng tốc + filter)...")
    
    # Tìm nhạc nền nếu có
    chosen_bg = None
    try:
        discord_bot_bgaudio = os.path.join(BASE_DIR, "discord-bot", "bgaudio")
        if os.path.isdir(discord_bot_bgaudio):
            bgaudio_dir = discord_bot_bgaudio
        else:
            bgaudio_dir = os.path.join(OUTPUT_DIR, "bgaudio")
        
        bg_files = []
        if os.path.isdir(bgaudio_dir):
            for f in os.listdir(bgaudio_dir):
                if f.lower().endswith(".wav"):
                    bg_files.append(os.path.join(bgaudio_dir, f))
        
        # Nếu có yêu cầu nhạc nền cụ thể
        if bg_choice:
            candidate = os.path.join(bgaudio_dir, os.path.basename(bg_choice))
            if os.path.exists(candidate):
                bg_files = [candidate]
            else:
                send_discord_message("⚠️ Không tìm thấy nhạc nền: %s. Dùng ngẫu nhiên.", candidate)

        if bg_files:
            chosen_bg = bg_files[0] if len(bg_files) == 1 else random.choice(bg_files)
    except Exception as e:
        send_discord_message(f"⚠️ Lỗi khi tìm nhạc nền: {e}")
        chosen_bg = None

    # If caller requested Gemini-specific processing, delegate to gemini variant
    if use_gemini:
        return prepare_audio_for_video_gemini(input_path, bg_choice, narration_boost_db)

    # Xây dựng filter ffmpeg
    if chosen_bg and os.path.exists(chosen_bg):
        # CÓ NHẠC NỀN - mix bằng ffmpeg hoàn toàn
        send_discord_message(f"🎵 Mix với nhạc nền: {os.path.basename(chosen_bg)}")
        
        # Filter chain:
        # [0:a] = narration (boost + process)
        # [1:a] = background (loop + lower volume)
        # Mix cả 2
        #   f"[0:a]rubberband=pitch=1.00,atempo=1.45,highpass=f=250,treble=g=5"
        filter_complex = (
            f"[0:a]atempo=1.45,"
            f"volume={narration_boost_db}dB[narration];"
            f"[1:a]aloop=loop=-1:size=2e+09,volume=-14dB[bg];"
            f"[narration][bg]amix=inputs=2:duration=first:dropout_transition=0[out]"
        )
        
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,      # [0] narration
            "-i", chosen_bg,        # [1] background
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:a", "flac",
            output_path
        ]
        print(cmd);
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            send_discord_message("✅ Audio đã xử lý + nhạc nền: %s", output_path)
            return output_path
        except subprocess.CalledProcessError as e:
            send_discord_message(f"⚠️ Lỗi khi mix nhạc nền: {e.stderr.decode()}")
            # Fallback: xử lý không có nhạc nền
            chosen_bg = None
    
    if not chosen_bg:
        # KHÔNG CÓ NHẠC NỀN - chỉ xử lý giọng đọc
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-filter:a", 
            f"atempo=1.45,volume={narration_boost_db}dB",
            "-c:a", "flac",
            output_path,
        ]    
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            send_discord_message("✅ Audio đã xử lý (không có nhạc nền): %s", output_path)
            return output_path
        except subprocess.CalledProcessError as e:
            send_discord_message(f"❌ Lỗi khi xử lý audio: {e.stderr.decode()}")
            raise

def enhance_audio_gemini(input_path: str) -> str:
    """
    Dùng ffmpeg để tăng tốc và tinh chỉnh giọng giống CapCut.
    """
    base_noext, _ = os.path.splitext(input_path)
    output_path = base_noext + "_capcut.flac"
    if os.path.exists(output_path):
        send_discord_message("🎧 Dùng cache audio đã chỉnh: %s", output_path)
        return output_path

    send_discord_message("⚙️ Đang tăng tốc và lọc âm thanh bằng ffmpeg...")
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter:a", "atempo=1.5",
        "-c:a", "flac",
        output_path
    ]
    subprocess.run(cmd, check=True)
    send_discord_message("✅ Đã tạo audio đã chỉnh tốc: %s", output_path)
    return output_path


def prepare_audio_for_video_gemini(input_path: str, bg_choice: str | None = None, narration_boost_db: float = 6.0) -> str:
    """
    Prepare audio for Gemini flow.

    Applies the requested Gemini-style voice transform to the narration using:
      asetrate=44100*0.65,aresample=44100,atempo=1.4

    If a background choice is provided, the background will be looped and
    mixed without the voice transform applied to the background (background
    kept as-is except volume attenuation). The narration gets volume boost
    by `narration_boost_db`.
    """
    base_noext, _ = os.path.splitext(input_path)
    timestamp = int(time.time())
    output_path = base_noext + f"_capcut.flac"

    if os.path.exists(output_path):
        send_discord_message("🎧 Dùng cache Gemini audio đã xử lý: %s", output_path)
        return output_path

    send_discord_message("⚙️ (Gemini) Đang xử lý audio: áp dụng asetrate/aresample/atempo + mix nhạc nền nếu có...")

    # Find background similar to standard function
    chosen_bg = None
    try:
        discord_bot_bgaudio = os.path.join(BASE_DIR, "discord-bot", "bgaudio")
        if os.path.isdir(discord_bot_bgaudio):
            bgaudio_dir = discord_bot_bgaudio
        else:
            bgaudio_dir = os.path.join(OUTPUT_DIR, "bgaudio")

        bg_files = []
        if os.path.isdir(bgaudio_dir):
            for f in os.listdir(bgaudio_dir):
                if f.lower().endswith(".wav"):
                    bg_files.append(os.path.join(bgaudio_dir, f))

        # specific choice
        if bg_choice:
            candidate = os.path.join(bgaudio_dir, os.path.basename(bg_choice))
            if os.path.exists(candidate):
                bg_files = [candidate]
            else:
                send_discord_message("⚠️ (Gemini) Không tìm thấy nhạc nền: %s. Dùng ngẫu nhiên.", candidate)

        if bg_files:
            chosen_bg = bg_files[0] if len(bg_files) == 1 else random.choice(bg_files)
    except Exception as e:
        send_discord_message(f"⚠️ (Gemini) Lỗi khi tìm nhạc nền: {e}")
        chosen_bg = None

    # If we have a background, mix using filter_complex and only apply the voice
    # transform to the narration stream. Background is looped and attenuated.
    if chosen_bg and os.path.exists(chosen_bg):
        send_discord_message("🎵 (Gemini) Mix với nhạc nền: %s", os.path.basename(chosen_bg))

        filter_complex = (
            f"[0:a]asetrate=44100*0.6,aresample=44100,atempo=1.4,"
            f"highpass=f=80,lowpass=f=8000,bass=g=6:f=120,treble=g=-6:f=6000,"
            f"dynaudnorm=f=150:g=15,volume=6dB[narr];"
            f"[1:a]aloop=loop=-1:size=2000000000,volume=-14dB[bg];"
            f"[narr][bg]amix=inputs=2:duration=first:dropout_transition=0[out]"
        )
        print(filter_complex)
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-i", chosen_bg,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:a", "flac",
            output_path
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
            send_discord_message("✅ (Gemini) Audio đã xử lý + nhạc nền: %s", output_path)
            return output_path
        except subprocess.CalledProcessError as e:
            send_discord_message(f"⚠️ (Gemini) Lỗi khi mix nhạc nền: {e.stderr.decode()}")
            chosen_bg = None

    # No background or mixing failed: only apply narration transform
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter:a", "asetrate=44100*0.65,aresample=44100,atempo=1.4,volume=%sdB" % narration_boost_db,
        "-c:a", "flac",
        output_path
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        send_discord_message("✅ (Gemini) Audio đã xử lý (không có nhạc nền): %s", output_path)
        return output_path
    except subprocess.CalledProcessError as e:
        send_discord_message(f"❌ (Gemini) Lỗi khi xử lý audio: {e.stderr.decode()}")
        raise
def prepare_audio_for_video_gemini_male(input_path: str, bg_choice: str | None = None, narration_boost_db: float = 6.0) -> str:
    """
    Prepare audio for Gemini flow.

    Applies the requested Gemini-style voice transform to the narration using:
      asetrate=44100*0.65,aresample=44100,atempo=1.4

    If a background choice is provided, the background will be looped and
    mixed without the voice transform applied to the background (background
    kept as-is except volume attenuation). The narration gets volume boost
    by `narration_boost_db`.
    """
    base_noext, _ = os.path.splitext(input_path)
    timestamp = int(time.time())
    output_path = base_noext + f"_capcut.flac"

    if os.path.exists(output_path):
        send_discord_message("🎧 Dùng cache Gemini audio đã xử lý: %s", output_path)
        return output_path

    send_discord_message("⚙️ (Gemini) Đang xử lý audio: áp dụng asetrate/aresample/atempo + mix nhạc nền nếu có...")

    # Find background similar to standard function
    chosen_bg = None
    try:
        discord_bot_bgaudio = os.path.join(BASE_DIR, "discord-bot", "bgaudio")
        if os.path.isdir(discord_bot_bgaudio):
            bgaudio_dir = discord_bot_bgaudio
        else:
            bgaudio_dir = os.path.join(OUTPUT_DIR, "bgaudio")

        bg_files = []
        if os.path.isdir(bgaudio_dir):
            for f in os.listdir(bgaudio_dir):
                if f.lower().endswith(".wav"):
                    bg_files.append(os.path.join(bgaudio_dir, f))

        # specific choice
        if bg_choice:
            candidate = os.path.join(bgaudio_dir, os.path.basename(bg_choice))
            if os.path.exists(candidate):
                bg_files = [candidate]
            else:
                send_discord_message("⚠️ (Gemini) Không tìm thấy nhạc nền: %s. Dùng ngẫu nhiên.", candidate)

        if bg_files:
            chosen_bg = bg_files[0] if len(bg_files) == 1 else random.choice(bg_files)
    except Exception as e:
        send_discord_message(f"⚠️ (Gemini) Lỗi khi tìm nhạc nền: {e}")
        chosen_bg = None

    # If we have a background, mix using filter_complex and only apply the voice
    # transform to the narration stream. Background is looped and attenuated.
    if chosen_bg and os.path.exists(chosen_bg):
        send_discord_message("🎵 (Gemini) Mix với nhạc nền: %s", os.path.basename(chosen_bg))

        filter_complex="""
            [0:a]asetrate=38000*0.65,aresample=48000,
                atempo=1.35,
                lowpass=f=4500,highpass=f=80,
                volume=5dB[narr];

            [1:a]aloop=loop=-1:size=2000000000,volume=-14dB[bg];

            [narr][bg]amix=inputs=2:duration=first:dropout_transition=0[out]
            """
        print(filter_complex)
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-i", chosen_bg,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:a", "flac",
            output_path
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True)
            send_discord_message("✅ (Gemini) Audio đã xử lý + nhạc nền: %s", output_path)
            return output_path
        except subprocess.CalledProcessError as e:
            send_discord_message(f"⚠️ (Gemini) Lỗi khi mix nhạc nền: {e.stderr.decode()}")
            chosen_bg = None

    # No background or mixing failed: only apply narration transform
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter:a", "asetrate=38000*0.7,aresample=48000,atempo=1.38,lowpass=f=4500,highpass=f=80,volume=%sdB" % narration_boost_db,
        "-c:a", "flac",
        output_path
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        send_discord_message("✅ (Gemini) Audio đã xử lý (không có nhạc nền): %s", output_path)
        return output_path
    except subprocess.CalledProcessError as e:
        send_discord_message(f"❌ (Gemini) Lỗi khi xử lý audio: {e.stderr.decode()}")
        raise
def extract_domain_structure(url): 
    """Tự nhận biết domain và chọn cấu trúc phù hợp""" 
    domain = re.search(r"https?://([^/]+)/", url).group(1) 
    if "metruyenhot" in domain: 
        return {"content_selector": "div.chapter-c", "next_text": "Tiếp"} 
    elif "truyenfull" in domain: 
        return {"content_selector": "div.chapter-c", "next_text": "Chương tiếp"} 
    else: return {"content_selector": "div.chapter", "next_text": "Next"}


def url_hash(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()



def is_summary_in_content(summary_text: str, content_text: str, threshold: float = 0.7) -> bool:
    """
    Kiểm tra xem văn án có nằm trong đoạn đầu của nội dung không.
    
    Args:
        summary_text: Văn án
        content_text: Nội dung truyện
        threshold: Ngưỡng tương đồng (0.0 - 1.0)
    
    Returns:
        True nếu văn án đã có trong nội dung, False nếu chưa có
    """
    if not summary_text or not content_text:
        return False
    
    # Chuẩn hóa: loại bỏ khoảng trắng thừa, xuống dòng, chuyển về lowercase
    def normalize(text):
        import re
        text = re.sub(r'\s+', ' ', text.strip().lower())
        # Loại bỏ các ký tự đặc biệt
        text = re.sub(r'[^\w\s]', '', text)
        return text
    
    summary_norm = normalize(summary_text)
    
    # Lấy phần đầu của content tương ứng với độ dài văn án + 20% buffer
    content_prefix_len = int(len(summary_norm) * 1.2)
    content_prefix = normalize(content_text[:content_prefix_len * 2])  # *2 vì content chưa normalize
    
    # Kiểm tra xem có bao nhiêu từ trong summary xuất hiện trong content prefix
    summary_words = set(summary_norm.split())
    content_words = set(content_prefix.split())
    
    if not summary_words:
        return False
    
    # Tính tỷ lệ từ trong summary có trong content
    matching_words = summary_words.intersection(content_words)
    similarity = len(matching_words) / len(summary_words)
    
    send_discord_message(f"🔍 Kiểm tra văn án trong nội dung: {similarity:.1%} tương đồng")
    
    return similarity >= threshold






 
def wave_file(filename, pcm, channels=1, rate=24000, sample_width=2):
   with wave.open(filename, "wb") as wf:
      wf.setnchannels(channels)
      wf.setsampwidth(sample_width)
      wf.setframerate(rate)
      wf.writeframes(pcm)
def convert_to_wav(audio_data: bytes, mime_type: str) -> bytes:
    """Generates a WAV file header for the given audio data and parameters.

    Args:
        audio_data: The raw audio data as a bytes object.
        mime_type: Mime type of the audio data.

    Returns:
        A bytes object representing the WAV file header.
    """
    parameters = parse_audio_mime_type(mime_type)
    bits_per_sample = parameters["bits_per_sample"]
    sample_rate = parameters["rate"]
    num_channels = 1
    data_size = len(audio_data)
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + data_size  # 36 bytes for header fields before data chunk size

    # http://soundfile.sapp.org/doc/WaveFormat/

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",          # ChunkID
        chunk_size,       # ChunkSize (total file size - 8 bytes)
        b"WAVE",          # Format
        b"fmt ",          # Subchunk1ID
        16,               # Subchunk1Size (16 for PCM)
        1,                # AudioFormat (1 for PCM)
        num_channels,     # NumChannels
        sample_rate,      # SampleRate
        byte_rate,        # ByteRate
        block_align,      # BlockAlign
        bits_per_sample,  # BitsPerSample
        b"data",          # Subchunk2ID
        data_size         # Subchunk2Size (size of audio data)
    )
    return header + audio_data


def _write_concat_list(parts: list, list_path: str):
    """Write an ffmpeg concat list file from a list of absolute paths."""
    os.makedirs(os.path.dirname(list_path), exist_ok=True)
    with open(list_path, 'w', encoding='utf-8') as f:
        for p in parts:
            if not p:
                continue
            if not os.path.exists(p):
                # skip missing entries; caller should have filtered but be defensive
                send_discord_message("⚠️ Bỏ qua file không tồn tại khi tạo danh sách concat: %s", p)
                continue
            f.write(f"file '{os.path.abspath(p)}'\n")


def _concat_audio_from_list(concat_list_path: str, output_path: str):
    """Concatenate audio files listed in `concat_list_path` into `output_path` using ffmpeg.

    Raises subprocess.CalledProcessError on failure.
    """
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list_path,
        "-ar", "24000",
        "-ac", "1",
        "-b:a", "192k",
        output_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _create_flac_copy(input_path: str, out_flac: str):
    """Create a FLAC copy from `input_path` to `out_flac` using ffmpeg.

    Raises subprocess.CalledProcessError on failure.
    """
    cmd = ["ffmpeg", "-y", "-i", input_path, "-c:a", "flac", out_flac]
    subprocess.run(cmd, check=True, capture_output=True)


def combine_audio_files(summary_file: str, content_file: str, output_file: str) -> str:
    """Concatenate `summary_file` then `content_file` into `output_file` using ffmpeg concat.

    This helper is intentionally small and raises subprocess.CalledProcessError
    if ffmpeg fails so callers can handle/report the error.
    """
    parts = []
    if summary_file and os.path.exists(summary_file):
        parts.append(summary_file)
    if content_file and os.path.exists(content_file):
        parts.append(content_file)
    if not parts:
        raise RuntimeError("No input audio files to combine")

    concat_list = output_file + ".concat_list.txt"
    _write_concat_list(parts, concat_list)
    try:
        _concat_audio_from_list(concat_list, output_file)
        try:
            os.remove(concat_list)
        except Exception as e:
            _report_and_ignore(e, "ignored")
        return output_file
    except subprocess.CalledProcessError:
        # bubble up; caller will log/handle
        raise

def parse_audio_mime_type(mime_type: str) -> dict[str, int | None]:
    """Parses bits per sample and rate from an audio MIME type string.

    Assumes bits per sample is encoded like "L16" and rate as "rate=xxxxx".

    Args:
        mime_type: The audio MIME type string (e.g., "audio/L16;rate=24000").

    Returns:
        A dictionary with "bits_per_sample" and "rate" keys. Values will be
        integers if found, otherwise None.
    """
    bits_per_sample = 16
    rate = 24000

    # Extract rate from parameters
    parts = mime_type.split(";")
    for param in parts: # Skip the main type part
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate_str = param.split("=", 1)[1]
                rate = int(rate_str)
            except (ValueError, IndexError):
                # Handle cases like "rate=" with no value or non-integer value
                pass # Keep rate as default
        elif param.startswith("audio/L"):
            try:
                bits_per_sample = int(param.split("L", 1)[1])
            except (ValueError, IndexError):
                pass # Keep bits_per_sample as default if conversion fails

    return {"bits_per_sample": bits_per_sample, "rate": rate}
def save_binary_file(file_name, data):
    f = open(file_name, "wb")
    f.write(data)
    f.close()
    send_discord_message(f"File saved to to: {file_name}")


def _get_dir_size_bytes(path: str) -> int:
    """Return total size (bytes) of files under path."""
    total = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            try:
                fp = os.path.join(root, f)
                total += os.path.getsize(fp)
            except Exception as e:
                _report_and_ignore(e, "ignored")
    return total


def _human(n: int) -> str:
    # human-readable
    for unit in ['B','KB','MB','GB','TB']:
        if n < 1024.0:
            return f"{n:3.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PB"
def _prune_old_videos(dir_path: str, older_than_days: int = 3, max_freed_bytes: int | None = None) -> dict:
    """Delete video files older than `older_than_days` in dir_path. Optionally stop when freed >= max_freed_bytes.

    Returns report dict {deleted_count, freed_bytes, deleted_files}.
    """
    exts = {'.mp4', '.mkv', '.mov', '.avi', '.webm'}
    cutoff = time.time() - older_than_days * 86400
    files = []
    for root, dirs, filenames in os.walk(dir_path):
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in exts:
                fp = os.path.join(root, fn)
                try:
                    m = os.path.getmtime(fp)
                except Exception:
                    m = 0
                if m < cutoff:
                    try:
                        size = os.path.getsize(fp)
                    except Exception:
                        size = 0
                    files.append((m, fp, size))

    files.sort()  # oldest first
    deleted = []
    total_freed = 0
    for m, fp, size in files:
        try:
            os.remove(fp)
            deleted.append(fp)
            total_freed += size
        except Exception:
            continue
        if max_freed_bytes and total_freed >= max_freed_bytes:
            break

    return {"deleted_count": len(deleted), "freed_bytes": total_freed, "deleted_files": deleted}


def _keep_n_recent(dir_path: str, n: int = 10) -> dict:
    """Keep only n most recent video files in dir_path (recursive). Delete older ones.

    Return report dict.
    """
    exts = {'.mp4', '.mkv', '.mov', '.avi', '.webm'}
    files = []
    for root, dirs, filenames in os.walk(dir_path):
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in exts:
                fp = os.path.join(root, fn)
                try:
                    m = os.path.getmtime(fp)
                    size = os.path.getsize(fp)
                except Exception:
                    m = 0
                    size = 0
                files.append((m, fp, size))

    if not files:
        return {"kept": 0, "deleted": 0, "freed_bytes": 0}

    files.sort(reverse=True)  # newest first
    keep = files[:n]
    to_delete = files[n:]
    deleted = []
    freed = 0
    for m, fp, size in to_delete:
        try:
            os.remove(fp)
            deleted.append(fp)
            freed += size
        except Exception:
            continue

    return {"kept": len(keep), "deleted": len(deleted), "freed_bytes": freed, "deleted_files": deleted}


@app.post('/maintenance/trim_storage')
async def maintenance_trim_storage(
    outputs_dir: str | None = Query(None, description="Path to outputs dir; default uses server OUTPUT_DIR"),
    project_root: str | None = Query(None, description="Path to project root; default uses BASE_DIR"),
    outputs_threshold_gb: float = Query(70.0, description="If outputs dir > this GB then prune old videos (default 70GB)"),
    project_limit_gb: float = Query(100.0, description="Hard cap for total project size (default 100GB)"),
    keep_cache_videos: int = Query(10, description="Keep this many most-recent files in video cache (default 10)"),
):
    """Maintenance endpoint:
    - If outputs dir > outputs_threshold_gb, delete video files older than 3 days until under threshold.
    - Trim `VIDEO_CACHE_DIR` to keep only `keep_cache_videos` most recent files.
    - Ensure total project size <= project_limit_gb by deleting oldest files under outputs if needed.
    """
    od = outputs_dir or OUTPUT_DIR
    pr = project_root or BASE_DIR

    report = {"initial": {}, "actions": []}

    try:
        out_bytes = _get_dir_size_bytes(od)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"failed to stat outputs dir: {e}"})

    report["initial"]["outputs_bytes"] = out_bytes
    report["initial"]["outputs_human"] = _human(out_bytes)

    outputs_threshold_bytes = int(outputs_threshold_gb * 1024 ** 3)
    project_limit_bytes = int(project_limit_gb * 1024 ** 3)

    # 1) If outputs too large -> prune >3 days old
    if out_bytes > outputs_threshold_bytes:
        send_discord_message(f"⚠️ Outputs size {_human(out_bytes)} > {outputs_threshold_gb}GB, pruning old videos...")
        pr_report = _prune_old_videos(od, older_than_days=3)
        report["actions"].append({"prune_old_videos": pr_report})
        out_bytes = _get_dir_size_bytes(od)
        report["after_prune_bytes"] = out_bytes
        report["after_prune_human"] = _human(out_bytes)

    # 2) Keep only N recent in video cache
    try:
        cache_report = _keep_n_recent(VIDEO_CACHE_DIR, keep_cache_videos)
        report["actions"].append({"trim_video_cache": cache_report})
    except Exception as e:
        report["actions"].append({"trim_video_cache_error": str(e)})

    # 3) Ensure project size under hard limit
    total_project = _get_dir_size_bytes(pr)
    report["initial"]["project_bytes"] = total_project
    report["initial"]["project_human"] = _human(total_project)

    if total_project > project_limit_bytes:
        send_discord_message(f"🚨 Project size {_human(total_project)} > {project_limit_gb}GB, trimming oldest videos under outputs...")
        # delete oldest files under outputs until under limit (targeting half the overage to be safe)
        over = total_project - project_limit_bytes
        # build list of candidate files (videos) sorted by mtime oldest first
        exts = {'.mp4', '.mkv', '.mov', '.avi', '.webm'}
        candidates = []
        for root, dirs, files in os.walk(od):
            for fn in files:
                if os.path.splitext(fn)[1].lower() in exts:
                    fp = os.path.join(root, fn)
                    try:
                        m = os.path.getmtime(fp)
                        s = os.path.getsize(fp)
                        candidates.append((m, fp, s))
                    except Exception:
                        continue
        candidates.sort()  # oldest first
        freed = 0
        deleted = []
        for m, fp, s in candidates:
            try:
                os.remove(fp)
                deleted.append(fp)
                freed += s
            except Exception:
                continue
            total_project -= s
            if total_project <= project_limit_bytes:
                break

        report["actions"].append({"forced_prune_project": {"deleted_count": len(deleted), "freed_bytes": freed, "deleted_files": deleted}})
        report["final_project_bytes"] = total_project
        report["final_project_human"] = _human(total_project)

    return JSONResponse(content=report)


@app.on_event("startup")
async def _start_maintenance_scheduler():
    """Start a background task that runs maintenance_trim_storage() daily at 02:00 local time."""
    async def _scheduler():
        while True:
            try:
                now = datetime.now()
                # next 2:00
                nxt = now.replace(hour=2, minute=0, second=0, microsecond=0)
                if nxt <= now:
                    nxt = nxt + timedelta(days=1)
                delay = (nxt - now).total_seconds()
                send_discord_message(f"🕒 Maintenance scheduler sleeping for {int(delay)}s until next 02:00")
                await asyncio.sleep(delay)
                try:
                    send_discord_message("🛠️ Running scheduled maintenance_trim_storage()")
                    await maintenance_trim_storage()
                except Exception as e:
                    send_discord_message(f"⚠️ Scheduled maintenance failed: {e}")
                # sleep 1 second before next loop (next iteration will compute next 2:00)
                await asyncio.sleep(1)
            except asyncio.CancelledError as e:
                logger.info("Maintenance scheduler cancelled: %s", e)
                break
            except Exception as e:
                send_discord_message(f"⚠️ Maintenance scheduler error: {e}")
                # wait a bit before retrying
                await asyncio.sleep(60)

    # start background task
    asyncio.create_task(_scheduler())
def clean_text(s: str):
    """Xóa toàn bộ ký tự điều khiển, bao gồm cả xuống dòng và tab."""
     # Loại bỏ tất cả ký tự ASCII từ 0-31 và 127 (non-printable)
    return re.sub(r"[\x00-\x1F\x7F]", " ", s).strip()

    
# generate_audio_Gemini provided by `tts.py`
# `tts.py` provides canonical TTS functions; top-level imports are used.

def download_video_url(url: str, output="temp_video.mp4", retries=3, delay=2, target_duration: float | None = None, fail_fast: bool = False):
    """
    Tải video YouTube với yt-dlp, thử lại tối đa `retries` lần nếu lỗi.

    If download succeeds the full downloaded file is saved into VIDEO_CACHE_DIR.
    If target_duration is provided, this function will produce an output file at `output`
    that is exactly `target_duration` seconds long by cutting/looping as needed.

    If download ultimately fails after retries, the function will attempt to build a clip
    from random cached videos to match target_duration (or a default short clip).
    """
    attempt = 0
    last_exception = None
    # temporary download target to avoid overwriting caller's expected filename
    tmp_full = output + ".download.full.mp4"

    while attempt < retries:
        try:
            send_discord_message("📥 Đang tải video YouTube (lần %d/%d): %s", attempt+1, retries, url)
            start="00:00" 
            end="01:00"
            # Build yt-dlp command with Linux-safe cookie handling
            cmd = [
                "yt-dlp",
                "-f", "bestvideo+bestaudio/best",
                "-o", tmp_full,
                "--merge-output-format", "mp4",
                "--quiet",
                "--no-warnings"
            ]
            # Only add cookies if file exists (common Linux failure)
            try:
                if os.path.exists("youtube_cookies.txt"):
                    cmd[1:1] = ["--cookies", "youtube_cookies.txt"]
            except Exception as e:
                _report_and_ignore(e, "ignored")
            try:
                print(" ".join(cmd + [url]))
                subprocess.run(cmd + [url], check=True)
            except (subprocess.CalledProcessError, FileNotFoundError) as ytdlp_err:
                # Fallback: try Python API of yt_dlp to be more portable on Linux
                try:
                    send_discord_message(f"⚠️ yt-dlp CLI lỗi, chuyển sang API: {ytdlp_err}")
                    ydl_opts = {
                        "format": "bestvideo+bestaudio/best",
                        "outtmpl": tmp_full,
                        "merge_output_format": "mp4",
                        "quiet": True,
                        "no_warnings": True,
                    }
                    if os.path.exists("youtube_cookies.txt"):
                        ydl_opts["cookiefile"] = "youtube_cookies.txt"
                    with YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                except Exception as api_err:
                    # Propagate to retry loop
                    raise api_err
            # If file exists, move it into cache and create desired clip
            if os.path.exists(tmp_full):
                safe_name = url_hash(url) + "_" + str(int(time.time())) + ".mp4"
                cached_full = os.path.join(VIDEO_CACHE_DIR, safe_name)
                shutil.move(tmp_full, cached_full)
                send_discord_message("✅ Hoàn tất tải video & lưu cache: %s", cached_full)
                # Create a TikTok-optimized processed copy (crop center to 9:16 and scale to 1080x1920)
                # Save processed cached version to avoid repeated work.
                proc_name = os.path.splitext(safe_name)[0] + "_tiktok.mp4"
                processed_cached = os.path.join(VIDEO_CACHE_DIR, proc_name)

                # If target_duration provided, create a trimmed source first to avoid processing unnecessarily long files
                source_for_processing = cached_full
                tmp_trim = None
                try:
                    if target_duration and target_duration > 0:
                        tmp_trim = cached_full + f".trim_{int(target_duration)}.mp4"
                        _create_clip_from_source(cached_full, tmp_trim, target_duration)
                        source_for_processing = tmp_trim

                    # If a processed cached file exists and is long enough, reuse it
                    reuse = False
                    if os.path.exists(processed_cached):
                        try:
                            _, _, existing_dur = get_media_info(processed_cached)
                            if not target_duration or existing_dur >= (target_duration - 1.0):
                                reuse = True
                                send_discord_message("♻️ Dùng processed cache: %s", processed_cached)
                        except Exception:
                            reuse = False

                    if reuse:
                        # Reuse processed cached file directly (avoid copying to outputs to prevent duplication)
                        send_discord_message("♻️ Trả về processed cache trực tiếp: %s", processed_cached)
                        # Remove raw cached_full to save space (if present)
                        send_discord_message("🗑️ Xóa video gốc để tiết kiệm dung lượng cache...")
                        try:
                            if os.path.exists(cached_full):
                                os.remove(cached_full)
                                send_discord_message("✅ Đã xóa video gốc: %s", cached_full)
                        except Exception as ex:
                            send_discord_message(f"⚠️ Không xóa được video gốc: {ex}")
                        
                        # Also delete tmp_trim if it exists
                        try:
                            if tmp_trim and os.path.exists(tmp_trim):
                                os.remove(tmp_trim)
                                tmp_trim = None  # Mark as cleaned
                        except Exception as e:
                            _report_and_ignore(e, "ignored")
                        return processed_cached

                    # Probe source to compute crop
                    try:
                        w, h, _ = get_media_info(source_for_processing)
                        if not w or not h:
                            raise RuntimeError("Không đọc được kích thước video")
                    except Exception:
                        # fallback: copy cached full -> output
                        try:
                            shutil.copy(cached_full, output)
                            return output
                        except Exception:
                            return cached_full

                    aspect = float(w) / float(h)
                    target = 9.0 / 16.0
                    if aspect > target:
                        # video is wider than 9:16 -> crop width center
                        new_w = int(h * target)
                        x_offset = (w - new_w) // 2
                        crop_filter = f"crop={new_w}:{h}:{x_offset}:0"
                    else:
                        # video is taller -> crop height center
                        new_h = int(w / target)
                        y_offset = (h - new_h) // 2
                        crop_filter = f"crop={w}:{new_h}:0:{y_offset}"

                    # Build ffmpeg command to produce processed video (preserve original size)
                    ff_out = processed_cached
                    cmd = ["ffmpeg", "-y", "-i", source_for_processing]
                    cmd.extend(_preferred_video_encode_args())
                    cmd.extend(['-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', ff_out])

                    send_discord_message("🔧 Tạo bản TikTok-optimized: %s", ff_out)
                    try:
                        subprocess.run(cmd, check=True, capture_output=True)
                        # Processing succeeded: delete original raw cached file to avoid duplication and return processed cache path
                        send_discord_message("🗑️ Xóa video gốc để tiết kiệm dung lượng cache...")
                        try:
                            if os.path.exists(cached_full):
                                os.remove(cached_full)
                                send_discord_message("✅ Đã xóa video gốc: %s", cached_full)
                        except Exception as ex:
                            send_discord_message(f"⚠️ Không xóa được video gốc: {ex}")
                        
                        # Also delete tmp_trim if it exists
                        try:
                            if tmp_trim and os.path.exists(tmp_trim):
                                os.remove(tmp_trim)
                                tmp_trim = None  # Mark as cleaned
                        except Exception as e:
                            _report_and_ignore(e, "ignored")
                        return ff_out
                    except subprocess.CalledProcessError as e:
                        send_discord_message("⚠️ FFmpeg processing failed, returning cached full: %s", e)
                        # Return the raw cached download; caller can decide what to do
                        return cached_full

                finally:
                    # cleanup any temporary trim file
                    try:
                        if tmp_trim and os.path.exists(tmp_trim):
                            os.remove(tmp_trim)
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
            raise RuntimeError("Không tạo được file sau khi tải")

        except Exception as e:
            last_exception = e
            attempt += 1
            send_discord_message("⚠️ Tải video thất bại (lần %d/%d): %s", attempt, retries, e)
            time.sleep(delay)

    # All retries exhausted
    send_discord_message("❌ Tải video không thành công sau %d lần: %s", retries, url)
    if fail_fast:
        # Immediately abort and propagate last exception
        send_discord_message("⛔ fail_fast active: dừng tiến trình do tải video thất bại: %s", url)
        if last_exception:
            raise last_exception
        else:
            raise RuntimeError(f"Tải video không thành công: {url}")

    # Otherwise fallback to cache behavior
    try:
        cached_files = [os.path.join(VIDEO_CACHE_DIR, f) for f in os.listdir(VIDEO_CACHE_DIR) if f.lower().endswith('.mp4')]
        if not cached_files:
            raise RuntimeError("Không có video trong cache để dùng thay thế")

        if not target_duration or target_duration <= 0:
            # produce a default 30s clip
            src = random.choice(cached_files)
            _create_clip_from_source(src, output, 30)
            return output

        # Build concatenated random segments to reach target_duration
        parts = []
        remaining = float(target_duration)
        tmp_dir = tempfile.mkdtemp(prefix="video_fill_")
        try:
            part_idx = 0
            while remaining > 0.5:
                src = random.choice(cached_files)
                seg_len = min(remaining, max(5.0, min(remaining, random.uniform(10.0, min(60.0, remaining)))))
                part_idx += 1
                part_path = os.path.join(tmp_dir, f"part_{part_idx}.mp4")
                _create_clip_from_source(src, part_path, seg_len)
                parts.append(part_path)
                remaining -= seg_len

            # concat parts
            concat_list = os.path.join(tmp_dir, "concat_list.txt")
            with open(concat_list, 'w', encoding='utf-8') as f:
                for p in parts:
                    f.write(f"file '{os.path.abspath(p)}'\n")

            cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list, '-c', 'copy', output]
            subprocess.run(cmd, check=True)

            # Trim to exact duration in case of small rounding issues
            tmp_trim = output + '.tmp'
            cmd_trim = ['ffmpeg', '-y', '-i', output, '-t', str(target_duration), '-c', 'copy', tmp_trim]
            subprocess.run(cmd_trim, check=True)
            shutil.move(tmp_trim, output)
            try:
                shutil.rmtree(tmp_dir)
            except Exception as e:
                _report_and_ignore(e, "ignored")
            send_discord_message("✅ Tạo clip từ cache hoàn tất: %s", output)
            return output

        except Exception:
            try:
                shutil.rmtree(tmp_dir)
            except Exception as e:
                _report_and_ignore(e, "ignored")
            raise

    except Exception as e:
        send_discord_message("🚫 Không có giải pháp thay thế: %s", e)
        raise RuntimeError(f"Tải video không thành công và không có cache: {e}") from last_exception


def _create_clip_from_source(src_path: str, out_path: str, desired_duration: float):
    """Create a clip of length desired_duration (seconds) from src_path by picking a random start.
    If src shorter than desired_duration, will loop it using -stream_loop then trim.
    """
    if not os.path.exists(src_path):
        raise FileNotFoundError(src_path)

    w, h, dur = get_media_info(src_path)
    dur = float(dur)
    desired = float(desired_duration)

    if dur >= desired:
        max_start = max(0.0, dur - desired - 1.0)
        start = random.uniform(0, max_start) if max_start > 0 else 0
        cmd = ['ffmpeg', '-y', '-ss', str(start), '-i', src_path, '-t', str(desired), '-c', 'copy', out_path]
        subprocess.run(cmd, check=True)
        return

    loops = int(math.ceil(desired / dur))
    cmd = ['ffmpeg', '-y', '-stream_loop', str(loops - 1), '-i', src_path, '-t', str(desired), '-c', 'copy', out_path]
    subprocess.run(cmd, check=True)
   
@app.get("/sample_random_mix")
async def sample_random_mix(count: int = Query(1, description="How many samples to generate (default 1)")):
    """Return one or more sampled `random_mix` parameter sets without invoking the AI.

    Stores the sampled params into `tasks` under a generated `task_id` with
    `status='sampled'` so the caller can later decide to proceed to full
    generation using `/generate_random_mix_preview` (or another flow).
    """
    import random
    from story_generator import StoryPrompts

    samples = []
    tasks = load_tasks()

    for _ in range(max(1, int(count))):
        request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        the_loai_chinh = random.choice(StoryPrompts.RANDOM_MIX['the_loai_chinh'])
        the_loai_phu = random.choice(StoryPrompts.RANDOM_MIX['the_loai_phu'])
        nhan_vat = random.choice(StoryPrompts.RANDOM_MIX['nhan_vat'])
        boi_canh = random.choice(StoryPrompts.RANDOM_MIX['boi_canh'])
        mo_tip = random.choice(StoryPrompts.RANDOM_MIX['mo_tip'])


        entry = {
            'task_id': request_id,
            'status': 'sampled',
            'genre': 'random_mix',
            'the_loai_chinh': the_loai_chinh,
            'the_loai_phu': the_loai_phu,
            'nhan_vat': nhan_vat,
            'boi_canh': boi_canh,
            'mo_tip': mo_tip,
            'created_at': time.time()
        }

        tasks[request_id] = entry
        samples.append(entry)

    save_tasks(tasks)

    # Provide an example proceed URL for the first sample
    first = samples[0]
    proceed_example = (
        "/generate_random_mix_preview?"
        f"random_main_genre={quote_plus(first['the_loai_chinh'])}"
        f"&random_sub_genre={quote_plus(first['the_loai_phu'])}"
        f"&random_character={quote_plus(first['nhan_vat'])}"
        f"&random_setting={quote_plus(first['boi_canh'])}"
        f"&random_plot_motif={quote_plus(first['mo_tip'])}"
    )

    return {'samples': samples, 'proceed_example': proceed_example}


@app.get("/sample_random_mix_ai")
async def sample_random_mix_ai(
    count: int = Query(1, description="How many AI-selected samples to generate (default 1)"),
    user_idea: str = Query("", description="Ý tưởng của user (VD: 'tình cảm bị phản bội rồi trả thù chồng cũ')")
):
    """Return one or more AI-selected `random_mix` parameter sets.
    
    Uses OpenAI to select coherent combinations based on user's idea or hot trends.
    Stores the sampled params into `tasks` under a generated `task_id` with
    `status='sampled'` so the caller can later decide to proceed to full generation.
    """
    from story_generator import StoryGenerator
    
    samples = []
    tasks = load_tasks()
    
    # Initialize generator
    generator = StoryGenerator(model="gemini-2.5-pro")

    for _ in range(max(1, int(count))):
        request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        
        try:
            # Call AI to select coherent combination with user idea
            selected = generator._ai_select_coherent_combination(user_idea=user_idea.strip())
            
            the_loai_chinh = selected['the_loai_chinh']
            the_loai_phu = selected['the_loai_phu']
            nhan_vat = selected['nhan_vat']
            boi_canh = selected['boi_canh']
            mo_tip = selected['mo_tip']
            ly_do = selected.get('ly_do', 'AI đã chọn kết hợp hợp lý')
            
        except Exception as e:
            # Fallback to random if AI fails
            import random
            from story_generator import StoryPrompts
            
            the_loai_chinh = random.choice(StoryPrompts.RANDOM_MIX['the_loai_chinh'])
            the_loai_phu = random.choice(StoryPrompts.RANDOM_MIX['the_loai_phu'])
            nhan_vat = random.choice(StoryPrompts.RANDOM_MIX['nhan_vat'])
            boi_canh = random.choice(StoryPrompts.RANDOM_MIX['boi_canh'])
            mo_tip = random.choice(StoryPrompts.RANDOM_MIX['mo_tip'])
            ly_do = f"AI failed ({e}), random fallback"

        entry = {
            'task_id': request_id,
            'status': 'sampled',
            'genre': 'random_mix',
            'the_loai_chinh': the_loai_chinh,
            'the_loai_phu': the_loai_phu,
            'nhan_vat': nhan_vat,
            'boi_canh': boi_canh,
            'mo_tip': mo_tip,
            'ai_selected': True,
            'selection_reason': ly_do,
            'user_idea': user_idea.strip() if user_idea.strip() else None,
            'created_at': time.time()
        }

        tasks[request_id] = entry
        samples.append(entry)

    save_tasks(tasks)

    # Provide an example proceed URL for the first sample
    first = samples[0]
    proceed_example = (
        "/generate_random_mix_preview?"
        f"random_main_genre={quote_plus(first['the_loai_chinh'])}"
        f"&random_sub_genre={quote_plus(first['the_loai_phu'])}"
        f"&random_character={quote_plus(first['nhan_vat'])}"
        f"&random_setting={quote_plus(first['boi_canh'])}"
        f"&random_plot_motif={quote_plus(first['mo_tip'])}"
    )



    return {'samples': samples, 'proceed_example': proceed_example, 'ai_selected': True}


@app.post("/generate_full_preview")
async def generate_full_preview(
    random_main_genre: str = Query(None),
    random_sub_genre: str = Query(None),
    random_character: str = Query(None),
    random_setting: str = Query(None),
    random_plot_motif: str = Query(None),
    user_idea: str = Query("", description="Optional user idea to bias generation"),
    ai_backend: str = Query("gemini", description="ai backend hint, optional")
):
    """Generate full preview (title + content + summary) for a random_mix selection.

    This endpoint returns JSON with keys: title, content, summary, file_path, metadata.
    """
    from story_generator import StoryGenerator

    generator = StoryGenerator(model="gemini-2.5-pro")

    # Use the preview helper which will generate story and summary
    try:
        res = await asyncio.get_event_loop().run_in_executor(
            None,
            generator.generate_random_mix_preview,
            random_main_genre,
            random_sub_genre,
            random_character,
            random_setting,
            random_plot_motif,
            None,  # custom_requirements
            None,  # max_tokens
            0.9
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

    return JSONResponse(status_code=200, content=res)


@app.post("/generate_random_mix_preview")
async def generate_random_mix_preview_alias(
    random_main_genre: str = Query(None),
    random_sub_genre: str = Query(None),
    random_character: str = Query(None),
    random_setting: str = Query(None),
    random_plot_motif: str = Query(None),
    user_idea: str = Query("", description="Optional user idea to bias generation"),
    ai_backend: str = Query("gemini", description="ai backend hint, optional")
):
    """Compatibility alias for older clients that call /generate_random_mix_preview.
    Forwards the request to `generate_full_preview` to keep backward compatibility.
    """
    return await generate_full_preview(
        random_main_genre,
        random_sub_genre,
        random_character,
        random_setting,
        random_plot_motif,
        user_idea,
        ai_backend,
    )

def get_media_info(path):
    """Trích xuất thông tin media (video hoặc audio) an toàn."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Không tìm thấy file: {path}")

    probe = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-show_entries", "stream=codec_type,width,height",
        "-of", "json", path
    ], capture_output=True, text=True)

    if probe.returncode != 0 or not probe.stdout.strip():
        raise RuntimeError(f"ffprobe thất bại cho file: {path}")

    try:
        data = json.loads(probe.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Không đọc được JSON từ ffprobe: {probe.stdout[:200]}")

    if "format" not in data:
        raise RuntimeError(f"Không có thông tin 'format' trong ffprobe output cho file: {path}")

    duration = float(data["format"].get("duration", 0) or 0)
    width = height = None

    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width", 0) or 0)
            height = int(stream.get("height", 0) or 0)
            break

    return width, height, duration


def extract_audio_from_video(video_path: str, out_wav: str) -> str:
    """Extract audio from a video file into a WAV file using ffmpeg."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)
    cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-vn', '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2', out_wav
    ]
    subprocess.run(cmd, check=True)
    if not os.path.exists(out_wav):
        raise RuntimeError(f"Failed to extract audio to {out_wav}")
    return out_wav


def is_facebook_url(url: str) -> bool:
    """Return True if the URL is a Facebook (or fb.watch / m.facebook) link.

    We treat Facebook-like hosts as special: when downloads from these URLs fail
    we prefer to fail-fast rather than silently substitute cached random clips.
    """
    if not url:
        return False
    return bool(re.search(r"facebook\.com|fb\.watch|m\.facebook\.com|fbcdn\.net", url, re.I))


def sample_frames_for_watermark(video_path: str, num_frames: int = 5, start_sec: float = 0.5, duration: float = 4.0, max_width: int = 640):
    """Sample `num_frames` evenly spaced frames from a short clip stored at `video_path`.

    Returns a list of frames as numpy arrays (BGR) and the scale factor used when resizing.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video for sampling: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 00
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    _, _, clip_dur = get_media_info(video_path)

    # Compute actual start/time window (clamped)
    duration = min(duration, clip_dur if clip_dur and clip_dur > 0 else duration)
    start_sec = max(0.0, min(start_sec, max(0.0, clip_dur - 0.1)))

    # If we can't get durations, fall back to frame indices
    frames = []
    timestamps = []
    for i in range(num_frames):
        t = start_sec + (i + 0.5) * (duration / max(1, num_frames))
        timestamps.append(t)

    # Read frames at each timestamp
    for t in timestamps:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ret, frame = cap.read()
        if not ret:
            # try to read next available
            ret, frame = cap.read()
            if not ret:
                continue
        # resize if too wide for speed
        scale = 1.0
        if max_width and frame.shape[1] > max_width:
            scale = max_width / float(frame.shape[1])
            frame = cv2.resize(frame, (int(frame.shape[1] * scale), int(frame.shape[0] * scale)))
        frames.append(frame)

    cap.release()
    if not frames:
        raise RuntimeError("Không thể trích xuất khung hình từ video")

    return frames, scale if 'scale' in locals() else 1.0


def detect_static_watermark(frames: List[np.ndarray], min_area: int = 400, debug: bool = False) -> dict:
    """Detect static watermark/logo by finding regions of low variance across sampled frames.

    Returns dict: {found: bool, bbox: (x,y,w,h), corner: 'top-left'|'top-right'|'bottom-left'|'bottom-right', confidence: float}
    """
    if not frames:
        return {"found": False}

    # Convert to float and compute per-pixel standard deviation across frames
    arrs = [f.astype(np.float32) for f in frames]
    stack = np.stack(arrs, axis=0)  # shape (N,H,W,3)

    # Compute per-pixel stddev across time, average across color channels
    std = np.std(stack, axis=0)
    if std.ndim == 3:
        std_gray = std.mean(axis=2)
    else:
        std_gray = std

    # Normalize to 0-255
    std_norm = (std_gray - std_gray.min())
    if std_gray.max() - std_gray.min() > 1e-6:
        std_norm = (std_norm / (std_gray.max() - std_gray.min())) * 255.0
    std_norm = std_norm.astype(np.uint8)

    # Low-variance regions are candidate static overlays
    # Threshold adaptively: choose low percentile
    p10 = np.percentile(std_norm, 10)
    thresh_val = max(6, int(p10 * 0.8))
    _, mask = cv2.threshold(std_norm, thresh_val, 255, cv2.THRESH_BINARY_INV)

    # Morphological clean
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = std_norm.shape
    candidates = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        if area < min_area:
            continue
        # prefer regions closer to corners and small-ish aspect ratio
        cx = x + cw / 2
        cy = y + ch / 2
        # compute corner score: distance to nearest corner
        corners = {
            'top-left': (0, 0),
            'top-right': (w, 0),
            'bottom-left': (0, h),
            'bottom-right': (w, h)
        }
        best_corner = None
        best_dist = None
        for name, (cx_corner, cy_corner) in corners.items():
            dist = math.hypot(cx - cx_corner, cy - cy_corner)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_corner = name

        candidates.append({"bbox": (int(x), int(y), int(cw), int(ch)), "area": area, "corner": best_corner, "dist": best_dist})

    if not candidates:
        return {"found": False}

    # pick largest area candidate
    best = max(candidates, key=lambda x: x["area"])
    x, y, cw, ch = best["bbox"]
    # confidence as area relative to frame
    confidence = float(best["area"]) / float(w * h)

    if debug:
        # return mask and bbox info for debugging
        return {"found": True, "bbox": (x, y, cw, ch), "corner": best["corner"], "confidence": confidence, "mask": mask}

    return {"found": True, "bbox": (x, y, cw, ch), "corner": best["corner"], "confidence": confidence}


def detect_static_watermarks(frames: List[np.ndarray], min_area: int = 400) -> List[dict]:
    """Detect multiple static watermark/logo candidates across sampled frames.

    Returns a list of candidates sorted by confidence descending. Each candidate is a dict:
    {bbox: (x,y,w,h), area: int, corner: str, confidence: float}
    """
    if not frames:
        return []

    arrs = [f.astype(np.float32) for f in frames]
    stack = np.stack(arrs, axis=0)
    std = np.std(stack, axis=0)
    if std.ndim == 3:
        std_gray = std.mean(axis=2)
    else:
        std_gray = std

    std_norm = (std_gray - std_gray.min())
    if std_gray.max() - std_gray.min() > 1e-6:
        std_norm = (std_norm / (std_gray.max() - std_gray.min())) * 255.0
    std_norm = std_norm.astype(np.uint8)

    p10 = np.percentile(std_norm, 10)
    thresh_val = max(6, int(p10 * 0.8))
    _, mask = cv2.threshold(std_norm, thresh_val, 255, cv2.THRESH_BINARY_INV)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = std_norm.shape
    candidates = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        if area < min_area:
            continue
        cx = x + cw / 2
        cy = y + ch / 2
        corners = {
            'top-left': (0, 0),
            'top-right': (w, 0),
            'bottom-left': (0, h),
            'bottom-right': (w, h)
        }
        best_corner = None
        best_dist = None
        for name, (cx_corner, cy_corner) in corners.items():
            dist = math.hypot(cx - cx_corner, cy - cy_corner)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_corner = name

        candidates.append({"bbox": (int(x), int(y), int(cw), int(ch)), "area": area, "corner": best_corner, "confidence": float(area) / float(w * h)})

    # sort by confidence descending
    candidates.sort(key=lambda x: x.get('confidence', 0.0), reverse=True)
    return candidates


def overlay_logo_on_bbox(src_path: str, out_path: str, bbox: tuple, logo_path: str | None = None) -> str:
    """Overlay logo image scaled to bbox (x,y,w,h).

    If logo_path is None will use get_logo_path().
    Returns out_path.
    """
    if logo_path is None:
        logo_path = get_logo_path()
    if not logo_path or not os.path.exists(logo_path):
        raise FileNotFoundError("No logo file found to overlay")
    x, y, w_box, h_box = bbox
    # scale logo to bbox size
    # ffmpeg scale filter: scale=w:h
    filter_complex = f"[1:v]scale={w_box}:{h_box}[lg];[0:v][lg]overlay={x}:{y}"
    cmd = ['ffmpeg', '-y', '-i', src_path, '-i', logo_path, '-filter_complex', filter_complex, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-c:a', 'copy', out_path]
    # use preferred encoder args
    cmd = ['ffmpeg', '-y', '-i', src_path, '-i', logo_path, '-filter_complex', filter_complex]
    cmd.extend(_preferred_video_encode_args())
    cmd.extend(['-c:a', 'copy', out_path])
    subprocess.run(cmd, check=True)
    print(cmd);
    return out_path


def blur_bbox_with_delogo(src_path: str, out_path: str, bbox: tuple) -> str:
    """Apply ffmpeg delogo filter to the bbox region. Returns out_path."""
    x, y, w_box, h_box = bbox
    # delogo: x:y:w:h:band=4:show=0
    filter_str = f"delogo=x={x}:y={y}:w={w_box}:h={h_box}:band=8:show=0"
    cmd = ['ffmpeg', '-y', '-i', src_path, '-vf', filter_str]
    cmd.extend(_preferred_video_encode_args())
    cmd.extend(['-c:a', 'copy', out_path])
    subprocess.run(cmd, check=True)
    return out_path



def suggest_watermark_fix_with_gemini(frame_image_b64: str, api_key: str | None = None) -> dict:
    """Send a single base64-encoded frame to Gemini (if available) and request a JSON suggestion.

    Returns a dict like {found:bool, bbox:[x,y,w,h], action:'blur'|'overlay', ffmpeg_cmd: '...'}.
    If Gemini isn't available or call fails, raises Exception.
    """
    # Build prompt asking for JSON only
    system = (
        "You are a computer vision assistant specialized in detecting static watermarks or logos in video frames. "
        "Your task is to analyze a given image and return the watermark region (if any) as a structured JSON response. "
        "Output must be a single valid JSON object only — no text, markdown, or explanations."
    )

    user = (
        "Inspect the provided base64-encoded image to detect any visible, static watermark or logo region. "
        "Return a JSON object with the following keys:\n"
        " - found (boolean): true if a watermark/logo is detected, otherwise false.\n"
        " - bbox (array of 4 integers): [x, y, w, h] — the top-left coordinates and size of the watermark region, in pixels.\n"
        " - action (string): either 'blur' or 'overlay' — whichever best hides the watermark.\n"
        " - ffmpeg_cmd (string): a ready-to-use ffmpeg command that would blur or overlay the detected watermark region.\n\n"
        "Rules:\n"
        "1. Coordinates must be integers relative to the full image dimensions.\n"
        "2. If no watermark is found, return {\"found\": false}.\n"
        "3. Output JSON only — no comments or additional text.\n\n"
        "The image is provided as a base64 string in key 'image_b64'."
    )
    # Build request payload
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user + "\n\n{" + f'"image_b64":"[BASE64]"' + "} (replace [BASE64] with the provided image)"}
    ]

    # Use client if available. We only want bbox and confidence back from Gemini.
    try:
        client = _genai.Client(api_key=api_key or GEMINI_API_KEY)
        short_b64 = frame_image_b64[:2000]
        full_prompt = (
            system + "\n" + user + "\nExample image start (truncated):\n" + short_b64 + "\n\nRespond with JSON only."
        )
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=[full_prompt],
            config=None
        )
        # Extract text safely
       
        try:
            print( text = response.candidates[0].content[0].text);
            text = response.candidates[0].content[0].text
        except Exception:
            text = getattr(response, 'text', None) or str(response)

        clean = text.strip()
        # strip code fences
        if clean.startswith('```'):
            parts = clean.split('\n', 1)
            if parts and parts[0].startswith('```'):
                clean = parts[1] if len(parts) > 1 else ''
        if clean.endswith('```'):
            clean = clean[:clean.rfind('```')]
        clean = clean.strip()

        start = clean.find('{')
        end = clean.rfind('}')
        if start >= 0 and end > start:
            candidate = clean[start:end+1]
            parsed = None
            try:
                parsed = _json.loads(candidate)
            except Exception:
                # permissive cleanup
                try:
                    parsed = _json.loads(candidate.replace('```', ''))
                except Exception:
                    parsed = None

            # If Gemini returned a JSON object with bbox, extract it
            if isinstance(parsed, dict) and parsed.get('bbox'):
                bbox = parsed.get('bbox')
                # normalize bbox to list of ints [x,y,w,h]
                try:
                    bx, by, bw, bh = map(int, bbox[:4])
                    confidence = float(parsed.get('confidence', 1.0)) if parsed.get('confidence') else 1.0
                    return {"found": True, "bbox": [bx, by, bw, bh], "confidence": confidence}
                except Exception as e:
                    _report_and_ignore(e, "ignored")
        # if we reach here, Gemini didn't provide a usable bbox
    except Exception as e:
        # swallow and fallback to local detection below
        send_discord_message("⚠️ Gemini suggestion failed or did not return bbox: %s", str(e))

    # Fallback: decode provided base64 frame and run local detector on it
    try:
        img_bytes = b64decode(frame_image_b64)
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return {"found": False}
        det = detect_static_watermark([img])
        if not det.get('found'):
            return {"found": False}
        x, y, w_box, h_box = det['bbox']
        return {"found": True, "bbox": [int(x), int(y), int(w_box), int(h_box)], "confidence": float(det.get('confidence', 1.0))}
    except Exception:
        return {"found": False}


def suggest_with_gemini_file(file_path: str, api_key: str | None = None, fps: int = 1, start_offset: str | None = None, end_offset: str | None = None) -> dict:
    """Upload video to Gemini Files API and request a JSON suggestion for watermark fix.

    Returns parsed JSON suggestion or raises on failure.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    client = _genai.Client(api_key=api_key or GEMINI_API_KEY)

    # If file is small (<20MB) prefer inline blob part (faster & avoids Files API)
    try:
        size = os.path.getsize(file_path)
    except Exception:
        size = None

    inline_threshold = 20 * 1024 * 1024  # 20 MB
    send_discord_message("📤 Sending video to Gemini for analysis (size=%s bytes): %s", size, file_path)

    # Prepare video metadata if provided
    video_metadata = None
    if fps or start_offset or end_offset:
        video_metadata = gen_types.VideoMetadata()
        if fps:
            video_metadata.fps = int(fps)
        if start_offset:
            video_metadata.start_offset = str(start_offset)
        if end_offset:
            video_metadata.end_offset = str(end_offset)

    # If small enough, send inline blob
    if size is not None and size <= inline_threshold:
        try:
            with open(file_path, 'rb') as f:
                video_bytes = f.read()
            parts = [gen_types.Part(inline_data=gen_types.Blob(data=video_bytes, mime_type='video/mp4'), video_metadata=video_metadata), gen_types.Part(text=(
                "Inspect the referenced video (inline) and return a single JSON object ONLY with keys:\n"
                "found: boolean, bbox: [x,y,w,h] (integers in pixels), action: 'blur' or 'overlay', ffmpeg_cmd: string." 
                " Do not include any explanatory text."))]

            resp = client.models.generate_content(model="models/gemini-2.5-flash", contents=gen_types.Content(parts=parts))
            try:
                text = resp.candidates[0].content[0].text
            except Exception:
                text = getattr(resp, 'text', None) or str(resp)

            start = text.find('{')
            if start >= 0:
                candidate = text[start:]
                end = candidate.rfind('}')
                if end != -1:
                    candidate = candidate[:end+1]
                return _json.loads(candidate)
            raise RuntimeError(f"Gemini inline did not return parseable JSON: {text[:400]}")
        except Exception as e:
            send_discord_message("⚠️ Gemini inline attempt failed, will fallback to Files API: %s", e)

    # Fallback to Files API upload
    myfile = client.files.upload(file=file_path)
    # normalize uploaded file reference to a string URI accepted by gen_types.FileData
    if isinstance(myfile, str):
        file_uri = myfile
    else:
        file_uri = getattr(myfile, 'name', None) or getattr(myfile, 'uri', None) or getattr(myfile, 'file_uri', None) or getattr(myfile, 'id', None) or str(myfile)

    # Prepare video metadata if provided
    video_metadata = None
    if fps or start_offset or end_offset:
        video_metadata = gen_types.VideoMetadata()
        if fps:
            video_metadata.fps = int(fps)
        if start_offset:
            video_metadata.start_offset = str(start_offset)
        if end_offset:
            video_metadata.end_offset = str(end_offset)

    # Build prompt requesting JSON output only
    user_text = (
        "Inspect the referenced video file and return a single JSON object ONLY with keys:\n"
        "found: boolean, bbox: [x,y,w,h] (integers in pixels), action: 'blur' or 'overlay', ffmpeg_cmd: string."
        " Do not include any explanatory text."
    )

    parts = [
        gen_types.Part(file_data=gen_types.FileData(file_uri=file_uri)),
        gen_types.Part(text=user_text)
    ]

    if video_metadata:
        # attach same metadata to the file part
        parts[0].video_metadata = video_metadata

    try:
        resp = client.models.generate_content(model="models/gemini-2.5-flash", contents=gen_types.Content(parts=parts))
        # Extract text-safe output
        try:
            text = resp.candidates[0].content[0].text
        except Exception:
            text = getattr(resp, 'text', None) or str(resp)

        # parse first JSON object in response
        start = text.find('{')
        if start >= 0:
            candidate = text[start:]
            try:
                return _json.loads(candidate)
            except Exception:
                # try to be permissive
                # remove trailing characters after last '}'
                end = candidate.rfind('}')
                if end != -1:
                    try:
                        return _json.loads(candidate[:end+1])
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
        raise RuntimeError(f"Gemini Files API did not return parseable JSON: {text[:400]}")
    except Exception as e:
        raise

def suggest_copyright_transform_with_gemini(file_path: str, api_key: str | None = None) -> dict:
    """Upload a video file to Gemini and request a short JSON suggestion for a copyright-avoidance transform.

    Expected return JSON: {"ffmpeg_cmd": "...", "reason": "...", "success_likely": true}
    The returned command should ideally use placeholders {in} and {out} which will be replaced by the caller.
    Raises on failure to contact Gemini or parse the result.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    client = _genai.Client(api_key=api_key or GEMINI_API_KEY)
    send_discord_message("📤 Requesting Gemini copyright-transform suggestion for: %s", file_path)

    # prefer inline blob for small files (<=20MB) following Gemini sample
    try:
        size = os.path.getsize(file_path)
    except Exception:
        size = None

    inline_threshold = 20 * 1024 * 1024
    user_text = (
        "You will be given a video file (attached). Return a single JSON object ONLY with keys:\n"
        "ffmpeg_cmd: a full ffmpeg command string that uses placeholders {in} and {out} for input and output paths,\n"
        "reason: short explanation (1-2 sentences),\n"
        "success_likely: boolean.\n"
        "Do not include any additional text. If you cannot propose a reliable command, return {\"ffmpeg_cmd\": \"\", \"reason\": \"\", \"success_likely\": false}."
    )

    # Try inline blob path when file is small
    if size is not None and size <= inline_threshold:
        try:
            with open(file_path, 'rb') as f:
                video_bytes = f.read()
            parts = [
                gen_types.Part(inline_data=gen_types.Blob(data=video_bytes, mime_type='video/mp4'),
                               video_metadata=gen_types.VideoMetadata()),
                gen_types.Part(text=user_text)
            ]

            resp = client.models.generate_content(model='models/gemini-2.5-flash', contents=gen_types.Content(parts=parts))
            try:
                text = resp.candidates[0].content[0].text
            except Exception:
                text = getattr(resp, 'text', None) or str(resp)

            start = text.find('{')
            if start >= 0:
                candidate = text[start:]
                end = candidate.rfind('}')
                if end != -1:
                    candidate = candidate[:end+1]
                return _json.loads(candidate)
            raise RuntimeError(f"Gemini (inline) did not return JSON: {text[:400]}")
        except Exception as e:
            send_discord_message("⚠️ Gemini inline attempt failed, will fallback to Files API: %s", e)

    # Fallback to Files API
    myfile = client.files.upload(file=file_path)
    if isinstance(myfile, str):
        file_uri = myfile
    else:
        file_uri = getattr(myfile, 'name', None) or getattr(myfile, 'uri', None) or getattr(myfile, 'file_uri', None) or getattr(myfile, 'id', None) or str(myfile)

    parts = [
        gen_types.Part(file_data=gen_types.FileData(file_uri=file_uri)),
        gen_types.Part(text=user_text)
    ]

    resp = client.models.generate_content(model="models/gemini-2.5-flash", contents=gen_types.Content(parts=parts))
    try:
        text = resp.candidates[0].content[0].text
    except Exception:
        text = getattr(resp, 'text', None) or str(resp)

    start = text.find('{')
    if start >= 0:
        candidate = text[start:]
        end = candidate.rfind('}')
        if end != -1:
            candidate = candidate[:end+1]
        return _json.loads(candidate)
    raise RuntimeError(f"Gemini Files API did not return parseable JSON: {text[:400]}")


@app.post('/facebook_fix_watermark')
async def facebook_fix_watermark(
    fb_url: str = Query(..., description='Facebook video URL'),
    use_gemini: bool = Query(True, description='If True, send a sample frame to Gemini for suggestion'),
    apply_fix: bool = Query(False, description='If True, apply the suggested fix to the clip and return the fixed path'),
    gemini_api_key: str | None = Query(None, description='Optional Gemini API key (if not set, will use client default)')
):
    """Analyze a short FB clip for watermark and either return Gemini suggestion or apply fix.

    Returns JSON with suggestion and optionally the path to the fixed clip.
    """
    loop = asyncio.get_event_loop()
   
    request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    base_name = f"fb_fix_{url_hash(fb_url)}"
    clip_path = os.path.join(OUTPUT_DIR, f"{base_name}.mp4")

    # Download short clip (fail fast)
    try:
        await loop.run_in_executor(executor, download_video_url, fb_url, clip_path, 3, 2, 4.0, True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tải video thất bại: {e}")

    # Sample a single representative frame
    try:
        frames, scale = await loop.run_in_executor(executor, sample_frames_for_watermark, clip_path, 3, 0.5, 3.0)
        rep = frames[len(frames)//2]
        # encode to PNG base64
        _, buf = cv2.imencode('.png', rep)
        b64 = b64encode(buf.tobytes()).decode('ascii')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không thể trích khung hình: {e}")

    suggestion = None
    # Try Gemini if requested
    if use_gemini:
        try:
            suggestion = await loop.run_in_executor(executor, suggest_watermark_fix_with_gemini, b64, gemini_api_key)
        except Exception as e:
            send_discord_message("⚠️ Gemini suggestion failed, falling back to local detector: %s", e)
            suggestion = None

    if not suggestion:
        # fallback to local detector
        local = await loop.run_in_executor(executor, detect_static_watermark, frames)
        if not local.get('found'):
            return {"found": False, "note": "No watermark detected by local method"}
        x, y, w_box, h_box = local['bbox']
        action = 'overlay' if (w_box * h_box) < (0.03 * rep.shape[0] * rep.shape[1]) else 'blur'
        # Build ffmpeg suggestion using delogo (for blur) or overlay command
        if action == 'blur':
            ffmpeg_cmd = f"ffmpeg -i {clip_path} -vf \"delogo=x={x}:y={y}:w={w_box}:h={h_box}:show=0\" -c:v libx264 -crf 23 -c:a copy fixed.mp4"
        else:
            ffmpeg_cmd = f"ffmpeg -i {clip_path} -i LOGO.png -filter_complex \"[1:v]scale={w_box}:{h_box}[lg];[0:v][lg]overlay={x}:{y}\" -c:v libx264 -crf 23 -c:a copy fixed.mp4"
        suggestion = {"found": True, "bbox": [int(x), int(y), int(w_box), int(h_box)], "action": action, "ffmpeg_cmd": ffmpeg_cmd}

    result = {"suggestion": suggestion}

    # Optionally apply fix locally
    if apply_fix and suggestion.get('found'):
        action = suggestion.get('action')
        bbox = tuple(suggestion.get('bbox'))
        fixed = os.path.join(OUTPUT_DIR, f"{base_name}_fixed.mp4")
        try:
            if action == 'blur':
                await loop.run_in_executor(executor, blur_bbox_with_delogo, clip_path, fixed, bbox)
            else:
                await loop.run_in_executor(executor, overlay_logo_on_bbox, clip_path, fixed, bbox, None)
            result['fixed_path'] = fixed
        except Exception as e:
            result['apply_error'] = str(e)

    # cleanup sample clip only if we applied fix or not needed
    # (keep it otherwise for inspection)
    return JSONResponse(content=result)


@app.get("/facebook_detect_watermark")
async def facebook_detect_watermark(
    fb_url: str = Query(..., description="Facebook video URL"),
    duration: float = Query(4.0, description="Seconds to sample"),
    num_frames: int = Query(5, description="Number of frames to sample"),
    start_sec: float = Query(0.5, description="Start position inside sampled clip (seconds)"),
):
    """Download a short clip from Facebook (fail-fast) and detect static watermark/logo position.

    Returns JSON with bbox (x,y,w,h) in pixels relative to the sampled/resized frames and corner suggestion.
    """
    loop = asyncio.get_event_loop()
    base_name = f"fb_wm_{url_hash(fb_url)}"
    out_clip = os.path.join(OUTPUT_DIR, f"{base_name}.mp4")

    try:
        # download a short clip equal to `duration` (fail fast for FB)
        await loop.run_in_executor(executor, download_video_url, fb_url, out_clip, 3, 2, duration, True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tải video thất bại: {e}")

    try:
        frames, scale = await loop.run_in_executor(executor, sample_frames_for_watermark, out_clip, num_frames, start_sec, duration)
        result = await loop.run_in_executor(executor, detect_static_watermark, frames, 400, False)
        # If bbox was computed on resized frames, scale bbox back to original if needed
        if result.get("found") and scale and scale != 1.0:
            x, y, cw, ch = result["bbox"]
            inv = 1.0 / scale
            result["bbox_orig"] = (int(x * inv), int(y * inv), int(cw * inv), int(ch * inv))
        # attach a suggested overlay coordinate: prefer placing overlay centered on bbox
        if result.get("found"):
            x, y, cw, ch = result.get("bbox_orig") if result.get("bbox_orig") else result.get("bbox")
            result["overlay_pos"] = {"x": x, "y": y, "w": cw, "h": ch, "corner": result.get("corner")}

        # save to task if a matching task exists (optional)
        return JSONResponse(content=result)
    finally:
        try:
            if os.path.exists(out_clip):
                os.remove(out_clip)
        except Exception as e:
            _report_and_ignore(e, "ignored")
@app.get("/get_truyen_no_vanan")
async def get_truyen_no_vanan(
    url: str = Query(..., description="Link truyện (trang chính hoặc link chương 1)."),
    delay: float = Query(1.0, description="Delay giữa các request (giây)."),
    max_chapters: int = Query(500, description="Số chương tối đa để cào."),
):
    """Trả về toàn bộ nội dung chương (không lấy văn án).

    - Nếu `url` là trang chính chứa link tới chương 1, hàm sẽ tự tìm chương 1 và bắt đầu cào.
    - Trả về JSON: {"text": <full_chapters_text>, "chapter_urls": [..]}.
    """
    loop = asyncio.get_event_loop()
    send_discord_message("🔎 get_truyen_no_vanan: bắt đầu cào %s", url)
    try:
        # crawl_chapters_until_disabled tự xử lý khi url là trang chính hoặc link chương
        full_text, chapter_urls = await loop.run_in_executor(executor, crawl_chapters_until_disabled, url, delay, max_chapters)
        return JSONResponse(content={"text": full_text or "", "chapter_urls": chapter_urls or []})
    except Exception as e:
        send_discord_message("❌ get_truyen_no_vanan error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
def get_media_info_fbs(path):
    """Trích xuất thông tin media (video hoặc audio) an toàn, gồm width, height, duration, fps."""
    import os, subprocess, json

    if not os.path.exists(path):
        raise FileNotFoundError(f"Không tìm thấy file: {path}")

    # Gọi ffprobe để lấy thông tin video + audio
    probe = subprocess.run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",  # chỉ lấy stream video đầu tiên
        "-show_entries", "stream=codec_type,width,height,r_frame_rate",
        "-show_entries", "format=duration",
        "-of", "json", path
    ], capture_output=True, text=True)

   # Kiểm tra lỗi trả về
    if probe.returncode != 0 or not probe.stdout.strip():
        raise RuntimeError(
            f"ffprobe thất bại cho file: {path}\n"
            f"Mã lỗi: {probe.returncode}\n"
            f"Lỗi chi tiết: {probe.stderr.strip() or 'Không có thông tin lỗi.'}"
        )

    # Thử đọc JSON
    try:
        data = json.loads(probe.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Không đọc được JSON từ ffprobe cho file: {path}\n"
            f"Lỗi JSON: {e}\n"
            f"Dữ liệu trả về (200 ký tự đầu): {probe.stdout[:200]}\n"
            f"stderr: {probe.stderr.strip()}"
        )

    # Thời lượng
    duration = float(data.get("format", {}).get("duration", 0) or 0)

    width = height = None
    fps = 0.0

    # Lấy thông tin video (nếu có)
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width", 0) or 0)
            height = int(stream.get("height", 0) or 0)

            fps_str = stream.get("r_frame_rate", "0/0")
            try:
                num, den = fps_str.split('/')
                fps = float(num) / float(den) if float(den) != 0 else 0.0
            except Exception:
                fps = 0.0
            break

    # Nếu không có video (chỉ là audio) → width, height = None, fps = 0
    return width, height, duration, fps

import os, math, subprocess, logging
def concat_crop_audio_with_titles(video_paths, audio_path, output_path="final.mp4",
                                  Title="", font_path="/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"):
    """
    🔹 Gộp nhiều video + crop 9:16 + scale 1080x1920 + add audio.
    🔹 Thêm tiêu đề 3s đầu mỗi part (0h, 1h, 2h, ...) dựa trên tổng thời lượng audio.
    🔹 Encode 1 lần duy nhất — sau đó chia part nhanh bằng copy (fix DTS lỗi).
    """
    import os, math, subprocess, logging

    if not video_paths:
        raise ValueError("Danh sách video trống.")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Không tìm thấy file âm thanh: {audio_path}")

    # --- 1️⃣ Lấy thông tin video và audio ---
    # Nếu get_media_info_fbs bị lỗi với video nào, bỏ qua video đó
    video_infos = []
    total_video_dur = 0
    fps_values = []
    valid_video_paths = []
    
    for idx, p in enumerate(video_paths):
        try:
            w, h, d, fps = get_media_info_fbs(p)
            video_infos.append((w, h, d, fps))
            valid_video_paths.append(p)
            total_video_dur += d
            if fps > 0:
                fps_values.append(fps)
            send_discord_message(f"✅ Video {idx+1}/{len(video_paths)} OK - {os.path.basename(p)}")
        except Exception as e:
            send_discord_message(
                f"⚠️ Bỏ qua video {idx+1}/{len(video_paths)} do lỗi get_media_info: {os.path.basename(p)} - {e}"
            )
            continue
    
    if not valid_video_paths:
        raise RuntimeError("Không có video hợp lệ nào sau khi kiểm tra get_media_info")
    
    # Cập nhật video_paths chỉ chứa video hợp lệ
    video_paths = valid_video_paths
    
    if not fps_values:
        fps_values.append(30)
    
    _, _, audio_dur = get_media_info(audio_path)
    send_discord_message(f"🎞️ Tổng video={total_video_dur:.2f}s, Audio={audio_dur:.2f}s")
    min_fps = min(fps_values) if fps_values else 30
    # Estimate how many 1-hour parts the final audio will produce so titles can reflect parts
    total_seconds = audio_dur
    num_parts = math.floor(total_seconds / 3600) + 1 if total_seconds > 3600 else 1
    total_parts = num_parts
    # default start_time for title overlay (will be adjusted in per-part processing if needed)
    start_time = 0
    # --- 2️⃣ Lặp video nếu audio dài hơn tổng video ---
    loops = math.ceil(audio_dur / total_video_dur) if total_video_dur < audio_dur else 1
    extended_video_paths = video_paths * loops
    total_video_dur *= loops

    # --- 3️⃣ Build filter_complex ---
    filters = []
    for i, (w, h, _,fps) in enumerate(video_infos * loops):
        aspect = w / h
        target = 9 / 16
        if aspect > target:
            new_w = int(h * target)
            x_offset = (w - new_w) // 2
            crop = f"crop={new_w}:{h}:{x_offset}:0"
        else:
            new_h = int(w / target)
            y_offset = (h - new_h) // 2
            crop = f"crop={w}:{new_h}:0:{y_offset}"
        # preserve original size; avoid forced 9:16 scaling
        filters.append(f"[{i}:v]setsar=1[v{i}]")

    concat_inputs = "".join([f"[v{i}]" for i in range(len(extended_video_paths))])
    filters.append(f"{concat_inputs}concat=n={len(extended_video_paths)}:v=1:a=0[vc]")

    # --- 4️⃣ Tiêu đề ---
    title_filters = []
    if total_parts == 1:
        text = f"[FULL] {Title.upper()}"
    else:
        text = f"{Title.upper()} - P.{i+1}"
    text = text.replace(":", "\\:").replace("'", "\\'")
    wrapped_text = wrap_text(text, max_chars_per_line=35)
    pad_h = 40
    title_filters.append(
        f"drawtext=fontfile='{font_path}':text='{wrapped_text}':"
        f"fontcolor=white:fontsize=40:box=1:boxcolor=black@1:boxborderw=20:"
        f"text_align=center:"
        f"x=(w-text_w)/2:y=(h-text_h-line_h)/2:"
        f"enable='between(t,{start_time},{start_time+3})'"
    )

    if title_filters:
        filters.append(f"[vc]{','.join(title_filters)}[v]")
    else:
        filters.append("[vc]copy[v]")

    filters.append(f"[{len(extended_video_paths)}:a]aresample=48000[a]")
    filter_complex = ";".join(filters)

    # --- 5️⃣ Render video chính ---
    cmd = ["ffmpeg", "-y", "-fflags", "+genpts"]
    for p in extended_video_paths:
        cmd += ["-i", p]
    cmd += ["-i", audio_path]
    cmd += [
        "-t", str(audio_dur),
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
    ]
    cmd.extend(_preferred_video_encode_args())
    cmd.extend(["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-shortest", "-pix_fmt", "yuv420p", output_path])

    send_discord_message("🎬 Render video (concat + crop + audio + title multi-parts)...")
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode != 0:
        logging.error(f"❌ FFmpeg error:\n{result.stderr}")
        raise RuntimeError("Lỗi khi render video")

    # --- 6️⃣ Chia part nhanh (không re-encode, fix DTS) ---
    total_seconds = audio_dur
    num_parts = math.floor(total_seconds / 3600) + 1 if total_seconds > 3600 else 1
    part_duration = total_seconds/num_parts

    base, ext = os.path.splitext(output_path)
    output_files = []
    for i in range(num_parts):
        start = i * part_duration
        duration = min(part_duration, total_seconds - start)
        part_path = f"{base}_part_{i+1}{ext}"

        # ⚙️ Fix non-monotonic DTS bằng các flag sau:
        cut_cmd = [
            "ffmpeg", "-y",
            "-fflags", "+genpts",
            "-avoid_negative_ts", "1",
            "-ss", str(start), "-t", str(duration),
            "-i", output_path,
            "-c", "copy",
            part_path
        ]
        subprocess.run(cut_cmd, check=True)
        output_files.append(part_path)

        try:
            uploadOneDrive(part_path)
            send_discord_message(f"✅ Xuất video hoàn tất: {part_path}")
        except Exception:
            send_discord_message("⚠️ Upload không thành công")

    os.remove(output_path)
    return output_files

def concat_and_add_audio(video_paths, audio_path, output_path="final.mp4", Title=""):
    """
    🔹 Gộp nhiều video + crop trung tâm 9:16 + scale 1080x1920 + add audio
    - Nếu tổng thời lượng < audio → lặp video
    - Nếu tổng thời lượng > audio → cắt video
    - Tất cả xử lý trong 1 lần encode
    """
    if not video_paths:
        raise ValueError("Danh sách video trống.")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Không tìm thấy file âm thanh: {audio_path}")

    # --- 1️⃣ Lấy thông tin video và audio ---
    video_infos = []
    total_video_dur = 0
    for p in video_paths:
        w, h, d = get_media_info(p)  # hàm user có sẵn
        video_infos.append((w, h, d))
        total_video_dur += d
    _, _, audio_dur = get_media_info(audio_path)
    send_discord_message(f"🎞️ Tổng video={total_video_dur:.2f}s, Audio={audio_dur:.2f}s")

    # --- 2️⃣ Lặp video nếu audio dài hơn tổng video ---
    loops = 1
    if total_video_dur < audio_dur:
        loops = math.ceil(audio_dur / total_video_dur)
    extended_video_paths = video_paths * loops
    total_video_dur *= loops

    # --- 3️⃣ Build filter_complex ---
    filters = []
    for i, (w, h, _) in enumerate(video_infos * loops):
        aspect = w / h
        target = 9 / 16
        if aspect > target:
            new_w = int(h * target)
            x_offset = (w - new_w) // 2
            crop = f"crop={new_w}:{h}:{x_offset}:0"
        else:
            new_h = int(w / target)
            y_offset = (h - new_h) // 2
            crop = f"crop={w}:{new_h}:0:{y_offset}"
        # preserve original size; avoid forced 9:16 scaling
        filters.append(f"[{i}:v]setsar=1[v{i}]")

    # Concat tất cả video
    concat_inputs = "".join([f"[v{i}]" for i in range(len(extended_video_paths))])
    filters.append(f"{concat_inputs}concat=n={len(extended_video_paths)}:v=1:a=0[v]")

    # Audio
    filters.append(f"[{len(extended_video_paths)}:a]aresample=48000[a]")

    filter_complex = ";".join(filters)

    # --- 4️⃣ Tạo lệnh ffmpeg ---
    cmd = ["ffmpeg", "-y"]

    # Thêm video inputs
    for p in extended_video_paths:
        cmd += ["-i", p]
    # Thêm audio input
    cmd += ["-i", audio_path]

    # Filter + map + encode
    cmd += [
        "-t", str(audio_dur),  # cắt nếu video dài hơn audio
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-shortest",
        "-pix_fmt", "yuv420p",
        output_path
    ]

    send_discord_message("🎬 Render video (concat + crop + audio)...")
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode != 0:
        logging.error(f"❌ FFmpeg error:\n{result.stderr}")
        raise RuntimeError("Lỗi khi render video")

    # --- 5️⃣ Optional: chia video, upload ---
    list_output = split_video_by_hour_with_title(output_path, Title,"/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf")
    for o in list_output:
        try:
            uploadOneDrive(o, Title)
            send_discord_message(f"✅ Xuất video hoàn tất: {o}")
        except Exception:
            send_discord_message("⚠️ Upload không thành công")

    return list_output



def split_video_by_hour_with_title(input_path, base_title=None, font_path="times.ttf"):
    """
    🔹 Chia video >1h, thêm tiêu đề 3s đầu mà không encode toàn bộ video
    """
    import math

    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", input_path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    total_seconds = float(result.stdout)
    output_files = []

    if total_seconds > 3600:
        num_parts = math.floor(total_seconds / 3600) + 1
        part_duration = total_seconds / num_parts
    else:
        num_parts = 1
        part_duration = total_seconds

    base, ext = os.path.splitext(input_path)

    for i in range(num_parts):
        start = i * part_duration
        duration = min(part_duration, total_seconds - start)
        output_path = f"{base}_part_{i+1}{ext}"

        if base_title:
            if num_parts == 1:
                title_text = f"[FULL] {base_title}"
            else:
                title_text = f"{base_title} - P.{i+1}"
            wrapped_text = wrap_text(title_text, max_chars_per_line=35)
            pad_h = 40
            drawtext = (
                f"drawtext=fontfile='{font_path}':text='{wrapped_text}':"
                f"fontcolor=white:fontsize=42:box=1:boxcolor=black@1:boxborderw=20:"
                f"text_align=center:"
                f"x=(w-text_w)/2:y=(h-text_h-line_h)/2:enable='between(t,0,3)':boxborderw={pad_h}"
            )

            # 1️⃣ Clip 3s đầu với title
            clip_title = f"{base}_part_{i+1}_title{ext}"
            cmd_clip_title = ["ffmpeg", "-y", "-ss", str(start), "-t", "3", "-i", input_path, "-vf", drawtext]
            cmd_clip_title.extend(_preferred_video_encode_args())
            cmd_clip_title.extend(["-c:a", "copy", clip_title])
            subprocess.run(cmd_clip_title, check=True)

            # 2️⃣ Copy phần còn lại
            clip_rest = f"{base}_part_{i+1}_rest{ext}"
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(start + 3), "-t", str(duration - 3),
                "-i", input_path, "-c", "copy", clip_rest
            ], check=True)

            # 3️⃣ Concat 2 clip
            concat_file = f"{base}_part_{i+1}_list.txt"
            with open(concat_file, "w") as f:
                f.write(f"file '{clip_title}'\nfile '{clip_rest}'\n")
            subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_file, "-c", "copy", output_path
            ], check=True)

            # Xóa tạm
            os.remove(clip_title)
            os.remove(clip_rest)
            os.remove(concat_file)

        else:
            # Copy toàn bộ nếu không cần title
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(start), "-t", str(duration),
                "-i", input_path, "-c", "copy", output_path
            ], check=True)

        output_files.append(output_path)

    return output_files
def wrap_text(text, max_chars_per_line=10):
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        if len(current_line + " " + word) <= max_chars_per_line:
            current_line += " " + word if current_line else word
        else:
            lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return "\n".join(lines)
def concat_videos_fast_cpu(video_paths, output_path="merged.mp4"):  
    import tempfile, subprocess, os

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as f:
        for p in video_paths:
            if not os.path.exists(p):
                raise FileNotFoundError(f"Không tìm thấy file: {p}")
            f.write(f"file '{os.path.abspath(p)}'\n")
        list_file = f.name

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-fflags", "+genpts",
        "-avoid_negative_ts", "make_zero",
        "-c:v", "libx264",
        "-preset", "ultrafast",     # nhanh nhất
        "-crf", "28",               # nén nhẹ, tốc độ cao
        "-tune", "fastdecode",      # tối ưu giải mã nhanh
        "-x264-params", "keyint=60;min-keyint=60;no-scenecut=1",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        "-threads", "0",
        output_path
    ]

    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode != 0:
        send_discord_message("❌ FFmpeg error:\n", result.stderr)
        raise RuntimeError("Lỗi khi concat video")

    return output_path
    
# ============================== DEPRECATED - Uses AudioSegment ==============================
# def enhance_audio_sox(input_path: str, bg_choice: str | None = None) -> str:
#     """
#     Use sox to increase speed and pitch of the voice, then optionally mix a background WAV.
# 
#     This function will:
#     - call the `sox` CLI to produce a processed tmp file
#     - load the processed file with pydub, mix background similarly to `enhance_audio`
#     - export final file as <input>_capcut_sox.wav
#     """
#     output_path = input_path.replace(".wav", "_capcut_sox.wav")
#     if os.path.exists(output_path):
#         send_discord_message("🎧 Dùng cache audio SOX đã chỉnh: %s", output_path)
#         return output_path
# 
#     send_discord_message("⚙️ Đang xử lý audio bằng sox (tăng tốc & pitch)...")
#     tmp_sox = output_path + ".sox.tmp.wav"
# 
#     # Build sox command. Adjust speed and pitch multipliers/cents as desired.
#     # speed: 1.08 means ~8% faster (also raises pitch). pitch in cents (100 cents = 1 semitone)
#     speed_factor = 1.5
#     pitch_cents = 400  # ~2 semitones
# 
#     # We force output to 48000 rate to match downstream expectations
#     cmd = [
#         "sox", input_path, tmp_sox,
#         "speed", f"{speed_factor}",
#         "pitch", str(pitch_cents),
#         "rate", "48000"
#     ]
# 
#     try:
#         subprocess.run(cmd, check=True, capture_output=True)
#     except Exception as e:
#         send_discord_message(f"⚠️ Lỗi khi chạy sox: {e}. Bỏ qua sox và dùng file gốc.")
#         # fallback to original behavior: return original or raise
#         if os.path.exists(input_path):
#             return input_path
#         raise
# 
#     # Now mix background similar to enhance_audio
#     try:
#         # Prefer bgaudio folder inside the discord-bot directory (for files selected via the Discord UI).
#         discord_bot_bgaudio = os.path.join(BASE_DIR, "discord-bot", "bgaudio")
#         if os.path.isdir(discord_bot_bgaudio):
#             bgaudio_dir = discord_bot_bgaudio
#         else:
#             bgaudio_dir = os.path.join(OUTPUT_DIR, "bgaudio")
#         bg_files = []
#         if os.path.isdir(bgaudio_dir):
#             for f in os.listdir(bgaudio_dir):
#                 if f.lower().endswith(".wav"):
#                     bg_files.append(os.path.join(bgaudio_dir, f))
# 
#         # If a specific bg_choice was requested, prefer it when present
#         if bg_choice:
#             candidate = os.path.join(bgaudio_dir, os.path.basename(bg_choice))
#             if os.path.exists(candidate):
#                 bg_files = [candidate]
#             else:
#                 send_discord_message("⚠️ Yêu cầu nhạc nền không tìm thấy cho SOX: %s. Dùng ngẫu nhiên.", candidate)
# 
#         if not bg_files:
#             # No background available, move tmp_sox to final
#             os.replace(tmp_sox, output_path)
#             send_discord_message("✅ Đã tạo audio SOX (không có nhạc nền): %s", output_path)
#             return output_path
# 
#         # Pick background (requested or random)
#         if len(bg_files) == 1:
#             chosen_bg = bg_files[0]
#         else:
#             chosen_bg = random.choice(bg_files)
# 
#         processed = AudioSegment.from_file(tmp_sox)
#         bg = AudioSegment.from_file(chosen_bg)
# 
#         # Match channels and frame rate
#         if bg.channels != processed.channels:
#             bg = bg.set_channels(processed.channels)
#         if bg.frame_rate != processed.frame_rate:
#             bg = bg.set_frame_rate(processed.frame_rate)
# 
#         # Loop background to at least the length of the processed audio
#         if len(bg) < len(processed):
#             repeats = math.ceil(len(processed) / len(bg))
#             bg = bg * repeats
# 
#         bg = bg[:len(processed)]
# 
#         # Lower background volume so voice remains clear
#         bg = bg - 20
# 
#         combined = processed.overlay(bg)
#         combined.export(output_path, format="wav")
#         send_discord_message("✅ Đã tạo audio SOX và trộn nhạc nền: %s (bg=%s)", output_path, os.path.basename(chosen_bg))
# 
#         # cleanup
#         try:
#             if os.path.exists(tmp_sox):
#                 os.remove(tmp_sox)
#         except Exception:
#             pass
# 
#         return output_path
# 
#     except Exception as e:
#         send_discord_message(f"⚠️ Lỗi khi trộn nhạc nền cho SOX: {e}. Dùng file processed thuần.")
#         try:
#             if os.path.exists(tmp_sox):
#                 os.replace(tmp_sox, output_path)
#                 return output_path
#         except Exception:
#             pass
#         raise
# ============================================================================================

def combine_video_with_audio(video_path, audio_path, output_path="out.mp4"):
    """
    Đồng bộ video với audio:
    - Crop trung tâm theo 9:16
    - Scale 1080x1920
    - Nếu video ngắn hơn audio -> lặp video
    - Nếu dài hơn -> cắt cho khớp audio
    """
    width, height, video_dur = get_media_info(video_path)
    _, _, audio_dur = get_media_info(audio_path)
    send_discord_message(f"🎞️ Video={video_dur:.2f}s, Audio={audio_dur:.2f}s")

    aspect = width / height
    target = 9 / 16

    # Crop cho tỉ lệ dọc
    if aspect > target:
        new_width = int(height * target)
        x_offset = (width - new_width) // 2
        crop = f"crop={new_width}:{height}:{x_offset}:0"
    else:
        new_height = int(width / target)
        y_offset = (height - new_height) // 2
        crop = f"crop={width}:{new_height}:0:{y_offset}"

    # preserve original size; do not force crop/scale to 1080x1920
    filter_complex = f"[0:v]setsar=1[v];[1:a]aresample=48000[a]"

    # Nếu video ngắn hơn audio → lặp lại
    loop_cmd = []
    if video_dur < audio_dur:
        loops = math.ceil(audio_dur / video_dur)
        loop_cmd = [
        "ffmpeg", "-y",
        "-stream_loop", str(loops),
        "-i", video_path,
        "-i", audio_path,
        "-t", str(audio_dur),
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-shortest",
        "-pix_fmt", "yuv420p",
        output_path
        ]
    else:
        loop_cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-t", str(audio_dur),
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "28",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-shortest",
            "-pix_fmt", "yuv420p",
        output_path
    ]


    send_discord_message("🎬 Đang render video cuối cùng...")
    subprocess.run(loop_cmd, check=True)
    send_discord_message("✅ Xuất video hoàn tất: %s", output_path)
 

    try:     
        upload_video_to_photos(output_path)
    except json.JSONDecodeError:
        send_discord_message("Upload không thành công")

    return output_path
def safe_filename(name: str, max_length: int = 100) -> str:
    """
    Chuyển đổi tên file có dấu tiếng Việt thành không dấu, 
    loại bỏ ký tự đặc biệt để tương thích với cả Windows và Linux
    """
    import unicodedata
    
    # Bảng chuyển đổi tiếng Việt có dấu -> không dấu
    vietnamese_map = {
        'à': 'a', 'á': 'a', 'ả': 'a', 'ã': 'a', 'ạ': 'a',
        'ă': 'a', 'ằ': 'a', 'ắ': 'a', 'ẳ': 'a', 'ẵ': 'a', 'ặ': 'a',
        'â': 'a', 'ầ': 'a', 'ấ': 'a', 'ẩ': 'a', 'ẫ': 'a', 'ậ': 'a',
        'è': 'e', 'é': 'e', 'ẻ': 'e', 'ẽ': 'e', 'ẹ': 'e',
        'ê': 'e', 'ề': 'e', 'ế': 'e', 'ể': 'e', 'ễ': 'e', 'ệ': 'e',
        'ì': 'i', 'í': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ị': 'i',
        'ò': 'o', 'ó': 'o', 'ỏ': 'o', 'õ': 'o', 'ọ': 'o',
        'ô': 'o', 'ồ': 'o', 'ố': 'o', 'ổ': 'o', 'ỗ': 'o', 'ộ': 'o',
        'ơ': 'o', 'ờ': 'o', 'ớ': 'o', 'ở': 'o', 'ỡ': 'o', 'ợ': 'o',
        'ù': 'u', 'ú': 'u', 'ủ': 'u', 'ũ': 'u', 'ụ': 'u',
        'ư': 'u', 'ừ': 'u', 'ứ': 'u', 'ử': 'u', 'ữ': 'u', 'ự': 'u',
        'ỳ': 'y', 'ý': 'y', 'ỷ': 'y', 'ỹ': 'y', 'ỵ': 'y',
        'đ': 'd',
        'À': 'A', 'Á': 'A', 'Ả': 'A', 'Ã': 'A', 'Ạ': 'A',
        'Ă': 'A', 'Ằ': 'A', 'Ắ': 'A', 'Ẳ': 'A', 'Ẵ': 'A', 'Ặ': 'A',
        'Â': 'A', 'Ầ': 'A', 'Ấ': 'A', 'Ẩ': 'A', 'Ẫ': 'A', 'Ậ': 'A',
        'È': 'E', 'É': 'E', 'Ẻ': 'E', 'Ẽ': 'E', 'Ẹ': 'E',
        'Ê': 'E', 'Ề': 'E', 'Ế': 'E', 'Ể': 'E', 'Ễ': 'E', 'Ệ': 'E',
        'Ì': 'I', 'Í': 'I', 'Ỉ': 'I', 'Ĩ': 'I', 'Ị': 'I',
        'Ò': 'O', 'Ó': 'O', 'Ỏ': 'O', 'Õ': 'O', 'Ọ': 'O',
        'Ô': 'O', 'Ồ': 'O', 'Ố': 'O', 'Ổ': 'O', 'Ỗ': 'O', 'Ộ': 'O',
        'Ơ': 'O', 'Ờ': 'O', 'Ớ': 'O', 'Ở': 'O', 'Ỡ': 'O', 'Ợ': 'O',
        'Ù': 'U', 'Ú': 'U', 'Ủ': 'U', 'Ũ': 'U', 'Ụ': 'U',
        'Ư': 'U', 'Ừ': 'U', 'Ứ': 'U', 'Ử': 'U', 'Ữ': 'U', 'Ự': 'U',
        'Ỳ': 'Y', 'Ý': 'Y', 'Ỷ': 'Y', 'Ỹ': 'Y', 'Ỵ': 'Y',
        'Đ': 'D',
    }
    
    # Chuyển đổi tiếng Việt có dấu thành không dấu
    result = ''
    for char in name:
        result += vietnamese_map.get(char, char)
    
    # Loại bỏ các ký tự không phải ASCII còn lại (emoji, ký tự đặc biệt khác)
    result = unicodedata.normalize('NFKD', result)
    result = result.encode('ascii', 'ignore').decode('ascii')
    
    # Loại bỏ ký tự không hợp lệ cho filename (Windows + Linux)
    # Giữ lại: chữ cái, số, dấu gạch ngang, gạch dưới, dấu chấm, khoảng trắng
    result = re.sub(r'[^\w\s\-\.]', '_', result)
    
    # Thay nhiều khoảng trắng liên tiếp thành 1 gạch dưới
    result = re.sub(r'\s+', '_', result)
    
    # Loại bỏ nhiều gạch dưới liên tiếp
    result = re.sub(r'_+', '_', result)
    
    # Loại bỏ gạch dưới ở đầu/cuối
    result = result.strip('_')
    
    # Nếu dài quá, cắt và thêm hash ở cuối để tránh trùng
    if len(result) > max_length:
        import hashlib
        hash_suffix = hashlib.md5(name.encode()).hexdigest()[:8]
        result = result[:max_length - 9] + "_" + hash_suffix
    
    # Đảm bảo không rỗng
    if not result:
        result = "untitled"
    
    return result



def extract_slug(url: str, max_length: int = 100) -> str:
    # Bỏ phần giao thức
    url = re.sub(r"^https?://", "", url)
    # Thay các dấu đặc biệt bằng _
    name = re.sub(r"[\/\?\&\=\#\.]+", "_", url)
    # Loại bỏ dấu _ ở đầu/cuối
    name = name.strip("_")
    # Đảm bảo an toàn và không quá dài
    return safe_filename(name, max_length)
async def queue_worker(worker_id: int):
    send_discord_message(f"👷 Worker-{worker_id} started")
    while True:
        try:
            item = await TASK_QUEUE.get()
        except asyncio.CancelledError as e:
            # Worker was cancelled (graceful shutdown)
            logger.info("Worker-%s received CancelledError, exiting: %s", worker_id, e)
            break
        except Exception as e:
            # Catch unexpected errors from the queue get and log full traceback
            import traceback
            tb = traceback.format_exc()
            logger.exception("Unexpected error while getting item from TASK_QUEUE in Worker-%s: %s\n%s", worker_id, e, tb)
            # Sleep briefly to avoid busy-looping on persistent errors, then continue
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError as e:
                logger.info("Worker-%s cancelled during sleep, exiting: %s", worker_id, e)
                break
            continue

        task_id = item["task_id"]
        try:
            send_discord_message(f"👷 Worker-{worker_id} pick task {task_id}")
            # Cập nhật trạng thái chạy; also clear any 'queued' marker
            tasks = load_tasks()
            t_info = tasks.get(task_id)
            if t_info:
                t_info["status"] = "running"
                t_info["progress"] = 1
                # Remove from in-memory queued set so periodic enqueuer won't re-add
                try:
                    if task_id in QUEUED_TASK_IDS:
                        QUEUED_TASK_IDS.discard(task_id)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
                tasks[task_id] = t_info
                save_tasks(tasks)
            # item may be a facebook task and not include 'urls' or 'story_url'
            urls_preview = item.get("urls") or []
            try:
                if isinstance(urls_preview, list):
                    urls_str = ",".join(urls_preview)
                else:
                    urls_str = str(urls_preview)
            except Exception:
                urls_str = str(urls_preview)
            send_discord_message(urls_str)
            send_discord_message("Story:" + str(item.get("story_url", item.get("fb_url", ""))))
            # Route tasks by task_type (facebook, story_to_video) or fallback to generic process_task
            task_type = item.get("task_type") or item.get("type")
            # Series tasks (type=8) — route into `process_series` logic but keep
            # the existing `task_id` so UI/control continue to work.
            if (isinstance(task_type, int) and task_type == 8) or (isinstance(task_type, str) and str(task_type).lower() == "series"):
                send_discord_message(f"👷 Worker-{worker_id} handling series task {task_id}")
                try:
                    # call process_series endpoint logic directly, passing the queued params
                    await process_series(
                        start_url=item.get('start_url', ''),
                        title=item.get('title', ''),
                        max_episodes=item.get('max_episodes'),
                        run_in_background=False,
                        add_narration=item.get('add_narration', False),
                        with_subtitles=item.get('with_subtitles', True),
                        render_full=item.get('render_full', False),
                        narration_voice=item.get('narration_voice', 'vi-VN-Standard-C'),
                        narration_replace_audio=item.get('narration_replace_audio', False),
                        narration_volume_db=item.get('narration_volume_db', 8.0),
                        narration_enabled=item.get('narration_enabled', None),
                        narration_rate_dynamic=item.get('narration_rate_dynamic', 0),
                        narration_apply_fx=item.get('narration_apply_fx', 1),
                        bg_choice=item.get('bg_choice'),
                        request_id=task_id,
                        use_queue=False
                    )
                except Exception as e:
                    logger.exception("Worker-%s failed running process_series for %s: %s", worker_id, task_id, e)
                    tasks = load_tasks()
                    t = tasks.get(task_id, {})
                    t["status"] = 'error'
                    t["error"] = str(e)
                    t["progress"] = 0
                    tasks[task_id] = t
                    save_tasks(tasks)
                continue
            # YTDL Video tasks (type=9) — route into `process_video_ytdl` logic
            if (isinstance(task_type, int) and task_type == 9) or (isinstance(task_type, str) and str(task_type).lower() == "ytdl_video"):
                send_discord_message(f"👷 Worker-{worker_id} handling ytdl_video task {task_id}")
                try:
                    await process_video_ytdl(
                        video_url=item.get('video_url', ''),
                        title=item.get('title', ''),
                        run_in_background=False,
                        add_narration=item.get('add_narration', True),
                        with_subtitles=item.get('with_subtitles', True),
                        narration_voice=item.get('narration_voice', 'vi-VN-Standard-C'),
                        narration_replace_audio=item.get('narration_replace_audio', False),
                        narration_volume_db=item.get('narration_volume_db', 8.0),
                        narration_rate_dynamic=item.get('narration_rate_dynamic', 0),
                        narration_apply_fx=item.get('narration_apply_fx', 1),
                        bg_choice=item.get('bg_choice'),
                        request_id=task_id,
                        use_queue=False
                    )
                except Exception as e:
                    logger.exception("Worker-%s failed running process_video_ytdl for %s: %s", worker_id, task_id, e)
                    tasks = load_tasks()
                    t = tasks.get(task_id, {})
                    t["status"] = 'error'
                    t["error"] = str(e)
                    t["progress"] = 0
                    tasks[task_id] = t
                    save_tasks(tasks)
                continue
            # YTDL Playlist tasks (type=10) — route into `process_playlist_ytdl` logic
            if (isinstance(task_type, int) and task_type == 10) or (isinstance(task_type, str) and str(task_type).lower() == "playlist_ytdl"):
                send_discord_message(f"👷 Worker-{worker_id} handling playlist_ytdl task {task_id}")
                try:
                    await process_playlist_ytdl(
                        playlist_url=item.get('playlist_url', ''),
                        title=item.get('title', ''),
                        max_episodes=item.get('max_episodes'),
                        run_in_background=False,
                        add_narration=item.get('add_narration', True),
                        with_subtitles=item.get('with_subtitles', True),
                        render_full=item.get('render_full', False),
                        narration_voice=item.get('narration_voice', 'vi-VN-Standard-C'),
                        narration_replace_audio=item.get('narration_replace_audio', False),
                        narration_volume_db=item.get('narration_volume_db', 8.0),
                        narration_rate_dynamic=item.get('narration_rate_dynamic', 0),
                        narration_apply_fx=item.get('narration_apply_fx', 1),
                        bg_choice=item.get('bg_choice'),
                        request_id=task_id,
                        use_queue=False
                    )
                except Exception as e:
                    logger.exception("Worker-%s failed running process_playlist_ytdl for %s: %s", worker_id, task_id, e)
                    tasks = load_tasks()
                    t = tasks.get(task_id, {})
                    t["status"] = 'error'
                    t["error"] = str(e)
                    t["progress"] = 0
                    tasks[task_id] = t
                    save_tasks(tasks)
                continue
            if task_type == "story_to_video":
                # Story to Video pipeline
                await process_story_to_video_task(
                    task_id=task_id,
                    urls=item.get("urls", []),
                    title=item.get("title", ""),
                    voice=item.get("voice", ""),
                    bg_choice=item.get("bg_choice"),
                   
                    genre_params=item.get("genre_params", {})
                )
            elif task_type == "facebook":
                # Route Facebook-style tasks into the unified process_task as type=3.
                # We pass the fb url as both 'urls' and 'story_url' so process_task can
                # find the data in the task record and behave like the previous
                # process_facebook_task. This keeps task metadata format consistent.
                fb_url = item.get("fb_url")
                title_slug_fb = extract_slug(fb_url) if fb_url else item.get("title_slug")
                merged_video_path_fb = item.get("merged_video_path") or os.path.join(OUTPUT_DIR, f"{title_slug_fb}_merged.mp4")
                final_video_path_fb = item.get("final_video_path") or os.path.join(OUTPUT_DIR, f"{title_slug_fb}_video.mp4")
                await process_task(
                    task_id=task_id,
                    urls=[fb_url] if fb_url else item.get("urls", []),
                    story_url=fb_url or item.get("story_url", ""),
                    Title=item.get("title", ""),
                    merged_video_path=merged_video_path_fb,
                    final_video_path=final_video_path_fb,
                    title_slug=title_slug_fb,
                    key_file=item.get("key_file", "key.json"),
                    voice=item.get("voice", ""),
                    type=3,
                    bg_choice=item.get("bg_choice"),
                    refresh=item.get("refresh", False)
                )
            else:
                await process_task(
                    task_id=task_id,
                    urls=item.get("urls", []),
                    story_url=item.get("story_url"),
                    Title=item.get("title", ""),
                    merged_video_path=item.get("merged_video_path"),
                    final_video_path=item.get("final_video_path"),
                    title_slug=item.get("title_slug"),
                    key_file=item.get("key_file", "key.json"),
                    voice=item.get("voice", ""),
                    type=item.get("type", 1),
                    bg_choice=item.get("bg_choice"),
                    refresh=item.get("refresh", False)
                )
        except Exception as e:
            logger.exception("❌ Lỗi trong worker khi xử lý task %s: %s", task_id, e)
            tasks = load_tasks()
            t = tasks.get(task_id, {})
            t["status"] = "error"
            t["error"] = str(e)
            t["progress"] = 0
            tasks[task_id] = t
            save_tasks(tasks)
        finally:

            TASK_QUEUE.task_done()
async def process_task(task_id, urls, story_url, merged_video_path, final_video_path, title_slug, key_file="key.json",Title ="",voice: str = "",type = 1, bg_choice: str | None = None, refresh: bool = False):
    """
    Hàm thực tế xử lý 1 task — được gọi bởi worker.
    
    Args:
        refresh: Nếu True, bỏ qua cache và tạo lại audio mới
    """
    tasks = load_tasks()
    key_manager = FPTKeyManager(key_file=key_file)
    # Register running asyncio task so /task_cancel can cancel it
    try:
        cur = asyncio.current_task()
        if cur is not None:
            RUNNING_TASKS[task_id] = cur
            def _remove_on_done(fut: asyncio.Future):
                try:
                    RUNNING_TASKS.pop(task_id, None)
                except Exception:
                    pass
            try:
                cur.add_done_callback(_remove_on_done)
            except Exception:
                pass
    except Exception:
        pass
    # If this is a Facebook-only task (type==3) we should NOT fetch the story or
    # generate narration audio. Facebook flow only needs the video URL, optional
    # transform and splitting — handle it here and return early.
    if type == 3:
        t = load_tasks().get(task_id, {})
        fb_url = t.get('fb_url') or (urls[0] if urls else story_url)
        Title_fb = t.get('title', Title)
        avoid_copyright = t.get('avoid_copyright', True)
        part_time = t.get('part_time', 3600)
        overlay_logo = t.get('overlay_logo', False)

        loop = asyncio.get_event_loop()
        try:
            send_discord_message("[%s] 📥 Worker: bắt đầu tải Facebook video: %s", task_id, fb_url)

            base_name = f"fb_{url_hash(fb_url)}"
            downloaded = os.path.join(OUTPUT_DIR, f"{base_name}.mp4")

            # Download (fail fast)
            try:
                downloaded_path = await loop.run_in_executor(executor, download_video_url, fb_url, downloaded, 3, 2, None, True)
            except Exception as e:
                send_discord_message("[%s] ❌ Tải Facebook thất bại: %s", task_id, e)
                t = load_tasks().get(task_id, {})
                t["status"] = "error"
                t["error"] = str(e)
                t["progress"] = 0
                tasks = load_tasks()
                tasks[task_id] = t
                save_tasks(tasks)
                return

            t = load_tasks().get(task_id, {})
            t.setdefault("temp_videos", []).append(downloaded_path)
            t["progress"] = 20
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)

            # Tiny transform to reduce fingerprint risk
            processed = downloaded_path
            if avoid_copyright:
                processed = os.path.join(OUTPUT_DIR, f"{base_name}_mod.mp4")
                try:
                    await loop.run_in_executor(executor, enhance_video_for_copyright, downloaded_path, processed)
                except Exception as e:
                    send_discord_message("[%s] ⚠️ Transform thất bại, tiếp tục với bản gốc: %s", task_id, e)
                    processed = downloaded_path

            t = load_tasks().get(task_id, {})
            t["progress"] = 50
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)

            # Watermark/logo handling if requested
            if overlay_logo:
                try:
                    logo_out = os.path.join(OUTPUT_DIR, f"{base_name}_logo.mp4")
                    try:
                        frames, scale = await loop.run_in_executor(executor, sample_frames_for_watermark, processed, 3, 0.5, 4.0)
                    except Exception as e:
                        send_discord_message("[%s] ⚠️ Không thể trích khung hình để detect watermark: %s", task_id, e)
                        frames = []
                        scale = 1.0

                    suggestion = None
                    if frames:
                        rep = frames[len(frames)//2]
                        _, buf = cv2.imencode('.png', rep)
                        b64 = b64encode(buf.tobytes()).decode('ascii')
                        try:
                            suggestion = await loop.run_in_executor(executor, suggest_watermark_fix_with_gemini, b64, None)
                        except Exception as e:
                            send_discord_message("[%s] ⚠️ Gemini suggestion failed, falling back to local: %s", task_id, e)
                            suggestion = None

                    if not suggestion or not suggestion.get('found'):
                        try:
                            await loop.run_in_executor(executor, cover_watermark_with_logo, processed, logo_out, None)
                            processed = logo_out
                            t = load_tasks().get(task_id, {})
                            t.setdefault('temp_videos', []).append(logo_out)
                            tasks = load_tasks()
                            tasks[task_id] = t
                            save_tasks(tasks)
                        except FileNotFoundError:
                            send_discord_message("[%s] ⚠️ Không tìm thấy logo, bỏ qua overlay.", task_id)
                        except Exception as e:
                            send_discord_message("[%s] ⚠️ Lỗi overlay logo (tiếp tục): %s", task_id, e)
                    else:
                        x, y, w_box, h_box = suggestion.get('bbox')
                        inv = 1.0 / float(scale) if scale and scale != 1.0 else 1.0
                        bx = int(x * inv)
                        by = int(y * inv)
                        bw = int(w_box * inv)
                        bh = int(h_box * inv)

                        logo_path = get_logo_path()
                        logo_area = None
                        if logo_path and os.path.exists(logo_path):
                            try:
                                lg = cv2.imread(logo_path, cv2.IMREAD_UNCHANGED)
                                if lg is not None:
                                    lh, lw = lg.shape[:2]
                                    logo_area = lw * lh
                            except Exception:
                                logo_area = None
                        if not logo_area:
                            logo_area = 20000

                        bbox_area = bw * bh

                        if bbox_area > logo_area or not logo_path:
                            try:
                                await loop.run_in_executor(executor, blur_bbox_with_delogo, processed, logo_out, (bx, by, bw, bh))
                                processed = logo_out
                                t = load_tasks().get(task_id, {})
                                t.setdefault('temp_videos', []).append(logo_out)
                                tasks = load_tasks()
                                tasks[task_id] = t
                                save_tasks(tasks)
                            except Exception as e:
                                send_discord_message("[%s] ⚠️ Lỗi khi blur bbox %s: %s", task_id, (bx, by, bw, bh), e)
                        else:
                            try:
                                await loop.run_in_executor(executor, overlay_logo_on_bbox, processed, logo_out, (bx, by, bw, bh), logo_path)
                                processed = logo_out
                                t = load_tasks().get(task_id, {})
                                t.setdefault('temp_videos', []).append(logo_out)
                                tasks = load_tasks()
                                tasks[task_id] = t
                                save_tasks(tasks)
                            except Exception as e:
                                send_discord_message("[%s] ⚠️ Lỗi khi overlay logo: %s", task_id, e)

                except Exception as e:
                    send_discord_message("[%s] ⚠️ Lỗi overlay logo tổng quát (tiếp tục): %s", task_id, e)

            # Split
            try:
                split_list = await loop.run_in_executor(executor, split_video_by_time_with_title, processed, Title_fb, "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", part_time)
            except Exception as e:
                send_discord_message("[%s] ❌ Lỗi khi chia video: %s", task_id, e)
                t = load_tasks().get(task_id, {})
                t["status"] = "error"
                t["error"] = str(e)
                t["progress"] = 0
                tasks = load_tasks()
                tasks[task_id] = t
                save_tasks(tasks)
                return

            # Upload parts to Drive (best-effort)
            uploaded_results = []
            for fpath in split_list:
                try:
                    send_discord_message("[%s] 📤 Uploading to Drive: %s", task_id, fpath)
                    uploaded = await loop.run_in_executor(executor, uploadOneDrive, fpath, Title_fb)
                    link = uploaded.get('downloadLink') or uploaded.get('webViewLink')
                    t = load_tasks().get(task_id, {})
                    t.setdefault('video_file', []).append(link or uploaded.get('name'))
                    t.setdefault('temp_videos', []).append(fpath)
                    tasks = load_tasks()
                    tasks[task_id] = t
                    save_tasks(tasks)
                    uploaded_results.append(uploaded)
                except Exception as e:
                    send_discord_message("[%s] ⚠️ Upload thất bại cho %s: %s", task_id, fpath, e)
                    t = load_tasks().get(task_id, {})
                    t.setdefault('video_file', []).append(fpath)
                    tasks = load_tasks()
                    tasks[task_id] = t
                    save_tasks(tasks)

            # Finalize
            t = load_tasks().get(task_id, {})
            t['status'] = 'completed'
            t['progress'] = 100
            if split_list:
                t['video_path'] = split_list[0]
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)

            send_discord_message("[%s] ✅ Facebook task hoàn tất: %s", task_id, [u.get('id') for u in uploaded_results])
            return
        except Exception as e:
            logger.exception("[%s] Lỗi không mong muốn trong Facebook flow: %s", task_id, e)
            t = load_tasks().get(task_id, {})
            t['status'] = 'error'
            t['error'] = str(e)
            t['progress'] = 0
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)
            return
    try:
        # 1) Lấy text truyện (chạy blocking trong executor)
        send_discord_message("[%s] ✉️ Lấy nội dung truyện...", task_id)
        # If this is the convert_stt preprocessing task (type==7), do the
        # dedicated download -> transcribe -> translate -> burn flow and finish.
        if type == 7:
            try:
                send_discord_message("[%s] 📥 Worker (convert_stt): download and transcribe starting...", task_id)
              
                loop = asyncio.get_event_loop()
                video_url = (urls[0] if urls else None)
                if not video_url:
                    raise RuntimeError("No URL provided to download/transcribe for convert_stt task")

                # Download with task-specific filename for clarity
                try:
                    task_video_name = os.path.join(OUTPUT_DIR, f"{task_id}__{title_slug or 'video'}.mp4")
                except Exception:
                    task_video_name = os.path.join(OUTPUT_DIR, f"{task_id}__video.mp4")
                downloaded = await loop.run_in_executor(executor, convert_stt.download_video, video_url, task_video_name)

                # Transcribe -> produce SRT (and possibly translated SRT)
                srt_path = await loop.run_in_executor(executor, convert_stt.transcribe, downloaded)
                send_discord_message("[%s] ✅ Transcribe done: %s", task_id, srt_path)
                if not srt_path or not os.path.exists(srt_path):
                    raise RuntimeError("Worker(convert_stt): SRT generation failed or missing")

                # Ensure we prefer Vietnamese subtitles for both burn and narration.
                # If we only have Chinese SRT, attempt translation to .vi.srt.
                prefer_srt = srt_path
                try:
                    if not srt_path.endswith('.vi.srt'):
                        vi_candidate = srt_path[:-4] + '.vi.srt' if srt_path.lower().endswith('.srt') else srt_path + '.vi.srt'
                        if not os.path.exists(vi_candidate):
                            try:
                                from srt_translate import translate_srt_file
                                api_key = os.environ.get('GEMINI_API_KEY_Translate') or os.environ.get('GOOGLE_TTS_API_KEY')
                                model = "gemini-2.5-flash-lite"
                                ctx = int(os.environ.get('SRT_CTX_WIN', '2'))
                                translated = await loop.run_in_executor(
                                    executor,
                                    translate_srt_file,
                                    srt_path,
                                    vi_candidate
                                   
                                )
                                if translated and os.path.exists(translated):
                                    prefer_srt = translated
                                    send_discord_message("[%s] ✅ Vietnamese SRT created: %s", task_id, translated)
                                else:
                                    prefer_srt = srt_path
                            except Exception:
                                prefer_srt = srt_path
                        else:
                            prefer_srt = vi_candidate
                            send_discord_message("[%s] ♻️ Using existing Vietnamese SRT: %s", task_id, vi_candidate)
                    else:
                        prefer_srt = srt_path
                except Exception:
                    prefer_srt = srt_path

                # Burn subtitles using ASS for better styling
                tiktok_video = os.path.splitext(downloaded)[0] + ".tiktok.mp4"
                try:
                    from convert_srt_to_ass import convert as convert_srt_to_ass_convert
                except Exception:
                    convert_srt_to_ass_convert = None

                try:
                    # Use Vietnamese SRT if available for nicer burn
                    burn_srt = prefer_srt
                    ass_path = burn_srt.replace('.srt', '.ass')
                    if convert_srt_to_ass_convert:
                        # Use TikTok-friendly defaults
                        await loop.run_in_executor(
                            executor,
                            convert_srt_to_ass_convert,
                            burn_srt,
                            ass_path,
                            30,
                            11,
                            "Noto Sans",
                            20,
                            150
                        )
                    else:
                        # Fallback: simple ffmpeg SRT->ASS conversion
                        try:
                            subprocess.run(["ffmpeg", "-y", "-i", burn_srt, ass_path], check=True)
                        except Exception:
                            ass_path = burn_srt
                
                    # Scale/pad to 1080x1920 and burn ASS subtitles
                    send_discord_message("[%s] 🔥 Burning subtitles to video (ASS)", task_id)
                    # Build a robust ffmpeg subtitles filter for Windows paths
                    # Use libass 'filename=' form and quote the path
                    def ffmpeg_sub_filter(ass_path: str) -> str:
                        p = Path(ass_path).resolve().as_posix()
                        # Escape drive colon for ffmpeg filter args (E\:/...)
                        p = p.replace(":", r"\:")
                        # Quote the filename to avoid parsing issues
                        return f"subtitles=filename='{p}'"
                    
                    sub_filter = ffmpeg_sub_filter(ass_path)

                    cmd = [
                        "ffmpeg", "-y",
                        "-i", downloaded,
                        "-vf",
                            # keep original size, just apply subtitles
                            sub_filter,
                        "-c:a", "copy",
                        tiktok_video
                    ]
                    print(cmd)
                    # Run ffmpeg in executor with check=True
                    await loop.run_in_executor(executor, lambda: subprocess.run(cmd, check=True))
                    send_discord_message("[%s] ✅ Burned subtitles: %s", task_id, tiktok_video)
                except Exception as e:
                    send_discord_message("[%s] ⚠️ Worker(convert_stt): burn subtitles (ASS) failed: %s", task_id, e)

                # Optional: create narration similar to process_series
                try:
                    t_params = load_tasks().get(task_id, {})
                    _add_narr = bool(t_params.get('add_narration')) if 'add_narration' in t_params else False
                    if _add_narr:
                        narr_voice = t_params.get('narration_voice') or 'vi-VN-Standard-C'
                        narr_replace = bool(t_params.get('narration_replace_audio')) if 'narration_replace_audio' in t_params else False
                        # Default narration boost to +6 dB if not specified
                        narr_vol = float(t_params.get('narration_volume_db')) if 'narration_volume_db' in t_params else 6.0

                        # Prefer Vietnamese SRT for narration
                        use_srt = prefer_srt if os.path.exists(prefer_srt) else (srt_path if os.path.exists(srt_path) else None)
                        if use_srt:
                            nar_tmp = os.path.join(OUTPUT_DIR, f"{task_id}__{title_slug or 'video'}.nar.flac")
                            try:
                                send_discord_message("[%s] 🎙️ Building narration from SRT: %s", task_id, use_srt)
                                nar_audio, _meta = await loop.run_in_executor(
                                    executor,
                                    narration_from_srt.build_narration_schedule,
                                    use_srt,
                                    nar_tmp,
                                    narr_voice,
                                    1.28,
                                    0.0,
                                    None,
                                    False
                                )
                            except Exception as e:
                                send_discord_message("[%s] ⚠️ Worker(convert_stt): build narration failed: %s", task_id, e)
                                nar_audio = None

                            if nar_audio and os.path.exists(nar_audio):
                                narr_out = os.path.join(OUTPUT_DIR, f"{task_id}__{title_slug or 'video'}.narr.mp4")
                                try:
                                    send_discord_message("[%s] 🔊 Mixing narration (vol=%sdB, video=%sdB)...", task_id, narr_vol, -4.0)
                                    await loop.run_in_executor(
                                        executor,
                                        narration_from_srt.mix_narration_into_video,
                                        tiktok_video if os.path.exists(tiktok_video) else downloaded,
                                        nar_audio,
                                        narr_out,
                                        narr_vol,
                                        narr_replace,
                                        True,
                                        0.0,
                                        -4.0
                                    )
                                    tiktok_video = narr_out
                                    send_discord_message("[%s] ✅ Worker(convert_stt): narration mixed: %s", task_id, narr_out)
                                except Exception as e:
                                    send_discord_message("[%s] ⚠️ Worker(convert_stt): mix narration failed: %s", task_id, e)
                except Exception as e:
                    send_discord_message("[%s] ⚠️ Worker(convert_stt): narration step error: %s", task_id, e)

                # Name files with task_id + title_slug for clarity
                try:
                    named_srt = os.path.join(OUTPUT_DIR, f"{task_id}__{title_slug}.srt")
                    os.replace(srt_path, named_srt)
                    srt_path = named_srt
                except Exception as e:
                    _report_and_ignore(e, "ignored")
                try:
                    named_tiktok = os.path.join(OUTPUT_DIR, f"{task_id}__{title_slug}.tiktok.mp4")
                    if os.path.exists(tiktok_video):
                        os.replace(tiktok_video, named_tiktok)
                        tiktok_video = named_tiktok
                except Exception as e:
                    _report_and_ignore(e, "ignored")
                # Update task record and finish
                t = load_tasks().get(task_id, {})
                t['downloaded_video'] = downloaded
                t['srt_file'] = srt_path
                t['burned_video'] = tiktok_video
                t['prebuilt_srt'] = True
                t['srt_path'] = srt_path
                t['request_urls'] = [video_url, f"file://{srt_path}"]
                t['status'] = 'completed'
                t['progress'] = 100
                tasks = load_tasks(); tasks[task_id] = t; save_tasks(tasks)
                # Announce sandbox links and upload to Drive (best-effort)
                try:
                    if os.path.exists(tiktok_video):
                        rel = to_project_relative_posix(tiktok_video)
                        view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                        download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                        send_discord_message("🎥 Xem video:" + view_link)
                        send_discord_message("⬇️ Tải video:" + download_link)
                        try:
                            uploaded = uploadOneDrive(tiktok_video, title_slug if 'title_slug' in locals() else None)
                            link = uploaded.get('downloadLink') or uploaded.get('webViewLink')
                            if link:
                                # send_discord_message("📤 Drive:" + link)
                                t = load_tasks().get(task_id, {})
                                t.setdefault('video_file', []).append(link)
                                tasks = load_tasks(); tasks[task_id] = t; save_tasks(tasks)
                        except Exception as e:
                            _report_and_ignore(e, "ignored")
                except Exception as e:
                    _report_and_ignore(e, "ignored")
                send_discord_message("[%s] ✅ Worker(convert_stt): completed", task_id)
                return
            except Exception as e:
                logger.exception("[%s] Worker(convert_stt) failed: %s", task_id, e)
                t = load_tasks().get(task_id, {})
                t['status'] = 'error'
                t['error'] = str(e)
                t['progress'] = 0
                tasks = load_tasks(); tasks[task_id] = t; save_tasks(tasks)
                return
        # Try cached text first (cache key: text_{md5(url)}.txt)
        text = ""
        summary = ""
        try:
            cache_file = None
            if isinstance(story_url, str):
                try:
                    cache_file = os.path.join(CACHE_DIR, f"text_{url_hash(story_url)}.txt")
                except Exception:
                    cache_file = None

            if cache_file and os.path.exists(cache_file):
                send_discord_message("♻️ Dùng cache text: %s", cache_file)
                with open(cache_file, "r", encoding="utf-8") as fh:
                    text = fh.read()
                summary = ""
            elif isinstance(story_url, str) and story_url.startswith("file://"):
                local_path = story_url[len("file://"):]
                # If the provided local path is an SRT, treat it as prebuilt subtitles
                # and DO NOT use the SRT content as story text for TTS generation.
                if os.path.exists(local_path):
                    if local_path.lower().endswith('.srt'):
                        send_discord_message("♻️ Detected prebuilt SRT for task: %s", local_path)
                        # Mark the task record so downstream logic can skip TTS
                        t = load_tasks().get(task_id, {})
                        t['prebuilt_srt'] = True
                        t['srt_path'] = local_path
                        tasks = load_tasks(); tasks[task_id] = t; save_tasks(tasks)
                        # Ensure text/summary are empty so we don't accidentally TTS the SRT content
                        text = ""
                        summary = ""
                    else:
                        with open(local_path, "r", encoding="utf-8") as fh:
                            text = fh.read()
                        summary = ""
                else:
                    send_discord_message("⚠️ Local story file not found: %s", local_path)
                    # fallback to remote fetch
                    text, summary = await asyncio.get_event_loop().run_in_executor(executor, get_novel_text, story_url)
            else:
                text, summary = await asyncio.get_event_loop().run_in_executor(executor, get_novel_text, story_url)
        except Exception:
            # Ensure we always attempt remote fetch on unexpected errors
            text, summary = await asyncio.get_event_loop().run_in_executor(executor, get_novel_text, story_url)

        # cập nhật progress
        tasks = load_tasks()
        t = tasks.get(task_id, {})
        t["progress"] = 5
        save_tasks(tasks)
        
        # 2) Tạo audio - hỗ trợ cả luồng Gemini (generate_audio_Gemini) hoặc luồng mặc định (summary + content)
        # Cache files (dùng cho luồng mặc định)
        # NOTE: these paths may be voice-specific; we'll set default legacy names
        # and then recompute them once any voice override is known below.
        summary_audio_path = os.path.join(OUTPUT_DIR, f"{title_slug}_summary.wav")
        content_audio_path = os.path.join(OUTPUT_DIR, f"{title_slug}_content.wav")
        combined_audio_path = os.path.join(OUTPUT_DIR, f"{title_slug}.wav")

        IsBase = "0"

        # Kiểm tra xem task được yêu cầu dùng Gemini TTS hay không
        tasks = load_tasks()
        t = tasks.get(task_id, {})
        # Do not rely on task flag 'use_gemini' — decide solely from voice.
        use_gemini = False
        # default prepare callable to safe fallback
        prepare_audio_callable = prepare_audio_for_video
        # Optional override: force voice via task record or function param
        # priority: force_voice > voice (task) > style > function param
        selected_voice = (t.get('force_voice') or t.get('voice') or t.get('style') or voice or "")
        selected_voice = (selected_voice or "").lower()

        # choose gemini voice / prepare-audio variant based on selected voice
        gemini_voice = None
        if selected_voice == 'gman':
            use_gemini = True
            gemini_voice = "vi-VN-Standard-D"
            prepare_audio_callable = prepare_audio_for_video_gemini_male
        elif selected_voice == 'gfemale':
            use_gemini = True
            gemini_voice = "vi-VN-Standard-C"
            prepare_audio_callable = prepare_audio_for_video_gemini
        elif selected_voice in ('echo', 'nova'):
            prepare_audio_callable = prepare_audio_for_video
        else:
            prepare_audio_callable = prepare_audio_for_video_gemini if use_gemini else prepare_audio_for_video
    
        # keep compatibility variable name used later
        voice_override = selected_voice or None
        # If a voice override exists, prefer voice-specific cached filenames
        # (keep legacy names as fallback). This mirrors naming in `tts.py`.
        if voice_override:
            if voice_override == 'gman':
                suffix ="_vi-VN-Standard-D"
            elif voice_override == 'gfemale':
                suffix = "_vi-VN-Standard-C"
            else:
                suffix = f"_{voice_override}"
          
            summary_audio_path = os.path.join(OUTPUT_DIR, f"{title_slug}_summary{suffix}.wav")
            content_audio_path = os.path.join(OUTPUT_DIR, f"{title_slug}_content{suffix}.wav")
            combined_audio_path = os.path.join(OUTPUT_DIR, f"{title_slug}{suffix}.wav")
        include_summary_override = t.get('include_summary') if 'include_summary' in t else None

        # If the task provided a prebuilt SRT, prefer using provided video/audio
        # instead of generating TTS. We expect the endpoint that enqueued this
        # task to include a 'provided_video' or 'downloaded_video' field pointing
        # to a local video file from which audio can be extracted.
        if t.get('prebuilt_srt'):
            provided_video = t.get('provided_video') or t.get('downloaded_video') or None
            if provided_video and os.path.exists(provided_video):
                try:
                    provided_audio = os.path.join(OUTPUT_DIR, f"{title_slug}_{task_id}.wav")
                    send_discord_message("[%s] 🔉 Extracting audio from provided video: %s", task_id, provided_video)
                    loop = asyncio.get_event_loop()
                    audio_file = await loop.run_in_executor(executor, extract_audio_from_video, provided_video, provided_audio)
                    audio_path = audio_file
                    IsBase = "1"
                    t = load_tasks().get(task_id, {})
                    t['audio_path'] = audio_path
                    t['progress'] = 40
                    tasks = load_tasks(); tasks[task_id] = t; save_tasks(tasks)
                    send_discord_message("[%s] ✅ Extracted audio for prebuilt SRT: %s", task_id, audio_path)
                except Exception as e:
                    send_discord_message("[%s] ⚠️ Failed to extract audio from provided video: %s", task_id, e)
                    # Fall back to normal TTS flow if extraction fails
                    pass

        if use_gemini:
            # Dùng Gemini TTS cho toàn bộ nội dung (một file duy nhất)
            send_discord_message("[%s] 🪄 Sử dụng Gemini TTS để tạo audio (generate_audio_Gemini)...", task_id)
            # If we selected a specific Gemini voice for the chosen voice, pass it through
            if gemini_voice:
                audio_file = await asyncio.get_event_loop().run_in_executor(
                    executor,
                    generate_audio_Gemini,
                    text,
                    title_slug,
                    gemini_voice
                )
            else:
                audio_file = await asyncio.get_event_loop().run_in_executor(
                    executor,
                    generate_audio_Gemini,
                    text,
                    title_slug,
                )
            if not audio_file or not os.path.exists(audio_file):
                raise RuntimeError("Không tạo được file audio từ Gemini")
            send_discord_message("[%s] ✅ Gemini audio tạo thành công: %s", task_id, audio_file)
            # By default use the Gemini-generated audio as the audio path
            audio_path = audio_file
            # If we have a separate summary and it is not present in the main text,
            # generate a summary audio (using existing OpenAI summary TTS) and
            # prepend it to the Gemini audio so final output includes the summary.
            try:
                skip_summary = False
                if summary and summary.strip() and type != 6 and text:
                    if is_summary_in_content(summary, text):
                        send_discord_message("⚠️ Văn án đã có trong nội dung, bỏ qua gắn summary (Gemini flow)")
                        skip_summary = True

                    if not skip_summary:
                        summary_audio = None
                        # Use cached summary audio if present
                        if os.path.exists(summary_audio_path):
                            summary_audio = summary_audio_path
                            send_discord_message("♻️ Dùng cache summary audio (Gemini flow): %s", summary_audio)
                        else:
                            try:
                                if voice_override:
                                    summary_audio = await asyncio.get_event_loop().run_in_executor(
                                        executor, generate_audio_summary, summary, title_slug, voice_override
                                    )
                                else:
                                    summary_audio = await asyncio.get_event_loop().run_in_executor(
                                        executor, generate_audio_summary, summary, title_slug
                                    )
                            except Exception as e:
                                send_discord_message(f"⚠️ Không thể tạo audio summary cho Gemini flow: {e}")
                                summary_audio = None

                        if summary_audio and os.path.exists(summary_audio):
                            combined = combined_audio_path
                            try:
                                audio_path = await asyncio.get_event_loop().run_in_executor(
                                    executor, combine_audio_files, summary_audio, audio_file, combined
                                )
                                send_discord_message("✅ Đã gắn summary + Gemini audio -> %s", audio_path)
                            except Exception as e:
                                send_discord_message(f"⚠️ Không thể ghép summary + Gemini audio: {e}")
                                # fallback: keep original Gemini audio
                                audio_path = audio_file
            except Exception as e:
                # Best-effort: do not fail the whole task because summary handling failed
                send_discord_message(f"⚠️ Lỗi khi xử lý summary trong Gemini flow: {e}")

            IsBase = "1"
            t = load_tasks().get(task_id, {})
            t['audio_path'] = audio_path
            t['progress'] = 40
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)
        else:
            # Luồng mặc định: tách summary + content, hỗ trợ cache và refresh
            summary_exists = os.path.exists(summary_audio_path)
            content_exists = os.path.exists(content_audio_path)
            combined_exists = os.path.exists(combined_audio_path)

            if not refresh:
                # Nếu đã có combined cache, dùng luôn
                if combined_exists:
                    send_discord_message("♻️ Dùng cache audio hoàn chỉnh: %s", combined_audio_path)
                    IsBase = "1"
                    audio_path = combined_audio_path
                # Nếu có content cache (cho type 6 - no summary)
                elif content_exists and type == 6:
                    send_discord_message("♻️ Dùng cache audio content (no summary): %s", content_audio_path)
                    IsBase = "1"
                    audio_path = content_audio_path
                else:
                    # Tạo mới
                    IsBase = "1"
                    send_discord_message("[%s] 🔊 Tạo audio riêng biệt (summary + content)...", task_id)

                    # Kiểm tra xem văn án có nằm trong nội dung không
                    skip_summary = False
                    if summary and summary.strip() and text:
                        if is_summary_in_content(summary, text):
                            send_discord_message("⚠️ Văn án đã có trong nội dung, bỏ qua tạo audio văn án")
                            skip_summary = True

                    # Tạo summary audio (nếu có và không phải type 6 và chưa có trong content)
                    summary_audio = None
                    if summary and summary.strip() and type != 6 and not skip_summary:
                        if not summary_exists:
                            if voice_override:
                                summary_audio = await asyncio.get_event_loop().run_in_executor(
                                    executor, generate_audio_summary, summary, title_slug, voice_override
                                )
                            else:
                                summary_audio = await asyncio.get_event_loop().run_in_executor(
                                    executor, generate_audio_summary, summary, title_slug
                                )
                        else:
                            summary_audio = summary_audio_path
                            send_discord_message("♻️ Dùng cache summary audio")

                    # Tạo content audio
                    if not content_exists:
                        if voice_override:
                            content_audio = await asyncio.get_event_loop().run_in_executor(
                                executor, generate_audio_content, text, title_slug, voice_override
                            )
                        else:
                            content_audio = await asyncio.get_event_loop().run_in_executor(
                                executor, generate_audio_content, text, title_slug
                            )
                    else:
                        content_audio = content_audio_path
                        send_discord_message("♻️ Dùng cache content audio")

                    # Nối summary + content (hoặc chỉ content nếu type 6 hoặc skip_summary)
                    if type == 6 or skip_summary or not summary_audio:
                        # Type 6 hoặc văn án đã có trong content: chỉ dùng content
                        audio_path = content_audio
                    else:
                        # Type khác: nối summary + content
                        audio_path = await asyncio.get_event_loop().run_in_executor(
                            executor, combine_audio_files, summary_audio, content_audio, combined_audio_path
                        )
            else:
                # Refresh: tạo lại toàn bộ
                IsBase = "1"
                send_discord_message("[%s] 🔄 Refresh: Tạo lại audio mới...", task_id)

                # Kiểm tra xem văn án có nằm trong nội dung không
                skip_summary = False
                if summary and summary.strip() and text:
                    if is_summary_in_content(summary, text):
                        send_discord_message("⚠️ Văn án đã có trong nội dung, bỏ qua tạo audio văn án")
                        skip_summary = True

                # Tạo summary audio (nếu có và không phải type 6 và chưa có trong content)
                summary_audio = None
                if summary and summary.strip() and type != 6 and not skip_summary:
                    if voice_override:
                        summary_audio = await asyncio.get_event_loop().run_in_executor(
                            executor, generate_audio_summary, summary, title_slug, voice_override
                        )
                    else:
                        summary_audio = await asyncio.get_event_loop().run_in_executor(
                            executor, generate_audio_summary, summary, title_slug
                        )

                # Tạo content audio
                if voice_override:
                    content_audio = await asyncio.get_event_loop().run_in_executor(
                        executor, generate_audio_content, text, title_slug, voice_override
                    )
                else:
                    content_audio = await asyncio.get_event_loop().run_in_executor(
                        executor, generate_audio_content, text, title_slug
                    )

                # Nối summary + content (hoặc chỉ content nếu type 6 hoặc skip_summary)
                if type == 6 or skip_summary or not summary_audio:
                    audio_path = content_audio
                else:
                    audio_path = await asyncio.get_event_loop().run_in_executor(
                        executor, combine_audio_files, summary_audio, content_audio, combined_audio_path
                    )

            tasks = load_tasks()
            t = tasks.get(task_id, {})
            t["progress"] = 40
            tasks[task_id] = t
            save_tasks(tasks)

        # --- Type 3: Facebook download + optional transform + split/upload ---
        if type == 3:
            # Read facebook-specific params from the task record (saved by endpoint)
            t = load_tasks().get(task_id, {})
            fb_url = t.get('fb_url') or (urls[0] if urls else story_url)
            Title_fb = t.get('title', Title)
            avoid_copyright = t.get('avoid_copyright', True)
            part_time = t.get('part_time', 3600)
            overlay_logo = t.get('overlay_logo', False)

            loop = asyncio.get_event_loop()
            try:
                send_discord_message("[%s] 📥 Worker: bắt đầu tải Facebook video: %s", task_id, fb_url)

                base_name = f"fb_{url_hash(fb_url)}"
                downloaded = os.path.join(OUTPUT_DIR, f"{base_name}.mp4")

                # Download (fail fast)
                try:
                    downloaded_path = await loop.run_in_executor(executor, download_video_url, fb_url, downloaded, 3, 2, None, True)
                except Exception as e:
                    send_discord_message("[%s] ❌ Tải Facebook thất bại: %s", task_id, e)
                    t = load_tasks().get(task_id, {})
                    t["status"] = "error"
                    t["error"] = str(e)
                    t["progress"] = 0
                    tasks = load_tasks()
                    tasks[task_id] = t
                    save_tasks(tasks)
                    return

                t = load_tasks().get(task_id, {})
                t.setdefault("temp_videos", []).append(downloaded_path)
                t["progress"] = 20
                tasks = load_tasks()
                tasks[task_id] = t
                save_tasks(tasks)

                # Tiny transform to reduce fingerprint risk
                processed = downloaded_path
                if avoid_copyright:
                    processed = os.path.join(OUTPUT_DIR, f"{base_name}_mod.mp4")
                    try:
                        await loop.run_in_executor(executor, enhance_video_for_copyright, downloaded_path, processed)
                    except Exception as e:
                        send_discord_message("[%s] ⚠️ Transform thất bại, tiếp tục với bản gốc: %s", task_id, e)
                        processed = downloaded_path

                t = load_tasks().get(task_id, {})
                t["progress"] = 50
                tasks = load_tasks()
                tasks[task_id] = t
                save_tasks(tasks)

                # Watermark/logo handling if requested
                if overlay_logo:
                    try:
                        logo_out = os.path.join(OUTPUT_DIR, f"{base_name}_logo.mp4")
                        try:
                            frames, scale = await loop.run_in_executor(executor, sample_frames_for_watermark, processed, 3, 0.5, 4.0)
                        except Exception as e:
                            send_discord_message("[%s] ⚠️ Không thể trích khung hình để detect watermark: %s", task_id, e)
                            frames = []
                            scale = 1.0

                        suggestion = None
                        if frames:
                            rep = frames[len(frames)//2]
                            _, buf = cv2.imencode('.png', rep)
                            b64 = b64encode(buf.tobytes()).decode('ascii')
                            try:
                                suggestion = await loop.run_in_executor(executor, suggest_watermark_fix_with_gemini, b64, None)
                            except Exception as e:
                                send_discord_message("[%s] ⚠️ Gemini suggestion failed, falling back to local: %s", task_id, e)
                                suggestion = None

                        if not suggestion or not suggestion.get('found'):
                            try:
                                await loop.run_in_executor(executor, cover_watermark_with_logo, processed, logo_out, None)
                                processed = logo_out
                                t = load_tasks().get(task_id, {})
                                t.setdefault('temp_videos', []).append(logo_out)
                                tasks = load_tasks()
                                tasks[task_id] = t
                                save_tasks(tasks)
                            except FileNotFoundError:
                                send_discord_message("[%s] ⚠️ Không tìm thấy logo, bỏ qua overlay.", task_id)
                            except Exception as e:
                                send_discord_message("[%s] ⚠️ Lỗi overlay logo (tiếp tục): %s", task_id, e)
                        else:
                            x, y, w_box, h_box = suggestion.get('bbox')
                            inv = 1.0 / float(scale) if scale and scale != 1.0 else 1.0
                            bx = int(x * inv)
                            by = int(y * inv)
                            bw = int(w_box * inv)
                            bh = int(h_box * inv)

                            logo_path = get_logo_path()
                            logo_area = None
                            if logo_path and os.path.exists(logo_path):
                                try:
                                    lg = cv2.imread(logo_path, cv2.IMREAD_UNCHANGED)
                                    if lg is not None:
                                        lh, lw = lg.shape[:2]
                                        logo_area = lw * lh
                                except Exception:
                                    logo_area = None
                            if not logo_area:
                                logo_area = 20000

                            bbox_area = bw * bh

                            if bbox_area > logo_area or not logo_path:
                                try:
                                    await loop.run_in_executor(executor, blur_bbox_with_delogo, processed, logo_out, (bx, by, bw, bh))
                                    processed = logo_out
                                    t = load_tasks().get(task_id, {})
                                    t.setdefault('temp_videos', []).append(logo_out)
                                    tasks = load_tasks()
                                    tasks[task_id] = t
                                    save_tasks(tasks)
                                except Exception as e:
                                    send_discord_message("[%s] ⚠️ Lỗi khi blur bbox %s: %s", task_id, (bx, by, bw, bh), e)
                            else:
                                try:
                                    await loop.run_in_executor(executor, overlay_logo_on_bbox, processed, logo_out, (bx, by, bw, bh), logo_path)
                                    processed = logo_out
                                    t = load_tasks().get(task_id, {})
                                    t.setdefault('temp_videos', []).append(logo_out)
                                    tasks = load_tasks()
                                    tasks[task_id] = t
                                    save_tasks(tasks)
                                except Exception as e:
                                    send_discord_message("[%s] ⚠️ Lỗi khi overlay logo: %s", task_id, e)

                    except Exception as e:
                        send_discord_message("[%s] ⚠️ Lỗi overlay logo tổng quát (tiếp tục): %s", task_id, e)

                # Split
                try:
                    split_list = await loop.run_in_executor(executor, split_video_by_time_with_title, processed, Title_fb, "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", part_time)
                except Exception as e:
                    send_discord_message("[%s] ❌ Lỗi khi chia video: %s", task_id, e)
                    t = load_tasks().get(task_id, {})
                    t["status"] = "error"
                    t["error"] = str(e)
                    t["progress"] = 0
                    tasks = load_tasks()
                    tasks[task_id] = t
                    save_tasks(tasks)
                    return

                # Upload parts to Drive (best-effort)
                uploaded_results = []
                for fpath in split_list:
                    try:
                        send_discord_message("[%s] 📤 Uploading to Drive: %s", task_id, fpath)
                        uploaded = await loop.run_in_executor(executor, uploadOneDrive, fpath, Title_fb)
                        link = uploaded.get('downloadLink') or uploaded.get('webViewLink')
                        t = load_tasks().get(task_id, {})
                        t.setdefault('video_file', []).append(link or uploaded.get('name'))
                        t.setdefault('temp_videos', []).append(fpath)
                        tasks = load_tasks()
                        tasks[task_id] = t
                        save_tasks(tasks)
                        uploaded_results.append(uploaded)
                    except Exception as e:
                        send_discord_message("[%s] ⚠️ Upload thất bại cho %s: %s", task_id, fpath, e)
                        t = load_tasks().get(task_id, {})
                        t.setdefault('video_file', []).append(fpath)
                        tasks = load_tasks()
                        tasks[task_id] = t
                        save_tasks(tasks)

                # Finalize
                t = load_tasks().get(task_id, {})
                t['status'] = 'completed'
                t['progress'] = 100
                if split_list:
                    t['video_path'] = split_list[0]
                tasks = load_tasks()
                tasks[task_id] = t
                save_tasks(tasks)

                send_discord_message("[%s] ✅ Facebook task hoàn tất: %s", task_id, [u.get('id') for u in uploaded_results])
                return
            except Exception as e:
                logger.exception("[%s] Lỗi không mong muốn trong Facebook flow: %s", task_id, e)
                t = load_tasks().get(task_id, {})
                t['status'] = 'error'
                t['error'] = str(e)
                t['progress'] = 0
                tasks = load_tasks()
                tasks[task_id] = t
                save_tasks(tasks)
                return

        # 3) Download video(s) SEQUENTIALLY (one-at-a-time) to avoid concurrent downloads within a task
        loop = asyncio.get_event_loop()
        temp_files = []
        video_paths = []
        
        # --- Type 4: TikTok Large Video (chia audio trước, render từng part) ---
        if type == 4:
            send_discord_message("[%s] 🎬 TikTok Large Video flow: Chia audio → Render từng part...", task_id)
            
            # Lấy params từ task record
            t = load_tasks().get(task_id, {})
            part_duration = int(t.get('part_duration', 3600) or 3600)
            part_duration = max(1, min(part_duration, 3600))
            start_from_part = t.get('start_from_part', 1)
            
            # 1. Chuẩn bị audio cho video (tăng tốc + mix nhạc nền)
            if IsBase == "1":
                send_discord_message("[%s] 🎵 Xử lý audio (tăng tốc + nhạc nền)...", task_id)
                processed_audio = await loop.run_in_executor(executor, prepare_audio_callable, audio_path, bg_choice, 6.0)
            else:
                processed_audio = audio_path
            
            t = load_tasks().get(task_id, {})
            t["progress"] = 45
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)
            
            # 2. Chia audio thành các part
            send_discord_message("[%s] ✂️ Chia audio thành các part...", task_id)
            # Prefer TTS-generated parts (Gemini/OpenAI) if they exist — but to
            # keep behavior consistent we concatenate then produce a processed
            # master FLAC and split that master. We'll track whether split parts
            # were generated so we can delete them while preserving original
            # per-TTS files.
           
            split_generated_from_processed = False
         
            processed_master = processed_audio
            audio_parts = await loop.run_in_executor(
                executor,
                split_audio_by_duration,
                processed_master,
                part_duration,
                OUTPUT_DIR
            )
            split_generated_from_processed = True
            
            total_parts = len(audio_parts)
            send_discord_message("[%s] 📊 Tổng số part: %d", task_id, total_parts)
            
            t = load_tasks().get(task_id, {})
            t["progress"] = 50
            t["total_parts"] = total_parts
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)
            
            # 3. Xử lý video nguồn
            # Nếu không có URLs → sẽ lấy random từ cache cho mỗi part (tránh lặp lại)
            # Nếu có URLs → tải video về
            use_cache = not urls or (len(urls) == 1 and not urls[0])
            
            if use_cache:
                send_discord_message("[%s] 📦 Không có video URL, mỗi part sẽ random từ cache...", task_id)
                # Kiểm tra cache có video không
                try:
                    cached_videos = [
                        os.path.join(VIDEO_CACHE_DIR, f) 
                        for f in os.listdir(VIDEO_CACHE_DIR) 
                        if f.lower().endswith('.mp4')
                    ]
                    if not cached_videos:
                        raise RuntimeError("Không có video nào trong cache để sử dụng")
                    
                    # Lưu danh sách cache vào video_paths để truyền cho mỗi part
                    video_paths = cached_videos
                    send_discord_message("[%s] ✅ Tìm thấy %d video trong cache", task_id, len(cached_videos))
                except Exception as e:
                    send_discord_message("[%s] ❌ Lỗi lấy video từ cache: %s", task_id, e)
                    raise
            else:
                # Có URLs → tải video
                send_discord_message("[%s] 📥 Tải video nguồn...", task_id)
                for idx, url in enumerate(urls, 1):
                    out_name = os.path.join(task_output_dir, f"temp_{title_slug}_{idx}.mp4")
                    temp_files.append(out_name)
                    
                    if re.search(r"https?://", url, re.I):
                        try:
                            # Tải video với thời lượng match với audio part đầu tiên
                            _, _, first_audio_dur = get_media_info(audio_parts[0])
                            path = await loop.run_in_executor(
                                executor,
                                download_video_url,
                                url, out_name, 3, 2, first_audio_dur,
                                is_facebook_url(url)
                            )
                            video_paths.append(path)
                        except Exception as e:
                            send_discord_message("[%s] ❌ Lỗi tải video %s: %s", task_id, url, e)
                            raise
                    else:
                        video_paths.append(url)
            
            t = load_tasks().get(task_id, {})
            t["temp_videos"] = temp_files
            t["progress"] = 60
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)
            
            # 4. Render từng video part (mỗi part sẽ random chọn video từ video_paths)
            output_parts = []
            video_files = []
            # unique suffix so final part filenames are new per render
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            suffix = f"_{task_id}_{ts}"
            
            for i in range(start_from_part - 1, total_parts):
                part_num = i + 1
                audio_part = audio_parts[i]
                output_part = os.path.join(task_output_dir, f"{title_slug}_part{part_num}{suffix}.mp4")
                
                send_discord_message("[%s] 🎬 Render part %d/%d...", task_id, part_num, total_parts)
                
                try:
                    # Mỗi part sẽ nhận toàn bộ video_paths và tự random chọn
                    rendered_part = await loop.run_in_executor(
                        executor,
                        render_tiktok_video_from_audio_part,
                        video_paths,
                        audio_part,
                        output_part,
                        Title,
                        part_num,
                        total_parts,
                        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
                    )
                    
                    output_parts.append(rendered_part)
                    
                    # Upload lên Drive
                    try:
                        send_discord_message("[%s] 📤 Upload part %d lên Drive...", task_id, part_num)
                        uploaded = await loop.run_in_executor(executor, uploadOneDrive, rendered_part, Title)
                        
                        link = uploaded.get('downloadLink') or uploaded.get('webViewLink')
                        # video_files.append(link or uploaded.get('name'))
                    except Exception as e:
                        send_discord_message("[%s] ⚠️ Upload thất bại part %d: %s", task_id, part_num, e)
                        # video_files.append(rendered_part)
                    video_files.append(f"https://sandbox.travel.com.vn/api/download-video?download=1&video_name="+quote_plus(to_project_relative_posix(rendered_part)))
                    send_discord_message("🎥 Xem video:"+"https://sandbox.travel.com.vn/api/download-video?video_name="+quote_plus(to_project_relative_posix(rendered_part)))
                    send_discord_message(f"⬇️ Tải video:"+"https://sandbox.travel.com.vn/api/download-video?download=1&video_name="+quote_plus(to_project_relative_posix(rendered_part)))
                    # Cập nhật progress
                    progress = 60 + int((part_num / total_parts) * 35)
                    t = load_tasks().get(task_id, {})
                    t["progress"] = progress
                    t["current_part"] = part_num
                    t["video_file"] = video_files
                    tasks = load_tasks()
                    tasks[task_id] = t
                    save_tasks(tasks)
                    
                except Exception as e:
                    send_discord_message("[%s] ❌ Lỗi render part %d: %s", task_id, part_num, e)
                    t = load_tasks().get(task_id, {})
                    t["status"] = "error"
                    t["error"] = f"Lỗi tại part {part_num}: {str(e)}"
                    t["last_successful_part"] = part_num - 1 if part_num > 1 else 0
                    t["resume_from_part"] = part_num
                    tasks = load_tasks()
                    tasks[task_id] = t
                    save_tasks(tasks)
                    raise
            
            # 5. Hoàn tất
            send_discord_message("[%s] ✅ Hoàn tất tất cả %d part!", task_id, total_parts)
            
            t = load_tasks().get(task_id, {})
            t["status"] = "completed"
            t["progress"] = 100
            t["video_file"] = video_files
            t["output_parts"] = output_parts
            if output_parts:
                t["video_path"] = output_parts[0]
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)
            
            # Add to TikTok upload queue if requested
            try:
                _add_videos_to_tiktok_queue(task_id, output_parts, t)
            except Exception as e:
                _report_and_ignore(e, "add to tiktok queue")
            
            # Cleanup temp files. We DO NOT keep generated split audio parts; only
            # preserve original per‑TTS parts. If split parts were generated from
            # a processed master during this run, remove them and the processed master.
            for f in temp_files:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
            # Remove split audio parts and processed master if they were generated
            try:
                if 'audio_parts' in locals() and split_generated_from_processed:
                    for p in audio_parts:
                        try:
                            if os.path.exists(p):
                                os.remove(p)
                        except Exception as e:
                            _report_and_ignore(e, "ignored")
                if 'processed_master' in locals() and processed_master and os.path.exists(processed_master):
                    try:
                        os.remove(processed_master)
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
                # Remove temp concat artifacts if present
                if 'concat_list' in locals() and os.path.exists(concat_list):
                    try:
                        os.remove(concat_list)
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
                if 'combined_tts_wav' in locals() and os.path.exists(combined_tts_wav):
                    try:
                        os.remove(combined_tts_wav)
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
                # Also remove intermediate summary/content WAVs if they exist
                if 'summary_audio_path' in locals() and summary_audio_path and os.path.exists(summary_audio_path):
                    try:
                        os.remove(summary_audio_path)
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
                if 'content_audio_path' in locals() and content_audio_path and os.path.exists(content_audio_path):
                    try:
                        os.remove(content_audio_path)
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
            except Exception as e:
                _report_and_ignore(e, "ignored")
            send_discord_message("[%s] ✅ TikTok Large Video task hoàn tất", task_id)
            return
        
        # --- Type 5: TikTok Large Video (chỉ render các part cụ thể) ---
        if type == 5:
            send_discord_message("[%s] 🎬 TikTok Large Video (Specific Parts) flow...", task_id)
            
            # Lấy params từ task record
            t = load_tasks().get(task_id, {})
            part_duration = int(t.get('part_duration', 3600) or 3600)
            part_duration = max(1, min(part_duration, 3600))
            parts_to_render = t.get('parts_to_render', [])
            
            if not parts_to_render:
                raise ValueError("Không có part nào được chỉ định để render")
            
            send_discord_message("[%s] 📋 Sẽ render các part: %s", task_id, ", ".join(map(str, parts_to_render)))
            
            # 1. Chuẩn bị audio cho video (tăng tốc + mix nhạc nền)
            if IsBase == "1":
                send_discord_message("[%s] 🎵 Xử lý audio (tăng tốc + nhạc nền)...", task_id)
                processed_audio = await loop.run_in_executor(executor, prepare_audio_callable, audio_path, bg_choice, 6.0)
            else:
                processed_audio = audio_path
            
            t = load_tasks().get(task_id, {})
            t["progress"] = 45
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)
            
            # 2. Chia audio thành các part
            send_discord_message("[%s] ✂️ Chia audio thành các part...", task_id)
           
            
          
            processed_master = processed_audio
            audio_parts = await loop.run_in_executor(
                executor,
                split_audio_by_duration,
                processed_master,
                part_duration,
                    OUTPUT_DIR
            )
            split_generated_from_processed = True           
            total_parts = len(audio_parts)
            send_discord_message("[%s] 📊 Tổng số part: %d", task_id, total_parts)           
            # Kiểm tra các part được yêu cầu có hợp lệ không
            invalid_parts = [p for p in parts_to_render if p > total_parts or p < 1]
            if invalid_parts:
                send_discord_message(
                    "[%s] ⚠️ Cảnh báo: Các part không hợp lệ sẽ bị bỏ qua: %s (tổng chỉ có %d part)",
                    task_id, ", ".join(map(str, invalid_parts)), total_parts
                )
                parts_to_render = [p for p in parts_to_render if 1 <= p <= total_parts]
            
            if not parts_to_render:
                raise ValueError(f"Không có part hợp lệ nào để render (tổng có {total_parts} part)")
            
            t = load_tasks().get(task_id, {})
            t["progress"] = 50
            t["total_parts"] = total_parts
            t["parts_to_render"] = parts_to_render
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)
            
            # 3. Xử lý video nguồn
            # Nếu không có URLs → sẽ lấy random từ cache cho mỗi part (tránh lặp lại)
            # Nếu có URLs → tải video về
            use_cache = not urls or (len(urls) == 1 and not urls[0])
            
            if use_cache:
                send_discord_message("[%s] 📦 Không có video URL, mỗi part sẽ random từ cache...", task_id)
                # Kiểm tra cache có video không
                try:
                    cached_videos = [
                        os.path.join(VIDEO_CACHE_DIR, f) 
                        for f in os.listdir(VIDEO_CACHE_DIR) 
                        if f.lower().endswith('.mp4')
                    ]
                    if not cached_videos:
                        raise RuntimeError("Không có video nào trong cache để sử dụng")
                    
                    # Lưu danh sách cache vào video_paths để truyền cho mỗi part
                    video_paths = cached_videos
                    send_discord_message("[%s] ✅ Tìm thấy %d video trong cache", task_id, len(cached_videos))
                except Exception as e:
                    send_discord_message("[%s] ❌ Lỗi lấy video từ cache: %s", task_id, e)
                    raise
            else:
                # Có URLs → tải video
                send_discord_message("[%s] 📥 Tải video nguồn...", task_id)
                # Lấy part đầu tiên trong danh sách để tính duration
                first_part_idx = min(parts_to_render) - 1
                for idx, url in enumerate(urls, 1):
                    out_name = os.path.join(task_output_dir, f"temp_{title_slug}_{idx}.mp4")
                    temp_files.append(out_name)
                    
                    if re.search(r"https?://", url, re.I):
                        try:
                            # Tải video với thời lượng match với audio part đầu tiên cần render
                            _, _, first_audio_dur = get_media_info(audio_parts[first_part_idx])
                            path = await loop.run_in_executor(
                                executor,
                                download_video_url,
                                url, out_name, 3, 2, first_audio_dur,
                                is_facebook_url(url)
                            )
                            video_paths.append(path)
                        except Exception as e:
                            send_discord_message("[%s] ❌ Lỗi tải video %s: %s", task_id, url, e)
                            raise
                    else:
                        video_paths.append(url)
            
            t = load_tasks().get(task_id, {})
            t["temp_videos"] = temp_files
            t["progress"] = 60
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)
            
            # 4. CHỈ RENDER CÁC VIDEO PART ĐƯỢC CHỈ ĐỊNH
            output_parts = []
            video_files = []
            # unique suffix so final part filenames are new per render
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            suffix = f"_{task_id}_{ts}"
            
            for part_num in sorted(parts_to_render):
                audio_part = audio_parts[part_num - 1]  # Convert to 0-indexed
                output_part = os.path.join(task_output_dir, f"{title_slug}_part{part_num}{suffix}.mp4")
                
                send_discord_message("[%s] 🎬 Render part %d/%d (part %d/%d được chỉ định)...", 
                                   task_id, parts_to_render.index(part_num) + 1, len(parts_to_render), part_num, total_parts)
                
                try:
                    # Mỗi part sẽ nhận toàn bộ video_paths và tự random chọn
                    rendered_part = await loop.run_in_executor(
                        executor,
                        render_tiktok_video_from_audio_part,
                        video_paths,
                        audio_part,
                        output_part,
                        Title,
                        part_num,
                        total_parts,
                        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
                    )
                    
                    output_parts.append(rendered_part)
                    
                    # Upload lên Drive
                    try:
                        send_discord_message("[%s] 📤 Upload part %d lên Drive...", task_id, part_num)
                        uploaded = await loop.run_in_executor(executor, uploadOneDrive, rendered_part, Title)
                    
                        link = uploaded.get('downloadLink') or uploaded.get('webViewLink')
                        # video_files.append(link or uploaded.get('name'))
                    except Exception as e:
                        send_discord_message("[%s] ⚠️ Upload thất bại part %d: %s", task_id, part_num, e)
                        # video_files.append(rendered_part)
                    video_files.append(f"https://sandbox.travel.com.vn/api/download-video?download=1&video_name="+quote_plus(to_project_relative_posix(rendered_part)))
                    send_discord_message("🎥 Xem video:"+"https://sandbox.travel.com.vn/api/download-video?video_name="+quote_plus(to_project_relative_posix(rendered_part)))
                    send_discord_message(f"⬇️ Tải video:"+"https://sandbox.travel.com.vn/api/download-video?download=1&video_name="+quote_plus(to_project_relative_posix(rendered_part)))
                    # Cập nhật progress
                    completed_count = parts_to_render.index(part_num) + 1
                    progress = 60 + int((completed_count / len(parts_to_render)) * 35)
                    t = load_tasks().get(task_id, {})
                    t["progress"] = progress
                    t["current_part"] = part_num
                    t["video_file"] = video_files
                    tasks = load_tasks()
                    tasks[task_id] = t
                    save_tasks(tasks)
                    
                except Exception as e:
                    send_discord_message("[%s] ❌ Lỗi render part %d: %s", task_id, part_num, e)
                    t = load_tasks().get(task_id, {})
                    t["status"] = "error"
                    t["error"] = f"Lỗi tại part {part_num}: {str(e)}"
                    t["last_successful_part"] = part_num - 1 if part_num > 1 else 0
                    tasks = load_tasks()
                    tasks[task_id] = t
                    save_tasks(tasks)
                    raise
            
            # 5. Hoàn tất
            send_discord_message("[%s] ✅ Hoàn tất tất cả %d part được chỉ định!", task_id, len(parts_to_render))
            
            t = load_tasks().get(task_id, {})
            t["status"] = "completed"
            t["progress"] = 100
            t["video_file"] = video_files
            t["output_parts"] = output_parts
            if output_parts:
                t["video_path"] = output_parts[0]
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)
            
            # Add to TikTok upload queue if requested
            try:
                _add_videos_to_tiktok_queue(task_id, output_parts, t)
            except Exception as e:
                _report_and_ignore(e, "add to tiktok queue")
            
            # Cleanup temp files
            for f in temp_files:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
            # Remove generated split audio parts and processed master (do not
            # remove original per‑TTS parts). Also clean intermediate files.
            try:
                if 'audio_parts' in locals() and split_generated_from_processed:
                    for p in audio_parts:
                        try:
                            if os.path.exists(p):
                                os.remove(p)
                        except Exception as e:
                            _report_and_ignore(e, "ignored")
                if 'processed_master' in locals() and processed_master and os.path.exists(processed_master):
                    try:
                        os.remove(processed_master)
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
                if 'concat_list' in locals() and os.path.exists(concat_list):
                    try:
                        os.remove(concat_list)
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
                if 'combined_tts_wav' in locals() and os.path.exists(combined_tts_wav):
                    try:
                        os.remove(combined_tts_wav)
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
            except Exception as e:
                _report_and_ignore(e, "ignored")
            send_discord_message("[%s] ✅ TikTok Large Video (Specific Parts) task hoàn tất", task_id)
            return
        
        # --- Type 6: TikTok Large Video (No Summary - chỉ lấy nội dung truyện) ---
        if type == 6:
            send_discord_message("[%s] 🎬 TikTok Large Video (No Summary) flow: Chỉ lấy nội dung truyện...", task_id)
            
            # Lấy params từ task record
            t = load_tasks().get(task_id, {})
            part_duration = int(t.get('part_duration', 3600) or 3600)
            part_duration = max(1, min(part_duration, 3600))
            start_from_part = t.get('start_from_part', 1)
            task_output_dir = t.get('output_dir') or OUTPUT_DIR
            os.makedirs(task_output_dir, exist_ok=True)
            
            # Audio đã được tạo ở phần chung (chỉ content, không có summary)
            # audio_path đã có sẵn từ logic chung ở trên
            send_discord_message("[%s] ✅ Sử dụng audio content (đã bỏ văn án)", task_id)
            tasks[task_id] = t
            save_tasks(tasks)
            
            # 1. Chuẩn bị audio cho video (tăng tốc + mix nhạc nền)
            if IsBase == "1":
                send_discord_message("[%s] 🎵 Xử lý audio (tăng tốc + nhạc nền)...", task_id)
                processed_audio = await loop.run_in_executor(executor, prepare_audio_callable, audio_path, bg_choice, 6.0)
            else:
                processed_audio = audio_path
            
            t = load_tasks().get(task_id, {})
            t["progress"] = 45
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)
            
            # 2. Chia audio thành các part
            send_discord_message("[%s] ✂️ Chia audio thành các part...", task_id)
            tts_parts = get_tts_part_files(title_slug, task_output_dir)
            split_generated_from_processed = False
            processed_master = None
            if tts_parts:
                send_discord_message("♻️ Tìm thấy per-TTS phần audio (%d), sẽ concat -> process -> split for rendering", len(tts_parts))
                concat_list = os.path.join(task_output_dir, f"{title_slug}_tts_concat.txt")
                combined_tts_wav = os.path.join(task_output_dir, f"{title_slug}_tts_combined.wav")
                await loop.run_in_executor(executor, _write_concat_list, tts_parts, concat_list)
                await loop.run_in_executor(executor, _concat_audio_from_list, concat_list, combined_tts_wav)
                processed_master = await loop.run_in_executor(executor, prepare_audio_callable, combined_tts_wav, bg_choice, 6.0)
                if not processed_master or not os.path.exists(processed_master):
                    raise RuntimeError(f"Không tạo được processed master audio từ per-TTS parts: {processed_master}")
                audio_parts = await loop.run_in_executor(
                    executor,
                    split_audio_by_duration,
                    processed_master,
                    part_duration,
                    task_output_dir
                )
                split_generated_from_processed = True
            else:
                processed_master = processed_audio
                audio_parts = await loop.run_in_executor(
                    executor,
                    split_audio_by_duration,
                    processed_master,
                    part_duration,
                    task_output_dir
                )
                split_generated_from_processed = True
            
            total_parts = len(audio_parts)
            send_discord_message("[%s] 📊 Tổng số part: %d", task_id, total_parts)
            
            t = load_tasks().get(task_id, {})
            t["progress"] = 50
            t["total_parts"] = total_parts
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)
            
            # 3. Xử lý video nguồn (giống type 4)
            use_cache = not urls or (len(urls) == 1 and not urls[0])
            
            if use_cache:
                send_discord_message("[%s] 📦 Không có video URL, mỗi part sẽ random từ cache...", task_id)
                try:
                    cached_videos = [
                        os.path.join(VIDEO_CACHE_DIR, f) 
                        for f in os.listdir(VIDEO_CACHE_DIR) 
                        if f.lower().endswith('.mp4')
                    ]
                    if not cached_videos:
                        raise RuntimeError("Không có video nào trong cache để sử dụng")
                    
                    video_paths = cached_videos
                    send_discord_message("[%s] ✅ Tìm thấy %d video trong cache", task_id, len(cached_videos))
                except Exception as e:
                    send_discord_message("[%s] ❌ Lỗi lấy video từ cache: %s", task_id, e)
                    raise
            else:
                send_discord_message("[%s] 📥 Tải video nguồn...", task_id)
                for idx, url in enumerate(urls, 1):
                    out_name = os.path.join(task_output_dir, f"temp_{title_slug}_{idx}.mp4")
                    temp_files.append(out_name)
                    
                    if re.search(r"https?://", url, re.I):
                        try:
                            _, _, first_audio_dur = get_media_info(audio_parts[0])
                            path = await loop.run_in_executor(
                                executor,
                                download_video_url,
                                url, out_name, 3, 2, first_audio_dur,
                                is_facebook_url(url)
                            )
                            video_paths.append(path)
                        except Exception as e:
                            send_discord_message("[%s] ❌ Lỗi tải video %s: %s", task_id, url, e)
                            raise
                    else:
                        video_paths.append(url)
            
            t = load_tasks().get(task_id, {})
            t["temp_videos"] = temp_files
            t["progress"] = 60
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)
            
            # 4. Render từng video part
            output_parts = []
            video_files = []
            # unique suffix so final part filenames are new per render
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            suffix = f"_{task_id}_{ts}"

            for i in range(start_from_part - 1, total_parts):
                part_num = i + 1
                audio_part = audio_parts[i]
                output_part = os.path.join(task_output_dir, f"{title_slug}_part{part_num}{suffix}.mp4")
                
                send_discord_message("[%s] 🎬 Render part %d/%d...", task_id, part_num, total_parts)
                
                try:
                    rendered_part = await loop.run_in_executor(
                        executor,
                        render_tiktok_video_from_audio_part,
                        video_paths,
                        audio_part,
                        output_part,
                        Title,
                        part_num,
                        total_parts,
                        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
                    )
                    
                    output_parts.append(rendered_part)
                    
                    try:
                        send_discord_message("[%s] 📤 Upload part %d lên Drive...", task_id, part_num)
                        uploaded = await loop.run_in_executor(executor, uploadOneDrive, rendered_part, Title)
                  
                        link = uploaded.get('downloadLink') or uploaded.get('webViewLink')
                        # video_files.append(link or uploaded.get('name'))
                    except Exception as e:
                        send_discord_message("[%s] ⚠️ Upload thất bại part %d: %s", task_id, part_num, e)
                        # video_files.append(rendered_part)
                    video_files.append(f"https://sandbox.travel.com.vn/api/download-video?download=1&video_name="+quote_plus(to_project_relative_posix(rendered_part)))
                    send_discord_message("🎥 Xem video:"+"https://sandbox.travel.com.vn/api/download-video?video_name="+quote_plus(to_project_relative_posix(rendered_part)))
                    send_discord_message(f"⬇️ Tải video:"+"https://sandbox.travel.com.vn/api/download-video?download=1&video_name="+quote_plus(to_project_relative_posix(rendered_part)))
                    progress = 60 + int((part_num / total_parts) * 35)
                    t = load_tasks().get(task_id, {})
                    t["progress"] = progress
                    t["current_part"] = part_num
                    t["video_file"] = video_files
                    tasks = load_tasks()
                    tasks[task_id] = t
                    save_tasks(tasks)
                    
                except Exception as e:
                    send_discord_message("[%s] ❌ Lỗi render part %d: %s", task_id, part_num, e)
                    t = load_tasks().get(task_id, {})
                    t["status"] = "error"
                    t["error"] = f"Lỗi tại part {part_num}: {str(e)}"
                    t["last_successful_part"] = part_num - 1 if part_num > 1 else 0
                    t["resume_from_part"] = part_num
                    tasks = load_tasks()
                    tasks[task_id] = t
                    save_tasks(tasks)
                    raise
            
            # 5. Hoàn tất
            send_discord_message("[%s] ✅ Hoàn tất tất cả %d part!", task_id, total_parts)
            
            t = load_tasks().get(task_id, {})
            t["status"] = "completed"
            t["progress"] = 100
            t["video_file"] = video_files
            t["output_parts"] = output_parts
            if output_parts:
                t["video_path"] = output_parts[0]
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)
            
            # Add to TikTok upload queue if requested
            try:
                _add_videos_to_tiktok_queue(task_id, output_parts, t)
            except Exception as e:
                _report_and_ignore(e, "add to tiktok queue")
            
            # Cleanup
            for f in temp_files:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
            # Remove generated split audio parts and processed master (do not
            # remove original per‑TTS parts). Also clean intermediate files.
            try:
                if 'audio_parts' in locals() and split_generated_from_processed:
                    for p in audio_parts:
                        try:
                            if os.path.exists(p):
                                os.remove(p)
                        except Exception as e:
                            _report_and_ignore(e, "ignored")
                if 'processed_master' in locals() and processed_master and os.path.exists(processed_master):
                    try:
                        os.remove(processed_master)
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
                if 'concat_list' in locals() and os.path.exists(concat_list):
                    try:
                        os.remove(concat_list)
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
                if 'combined_tts_wav' in locals() and os.path.exists(combined_tts_wav):
                    try:
                        os.remove(combined_tts_wav)
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
            except Exception as e:
                _report_and_ignore(e, "ignored")
            send_discord_message("[%s] ✅ TikTok Large Video (No Summary) task hoàn tất", task_id)
            return
        
        # --- Type 1: TikTok Normal (render toàn bộ rồi chia) ---
        if type == 1:
            # compute audio duration so we can request clips that match audio length
            try:
                _, _, audio_dur = get_media_info(audio_path)
            except Exception:
                audio_dur = None

            send_discord_message("[%s] 📥 Bắt đầu tải video nguồn (tuần tự) ...", task_id)
            for idx, url in enumerate(urls, 1):
                out_name = os.path.join(OUTPUT_DIR, f"temp_{title_slug}_{idx}.mp4")
                temp_files.append(out_name)
                if re.search(r"https?://", url, re.I):
                    fb = is_facebook_url(url)
                    # Run download in executor but await each one sequentially
                    try:
                        if audio_dur:
                            path = await loop.run_in_executor(executor, download_video_url, url, out_name, 3, 2, audio_dur, fb)
                        else:
                            path = await loop.run_in_executor(executor, download_video_url, url, out_name, 3, 2, None, fb)
                        video_paths.append(path)
                    except Exception as e:
                        # propagate error for fail-fast behavior (caller expects exception)
                        send_discord_message("[%s] ❌ Tải video thất bại (tuần tự) cho %s: %s", task_id, url, e)
                        raise
                else:
                    # local path or already a file
                    video_paths.append(url)
            # cập nhật task info files
            tasks = load_tasks()
            t = tasks.get(task_id, {})
            t["temp_videos"] = temp_files
            t["progress"] = 60
            save_tasks(tasks)
            # 4) Chuẩn bị audio cho video (tăng tốc, filter, mix background)
            if IsBase == "1":           
                send_discord_message("[%s] 🎵 Chuẩn bị audio cho video (mix nhạc nền)...", task_id)
                processed_audio = await loop.run_in_executor(executor, prepare_audio_callable, audio_path, bg_choice, 6.0)
            else:       
                processed_audio = audio_path          
            # 5) Concat & combine (chạy blocking)      
            list = await loop.run_in_executor(executor, concat_crop_audio_with_titles, video_paths, processed_audio, final_video_path, Title)
            # 6) Hoàn tất
            tasks = load_tasks()
            uploadList = []
            for file in list:           
                send_discord_message("🎥 Xem video:"+"https://sandbox.travel.com.vn/api/download-video?video_name="+quote_plus(to_project_relative_posix(file)))
                send_discord_message(f"⬇️ Tải video:"+"https://sandbox.travel.com.vn/api/download-video?download=1&video_name="+quote_plus(to_project_relative_posix(file)))
                uploadList.append(f"https://sandbox.travel.com.vn/api/download-video?video_name="+quote_plus(to_project_relative_posix(file)))
        else:
            # Type 2: YouTube với video được tạo (Veo3, v.v.)
            # Goal: create ONE horizontal master clip ~audio_duration (e.g. ~1h30) by looping the Veo3 base
            # clip, then run the YouTube-oriented renderer (concat_crop_audio_youtube) to avoid creating many
            # small temporary clips and reduce disk churn. Finally upload parts directly to YouTube.
            send_discord_message("[%s] 🎬 YouTube flow: tạo clip nền Veo3 và mở rộng thành 1 file dài...", task_id)

            # 1) generate/get a base veo3 clip
            base_clip = generatevideoveo3(title_slug)

            # 2) prepare audio (mix bg if needed)
            send_discord_message("[%s] 🎵 Chuẩn bị audio cho video YouTube (mix nhạc nền)...", task_id)
            if IsBase == "1":
                processed_audio = await loop.run_in_executor(executor, prepare_audio_callable, audio_path, bg_choice, 6.0)
            else:
                processed_audio = audio_path

            # 3) ensure we have a single long horizontal clip matching audio duration
            try:
                _, _, audio_dur = get_media_info(processed_audio)
            except Exception:
                audio_dur = None

            long_clip = os.path.join(OUTPUT_DIR, f"{title_slug}_veo3_long.mp4")

            # Decide target duration: if audio > 1h30 (5400s) use 5400s, otherwise use audio length
            if audio_dur and audio_dur > 5400:
                target_duration = 5400
            elif audio_dur and audio_dur > 0:
                target_duration = audio_dur
            else:
                # fallback default when audio duration unknown
                target_duration = 5400

            # If an existing long clip is already sufficient, reuse it
            reuse_ok = False
            try:
                if os.path.exists(long_clip):
                    _, _, existing_dur = get_media_info(long_clip)
                    if existing_dur >= max(0.98 * target_duration, target_duration - 1.0):
                        reuse_ok = True
                        send_discord_message("♻️ Dùng lại long veo3 clip hiện có: %s (dur=%.1fs)", long_clip, existing_dur)
            except Exception:
                reuse_ok = False

            if not reuse_ok:
                # create long clip by looping base_clip to target_duration
                send_discord_message("🔁 Tạo long clip bằng cách lặp clip nền: %s -> %s (target=%.1fs)", base_clip, long_clip, target_duration or 0)
                try:
                    # probe base clip
                    try:
                        _, _, base_dur = get_media_info(base_clip)
                    except Exception:
                        base_dur = None

                    if base_dur and base_dur > 0:
                        loops = math.ceil(target_duration / base_dur)
                        # stream_loop with copy may be fastest; if it fails we'll fallback to re-encode
                        cmd = [
                            "ffmpeg", "-y",
                            "-stream_loop", str(max(0, loops - 1)),
                            "-i", base_clip,
                            "-t", str(target_duration),
                            "-c", "copy",
                            long_clip
                        ]
                        try:
                            subprocess.run(cmd, check=True, capture_output=True)
                        except subprocess.CalledProcessError:
                            # fallback: re-encode to ensure compatibility
                            cmd2 = [
                                "ffmpeg", "-y",
                                "-stream_loop", str(max(0, loops - 1)),
                                "-i", base_clip,
                                "-t", str(target_duration),
                                "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080",
                                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                                "-c:a", "aac", "-b:a", "128k",
                                long_clip
                            ]
                            subprocess.run(cmd2, check=True)
                    else:
                        # As a last resort just copy the base clip
                        shutil.copy(base_clip, long_clip)

                except Exception as e:
                    send_discord_message("⚠️ Không thể tạo long clip tự động, dùng base clip: %s", e)
                    # fallback to base clip
                    long_clip = base_clip

            # 4) Render using YouTube-optimized pipeline (horizontal 16:9)
            try:
                listOutputs = await loop.run_in_executor(
                    executor,
                    concat_crop_audio_youtube,
                    [long_clip],
                    processed_audio,
                    final_video_path,
                    Title
                )
            except Exception as e:
                send_discord_message("⚠️ YouTube render failed: %s. Falling back to single-pass render.", e)
                # Fallback: try single-pass renderer
                try:
                    listOutputs = await loop.run_in_executor(
                        executor,
                        render_add_audio_and_split,
                        [long_clip],
                        processed_audio,
                        final_video_path,
                        Title,
                        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
                        43200
                    )
                except Exception as e2:
                    send_discord_message("❌ All render attempts failed: %s", e2)
                    raise

            uploadList = []
            # Upload parts to YouTube directly
            for i, out_path in enumerate(listOutputs):
                if len(listOutputs) == 1:
                    part_title = f"[FULL] {Title.upper()}"
                else:
                    part_title = f"[PHẦN {i+1}] - {Title.upper()}"

                upload_video(
                    file_path=out_path,
                    title=part_title,
                    description=summary,
                    category="Entertainment",
                    privacy="public",
                    tags=["truyenaudio", "truyenhay", "giaitri"]
                )

                send_discord_message("🎥 Xem video:"+"https://sandbox.travel.com.vn/api/download-video?video_name="+quote_plus(to_project_relative_posix(out_path)))
                send_discord_message(f"⬇️ Tải video:"+"https://sandbox.travel.com.vn/api/download-video?download=1&video_name="+quote_plus(to_project_relative_posix(out_path)))
                uploadList.append(f"https://sandbox.travel.com.vn/api/download-video?video_name="+quote_plus(to_project_relative_posix(out_path)))

        t = tasks.get(task_id, {})
        t["status"] = "completed"
        t["progress"] = 100
        t["video_path"] = final_video_path
        t["video_file"]=uploadList
        save_tasks(tasks)

        # Xóa temp files
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
        # Remove final combined WAV/FLAC and intermediate summary/content WAVs (keep per-part audio files)
        try:
            if 'combined_audio_path' in locals() and combined_audio_path and os.path.exists(combined_audio_path):
                os.remove(combined_audio_path)
        except Exception as e:
            _report_and_ignore(e, "ignored")
        try:
            final_flac = os.path.join(OUTPUT_DIR, f"{title_slug}.flac")
            if os.path.exists(final_flac):
                os.remove(final_flac)
        except Exception as e:
            _report_and_ignore(e, "ignored")
        try:
            if 'summary_audio_path' in locals() and summary_audio_path and os.path.exists(summary_audio_path):
                os.remove(summary_audio_path)
        except Exception as e:
            _report_and_ignore(e, "ignored")
        try:
            if 'content_audio_path' in locals() and content_audio_path and os.path.exists(content_audio_path):
                os.remove(content_audio_path)
        except Exception as e:
            _report_and_ignore(e, "ignored")
        send_discord_message("[%s] ✅ Task hoàn tất", task_id)
    except Exception as e:
        logger.exception("[%s] Lỗi trong process_task: %s", task_id, e)
        tasks = load_tasks()
        t = tasks.get(task_id, {})
        t["status"] = "error"
        t["error"] = str(e)
        t["progress"] = 0
        tasks[task_id] = t
        save_tasks(tasks)
        raise

async def process_facebook_task(task_id: str, fb_url: str, Title: str = "", avoid_copyright: bool = True, part_time: int = 3600, overlay_logo: bool = False, key_file: str = "key.json"):
    """Worker handler to process a Facebook-download task (runs in the worker loop).

    Downloads the FB video, optionally applies tiny transform, optionally overlays logo,
    splits into parts, uploads parts to Drive, and updates the task record.
    """
    tasks = load_tasks()
    t = tasks.get(task_id, {})
    t["status"] = "running"
    t["progress"] = 1
    t.setdefault("temp_videos", [])
    t.setdefault("video_file", [])
    tasks[task_id] = t
    save_tasks(tasks)

    loop = asyncio.get_event_loop()
    try:
        send_discord_message("[%s] 📥 Worker: bắt đầu tải Facebook video: %s", task_id, fb_url)

        base_name = f"fb_{url_hash(fb_url)}"
        downloaded = os.path.join(OUTPUT_DIR, f"{base_name}.mp4")

        # Download (fail fast)
        try:
            downloaded_path = await loop.run_in_executor(executor, download_video_url, fb_url, downloaded, 3, 2, None, True)
        except Exception as e:
            send_discord_message("[%s] ❌ Tải Facebook thất bại: %s", task_id, e)
            t = load_tasks().get(task_id, {})
            t["status"] = "error"
            t["error"] = str(e)
            t["progress"] = 0
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)
            return

        t = load_tasks().get(task_id, {})
        t.setdefault("temp_videos", []).append(downloaded_path)
        t["progress"] = 20
        tasks = load_tasks()
        tasks[task_id] = t
        save_tasks(tasks)

        # Tiny transform
        processed = downloaded_path
        if avoid_copyright:
            processed = os.path.join(OUTPUT_DIR, f"{base_name}_mod.mp4")
            try:
                await loop.run_in_executor(executor, enhance_video_for_copyright, downloaded_path, processed)
            except Exception as e:
                send_discord_message("[%s] ⚠️ Transform thất bại, tiếp tục với bản gốc: %s", task_id, e)
                processed = downloaded_path

        t = load_tasks().get(task_id, {})
        t["progress"] = 50
        tasks = load_tasks()
        tasks[task_id] = t
        save_tasks(tasks)

        # Overlay logo if requested: detect all static watermark regions locally,
        # blur the larger ones and place the logo at a single chosen small region.
        if overlay_logo:
            try:
                logo_out = os.path.join(OUTPUT_DIR, f"{base_name}_logo.mp4")

                # New flow: try Gemini suggestion (or local fallback) on a representative frame,
                # then apply a single fix across the whole video (only one logo per video).
                try:
                    frames, scale = await loop.run_in_executor(executor, sample_frames_for_watermark, processed, 3, 0.5, 4.0)
                except Exception as e:
                    send_discord_message("[%s] ⚠️ Không thể trích khung hình để detect watermark: %s", task_id, e)
                    frames = []
                    scale = 1.0

                suggestion = None
                if frames:
                    rep = frames[len(frames)//2]
                    _, buf = cv2.imencode('.png', rep)
                    b64 = b64encode(buf.tobytes()).decode('ascii')
                    try:
                        suggestion = await loop.run_in_executor(executor, suggest_watermark_fix_with_gemini, b64, None)
                    except Exception as e:
                        send_discord_message("[%s] ⚠️ Gemini suggestion failed, falling back to local: %s", task_id, e)
                        suggestion = None

                # If Gemini/local found nothing, fallback to placing a logo centrally (cover_watermark_with_logo)
                if not suggestion or not suggestion.get('found'):
                    try:
                        await loop.run_in_executor(executor, cover_watermark_with_logo, processed, logo_out, None)
                        processed = logo_out
                        t = load_tasks().get(task_id, {})
                        t.setdefault('temp_videos', []).append(logo_out)
                        tasks = load_tasks()
                        tasks[task_id] = t
                        save_tasks(tasks)
                    except FileNotFoundError:
                        send_discord_message("[%s] ⚠️ Không tìm thấy logo, bỏ qua overlay.", task_id)
                    except Exception as e:
                        send_discord_message("[%s] ⚠️ Lỗi overlay logo (tiếp tục): %s", task_id, e)
                else:
                    # Use returned bbox (relative to sampled frame). Scale to full video coords.
                    x, y, w_box, h_box = suggestion.get('bbox')
                    inv = 1.0 / float(scale) if scale and scale != 1.0 else 1.0
                    bx = int(x * inv)
                    by = int(y * inv)
                    bw = int(w_box * inv)
                    bh = int(h_box * inv)

                    # Determine logo path and pixel area
                    logo_path = get_logo_path()
                    logo_area = None
                    if logo_path and os.path.exists(logo_path):
                        try:
                            lg = cv2.imread(logo_path, cv2.IMREAD_UNCHANGED)
                            if lg is not None:
                                lh, lw = lg.shape[:2]
                                logo_area = lw * lh
                        except Exception:
                            logo_area = None
                    if not logo_area:
                        logo_area = 20000

                    bbox_area = bw * bh

                    # Decide: if watermark bigger than logo -> blur; else overlay logo
                    if bbox_area > logo_area or not logo_path:
                        # blur the found bbox across the whole video
                        try:
                            await loop.run_in_executor(executor, blur_bbox_with_delogo, processed, logo_out, (bx, by, bw, bh))
                            processed = logo_out
                            t = load_tasks().get(task_id, {})
                            t.setdefault('temp_videos', []).append(logo_out)
                            tasks = load_tasks()
                            tasks[task_id] = t
                            save_tasks(tasks)
                        except Exception as e:
                            send_discord_message("[%s] ⚠️ Lỗi khi blur bbox %s: %s", task_id, (bx, by, bw, bh), e)
                    else:
                        # overlay logo scaled to bbox across the whole video
                        try:
                            await loop.run_in_executor(executor, overlay_logo_on_bbox, processed, logo_out, (bx, by, bw, bh), logo_path)
                            processed = logo_out
                            t = load_tasks().get(task_id, {})
                            t.setdefault('temp_videos', []).append(logo_out)
                            tasks = load_tasks()
                            tasks[task_id] = t
                            save_tasks(tasks)
                        except Exception as e:
                            send_discord_message("[%s] ⚠️ Lỗi khi overlay logo: %s", task_id, e)

            except Exception as e:
                send_discord_message("[%s] ⚠️ Lỗi overlay logo tổng quát (tiếp tục): %s", task_id, e)

        t = load_tasks().get(task_id, {})
        t["progress"] = 65
        tasks = load_tasks()
        tasks[task_id] = t
        save_tasks(tasks)

        # Split
        try:
            split_list = await loop.run_in_executor(executor, split_video_by_time_with_title, processed, Title, "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", part_time)
        except Exception as e:
            send_discord_message("[%s] ❌ Lỗi khi chia video: %s", task_id, e)
            t = load_tasks().get(task_id, {})
            t["status"] = "error"
            t["error"] = str(e)
            t["progress"] = 0
            tasks = load_tasks()
            tasks[task_id] = t
            save_tasks(tasks)
            return

        # Upload parts
        uploaded_results = []
        for fpath in split_list:
            try:
                send_discord_message("[%s] 📤 Uploading to Drive: %s", task_id, fpath)
                uploaded = await loop.run_in_executor(executor, uploadOneDrive, fpath, Title)
                link = uploaded.get('downloadLink') or uploaded.get('webViewLink')
                t = load_tasks().get(task_id, {})
                t.setdefault('video_file', []).append(link or uploaded.get('name'))
                t.setdefault('temp_videos', []).append(fpath)
                tasks = load_tasks()
                tasks[task_id] = t
                save_tasks(tasks)
                uploaded_results.append(uploaded)
            except Exception as e:
                send_discord_message("[%s] ⚠️ Upload thất bại cho %s: %s", task_id, fpath, e)
                t = load_tasks().get(task_id, {})
                t.setdefault('video_file', []).append(fpath)
                tasks = load_tasks()
                tasks[task_id] = t
                save_tasks(tasks)

        # Finalize task
        t = load_tasks().get(task_id, {})
        t['status'] = 'completed'
        t['progress'] = 100
        if split_list:
            t['video_path'] = split_list[0]
        tasks = load_tasks()
        tasks[task_id] = t
        save_tasks(tasks)

        send_discord_message("[%s] ✅ Facebook task hoàn tất: %s", task_id, [u.get('id') for u in uploaded_results])

    except Exception as e:
        logger.exception("[%s] Lỗi không mong muốn trong process_facebook_task: %s", task_id, e)
        t = load_tasks().get(task_id, {})
        t['status'] = 'error'
        t['error'] = str(e)
        t['progress'] = 0
        tasks = load_tasks()
        tasks[task_id] = t
        save_tasks(tasks)
        return


async def process_story_to_video_task(
    task_id: str,
    urls: List[str],
    title: str,
    voice: str,
    bg_choice: str | None,
   
    genre_params: dict
):
    """
    Xử lý full pipeline: Truyện → Audio → Video
    
    Args:
        task_id: ID task để tracking
        urls: Danh sách URL video background
        title: Tiêu đề video (tùy chọn)
        voice: Voice or instruction for TTS
        bg_choice: Tên file nhạc nền
        part_duration: Thời lượng mỗi part video (giây)
        genre_params: Dictionary chứa thông số cho từng thể loại
    """
    from story_generator import StoryGenerator
    
    loop = asyncio.get_event_loop()
    
    try:
        # ============ PHASE 1: TẠO TRUYỆN ============
        send_discord_message(f"[{task_id}] 📖 PHASE 1/4: Tạo truyện thể loại {genre_params['genre'].upper()}...")
        tasks = load_tasks()
        t = tasks.get(task_id, {})
        t['status'] = 'running'
        t['phase'] = 'generating_story'
        t['progress'] = 5
        save_tasks(tasks)
        
        # Khởi tạo StoryGenerator: dùng Gemini (API key = GEMINI_API_KEY) và model Gemini
        # regardless of incoming `model` param to ensure generation uses Gemini.
        try:
            # Initialize StoryGenerator explicitly with Gemini enabled
            generator = StoryGenerator(
                model='gemini-2.5-pro',
                
            )
        except Exception as e:
            send_discord_message(f"[{task_id}] ⚠️ Không thể khởi tạo StoryGenerator với Gemini: {e}")
            # Fallback: try to init without explicit key (may use GEMINI_API_KEY env var)
            try:
                generator = StoryGenerator(model='gemini-2.5-pro')
            except Exception:
                # Last resort: init with default model (OpenAI fallback)
                generator = StoryGenerator(model='gemini-2.5-pro')
        
        genre = genre_params['genre']
        story_file = None
        story_title = None
        
        # Tạo truyện theo thể loại
        if genre == 'horror':
            story_result = await loop.run_in_executor(
                executor,
                generator.generate_horror_story,
                genre_params.get('horror_theme'),
                genre_params.get('horror_setting')
            )
        elif genre == 'face_slap':
            story_result = await loop.run_in_executor(
                executor,
                generator.generate_face_slap_story,
                genre_params.get('face_slap_theme'),
                genre_params.get('face_slap_role'),
                genre_params.get('face_slap_setting')
            )
        elif genre == 'random_mix':
            # Extract individual random mix parameters
            story_result = await loop.run_in_executor(
                executor,
                generator.generate_random_mix_story,
                genre_params.get('random_main_genre'),      # the_loai_chinh
                genre_params.get('random_sub_genre'),       # the_loai_phu
                genre_params.get('random_character'),       # nhan_vat
                genre_params.get('random_setting'),         # boi_canh
                genre_params.get('random_plot_motif')       # mo_tip
            )
        
        if not story_result or 'file_path' not in story_result:
            raise RuntimeError("Không tạo được file truyện")
        
        story_file = story_result['file_path']
        story_content = story_result['content']
        
        # Use the title returned by StoryGenerator (generated together with content to save tokens).
        # Fall back to local extractor only if the generator didn't provide a title.
        story_title = None
        try:
            if isinstance(story_result, dict):
                story_title = (story_result.get('title') or '').strip()
        except Exception:
            story_title = None

        if not story_title:
            try:
                if 'generator' in locals() and generator:
                    if genre == 'horror':
                        story_title = generator._extract_title(story_content, genre_params.get('horror_theme', 'Truyện Kinh Dị'))
                    elif genre == 'face_slap':
                        story_title = generator._extract_title_face_slap(story_content, genre_params.get('face_slap_theme', 'Vả Mặt'))
                    elif genre == 'random_mix':
                        story_title = generator._extract_title_random_mix(
                            story_content,
                            genre_params.get('random_main_genre', '') or 'Random Mix',
                            genre_params.get('random_plot_motif', '') or ''
                        )
                    else:
                        story_title = generator._extract_title(story_content, os.path.splitext(os.path.basename(story_file))[0])
            except Exception:
                story_title = None

        # Fallback: nếu không tạo được từ generator hay extractor thì lấy từ tên file
        if not story_title:
            story_title = os.path.splitext(os.path.basename(story_file))[0]
            parts = story_title.split('_', 2)
            if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit():
                story_title = parts[2]

        # Trim and ensure string
        story_title = (story_title or '').strip()

        # Save AI-suggested title into task metadata so it's visible later.
        # Use provided `title` param if present, otherwise use the AI-generated title.
        # Store both the final title and the AI suggestion.
        tasks = load_tasks()
        t = tasks.get(task_id, {})
        t['ai_title_suggestion'] = story_title

        final_title = title or story_title

        # Create slug from the Vietnamese title (short, safe)
        title_slug = safe_filename(final_title or story_title or os.path.splitext(os.path.basename(story_file))[0], max_length=50)

        # Define common audio path names so later cleanup references exist
        summary_audio_path = os.path.join(OUTPUT_DIR, f"{title_slug}_summary.wav")
        content_audio_path = os.path.join(OUTPUT_DIR, f"{title_slug}_content.wav")
        combined_audio_path = os.path.join(OUTPUT_DIR, f"{title_slug}.wav")


        send_discord_message(f"[{task_id}] ✅ Tạo truyện thành công: {story_title} ({len(story_content)} ký tự)")
        send_discord_message(f"[{task_id}] 📝 Slug sử dụng: {title_slug}")

        t['story_path'] = story_file
        t['title'] = final_title
        t['ai_title'] = story_title
        t['slug'] = title_slug  # Lưu slug để tái sử dụng
        t['progress'] = 15
        tasks[task_id] = t
        save_tasks(tasks)
        
        # ============ PHASE 2: TẠO AUDIO ============
        send_discord_message(f"[{task_id}] 🎙️ PHASE 2/4: Tạo audio từ truyện...")
        t['phase'] = 'generating_audio'
        t['progress'] = 20
        save_tasks(tasks)
        
        
        # Tạo audio từ văn bản (dùng slug đã tạo)
        # Story generation always uses Gemini; TTS backend can be chosen per-task.
        ai_backend = 'gemini'
        try:
            if isinstance(genre_params, dict):
                ai_backend = (genre_params.get('ai_backend') or genre_params.get('backend') or 'gemini').lower()
        except Exception:
            ai_backend = 'gemini'

        # Record chosen backend in task metadata
        t = load_tasks().get(task_id, {})
        t['ai_backend'] = ai_backend
        tasks[task_id] = t
        save_tasks(tasks)

        # Select TTS generator & post-processing based on backend
        if ai_backend == 'openai':
            # Use OpenAI TTS generator and non-Gemini audio processor
            audio_file = await loop.run_in_executor(
                executor,
                generate_audio,
                story_content,
                title_slug
            )
        else:
            # Default: use Gemini TTS and Gemini-specific processor
            audio_file = await loop.run_in_executor(
                executor,
                generate_audio_Gemini,
                story_content,
                title_slug
            )

        if not audio_file or not os.path.exists(audio_file):
            raise RuntimeError("Không tạo được file audio")

        send_discord_message(f"[{task_id}] ✅ Tạo audio thành công: {audio_file} (backend={ai_backend})")

        t = load_tasks().get(task_id, {})
        t['audio_path'] = audio_file
        t['progress'] = 40
        tasks[task_id] = t
        save_tasks(tasks)

        # ============ PHASE 3: XỬ LÝ AUDIO ============
        send_discord_message(f"[{task_id}] ⚙️ PHASE 3/4: Xử lý audio (tăng tốc + nhạc nền)... (backend={ai_backend})")
        t['phase'] = 'processing_audio'
        t['progress'] = 45
        tasks[task_id] = t
        save_tasks(tasks)

        # Xử lý audio với appropriate prepare_audio_for_video variant
        if ai_backend == 'openai':
            processed_audio = await loop.run_in_executor(
                executor,
                prepare_audio_for_video,
                audio_file,
                bg_choice
            )
        else:
            processed_audio = await loop.run_in_executor(
                executor,
                prepare_audio_for_video_gemini,
                audio_file,
                bg_choice
            )

        if not processed_audio or not os.path.exists(processed_audio):
            raise RuntimeError("Không xử lý được audio")

        send_discord_message(f"[{task_id}] ✅ Xử lý audio thành công: {processed_audio}")

        t = load_tasks().get(task_id, {})
        t['processed_audio_path'] = processed_audio
        t['progress'] = 50
        tasks[task_id] = t
        save_tasks(tasks)
        
        # ============ PHASE 4: TẠO VIDEO ============
        send_discord_message(f"[{task_id}] 🎬 PHASE 4/4: Render video từ audio...")
        t['phase'] = 'rendering_video'
        t['progress'] = 55
        save_tasks(tasks)
        
        # Download video backgrounds (if an item is already a local path, use it directly)
        video_files = []
        for i, url in enumerate(urls):
            send_discord_message(f"[{task_id}] 📥 Tải video background {i+1}/{len(urls)}...")
            try:
                # If url is a local path or file:// URI, skip download and use it directly
                cached_video = None
                if isinstance(url, str):
                    if url.lower().startswith('file://'):
                        local_path = url[7:]
                        if os.path.exists(local_path):
                            cached_video = local_path
                    elif os.path.exists(url):
                        cached_video = url

                if not cached_video:
                    # download_video_url trả về path cache (không cần truyền output path)
                    cached_video = await loop.run_in_executor(
                        executor,
                        download_video_url,
                        url,
                        f"{title_slug}_bg_{i+1}.mp4",  # tên gợi ý (hàm có thể ignore)
                        3,  # retries
                        2,  # delay
                        None,  # target_duration (full video)
                        False  # fail_fast
                    )

                if cached_video and os.path.exists(cached_video):
                    video_files.append(cached_video)  # Lưu path cache thực tế
                    send_discord_message(f"[{task_id}] ✅ Cache: {os.path.basename(cached_video)}")
                else:
                    send_discord_message(f"[{task_id}] ⚠️ Không nhận được file cache từ {url}")
            except Exception as e:
                send_discord_message(f"[{task_id}] ⚠️ Lỗi tải video {url}: {e}")
                continue
        
        if not video_files:
            raise RuntimeError("Không tải được video background nào")
        
        send_discord_message(f"[{task_id}] ✅ Đã tải {len(video_files)} video backgrounds")
        
        t = load_tasks().get(task_id, {})
        t['progress'] = 65
        save_tasks(tasks)
        
        # Render using TikTok Large flow: prefer per‑TTS parts, else split processed audio
        send_discord_message(f"[{task_id}] 🎬 Render video theo flow TikTok Large (chia part và render từng phần)...")

        # Part duration: prefer explicit param, fallback to provided value. Clamp to max 3600s (60 minutes).
      
        start_from_part = int(genre_params.get('start_from_part', 1)) if isinstance(genre_params, dict) else 1

        # 1) Get per-TTS parts if present
        # Flow change: even when per-TTS parts exist, we first concatenate them,
        # produce a single processed FLAC (with background mix) and then split
        # that FLAC into parts <= 60 minutes for rendering. After render we
        # delete the split parts and the processed master FLAC but keep the
        # original per-TTS WAVs.
        tts_parts = get_tts_part_files(title_slug, OUTPUT_DIR)
        split_generated_from_processed = False
        processed_master = None

        if tts_parts:
            send_discord_message(f"[{task_id}] ♻️ Tìm thấy per‑TTS parts ({len(tts_parts)} phần). Will concatenate and produce processed FLAC then split into parts.")

            # Create a concat list and combine per-TTS parts into a single WAV
            concat_list = os.path.join(OUTPUT_DIR, f"{title_slug}_tts_concat.txt")
            combined_tts_wav = os.path.join(OUTPUT_DIR, f"{title_slug}_tts_combined.wav")

            # Write concat list and run ffmpeg concat in threadpool
            await loop.run_in_executor(executor, _write_concat_list, tts_parts, concat_list)
            await loop.run_in_executor(executor, _concat_audio_from_list, concat_list, combined_tts_wav)

            # Process the combined wav into the master processed FLAC (adds bg, resample, etc.)
            processed_master = await loop.run_in_executor(
                executor,
                prepare_audio_for_video_gemini,
                combined_tts_wav,
                bg_choice
            )

            if not processed_master or not os.path.exists(processed_master):
                raise RuntimeError(f"Không tạo được processed master audio từ per-TTS parts: {processed_master}")

            # Split the processed master into parts of <= 3600s
            audio_parts = await loop.run_in_executor(
                executor,
                split_audio_by_duration,
                processed_master,
                3600,
                OUTPUT_DIR
            )

            split_generated_from_processed = True

        else:
            # No per-TTS pieces: split the already prepared processed_audio produced above
            processed_master = processed_audio
            audio_parts = await loop.run_in_executor(
                executor,
                split_audio_by_duration,
                processed_master,
                3600,
                OUTPUT_DIR
            )
            split_generated_from_processed = True

        total_parts = len(audio_parts)
        send_discord_message(f"[{task_id}] 📊 Tổng số audio part: {total_parts}")

        if total_parts == 0:
            raise RuntimeError("Không có phần audio để render")

        t = load_tasks().get(task_id, {})
        t['progress'] = 70
        t['total_parts'] = total_parts
        tasks = load_tasks()
        tasks[task_id] = t
        save_tasks(tasks)

        # 2) Ensure we have downloaded background video files (video_files already collected)
        if not video_files:
            raise RuntimeError("Không có video background nào để render")

        # 3) Render each part sequentially
        output_parts = []
        video_links = []
        # unique suffix so final part filenames are new per render
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        suffix = f"_{task_id}_{ts}"

        for i in range(start_from_part - 1, total_parts):
            part_num = i + 1
            audio_part = audio_parts[i]
            output_part = os.path.join(OUTPUT_DIR, f"{title_slug}_part{part_num}{suffix}.mp4")

            send_discord_message(f"[{task_id}] 🎬 Render part {part_num}/{total_parts}...")

            try:
                rendered_part = await loop.run_in_executor(
                    executor,
                    render_tiktok_video_from_audio_part,
                    video_files,
                    audio_part,
                    output_part,
                    final_title,
                    part_num,
                    total_parts,
                    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
                )

                output_parts.append(rendered_part)

                # Only provide sandbox view/download links for parts (no Drive upload)
                view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(to_project_relative_posix(rendered_part))
                download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(to_project_relative_posix(rendered_part))
                video_links.append(download_link)
                send_discord_message("🎥 Xem video:" + view_link)
                send_discord_message("⬇️ Tải video:" + download_link)
                    # Cập nhật progress
                # Update progress
                progress = 70 + int((part_num / total_parts) * 25)
                t = load_tasks().get(task_id, {})
                t['progress'] = progress
                t['current_part'] = part_num
                t.setdefault('video_file', [])
                t['video_file'] = video_links
                tasks = load_tasks()
                tasks[task_id] = t
                save_tasks(tasks)

            except Exception as e:
                send_discord_message(f"[{task_id}] ❌ Lỗi render part {part_num}: {e}")
                t = load_tasks().get(task_id, {})
                t['status'] = 'error'
                t['error'] = f"Lỗi tại part {part_num}: {str(e)}"
                t['last_successful_part'] = part_num - 1 if part_num > 1 else 0
                t['resume_from_part'] = part_num
                tasks = load_tasks()
                tasks[task_id] = t
                save_tasks(tasks)
                raise

        # Finalize
        send_discord_message(f"[{task_id}] ✅ Hoàn tất render {len(output_parts)} part")

        t = load_tasks().get(task_id, {})
        t['status'] = 'completed'
        t['progress'] = 100
        t['video_file'] = video_links
        t['output_parts'] = output_parts
        if output_parts:
            t['video_path'] = output_parts[0]
        tasks = load_tasks()
        tasks[task_id] = t
        save_tasks(tasks)

        # Cleanup: keep only per-TTS parts and final uploaded video parts
        # Remove large intermediate/processed files but PRESERVE original per-TTS
        # part WAVs (and their .done markers) as well as final rendered video parts
        # listed in `output_parts`/`video_links` so they remain for reuse/inspection.
        try:
            # 1) Remove processed master (combined FLAC/WAV used for splitting)
            if 'processed_master' in locals() and processed_master:
                try:
                    if os.path.exists(processed_master):
                        os.remove(processed_master)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
            # 2) Remove split audio parts created from processed master
            if 'audio_parts' in locals() and isinstance(audio_parts, (list, tuple)):
                for ap in audio_parts:
                    try:
                        # don't remove per-TTS original parts (they live in tts_parts)
                        if ap and os.path.exists(ap):
                            os.remove(ap)
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
            # 3) Remove combined per-TTS concatenated WAV and concat list
            if 'combined_tts_wav' in locals() and combined_tts_wav:
                try:
                    if os.path.exists(combined_tts_wav):
                        os.remove(combined_tts_wav)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
            if 'concat_list' in locals() and concat_list:
                try:
                    if os.path.exists(concat_list):
                        os.remove(concat_list)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
            # 4) Remove other intermediate audio artifacts if present
            for varname in ('processed_audio', 'summary_audio_path', 'content_audio_path', 'combined_audio_path'):
                try:
                    if varname in locals():
                        p = locals().get(varname)
                        if p and os.path.exists(p):
                            os.remove(p)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
            # 5) Keep per-TTS parts and their .done markers. Do NOT remove files
            # returned by get_tts_part_files (tts_parts) or any *.done files inside
            # OUTPUT_DIR that correspond to them. Also keep final rendered video
            # parts in `output_parts` (they are user artifacts / uploads).
            # No-op here: preservation is intentional.
            pass
        except Exception as e:
            _report_and_ignore(e, "ignored")
        # ============ HOÀN TẤT ============
        send_discord_message(f"[{task_id}] 🎉 HOÀN TẤT! Đã tạo {len(output_parts)} video parts")
        
        t = load_tasks().get(task_id, {})
        t['status'] = 'completed'
        t['phase'] = 'completed'
        t['progress'] = 100
        save_tasks(tasks)
        
    except Exception as e:
        logger.exception(f"[{task_id}] ❌ Lỗi trong process_story_to_video_task: {e}")
        tasks = load_tasks()
        t = tasks.get(task_id, {})
        t['status'] = 'error'
        t['error'] = str(e)
        t['progress'] = 0
        save_tasks(tasks)


# ==============================
# API endpoint
# ==============================
from fastapi import BackgroundTasks
@app.on_event("startup")
async def startup_workers():
    global _worker_tasks
    send_discord_message("🚀 Khởi tạo %d worker xử lý hàng đợi...", WORKER_COUNT)
    loop = asyncio.get_event_loop()
    for i in range(WORKER_COUNT):
        t = loop.create_task(queue_worker(i+1))
        _worker_tasks.append(t)
    # Start periodic enqueuer to pick up tasks manually set to 'pending'
    async def _enqueue_loop():
        while True:
            try:
                await enqueue_pending_tasks_once()
            except Exception as e:
                send_discord_message(f"⚠️ Periodic enqueuer error: {e}")
            await asyncio.sleep(POLL_INTERVAL)

    loop.create_task(_enqueue_loop())


async def enqueue_pending_tasks_once():
    """Scan the tasks file for entries with status=='pending' and no 'queued' flag,
    mark them queued and put them into TASK_QUEUE so workers will pick them up.
    This allows manual edits of tasks.json (set to pending) to be re-queued.
    """
    tasks = load_tasks()
    if not tasks:
        return
    for tid, t in list(tasks.items()):
        try:
            if not isinstance(t, dict):
                continue
            status = (t.get("status") or "").lower()
            # Enqueue any pending task not already in the in-memory queued set
            # Skip tasks that are managed by the series processor or explicitly flagged to skip queue
            is_series = str(t.get("task_type", "")).lower() == "series" or t.get("type") == 8
            should_skip = bool(t.get("skip_queue")) or is_series
            if status == "pending" and tid not in QUEUED_TASK_IDS and not should_skip:
                # Prepare queue payload (best-effort: include fields if present)
                # Normalize request_urls which may be stored as a comma-separated string or a list.
                raw_req_urls = t.get("request_urls") or t.get("urls") or []
                req_urls_list = []
                try:
                    if isinstance(raw_req_urls, str):
                        # split comma-separated string and strip
                        req_urls_list = [u.strip() for u in raw_req_urls.split(",") if u.strip()]
                    elif isinstance(raw_req_urls, (list, tuple)):
                        req_urls_list = [str(u).strip() for u in raw_req_urls if str(u).strip()]
                    else:
                        req_urls_list = []
                except Exception:
                    req_urls_list = []

                # Determine story_url as last item (if not explicitly stored)
                story_url_val = t.get("story_url") or (req_urls_list[-1] if req_urls_list else None)
                # Determine video/background urls as all items except the last (if any)
                urls_only = req_urls_list[:-1] if len(req_urls_list) > 1 else []

                # Compute title_slug (prefer stored, else from story_url)
                title_slug_val = t.get("title_slug") or (extract_slug(story_url_val) if story_url_val else None)

                # Compute final_video_path similar to endpoints: include voice in filename if present
                voice_val = (t.get("voice") or "").strip()
                final_video_path_val = t.get("video_path") or (
                    os.path.join(OUTPUT_DIR, f"{title_slug_val}_{voice_val}_video.mp4") if title_slug_val and voice_val else
                    (os.path.join(OUTPUT_DIR, f"{title_slug_val}_video.mp4") if title_slug_val else None)
                )

                payload = {
                    "task_id": tid,
                    "urls": urls_only,
                    "story_url": story_url_val,
                    "merged_video_path": t.get("merged_video_path"),
                    "final_video_path": final_video_path_val,
                    "title_slug": title_slug_val,
                    "key_file": t.get("key_file", "key.json"),
                    "title": t.get("title", ""),
                    "voice": voice_val,
                    "bg_choice": t.get("bg_choice"),
                    "refresh": t.get("refresh", False),
                    "type": t.get("type", t.get("task_type", 1)),
                }
                # Put into queue using helper which tracks queued ids in-memory
                await enqueue_task(payload)
                send_discord_message("🔁 Re-queued pending task: %s", tid)
        except Exception:
            continue

@app.on_event("shutdown")
async def shutdown_workers():
    send_discord_message("🛑 Shutdown workers...")
    for t in _worker_tasks:
        t.cancel()
    await asyncio.gather(*_worker_tasks, return_exceptions=True)
    send_discord_message("✅ Workers stopped.")
@app.get("/generate_video")
async def generate_video(
    video_url: str = Query(...),
    story_url: str = Query(...),
    force_refresh: bool = Query(False, description="Bỏ cache và tải lại nội dung truyện"),
    refresh_audio: bool = Query(False, description="Bỏ cache và tạo lại file audio capcut.wav")
):
    cleanup_old_tasks(days=30)  # cleanup tự động
    key_manager = FPTKeyManager(key_file="key.json")
    request_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    title_slug = extract_slug(story_url)
    urls = [u.strip() for u in video_url.split(",") if u.strip()]

    merged_video_path = os.path.join(OUTPUT_DIR, f"{title_slug}_merged.mp4")
    # This endpoint does not accept a `voice` parameter; use legacy filename
    final_video_path = os.path.join(OUTPUT_DIR, f"{title_slug}_video.mp4")
    cache_file = os.path.join(CACHE_DIR, f"{url_hash(story_url)}.txt")

    # Tạo task
    tasks = load_tasks()
    task_info = {
        "task_id": request_id,
        "status": "pending",
        "progress": 0,
        "video_path": final_video_path,
        "temp_videos": [],
        "request_urls": urls + [story_url],
        "created_at": time.time()
    }
    tasks[request_id] = task_info
    save_tasks(tasks)
    if force_refresh and os.path.exists(cache_file):
        os.remove(cache_file)

    # --- Background pipeline ---
    # Ensure a safe default prepare_audio callable is available for the pipeline
    # This endpoint is legacy and does not accept a `voice` param, so use the generic processor.
    prepare_audio_callable = prepare_audio_for_video

    async def pipeline(task_id, urls, story_url, merged_video_path, final_video_path, refresh_audio, bg_choice=None):
        tasks = load_tasks()
        try:
            # Respect cooperative cancellation if requested before starting
            if is_task_cancelled(task_id):
                try:
                    tasks_local = load_tasks()
                    if task_id in tasks_local:
                        tasks_local[task_id]['status'] = 'cancelled'
                        save_tasks(tasks_local)
                except Exception:
                    pass
                return

            # Ensure there's space before heavy work: run quick maintenance
            try:
                await maintenance_trim_storage()
            except Exception:
                # non-fatal: continue even if maintenance fails
                send_discord_message("⚠️ Maintenance pre-check failed, continuing pipeline.")

            # --- Audio thuần (chỉ giọng đọc) ---
            text = await asyncio.get_event_loop().run_in_executor(executor, get_novel_text, story_url)
            if is_task_cancelled(task_id):
                raise asyncio.CancelledError()

            # Check cache audio thuần (.wav)
            audio_base_path = title_slug + ".wav"
            outputAudio = os.path.join(OUTPUT_DIR, audio_base_path)

            if os.path.exists(outputAudio) and not refresh_audio:
                send_discord_message("🎧 Dùng cache audio thuần: %s", outputAudio)
                audio_path = outputAudio
            else:
                if refresh_audio:
                    send_discord_message("🔄 Refresh: Tạo lại audio mới...")
                audio_path = await asyncio.get_event_loop().run_in_executor(executor, generate_audio, text, title_slug)
            if is_task_cancelled(task_id):
                raise asyncio.CancelledError()

            # Chuẩn bị audio cho video (mix nhạc nền) trước khi render
            processed_audio = await asyncio.get_event_loop().run_in_executor(executor, prepare_audio_callable, audio_path, bg_choice)
            if is_task_cancelled(task_id):
                raise asyncio.CancelledError()

            # --- Video download & concat ---
            loop = asyncio.get_event_loop()
            download_tasks = []
            temp_files = []
            for idx, url in enumerate(urls, 1):
                out_name = os.path.join(OUTPUT_DIR, f"temp_{title_slug}_{idx}.mp4")
                temp_files.append(out_name)
                if re.search(r"https?://", url, re.I):
                    fb = is_facebook_url(url)
                    # pass explicit retries/delay + None target_duration so we can set fail_fast
                    download_tasks.append(loop.run_in_executor(executor, download_video_url, url, out_name, 3, 2, None, fb))
                else:
                    download_tasks.append(loop.run_in_executor(executor, lambda p=url: p))

            video_paths = await asyncio.gather(*download_tasks)
            if is_task_cancelled(task_id):
                raise asyncio.CancelledError()

            task_info = tasks[task_id]
            task_info["temp_videos"] = temp_files
            tasks[task_id] = task_info
            save_tasks(tasks)

         
            await loop.run_in_executor(executor, concat_and_add_audio, video_paths, processed_audio, final_video_path)

            # Hoàn tất
            task_info["status"] = "completed"
            task_info["progress"] = 100
            tasks[task_id] = task_info
            save_tasks(tasks)

            # Xóa temp videos
            for f in temp_files:
                if os.path.exists(f):
                    os.remove(f)

            # After creation, run maintenance again to free space if needed
            try:
                await maintenance_trim_storage()
            except Exception:
                send_discord_message("⚠️ Maintenance post-check failed or errored.")

        except asyncio.CancelledError:
            try:
                tasks_local = load_tasks()
                if task_id in tasks_local:
                    tasks_local[task_id]['status'] = 'cancelled'
                    save_tasks(tasks_local)
            except Exception:
                pass
            send_discord_message(f"🛑 Task {task_id} cancelled during pipeline.")
            return
        except Exception as e:
            task_info = tasks[task_id]
            task_info["status"] = "error"
            task_info["progress"] = 0
            task_info["error"] = str(e)
            tasks[task_id] = task_info
            save_tasks(tasks)

    # Chạy pipeline bất đồng bộ (theo dõi để hỗ trợ cancel)
    create_tracked_task(request_id, pipeline(request_id, urls, story_url, merged_video_path, final_video_path, refresh_audio, bg_choice=None))

    # Trả về ngay task_id
    return {"task_id": request_id}
@app.get("/generate_video_task")
async def generate_video_task(
    video_url: str = Query(...),
    story_url: str = Query(...),
    Title="",
    voice: str = "",
    bg_choice: str = Query(None, description="Optional background WAV filename from outputs/bgaudio/"),
    force_refresh: bool = Query(False, description="Bỏ cache và tải lại nội dung truyện"),
    refresh_audio: bool = Query(False, description="Bỏ cache và tạo lại file audio capcut.wav")
):
    
    cleanup_old_tasks(days=30)  # cleanup tự động
    key_file = "key.json"  # nếu bạn muốn khác, thay ở đây
    request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    title_slug = extract_slug(story_url)
    urls = [u.strip() for u in video_url.split(",") if u.strip()]

    merged_video_path = os.path.join(OUTPUT_DIR, f"{title_slug}_merged.mp4")
    final_video_path = os.path.join(OUTPUT_DIR, f"{title_slug}_{voice}_video.mp4") if voice else os.path.join(OUTPUT_DIR, f"{title_slug}_video.mp4")
    cache_file = os.path.join(CACHE_DIR, f"{url_hash(story_url)}.txt")

    # Tạo task metadata
    tasks = load_tasks()
    task_info = {
        "task_id": request_id,
        "status": "pending",
        "progress": 0,
        "video_path": final_video_path,
        "video_file":[],
        "title":Title,
        "voice":voice,
        "bg_choice": bg_choice,
        "refresh": refresh_audio,
        "temp_videos": [],
        "request_urls": urls + [story_url],
        "created_at": time.time(),
        "type":1
    }
    tasks[request_id] = task_info
    save_tasks(tasks)

    if force_refresh and os.path.exists(cache_file):
        os.remove(cache_file)

    # Đẩy vào queue (worker sẽ pick lên)
    await enqueue_task({
        "task_id": request_id,
        "urls": urls,
        "story_url": story_url,
        "merged_video_path": merged_video_path,
        "final_video_path": final_video_path,
        "title_slug": title_slug,
        "key_file": key_file,
        "title":Title,
        "voice":voice,
        "video_file":[],
        "bg_choice": bg_choice,
        "refresh": refresh_audio,
        "type":1
    })

    send_discord_message("📨 Đã xếp task %s vào hàng chờ", request_id)
    return {"task_id": request_id}
@app.get("/generate_video_task_youtube")
async def generate_video_task_youtube(
  
    story_url: str = Query(...),
    Title="",
    voice: str = "",
    bg_choice: str = Query(None, description="Optional background WAV filename from outputs/bgaudio/"),
    force_refresh: bool = Query(False, description="Bỏ cache và tải lại nội dung truyện"),
    refresh_audio: bool = Query(False, description="Bỏ cache và tạo lại file audio capcut.wav")
):
    
    cleanup_old_tasks(days=30)  # cleanup tự động
    key_file = "key.json"  # nếu bạn muốn khác, thay ở đây
    request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    title_slug = extract_slug(story_url)
   

    merged_video_path = os.path.join(OUTPUT_DIR, f"{title_slug}_merged.mp4")
    final_video_path = os.path.join(OUTPUT_DIR, f"{title_slug}_{voice}_video.mp4") if voice else os.path.join(OUTPUT_DIR, f"{title_slug}_video.mp4")
    cache_file = os.path.join(CACHE_DIR, f"{url_hash(story_url)}.txt")

    # Tạo task metadata
    tasks = load_tasks()
    task_info = {
        "task_id": request_id,
        "status": "pending",
        "progress": 0,
        "video_path": final_video_path,
        "video_file":[],
        "title":Title,
        "voice":voice,
        "bg_choice": bg_choice,
        "refresh": refresh_audio,
        "temp_videos": [],
        "request_urls": [story_url],
        "created_at": time.time(),
        "type":2
    }
    tasks[request_id] = task_info
    save_tasks(tasks)

    if force_refresh and os.path.exists(cache_file):
        os.remove(cache_file)

    # Đẩy vào queue (worker sẽ pick lên)
    await enqueue_task({
        "task_id": request_id,
        "urls": "",
        "story_url": story_url,
        "merged_video_path": merged_video_path,
        "final_video_path": final_video_path,
        "title_slug": title_slug,
        "key_file": key_file,
        "title":Title,
        "voice":voice,
        "type":2,
        "bg_choice": bg_choice,
        "refresh": refresh_audio,
        "video_file":[]
    })

    send_discord_message("📨 Đã xếp task %s vào hàng chờ", request_id)
    return {"task_id": request_id}
def stream_file(path, start=0, end=None, chunk_size=1024 * 1024):
    with open(path, "rb") as f:
        f.seek(start)
        remaining = None if end is None else (end - start + 1)
        while True:
            read_size = chunk_size if remaining is None else min(chunk_size, remaining)
            data = f.read(read_size)
            if not data:
                break
            yield data
            if remaining is not None:
                remaining -= len(data)
                if remaining <= 0:
                    break

CHUNK_SIZE = 1024 * 1024  # 1MB
@app.get("/tasks")
async def list_tasks():
    """Danh sách tất cả task"""
    tasks = load_tasks()
    

    # Chuyển sang list với thông tin cần thiết
    result = [
        {
            "task_id": t["task_id"],
            "status": t["status"],
            "progress": t.get("progress", 0),
            "request_urls": t.get("request_urls", []),
            "video_File":t.get("video_file",[]),
            "created_at": datetime.fromtimestamp(t.get("created_at", 0)).isoformat()
        } 
        for t in tasks.values()
    ]
    
    # Sắp xếp theo created_at từ gần nhất tới xa nhất
    result_sorted = sorted(result, key=lambda x: x["created_at"], reverse=True)
    
    return result_sorted

@app.get("/task_status")
async def task_status(task_id: str = Query(...)):
    """Kiểm tra trạng thái task"""
    tasks = load_tasks()
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task ID không tồn tại")
    t = tasks[task_id]
    return {
        "task_id": t["task_id"],
        "status": t["status"],
        "progress": t.get("progress", 0),
        "request_urls": t.get("request_urls", []),
        "created_at": datetime.fromtimestamp(t.get("created_at", 0)).isoformat()
    }


@app.post("/task_cancel")
async def task_cancel(task_id: str = Body(...)):
    """Cancel a running or queued task by `task_id`.

    This sets the task status to 'cancelled', removes it from the queued set,
    and attempts to cancel the running asyncio.Task if present.
    """
    tasks = load_tasks()
    if task_id not in tasks:
        return JSONResponse(status_code=404, content={"ok": False, "error": "Task ID not found"})
    try:
        tasks[task_id]['status'] = 'cancelled'
        save_tasks(tasks)
    except Exception:
        pass
    try:
        QUEUED_TASK_IDS.discard(task_id)
    except Exception:
        pass
    t = RUNNING_TASKS.get(task_id)
    if t:
        try:
            t.cancel()
        except Exception:
            pass
    send_discord_message(f"🛑 Cancellation requested for task {task_id}")
    return {"ok": True, "task_id": task_id, "cancelled": True}


@app.get("/running_tasks")
async def running_tasks():
    """Return currently tracked running tasks and basic metadata."""
    running = []
    try:
        tasks = load_tasks()
    except Exception:
        tasks = {}
    for tid, tsk in list(RUNNING_TASKS.items()):
        entry = {"task_id": tid, "is_alive": not getattr(tsk, "done", lambda: False)(), "queued": tid in QUEUED_TASK_IDS}
        meta = tasks.get(tid, {})
        if meta:
            entry.update({"status": meta.get("status"), "progress": meta.get("progress", 0), "created_at": datetime.fromtimestamp(meta.get("created_at", 0)).isoformat() if meta.get("created_at") else None})
        running.append(entry)
    return {"running": running, "count": len(running)}

@app.post("/clear_story_cache")
async def clear_story_cache(
    story_url: str = Query(..., description="URL truyện cần xóa cache"),
    preserve_video_cache: bool = Query(True, description="Nếu True thì không xóa các file nằm trong VIDEO_CACHE_DIR")
):
    """
    Xóa các file cache liên quan đến một truyện:
      - cache text ở CACHE_DIR (url_hash(story_url).txt)
      - audio: <slug>.wav, <slug>.flac, <slug>_summary.wav, <slug>_content.wav
      - processed audio: <slug>_capcut.flac và các part *_part*.flac
      - video outputs bắt đầu bằng <slug>_ (ví dụ <slug>_part1.mp4, <slug>_final.mp4)

    Video trong thư mục VIDEO_CACHE_DIR sẽ được giữ lại (không xóa) khi preserve_video_cache=True.

    Trả về JSON với danh sách file đã xóa và các file bị bỏ qua / lỗi.
    """
    deleted = []
    skipped = []
    errors = []

    try:
        slug = extract_slug(story_url)
        # cache text
        cache_file = os.path.join(CACHE_DIR, f"{url_hash(story_url)}.txt")
        candidates = []

        # common audio names
        candidates += [
            os.path.join(OUTPUT_DIR, f"{slug}.wav"),
            os.path.join(OUTPUT_DIR, f"{slug}.flac"),
            os.path.join(OUTPUT_DIR, f"{slug}_summary.wav"),
            os.path.join(OUTPUT_DIR, f"{slug}_content.wav"),
            os.path.join(OUTPUT_DIR, f"{slug}.flac"),
            os.path.join(OUTPUT_DIR, f"{slug}_capcut.flac"),
        ]

        # gemini parts and generic part files
        # pattern: <slug>_gemini_part_*.wav and <slug>_part*.flac
        for fname in os.listdir(OUTPUT_DIR) if os.path.isdir(OUTPUT_DIR) else []:
            if fname.startswith(slug + "_") and (fname.endswith('.wav') or fname.endswith('.flac') or fname.endswith('.mp4')):
                candidates.append(os.path.join(OUTPUT_DIR, fname))

        # also include cache file
        candidates.append(cache_file)

        # dedupe
        candidates = list(dict.fromkeys(candidates))

        for f in candidates:
            try:
                if not os.path.exists(f):
                    continue
                # If preserving video cache, skip files that are inside VIDEO_CACHE_DIR
                if preserve_video_cache and os.path.isdir(VIDEO_CACHE_DIR):
                    try:
                        if os.path.commonpath([os.path.abspath(f), os.path.abspath(VIDEO_CACHE_DIR)]) == os.path.abspath(VIDEO_CACHE_DIR):
                            skipped.append(f)
                            continue
                    except Exception:
                        # if commonpath fails, ignore and proceed
                        pass

                # Only delete files (not directories)
                if os.path.isfile(f):
                    os.remove(f)
                    deleted.append(f)
                else:
                    # if it's a dir (unlikely), skip
                    skipped.append(f)
            except Exception as e:
                errors.append({"file": f, "error": str(e)})

        send_discord_message("🧹 clear_story_cache: deleted %d files, skipped %d, errors %d", len(deleted), len(skipped), len(errors))
        return {"deleted": deleted, "skipped": skipped, "errors": errors}

    except Exception as e:
        logger.exception("Error in clear_story_cache: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


from fastapi import FastAPI, Request, Query, HTTPException
@app.get("/api/download-video", response_model=None)
async def download_video(
    request: Request,
    video_name: str = Query(..., description="Tên hoặc đường dẫn video"),
    download: bool = Query(False, description="Nếu True thì buộc tải xuống"),
    inline: bool = Query(False, description="Nếu True thì trả về inline để trình duyệt mở preview (useful for iOS long-press Save Video)")
):
    # Normalize `video_name` to an absolute file path under OUTPUT_DIR.
    # Accept either an absolute path inside OUTPUT_DIR or a path relative to OUTPUT_DIR.
    from urllib.parse import quote
    import mimetypes

    if os.path.isabs(video_name):
        file_path = os.path.abspath(video_name)
        # For security, require absolute paths to be under OUTPUT_DIR
        if not file_path.startswith(os.path.abspath(OUTPUT_DIR)):
            raise HTTPException(status_code=403, detail="Access to this path is denied")
    else:
        file_path = os.path.abspath(os.path.join(OUTPUT_DIR, video_name))

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Video không tồn tại")

    file_size = os.path.getsize(file_path)
    range_header = request.headers.get("range")

    mimetype = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
    # RFC5987 filename* for UTF-8 filenames
    if download:
        disposition = f"attachment; filename*=UTF-8''{quote(os.path.basename(file_path))}"
    elif inline:
        disposition = 'inline'
    else:
        # default behavior: inline unless download forced
        disposition = 'inline'

    def iterfile(start=0, end=None):
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = (end - start + 1) if end is not None else None
            while True:
                chunk_size = CHUNK_SIZE if remaining is None else min(CHUNK_SIZE, remaining)
                data = f.read(chunk_size)
                if not data:
                    break
                if remaining is not None:
                    remaining -= len(data)
                yield data

    # No Range: return full file via FileResponse for efficiency
    from fastapi.responses import FileResponse, Response
    if not range_header:
        headers = {
            'Cache-Control': 'public, max-age=3600',
            'Accept-Ranges': 'bytes',
            'Content-Disposition': disposition,
            # CORS so cross-origin previews (and Save) work in Safari
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET,HEAD,OPTIONS',
            # expose headers so client can read Content-Length/Range if needed
            'Access-Control-Expose-Headers': 'Content-Length, Accept-Ranges, Content-Range'
        }
        return FileResponse(file_path, media_type=mimetype, filename=os.path.basename(file_path), headers=headers)

    # Parse Range header for partial content and stream it in chunks to avoid
    # loading large slices into memory (supports multi-GB files).
    try:
        _, range_spec = range_header.split('=', 1)
        start_str, end_str = range_spec.split('-', 1)
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
    except Exception:
        raise HTTPException(status_code=400, detail='malformed Range')

    if end >= file_size:
        end = file_size - 1
    if start > end or start < 0:
        raise HTTPException(status_code=416, detail='Requested Range Not Satisfiable')

    length = end - start + 1

    # Use aiofiles to stream file asynchronously in chunks
    try:
        import aiofiles
    except Exception:
        raise HTTPException(status_code=500, detail='aiofiles is required for streaming large files. pip install aiofiles')

    from fastapi.responses import StreamingResponse

    async def stream_range(path, start_pos, end_pos, chunk_size=CHUNK_SIZE):
        async with aiofiles.open(path, 'rb') as f:
            await f.seek(start_pos)
            remaining = end_pos - start_pos + 1
            while remaining > 0:
                read_size = min(chunk_size, remaining)
                chunk = await f.read(read_size)
                if not chunk:
                    break
                yield chunk
                remaining -= len(chunk)

    headers = {
        'Content-Range': f'bytes {start}-{end}/{file_size}',
        'Accept-Ranges': 'bytes',
        'Content-Length': str(length),
        'Cache-Control': 'public, max-age=3600',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET,HEAD,OPTIONS',
        'Access-Control-Expose-Headers': 'Content-Length, Accept-Ranges, Content-Range'
    }
    if disposition:
        headers['Content-Disposition'] = disposition

    return StreamingResponse(stream_range(file_path, start, end), status_code=206, media_type=mimetype, headers=headers)
def enhance_video_for_copyright(src_path: str, out_path: str) -> str:
    """Apply slight re-encode and tiny speed/pitch shift to reduce exact-fingerprint matches.

    This performs a very small random speed change (0.98-1.02) and a slight contrast/brightness
    tweak, then re-encodes to H.264. The function writes to out_path and returns it.
    """
    # New behavior: ask Gemini to suggest an ffmpeg command to avoid copyright fingerprinting
    # If Gemini returns a usable command (expects placeholders {in} and {out}), we run it.
    # Otherwise fall back to the original lightweight transform.
    if not os.path.exists(src_path):
        raise FileNotFoundError(src_path)

    try:
        suggestion = suggest_copyright_transform_with_gemini(src_path, None)
        ffmpeg_cmd = suggestion.get('ffmpeg_cmd', '') if isinstance(suggestion, dict) else ''
        send_discord_message("🧠 Gemini suggested transform: %s", ffmpeg_cmd)

        if ffmpeg_cmd and isinstance(ffmpeg_cmd, str):
            # Replace placeholders if present
            cmd_str = ffmpeg_cmd.replace('{in}', f'"{src_path}"').replace('{out}', f'"{out_path}"')
            # If placeholders not used, try to be helpful: replace tokens INPUT_PATH/OUTPUT_PATH
            cmd_str = cmd_str.replace('INPUT_PATH', f'"{src_path}"').replace('OUTPUT_PATH', f'"{out_path}"')

            # If still no mention of output, append output
            if out_path not in cmd_str and '{out}' not in ffmpeg_cmd and 'OUTPUT_PATH' not in ffmpeg_cmd:
                # naive fallback: ensure command writes to out_path by appending it
                cmd_str = cmd_str + f' "{out_path}"'

            try:
                cmd_list = shlex.split(cmd_str)
                subprocess.run(cmd_list, check=True)
                return out_path
            except Exception as e:
                send_discord_message("⚠️ Lỗi khi chạy lệnh Gemini: %s. Sẽ dùng phương pháp fallback.", e)
    except Exception as e:
        send_discord_message("⚠️ Gemini suggestion failed: %s. Falling back to local transform.", e)

    # Fallback: original small transform
    factor = round(random.uniform(0.98, 1.02), 4)
    send_discord_message("🛠️ Áp dụng chỉnh sửa nhẹ để giảm trùng bản quyền (speed=%s)", factor)

    vf = f"setpts=PTS/{factor},eq=contrast=1.01:brightness=0.01,format=yuv420p"
    af = f"atempo={factor}"

    cmd = [
        'ffmpeg', '-y', '-i', src_path,
        '-filter:v', vf,
        '-filter:a', af,
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '128k',
        out_path
    ]

    subprocess.run(cmd, check=True)
    return out_path


def get_logo_path() -> str | None:
    """Find a logo image in common logo folders and return its path or None.

    Searches (in order): <BASE_DIR>/Logo, <BASE_DIR>/logo, <OUTPUT_DIR>/logo
    Prefers PNG over JPG if multiple files exist.
    """
    for folder in (os.path.join(BASE_DIR, "Logo"), os.path.join(BASE_DIR, "logo"), os.path.join(OUTPUT_DIR, "logo")):
        try:
            if not os.path.isdir(folder):
                continue
            files = [f for f in os.listdir(folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
            if not files:
                continue
            # Prefer png
            files.sort(key=lambda p: (0 if p.lower().endswith('.png') else 1, p))
            return os.path.join(folder, files[0])
        except Exception:
            continue
    return None


def cover_watermark_with_logo(src_path: str, out_path: str, logo_path: str | None = None, position: str = 'bottom-right', scale: float = 0.15) -> str:
    """Overlay a logo image onto the video to cover a small watermark.

    - logo_path: optional path to a logo image. If None, will search Logo/ using get_logo_path().
    - position: currently supports 'bottom-right', 'bottom-left', 'top-right', 'top-left'.
    - scale: fraction of video width that the logo should occupy (e.g. 0.15 = 15% of width).

    Writes output to out_path and returns it.
    """
    if logo_path is None:
        logo_path = get_logo_path()
    if not logo_path or not os.path.exists(logo_path):
        raise FileNotFoundError("No logo file found in Logo/ folder")
    # get video width so we can compute target logo width
    try:
        w, h, dur = get_media_info(src_path)
    except Exception as e:
        raise RuntimeError(f"Failed to probe video for overlay sizing: {e}") from e
    if not w or w <= 0:
        raise RuntimeError("Unable to determine video width for overlay sizing")
    logo_target_w = max(24, int(w * float(scale)))

    # overlay position
    margin = 10
    if position == 'bottom-right':
        overlay_expr = f"main_w-overlay_w-{margin}:main_h-overlay_h-{margin}"
    elif position == 'bottom-left':
        overlay_expr = f"{margin}:main_h-overlay_h-{margin}"
    elif position == 'top-right':
        overlay_expr = f"main_w-overlay_w-{margin}:{margin}"
    else:
        overlay_expr = f"{margin}:{margin}"

    filter_complex = f"[1:v]scale={logo_target_w}:-1[lg];[0:v][lg]overlay={overlay_expr}"

    cmd = [
        'ffmpeg', '-y', '-i', src_path, '-i', logo_path,
        '-filter_complex', filter_complex,
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
        '-c:a', 'copy', out_path
    ]
    subprocess.run(cmd, check=True)
    return out_path


@app.post('/download_facebook_and_split')
async def download_facebook_and_split(
    fb_url: str = Query(..., description='Facebook video URL'),
    Title: str = Query('', description='Optional title to use in split headers'),
    avoid_copyright: bool = Query(True, description='Apply small transform to reduce fingerprint risk'),
    part_time: int = Query(3600, description='Max seconds per split (default 3600)'),
    overlay_logo: bool = Query(False, description='If True, overlay a logo from the Logo/ folder to cover small watermarks'),
    task_id: str | None = Query(None, description='Optional existing task_id to attach results to')
):
    """Download a Facebook video, optionally apply a tiny transform, then split using split_video_by_time_with_title.

    Returns: JSON with list of produced split file paths.
    """
    # Enqueue a Facebook processing task so it runs in worker queue (non-blocking endpoint)
    cleanup_old_tasks(days=30)


@app.post("/transcribe_and_create_audio")
async def transcribe_and_create_audio(
    media_url: str = Query(..., description="Link audio or video (downloadable by yt-dlp)"),
    title: str = Query("", description="Optional title to use for output filenames"),
    voice: str = Query("nova", description="TTS voice to use (defaults to 'nova')"),
    run_in_background: bool = Query(False, description="If true, start job in background and return 202")
):
    """Download media via yt-dlp, transcribe to text, then generate audio via existing TTS flow.

    Returns JSON with `audio_path` (server path) on success or error message.
    """
    download_dir = os.path.join(OUTPUT_DIR, "downloads")
    os.makedirs(download_dir, exist_ok=True)

    # Prepare ytdlp options: download best audio and extract to mp3
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(download_dir, "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ],
    }

    loop = asyncio.get_event_loop()

    def _download_and_transcribe():
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(media_url, download=True)

            media_id = info.get("id")
            expected_mp3 = os.path.join(download_dir, f"{media_id}.mp3")
            # if postprocessor created mp3 with id
            if not os.path.exists(expected_mp3):
                # fallback: pick any file starting with id in download_dir
                for fn in os.listdir(download_dir):
                    if fn.startswith(media_id):
                        expected_mp3 = os.path.join(download_dir, fn)
                        break

            if not os.path.exists(expected_mp3):
                raise RuntimeError(f"Downloaded file not found for id {media_id}")

            # Transcribe using STTEXT.transcribe_audio (supports faster_whisper or whisper fallback)
            _trans_fn = get_transcribe_audio()
            if not _trans_fn:
                raise RuntimeError("transcribe_audio not available. Please ensure STTEXT.py is present and importable.")
            txt_path = _trans_fn(expected_mp3)
            if not txt_path or not os.path.exists(txt_path):
                raise RuntimeError("Transcription failed or produced no txt file")

            with open(txt_path, "r", encoding="utf-8") as f:
                text = f.read().strip()

            if not text:
                raise RuntimeError("Transcription produced empty text")

            # Prepare title_slug from provided title or media id
            slug_source = title if title and title.strip() else media_id or media_url
            title_slug = hashlib.md5(slug_source.encode("utf-8")).hexdigest()[:12]

            # Generate content audio via existing TTS (generate_audio_content)
            content_audio = generate_audio_content(text, title_slug, voice)

            return {"audio_path": content_audio, "text_file": txt_path, "downloaded_file": expected_mp3}
        except Exception as e:
            return {"error": str(e)}

    try:
        tasks_local = load_tasks()
        # create a placeholder task entry if missing
        request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        if request_id not in tasks_local:
            tasks_local[request_id] = {"task_id": request_id, "status": "pending", "created_at": time.time(), "title": title}
        tasks_local[request_id]['status'] = 'running'
        save_tasks(tasks_local)
    except Exception:
        pass

    tracked = create_tracked_task(request_id, asyncio.to_thread(_download_and_transcribe))
    if run_in_background:
        return JSONResponse(status_code=202, content={"started": True})

    result = await tracked
    if result.get("error"):
        return JSONResponse(status_code=500, content={"error": result.get("error")})

    # Return server path(s) (absolute) and project-relative posix path for client use
    audio_path = result.get("audio_path")
    txt_path = result.get("text_file")
    return JSONResponse(status_code=200, content={
        "audio_path": audio_path,
        "audio_rel": to_project_relative_posix(audio_path),
        "text_path": txt_path,
        "text_rel": to_project_relative_posix(txt_path),
    })


@app.post("/render_tiktok_from_video_url")
async def render_tiktok_from_video_url(
    visual_video_url: str = Query(..., description="URL(s) for visual background video, comma-separated"),
    source_media_url: str | None = Query(None, description="Source media URL to extract audio from (if omitted uses visual_video_url)") ,
    title: str = Query("", description="Optional title to use for output filenames"),
    voice: str = Query("nova", description="TTS voice to use for narration"),
    part_duration: int = Query(3600, description="Max part duration seconds"),
    refresh_audio: bool = Query(False, description="Force refresh audio generation"),
    run_in_background: bool = Query(True, description="If true, enqueue and return immediately (recommended)")
):
    """Download source media, extract/transcribe audio, create narration, then enqueue TikTok large-video task.

    This endpoint will:
      - download the `source_media_url` (or `visual_video_url` if omitted) via `download_video_url`
      - extract audio and run `transcribe_audio` to produce a text file
      - save the text file locally and enqueue a TikTok large-video task where `story_url` points to that file
    """
    cleanup_old_tasks(days=30)

    src_url = source_media_url or visual_video_url
    # Download source media to outputs/downloads/<hash>_src.mp4
    os.makedirs(os.path.join(OUTPUT_DIR, "downloads"), exist_ok=True)
    base_name = f"src_{url_hash(src_url)}"
    downloaded_path = os.path.join(OUTPUT_DIR, "downloads", f"{base_name}.mp4")

    loop = asyncio.get_event_loop()

    def _download_and_extract_and_transcribe():
        try:
            # Download video (uses internal helper)
            dp = download_video_url(src_url, downloaded_path, retries=3, delay=2, target_duration=None, fail_fast=True)
            if not dp or not os.path.exists(dp):
                raise RuntimeError("Download failed or returned invalid path")

            # Extract audio to mp3 for transcribe
            mp3_out = os.path.join(OUTPUT_DIR, "downloads", f"{base_name}.mp3")
            cmd = [
                "ffmpeg", "-y", "-i", dp,
                "-vn", "-acodec", "libmp3lame", "-ar", "24000", "-ac", "1", mp3_out
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            if not os.path.exists(mp3_out):
                raise RuntimeError("FFmpeg failed to extract audio")

            # Transcribe using STTEXT.transcribe_audio
            _trans_fn = get_transcribe_audio()
            if not _trans_fn:
                raise RuntimeError("transcribe_audio not available. Please ensure STTEXT.py is present and importable.")
            txt_path = _trans_fn(mp3_out)
            if not txt_path or not os.path.exists(txt_path):
                raise RuntimeError("Transcription failed")

            # Save a copy of text under cache with deterministic name
            with open(txt_path, "r", encoding="utf-8") as f:
                text_content = f.read()

            text_cache_path = os.path.join(CACHE_DIR, f"text_{url_hash(src_url)}.txt")
            with open(text_cache_path, "w", encoding="utf-8") as f:
                f.write(text_content)

            return {"text_file": text_cache_path, "downloaded": dp, "mp3": mp3_out}
        except Exception as e:
            return {"error": str(e)}

    if run_in_background:
        # Run download/transcribe in background and enqueue task after completion
        bg_task_id = f"render_tiktok_from_video_bg-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
        try:
            tasks_local = load_tasks()
            tasks_local.setdefault(bg_task_id, {"task_id": bg_task_id, "status": "pending", "created_at": time.time(), "title": title})
            tasks_local[bg_task_id]['status'] = 'running'
            save_tasks(tasks_local)
        except Exception:
            pass

        def _bg_work():
            res = _download_and_extract_and_transcribe()
            if res.get("error"):
                send_discord_message("❌ render_tiktok_from_video_url background failed: %s", res.get("error"))
                return
            # enqueue TikTok large-video task with story_url pointing to file://<text_cache_path>
            request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            title_slug = extract_slug(title or visual_video_url)
            urls = [u.strip() for u in visual_video_url.split(",") if u.strip()]
            story_file = res.get("text_file")
            final_video_path = os.path.join(OUTPUT_DIR, f"{title_slug}_{voice}_video.mp4") if voice else os.path.join(OUTPUT_DIR, f"{title_slug}_video.mp4")

            tasks = load_tasks()
            task_info = {
                "task_id": request_id,
                "status": "pending",
                "progress": 0,
                "video_path": final_video_path,
                "video_file": [],
                "title": title,
                "voice": voice,
                "bg_choice": None,
                "refresh": refresh_audio,
                "temp_videos": [],
                "request_urls": urls + [f"file://{story_file}"],
                "created_at": time.time(),
                "type": 4,  # reuse TikTok large video flow
                "part_duration": part_duration,
                "start_from_part": 1,
                "total_parts": 0,
                "current_part": 0
            }
            tasks[request_id] = task_info
            save_tasks(tasks)
            # enqueue
            loop2 = asyncio.new_event_loop()
            asyncio.set_event_loop(loop2)
            loop2.run_until_complete(enqueue_task({
                "task_id": request_id,
                "urls": urls,
                "story_url": f"file://{story_file}",
                "merged_video_path": "",
                "final_video_path": final_video_path,
                "title_slug": title_slug,
                "key_file": "key.json",
                "title": title,
                "voice": voice,
                "type": 4,
                "bg_choice": None,
                "refresh": refresh_audio,
                "part_duration": part_duration,
                "start_from_part": 1
            }))

        create_tracked_task(bg_task_id, asyncio.to_thread(_bg_work))
        return JSONResponse(status_code=202, content={"background_task_id": bg_task_id, "started": True})

    # synchronous path: perform download/transcribe now then enqueue
    res = await loop.run_in_executor(executor, _download_and_extract_and_transcribe)
    if res.get("error"):
        return JSONResponse(status_code=500, content={"error": res.get("error")})

    story_file = res.get("text_file")
    request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    title_slug = extract_slug(title or visual_video_url)
    urls = [u.strip() for u in visual_video_url.split(",") if u.strip()]
    final_video_path = os.path.join(OUTPUT_DIR, f"{title_slug}_{voice}_video.mp4") if voice else os.path.join(OUTPUT_DIR, f"{title_slug}_video.mp4")

    tasks = load_tasks()
    task_info = {
        "task_id": request_id,
        "status": "pending",
        "progress": 0,
        "video_path": final_video_path,
        "video_file": [],
        "title": title,
        "voice": voice,
        "bg_choice": None,
        "refresh": refresh_audio,
        "temp_videos": [],
        "request_urls": urls + [f"file://{story_file}"],
        "created_at": time.time(),
        "type": 4,  # reuse TikTok large video flow
        "part_duration": part_duration,
        "start_from_part": 1,
        "total_parts": 0,
        "current_part": 0
    }
    tasks[request_id] = task_info
    save_tasks(tasks)

    # Enqueue job for worker
    await enqueue_task({
        "task_id": request_id,
        "urls": urls,
        "story_url": f"file://{story_file}",
        "merged_video_path": "",
        "final_video_path": final_video_path,
        "title_slug": title_slug,
        "key_file": "key.json",
        "title": title,
        "voice": voice,
        "type": 4,
        "bg_choice": None,
        "refresh": refresh_audio,
        "part_duration": part_duration,
        "start_from_part": 1
    })

    send_discord_message(f"📨 Đã xếp task render_tiktok_from_video_url vào hàng chờ: {request_id}")
    return JSONResponse(status_code=200, content={"task_id": request_id})

    # Choose or create task id
    if task_id:
        request_id = task_id
    else:
        request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")

    title_slug = extract_slug(fb_url)

    tasks = load_tasks()
    task_info = {
        "task_id": request_id,
        "status": "pending",
        "progress": 0,
        "video_path": "",
        "video_file": [],
        "title": Title,
        "temp_videos": [],
        "request_urls": [fb_url],
        "created_at": time.time(),
        "task_type": "facebook",
        "fb_url": fb_url,
        "avoid_copyright": avoid_copyright,
        "part_time": part_time,
        "overlay_logo": overlay_logo,
        "key_file": "key.json"
    }
    
    tasks[request_id] = task_info
    save_tasks(tasks)

    # Put into the existing TASK_QUEUE so workers will process it sequentially
    await enqueue_task({
        "task_id": request_id,
        "task_type": "facebook",
        "fb_url": fb_url,
        "title": Title,
        "avoid_copyright": avoid_copyright,
        "part_time": part_time,
        "overlay_logo": overlay_logo,
        "key_file": "key.json"
    })

    send_discord_message("📨 Đã xếp Facebook task %s vào hàng chờ", request_id)
    return {"task_id": request_id}


def remove_corrupt_video_from_cache(video_path: str):
    """Xóa video corrupt khỏi cache và log.
    
    Args:
        video_path: Đường dẫn video bị corrupt
    """
    try:
        if os.path.exists(video_path) and VIDEO_CACHE_DIR in video_path:
            os.remove(video_path)
            send_discord_message(f"🗑️ Đã xóa video corrupt khỏi cache: {os.path.basename(video_path)}")
            return True
    except Exception as e:
        send_discord_message(f"⚠️ Không thể xóa video corrupt {video_path}: {e}")
    return False


def extract_random_segment_from_video(video_path: str, target_duration: float, output_path: str) -> str:
    """Extract một segment ngẫu nhiên từ video để tận dụng toàn bộ video dài.
    
    Args:
        video_path: Đường dẫn video nguồn
        target_duration: Thời lượng segment cần lấy (giây)
        output_path: Đường dẫn file output
        
    Returns:
        Đường dẫn file segment đã extract
    """
    import random
    
    # Lấy thông tin video
    _, _, video_duration, _ = get_media_info_fbs(video_path)
    
    if video_duration <= target_duration:
        # Video ngắn hơn hoặc bằng target, copy toàn bộ
        start_time = 0
        duration = video_duration
    else:
        # Random chọn điểm bắt đầu
        max_start = video_duration - target_duration
        start_time = random.uniform(0, max_start)
        duration = target_duration
    
    send_discord_message(
        f"✂️ Extract segment từ {os.path.basename(video_path)}: "
        f"{start_time:.1f}s → {start_time+duration:.1f}s (total: {video_duration:.1f}s)"
    )
    
    # Extract segment bằng ffmpeg
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_time),
        "-t", str(duration),
        "-i", video_path,
        "-c", "copy",  # Copy codec để nhanh
        output_path
    ]
    
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path
    except subprocess.CalledProcessError as e:
        # Nếu copy codec fail, thử re-encode
        send_discord_message(f"⚠️ Copy codec fail, thử re-encode...")
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_time),
            "-t", str(duration),
            "-i", video_path,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            output_path
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path


def split_audio_by_duration(audio_path: str, max_part_duration: int = 3600, output_dir: str = None) -> list:
    """Chia audio thành các part cân bằng, tránh part cuối quá ngắn.
    
    Logic chia:
    - Tính số part = ceil(tổng_thời_lượng / max_part_duration)
    - Thời lượng mỗi part = tổng_thời_lượng / số_part (chia đều)
    
    Ví dụ:
    - Audio 70p, max=60p → 2 part → mỗi part 35p
    - Audio 150p, max=60p → 3 part → mỗi part 50p
    - Audio 50p, max=60p → 1 part → mỗi part 50p
    
    Args:
        audio_path: Đường dẫn file audio (.flac hoặc .wav)
        max_part_duration: Thời lượng tối đa mỗi part (giây), dùng để tính số part
        output_dir: Thư mục lưu các part, mặc định cùng thư mục với audio
        
    Returns:
        List các đường dẫn file audio part đã tạo
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Không tìm thấy file audio: {audio_path}")
    
    # Lấy thông tin audio
    _, _, total_duration = get_media_info(audio_path)
    
    if output_dir is None:
        output_dir = os.path.dirname(audio_path)
    
    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    
    # Tính số part cần chia (làm tròn lên)
    num_parts = math.ceil(total_duration / max_part_duration)
    
    # Tính thời lượng thực tế cho mỗi part (chia đều)
    actual_part_duration = total_duration / num_parts
    
    send_discord_message(
        f"🔪 Audio {total_duration/60:.1f}p → {num_parts} part × {actual_part_duration/60:.1f}p = {total_duration/60:.1f}p"
    )
    
    audio_parts = []
    for i in range(num_parts):
        # Tính thời điểm bắt đầu và thời lượng cho part này
        start_time = i * actual_part_duration
        
        # Part cuối cùng lấy đến hết audio (tránh sai số làm tròn)
        if i == num_parts - 1:
            duration = total_duration - start_time
        else:
            duration = actual_part_duration
        
        # Always create a fresh final part (overwrite if exists).
        # We intentionally do NOT reuse any existing candidate files here because
        # downstream cleanup will remove generated parts after the full job completes.
        part_file = os.path.join(output_dir, f"{base_name}_part{i+1}.flac")
        
        send_discord_message(
            f"✂️ Tạo part {i+1}/{num_parts}: "
            f"{start_time/60:.1f}p → {(start_time+duration)/60:.1f}p "
            f"(~{duration/60:.1f}p)"
        )
        
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_time),
            "-t", str(duration),
            "-i", audio_path,
            "-af", "aresample=24000",  # Force resample to ensure consistent format
            "-c:a", "flac",
            "-sample_fmt", "s16",  # Force 16-bit sample format
            part_file
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            audio_parts.append(part_file)
        except subprocess.CalledProcessError as e:
            send_discord_message(f"❌ Lỗi khi tạo audio part {i+1}: {e.stderr.decode()}")
            raise
    
    return audio_parts


# audio helpers (moved to audio_helpers.py)


def render_tiktok_video_from_audio_part(
    video_paths: list,
    audio_part_path: str,
    output_path: str,
    title: str = "",
    part_number: int = 1,
    total_parts: int = 1,
    font_path: str = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
) -> str:
    """Render video TikTok từ một audio part.
    
    Mỗi part sẽ random chọn video từ video_paths để tránh lặp lại nội dung.
    
    Args:
        video_paths: Danh sách đường dẫn video nguồn (sẽ random chọn)
        audio_part_path: Đường dẫn audio part
        output_path: Đường dẫn video output
        title: Tiêu đề để hiển thị
        part_number: Số thứ tự part hiện tại
        total_parts: Tổng số part
        font_path: Đường dẫn font cho text
        
    Returns:
        Đường dẫn video đã render
    """
    if os.path.exists(output_path):
        send_discord_message(f"♻️ Video part {part_number} đã tồn tại: {output_path}")
        return output_path
    
    send_discord_message(f"🎬 Render video part {part_number}/{total_parts}")
    
    # Lấy thông tin audio part
    _, _, audio_dur = get_media_info(audio_part_path)
    
    # Random chọn video từ video_paths (tránh lặp lại giữa các part)
    # Số lượng video cần lấy: tối thiểu 1, tối đa 3
    num_videos_needed = min(3, len(video_paths))
    selected_videos = random.sample(video_paths, num_videos_needed)
    
    send_discord_message(f"🎲 Part {part_number}: Random chọn {num_videos_needed} video từ {len(video_paths)} video khả dụng")
    
    # Kiểm tra xem có video nào từ cache không
    # Nếu có, extract random segment để tận dụng toàn bộ video dài
    is_from_cache = any(VIDEO_CACHE_DIR in v for v in selected_videos)
    temp_extracted_videos = []
    
    if is_from_cache:
        send_discord_message(f"📦 Part {part_number}: Phát hiện video từ cache, sẽ extract random segment...")
        extracted_videos = []
        remaining_cache_videos = [v for v in video_paths if v not in selected_videos and VIDEO_CACHE_DIR in v]
        
        for idx, video_path in enumerate(selected_videos):
            if VIDEO_CACHE_DIR in video_path:
                # Video từ cache → extract random segment
                base_name = os.path.basename(video_path)
                # ensure output segment has a proper extension (prefer original extension or .mp4)
                orig_ext = os.path.splitext(base_name)[1] or ".mp4"
                segment_name = f"segment_part{part_number}_v{idx+1}_{os.path.splitext(base_name)[0]}{orig_ext}"
                segment_path = os.path.join(OUTPUT_DIR, segment_name)
                
                success = False
                current_video = video_path
                attempts = 0
                max_attempts = min(5, len(video_paths))
                
                while not success and attempts < max_attempts:
                    try:
                        # Lấy thông tin video để tính target duration phù hợp
                        _, _, video_dur, _ = get_media_info_fbs(current_video)
                        
                        # Compute a robust target duration for the extracted segment.
                        # Aim for roughly (audio_dur / num_videos_needed), allow a small buffer,
                        # but clamp to a sensible minimum so very short segments are avoided.
                        ideal_duration = float(audio_dur) / max(1, num_videos_needed)
                        min_segment = 8  # seconds (allow short segments for short audio parts)
                        # allow +15% buffer but never exceed the video duration
                        target_duration = min(video_dur, max(min_segment, int(ideal_duration * 1.15)))
                        # Safety: if target_duration ends up 0 or negative, fallback to 8s
                        if target_duration <= 0:
                            target_duration = min(video_dur, min_segment)
                        
                        extract_random_segment_from_video(current_video, target_duration, segment_path)
                        extracted_videos.append(segment_path)
                        temp_extracted_videos.append(segment_path)
                        success = True
                        send_discord_message(f"✅ Part {part_number}: Extracted segment từ {os.path.basename(current_video)}")
                    except Exception as e:
                        attempts += 1
                        error_msg = str(e)
                        send_discord_message(
                            f"⚠️ Part {part_number}: Video corrupt/lỗi '{os.path.basename(current_video)}': {error_msg[:100]}"
                        )
                        
                        # Nếu video corrupt (moov atom not found, invalid data, etc), xóa khỏi cache
                        if "moov atom not found" in error_msg or "Invalid data" in error_msg or "corrupt" in error_msg.lower():
                            remove_corrupt_video_from_cache(current_video)
                        
                        # Thử lấy video thay thế từ cache
                        if remaining_cache_videos:
                            replacement = remaining_cache_videos.pop(0)
                            send_discord_message(
                                f"🔄 Part {part_number}: Thay thế bằng '{os.path.basename(replacement)}'"
                            )
                            current_video = replacement
                        else:
                            send_discord_message(f"❌ Part {part_number}: Không còn video cache khả dụng!")
                            break
                
                if not success:
                    # Không extract được, bỏ qua video này
                    send_discord_message(f"⚠️ Part {part_number}: Bỏ qua video {idx+1}, tiếp tục với video còn lại")
                    
            else:
                # Video không từ cache → giữ nguyên
                extracted_videos.append(video_path)
        
        selected_videos = extracted_videos
        send_discord_message(f"✅ Part {part_number}: Đã extract {len(temp_extracted_videos)} segment từ cache")
    
    # Lấy thông tin video và tính tổng thời lượng
    # Nếu get_media_info_fbs bị lỗi, thay thế video khác
    video_infos = []
    total_video_dur = 0
    fps_values = []
    valid_videos = []
    remaining_videos = [v for v in video_paths if v not in selected_videos]
    max_retries = min(10, len(video_paths))  # Giới hạn số lần thử
    retry_count = 0
    
    for idx, p in enumerate(selected_videos):
        success = False
        current_video = p
        
        while not success and retry_count < max_retries:
            try:
                w, h, d, fps = get_media_info_fbs(current_video)
                video_infos.append((w, h, d, fps))
                valid_videos.append(current_video)
                total_video_dur += d
                if fps > 0:
                    fps_values.append(fps)
                success = True
                send_discord_message(f"✅ Part {part_number}: Video {idx+1} OK - {os.path.basename(current_video)}")
            except Exception as e:
                retry_count += 1
                error_msg = str(e)
                send_discord_message(
                    f"⚠️ Part {part_number}: Lỗi get_media_info cho video '{os.path.basename(current_video)}': {error_msg[:150]}"
                )
                
                # Nếu video từ cache và bị corrupt, xóa khỏi cache
                if VIDEO_CACHE_DIR in current_video:
                    if "moov atom not found" in error_msg or "Invalid data" in error_msg or "corrupt" in error_msg.lower():
                        remove_corrupt_video_from_cache(current_video)
                
                # Thử lấy video thay thế từ danh sách còn lại
                if remaining_videos:
                    replacement = random.choice(remaining_videos)
                    remaining_videos.remove(replacement)
                    send_discord_message(
                        f"🔄 Part {part_number}: Thay thế bằng video '{os.path.basename(replacement)}'"
                    )
                    current_video = replacement
                else:
                    # Không còn video để thay thế
                    send_discord_message(
                        f"❌ Part {part_number}: Không còn video khả dụng để thay thế!"
                    )
                    raise RuntimeError(f"Không thể lấy thông tin video sau {retry_count} lần thử")
        
        if not success:
            raise RuntimeError(f"Đã thử {max_retries} lần nhưng không tìm được video khả dụng")
    
    # Cập nhật selected_videos với danh sách video hợp lệ
    selected_videos = valid_videos
    
    if not fps_values:
        fps_values.append(30)
    
    min_fps = min(fps_values) if fps_values else 30
    
    # Lặp video nếu audio dài hơn
    loops = math.ceil(audio_dur / total_video_dur) if total_video_dur < audio_dur else 1
    extended_video_paths = selected_videos * loops
    
    # Build filter_complex
    filters = []
    for i, (w, h, _, fps) in enumerate(video_infos * loops):
        aspect = w / h
        target = 9 / 16
        
        if aspect > target:
            new_w = int(h * target)
            x_offset = (w - new_w) // 2
            crop = f"crop={new_w}:{h}:{x_offset}:0"
        else:
            new_h = int(w / target)
            y_offset = (h - new_h) // 2
            crop = f"crop={w}:{new_h}:0:{y_offset}"
        
        filters.append(f"[{i}:v]{crop},scale=1080:1920,fps={min_fps},setsar=1[v{i}]")
    
    # Concat video
    concat_inputs = "".join([f"[v{i}]" for i in range(len(extended_video_paths))])
    filters.append(f"{concat_inputs}concat=n={len(extended_video_paths)}:v=1:a=0[vc]")
    
    # Thêm tiêu đề
    if title:
        if total_parts == 1:
            text = f"[FULL] {title.upper()}"
        else:
            text = f"{title.upper()} - PHẦN {part_number}/{total_parts}"

        # Escape ký tự đặc biệt cho ffmpeg
        text = (
            text.replace("\\", "\\\\")
                .replace(":", "\\:")
                .replace("'", "\\'")
                .replace(",", "\\,")
        )

        wrapped_text = wrap_text(text, max_chars_per_line=35)

        title_filter = (
                f"drawtext=fontfile='{font_path}':"
                f"text='{wrapped_text}':"
                f"fontcolor=white:"
                f"fontsize=40:"
                f"text_align=center:"
                f"box=1:"
                f"boxcolor=black@1:"
                f"boxborderw=20:"
                f"x=(w-text_w)/2:"
                f"y=(h-text_h-line_h)/2:"
                f"enable='between(t\\,0\\,3)'"
        )

        filters.append(f"[vc]{title_filter}[v]")
    else:
        filters.append("[vc]copy[v]")
    
    # Audio resampling
    filters.append(f"[{len(extended_video_paths)}:a]aresample=48000[a]")
    
    filter_complex = ";".join(filters)
    
    # Build ffmpeg command
    cmd = ["ffmpeg", "-y", "-fflags", "+genpts"]
    
    for p in extended_video_paths:
        cmd += ["-i", p]
    
    cmd += ["-i", audio_part_path]
    cmd += [
        "-t", str(audio_dur),
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-shortest",
        "-pix_fmt", "yuv420p",
        output_path
    ]
    send_discord_message(cmd);
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode != 0:
        logging.error(f"❌ FFmpeg error:\n{result.stderr}")
        raise RuntimeError(f"Lỗi khi render video part {part_number}")
    
    # Cleanup temp extracted segments
    for temp_file in temp_extracted_videos:
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
                send_discord_message(f"🗑️ Đã xóa temp segment: {os.path.basename(temp_file)}")
        except Exception as e:
            send_discord_message(f"⚠️ Không thể xóa temp file {temp_file}: {e}")
    
    send_discord_message(f"✅ Hoàn tất render video part {part_number}: {output_path}")
    return output_path


@app.post("/render_tiktok_large_video")
async def render_tiktok_large_video(
    video_url: str = Query(..., description="URL video nguồn (có thể nhiều, phân cách bằng dấu phẩy)"),
    story_url: str = Query(..., description="URL truyện"),
    title: str = Query("", description="Tiêu đề video"),
    voice: str = Query("", description="Voice name or instruction"),
    bg_choice: str = Query(None, description="Tên file nhạc nền (optional)"),
    part_duration: int = Query(3600, description="Thời lượng tối đa mỗi part (giây), mặc định 3600s = 60p"),
    start_from_part: int = Query(1, description="Bắt đầu render từ part số (để tiếp tục khi lỗi)"),
    refresh_audio: bool = Query(False, description="Tạo lại audio mới")
):
    """
    Endpoint render video TikTok cho video dung lượng lớn.
    
    Quy trình:
    1. Tạo audio hoàn chỉnh từ truyện
    2. Xử lý audio (tăng tốc + nhạc nền) 
    3. Chia audio thành các part cân bằng (tránh part cuối quá ngắn)
    4. Render từng video part từ audio đã chia
    5. Kiểm tra part đã tồn tại để bỏ qua
    6. Cho phép tiếp tục từ part chỉ định nếu bị lỗi
    
    Returns:
        task_id để theo dõi tiến trình
    """
    cleanup_old_tasks(days=30)
    
    request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    title_slug = extract_slug(story_url)
    urls = [u.strip() for u in video_url.split(",") if u.strip()]
    
    final_video_path = os.path.join(OUTPUT_DIR, f"{title_slug}_{voice}_video.mp4") if voice else os.path.join(OUTPUT_DIR, f"{title_slug}_video.mp4")
    
    # Tạo task metadata
    tasks = load_tasks()
    task_info = {
        "task_id": request_id,
        "status": "pending",
        "progress": 0,
        "video_path": final_video_path,
        "video_file": [],
        "title": title,
        "voice": voice,
        "bg_choice": bg_choice,
        "refresh": refresh_audio,
        "temp_videos": [],
        "request_urls": urls + [story_url],
        "created_at": time.time(),
        "type": 4,  # Type 4 = TikTok Large Video
        "part_duration": part_duration,
        "start_from_part": start_from_part,
        "total_parts": 0,
        "current_part": 0
    }
    tasks[request_id] = task_info
    save_tasks(tasks)
    
    # Đẩy vào queue (worker sẽ xử lý)
    await enqueue_task({
        "task_id": request_id,
        "urls": urls,
        "story_url": story_url,
        "merged_video_path": "",
        "final_video_path": final_video_path,
        "title_slug": title_slug,
        "key_file": "key.json",
        "title": title,
        "voice": voice,
        "type": 4,
        "bg_choice": bg_choice,
        "refresh": refresh_audio,
        "part_duration": part_duration,
        "start_from_part": start_from_part
    })
    
    send_discord_message(f"📨 Đã xếp task TikTok Large Video vào hàng chờ: {request_id}")
    return {"task_id": request_id}


@app.post("/render_tiktok_large_video_gemini")
async def render_tiktok_large_video_gemini(
    video_url: str = Query(..., description="URL video nguồn (có thể nhiều, phân cách bằng dấu phẩy)"),
    story_url: str = Query(..., description="URL truyện"),
    title: str = Query("", description="Tiêu đề video"),
    voice: str = Query("", description="Voice name or instruction (ignored for Gemini)"),
    bg_choice: str = Query(None, description="Tên file nhạc nền (optional)"),
    part_duration: int = Query(3600, description="Thời lượng tối đa mỗi part (giây), mặc định 3600s = 60p"),
    start_from_part: int = Query(1, description="Bắt đầu render từ part số (để tiếp tục khi lỗi)"),
    refresh_audio: bool = Query(False, description="Tạo lại audio mới")
):
    """
    Same as `/render_tiktok_large_video` but forces use of Gemini TTS (generate_audio_Gemini) to create the narration audio.

    Returns:
        task_id để theo dõi tiến trình
    """
    cleanup_old_tasks(days=30)

    request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    title_slug = extract_slug(story_url)
    if video_url:
        urls = [u.strip() for u in video_url.split(",") if u.strip()]
    else:
        urls = []
    final_video_path = os.path.join(OUTPUT_DIR, f"{title_slug}_{voice}_video.mp4") if voice else os.path.join(OUTPUT_DIR, f"{title_slug}_video.mp4")

    # Tạo task metadata
    tasks = load_tasks()
    task_info = {
        "task_id": request_id,
        "status": "pending",
        "progress": 0,
        "video_path": final_video_path,
        "video_file": [],
        "title": title,
        "voice": voice,
        "bg_choice": bg_choice,
        "refresh": refresh_audio,
        "temp_videos": [],
        "request_urls": urls + [story_url],
        "created_at": time.time(),
        "type": 4,  # Type 4 = TikTok Large Video
        "part_duration": part_duration,
        "start_from_part": start_from_part,
        "use_gemini": True,
        "total_parts": 0,
        "current_part": 0
    }
    tasks[request_id] = task_info
    save_tasks(tasks)

    # Đẩy vào queue (worker sẽ xử lý)
    await enqueue_task({
        "task_id": request_id,
        "urls": urls,
        "story_url": story_url,
        "merged_video_path": "",
        "final_video_path": final_video_path,
        "title_slug": title_slug,
        "key_file": "key.json",
        "title": title,
        "voice": voice,
        "type": 4,
        "bg_choice": bg_choice,
        "refresh": refresh_audio,
        "part_duration": part_duration,
        "start_from_part": start_from_part,
        "use_gemini": True
    })

    send_discord_message(f"📨 Đã xếp task TikTok Large Video (Gemini TTS) vào hàng chờ: {request_id}")
    return {"task_id": request_id}


@app.post("/render_tiktok_large_video_openai_echo")
async def render_tiktok_large_video_openai_echo(
    video_url: str = Query(..., description="URL video nguồn (có thể nhiều, phân cách bằng dấu phẩy)"),
    story_url: str = Query(..., description="URL truyện"),
    title: str = Query("", description="Tiêu đề video"),
    include_summary: bool = Query(True, description="Có gắn văn án (summary) trước nội dung không"),
    bg_choice: str = Query(None, description="Tên file nhạc nền (optional)"),
    part_duration: int = Query(3600, description="Thời lượng tối đa mỗi part (giây), mặc định 3600s = 60p"),
    start_from_part: int = Query(1, description="Bắt đầu render từ part số (để tiếp tục khi lỗi)"),
    refresh_audio: bool = Query(False, description="Tạo lại audio mới"),
    voice: str = Query("", description="Voice name or instruction (ignored for OpenAI 'echo')")
):
    """
    Render TikTok large video using OpenAI TTS with voice 'echo'.

    If `include_summary` is False this endpoint will behave like the No-Summary flow.
    Returns a `task_id` that the worker will process in background.
    """
    cleanup_old_tasks(days=30)

    request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    title_slug = extract_slug(story_url)
    urls = [u.strip() for u in video_url.split(",") if u.strip()]

    # Force voice 'echo' for this endpoint, use it in filename
    final_video_path = os.path.join(OUTPUT_DIR, f"{title_slug}_echo_video.mp4")

    # Tạo task metadata
    tasks = load_tasks()
    task_info = {
        "task_id": request_id,
        "status": "pending",
        "progress": 0,
        "video_path": final_video_path,
        "video_file": [],
        "title": title,
        "bg_choice": bg_choice,
        "refresh": refresh_audio,
        "temp_videos": [],
        "request_urls": urls + [story_url],
        "created_at": time.time(),
        # type 4 = TikTok Large Video with summary; type 6 = No Summary
        "type": 4 if include_summary else 6,
        "part_duration": part_duration,
        "start_from_part": start_from_part,
        # force OpenAI voice
        "force_voice": voice,
        "include_summary": include_summary,
        "total_parts": 0,
        "current_part": 0
    }
    tasks[request_id] = task_info
    save_tasks(tasks)

    # Đẩy vào queue (worker sẽ xử lý)
    await enqueue_task({
        "task_id": request_id,
        "urls": urls,
        "story_url": story_url,
        "merged_video_path": "",
        "final_video_path": final_video_path,
        "title_slug": title_slug,
        "key_file": "key.json",
        "title": title,
        "type": 4 if include_summary else 6,
        "bg_choice": bg_choice,
        "refresh": refresh_audio,
        "part_duration": part_duration,
        "start_from_part": start_from_part,
        "force_voice": voice,
        "include_summary": include_summary
    })

    send_discord_message(f"📨 Đã xếp task TikTok Large Video (OpenAI 'echo') vào hàng chờ: {request_id}")
    return {"task_id": request_id}


@app.post("/render_tiktok_large_video_parts")
async def render_tiktok_large_video_parts(
    video_url: str = Query(..., description="URL video nguồn (có thể nhiều, phân cách bằng dấu phẩy)"),
    story_url: str = Query(..., description="URL truyện"),
    parts: str = Query(..., description="Danh sách các part cần render, cách nhau bởi dấu phẩy. VD: 1,3,5,7"),
    title: str = Query("", description="Tiêu đề video"),
    voice: str = Query("", description="Voice name or instruction"),
    bg_choice: str = Query(None, description="Tên file nhạc nền (optional)"),
    part_duration: int = Query(3600, description="Thời lượng tối đa mỗi part (giây), mặc định 3600s = 60p"),
    refresh_audio: bool = Query(False, description="Tạo lại audio mới")
):
    """
    Endpoint render video TikTok cho video dung lượng lớn - CHỈ RENDER CÁC PART CỤ THỂ.
    
    Quy trình:
    1. Tạo audio hoàn chỉnh từ truyện
    2. Xử lý audio (tăng tốc + nhạc nền) 
    3. Chia audio thành các part cân bằng
    4. CHỈ RENDER CÁC PART ĐƯỢC LIỆT KÊ (ví dụ: parts=1,3,5 sẽ chỉ render part 1, 3, và 5)
    5. Kiểm tra part đã tồn tại để bỏ qua
    
    Args:
        parts: Chuỗi các số part cách nhau bởi dấu phẩy. VD: "1,3,5,7" hoặc "2,4,6"
    
    Returns:
        task_id để theo dõi tiến trình
    """
    cleanup_old_tasks(days=30)
    
    # Parse danh sách part cần render
    try:
        parts_to_render = [int(p.strip()) for p in parts.split(",") if p.strip()]
        if not parts_to_render:
            return JSONResponse(
                status_code=400, 
                content={"error": "Phải chỉ định ít nhất một part để render"}
            )
        # Kiểm tra part phải là số dương
        if any(p <= 0 for p in parts_to_render):
            return JSONResponse(
                status_code=400,
                content={"error": "Số part phải là số nguyên dương"}
            )
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": f"Format parts không hợp lệ: '{parts}'. Phải là các số cách nhau bởi dấu phẩy, VD: 1,3,5"}
        )
    
    request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    title_slug = extract_slug(story_url)
    urls = [u.strip() for u in video_url.split(",") if u.strip()]
    
    final_video_path = os.path.join(OUTPUT_DIR, f"{title_slug}_{voice}_video.mp4") if voice else os.path.join(OUTPUT_DIR, f"{title_slug}_video.mp4")
    
    # Tạo task metadata
    tasks = load_tasks()
    task_info = {
        "task_id": request_id,
        "status": "pending",
        "progress": 0,
        "video_path": final_video_path,
        "video_file": [],
        "title": title,
        "voice": voice,
        "bg_choice": bg_choice,
        "refresh": refresh_audio,
        "temp_videos": [],
        "request_urls": urls + [story_url],
        "created_at": time.time(),
        "type": 5,  # Type 5 = TikTok Large Video (Specific Parts)
        "part_duration": part_duration,
        "parts_to_render": parts_to_render,  # Danh sách part cụ thể
        "total_parts": 0,
        "current_part": 0
    }
    tasks[request_id] = task_info
    save_tasks(tasks)
    
    # Đẩy vào queue (worker sẽ xử lý)
    await enqueue_task({
        "task_id": request_id,
        "urls": urls,
        "story_url": story_url,
        "merged_video_path": "",
        "final_video_path": final_video_path,
        "title_slug": title_slug,
        "key_file": "key.json",
        "title": title,
        "voice": voice,
        "type": 5,
        "bg_choice": bg_choice,
        "refresh": refresh_audio,
        "part_duration": part_duration,
        "parts_to_render": parts_to_render
    })
    
    send_discord_message(f"📨 Đã xếp task TikTok Large Video (Parts: {parts}) vào hàng chờ: {request_id}")
    return {"task_id": request_id, "parts_to_render": parts_to_render}


@app.post("/render_tiktok_large_video_no_summary")
async def render_tiktok_large_video_no_summary(
    video_url: str = Query(..., description="URL video nguồn (có thể nhiều, phân cách bằng dấu phẩy)"),
    story_url: str = Query(..., description="URL truyện"),
    title: str = Query("", description="Tiêu đề video"),
    voice: str = Query("", description="Voice name or instruction"),
    bg_choice: str = Query(None, description="Tên file nhạc nền (optional)"),
    part_duration: int = Query(3600, description="Thời lượng tối đa mỗi part (giây), mặc định 3600s = 60p"),
    start_from_part: int = Query(1, description="Bắt đầu render từ part số (để tiếp tục khi lỗi)"),
    refresh_audio: bool = Query(False, description="Tạo lại audio mới")
):
    """
    Endpoint render video TikTok cho video dung lượng lớn - CHỈ LẤY NỘI DUNG TRUYỆN (KHÔNG LẤY VĂN ÁN).
    
    Quy trình:
    1. Tạo audio hoàn chỉnh từ truyện (CHỈ NỘI DUNG, BỎ QUA VĂN ÁN)
    2. Xử lý audio (tăng tốc + nhạc nền) 
    3. Chia audio thành các part cân bằng (tránh part cuối quá ngắn)
    4. Render từng video part từ audio đã chia
    5. Kiểm tra part đã tồn tại để bỏ qua
    6. Cho phép tiếp tục từ part chỉ định nếu bị lỗi
    
    Returns:
        task_id để theo dõi tiến trình
    """
    cleanup_old_tasks(days=30)
    
    request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    title_slug = extract_slug(story_url)
    urls = [u.strip() for u in video_url.split(",") if u.strip()]
    
    final_video_path = os.path.join(OUTPUT_DIR, f"{title_slug}_{voice}_video.mp4") if voice else os.path.join(OUTPUT_DIR, f"{title_slug}_video.mp4")
    
    # Tạo task metadata
    tasks = load_tasks()
    task_info = {
        "task_id": request_id,
        "status": "pending",
        "progress": 0,
        "video_path": final_video_path,
        "video_file": [],
        "title": title,
        "voice": voice,
        "bg_choice": bg_choice,
        "refresh": refresh_audio,
        "temp_videos": [],
        "request_urls": urls + [story_url],
        "created_at": time.time(),
        "type": 6,  # Type 6 = TikTok Large Video (No Summary)
        "part_duration": part_duration,
        "start_from_part": start_from_part,
        "total_parts": 0,
        "current_part": 0
    }
    tasks[request_id] = task_info
    save_tasks(tasks)
    
    # Đẩy vào queue (worker sẽ xử lý)
    await enqueue_task({
        "task_id": request_id,
        "urls": urls,
        "story_url": story_url,
        "merged_video_path": "",
        "final_video_path": final_video_path,
        "title_slug": title_slug,
        "key_file": "key.json",
        "title": title,
        "voice": voice,
        "type": 6,
        "bg_choice": bg_choice,
        "refresh": refresh_audio,
        "part_duration": part_duration,
        "start_from_part": start_from_part
    })
    
    send_discord_message(f"📨 Đã xếp task TikTok Large Video (No Summary) vào hàng chờ: {request_id}")
    return {"task_id": request_id}


@app.get("/render_tiktok_large_video_unified")
async def render_tiktok_large_video_unified(
    video_url: str | None = Query(None, description="URL video nguồn (có thể nhiều, phân cách bằng dấu phẩy)"),
    story_url: str = Query(..., description="URL truyện"),
    title: str = Query("", description="Tiêu đề video"),
    voice: str = Query("", description="Voice name or instruction"),
    bg_choice: str = Query(None, description="Tên file nhạc nền (optional)"),
    part_duration: int = Query(3600, description="Thời lượng tối đa mỗi part (giây), mặc định 3600s = 60p"),
    start_from_part: int = Query(1, description="Bắt đầu render từ part số (để tiếp tục khi lỗi)"),
    refresh_audio: bool = Query(False, description="Tạo lại audio mới"),
    ai_backend: str = Query("default", description="AI backend: 'gemini', 'openai', 'openai_echo' or 'default'"),
    include_summary: bool = Query(True, description="Có gắn văn án (summary) trước nội dung không"),
    parts: str | None = Query(None, description="(optional) danh sách part cần render, cách nhau bởi dấu phẩy (ví dụ: '1,3,5')"),
    # TikTok upload scheduling fields (optional)
    is_upload_tiktok: bool = Query(False, description="If true, schedule upload to TikTok when rendering finishes"),
    upload_duration_hours: int | None = Query(None, description="Delay before upload in hours (used for scheduling)"),
    tiktok_tags: str | None = Query(None, description="Comma-separated tags (or JSON array string) to attach to upload"),
    cookies: str | None = Query(None, description="Cookies name/file to use for TikTok uploader (will resolve under Cookies/)")
):
    """
    Unified endpoint that covers multiple render modes:

    - If `parts` is provided -> render specific parts (type 5)
    - If `ai_backend=='gemini'` -> use Gemini TTS (use_gemini=True, type 4)
    - If `ai_backend=='openai_echo'` -> force OpenAI 'echo' voice (type 4 or 6 depending on include_summary)
    - If `include_summary` is False -> No-summary flow (type 6)

    Returns: task_id and optional parts list
    """
    cleanup_old_tasks(days=30)

    # parse parts if provided
    parts_to_render = None
    if parts:
        try:
            parts_to_render = [int(p.strip()) for p in parts.split(',') if p.strip()]
            if not parts_to_render:
                return JSONResponse(status_code=400, content={"error": "Phải chỉ định ít nhất một part để render"})
            if any(p <= 0 for p in parts_to_render):
                return JSONResponse(status_code=400, content={"error": "Số part phải là số nguyên dương"})
        except ValueError:
            return JSONResponse(status_code=400, content={"error": f"Format parts không hợp lệ: '{parts}'"})

    request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    title_slug = extract_slug(story_url)
    folder_label = safe_filename(title) if title else safe_filename(title_slug or request_id)
    task_output_dir = os.path.join(OUTPUT_DIR, folder_label)
    os.makedirs(task_output_dir, exist_ok=True)
    if video_url:
        urls = [u.strip() for u in video_url.split(",") if u.strip()]
    else:
        urls = []

    # decide final filename
    if ai_backend == 'openai_echo':
        final_video_path = os.path.join(task_output_dir, f"{title_slug}_echo_video.mp4")
    else:
        final_video_path = os.path.join(task_output_dir, f"{title_slug}_{voice}_video.mp4") if voice else os.path.join(task_output_dir, f"{title_slug}_video.mp4")

    # determine task type and extra flags
    if parts_to_render is not None:
        task_type = 5
    else:
        if ai_backend == 'gemini':
            task_type = 4
        elif ai_backend == 'openai_echo':
            task_type = 4 if include_summary else 6
        else:
            # default: include_summary true -> type 4, else type 6
            task_type = 4 if include_summary else 6

    # Parse tiktok_tags before creating task_info
    parsed_tags = None
    if isinstance(tiktok_tags, str) and tiktok_tags:
        try:
            if (tiktok_tags.strip().startswith('[') and tiktok_tags.strip().endswith(']')):
                parsed_tags = json.loads(tiktok_tags)
            else:
                parsed_tags = [t.strip().lstrip('#') for t in tiktok_tags.split(',') if t.strip()]
        except Exception:
            parsed_tags = [t.strip().lstrip('#') for t in tiktok_tags.split(',') if t.strip()]

    tasks = load_tasks()
    task_info = {
        "task_id": request_id,
        "status": "pending",
        "progress": 0,
        "video_path": final_video_path,
        "video_file": [],
        "title": title,
        "voice": voice,
        "bg_choice": bg_choice,
        "refresh": refresh_audio,
        "temp_videos": [],
        "request_urls": urls + [story_url],
        "created_at": time.time(),
        "type": task_type,
        "part_duration": part_duration,
        "start_from_part": start_from_part,
        "total_parts": 0,
        "current_part": 0,
        # TikTok upload metadata
        "is_upload_tiktok": bool(is_upload_tiktok),
        "upload_duration_hours": int(upload_duration_hours) if upload_duration_hours else None,
        "tiktok_tags": parsed_tags,
        "tiktok_cookies": str(cookies) if cookies else None,
        "output_dir": task_output_dir
    }

    # extra flags
    if ai_backend == 'gemini':
        task_info['use_gemini'] = True
    if ai_backend == 'openai_echo':
        task_info['force_voice'] = voice or 'echo'
        task_info['include_summary'] = include_summary
    if parts_to_render is not None:
        task_info['parts_to_render'] = parts_to_render

    tasks[request_id] = task_info
    save_tasks(tasks)

    # enqueue payload
    payload = {
        "task_id": request_id,
        "urls": urls,
        "story_url": story_url,
        "merged_video_path": "",
        "final_video_path": final_video_path,
        "title_slug": title_slug,
        "key_file": "key.json",
        "title": title,
        "voice": voice,
        "type": task_type,
        "bg_choice": bg_choice,
        "refresh": refresh_audio,
        "part_duration": part_duration,
        "start_from_part": start_from_part,
        "output_dir": task_output_dir,
    }
    # include tiktok scheduling fields in payload (reuse parsed_tags from above)
    payload['is_upload_tiktok'] = bool(is_upload_tiktok)
    payload['upload_duration_hours'] = int(upload_duration_hours) if upload_duration_hours else None
    payload['tiktok_tags'] = parsed_tags
    payload['tiktok_cookies'] = str(cookies) if cookies else None
    if ai_backend == 'gemini':
        payload['use_gemini'] = True
    if ai_backend == 'openai_echo':
        payload['force_voice'] = voice or 'echo'
        payload['include_summary'] = include_summary
    if parts_to_render is not None:
        payload['parts_to_render'] = parts_to_render

    await enqueue_task(payload)

    send_discord_message(f"📨 Đã xếp task TikTok Large Video (unified) vào hàng chờ: {request_id}")
    resp = {"task_id": request_id}
    if parts_to_render is not None:
        resp['parts_to_render'] = parts_to_render
    return resp


@app.get('/api/bgaudio_list')
async def bgaudio_list():
    """Return list of background audio files from discord-bot/bgaudio.

    Response: { ok: True, files: [ { name, rel_path, mtime, size }, ... ] }
    """
    try:
        base_dir = os.path.join(os.path.dirname(__file__), 'discord-bot', 'bgaudio')
        files = []
        if not os.path.exists(base_dir):
            return {"ok": True, "files": []}
        for fname in sorted(os.listdir(base_dir)):
            fpath = os.path.join(base_dir, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                st = os.stat(fpath)
                rel = os.path.relpath(fpath, start=os.getcwd()).replace('\\', '/')
                files.append({
                    "name": fname,
                    "rel_path": rel,
                    "mtime": int(st.st_mtime),
                    "size": int(st.st_size),
                })
            except Exception:
                # skip unreadable files
                continue
        return {"ok": True, "files": files}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


  
@app.post('/api/download-bgaudio')
async def download_bgaudio(
        media_url: str = Query(..., description='URL to download audio from (yt-dlp)'),
        filename: str | None = Query(None, description='Optional desired filename (without extension)'),
        keep_source: bool = Query(False, description='If True keep the original downloaded audio file (non-wav)')
    ):
        """Download audio via yt-dlp into `discord-bot/bgaudio`, convert to WAV, and return path.

        - `media_url`: URL supported by `yt-dlp` (YouTube, SoundCloud, etc.)
        - `filename`: optional desired output name (no extension). If omitted, title from metadata is used.
        - `keep_source`: if True the downloaded source audio file is kept alongside the final WAV.
        """
        try:
            dest_dir = os.path.join(os.path.dirname(__file__), 'discord-bot', 'bgaudio')
            os.makedirs(dest_dir, exist_ok=True)

            # Prepare yt-dlp options to save original audio to dest_dir
            try:
                import yt_dlp
            except Exception:
                return JSONResponse(status_code=500, content={"ok": False, "error": "yt-dlp python module not available"})

            outtmpl = os.path.join(dest_dir, '%(id)s.%(ext)s')
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': outtmpl,
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
            }

            def _download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(media_url, download=True)
                    # prepare_filename usually returns the actual file path
                    try:
                        downloaded = ydl.prepare_filename(info)
                    except Exception:
                        # fallback: try to build from id/ext
                        ext = info.get('ext') or info.get('requested_formats', [{}])[-1].get('ext', 'm4a')
                        downloaded = os.path.join(dest_dir, f"{info.get('id')}.{ext}")
                    return info, downloaded

            # Try download up to 3 times (yt-dlp can fail intermittently)
            download_attempts = 3
            last_download_err = None
            info = None
            downloaded_path = None
            for attempt in range(1, download_attempts + 1):
                try:
                    info, downloaded_path = await asyncio.to_thread(_download)
                    if downloaded_path and os.path.exists(downloaded_path):
                        break
                except Exception as e:
                    last_download_err = e
                    logger.warning('download-bgaudio attempt %d failed: %s', attempt, e)
                    await asyncio.sleep(1)

            if not downloaded_path or not os.path.exists(downloaded_path):
                msg = f"Failed to download media after {download_attempts} attempts"
                if last_download_err:
                    msg += f": {last_download_err}"
                logger.error(msg)
                return JSONResponse(status_code=500, content={"ok": False, "error": msg})

            # Construct base output name
            base_name = filename or (info.get('title') if info and info.get('title') else info.get('id') if info else None) or str(int(time.time()))
            safe_name = safe_filename(base_name)

            # Ensure unique filename
            def _unique_path(path):
                if not os.path.exists(path):
                    return path
                base, ext = os.path.splitext(path)
                i = 1
                while True:
                    cand = f"{base}_{i}{ext}"
                    if not os.path.exists(cand):
                        return cand
                    i += 1

            out_wav = _unique_path(os.path.join(dest_dir, f"{safe_name}.wav"))

            # Try convert to WAV up to 3 times; on persistent failure, fall back to MP3
            conv_attempts = 3
            wav_ok = False
            last_conv_err = None
            for attempt in range(1, conv_attempts + 1):
                try:
                    cmd = ['ffmpeg', '-y', '-i', downloaded_path, '-ar', '48000', '-ac', '2', out_wav]
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode == 0 and os.path.exists(out_wav):
                        wav_ok = True
                        break
                    last_conv_err = result.stderr
                    logger.warning('ffmpeg wav conversion attempt %d failed: %s', attempt, result.stderr)
                    # small backoff
                    asyncio.sleep(0.5)
                except Exception as e:
                    last_conv_err = str(e)
                    logger.warning('ffmpeg wav conversion exception on attempt %d: %s', attempt, e)
                    await asyncio.sleep(0.5)

            fallback_to_mp3 = False
            out_mp3 = None
            if not wav_ok:
                # Try to produce MP3 as fallback
                fallback_to_mp3 = True
                out_mp3 = _unique_path(os.path.join(dest_dir, f"{safe_name}.mp3"))
                try:
                    cmd2 = ['ffmpeg', '-y', '-i', downloaded_path, '-ar', '48000', '-ac', '2', '-b:a', '192k', out_mp3]
                    r2 = subprocess.run(cmd2, capture_output=True, text=True)
                    if r2.returncode != 0 or not os.path.exists(out_mp3):
                        logger.error('ffmpeg mp3 fallback failed: %s', r2.stderr)
                        return JSONResponse(status_code=500, content={"ok": False, "error": 'Both WAV and MP3 conversion failed', 'wav_err': last_conv_err, 'mp3_err': r2.stderr})
                except Exception as e:
                    logger.exception('MP3 fallback conversion exception: %s', e)
                    return JSONResponse(status_code=500, content={"ok": False, "error": f'MP3 conversion exception: {e}'})

            # Cleanup source if requested
            if not keep_source:
                try:
                    if os.path.exists(downloaded_path):
                        os.remove(downloaded_path)
                except Exception:
                    pass

            if not fallback_to_mp3:
                return JSONResponse(status_code=200, content={
                    "ok": True,
                    "wav_path": out_wav,
                    "wav_rel": to_project_relative_posix(out_wav),
                    "title": info.get('title') if info else None,
                    "id": info.get('id') if info else None,
                    "fallback": False
                })
            else:
                return JSONResponse(status_code=200, content={
                    "ok": True,
                    "mp3_path": out_mp3,
                    "mp3_rel": to_project_relative_posix(out_mp3),
                    "title": info.get('title') if info else None,
                    "id": info.get('id') if info else None,
                    "fallback": True,
                    "fallback_format": "mp3"
                })

        except Exception as e:
            logger.exception('download-bgaudio failed: %s', e)
            return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

@app.post('/youtube_reupload')
async def youtube_reupload(
    file_path: str = Query(..., description='Local path to the video file to upload'),
    title: str | None = Query(None, description='Optional title for the video'),
    description: str = Query('', description='Video description'),
    category: str | None = Query(None, description='Category name or id'),
    privacy: str = Query('public', description='privacy status: public|unlisted|private'),
    tags: str | None = Query(None, description='Comma-separated tags'),
    run_in_background: bool = Query(False, description='If true, start upload in background and return immediately')
):
    """Re-upload a previously rendered video file to YouTube.

    Provide `file_path` (absolute or relative). Optional `title`, `description`, `category`, `privacy`, `tags`.
    If `run_in_background` is true the upload will be scheduled on a thread and this endpoint returns immediately.
    """
    out_path = os.path.join(OUTPUT_DIR,file_path)
    if not os.path.exists(out_path):
        return JSONResponse(status_code=400, content={"error": "file not found", "file": out_path})

    tag_list = [t.strip() for t in tags.split(',')] if tags else None
    title_use = title or os.path.basename(file_path)

    def _upload():
        try:
            out_path = os.path.join(OUTPUT_DIR,file_path)
            upload_video(
                file_path=out_path,
                title=title_use,
                description=description,
                category="Entertainment",  # bạn có thể dùng "Music", "People & Blogs", hoặc ID (vd: "10")
                privacy="public",
                tags=["truyenaudio", "truyenhay", "giaitri"]
            )
        except Exception as e:
            send_discord_message(f"❌ Upload failed for {file_path}: {e}")
            raise

    loop = asyncio.get_event_loop()
    try:
        # no dedicated task entry created here; synthesize a request id for tracking
        tmp_tid = f"youtube_reupload-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
        tasks_local = load_tasks()
        tasks_local.setdefault(tmp_tid, {"task_id": tmp_tid, "status": "pending", "created_at": time.time(), "title": title_use})
        tasks_local[tmp_tid]['status'] = 'running'
        save_tasks(tasks_local)
    except Exception:
        tmp_tid = None

    tracked = create_tracked_task(tmp_tid or file_path, asyncio.to_thread(_upload))
    if run_in_background:
        return JSONResponse(status_code=202, content={"started": True, "file": file_path})

    try:
        await tracked
        return JSONResponse(status_code=200, content={"success": True, "file": file_path})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/generate_story_to_video")
async def generate_story_to_video(
    genre: str = Query(..., description="Thể loại truyện: 'horror' (kinh dị), 'face_slap' (vả mặt), hoặc 'random_mix' (ngẫu nhiên)"),
    video_urls: str | None = Query(None, description="URL video background (có thể nhiều, phân cách bằng dấu phẩy). Nếu để trống sẽ lấy random từ cache video"),
    title: str = Query("", description="Tiêu đề video (tùy chọn)"),
    model: str = Query("gpt-4o-mini", description="Model OpenAI: gpt-4o-mini, gpt-4o, gpt-4-turbo"),
    voice: str = Query("Đọc bằng giọng hơi robotic, nhịp điệu nhanh giống giọng review phim.", description="Voice instruction or name"),
    bg_choice: str = Query(None, description="Tên file nhạc nền (optional)"),
    part_duration: int = Query(3600, description="Thời lượng tối đa mỗi part video (giây), mặc định 3600s = 1h"),
    
    # Tham số cho Horror story
    horror_theme: str = Query(None, description="Chủ đề kinh dị cụ thể (optional, để trống sẽ chọn ngẫu nhiên)"),
    horror_setting: str = Query(None, description="Bối cảnh kinh dị cụ thể (optional)"),
    
    # Tham số cho Face Slap story
    face_slap_theme: str = Query(None, description="Chủ đề vả mặt cụ thể (optional)"),
    face_slap_role: str = Query(None, description="Vai giả nghèo cụ thể (optional)"),
    face_slap_setting: str = Query(None, description="Bối cảnh vả mặt cụ thể (optional)"),
    
    # Tham số cho Random Mix story
    random_main_genre: str = Query(None, description="Thể loại chính cho random mix (optional)"),
    random_sub_genre: str = Query(None, description="Thể loại phụ cho random mix (optional)"),
    random_character: str = Query(None, description="Nhân vật cho random mix (optional)"),
    random_setting: str = Query(None, description="Bối cảnh cho random mix (optional)"),
    random_plot_motif: str = Query(None, description="Motif cốt truyện cho random mix (optional)"),
    
    # AI Backend selection
    ai_backend: str = Query("gemini", description="AI backend cho TTS: 'gemini' (default) hoặc 'openai'"),
):
    """
    🎬 ENDPOINT FULL PIPELINE: TRUYỆN → AUDIO → VIDEO
    
    Quy trình hoàn chỉnh:
    1. Tạo truyện bằng story_generator (3 thể loại)
    2. Tạo audio từ văn bản truyện (OpenAI TTS)
    3. Xử lý audio (tăng tốc + nhạc nền)
    4. Chia audio thành các part cân bằng
    5. Render video từ audio + background videos
    6. Upload lên Google Drive
    
    Thể loại truyện:
    - 'horror': Kinh dị - Huyền bí - Linh dị Việt Nam
    - 'face_slap': Vả mặt - Giả nghèo phản đòn
    - 'random_mix': Kết hợp ngẫu nhiên nhiều thể loại
    
    Returns:
        task_id để theo dõi tiến trình
    """
    from story_generator import StoryGenerator
    
    cleanup_old_tasks(days=30)
    
    # Validate genre
    valid_genres = ['horror', 'face_slap', 'random_mix']
    if genre.lower() not in valid_genres:
        raise HTTPException(
            status_code=400, 
            detail=f"Genre không hợp lệ. Chọn một trong: {', '.join(valid_genres)}"
        )
    
    request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    
    # Parse video URLs (optional). Nếu không truyền, lấy random từ video cache
    if video_urls and video_urls.strip():
        urls = [u.strip() for u in video_urls.split(",") if u.strip()]
    else:
        # lấy các file .mp4 trong VIDEO_CACHE_DIR
        try:
            cached_files = [os.path.join(VIDEO_CACHE_DIR, f) for f in os.listdir(VIDEO_CACHE_DIR) if f.lower().endswith('.mp4')]
        except Exception:
            cached_files = []

        if not cached_files:
            raise HTTPException(status_code=400, detail="Không có video trong cache. Vui lòng truyền ít nhất 1 video_url hoặc thêm video vào cache.")

        # chọn tối đa 3 video ngẫu nhiên từ cache để làm background
        pick_count = min(3, len(cached_files))
        urls = random.sample(cached_files, pick_count)
    
    # Tạo task metadata
    tasks = load_tasks()
    task_info = {
        "task_id": request_id,
        "status": "pending",
        "progress": 0,
        "phase": "initializing",
        "video_path": "",
        "story_path": "",
        "audio_path": "",
        "video_file": [],
        "title": title,
        "genre": genre,
        "model": model,
        "voice": voice,
        "bg_choice": bg_choice,
        "temp_videos": [],
        "request_urls": urls,
        "created_at": time.time(),
        "type": 7,  # Type 7 = Story to Video Pipeline
        "part_duration": part_duration,
        "total_parts": 0,
        "current_part": 0
    }
    tasks[request_id] = task_info
    save_tasks(tasks)
    
    # Tạo thông tin chi tiết cho từng thể loại
    genre_params = {
        "genre": genre.lower(),
        "model": model,
        "ai_backend": ai_backend.lower() if ai_backend else "gemini",
        "horror_theme": horror_theme,
        "horror_setting": horror_setting,
        "face_slap_theme": face_slap_theme,
        "face_slap_role": face_slap_role,
        "face_slap_setting": face_slap_setting,
        "random_main_genre": random_main_genre,
        "random_sub_genre": random_sub_genre,
        "random_character": random_character,
        "random_setting": random_setting,
        "random_plot_motif": random_plot_motif,
    }
    
    # Đẩy vào queue
    await enqueue_task({
        "task_id": request_id,
        "task_type": "story_to_video",
        "urls": urls,
        "title": title,
        "voice": voice,
        "bg_choice": bg_choice,
        "part_duration": part_duration,
        "genre_params": genre_params,
    })
    
    send_discord_message(f"📨 Đã xếp task Story→Video ({genre.upper()}) vào hàng chờ: {request_id}")
    return {"task_id": request_id, "status": "queued", "genre": genre}


@app.get("/stories_list")
async def stories_list():
    """Return a list of generated story files from the `stories/` folder.

    Returns JSON: {"stories":[{"name":"file.txt","path":"/abs/path/to/file.txt"}, ...]}
    """
    stories_dir = os.path.join(BASE_DIR, "stories")
    items = []
    try:
        if os.path.isdir(stories_dir):
            for fn in sorted(os.listdir(stories_dir), reverse=True):
                full = os.path.join(stories_dir, fn)
                if os.path.isfile(full) and fn.lower().endswith(('.txt', '.md')):
                    items.append({"name": fn, "path": full})
    except Exception as e:
        logger.exception("Error listing stories: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    return {"stories": items}


@app.get("/story_content")
async def story_content(story_path: str = Query(..., description="Path or basename of the story file inside stories/")):
    """Return the text content of a story split into Discord-sized chunks (safe for messages).

    Query param `story_path` may be either a basename (e.g. `20231101_story.txt`) or an absolute path.
    Response: {"title":..., "path":..., "chunks":[...]} where each chunk <= 1900 characters.
    """
    stories_dir = os.path.join(BASE_DIR, "stories")

    # Resolve path
    if os.path.isabs(story_path):
        path = story_path
    else:
        path = os.path.join(stories_dir, story_path)

    if not os.path.exists(path) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Story not found: {story_path}")

    try:
        # Prefer companion content-only file if present (created by story_generator)
        content_only_path = os.path.splitext(path)[0] + "_content.txt"
        if os.path.exists(content_only_path):
            try:
                with open(content_only_path, "r", encoding="utf-8") as f:
                    text = f.read().strip()
            except Exception:
                # fallback to full file if companion fails
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read().strip()
        else:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
    except Exception as e:
        logger.exception("Error reading story file %s: %s", path, e)
        raise HTTPException(status_code=500, detail=str(e))

    # Try to extract an explicit AI-provided title from the full file (if present)
    title_use = None
    try:
        with open(path, "r", encoding="utf-8") as f_full:
            full_text = f_full.read()
            m = re.search(r"^(?:TIÊU\s*ĐỀ|TIEU\s*DE|TITLE)\s*:\s*(.+)$", full_text, flags=re.I | re.M)
            if m:
                title_use = m.group(1).strip()
    except Exception:
        title_use = None

    max_len = 1900
    chunks = []
    remaining = text
    while remaining:
        part = remaining[:max_len]
        if len(part) == max_len and len(remaining) > max_len:
            # try to cut at a sensible boundary
            sep = max(part.rfind('\n'), part.rfind(' '), part.rfind('.'))
            if sep and sep > max_len // 2:
                part = part[:sep+1]
        chunks.append(part.strip())
        remaining = remaining[len(part):]

    return {"title": os.path.basename(path), "path": path, "chunks": chunks}


@app.post("/create_video_from_story")
async def create_video_from_story(
    story_path: str = Query(..., description="Basename or absolute path to story file in stories/"),
    video_urls: str | None = Query(None, description="Optional comma-separated background video URLs/paths"),
    title: str = Query("", description="Optional override title"),
    voice: str = Query("Đọc bằng giọng hơi robotic, nhịp điệu nhanh giống giọng review phim.", description="Voice instruction or name"),
    bg_choice: str | None = Query(None, description="Optional background WAV filename"),
    part_duration: int = Query(3600, description="Part duration in seconds"),
    start_from_part: int = Query(1, description="Start rendering from this part (1-based)"),
    ai_backend: str = Query("gemini", description="AI backend to use for TTS: 'gemini' or 'openai'"),
):
    """Create a background task that builds audio + video parts from a local story file.

    Returns immediately with a `task_id`. The actual work runs in background and updates `tasks.json`.
    """
    stories_dir = os.path.join(BASE_DIR, "stories")
    if os.path.isabs(story_path):
        path = story_path
    else:
        path = os.path.join(stories_dir, story_path)

    if not os.path.exists(path) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Story not found: {story_path}")

    # prepare video urls list
    # If `video_urls` is provided use it; otherwise pick random cached videos
    # from VIDEO_CACHE_DIR (up to 3), same behavior as other flows.
    if video_urls and video_urls.strip():
        urls = [u.strip() for u in video_urls.split(",") if u.strip()]
    else:
        try:
            cached_files = [os.path.join(VIDEO_CACHE_DIR, f) for f in os.listdir(VIDEO_CACHE_DIR) if f.lower().endswith('.mp4')]
        except Exception:
            cached_files = []

        if not cached_files:
            raise HTTPException(status_code=400, detail="No background videos available in cache; provide `video_urls`")

        pick_count = min(3, len(cached_files))
        urls = random.sample(cached_files, pick_count)

    # Read story file early so we can extract a title if Gemini saved one
    try:
        with open(path, "r", encoding="utf-8") as f:
            story_text = f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot read story file: {e}")

    # Try to extract an AI-provided title from the file (e.g. a line like 'TIÊU ĐỀ: <title>')
    import re
    title_from_file = None
    m = re.search(r"^(?:TIÊU\s*ĐỀ|TIEU\s*DE|TITLE)\s*:\s*(.+)$", story_text, flags=re.I | re.M)
    if m:
        title_from_file = m.group(1).strip()

    # Create task metadata
    request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    # Preference order: explicit `title` query param -> extracted title from file -> filename base
    title_use = title or title_from_file or os.path.splitext(os.path.basename(path))[0]
    title_slug = safe_filename(title_use or os.path.splitext(os.path.basename(path))[0], max_length=50)
    final_video_path = os.path.join(OUTPUT_DIR, f"{title_slug}_{voice}_video.mp4") if voice else os.path.join(OUTPUT_DIR, f"{title_slug}_video.mp4")

    tasks = load_tasks()
    task_info = {
        "task_id": request_id,
        "status": "pending",
        "progress": 0,
        "video_path": final_video_path,
        "video_file": [],
        "ai_title": title_use,
        "title": title_use,
        "voice": voice,
        "bg_choice": bg_choice,
        "temp_videos": [],
        "request_urls": urls + [path],
        "created_at": time.time(),
        "type": 4,  # treat as TikTok Large flow
        "part_duration": part_duration,
        "start_from_part": start_from_part,
        "ai_backend": ai_backend,
    }
    tasks[request_id] = task_info
    save_tasks(tasks)

    loop = asyncio.get_event_loop()

    async def _background_job():
        try:
            # Read story content. Prefer companion *_content.txt (content-only) if present
            content_only_path = os.path.splitext(path)[0] + "_content.txt"
            try:
                if os.path.exists(content_only_path):
                    with open(content_only_path, "r", encoding="utf-8") as f:
                        story_content = f.read().strip()
                else:
                    with open(path, "r", encoding="utf-8") as f:
                        story_content = f.read().strip()
            except Exception as e:
                raise RuntimeError(f"Cannot read story content: {e}")

            # Save story path to task
            t = load_tasks().get(request_id, {})
            t['story_path'] = path
            t['progress'] = 5
            tasks_local = load_tasks(); tasks_local[request_id] = t; save_tasks(tasks_local)

            # 1) Determine TTS backend and voice mapping based on incoming `voice` parameter.
            # Priority: explicit `voice` values control both which TTS backend and which
            # audio-preparation function to use. If `voice` is not one of the special
            # tokens, fall back to the `ai_backend` parameter.
            selected_voice = (voice or "").strip().lower()
            use_gemini = None
            gemini_voice = None
            # Default prepare callable; may be overridden below
            prepare_audio_callable_local = prepare_audio_for_video

            if selected_voice == "gman":
                # Gemini male mapping
                use_gemini = True
                gemini_voice = "vi-VN-Standard-D"
                prepare_audio_callable_local = prepare_audio_for_video_gemini_male
            elif selected_voice == "gfemale":
                # Gemini female mapping
                use_gemini = True
                gemini_voice = "vi-VN-Standard-C"
                prepare_audio_callable_local = prepare_audio_for_video_gemini
            elif selected_voice in ("echo", "nova"):
                # OpenAI voices
                use_gemini = False
                prepare_audio_callable_local = prepare_audio_for_video
            else:
                # Not an explicit voice token — fall back to ai_backend param
                backend = (ai_backend or "gemini").strip().lower()
                if backend == 'openai':
                    use_gemini = False
                    prepare_audio_callable_local = prepare_audio_for_video
                else:
                    use_gemini = True
                    # default Gemini processing
                    prepare_audio_callable_local = prepare_audio_for_video_gemini

            # Generate audio using chosen backend. For Gemini we may pass an explicit
            # voice identifier (`gemini_voice`) when available.
            if use_gemini:
                if gemini_voice:
                    audio_file = await loop.run_in_executor(executor, generate_audio_Gemini, story_content, title_slug, gemini_voice)
                else:
                    audio_file = await loop.run_in_executor(executor, generate_audio_Gemini, story_content, title_slug)
            else:
                # OpenAI TTS supports passing `voice` (human-friendly instruction/name)
                audio_file = await loop.run_in_executor(executor, generate_audio, story_content, title_slug, voice)

            if not audio_file or not os.path.exists(audio_file):
                raise RuntimeError("Không tạo được file audio từ truyện")

            t = load_tasks().get(request_id, {})
            t['audio_path'] = audio_file
            t['progress'] = 30
            tasks_local = load_tasks(); tasks_local[request_id] = t; save_tasks(tasks_local)

            # 2) Prepare/process audio for video (mix bg + filters)
            # Use the prepare callable chosen above (based on `voice` mapping or backend fallback).
            processed_audio = await loop.run_in_executor(executor, prepare_audio_callable_local, audio_file, bg_choice, 6.0)

            if not processed_audio or not os.path.exists(processed_audio):
                raise RuntimeError("Không xử lý được audio")

            t = load_tasks().get(request_id, {})
            t['processed_audio_path'] = processed_audio
            t['progress'] = 45
            tasks_local = load_tasks(); tasks_local[request_id] = t; save_tasks(tasks_local)

            # 3) Split the processed FLAC into parts for rendering
            # Always split the final processed audio (which includes bg music and filters)
            # into parts of at most `part_duration` seconds. After rendering we'll remove
            # these split parts and the processed FLAC, but keep the original per-TTS WAV files.
            audio_parts = await loop.run_in_executor(executor, split_audio_by_duration, processed_audio, part_duration, OUTPUT_DIR)

            total_parts = len(audio_parts)
            if total_parts == 0:
                raise RuntimeError("Không có phần audio để render")

            t = load_tasks().get(request_id, {})
            t['total_parts'] = total_parts
            t['progress'] = 60
            tasks_local = load_tasks(); tasks_local[request_id] = t; save_tasks(tasks_local)

            # 4) Download background videos (if none provided, try cache)
            video_files = []
            if urls:
                for i, url in enumerate(urls):
                    try:
                        cached = None
                        if os.path.exists(url):
                            cached = url
                        else:
                            cached = await loop.run_in_executor(executor, download_video_url, url, f"{title_slug}_bg_{i+1}.mp4", 3, 2, None, False)
                        if cached and os.path.exists(cached):
                            video_files.append(cached)
                    except Exception:
                        continue

            if not video_files:
                # fallback: use random cache in VIDEO_CACHE_DIR
                try:
                    cached_files = [os.path.join(VIDEO_CACHE_DIR, f) for f in os.listdir(VIDEO_CACHE_DIR) if f.lower().endswith('.mp4')]
                    if cached_files:
                        video_files = random.sample(cached_files, min(3, len(cached_files)))
                except Exception:
                    video_files = []

            if not video_files:
                raise RuntimeError("Không có video background để render")

            # 5) Render each part
            output_parts = []
            video_links = []
            # unique suffix so final part filenames are new per render
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            suffix = f"_{request_id}_{ts}"
            for i in range(start_from_part - 1, total_parts):
                part_num = i + 1
                audio_part = audio_parts[i]
                output_part = os.path.join(OUTPUT_DIR, f"{title_slug}_part{part_num}{suffix}.mp4")

                rendered_part = await loop.run_in_executor(
                    executor,
                    render_tiktok_video_from_audio_part,
                    video_files,
                    audio_part,
                    output_part,
                    title_use,
                    part_num,
                    total_parts,
                    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
                )
                output_parts.append(rendered_part)

                # Upload best-effort
                try:
                    uploaded = await loop.run_in_executor(executor, uploadOneDrive, rendered_part, title_use)
                    link = uploaded.get('downloadLink') or uploaded.get('webViewLink')
                    video_links.append(link or rendered_part)
                except Exception:
                    video_links.append(rendered_part)

                t = load_tasks().get(request_id, {})
                t['progress'] = 60 + int((part_num / total_parts) * 35)
                t.setdefault('video_file', [])
                t['video_file'] = video_links
                t.setdefault('output_parts', [])
                t['output_parts'] = output_parts
                tasks_local = load_tasks(); tasks_local[request_id] = t; save_tasks(tasks_local)

            # 6) Finalize
            t = load_tasks().get(request_id, {})
            t['status'] = 'completed'
            t['progress'] = 100
            t['video_file'] = video_links
            t['output_parts'] = output_parts
            if output_parts:
                t['video_path'] = output_parts[0]
            tasks_local = load_tasks(); tasks_local[request_id] = t; save_tasks(tasks_local)
            # Cleanup: remove the split FLAC parts and the processed combined FLAC
            # but keep the original per-TTS WAV files (they live in OUTPUT_DIR and
            # are intentionally preserved).
            try:
                # remove each generated split part
                for p in audio_parts:
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
                # remove the processed combined audio file
                try:
                    if os.path.exists(processed_audio):
                        os.remove(processed_audio)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
            except Exception as e:
                _report_and_ignore(e, "ignored")
        except Exception as e:
            logger.exception("Background create_video_from_story failed: %s", e)
            t = load_tasks().get(request_id, {})
            t['status'] = 'error'
            t['error'] = str(e)
            t['progress'] = 0
            tasks_local = load_tasks(); tasks_local[request_id] = t; save_tasks(tasks_local)

    # launch background job
    asyncio.create_task(_background_job())

    send_discord_message(f"📨 Đã xếp task tạo video từ story file vào hàng chờ: {request_id}")
    return {"task_id": request_id}


def burn_subtitles_ass_tiktok(input_video: str, srt_path: str, output_path: str | None = None) -> str:
    """Convert SRT to ASS (TikTok-friendly defaults) and burn onto a 1080x1920 video.
    Returns the output mp4 path.
    """
    if output_path is None:
        base = os.path.splitext(input_video)[0]
        output_path = base + ".tiktok.mp4"

    try:
        from convert_srt_to_ass import convert as convert_srt_to_ass_convert
    except Exception:
        convert_srt_to_ass_convert = None

    ass_path = srt_path.replace('.srt', '.ass') if srt_path.lower().endswith('.srt') else srt_path + '.ass'
    try:
        if convert_srt_to_ass_convert:
            convert_srt_to_ass_convert(srt_path, ass_path, 30, 11, "Noto Sans", 20, 150)
        else:
            try:
                subprocess.run(["ffmpeg", "-y", "-i", srt_path, ass_path], check=True)
            except Exception:
                ass_path = srt_path

        subtitle_input_escaped = ass_path.replace("'", "\\'")
        sub_filter = f"subtitles='{subtitle_input_escaped}'"
        cmd = [
            "ffmpeg", "-y",
            "-i", input_video,
            "-vf", "scale=w=1080:h=-2:flags=lanczos,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1," + sub_filter,
            "-c:a", "copy",
            output_path
        ]
        subprocess.run(cmd, check=True)
        return output_path
    except Exception:
        try:
            shutil.copy2(input_video, output_path)
        except Exception as e:
            _report_and_ignore(e, "ignored")
        return output_path


def _ffmpeg_sub_filter(ass_path: str) -> str:
    """Build an ffmpeg-compatible subtitles filter string for the given ASS/SRT path.

    This handles Windows drive letters and escapes single quotes for ffmpeg filter usage.
    """
    try:
        from pathlib import Path
        p = Path(ass_path).resolve().as_posix()
        p = p.replace(":", r"\:")
        return f"subtitles=filename='{p}'"
    except Exception:
        subtitle_input_escaped = ass_path.replace("'", "\\'").replace(":", r"\:")
        return f"subtitles='{subtitle_input_escaped}'"


def process_single_video_pipeline(
    video_path: str,
    output_dir: str,
    base_name: str,
    *,
    add_narration: bool = True,
    with_subtitles: bool = True,
    narration_voice: str = 'vi-VN-Standard-C',
    narration_replace_audio: bool = False,
    narration_volume_db: float = 8.0,
    narration_rate_dynamic: int = 0,
    narration_apply_fx: int = 1,
    voice_fx_func = None,
    progress_callback: callable = None,
    skip_transcribe: bool = False,
    skip_translate: bool = False,
    skip_narration: bool = False,
    skip_render: bool = False
) -> dict:
    """Helper function to process a single video through the full pipeline.
    
    Pipeline steps:
    1. Transcribe video to SRT (if not skip_transcribe)
    2. Translate SRT to Vietnamese (if not skip_translate)
    3. Create narration from Vietnamese SRT (if add_narration and not skip_narration)
    4. Render final video with subtitles/narration (if not skip_render)
    
    Args:
        video_path: Path to input video file
        output_dir: Directory for output files
        base_name: Base name for output files (without extension)
        add_narration: Whether to create and add narration
        with_subtitles: Whether to burn subtitles into video
        narration_voice: Google TTS voice name
        narration_replace_audio: Replace original audio with narration
        narration_volume_db: Narration volume (dB)
        narration_rate_dynamic: Use dynamic speaking rate (0 or 1)
        narration_apply_fx: Apply audio effects to narration (0 or 1)
        progress_callback: Optional callback function(step_name: str, progress: int)
        skip_transcribe: Skip transcription if raw SRT already exists
        skip_translate: Skip translation if Vietnamese SRT already exists
        skip_narration: Skip narration creation if FLAC already exists
        skip_render: Skip rendering if final video already exists
    
    Returns:
        dict with keys:
            - raw_srt: Path to raw/Chinese SRT
            - vi_srt: Path to Vietnamese SRT
            - nar_flac: Path to narration FLAC (if add_narration)
            - ass_path: Path to ASS file (if with_subtitles)
            - final_video: Path to rendered final video
            - reused: dict indicating which artifacts were reused
    """
    import subprocess, shutil
    
    def _progress(step: str, pct: int):
        if progress_callback:
            try:
                progress_callback(step, pct)
            except Exception:
                pass
    
    # Define artifact paths
    raw_srt = os.path.join(output_dir, f"{base_name}.srt")
    vi_srt = os.path.join(output_dir, f"{base_name}.vi.srt")
    nar_flac = os.path.join(output_dir, f"{base_name}.nar.flac")
    ass_path = os.path.join(output_dir, f"{base_name}.vi.ass")
    final_video = os.path.join(output_dir, f"{base_name}_final.mp4")
    
    reused = {}
    
    # Step 1: Transcribe
    if skip_transcribe or os.path.exists(raw_srt):
        if os.path.exists(raw_srt):
            send_discord_message(f"♻️ Phụ đề gốc đã tồn tại: {raw_srt}")
            reused['raw_srt'] = True
        srt_path = raw_srt
    else:
        send_discord_message(f"🎤 Bắt đầu tạo phụ đề (transcribe)...")
        _progress('transcribe', 30)
        
        import convert_stt
        srt_path = convert_stt.transcribe(video_path)
        if not srt_path or not os.path.exists(srt_path):
            raise RuntimeError("Transcription failed")
        
        # Move to output directory with proper name
        if srt_path != raw_srt:
            shutil.move(srt_path, raw_srt)
            srt_path = raw_srt
        send_discord_message(f"✅ Đã tạo phụ đề: {raw_srt}")
    
    # Step 2: Translate
    if skip_translate or os.path.exists(vi_srt):
        if os.path.exists(vi_srt):
            send_discord_message(f"♻️ Phụ đề tiếng Việt đã tồn tại: {vi_srt}")
            reused['vi_srt'] = True
    else:
        send_discord_message(f"🌐 Bắt đầu dịch phụ đề sang tiếng Việt...")
        _progress('translate', 50)
        
        try:
            from srt_translate import translate_srt_file
            translate_srt_file(raw_srt, vi_srt, src_lang='zh-CN', dest_lang='vi', use_gemini=False)
            if not os.path.exists(vi_srt):
                raise RuntimeError("Translation failed")
            send_discord_message(f"✅ Đã dịch phụ đề: {vi_srt}")
        except Exception as e:
            send_discord_message(f"⚠️ Lỗi dịch phụ đề, sử dụng bản gốc: {e}")
            vi_srt = raw_srt
    
    # Step 3: Create narration if requested
    nar_audio_path = None
    if add_narration:
        if skip_narration or os.path.exists(nar_flac):
            if os.path.exists(nar_flac):
                send_discord_message(f"♻️ Thuyết minh đã tồn tại: {nar_flac}")
                reused['nar_flac'] = True
            nar_audio_path = nar_flac
        else:
            send_discord_message(f"🎙️ Bắt đầu tạo thuyết minh...")
            _progress('narration', 60)
            
            # Generate narration audio
            tts_pieces_dir = os.path.join(output_dir, "tts_pieces")
            try:
                os.makedirs(tts_pieces_dir, exist_ok=True)
            except Exception:
                tts_pieces_dir = output_dir
            
            import narration_from_srt
            nar_audio, _meta = narration_from_srt.build_narration_schedule(
                vi_srt, nar_flac,
                voice_name=narration_voice,
                speaking_rate=1.0,
                lead=0.0,
                meta_out=os.path.join(output_dir, f"{base_name}.schedule.json"),
                trim=False,
                rate_mode=narration_rate_dynamic,
                apply_fx=bool(narration_apply_fx),
                tmp_subdir=tts_pieces_dir,
                voice_fx_func=voice_fx_func
            )
            nar_audio_path = nar_flac
            send_discord_message(f"✅ Đã tạo thuyết minh: {nar_flac}")
    
    # Step 4: Prepare ASS file if subtitles requested
    ass_file = None
    if with_subtitles:
        if os.path.exists(ass_path):
            send_discord_message(f"♻️ ASS đã tồn tại: {ass_path}")
            reused['ass_path'] = True
            ass_file = ass_path
        else:
            try:
                from convert_srt_to_ass import convert as convert_srt_to_ass_convert
                convert_srt_to_ass_convert(vi_srt, ass_path, 30, 11, "Noto Sans", 20, 150)
                ass_file = ass_path
            except Exception:
                # Fallback to ffmpeg conversion
                subprocess.run(["ffmpeg", "-y", "-i", vi_srt, ass_path], check=True)
                ass_file = ass_path
    
    # Step 5: Render final video
    if skip_render or os.path.exists(final_video):
        if os.path.exists(final_video):
            send_discord_message(f"♻️ Video final đã tồn tại: {final_video}")
            reused['final_video'] = True
    else:
        send_discord_message(f"🎬 Bắt đầu render video...")
        _progress('render', 80)
        
        if add_narration and nar_audio_path:
            # Render with narration
            try:
                burn_and_mix_narration(
                    video_path, ass_file, nar_audio_path, final_video,
                    replace_audio=narration_replace_audio,
                    narration_volume_db=narration_volume_db,
                    shift_sec=0.7,
                    with_subtitles=with_subtitles
                )
            except Exception:
                # Fallback to basic mix
                import narration_from_srt
                narration_from_srt.mix_narration_into_video(
                    video_path, nar_audio_path, final_video,
                    narration_volume_db=narration_volume_db if narration_volume_db is not None else 8.0,
                    replace_audio=narration_replace_audio,
                    extend_video=True,
                    shift_sec=0.7,
                    video_volume_db=-3.0
                )
        else:
            # No narration: burn subtitles or copy
            if with_subtitles and ass_file:
                try:
                    from pathlib import Path
                    p = Path(ass_file).resolve().as_posix()
                    p = p.replace(":", r"\:")
                    sub_filter = f"subtitles=filename='{p}'"
                except Exception:
                    subtitle_input_escaped = ass_file.replace("'", "\\'").replace(":", r"\:")
                    sub_filter = f"subtitles='{subtitle_input_escaped}'"
                
                cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", sub_filter]
                cmd.extend(_preferred_video_encode_args())
                cmd.extend(["-c:a", "copy", final_video])
                subprocess.run(cmd, check=True)
            else:
                # No subtitles, no narration: just copy
                shutil.copy2(video_path, final_video)
        
        send_discord_message(f"✅ Đã render video: {final_video}")
    
    return {
        'raw_srt': raw_srt,
        'vi_srt': vi_srt,
        'nar_flac': nar_flac if add_narration else None,
        'ass_path': ass_file,
        'final_video': final_video,
        'reused': reused
    }


def burn_and_mix_narration(src_video: str, ass_path: str | None, narr_file: str, out_path: str, *, replace_audio: bool = False, narration_volume_db: float | None = None, shift_sec: float = 0.7, with_subtitles: bool = True) -> bool:
    """Attempt a single-pass ffmpeg that optionally burns ASS subtitles and mixes a narration FLAC.
    Returns True on success, False on failure (on failure it will attempt the old Python mixer as a fallback).
    """
    try:
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
    except Exception as e:
        _report_and_ignore(e, "ignored")
    try:
        src_for_ff = src_video
        narr_file_local = narr_file
        narr_vol_lin = 10 ** (float(narration_volume_db) / 20.0) if narration_volume_db is not None else 10 ** (6.0 / 20.0)
        shift_ms = max(0, int(shift_sec * 1000))

        try:
            vid_dur = get_media_info(src_for_ff)[2] if os.path.exists(src_for_ff) else 0.0
        except Exception:
            vid_dur = 0.0
        try:
            nar_dur = get_media_info(narr_file_local)[2] if os.path.exists(narr_file_local) else 0.0
        except Exception:
            nar_dur = 0.0

        pad = max(0.0, nar_dur - (vid_dur or 0.0))
        tpad = f"tpad=stop_mode=clone:stop_duration={pad}" if (pad > 0.01 and not replace_audio) else ""

        try:
            sub_filter = _ffmpeg_sub_filter(ass_path) if with_subtitles and ass_path and os.path.exists(ass_path) else None
        except Exception:
            sub_filter = None

        if sub_filter:
            vchain = f"[0:v]{tpad},{sub_filter}[v]" if tpad else f"[0:v]{sub_filter}[v]"
        else:
            vchain = f"[0:v]{tpad},setpts=PTS[v]" if tpad else "[0:v]setpts=PTS[v]"

        nar_chain = f"[1:a]adelay={shift_ms}|{shift_ms},volume={narr_vol_lin}[nar]"

        if replace_audio:
            filt = ";".join([vchain, nar_chain])
            cmd = ["ffmpeg", "-y", "-i", src_for_ff, "-i", narr_file_local, "-filter_complex", filt, "-map", "[v]", "-map", "[nar]"]
            cmd.extend(_preferred_video_encode_args())
            cmd.extend(_preferred_audio_encode_args())
            cmd.append(out_path)
        else:
            vid_bg = f"[0:a]volume={10 ** ((-9.0) / 20):.6f}[bg]"
            amix = f"[bg][nar]amix=inputs=2:duration=longest:normalize=0[a]"
            filt = ";".join([vchain, vid_bg, nar_chain, amix])
            cmd = ["ffmpeg", "-y", "-i", src_for_ff, "-i", narr_file_local, "-filter_complex", filt, "-map", "[v]", "-map", "[a]"]
            cmd.extend(_preferred_video_encode_args())
            cmd.extend(_preferred_audio_encode_args())
            cmd.append(out_path)

        try:
            subprocess.run(cmd, check=True)
            return True
        except Exception:
            # fallback to the previous Python helper
            try:
                narration_from_srt.mix_narration_into_video(src_for_ff, narr_file_local, out_path, narration_volume_db=narration_volume_db if narration_volume_db is not None else 3.0, replace_audio=replace_audio, extend_video=True, shift_sec=shift_sec, video_volume_db=-3.0)
                return True
            except Exception:
                return False
    except Exception:
        return False

@app.get('/process_series')
async def process_series(
    start_url: str = Query(..., description='URL tập 1 của series (ví dụ: https://v.qq.com/x/cover/dat-cid/data-vid.html)'),
    title: str = Query('', description='Tiêu đề tổng thể (tùy chọn)'),
    max_episodes: int | None = Query(None, description='Số tập tối đa sẽ xử lý (nếu để trống sẽ lấy tất cả tìm thấy)'),
    run_in_background: bool = Query(True, description='Nếu True thì chạy nền và trả về ngay (recommended)'),
    add_narration: bool = Query(False, description='Nếu True, tạo thuyết minh từ phụ đề và trộn vào video'),
    with_subtitles: bool = Query(True, description='Nếu True thì burn phụ đề vào video final; nếu False chỉ thêm thuyết minh không burn phụ đề'),
    render_full: bool = Query(False, description='If True concatenate all episodes into a single [FULL] video instead of grouping by 4'),
    narration_voice: str = Query('vi-VN-Standard-C', description='Giọng Google TTS'),
    narration_replace_audio: bool = Query(False, description='Thay hoàn toàn audio gốc bằng thuyết minh'),
    narration_volume_db: float = Query(-4.0, description='Âm lượng thuyết minh khi trộn (dB)'),
    narration_enabled: bool | None = Query(None, description='Bật/tắt việc tạo TTS thuyết minh (ưu tiên tham số này nếu được truyền)'),
    narration_rate_dynamic: int = Query(0, description='1: dùng tốc độ nói động (1.28–1.40), 0: cố định 1.0'),
    narration_apply_fx: int = Query(1, description='1: áp EQ/tone/time filter cho giọng thuyết minh'),
    bg_choice: str | None = Query(None, description='Tên file nhạc nền (optional, áp dụng cho group/full video)'),
    request_id: str | None = Query(None, description='(internal) reuse existing task_id'),
    # TikTok upload scheduling
    is_upload_tiktok: bool = Query(False, description='If True schedule rendered groups for TikTok upload'),
    upload_duration_hours: float | None = Query(None, description='Spacing (hours) between scheduled uploads when `is_upload_tiktok` is true'),
    tiktok_tags: str | None = Query(None, description='Comma-separated tags to attach to scheduled TikTok uploads'),
    cookies: str | None = Query(None, description='Path to cookies.json to use for TikTok uploader'),
    use_queue: bool = Query(True, description='If True enqueue the series job into TASK_QUEUE instead of running inline')
):
    """Download a sequence of episode pages starting from `start_url`, create subtitles for each
    episode (attempt via `whisper` CLI if available), then concatenate into a full video and
    split into parts of max 3600s if needed.

    Naming rules:
    - If `title` provided and the full video is >60min, final filename becomes "[full] {title}.mp4".
    - Otherwise parts are named "{title} P1.mp4", "{title} Phần 2.mp4", etc.
    """
    narration_volume_db = 8.0
    # Helper to safely coerce upload spacing values which may be a raw value
    # or a FastAPI `Query` param object when called programmatically.
    def _coerce_hours(val):
        try:
            if val is None:
                return None
            if isinstance(val, (int, float)):
                return float(val)
            if isinstance(val, str):
                return float(val)
            # FastAPI Query param object: use its default if present
            if hasattr(val, 'default'):
                d = getattr(val, 'default', None)
                if d is None:
                    return None
                return float(d)
            # Fallback: try direct float cast
            return float(val)
        except Exception:
            return None
    # allow caller (queue worker) to provide a request_id so the queued task keeps the same id
    if not request_id:
        request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")

    # If requested, enqueue into TASK_QUEUE and return immediately. This makes process_series
    # queue-able and manageable by the central worker loop.
    if use_queue:
        try:
            tasks_local = load_tasks()
        except Exception:
            tasks_local = {}
        tasks_local[request_id] = {
            "task_id": request_id,
            "status": "pending",
            "progress": 0,
            "video_path": "",
            "video_file": [],
            "title": title,
            "request_urls": [start_url],
            "created_at": time.time(),
            "type": 8,
            "task_type": "series",
            "skip_queue": False,
            "add_narration": bool(add_narration),
            "narration_voice": narration_voice,
            "narration_replace_audio": narration_replace_audio,
            "narration_volume_db": narration_volume_db,
            "narration_rate_dynamic": narration_rate_dynamic,
            "narration_apply_fx": narration_apply_fx,
            "bg_choice": bg_choice,
            "is_upload_tiktok": bool(is_upload_tiktok),
            "upload_duration_hours": _coerce_hours(upload_duration_hours),
            "tiktok_tags": str(tiktok_tags) if tiktok_tags else None,
            "tiktok_cookies": str(cookies) if cookies else None,
        }
        try:
            save_tasks(tasks_local)
        except Exception:
            pass

        # Build payload with all parameters the worker will need
        payload = {
            "task_id": request_id,
            "type": 8,
            "start_url": start_url,
            "title": title,
            "max_episodes": max_episodes,
            "add_narration": bool(add_narration),
            "with_subtitles": bool(with_subtitles),
            "render_full": bool(render_full),
            "narration_voice": narration_voice,
            "narration_replace_audio": narration_replace_audio,
            "narration_volume_db": narration_volume_db,
            "narration_enabled": narration_enabled,
            "narration_rate_dynamic": narration_rate_dynamic,
            "narration_apply_fx": narration_apply_fx,
            "bg_choice": bg_choice,
            "is_upload_tiktok": bool(is_upload_tiktok),
            "upload_duration_hours": _coerce_hours(upload_duration_hours),
            "tiktok_tags": str(tiktok_tags) if tiktok_tags else None,
            "tiktok_cookies": str(cookies) if cookies else None,
        }
        try:
            await enqueue_task(payload)
        except Exception:
            # best-effort: if enqueue fails, mark error
            tasks_local = load_tasks()
            tasks_local[request_id]['status'] = 'error'
            tasks_local[request_id]['error'] = 'failed to enqueue'
            save_tasks(tasks_local)
            return JSONResponse(status_code=500, content={"error": "enqueue failed"})

        send_discord_message(f"📨 Đã xếp series task vào hàng chờ: {request_id}")
        return JSONResponse(status_code=202, content={"task_id": request_id, "started": True})
    
    def _worker():
        import requests, re, urllib.parse, subprocess, time
        try:
            send_discord_message(f"🔁 process_series start: {start_url} (task {request_id})")

            # Work with a mutable copy to avoid Python local variable scoping issues
            current_url = start_url

            # Normalize m.v.qq.com: prefer canonical cid/vid → desktop URL; else follow redirects
         

            # Determine whether to generate narration per episode.
            # Priority: explicit `narration_enabled` (if not None) -> `add_narration` -> default True
            try:
                if narration_enabled is not None:
                    _add_narr = bool(narration_enabled)
                else:
                    # `add_narration` is a query param (bool), prefer it if provided, otherwise default True
                    _add_narr = bool(add_narration) if add_narration is not None else True
            except Exception:
                _add_narr = True

            # create task entry
            try:
                tasks_local = load_tasks()
            except Exception:
                tasks_local = {}
            tasks_local[request_id] = {
                "task_id": request_id,
                # Mark as pending but flagged to skip the generic worker queue
                "status": "pending",
                "progress": 0,
                "video_path": "",
                "video_file": [],
                "title": title,
                "request_urls": [start_url],
                "created_at": time.time(),
                "type": 8,
                "task_type": "series",
                "skip_queue": True,
                "add_narration": _add_narr,
                "narration_voice": narration_voice,
                "narration_replace_audio": narration_replace_audio,
                "narration_volume_db": narration_volume_db,
                "narration_rate_dynamic": narration_rate_dynamic,
                "narration_apply_fx": narration_apply_fx,
                "bg_choice": bg_choice,
                "render_full": render_full,
                "is_upload_tiktok": bool(is_upload_tiktok),
                "upload_duration_hours": _coerce_hours(upload_duration_hours),
                "tiktok_tags": str(tiktok_tags) if tiktok_tags else None,
                "tiktok_cookies": str(cookies) if cookies else None
            }
            try:
                save_tasks(tasks_local)
            except Exception as e:
                _report_and_ignore(e, "ignored")
            # Build episode list robustly: prefer Playwright extraction; fallback to regex
            unique = []
            playlist_eps = []
            # Prefer Playwright helper if available
            try:
                from qq_playlist import get_episode_links
                send_discord_message("🧭 Dùng Playwright (headless) để lấy danh sách tập...")
                # Try up to 3 times with higher timeout/slow_mo to handle slow JS or anti-bot
                playlist_eps = []
                for attempt in range(5):
                    try:
                        send_discord_message(f"🔁 Lấy danh sách tập (try {attempt+1}/5)")
                        playlist_eps = get_episode_links(current_url, headless=True, slow_mo=300, timeout_ms=120000)
                        if playlist_eps:
                            break
                    except Exception as e_attempt:
                        send_discord_message(f"⚠️ get_episode_links thất bại (try {attempt+1}/5): {e_attempt}")
                        time.sleep(1 + attempt*2)
                if not playlist_eps:
                    send_discord_message("ℹ️ Playwright không trả về tập nào, fallback regex")
            except Exception as e:
                send_discord_message(f"ℹ️ Playwright không khả dụng, fallback regex: {e}")
           
            unique = playlist_eps
            # Remove the album URL itself if it is not an episode link
            unique = [u for u in unique if re.search(r"/x/cover/[^/]+/[^/]+\.html", u)]
            # Ensure deterministic ordering and dedupe
            seen = set()
            ordered = []
            for u in unique:
                if u not in seen:
                    seen.add(u)
                    ordered.append(u)
            unique = ordered

            if max_episodes:
                unique = unique[:max_episodes]

            if not unique:
                send_discord_message(f"⚠️ Không tìm thấy tập nào từ URL: {start_url}")
                tasks_local = load_tasks(); tasks_local[request_id]['status'] = 'error'; tasks_local[request_id]['error'] = 'No episodes found'; tasks_local[request_id]['progress'] = 0; save_tasks(tasks_local)
                return

            # update progress
            tasks_local = load_tasks(); tasks_local[request_id]['progress'] = 10; save_tasks(tasks_local)

            downloaded = []
            srt_files = []
            burned_videos = []
            narrated_videos = []
            episode_links = []
            # Base title for naming temp/component files (no URL hash)
            try:
                base_title_val = safe_filename(title) if title else 'series'
            except Exception:
                base_title_val = 'series'

            # Create per-title run directory to store all episode artifacts and temps
            try:
                run_root = os.path.join(OUTPUT_DIR, base_title_val)
                os.makedirs(run_root, exist_ok=True)
                # Use a persistent run folder per title (do NOT include request_id)
                run_dir = run_root
            except Exception:
                run_dir = OUTPUT_DIR

            # Subfolder to store final/grouped videos for this title
            try:
                final_dir = os.path.join(run_dir, "finalvideo")
                os.makedirs(final_dir, exist_ok=True)
            except Exception:
                final_dir = run_dir

            # ---- Grouping helpers (4–7 episode groups, episode-index based) ----
            import math, glob
            total_eps = len(unique)
            group_size = 4
            # episode_videos[i] will hold final video path for episode index i+1 (or None on failure/skip)
            episode_videos: list[str | None] = [None] * total_eps

            # Compute groups of episode indices using original 4/5–7 logic:
            #  - Nhóm size 4 cho đến khi số tập còn lại nằm trong (5,6,7) ⇒ gộp thành 1 nhóm cuối 5–7 tập.
            group_map: dict[int, list[int]] = {}
            ep_to_group: dict[int, int] = {}
            if total_eps > 0:
                g_idx = 1
                i_ep = 1
                while i_ep <= total_eps:
                    remaining = total_eps - i_ep + 1
                    if remaining > 4 and remaining < 8:
                        eps = list(range(i_ep, total_eps + 1))
                        group_map[g_idx] = eps
                        for ep in eps:
                            ep_to_group[ep] = g_idx
                        break
                    else:
                        end_ep = min(i_ep + group_size - 1, total_eps)
                        eps = list(range(i_ep, end_ep + 1))
                        group_map[g_idx] = eps
                        for ep in eps:
                            ep_to_group[ep] = g_idx
                        g_idx += 1
                        i_ep += group_size

            def _group_output_exists(g_idx: int) -> bool:
                """Return True if a concatenated group video (or its split parts) already exists for this group.

                We check both the legacy root of run_dir and the new
                run_dir/finalvideo subfolder to maintain backward
                compatibility with older runs.
                """
                if g_idx not in group_map:
                    return False
                prefixes = [
                    os.path.join(run_dir, f"{base_title_val}_Tap_{g_idx}"),
                    os.path.join(final_dir, f"{base_title_val}_Tap_{g_idx}"),
                ]
                # Match main group file and any split parts like _P1, _P2...
                patterns = []
                for pref in prefixes:
                    patterns.append(pref + ".mp4")
                    patterns.append(pref + "_P*.mp4")
                for pat in patterns:
                    try:
                        for p in glob.glob(pat):
                            if os.path.isfile(p):
                                return True
                    except Exception:
                        continue
                return False

            # Map group index -> whether a final group video already exists on disk
            group_existing: dict[int, bool] = {g_idx: _group_output_exists(g_idx) for g_idx in group_map}

            # metadata index to allow reuse of generated pieces (srt, vi.srt, tts parts, narration)
            index_path = os.path.join(run_dir, "index.json")
            try:
                import json
                if os.path.exists(index_path):
                    with open(index_path, 'r', encoding='utf-8') as f:
                        meta_index = json.load(f)
                else:
                    meta_index = {"title": title, "request_id": request_id, "episodes": {}}
                    with open(index_path, 'w', encoding='utf-8') as f:
                        json.dump(meta_index, f, ensure_ascii=False, indent=2)
            except Exception:
                meta_index = {"episodes": {}}
            # Helper: build ffmpeg subtitles filter compatible with Windows paths
            def _ffmpeg_sub_filter(ass_path: str) -> str:
                try:
                    from pathlib import Path
                    p = Path(ass_path).resolve().as_posix()
                    p = p.replace(":", r"\:")
                    return f"subtitles=filename='{p}'"
                except Exception:
                    # Fallback to naive escaping
                    subtitle_input_escaped = ass_path.replace("'", "\\'").replace(":", r"\:")
                    return f"subtitles='{subtitle_input_escaped}'"

            # ---- Group concatenation helpers & state (used both immediate and final) ----
            final_files: list[str] = []
            rendered_groups_this_run: set[int] = set()

            # Helper: determine if it's safe to concat-copy (same codec/size/audio)
            def _can_concat_copy(files: list) -> bool:
                try:
                    import json
                    def get_info(p):
                        cmd = ['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', p]
                        proc = subprocess.run(cmd, capture_output=True, text=True)
                        if proc.returncode != 0:
                            return None
                        return json.loads(proc.stdout)

                    base_info = None
                    for p in files:
                        info = get_info(p)
                        if not info or 'streams' not in info:
                            return False
                        # find first video and audio stream
                        v = next((s for s in info['streams'] if s.get('codec_type') == 'video'), None)
                        a = next((s for s in info['streams'] if s.get('codec_type') == 'audio'), None)
                        if not v:
                            return False
                        if base_info is None:
                            base_info = (v.get('codec_name'), int(v.get('width', 0)), int(v.get('height', 0)), v.get('pix_fmt'))
                            base_audio = (a.get('codec_name') if a else None, int(a.get('sample_rate')) if a and a.get('sample_rate') else None, int(a.get('channels')) if a and a.get('channels') else None)
                        else:
                            cur_v = (v.get('codec_name'), int(v.get('width', 0)), int(v.get('height', 0)), v.get('pix_fmt'))
                            cur_a = (a.get('codec_name') if a else None, int(a.get('sample_rate')) if a and a.get('sample_rate') else None, int(a.get('channels')) if a and a.get('channels') else None)
                            if cur_v != base_info:
                                return False
                            # allow slight audio differences (e.g., different codec) but require same sample rate and channels
                            if base_audio[1] and cur_a[1] and base_audio[1] != cur_a[1]:
                                return False
                            if base_audio[2] and cur_a[2] and base_audio[2] != cur_a[2]:
                                return False
                    return True
                except Exception:
                    return False

            def _has_encoder(enc_name: str) -> bool:
                try:
                    p = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True)
                    return enc_name in p.stdout
                except Exception:
                    return False

            def _render_group_batch(group_items: list[tuple[int, list[str], str]]):
                """Render one or more groups, append outputs to final_files and update state."""
                last_group_idx = max(group_map.keys()) if group_map else None
                has_multiple_groups = len(group_map) > 1
                for g_idx, grp, group_out in group_items:
                    # Prefer concat-copy when all files are compatible; otherwise re-encode with efficient CRF
                    try:
                        if _can_concat_copy(grp):
                            concat_list = os.path.join(run_dir, f"concat_{base_title_val}_G{g_idx}.txt")
                            with open(concat_list, 'w', encoding='utf-8') as f:
                                for p in grp:
                                    f.write(f"file '{os.path.abspath(p)}'\n")
                            subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list, '-c', 'copy', group_out], check=True)
                            used_encoder = None
                        else:
                            # choose best available encoder (prefer libx265)
                            enc = 'libx265' if _has_encoder('libx265') else 'libx264'
                            if enc == 'libx265':
                                v_args = ['-c:v', 'libx265', '-preset', 'slow', '-crf', '24', '-pix_fmt', 'yuv420p', '-tag:v', 'hvc1']
                            else:
                                v_args = ['-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-pix_fmt', 'yuv420p']
                            a_args = ['-c:a', 'aac', '-b:a', '128k']
                            # Build ffmpeg inputs
                            ff_args = ['ffmpeg', '-y']
                            for p in grp:
                                ff_args.extend(['-i', p])
                            concat_filter = f"concat=n={len(grp)}:v=1:a=1"
                            ff_args.extend(['-filter_complex', concat_filter, '-vsync', 'vfr'])
                            ff_args.extend(v_args)
                            ff_args.extend(a_args)
                            ff_args.append(group_out)
                            subprocess.run(ff_args, check=True)
                            used_encoder = enc
                    except Exception:
                        # Last resort: try concat-copy (best effort)
                        concat_list = os.path.join(run_dir, f"concat_{base_title_val}_G{g_idx}.txt")
                        try:
                            with open(concat_list, 'w', encoding='utf-8') as f:
                                for p in grp:
                                    f.write(f"file '{os.path.abspath(p)}'\n")
                            subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list, '-c', 'copy', group_out], check=True)
                        except Exception as e:
                            _report_and_ignore(e, "ignored")
                            continue

                    # Overlay title for 3s at start indicating starting episode or FULL
                    if title:
                        tmp_title = None
                        try:
                            font_path_try = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
                            try:
                                if not os.path.exists(font_path_try):
                                    font_path_try = "C:\\Windows\\Fonts\\arial.ttf" if os.name == "nt" else "times.ttf"
                            except Exception:
                                font_path_try = "C:\\Windows\\Fonts\\arial.ttf" if os.name == "nt" else "times.ttf"
                            # Use group ordinal for the overlay, or [FULL] when requested
                            if render_full:
                                title_text = f"[FULL] {title}"
                            else:
                                title_text = f"{title} - Tập {g_idx}"
                                if has_multiple_groups and last_group_idx == g_idx:
                                    title_text += " - Cuối"
                            title_text = title_text.replace(":", "\\:").replace("'", "\\'")
                            wrapped_text = wrap_text(title_text, max_chars_per_line=35)
                            drawtext = (
                                f"drawtext=fontfile='{font_path_try}':text_align=center:text='{wrapped_text}':"
                                f"fontcolor=white:fontsize=42:box=1:boxcolor=black@0.6:boxborderw=20:"
                                f"x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,0,3)'"
                            )
                            tmp_title = group_out + ".title.mp4"
                            cmd_title = ["ffmpeg", "-y", "-i", group_out, "-vf", drawtext]
                            cmd_title.extend(_preferred_video_encode_args())
                            cmd_title.extend(["-c:a", "copy", tmp_title])
                            subprocess.run(cmd_title, check=True)
                            os.replace(tmp_title, group_out)
                        except Exception as e:
                            _report_and_ignore(e, "ignored")
                        finally:
                            try:
                                if tmp_title and os.path.exists(tmp_title):
                                    os.remove(tmp_title)
                            except Exception:
                                pass

                    # Mix background audio if provided (in 1 render pass)
                    if bg_choice:
                        try:
                            send_discord_message(f"🎵 Đang thêm nhạc nền cho nhóm {g_idx}...")
                            
                            # Find background audio file
                            discord_bot_bgaudio = os.path.join(BASE_DIR, "discord-bot", "bgaudio")
                            if os.path.isdir(discord_bot_bgaudio):
                                bgaudio_dir = discord_bot_bgaudio
                            else:
                                bgaudio_dir = os.path.join(OUTPUT_DIR, "bgaudio")
                            
                            bg_file = os.path.join(bgaudio_dir, os.path.basename(bg_choice))
                            if os.path.exists(bg_file):
                                tmp_with_bg = group_out + ".with_bg.mp4"
                                
                                # Mix background audio: loop bg, lower volume, mix with original audio
                                filter_complex = (
                                    "[1:a]aloop=loop=-1:size=2e+09,volume=-14dB[bg];"
                                    "[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0[a]"
                                )
                                
                                cmd_bg = [
                                    "ffmpeg", "-y",
                                    "-i", group_out,  # [0] video with audio
                                    "-i", bg_file,     # [1] background audio
                                    "-filter_complex", filter_complex,
                                    "-map", "0:v",     # video from input 0
                                    "-map", "[a]",     # mixed audio
                                    "-c:v", "copy",    # copy video codec
                                    "-c:a", "aac", "-b:a", "128k",
                                    tmp_with_bg
                                ]
                                
                                subprocess.run(cmd_bg, check=True, capture_output=True)
                                os.replace(tmp_with_bg, group_out)
                                send_discord_message(f"✅ Đã thêm nhạc nền: {os.path.basename(bg_file)}")
                            else:
                                send_discord_message(f"⚠️ Không tìm thấy nhạc nền: {bg_file}")
                        except Exception as e:
                            send_discord_message(f"⚠️ Lỗi khi thêm nhạc nền: {e}")

                    # If group file exceeds 3600s, split into parts (no re-encode)
                    try:
                        _, _, group_dur = get_media_info(group_out)
                    except Exception:
                        group_dur = None
                    if group_dur and group_dur > 3600 and not render_full:
                        parts = math.ceil(group_dur / 3600)
                        for p in range(parts):
                            start = p * 3600
                            outp = os.path.join(final_dir, f"{base_title_val}_Tap_{g_idx}_P{p+1}.mp4")
                            subprocess.run(['ffmpeg', '-y', '-ss', str(start), '-i', group_out, '-t', '3600', '-c', 'copy', outp], check=True)
                            final_files.append(outp)
                        # Immediately announce each split part for this group (Drive upload removed)
                        try:
                            for p in range(parts):
                                outp = os.path.join(final_dir, f"{base_title_val}_Tap_{g_idx}_P{p+1}.mp4")
                                if os.path.exists(outp):
                                    try:
                                        rel = to_project_relative_posix(outp)
                                        uploaded = uploadOneDrive(outp,base_title_val)
                                        link = uploaded.get('downloadLink') or uploaded.get('webViewLink')
                                        view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                                        download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                                        send_discord_message(f"🎥 Xem video (nhóm {g_idx} phần {p+1}):" + view_link)
                                        send_discord_message(f"⬇️ Tải video (nhóm {g_idx} phần {p+1}):" + download_link)
                                    except Exception as e:
                                        _report_and_ignore(e, "ignored")
                        except Exception as e:
                            _report_and_ignore(e, "ignored")
                        # Schedule split parts for TikTok upload if requested
                        try:
                            if bool(is_upload_tiktok):
                                schedule_file = os.path.join(CACHE_DIR, 'tiktok_upload_queue.json')
                                try:
                                    existing_sched = []
                                    if os.path.exists(schedule_file):
                                        with open(schedule_file, 'r', encoding='utf8') as sfh:
                                            existing_sched = json.load(sfh) if sfh.read().strip() else []
                                except Exception:
                                    existing_sched = []
                                base_time = time.time()
                                spacing = (_coerce_hours(upload_duration_hours) or 0) * 3600
                                last_time = None
                                if existing_sched:
                                    try:
                                        last_time = max(item.get('scheduled_at', 0) for item in existing_sched)
                                    except Exception:
                                        last_time = None
                                start_time = last_time + spacing if (last_time and spacing) else base_time
                                tags_list = []
                                try:
                                    if tiktok_tags:
                                        tags_list = [t.strip() for t in re.split(r"[,;\n]+", tiktok_tags) if t.strip()]
                                except Exception:
                                    tags_list = []
                                # schedule each split part sequentially
                                for idx_p in range(parts):
                                    outp = os.path.join(final_dir, f"{base_title_val}_Tap_{g_idx}_P{idx_p+1}.mp4")
                                    scheduled = {
                                        'scheduled_at': int(start_time + idx_p * spacing) if spacing else int(start_time),
                                        'video_path': to_project_relative_posix(outp),
                                        'title': (title_text if 'title_text' in locals() else (f"{title} - Tập {g_idx} P{idx_p+1}" if title else f"Tập {g_idx} P{idx_p+1}")),
                                        'tags': tags_list,
                                        'created_at': int(time.time()),
                                        'task_request_id': request_id,
                                    }
                                    existing_sched.append(scheduled)
                                try:
                                    with open(schedule_file, 'w', encoding='utf8') as sfh:
                                        json.dump(existing_sched, sfh, ensure_ascii=False, indent=2)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    else:
                        # Group NOT split: schedule the whole group_out file
                        final_files.append(group_out)
                        # Announce the concatenated group file (Drive upload removed)
                        try:
                            if os.path.exists(group_out):
                                try:
                                    rel = to_project_relative_posix(group_out)
                                    uploaded = uploadOneDrive(group_out,base_title_val)
                                    link = uploaded.get('downloadLink') or uploaded.get('webViewLink')
                                    view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                                    download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                                    send_discord_message(f"🎥 Xem video (nhóm {g_idx}):" + view_link)
                                    send_discord_message(f"⬇️ Tải video (nhóm {g_idx}):" + download_link)
                                except Exception as e:
                                    _report_and_ignore(e, "ignored")
                        except Exception as e:
                            _report_and_ignore(e, "ignored")

                        # If TikTok upload scheduling requested, add this group's output(s) to the schedule
                        try:
                            if bool(is_upload_tiktok):
                                try:
                                    schedule_file = os.path.join(CACHE_DIR, 'tiktok_upload_queue.json')
                                    try:
                                        existing_sched = []
                                        if os.path.exists(schedule_file):
                                            try:
                                                with open(schedule_file, 'r', encoding='utf8') as sfh:
                                                    existing_sched = json.load(sfh)
                                            except Exception:
                                                existing_sched = []
                                    except Exception:
                                        existing_sched = []

                                    # Determine base time for this run: now or last scheduled time + spacing
                                    base_time = time.time()
                                    spacing = (_coerce_hours(upload_duration_hours) or 0) * 3600
                                    # find last scheduled time in existing_sched for this run if present
                                    last_time = None
                                    if existing_sched:
                                        try:
                                            last_time = max(item.get('scheduled_at', 0) for item in existing_sched)
                                        except Exception:
                                            last_time = None

                                    # If spacing provided and there is existing scheduled items, start after last_time
                                    start_time = last_time + spacing if (last_time and spacing) else base_time

                                    # tags
                                    tags_list = []
                                    try:
                                        if tiktok_tags:
                                            tags_list = [t.strip() for t in re.split(r"[,;\n]+", tiktok_tags) if t.strip()]
                                    except Exception:
                                        tags_list = []

                                    # If this group was split into parts earlier we handled those; here schedule group_out
                                    scheduled = {
                                        'scheduled_at': int(start_time),
                                        'video_path': to_project_relative_posix(group_out),
                                        'title': (title_text if 'title_text' in locals() else (f"{title} - Tập {g_idx}" if title else f"Tập {g_idx}")),
                                        'tags': tags_list,
                                        'created_at': int(time.time()),
                                        'task_request_id': request_id,
                                    }
                                    existing_sched.append(scheduled)
                                    # save back
                                    try:
                                        with open(schedule_file, 'w', encoding='utf8') as sfh:
                                            json.dump(existing_sched, sfh, ensure_ascii=False, indent=2)
                                    except Exception:
                                        pass
                                except Exception:
                                    pass
                        except Exception:
                            pass

                    # Mark group as existing when running in non-full grouped mode
                    if not render_full and g_idx in group_existing:
                        group_existing[g_idx] = True
                        rendered_groups_this_run.add(g_idx)

            # 2) For each episode, use convert_stt flow: download -> transcribe -> burn subtitles


            for i, ep_url in enumerate(unique, start=1):
                # Cooperative cancellation check: if UI requested cancel, stop work promptly
                try:
                    if should_abort_sync(request_id):
                        try:
                            tasks_local = load_tasks()
                            if request_id in tasks_local:
                                tasks_local[request_id]['status'] = 'cancelled'
                                tasks_local[request_id]['progress'] = 0
                                save_tasks(tasks_local)
                        except Exception:
                            pass
                        send_discord_message(f"⛔ process_series cancelled by user: {request_id}")
                        return
                except Exception:
                    pass
                # Determine group index for this episode using 4–7 grouping logic
                group_idx = ep_to_group.get(i, 1) if not render_full and group_map else 1
                # If the corresponding group video already exists, skip heavy processing for these episodes
                if not render_full and group_existing.get(group_idx):
                    try:
                        send_discord_message(f"♻️ Bỏ qua tập {i} vì nhóm {group_idx} đã có video.")
                    except Exception:
                        pass
                    continue

                send_discord_message(f"⬇️ [{i}/{len(unique)}] Xử lý: {ep_url}")
                try:
                    # Per-episode force-rebuild flag: set True when we delete artefacts
                    force_rebuild = False
                    # Deterministic filenames based on provided title and episode index (no hash)
                    ep_label = f"{base_title_val}_Tap_{i}"
                    out_video = os.path.join(run_dir, f"{ep_label}.mp4")
                    # download filename should be distinct to avoid colliding with group/final names
                    dl_video = os.path.join(run_dir, f"{ep_label}_download.mp4")
                    vi_srt = os.path.join(run_dir, f"{ep_label}.vi.srt")
                    raw_srt = os.path.join(run_dir, f"{ep_label}_download.srt")
                    tiktok_out = os.path.join(run_dir, f"{ep_label}.tiktok.mp4")
                    # If a narrated episode output already exists from a previous run, reuse it
                    try:
                        prebuilt_narr = os.path.join(run_dir, f"{ep_label}.nar.mp4")
                        if os.path.exists(prebuilt_narr) :
                            # If an SRT exists and contains flagged keywords, treat the episode
                            # as not successfully processed: remove artefacts and force full reprocess.
                            try:
                                srt_to_check = None
                                if os.path.exists(vi_srt):
                                    srt_to_check = vi_srt
                                elif os.path.exists(raw_srt):
                                    srt_to_check = raw_srt

                                if srt_to_check and convert_stt._srt_contains_keywords(srt_to_check):
                                    send_discord_message(f"♻️ Phát hiện phụ đề lỗi cho {ep_label}; xóa artefact để tạo lại từ đầu")
                                    try:
                                        # Remove final video/audio artifacts to force rebuild
                                        cand_remove = [prebuilt_narr, os.path.join(run_dir, f"{ep_label}.nar.flac"), os.path.join(run_dir, f"{ep_label}.schedule.json")]
                                        for p in cand_remove:
                                            try:
                                                if p and os.path.exists(p):
                                                    os.remove(p)
                                            except Exception as _e:
                                                _report_and_ignore(_e, "ignored")
                                        # mark that we removed artifacts and must rebuild
                                        force_rebuild = True

                                        # Remove per-line TTS pieces under tts_pieces (common patterns)
                                        try:
                                            import glob
                                            tts_patterns = [
                                                os.path.join(run_dir, "tts_pieces", "tts", f"{ep_label}.vi_tts.*"),
                                                os.path.join(run_dir, "tts_pieces", f"{ep_label}*"),
                                                os.path.join(run_dir, "tts_pieces", "**", f"{ep_label}*"),
                                            ]
                                            found = []
                                            for pat in tts_patterns:
                                                try:
                                                    found.extend(glob.glob(pat, recursive=True))
                                                except Exception:
                                                    continue
                                            for fpath in set(found):
                                                try:
                                                    if os.path.exists(fpath):
                                                        os.remove(fpath)
                                                except Exception as _e:
                                                    _report_and_ignore(_e, "ignored")
                                        except Exception as _e:
                                            _report_and_ignore(_e, "ignored")

                                        # Remove the SRT files themselves so the pipeline will re-transcribe
                                        for s in (vi_srt, raw_srt):
                                            try:
                                                if s and os.path.exists(s):
                                                    os.remove(s)
                                            except Exception as _e:
                                                _report_and_ignore(_e, "ignored")
                                    except Exception as _e:
                                        _report_and_ignore(_e, "ignored")
                                    # Do NOT continue here; allow normal processing below to re-generate SRT/narration
                                else:
                                    send_discord_message(f"♻️ Đã có video thuyết minh tập {i}: {prebuilt_narr} — thêm vào danh sách nối")
                                    narrated_videos.append(prebuilt_narr)
                                    # Track final video for this episode index
                                    if 1 <= i <= total_eps:
                                        episode_videos[i-1] = prebuilt_narr
                                    try:
                                        rel = to_project_relative_posix(prebuilt_narr)
                                        view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                                        download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                                        send_discord_message(f"🎥 Xem video tập {i} :" + view_link)
                                        send_discord_message(f"⬇️ Tải video tập  {i}:" + download_link)
                                    except Exception as e:
                                        _report_and_ignore(e, "ignored")
                                    # Track progress artifacts for visibility
                                    if os.path.exists(vi_srt):
                                        srt_files.append(vi_srt)
                                    if os.path.exists(tiktok_out):
                                        burned_videos.append(tiktok_out)
                                    if os.path.exists(dl_video):
                                        downloaded.append(dl_video)
                                    try:
                                        tasks_local = load_tasks()
                                        # Ensure task record exists to avoid KeyError (may be removed externally)
                                        if request_id not in tasks_local:
                                            tasks_local.setdefault(request_id, {
                                                "task_id": request_id,
                                                "status": "pending",
                                                "created_at": time.time(),
                                            })

                                        tasks_local[request_id]['progress'] = 20 + int((len(srt_files) / len(unique)) * 40)
                                        tasks_local[request_id].setdefault('video_file', [])
                                        tasks_local[request_id]['video_file'] = downloaded
                                        tasks_local[request_id].setdefault('srt_files', [])
                                        tasks_local[request_id]['srt_files'] = srt_files
                                        tasks_local[request_id].setdefault('burned_videos', [])
                                        tasks_local[request_id]['burned_videos'] = burned_videos
                                        tasks_local[request_id].setdefault('narrated_videos', [])
                                        tasks_local[request_id]['narrated_videos'] = narrated_videos
                                        save_tasks(tasks_local)
                                    except Exception as e:
                                        _report_and_ignore(e, "ignored")
                                    # Skip expensive reprocessing for this episode (only when not flagged)
                                    continue
                            except Exception as e:
                                _report_and_ignore(e, "ignored")
                            if not force_rebuild:
                                try:
                                    rel = to_project_relative_posix(prebuilt_narr)
                                    view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                                    download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                                    send_discord_message(f"🎥 Xem video tập {i} :" + view_link)
                                    send_discord_message(f"⬇️ Tải video tập  {i}:" + download_link)
                                except Exception as e:
                                    _report_and_ignore(e, "ignored")
                                # Track progress artifacts for visibility
                                if os.path.exists(vi_srt):
                                    srt_files.append(vi_srt)
                                if os.path.exists(tiktok_out):
                                    burned_videos.append(tiktok_out)
                                if os.path.exists(dl_video):
                                    downloaded.append(dl_video)
                                try:
                                    tasks_local = load_tasks()
                                    tasks_local[request_id]['progress'] = 20 + int((len(srt_files) / len(unique)) * 40)
                                    tasks_local[request_id].setdefault('video_file', [])
                                    tasks_local[request_id]['video_file'] = downloaded
                                    tasks_local[request_id].setdefault('srt_files', [])
                                    tasks_local[request_id]['srt_files'] = srt_files
                                    tasks_local[request_id].setdefault('burned_videos', [])
                                    tasks_local[request_id]['burned_videos'] = burned_videos
                                    tasks_local[request_id].setdefault('narrated_videos', [])
                                    tasks_local[request_id]['narrated_videos'] = narrated_videos
                                    save_tasks(tasks_local)
                                except Exception as e:
                                    _report_and_ignore(e, "ignored")
                                # Skip expensive reprocessing for this episode
                                continue
                        # If narration disabled in future and burned preview exists, include it
                        # Only reuse burned preview when we're NOT forcing a rebuild
                        if not _add_narr and os.path.exists(tiktok_out) and not force_rebuild:
                            send_discord_message(f"♻️ Đã có video burn phụ đề tập {i}: {tiktok_out} — thêm vào danh sách nối")
                            burned_videos.append(tiktok_out)
                            # Track final video for this episode when only burned video is used
                            if 1 <= i <= total_eps and episode_videos[i-1] is None:
                                episode_videos[i-1] = tiktok_out
                            continue
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
                    # Integrity check: if an SRT exists (vi or raw) but may be flagged,
                    # remove it so the pipeline will re-transcribe and re-generate narration.
                    try:
                        srt_to_check = None
                        if os.path.exists(vi_srt):
                            srt_to_check = vi_srt
                        elif os.path.exists(raw_srt):
                            srt_to_check = raw_srt

                        if srt_to_check:
                            try:
                                if convert_stt._srt_contains_keywords(srt_to_check):
                                    send_discord_message(f"♻️ Phát hiện phụ đề lỗi cho {ep_label}; sẽ xóa SRT để tạo lại từ đầu: {srt_to_check}")
                                    # remove the SRT and any associated artifacts
                                    try:
                                        if os.path.exists(srt_to_check):
                                            os.remove(srt_to_check)
                                    except Exception as _e:
                                        _report_and_ignore(_e, "ignored")
                                    # remove per-line TTS pieces for this episode
                                    try:
                                        import glob
                                        tts_patterns = [
                                            os.path.join(run_dir, "tts_pieces", "tts", f"{ep_label}.vi_tts.*"),
                                            os.path.join(run_dir, "tts_pieces", f"{ep_label}*"),
                                            os.path.join(run_dir, "tts_pieces", "**", f"{ep_label}*"),
                                        ]
                                        found = []
                                        for pat in tts_patterns:
                                            try:
                                                found.extend(glob.glob(pat, recursive=True))
                                            except Exception:
                                                continue
                                        for fpath in set(found):
                                            try:
                                                if os.path.exists(fpath):
                                                    os.remove(fpath)
                                            except Exception as _e:
                                                _report_and_ignore(_e, "ignored")
                                    except Exception as _e:
                                        _report_and_ignore(_e, "ignored")
                                    # also remove any existing narration pieces to avoid reuse
                                    try:
                                        for p in (os.path.join(run_dir, f"{ep_label}.nar.flac"), os.path.join(run_dir, f"{ep_label}.schedule.json")):
                                            try:
                                                if p and os.path.exists(p):
                                                    os.remove(p)
                                            except Exception as _e:
                                                _report_and_ignore(_e, "ignored")
                                    except Exception:
                                        pass
                                        # ensure the loop will rebuild this episode
                                        force_rebuild = True
                                    # fall through to the normal transcription path (do not `continue`)
                            except Exception as _e:
                                _report_and_ignore(_e, "ignored")
                    except Exception:
                        pass

                    # If Vietnamese SRT already exists, skip transcription step
                    if os.path.exists(vi_srt):
                        send_discord_message(f"♻️ Đã có phụ đề tiếng Việt: {vi_srt} — bỏ qua tạo lại SRT")
                        srt_files.append(vi_srt)

                        # If narration requested, generate narration first then render
                        if _add_narr:
                            # ensure video file exists locally
                            if not os.path.exists(dl_video):
                                send_discord_message(f"⬇️ Tải video vì thiếu file local để burn+nar: {ep_url}")
                                try:
                                    out_dl = convert_stt.download_video(ep_url, dl_video)
                                except Exception:
                                    out_dl = None
                                if not out_dl:
                                    send_discord_message(f"⚠️ Không thể tải video để burn+nar: {ep_url}")
                                    continue

                            # Prepare ASS from SRT only if subtitles requested
                            ass_path = None
                            try:
                                convert_srt_to_ass_convert = None
                                if with_subtitles:
                                    try:
                                        from convert_srt_to_ass import convert as convert_srt_to_ass_convert
                                    except Exception:
                                        convert_srt_to_ass_convert = None

                                    ass_path = vi_srt.replace('.srt', '.ass')
                                    if convert_srt_to_ass_convert:
                                        try:
                                            convert_srt_to_ass_convert(vi_srt, ass_path, 30, 11, "Noto Sans", 20, 150)
                                        except Exception:
                                            ass_path = vi_srt
                                    else:
                                        try:
                                            subprocess.run(["ffmpeg", "-y", "-i", vi_srt, ass_path], check=True)
                                        except Exception:
                                            ass_path = vi_srt
                                else:
                                    # subtitles disabled for this run; keep ass_path None
                                    ass_path = None
                            except Exception:
                                ass_path = None

                            # Build narration audio (schedule) and then run a single ffmpeg pass
                            try:
                                # Reuse existing narration if available
                                nar_out_flac = os.path.join(run_dir, f"{ep_label}.nar.flac")
                                ep_narr_out = os.path.join(run_dir, f"{ep_label}.nar.mp4")
                                # If final narrated video already exists, reuse it
                                # Do not reuse when forcing rebuild
                                if os.path.exists(ep_narr_out) and not force_rebuild:
                                    narrated_videos.append(ep_narr_out)
                                    # update index
                                    try:
                                        meta_index.setdefault('episodes', {})
                                        meta_index['episodes'][ep_label] = meta_index['episodes'].get(ep_label, {})
                                        meta_index['episodes'][ep_label].update({'nar_video': ep_narr_out})
                                        with open(index_path, 'w', encoding='utf-8') as f:
                                            json.dump(meta_index, f, ensure_ascii=False, indent=2)
                                    except Exception as e:
                                        try:
                                            import traceback
                                            send_discord_message(f"⚠️ process_series: error writing index for {ep_label}: {e}\n{traceback.format_exc()}")
                                        except Exception as e:
                                            _report_and_ignore(e, "ignored")
                                    continue
                                # If final narration audio exists, mix into video without regenerating TTS
                                # Do not reuse when forcing rebuild
                                if os.path.exists(nar_out_flac) and not force_rebuild:
                                    try:
                                        src_for_mix = dl_video
                                        # Do not pre-burn subtitles to a temp file; let the single-pass helper handle burning.
                                      

                                            # Single-pass: burn ASS + mix prebuilt narration (centralized helper)
                                        try:
                                            burn_and_mix_narration(src_for_mix, ass_path, nar_out_flac, ep_narr_out, replace_audio=narration_replace_audio, narration_volume_db=narration_volume_db, shift_sec=0.7, with_subtitles=with_subtitles)
                                        except Exception:
                                            try:
                                                narration_from_srt.mix_narration_into_video(src_for_mix, nar_out_flac, ep_narr_out, narration_volume_db=narration_volume_db if narration_volume_db is not None else 3.0, replace_audio=narration_replace_audio, extend_video=True, shift_sec=0.7, video_volume_db=-3.0)
                                            except Exception as e:
                                                try:
                                                    import traceback
                                                    send_discord_message(f"⚠️ process_series: failed to publish episode links for {ep_label}: {e}\n{traceback.format_exc()}")
                                                except Exception as e:
                                                    _report_and_ignore(e, "ignored")
                                            if os.path.exists(ep_narr_out):
                                                narrated_videos.append(ep_narr_out)
                                                if 1 <= i <= total_eps:
                                                    episode_videos[i-1] = ep_narr_out
                                            try:
                                                meta_index.setdefault('episodes', {})
                                                meta_index['episodes'][ep_label] = meta_index['episodes'].get(ep_label, {})
                                                meta_index['episodes'][ep_label].update({'nar_audio': nar_out_flac, 'nar_video': ep_narr_out})
                                                with open(index_path, 'w', encoding='utf-8') as f:
                                                    json.dump(meta_index, f, ensure_ascii=False, indent=2)
                                                send_discord_message(f"🎥 Xong video thuyết minh tập {i}: {ep_narr_out}")
                                                sandbox_rel = to_project_relative_posix(ep_narr_out)
                                                view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(sandbox_rel)
                                                download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(sandbox_rel)
                                                send_discord_message(f"🎥 Xem video tập {i} :" + view_link)
                                                send_discord_message(f"⬇️ Tải video tập {i} :" + download_link)
                                            except Exception as e:
                                                _report_and_ignore(e, "process_series: mix fallback inner")
                                            continue
                                    except Exception as e:
                                        try:
                                            import traceback
                                            send_discord_message(f"⚠️ process_series: failed to publish episode links for {ep_label}: {e}\n{traceback.format_exc()}")
                                        except Exception as e:
                                            _report_and_ignore(e, "process_series: update index (inner)")
                                # Otherwise, look for existing TTS pieces to concatenate and reuse
                                tts_pieces_dir = os.path.join(run_dir, "tts_pieces")
                                try:
                                    import glob
                                    # search common piece patterns inside run_dir and subfolders
                                    patterns = [
                                        os.path.join(run_dir, f"norm_{ep_label}_*.flac"),
                                        
                                    ]
                                    pieces = []
                                    for p in patterns:
                                        pieces.extend(sorted(glob.glob(p)))
                                    # also search recursively under run_dir
                                    for root, dirs, files in os.walk(run_dir):
                                        for fn in files:
                                            if fn.endswith('.flac') and (fn.startswith('piece_') or fn.startswith('tts_') or fn.startswith('fit_') or fn.startswith(f"{ep_label}")):
                                                pieces.append(os.path.join(root, fn))
                                    pieces = sorted(set(pieces))
                                    # Only reuse pieces when not forcing a rebuild
                                    if pieces and not force_rebuild:
                                        # assemble into final nar_out_flac
                                        try:
                                            nar_audio, _meta = narration_from_srt.build_narration_schedule(
                                                vi_srt, nar_out_flac,
                                                voice_name=narration_voice,
                                                speaking_rate=1.0,
                                                lead=0.0,
                                                meta_out=os.path.join(run_dir, f"{ep_label}.schedule.json"),
                                                trim=False,
                                                rate_mode=narration_rate_dynamic,
                                                apply_fx=bool(narration_apply_fx),
                                                tmp_subdir=tts_pieces_dir
                                            )
                                            if os.path.exists(nar_out_flac):
                                                try:
                                                    src_for_mix = dl_video
                                                    
                                                    # Single-pass: burn subtitles (ASS) + mix prebuilt narration audio
                                                    try:
                                                        burn_and_mix_narration(src_for_mix, ass_path, nar_out_flac, ep_narr_out, replace_audio=narration_replace_audio, narration_volume_db=narration_volume_db, shift_sec=0.7, with_subtitles=with_subtitles)
                                                    except Exception:
                                                        try:
                                                            narration_from_srt.mix_narration_into_video(src_for_mix, nar_out_flac, ep_narr_out, narration_volume_db=narration_volume_db if narration_volume_db is not None else 3.0, replace_audio=narration_replace_audio, extend_video=True, shift_sec=0.7, video_volume_db=-3.0)
                                                        except Exception as e:
                                                            _report_and_ignore(e, "ignored")
                                                except Exception as e:
                                                    _report_and_ignore(e, "ignored")
                                                if os.path.exists(ep_narr_out):
                                                    narrated_videos.append(ep_narr_out)
                                                    try:
                                                        meta_index.setdefault('episodes', {})
                                                        meta_index['episodes'][ep_label] = meta_index['episodes'].get(ep_label, {})
                                                        meta_index['episodes'][ep_label].update({'nar_audio': nar_out_flac, 'nar_video': ep_narr_out})
                                                        with open(index_path, 'w', encoding='utf-8') as f:
                                                            json.dump(meta_index, f, ensure_ascii=False, indent=2)
                                                        sandbox_rel = to_project_relative_posix(ep_narr_out)
                                                        view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(sandbox_rel)
                                                        download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(sandbox_rel)
                                                        send_discord_message(f"🎥 Xem video tập {i} :" + view_link)
                                                        send_discord_message(f"⬇️ Tải video tập {i} :" + download_link)
                                                    except Exception as e:
                                                        _report_and_ignore(e, "ignored")
                                                    continue
                                        except Exception as e:
                                            _report_and_ignore(e, "process_series: pieces concat attempt")
                                except Exception as e:
                                    _report_and_ignore(e, "ignored")
                                # If we reach here, no reusable narration found — proceed to build normally
                                nar_audio, _meta = (None, None)
                                nar_out_flac = os.path.join(run_dir, f"{ep_label}.nar.flac")
                                # place per-line TTS pieces into a dedicated subfolder to avoid clutter
                              
                                try:
                                    os.makedirs(tts_pieces_dir, exist_ok=True)
                                except Exception:
                                    tts_pieces_dir = run_dir

                                nar_audio, _meta = narration_from_srt.build_narration_schedule(
                                    vi_srt, nar_out_flac,
                                    voice_name=narration_voice,
                                    speaking_rate=1.0,
                                    lead=0.0,
                                    meta_out=os.path.join(run_dir, f"{ep_label}.schedule.json"),
                                    trim=False,
                                    rate_mode=narration_rate_dynamic,
                                    apply_fx=bool(narration_apply_fx),
                                    tmp_subdir=tts_pieces_dir
                                )
                                # ensure ep_narr_out path set
                                ep_narr_out = os.path.join(run_dir, f"{ep_label}.nar.mp4")
                                

                                # Build ffmpeg filter_complex to burn subtitles and mix narration
                                sub_filter = ''
                                if with_subtitles and ass_path:
                                    try:
                                        sub_filter = _ffmpeg_sub_filter(ass_path)
                                    except Exception:
                                        sub_filter = ''
                                narr_vol_lin = 10 ** (float(narration_volume_db) / 20.0) if narration_volume_db is not None else 10 ** (6.0/20.0)

                                # Determine durations
                                vid_dur = None
                                try:
                                    vid_dur = get_media_info(dl_video)[2]
                                except Exception:
                                    vid_dur = None
                                try:
                                    nar_dur = get_media_info(nar_audio)[2] if os.path.exists(nar_audio) else 0.0
                                except Exception:
                                    nar_dur = 0.0
                                pad_sec = max(0.0, nar_dur - (vid_dur or 0.0))
                                need_pad = pad_sec > 0.01 and narration_replace_audio is False

                                # Compose filter_complex
                                # If narration longer than video and we are not replacing audio, extend last frame
                                tpad_frag = f"tpad=stop_mode=clone:stop_duration={pad_sec}" if need_pad else ""
                                # Place tpad before burning subtitles so ASS timing still applies
                                # Keep original video resolution: do NOT scale/pad/setsar the downloaded video.
                                if with_subtitles and sub_filter:
                                    if tpad_frag:
                                        vchain = f"[0:v]{tpad_frag},{sub_filter}[v]"
                                    else:
                                        vchain = f"[0:v]{sub_filter}[v]"
                                else:
                                    # No subtitle filter: just pass through video (optionally padded)
                                    if tpad_frag:
                                        vchain = f"[0:v]{tpad_frag},setpts=PTS[v]"
                                    else:
                                        vchain = "[0:v]setpts=PTS[v]"

                                # narration: input 1
                                shift_ms = max(0, int(0.7 * 1000))
                                nar_chain = f"[1:a]adelay={shift_ms}|{shift_ms},volume={narr_vol_lin}[nar]"

                                if narration_replace_audio:
                                    # Replace original audio with narration (no background mix)
                                    filter_complex = ";".join([vchain, nar_chain])
                                    cmd = ["ffmpeg", "-y", "-i", dl_video, "-i", nar_audio, "-filter_complex", filter_complex, "-map", "[v]", "-map", "[nar]"]
                                    cmd.extend(_preferred_video_encode_args())
                                    cmd.extend(_preferred_audio_encode_args())
                                    cmd.append(ep_narr_out)
                                else:
                                    # background audio (attenuated) + narration mixed; use duration=longest
                                    vid_bg_chain = f"[0:a]volume={10 ** ((-9.0)/20):.6f}[bg]"
                                    amix_chain = f"[bg][nar]amix=inputs=2:duration=longest:normalize=0[a]"
                                    filter_complex = ";".join([vchain, vid_bg_chain, nar_chain, amix_chain])
                                    cmd = ["ffmpeg", "-y", "-i", dl_video, "-i", nar_audio, "-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]"]
                                    cmd.extend(_preferred_video_encode_args())
                                    cmd.extend(_preferred_audio_encode_args())
                                    cmd.append(ep_narr_out)
                                try:
                                    subprocess.run(cmd, check=True)
                                    narrated_videos.append(ep_narr_out)
                                    # Track final per-episode video for grouping
                                    if 1 <= i <= total_eps:
                                        episode_videos[i-1] = ep_narr_out
                                    # update task artifacts
                                    downloaded.append(dl_video)
                                    # Immediately publish sandbox links and try upload to Drive for this episode
                                    try:
                                        rel = to_project_relative_posix(ep_narr_out)
                                       
                                        view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                                        download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                                        send_discord_message(f"🎥 Xem video tập {i} :" + view_link)
                                        send_discord_message(f"⬇️ Tải video tập  {i}:" + download_link)
                                    except Exception as e:
                                        try:
                                            import traceback
                                            send_discord_message(f"⚠️ process_series: Drive upload failed for group {g_idx} part {p+1}: {e}\n{traceback.format_exc()}")
                                        except Exception as e:
                                            _report_and_ignore(e, "process_series: pieces finalize")
                                    # update index
                                    try:
                                        meta_index.setdefault('episodes', {})
                                        meta_index['episodes'][ep_label] = meta_index['episodes'].get(ep_label, {})
                                        meta_index['episodes'][ep_label].update({
                                            'srt': raw_srt if os.path.exists(raw_srt) else None,
                                            'srt_vi': vi_srt if os.path.exists(vi_srt) else None,
                                            'nar_audio': nar_out_flac if os.path.exists(nar_out_flac) else None,
                                            'nar_video': ep_narr_out if os.path.exists(ep_narr_out) else None,
                                            'schedule': os.path.join(run_dir, f"{ep_label}.schedule.json")
                                        })
                                        with open(index_path, 'w', encoding='utf-8') as f:
                                            json.dump(meta_index, f, ensure_ascii=False, indent=2)
                                    except Exception as e:
                                        _report_and_ignore(e, "ignored")
                                except Exception as e:
                                    send_discord_message(f"⚠️ Lỗi khi render video+kara+nar: {e}")
                                    # fallback: create burned preview then mix
                                    try:
                                        # Instead of creating a persistent burned preview file (tiktok_out)
                                        # to save disk, mix narration directly into the downloaded video.
                                        # Single-pass: burn subtitles (if present) + mix generated narration audio
                                        try:
                                            ok = burn_and_mix_narration(dl_video, ass_path, nar_audio, ep_narr_out, replace_audio=narration_replace_audio, narration_volume_db=narration_volume_db, shift_sec=0.7, with_subtitles=with_subtitles)
                                            if not ok:
                                                try:
                                                    narration_from_srt.mix_narration_into_video(dl_video, nar_audio, ep_narr_out, narration_volume_db=narration_volume_db if narration_volume_db is not None else 3.0, replace_audio=narration_replace_audio, extend_video=True, shift_sec=0.7, video_volume_db=-3.0)
                                                except Exception:
                                                    try:
                                                        shutil.copy2(dl_video, tiktok_out)
                                                        burned_videos.append(tiktok_out)
                                                        if not _add_narr and 1 <= i <= total_eps and episode_videos[i-1] is None:
                                                            episode_videos[i-1] = tiktok_out
                                                    except Exception as e:
                                                        _report_and_ignore(e, "ignored")
                                        except Exception:
                                            try:
                                                narration_from_srt.mix_narration_into_video(dl_video, nar_audio, ep_narr_out, narration_volume_db=narration_volume_db if narration_volume_db is not None else 3.0, replace_audio=narration_replace_audio, extend_video=True, shift_sec=0.7, video_volume_db=-3.0)
                                            except Exception:
                                                try:
                                                    shutil.copy2(dl_video, tiktok_out)
                                                    burned_videos.append(tiktok_out)
                                                    if not _add_narr and 1 <= i <= total_eps and episode_videos[i-1] is None:
                                                        episode_videos[i-1] = tiktok_out
                                                except Exception as e:
                                                    _report_and_ignore(e, "ignored")
                                        narrated_videos.append(ep_narr_out)
                                    except Exception:
                                        try:
                                            shutil.copy2(dl_video, tiktok_out)
                                            burned_videos.append(tiktok_out)
                                            if not _add_narr and 1 <= i <= total_eps and episode_videos[i-1] is None:
                                                episode_videos[i-1] = tiktok_out
                                        except Exception as e:
                                            _report_and_ignore(e, "ignored")
                            except Exception as e:
                                send_discord_message(f"⚠️ Lỗi tạo thuyết minh+render cho tập {i}: {e}")
                                # fallback to normal burn-only behavior below
                                try:
                                    if not os.path.exists(dl_video):
                                        out_dl = convert_stt.download_video(ep_url, dl_video)
                                except Exception as e:
                                    try:
                                        import traceback
                                        send_discord_message(f"⚠️ process_series: error announcing split parts for group {g_idx}: {e}\n{traceback.format_exc()}")
                                    except Exception as e:
                                        _report_and_ignore(e, "ignored")
                                # To save disk, do NOT create a tiktok preview file; instead, skip creating burned preview.
                                # As a best-effort fallback, just copy the downloaded file into narrated list (no burned subtitles).
                                try:
                                    narrated_videos.append(dl_video)
                                except Exception as e:
                                    _report_and_ignore(e, "ignored")
                            try:
                                tasks_local = load_tasks()
                                tasks_local[request_id]['progress'] = 20 + int((len(srt_files) / len(unique)) * 40)
                                tasks_local[request_id].setdefault('video_file', [])
                                tasks_local[request_id]['video_file'] = downloaded
                                tasks_local[request_id].setdefault('srt_files', [])
                                tasks_local[request_id]['srt_files'] = srt_files
                                tasks_local[request_id].setdefault('burned_videos', [])
                                tasks_local[request_id]['burned_videos'] = burned_videos
                                tasks_local[request_id].setdefault('narrated_videos', [])
                                tasks_local[request_id]['narrated_videos'] = narrated_videos
                                save_tasks(tasks_local)
                            except Exception as e:
                                _report_and_ignore(e, "ignored")
                            continue

                        # If narration disabled in future and burned preview exists, include it
                        if not _add_narr and os.path.exists(tiktok_out):
                            send_discord_message(f"♻️ Đã có video burn phụ đề tập {i}: {tiktok_out} — thêm vào danh sách nối")
                            burned_videos.append(tiktok_out)
                            continue

                    # Otherwise, produce SRT and Vietnamese translation
                    # Ensure deterministic download path
                    if not os.path.exists(dl_video):
                        try:
                            out_dl = convert_stt.download_video(ep_url, dl_video)
                          
                        except Exception:
                            out_dl = None
                        if not out_dl or not os.path.exists(dl_video):
                            raise RuntimeError("Download failed")
                    downloaded.append(dl_video)

                    # Transcribe -> srt (convert_stt returns translated vi.srt when possible)
                   
                    res_srt = convert_stt.transcribe(dl_video, task_id=f"{request_id}_{i}")
                  
                    if not res_srt or not os.path.exists(res_srt):
                        send_discord_message(f"⚠️ Tạo SRT thất bại cho: {dl_video}")
                        continue

                    # move/rename SRT to deterministic vi_srt (if transcribe returned .srt, try translating)
                    try:
                        # If res_srt already a vi.srt, move
                        if res_srt.endswith('.vi.srt'):
                            os.replace(res_srt, vi_srt)
                        else:
                            # attempt to translate to vi using translate_srt_file if available
                            try:
                                api_key = os.environ.get('GEMINI_API_KEY_Translate') or os.environ.get('GOOGLE_TTS_API_KEY')
                                translated = translate_srt_file(res_srt, output_srt=vi_srt, task_id=f"{request_id}_{i}")
                                if not translated or not os.path.exists(translated):
                                    # fallback: rename original
                                    os.replace(res_srt, raw_srt)
                            except Exception:
                                os.replace(res_srt, raw_srt)
                    except Exception as e:
                        send_discord_message(f"⚠️ Lỗi khi lưu SRT: {e}")
                        continue

                    # record srt
                    if os.path.exists(vi_srt):
                        srt_files.append(vi_srt)
                    elif os.path.exists(raw_srt):
                        srt_files.append(raw_srt)

                    # Burn subtitles
                    try:
                        # Burn subtitles using ASS for better styling
                        try:
                            from convert_srt_to_ass import convert as convert_srt_to_ass_convert
                        except Exception:
                            convert_srt_to_ass_convert = None

                        use_srt = vi_srt if os.path.exists(vi_srt) else raw_srt
                        ass_path = use_srt.replace('.srt', '.ass')
                        if convert_srt_to_ass_convert:
                            convert_srt_to_ass_convert(use_srt, ass_path, 30, 11, "Noto Sans", 20, 150)
                        else:
                            try:
                                subprocess.run(["ffmpeg", "-y", "-i", use_srt, ass_path], check=True)
                            except Exception:
                                ass_path = use_srt

                        # Skip creating a TikTok-sized preview; use the original downloaded
                        # video for downstream narration/subtitle mixing to save disk and
                        # preserve original resolution. ASS file is prepared above for
                        # use during single-pass mixes.
                        sub_filter = _ffmpeg_sub_filter(ass_path)
                        tiktok_out = dl_video
                        burned_videos.append(tiktok_out)
                        # When narration is disabled globally, treat burned video as final per-episode output
                        if not _add_narr and 1 <= i <= total_eps and episode_videos[i-1] is None:
                            episode_videos[i-1] = tiktok_out
                    except Exception as e:
                        send_discord_message(f"⚠️ Burn subtitles (ASS) failed for {out_video}: {e}")
                        # Fallback: mark downloaded video as the source
                        try:
                            tiktok_out = dl_video
                            burned_videos.append(tiktok_out)
                            if not _add_narr and 1 <= i <= total_eps and episode_videos[i-1] is None:
                                episode_videos[i-1] = tiktok_out
                        except Exception as e:
                            _report_and_ignore(e, "ignored")
                    # Optional: create narration per episode and upload link
                    try:
                        if _add_narr:
                            use_srt = vi_srt if os.path.exists(vi_srt) else (raw_srt if os.path.exists(raw_srt) else None)
                            if use_srt:
                                # Store narration temp under per-title run folder to keep artifacts together
                                try:
                                    nar_dir = run_dir
                                    os.makedirs(nar_dir, exist_ok=True)
                                except Exception:
                                    nar_dir = OUTPUT_DIR
                                nar_tmp = os.path.join(nar_dir, f"{ep_label}.nar.flac")
                                # Write narration FLAC under run_dir with deterministic name
                                nar_out_flac = os.path.join(run_dir, f"{ep_label}.nar.flac")
                                # place per-line TTS pieces into a dedicated subfolder to avoid clutter
                                tts_pieces_dir = os.path.join(run_dir, "tts_pieces")
                                try:
                                    os.makedirs(tts_pieces_dir, exist_ok=True)
                                except Exception:
                                    tts_pieces_dir = run_dir

                                nar_audio, _meta = narration_from_srt.build_narration_schedule(
                                    use_srt, nar_out_flac,
                                    voice_name=narration_voice,
                                    speaking_rate=1.0,
                                    lead=0.0,
                                    meta_out=None,
                                    trim=False,
                                    rate_mode=narration_rate_dynamic,
                                    apply_fx=bool(narration_apply_fx),
                                    tmp_subdir=tts_pieces_dir
                                )
                                # Ensure FLAC path reference uses outputs
                                if nar_audio != nar_out_flac:
                                    try:
                                        shutil.copy2(nar_audio, nar_out_flac)
                                        nar_audio = nar_out_flac
                                    except Exception:
                                        nar_audio = nar_audio

                                # Attempt single-pass render: burn subtitles and mix narration
                                ep_narr_out = os.path.join(run_dir, f"{ep_label}.nar.mp4")
                                try:
                                    # prepare ASS for burn
                                    try:
                                        from convert_srt_to_ass import convert as convert_srt_to_ass_convert
                                    except Exception:
                                        convert_srt_to_ass_convert = None

                                    ass_path = use_srt.replace('.srt', '.ass')
                                    if convert_srt_to_ass_convert:
                                        try:
                                            convert_srt_to_ass_convert(use_srt, ass_path, 30, 11, "Noto Sans", 20, 150)
                                        except Exception:
                                            ass_path = use_srt
                                    else:
                                        try:
                                            subprocess.run(["ffmpeg", "-y", "-i", use_srt, ass_path], check=True)
                                        except Exception:
                                            ass_path = use_srt

                                    sub_filter = _ffmpeg_sub_filter(ass_path)
                                    narr_vol_lin = 10 ** (float(narration_volume_db) / 20.0) if narration_volume_db is not None else 10 ** (6.0/20.0)

                                    # Build filter_complex similar to earlier single-pass approach
                                    shift_ms = max(0, int(0.7 * 1000))
                                    # If narration longer than video and we are not replacing audio, extend last frame
                                    pad_sec = max(0.0, (get_media_info(nar_audio)[2] if os.path.exists(nar_audio) else 0.0) - (get_media_info(tiktok_out)[2] if os.path.exists(tiktok_out) else 0.0))
                                    need_pad_local = pad_sec > 0.01 and narration_replace_audio is False
                                    tpad_frag = f"tpad=stop_mode=clone:stop_duration={pad_sec}" if need_pad_local else ""
                                    if tpad_frag:
                                        # preserve original video size; do not force scale/pad for TikTok
                                        vchain = f"[0:v]{tpad_frag},{sub_filter}[v]"
                                    else:
                                        vchain = f"[0:v]{sub_filter}[v]"

                                    nar_chain = f"[1:a]adelay={shift_ms}|{shift_ms},volume={narr_vol_lin}[nar]"

                                    if narration_replace_audio:
                                        filter_complex = ";".join([vchain, nar_chain])
                                        cmd = ["ffmpeg", "-y", "-i", tiktok_out, "-i", nar_audio, "-filter_complex", filter_complex, "-map", "[v]", "-map", "[nar]"]
                                        cmd.extend(_preferred_video_encode_args())
                                        cmd.extend(_preferred_audio_encode_args())
                                        cmd.append(ep_narr_out)
                                    else:
                                        vid_bg_chain = f"[0:a]volume={10 ** ((-5.0)/20):.6f}[bg]"
                                        amix_chain = f"[bg][nar]amix=inputs=2:duration=longest:normalize=0[a]"
                                        filter_complex = ";".join([vchain, vid_bg_chain, nar_chain, amix_chain])
                                        cmd = ["ffmpeg", "-y", "-i", tiktok_out, "-i", nar_audio, "-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]"]
                                        cmd.extend(_preferred_video_encode_args())
                                        cmd.extend(_preferred_audio_encode_args())
                                        cmd.append(ep_narr_out)
                                    subprocess.run(cmd, check=True)
                                    narrated_videos.append(ep_narr_out)
                                    # Track final per-episode video for grouping
                                    if 1 <= i <= total_eps:
                                        episode_videos[i-1] = ep_narr_out
                                    try:
                                        rel = to_project_relative_posix(ep_narr_out)
                                        view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                                        download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                                        send_discord_message(f"🎥 Xem video tập {i} :" + view_link)
                                        send_discord_message(f"⬇️ Tải video tập  {i}:" + download_link)
                                    except Exception as e:
                                        _report_and_ignore(e, "ignored")
                                except Exception:
                                    # Fallback to previous two-step: burn then mix
                                    try:
                                        narration_from_srt.mix_narration_into_video(
                                            tiktok_out if os.path.exists(tiktok_out) else out_video,
                                            nar_audio,
                                            ep_narr_out,
                                            narration_volume_db=narration_volume_db if narration_volume_db is not None else 3.0,
                                            replace_audio=narration_replace_audio,
                                            extend_video=True,
                                            shift_sec=0.7,
                                            video_volume_db=-3.0,
                                        )
                                        narrated_videos.append(ep_narr_out)
                                        # Track final per-episode video for grouping
                                        if 1 <= i <= total_eps:
                                            episode_videos[i-1] = ep_narr_out
                                        rel = to_project_relative_posix(ep_narr_out)
                                        view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                                        download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                                        send_discord_message(f"🎥 Xem video tập {i} :" + view_link)
                                        send_discord_message(f"⬇️ Tải video tập  {i}:" + download_link)
                                    except Exception as e:
                                        send_discord_message(f"⚠️ Fallback tạo thuyết minh thất bại cho tập {i}: {e}")
                    except Exception as e:
                        send_discord_message(f"⚠️ Lỗi tạo thuyết minh cho tập {i}: {e}")

                    # update progress after each processed episode
                    try:
                        tasks_local = load_tasks()
                        tasks_local[request_id]['progress'] = 20 + int((len(srt_files) / len(unique)) * 40)
                        tasks_local[request_id].setdefault('video_file', [])
                        tasks_local[request_id]['video_file'] = downloaded
                        tasks_local[request_id].setdefault('srt_files', [])
                        tasks_local[request_id]['srt_files'] = srt_files
                        tasks_local[request_id].setdefault('burned_videos', [])
                        tasks_local[request_id]['burned_videos'] = burned_videos
                        save_tasks(tasks_local)
                    except Exception as e:
                        try:
                            import traceback
                            send_discord_message(f"⚠️ process_series: error while splitting/uploading group {g_idx}: {e}\n{traceback.format_exc()}")
                        except Exception as e:
                            _report_and_ignore(e, "ignored")
                except Exception as e:
                    try:
                        import traceback
                        tb = traceback.format_exc()
                        err_type = type(e).__name__
                        send_discord_message(f"⚠️ Bỏ qua tập do lỗi: {ep_url}: {err_type}: {e}\n{tb}")
                    except Exception:
                        send_discord_message(f"⚠️ Bỏ qua tập do lỗi: {ep_url}: {e}")
                    continue
                finally:
                    # Sau khi xử lý xong một tập, nếu toàn bộ nhóm 4–7 tập của nó
                    # đã có đủ episode_videos thì render group ngay lập tức.
                    try:
                        if not render_full and group_map:
                            g_local = ep_to_group.get(i)
                            if g_local and not group_existing.get(g_local):
                                eps_in_group = group_map.get(g_local, [])
                                grp_paths: list[str] = []
                                all_ready = True
                                for ep_idx in eps_in_group:
                                    arr_idx = ep_idx - 1
                                    if arr_idx < 0 or arr_idx >= len(episode_videos):
                                        all_ready = False
                                        break
                                    vpath = episode_videos[arr_idx]
                                    if not vpath or not os.path.exists(vpath):
                                        all_ready = False
                                        break
                                    grp_paths.append(vpath)
                                if all_ready and grp_paths:
                                    group_out_path = os.path.join(final_dir, f"{base_title_val}_Tap_{g_local}.mp4")
                                    _render_group_batch([(g_local, grp_paths, group_out_path)])
                                    try:
                                        group_existing[g_local] = True
                                        rendered_groups_this_run.add(g_local)
                                    except Exception:
                                        pass
                    except Exception as _e:
                        _report_and_ignore(_e, "ignored")

            # 4) Concatenate episodes into groups.
            # For non-full mode, we use fixed 4-episode groups based on episode index
            # and skip any group that already has a rendered output on disk.

            # Build list of groups to render (any groups chưa render trong quá trình loop sẽ được xử lý ở đây).
            groups_to_render: list[tuple[int, list[str], str]] = []  # (group_index, files, output_path)

            if render_full:
                # FULL mode: concatenate all successful episode videos into a single file.
                # Prefer episode_videos if available; otherwise fall back to previous behaviour.
                full_sources = [v for v in episode_videos if v]
                if not full_sources:
                    full_sources = narrated_videos if narrated_videos else (burned_videos if burned_videos else downloaded)
                if not full_sources:
                    send_discord_message("❌ Không có video nào được tải thành công. Kết thúc.")
                    tasks_local = load_tasks(); tasks_local[request_id]['status'] = 'error'; tasks_local[request_id]['error'] = 'No downloaded videos'; tasks_local[request_id]['progress'] = 0; save_tasks(tasks_local)
                    return
                group_out = os.path.join(final_dir, f"{base_title_val}_FULL.mp4")
                groups_to_render.append((1, full_sources, group_out))
            else:
                # Non-full: 4–7 episode groups based on episode index (same logic as original implementation).
                if not group_map:
                    send_discord_message("❌ Không có tập hợp lệ nào để group. Kết thúc.")
                    tasks_local = load_tasks(); tasks_local[request_id]['status'] = 'error'; tasks_local[request_id]['error'] = 'No episodes to group'; tasks_local[request_id]['progress'] = 0; save_tasks(tasks_local)
                    return

                for g_idx, eps in sorted(group_map.items()):
                    # If a group already existed on disk before this run, collect existing files
                    # and skip rendering. If the group was rendered earlier during this run,
                    # it will be tracked in `rendered_groups_this_run` and should be skipped
                    # to avoid duplicate rendering.
                    if group_existing.get(g_idx):
                        if g_idx in rendered_groups_this_run:
                            try:
                                send_discord_message(f"♻️ Nhóm {g_idx} đã render trong run hiện tại, bỏ qua render.")
                            except Exception:
                                pass
                            continue
                        try:
                            send_discord_message(f"♻️ Nhóm {g_idx} đã có video group, bỏ qua render.")
                            prefixes = [
                                os.path.join(run_dir, f"{base_title_val}_Tap_{g_idx}"),
                                os.path.join(final_dir, f"{base_title_val}_Tap_{g_idx}"),
                            ]
                            existing: list[str] = []
                            for pref in prefixes:
                                for pat in (pref + ".mp4", pref + "_P*.mp4"):
                                    try:
                                        for p in glob.glob(pat):
                                            if os.path.isfile(p):
                                                existing.append(p)
                                    except Exception:
                                        continue
                            if existing:
                                final_files.extend(sorted(set(existing)))
                        except Exception as e:
                            _report_and_ignore(e, "ignored")
                        continue

                    grp: list[str] = []
                    for ep_idx in eps:
                        arr_idx = ep_idx - 1
                        if 0 <= arr_idx < len(episode_videos):
                            vpath = episode_videos[arr_idx]
                            if vpath and os.path.exists(vpath):
                                grp.append(vpath)
                    if not grp:
                        # Nothing to concatenate for this group (all episodes failed/absent)
                        continue
                    group_out = os.path.join(final_dir, f"{base_title_val}_Tap_{g_idx}.mp4")
                    groups_to_render.append((g_idx, grp, group_out))

            # Concatenate each group separately and add a short title overlay indicating starting episode
            try:
                if should_abort_sync(request_id):
                    try:
                        tasks_local = load_tasks()
                        if request_id in tasks_local:
                            tasks_local[request_id]['status'] = 'cancelled'
                            tasks_local[request_id]['progress'] = 0
                            save_tasks(tasks_local)
                    except Exception:
                        pass
                    send_discord_message(f"⛔ process_series cancelled before group render: {request_id}")
                else:
                    if groups_to_render:
                        _render_group_batch(groups_to_render)
            except Exception:
                # ensure group render errors don't crash the entire run
                _report_and_ignore(Exception('group render stage failed'), 'ignored')
            # 6) Apply naming rules
            named_outputs = []
            # Compute total duration across final files (best-effort)
            total_dur = 0
            try:
                for fpath in final_files:
                    try:
                        _, _, d = get_media_info(fpath)
                        total_dur += d or 0
                    except Exception:
                        total_dur += 0
            except Exception:
                total_dur = None

            # Keep final output filenames as-produced; do NOT rename here so external
            # sandbox download URLs that use the file path remain valid.
            named_outputs = final_files

            # finalize task
            try:
                tasks_local = load_tasks()
                tasks_local[request_id]['status'] = 'completed'
                tasks_local[request_id]['progress'] = 100
                tasks_local[request_id]['video_file'] = named_outputs
                tasks_local[request_id]['video_path'] = named_outputs[0] if named_outputs else ''
                save_tasks(tasks_local)
            except Exception as e:
                _report_and_ignore(e, "ignored")
            # Also send collected per-episode links (if any)
            if episode_links:
                try:
                    tasks_local = load_tasks(); tasks_local[request_id]['episode_links'] = episode_links; save_tasks(tasks_local)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
            send_discord_message(f"✅ process_series completed: {title}, tổng thời lượng khoảng {int(total_dur/60)} phút.")
            for idx, f in enumerate(named_outputs, start=1):
                rel = to_project_relative_posix(f)
                view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                send_discord_message(f"🎥 Xem video (Tập {idx}): " + view_link)
                send_discord_message(f"⬇️ Tải video (Tập {idx}): " + download_link)
          
        except Exception as e:
            send_discord_message(f"❌ process_series error: {e}")
            try:
                tasks_local = load_tasks(); tasks_local[request_id]['status'] = 'error'; tasks_local[request_id]['error'] = str(e); tasks_local[request_id]['progress'] = 0; save_tasks(tasks_local)
            except Exception as e:
                _report_and_ignore(e, "ignored")
    loop = asyncio.get_event_loop()
    try:
        tasks_local = load_tasks()
        if request_id in tasks_local:
            tasks_local[request_id]['status'] = 'running'
            save_tasks(tasks_local)
    except Exception:
        pass

    # Run the synchronous worker inside a tracked asyncio Task (thread wrapper)
    tracked = create_tracked_task(request_id, asyncio.to_thread(_worker))
    if run_in_background:
        return JSONResponse(status_code=202, content={"task_id": request_id, "started": True})
    else:
        try:
            await tracked
            return JSONResponse(status_code=200, content={"task_id": request_id, "completed": True})
        except asyncio.CancelledError:
            return JSONResponse(status_code=400, content={"task_id": request_id, "cancelled": True})


@app.post('/process_series_episodes', response_class=JSONResponse)
async def process_series_episodes(
    start_url: str = Query(..., description='URL tập 1 của series (ví dụ: https://v.qq.com/x/cover/dat-cid/data-vid.html)'),
    title: str = Query('', description='Tiêu đề tổng thể (tùy chọn)'),
    episodes: str | None = Query(None, description='1-5 là từ tập 1 đến tập 5'),
    max_episodes: int = Query(0, description='Số tập tối đa để xử lý (0 = tất cả)'),
    final_filename: str | None = Query(None, description='Tên file cuối cùng (ví dụ: MySeries_Full.mp4) - nếu cung cấp sẽ dùng thay cho tên mặc định'),
    overlay_title: str | None = Query(None, description='Tiêu đề overlay dùng cho video cuối (nếu trống sẽ dùng `title`)'),
    run_in_background: bool = Query(True, description='Nếu True thì chạy nền và trả về ngay (recommended)'),
    add_narration: bool = Query(False, description='Nếu True, tạo thuyết minh từ phụ đề và trộn vào video'),
    with_subtitles: bool = Query(True, description='Nếu True thì burn phụ đề vào video final; nếu False chỉ thêm thuyết minh không burn phụ đề'),
    render_full: bool = Query(True, description='If True concatenate all episodes into a single [FULL] video instead of grouping by 4'),
    narration_voice: str = Query('vi-VN-Standard-C', description='Giọng Google TTS'),
    narration_replace_audio: bool = Query(False, description='Thay hoàn toàn audio gốc bằng thuyết minh'),
    narration_volume_db: float = Query(-4.0, description='Âm lượng thuyết minh khi trộn (dB)'),
    narration_enabled: bool | None = Query(None, description='Bật/tắt việc tạo TTS thuyết minh (ưu tiên tham số này nếu được truyền)'),
    narration_rate_dynamic: int = Query(0, description='1: dùng tốc độ nói động (1.28–1.40), 0: cố định 1.0'),
    narration_apply_fx: int = Query(1, description='1: áp EQ/tone/time filter cho giọng thuyết minh')
):
    """Download a sequence of episode pages starting from `start_url`, create subtitles for each
    episode (attempt via `whisper` CLI if available), then concatenate into a full video and
    split into parts of max 3600s if needed.

    Naming rules:
    - If `title` provided and the full video is >60min, final filename becomes "[full] {title}.mp4".
    - Otherwise parts are named "{title} P1.mp4", "{title} Phần 2.mp4", etc.
    """
    narration_volume_db = 8.0
    request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    ep_list = episodes.split('-') if episodes else []
    min_episode = int(ep_list[0]) if ep_list else None
    max_episode = int(ep_list[1]) if len(ep_list) > 1 else None
    def _worker():
        import requests, re, urllib.parse, subprocess, time
        try:
            send_discord_message(f"🔁 process_series start: {start_url} (task {request_id})")

            # Work with a mutable copy to avoid Python local variable scoping issues
            current_url = start_url

            # Normalize m.v.qq.com: prefer canonical cid/vid → desktop URL; else follow redirects
         

            # Determine whether to generate narration per episode.
            # Priority: explicit `narration_enabled` (if not None) -> `add_narration` -> default True
            try:
                if narration_enabled is not None:
                    _add_narr = bool(narration_enabled)
                else:
                    # `add_narration` is a query param (bool), prefer it if provided, otherwise default True
                    _add_narr = bool(add_narration) if add_narration is not None else True
            except Exception:
                _add_narr = True

            # create task entry
            try:
                tasks_local = load_tasks()
            except Exception:
                tasks_local = {}
            tasks_local[request_id] = {
                "task_id": request_id,
                # Mark as pending but flagged to skip the generic worker queue
                "status": "pending",
                "progress": 0,
                "video_path": "",
                "video_file": [],
                "title": title,
                "request_urls": [start_url],
                "created_at": time.time(),
                "type": 8,
                "task_type": "series",
                "skip_queue": True,
                "add_narration": _add_narr,
                "narration_voice": narration_voice,
                "narration_replace_audio": narration_replace_audio,
                "narration_volume_db": narration_volume_db,
                "narration_rate_dynamic": narration_rate_dynamic,
                "narration_apply_fx": narration_apply_fx
                ,"render_full": render_full
            }
            try:
                save_tasks(tasks_local)
            except Exception as e:
                _report_and_ignore(e, "ignored")
            # Build episode list robustly: prefer Playwright extraction; fallback to regex
            unique = []
            playlist_eps = []
            # Prefer Playwright helper if available
            try:
                from qq_playlist import get_episode_links
                send_discord_message("🧭 Dùng Playwright (headless) để lấy danh sách tập...")
                # Try up to 3 times with higher timeout/slow_mo to handle slow JS or anti-bot
                playlist_eps = []
                for attempt in range(3):
                    try:
                        send_discord_message(f"🔁 Lấy danh sách tập (try {attempt+1}/3)")
                        playlist_eps = get_episode_links(current_url, headless=True, slow_mo=300, timeout_ms=120000)
                        if playlist_eps:
                            break
                    except Exception as e_attempt:
                        send_discord_message(f"⚠️ get_episode_links thất bại (try {attempt+1}/3): {e_attempt}")
                        time.sleep(1 + attempt*2)
                if not playlist_eps:
                    send_discord_message("ℹ️ Playwright không trả về tập nào, fallback regex")
            except Exception as e:
                send_discord_message(f"ℹ️ Playwright không khả dụng, fallback regex: {e}")
           
            unique = playlist_eps
            # Remove the album URL itself if it is not an episode link
            unique = [u for u in unique if re.search(r"/x/cover/[^/]+/[^/]+\.html", u)]
            # Ensure deterministic ordering and dedupe
            seen = set()
            ordered = []
            for u in unique:
                if u not in seen:
                    seen.add(u)
                    ordered.append(u)
            unique = ordered

            if max_episodes:
                unique = unique[:max_episodes]

            if not unique:
                send_discord_message(f"⚠️ Không tìm thấy tập nào từ URL: {start_url}")
                tasks_local = load_tasks(); tasks_local[request_id]['status'] = 'error'; tasks_local[request_id]['error'] = 'No episodes found'; tasks_local[request_id]['progress'] = 0; save_tasks(tasks_local)
                return

            # update progress
            tasks_local = load_tasks(); tasks_local[request_id]['progress'] = 10; save_tasks(tasks_local)

            downloaded = []
            srt_files = []
            burned_videos = []
            narrated_videos = []
            episode_links = []
            # Base title for naming temp/component files (no URL hash)
            try:
                base_title_val = safe_filename(title) if title else 'series'
            except Exception:
                base_title_val = 'series'

            # Create per-title run directory to store all episode artifacts and temps
            try:
                run_root = os.path.join(OUTPUT_DIR, base_title_val)
                os.makedirs(run_root, exist_ok=True)
                # Use a persistent run folder per title (do NOT include request_id)
                run_dir = run_root
            except Exception:
                run_dir = OUTPUT_DIR

            # metadata index to allow reuse of generated pieces (srt, vi.srt, tts parts, narration)
            index_path = os.path.join(run_dir, "index.json")
            try:
                import json
                if os.path.exists(index_path):
                    with open(index_path, 'r', encoding='utf-8') as f:
                        meta_index = json.load(f)
                else:
                    meta_index = {"title": title, "request_id": request_id, "episodes": {}}
                    with open(index_path, 'w', encoding='utf-8') as f:
                        json.dump(meta_index, f, ensure_ascii=False, indent=2)
            except Exception:
                meta_index = {"episodes": {}}
            # Helper: build ffmpeg subtitles filter compatible with Windows paths
            def _ffmpeg_sub_filter(ass_path: str) -> str:
                try:
                    from pathlib import Path
                    p = Path(ass_path).resolve().as_posix()
                    p = p.replace(":", r"\:")
                    return f"subtitles=filename='{p}'"
                except Exception:
                    # Fallback to naive escaping
                    subtitle_input_escaped = ass_path.replace("'", "\\'").replace(":", r"\:")
                    return f"subtitles='{subtitle_input_escaped}'"

            # 2) For each episode, use convert_stt flow: download -> transcribe -> burn subtitles
         

            for i, ep_url in enumerate(unique, start=min_episode if min_episode is not None else 1):
                if max_episode is not None and i > max_episode:
                    break
                send_discord_message(f"⬇️ [{i}/{len(unique)}] Xử lý: {ep_url}")
                try:
                    # Per-episode force-rebuild flag: set True when we delete artefacts
                    force_rebuild = False
                    # Deterministic filenames based on provided title and episode index (no hash)
                    ep_label = f"{base_title_val}_Tap_{i}"
                    out_video = os.path.join(run_dir, f"{ep_label}.mp4")
                    # download filename should be distinct to avoid colliding with group/final names
                    dl_video = os.path.join(run_dir, f"{ep_label}_download.mp4")
                    vi_srt = os.path.join(run_dir, f"{ep_label}.vi.srt")
                    raw_srt = os.path.join(run_dir, f"{ep_label}_download.srt")
                    tiktok_out = os.path.join(run_dir, f"{ep_label}.tiktok.mp4")
                    # If a narrated episode output already exists from a previous run, reuse it
                    try:
                        prebuilt_narr = os.path.join(run_dir, f"{ep_label}.nar.mp4")
                        if os.path.exists(prebuilt_narr) :
                            # If an SRT exists and contains flagged keywords, treat the episode
                            # as not successfully processed: remove artefacts and force full reprocess.
                            try:
                                srt_to_check = None
                                if os.path.exists(vi_srt):
                                    srt_to_check = vi_srt
                                elif os.path.exists(raw_srt):
                                    srt_to_check = raw_srt

                                if srt_to_check and convert_stt._srt_contains_keywords(srt_to_check):
                                    send_discord_message(f"♻️ Phát hiện phụ đề lỗi cho {ep_label}; xóa artefact để tạo lại từ đầu")
                                    try:
                                        # Remove final video/audio artifacts to force rebuild
                                        cand_remove = [prebuilt_narr, os.path.join(run_dir, f"{ep_label}.nar.flac"), os.path.join(run_dir, f"{ep_label}.schedule.json")]
                                        for p in cand_remove:
                                            try:
                                                if p and os.path.exists(p):
                                                    os.remove(p)
                                            except Exception as _e:
                                                _report_and_ignore(_e, "ignored")
                                        # mark that we removed artifacts and must rebuild
                                        force_rebuild = True

                                        # Remove per-line TTS pieces under tts_pieces (common patterns)
                                        try:
                                            import glob
                                            tts_patterns = [
                                                os.path.join(run_dir, "tts_pieces", "tts", f"{ep_label}.vi_tts.*"),
                                                os.path.join(run_dir, "tts_pieces", f"{ep_label}*"),
                                                os.path.join(run_dir, "tts_pieces", "**", f"{ep_label}*"),
                                            ]
                                            found = []
                                            for pat in tts_patterns:
                                                try:
                                                    found.extend(glob.glob(pat, recursive=True))
                                                except Exception:
                                                    continue
                                            for fpath in set(found):
                                                try:
                                                    if os.path.exists(fpath):
                                                        os.remove(fpath)
                                                except Exception as _e:
                                                    _report_and_ignore(_e, "ignored")
                                        except Exception as _e:
                                            _report_and_ignore(_e, "ignored")

                                        # Remove the SRT files themselves so the pipeline will re-transcribe
                                        for s in (vi_srt, raw_srt):
                                            try:
                                                if s and os.path.exists(s):
                                                    os.remove(s)
                                            except Exception as _e:
                                                _report_and_ignore(_e, "ignored")
                                    except Exception as _e:
                                        _report_and_ignore(_e, "ignored")
                                    # Do NOT continue here; allow normal processing below to re-generate SRT/narration
                                else:
                                    send_discord_message(f"♻️ Đã có video thuyết minh tập {i}: {prebuilt_narr} — thêm vào danh sách nối")
                                    narrated_videos.append(prebuilt_narr)
                                    try:
                                        rel = to_project_relative_posix(prebuilt_narr)
                                        view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                                        download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                                        send_discord_message(f"🎥 Xem video tập {i} :" + view_link)
                                        send_discord_message(f"⬇️ Tải video tập  {i}:" + download_link)
                                    except Exception as e:
                                        _report_and_ignore(e, "ignored")
                                    # Track progress artifacts for visibility
                                    if os.path.exists(vi_srt):
                                        srt_files.append(vi_srt)
                                    if os.path.exists(tiktok_out):
                                        burned_videos.append(tiktok_out)
                                    if os.path.exists(dl_video):
                                        downloaded.append(dl_video)
                                    try:
                                        tasks_local = load_tasks()
                                        tasks_local[request_id]['progress'] = 20 + int((len(srt_files) / len(unique)) * 40)
                                        tasks_local[request_id].setdefault('video_file', [])
                                        tasks_local[request_id]['video_file'] = downloaded
                                        tasks_local[request_id].setdefault('srt_files', [])
                                        tasks_local[request_id]['srt_files'] = srt_files
                                        tasks_local[request_id].setdefault('burned_videos', [])
                                        tasks_local[request_id]['burned_videos'] = burned_videos
                                        tasks_local[request_id].setdefault('narrated_videos', [])
                                        tasks_local[request_id]['narrated_videos'] = narrated_videos
                                        save_tasks(tasks_local)
                                    except Exception as e:
                                        _report_and_ignore(e, "ignored")
                                    # Skip expensive reprocessing for this episode (only when not flagged)
                                    continue
                            except Exception as e:
                                _report_and_ignore(e, "ignored")
                            if not force_rebuild:
                                try:
                                    rel = to_project_relative_posix(prebuilt_narr)
                                    view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                                    download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                                    send_discord_message(f"🎥 Xem video tập {i} :" + view_link)
                                    send_discord_message(f"⬇️ Tải video tập  {i}:" + download_link)
                                except Exception as e:
                                    _report_and_ignore(e, "ignored")
                                # Track progress artifacts for visibility
                                if os.path.exists(vi_srt):
                                    srt_files.append(vi_srt)
                                if os.path.exists(tiktok_out):
                                    burned_videos.append(tiktok_out)
                                if os.path.exists(dl_video):
                                    downloaded.append(dl_video)
                                try:
                                    tasks_local = load_tasks()
                                    tasks_local[request_id]['progress'] = 20 + int((len(srt_files) / len(unique)) * 40)
                                    tasks_local[request_id].setdefault('video_file', [])
                                    tasks_local[request_id]['video_file'] = downloaded
                                    tasks_local[request_id].setdefault('srt_files', [])
                                    tasks_local[request_id]['srt_files'] = srt_files
                                    tasks_local[request_id].setdefault('burned_videos', [])
                                    tasks_local[request_id]['burned_videos'] = burned_videos
                                    tasks_local[request_id].setdefault('narrated_videos', [])
                                    tasks_local[request_id]['narrated_videos'] = narrated_videos
                                    save_tasks(tasks_local)
                                except Exception as e:
                                    _report_and_ignore(e, "ignored")
                                # Skip expensive reprocessing for this episode
                                continue
                        # If narration disabled in future and burned preview exists, include it
                        # Only reuse burned preview when we're NOT forcing a rebuild
                        if not _add_narr and os.path.exists(tiktok_out) and not force_rebuild:
                            send_discord_message(f"♻️ Đã có video burn phụ đề tập {i}: {tiktok_out} — thêm vào danh sách nối")
                            burned_videos.append(tiktok_out)
                            continue
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
                    # Integrity check: if an SRT exists (vi or raw) but may be flagged,
                    # remove it so the pipeline will re-transcribe and re-generate narration.
                    try:
                        srt_to_check = None
                        if os.path.exists(vi_srt):
                            srt_to_check = vi_srt
                        elif os.path.exists(raw_srt):
                            srt_to_check = raw_srt

                        if srt_to_check:
                            try:
                                if convert_stt._srt_contains_keywords(srt_to_check):
                                    send_discord_message(f"♻️ Phát hiện phụ đề lỗi cho {ep_label}; sẽ xóa SRT để tạo lại từ đầu: {srt_to_check}")
                                    # remove the SRT and any associated artifacts
                                    try:
                                        if os.path.exists(srt_to_check):
                                            os.remove(srt_to_check)
                                    except Exception as _e:
                                        _report_and_ignore(_e, "ignored")
                                    # remove per-line TTS pieces for this episode
                                    try:
                                        import glob
                                        tts_patterns = [
                                            os.path.join(run_dir, "tts_pieces", "tts", f"{ep_label}.vi_tts.*"),
                                            os.path.join(run_dir, "tts_pieces", f"{ep_label}*"),
                                            os.path.join(run_dir, "tts_pieces", "**", f"{ep_label}*"),
                                        ]
                                        found = []
                                        for pat in tts_patterns:
                                            try:
                                                found.extend(glob.glob(pat, recursive=True))
                                            except Exception:
                                                continue
                                        for fpath in set(found):
                                            try:
                                                if os.path.exists(fpath):
                                                    os.remove(fpath)
                                            except Exception as _e:
                                                _report_and_ignore(_e, "ignored")
                                    except Exception as _e:
                                        _report_and_ignore(_e, "ignored")
                                    # also remove any existing narration pieces to avoid reuse
                                    try:
                                        for p in (os.path.join(run_dir, f"{ep_label}.nar.flac"), os.path.join(run_dir, f"{ep_label}.schedule.json")):
                                            try:
                                                if p and os.path.exists(p):
                                                    os.remove(p)
                                            except Exception as _e:
                                                _report_and_ignore(_e, "ignored")
                                    except Exception:
                                        pass
                                        # ensure the loop will rebuild this episode
                                        force_rebuild = True
                                    # fall through to the normal transcription path (do not `continue`)
                            except Exception as _e:
                                _report_and_ignore(_e, "ignored")
                    except Exception:
                        pass

                    # If Vietnamese SRT already exists, skip transcription step
                    if os.path.exists(vi_srt):
                        send_discord_message(f"♻️ Đã có phụ đề tiếng Việt: {vi_srt} — bỏ qua tạo lại SRT")
                        srt_files.append(vi_srt)

                        # If narration requested, generate narration first then render
                        if _add_narr:
                            # ensure video file exists locally
                            if not os.path.exists(dl_video):
                                send_discord_message(f"⬇️ Tải video vì thiếu file local để burn+nar: {ep_url}")
                                try:
                                    out_dl = convert_stt.download_video(ep_url, dl_video)
                                except Exception:
                                    out_dl = None
                                if not out_dl:
                                    send_discord_message(f"⚠️ Không thể tải video để burn+nar: {ep_url}")
                                    continue

                            # Prepare ASS from SRT only if subtitles requested
                            ass_path = None
                            try:
                                convert_srt_to_ass_convert = None
                                if with_subtitles:
                                    try:
                                        from convert_srt_to_ass import convert as convert_srt_to_ass_convert
                                    except Exception:
                                        convert_srt_to_ass_convert = None

                                    ass_path = vi_srt.replace('.srt', '.ass')
                                    if convert_srt_to_ass_convert:
                                        try:
                                            convert_srt_to_ass_convert(vi_srt, ass_path, 30, 11, "Noto Sans", 20, 150)
                                        except Exception:
                                            ass_path = vi_srt
                                    else:
                                        try:
                                            subprocess.run(["ffmpeg", "-y", "-i", vi_srt, ass_path], check=True)
                                        except Exception:
                                            ass_path = vi_srt
                                else:
                                    # subtitles disabled for this run; keep ass_path None
                                    ass_path = None
                            except Exception:
                                ass_path = None

                            # Build narration audio (schedule) and then run a single ffmpeg pass
                            try:
                                # Reuse existing narration if available
                                nar_out_flac = os.path.join(run_dir, f"{ep_label}.nar.flac")
                                ep_narr_out = os.path.join(run_dir, f"{ep_label}.nar.mp4")
                                # If final narrated video already exists, reuse it
                                # Do not reuse when forcing rebuild
                                if os.path.exists(ep_narr_out) and not force_rebuild:
                                    narrated_videos.append(ep_narr_out)
                                    # update index
                                    try:
                                        meta_index.setdefault('episodes', {})
                                        meta_index['episodes'][ep_label] = meta_index['episodes'].get(ep_label, {})
                                        meta_index['episodes'][ep_label].update({'nar_video': ep_narr_out})
                                        with open(index_path, 'w', encoding='utf-8') as f:
                                            json.dump(meta_index, f, ensure_ascii=False, indent=2)
                                    except Exception as e:
                                        try:
                                            import traceback
                                            send_discord_message(f"⚠️ process_series: error writing index for {ep_label}: {e}\n{traceback.format_exc()}")
                                        except Exception as e:
                                            _report_and_ignore(e, "ignored")
                                    continue
                                # If final narration audio exists, mix into video without regenerating TTS
                                # Do not reuse when forcing rebuild
                                if os.path.exists(nar_out_flac) and not force_rebuild:
                                    try:
                                        src_for_mix = dl_video
                                        # Do not pre-burn subtitles to a temp file; let the single-pass helper handle burning.
                                      

                                            # Single-pass: burn ASS + mix prebuilt narration (centralized helper)
                                        try:
                                            burn_and_mix_narration(src_for_mix, ass_path, nar_out_flac, ep_narr_out, replace_audio=narration_replace_audio, narration_volume_db=narration_volume_db, shift_sec=0.7, with_subtitles=with_subtitles)
                                        except Exception:
                                            try:
                                                narration_from_srt.mix_narration_into_video(src_for_mix, nar_out_flac, ep_narr_out, narration_volume_db=narration_volume_db if narration_volume_db is not None else 3.0, replace_audio=narration_replace_audio, extend_video=True, shift_sec=0.7, video_volume_db=-3.0)
                                            except Exception as e:
                                                try:
                                                    import traceback
                                                    send_discord_message(f"⚠️ process_series: failed to publish episode links for {ep_label}: {e}\n{traceback.format_exc()}")
                                                except Exception as e:
                                                    _report_and_ignore(e, "ignored")
                                        if os.path.exists(ep_narr_out):
                                            narrated_videos.append(ep_narr_out)
                                            try:
                                                meta_index.setdefault('episodes', {})
                                                meta_index['episodes'][ep_label] = meta_index['episodes'].get(ep_label, {})
                                                meta_index['episodes'][ep_label].update({'nar_audio': nar_out_flac, 'nar_video': ep_narr_out})
                                                with open(index_path, 'w', encoding='utf-8') as f:
                                                    json.dump(meta_index, f, ensure_ascii=False, indent=2)
                                                send_discord_message(f"🎥 Xong video thuyết minh tập {i}: {ep_narr_out}")
                                                sandbox_rel = to_project_relative_posix(ep_narr_out)
                                                view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(sandbox_rel)
                                                download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(sandbox_rel)
                                                send_discord_message(f"🎥 Xem video tập {i} :" + view_link)
                                                send_discord_message(f"⬇️ Tải video tập {i} :" + download_link)
                                            except Exception as e:
                                                _report_and_ignore(e, "process_series: mix fallback inner")
                                            continue
                                    except Exception as e:
                                        try:
                                            import traceback
                                            send_discord_message(f"⚠️ process_series: failed to publish episode links for {ep_label}: {e}\n{traceback.format_exc()}")
                                        except Exception as e:
                                            _report_and_ignore(e, "process_series: update index (inner)")
                                # Otherwise, look for existing TTS pieces to concatenate and reuse
                                tts_pieces_dir = os.path.join(run_dir, "tts_pieces")
                                try:
                                    import glob
                                    # search common piece patterns inside run_dir and subfolders
                                    patterns = [
                                        os.path.join(run_dir, f"norm_{ep_label}_*.flac"),
                                        
                                    ]
                                    pieces = []
                                    for p in patterns:
                                        pieces.extend(sorted(glob.glob(p)))
                                    # also search recursively under run_dir
                                    for root, dirs, files in os.walk(run_dir):
                                        for fn in files:
                                            if fn.endswith('.flac') and (fn.startswith('piece_') or fn.startswith('tts_') or fn.startswith('fit_') or fn.startswith(f"{ep_label}")):
                                                pieces.append(os.path.join(root, fn))
                                    pieces = sorted(set(pieces))
                                    # Only reuse pieces when not forcing a rebuild
                                    if pieces and not force_rebuild:
                                        # assemble into final nar_out_flac
                                        try:
                                            nar_audio, _meta = narration_from_srt.build_narration_schedule(
                                                vi_srt, nar_out_flac,
                                                voice_name=narration_voice,
                                                speaking_rate=1.0,
                                                lead=0.0,
                                                meta_out=os.path.join(run_dir, f"{ep_label}.schedule.json"),
                                                trim=False,
                                                rate_mode=narration_rate_dynamic,
                                                apply_fx=bool(narration_apply_fx),
                                                tmp_subdir=tts_pieces_dir
                                            )
                                            if os.path.exists(nar_out_flac):
                                                try:
                                                    src_for_mix = dl_video
                                                    
                                                    # Single-pass: burn subtitles (ASS) + mix prebuilt narration audio
                                                    try:
                                                        burn_and_mix_narration(src_for_mix, ass_path, nar_out_flac, ep_narr_out, replace_audio=narration_replace_audio, narration_volume_db=narration_volume_db, shift_sec=0.7, with_subtitles=with_subtitles)
                                                    except Exception:
                                                        try:
                                                            narration_from_srt.mix_narration_into_video(src_for_mix, nar_out_flac, ep_narr_out, narration_volume_db=narration_volume_db if narration_volume_db is not None else 3.0, replace_audio=narration_replace_audio, extend_video=True, shift_sec=0.7, video_volume_db=-3.0)
                                                        except Exception as e:
                                                            _report_and_ignore(e, "ignored")
                                                except Exception as e:
                                                    _report_and_ignore(e, "ignored")
                                                if os.path.exists(ep_narr_out):
                                                    narrated_videos.append(ep_narr_out)
                                                    if 1 <= i <= total_eps:
                                                        episode_videos[i-1] = ep_narr_out
                                                    try:
                                                        meta_index.setdefault('episodes', {})
                                                        meta_index['episodes'][ep_label] = meta_index['episodes'].get(ep_label, {})
                                                        meta_index['episodes'][ep_label].update({'nar_audio': nar_out_flac, 'nar_video': ep_narr_out})
                                                        with open(index_path, 'w', encoding='utf-8') as f:
                                                            json.dump(meta_index, f, ensure_ascii=False, indent=2)
                                                        sandbox_rel = to_project_relative_posix(ep_narr_out)
                                                        view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(sandbox_rel)
                                                        download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(sandbox_rel)
                                                        send_discord_message(f"🎥 Xem video tập {i} :" + view_link)
                                                        send_discord_message(f"⬇️ Tải video tập {i} :" + download_link)
                                                    except Exception as e:
                                                        _report_and_ignore(e, "ignored")
                                                    continue
                                        except Exception as e:
                                            _report_and_ignore(e, "process_series: pieces concat attempt")
                                except Exception as e:
                                    _report_and_ignore(e, "ignored")
                                # If we reach here, no reusable narration found — proceed to build normally
                                nar_audio, _meta = (None, None)
                                nar_out_flac = os.path.join(run_dir, f"{ep_label}.nar.flac")
                                # place per-line TTS pieces into a dedicated subfolder to avoid clutter
                              
                                try:
                                    os.makedirs(tts_pieces_dir, exist_ok=True)
                                except Exception:
                                    tts_pieces_dir = run_dir

                                nar_audio, _meta = narration_from_srt.build_narration_schedule(
                                    vi_srt, nar_out_flac,
                                    voice_name=narration_voice,
                                    speaking_rate=1.0,
                                    lead=0.0,
                                    meta_out=os.path.join(run_dir, f"{ep_label}.schedule.json"),
                                    trim=False,
                                    rate_mode=narration_rate_dynamic,
                                    apply_fx=bool(narration_apply_fx),
                                    tmp_subdir=tts_pieces_dir
                                )
                                # ensure ep_narr_out path set
                                ep_narr_out = os.path.join(run_dir, f"{ep_label}.nar.mp4")
                                

                                # Build ffmpeg filter_complex to burn subtitles and mix narration
                                sub_filter = ''
                                if with_subtitles and ass_path:
                                    try:
                                        sub_filter = _ffmpeg_sub_filter(ass_path)
                                    except Exception:
                                        sub_filter = ''
                                narr_vol_lin = 10 ** (float(narration_volume_db) / 20.0) if narration_volume_db is not None else 10 ** (6.0/20.0)

                                # Determine durations
                                vid_dur = None
                                try:
                                    vid_dur = get_media_info(dl_video)[2]
                                except Exception:
                                    vid_dur = None
                                try:
                                    nar_dur = get_media_info(nar_audio)[2] if os.path.exists(nar_audio) else 0.0
                                except Exception:
                                    nar_dur = 0.0
                                pad_sec = max(0.0, nar_dur - (vid_dur or 0.0))
                                need_pad = pad_sec > 0.01 and narration_replace_audio is False

                                # Compose filter_complex
                                # If narration longer than video and we are not replacing audio, extend last frame
                                tpad_frag = f"tpad=stop_mode=clone:stop_duration={pad_sec}" if need_pad else ""
                                # Place tpad before burning subtitles so ASS timing still applies
                                # Keep original video resolution: do NOT scale/pad/setsar the downloaded video.
                                if with_subtitles and sub_filter:
                                    if tpad_frag:
                                        vchain = f"[0:v]{tpad_frag},{sub_filter}[v]"
                                    else:
                                        vchain = f"[0:v]{sub_filter}[v]"
                                else:
                                    # No subtitle filter: just pass through video (optionally padded)
                                    if tpad_frag:
                                        vchain = f"[0:v]{tpad_frag},setpts=PTS[v]"
                                    else:
                                        vchain = "[0:v]setpts=PTS[v]"

                                # narration: input 1
                                shift_ms = max(0, int(0.7 * 1000))
                                nar_chain = f"[1:a]adelay={shift_ms}|{shift_ms},volume={narr_vol_lin}[nar]"

                                if narration_replace_audio:
                                    # Replace original audio with narration (no background mix)
                                    filter_complex = ";".join([vchain, nar_chain])
                                    cmd = ["ffmpeg", "-y", "-i", dl_video, "-i", nar_audio, "-filter_complex", filter_complex, "-map", "[v]", "-map", "[nar]"]
                                    cmd.extend(_preferred_video_encode_args())
                                    cmd.extend(_preferred_audio_encode_args())
                                    cmd.append(ep_narr_out)
                                else:
                                    # background audio (attenuated) + narration mixed; use duration=longest
                                    vid_bg_chain = f"[0:a]volume={10 ** ((-9.0)/20):.6f}[bg]"
                                    amix_chain = f"[bg][nar]amix=inputs=2:duration=longest:normalize=0[a]"
                                    filter_complex = ";".join([vchain, vid_bg_chain, nar_chain, amix_chain])
                                    cmd = ["ffmpeg", "-y", "-i", dl_video, "-i", nar_audio, "-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]"]
                                    cmd.extend(_preferred_video_encode_args())
                                    cmd.extend(_preferred_audio_encode_args())
                                    cmd.append(ep_narr_out)
                                try:
                                    subprocess.run(cmd, check=True)
                                    narrated_videos.append(ep_narr_out)
                                    if 1 <= i <= total_eps:
                                        episode_videos[i-1] = ep_narr_out
                                    # update task artifacts
                                    downloaded.append(dl_video)
                                    # Immediately publish sandbox links and try upload to Drive for this episode
                                    try:
                                        rel = to_project_relative_posix(ep_narr_out)
                                       
                                        view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                                        download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                                        send_discord_message(f"🎥 Xem video tập {i} :" + view_link)
                                        send_discord_message(f"⬇️ Tải video tập  {i}:" + download_link)
                                    except Exception as e:
                                        try:
                                            import traceback
                                            send_discord_message(f"⚠️ process_series: Drive upload failed for group {g_idx} part {p+1}: {e}\n{traceback.format_exc()}")
                                        except Exception as e:
                                            _report_and_ignore(e, "process_series: pieces finalize")
                                    # update index
                                    try:
                                        meta_index.setdefault('episodes', {})
                                        meta_index['episodes'][ep_label] = meta_index['episodes'].get(ep_label, {})
                                        meta_index['episodes'][ep_label].update({
                                            'srt': raw_srt if os.path.exists(raw_srt) else None,
                                            'srt_vi': vi_srt if os.path.exists(vi_srt) else None,
                                            'nar_audio': nar_out_flac if os.path.exists(nar_out_flac) else None,
                                            'nar_video': ep_narr_out if os.path.exists(ep_narr_out) else None,
                                            'schedule': os.path.join(run_dir, f"{ep_label}.schedule.json")
                                        })
                                        with open(index_path, 'w', encoding='utf-8') as f:
                                            json.dump(meta_index, f, ensure_ascii=False, indent=2)
                                    except Exception as e:
                                        _report_and_ignore(e, "ignored")
                                except Exception as e:
                                    send_discord_message(f"⚠️ Lỗi khi render video+kara+nar: {e}")
                                    # fallback: create burned preview then mix
                                    try:
                                        # Instead of creating a persistent burned preview file (tiktok_out)
                                        # to save disk, mix narration directly into the downloaded video.
                                        # Single-pass: burn subtitles (if present) + mix generated narration audio
                                        try:
                                            ok = burn_and_mix_narration(dl_video, ass_path, nar_audio, ep_narr_out, replace_audio=narration_replace_audio, narration_volume_db=narration_volume_db, shift_sec=0.7, with_subtitles=with_subtitles)
                                            if not ok:
                                                try:
                                                    narration_from_srt.mix_narration_into_video(dl_video, nar_audio, ep_narr_out, narration_volume_db=narration_volume_db if narration_volume_db is not None else 3.0, replace_audio=narration_replace_audio, extend_video=True, shift_sec=0.7, video_volume_db=-3.0)
                                                except Exception:
                                                    try:
                                                        shutil.copy2(dl_video, tiktok_out)
                                                        burned_videos.append(tiktok_out)
                                                    except Exception as e:
                                                        _report_and_ignore(e, "ignored")
                                        except Exception:
                                            try:
                                                narration_from_srt.mix_narration_into_video(dl_video, nar_audio, ep_narr_out, narration_volume_db=narration_volume_db if narration_volume_db is not None else 3.0, replace_audio=narration_replace_audio, extend_video=True, shift_sec=0.7, video_volume_db=-3.0)
                                            except Exception:
                                                try:
                                                    shutil.copy2(dl_video, tiktok_out)
                                                    burned_videos.append(tiktok_out)
                                                except Exception as e:
                                                    _report_and_ignore(e, "ignored")
                                        narrated_videos.append(ep_narr_out)
                                        if 1 <= i <= total_eps:
                                            episode_videos[i-1] = ep_narr_out
                                    except Exception:
                                        try:
                                            shutil.copy2(dl_video, tiktok_out)
                                            burned_videos.append(tiktok_out)
                                        except Exception as e:
                                            _report_and_ignore(e, "ignored")
                            except Exception as e:
                                send_discord_message(f"⚠️ Lỗi tạo thuyết minh+render cho tập {i}: {e}")
                                # fallback to normal burn-only behavior below
                                try:
                                    if not os.path.exists(dl_video):
                                        out_dl = convert_stt.download_video(ep_url, dl_video)
                                except Exception as e:
                                    try:
                                        import traceback
                                        send_discord_message(f"⚠️ process_series: error announcing split parts for group {g_idx}: {e}\n{traceback.format_exc()}")
                                    except Exception as e:
                                        _report_and_ignore(e, "ignored")
                                # To save disk, do NOT create a tiktok preview file; instead, skip creating burned preview.
                                # As a best-effort fallback, just copy the downloaded file into narrated list (no burned subtitles).
                                try:
                                    narrated_videos.append(dl_video)
                                    if 1 <= i <= total_eps:
                                        episode_videos[i-1] = dl_video
                                except Exception as e:
                                    _report_and_ignore(e, "ignored")
                            try:
                                tasks_local = load_tasks()
                                tasks_local[request_id]['progress'] = 20 + int((len(srt_files) / len(unique)) * 40)
                                tasks_local[request_id].setdefault('video_file', [])
                                tasks_local[request_id]['video_file'] = downloaded
                                tasks_local[request_id].setdefault('srt_files', [])
                                tasks_local[request_id]['srt_files'] = srt_files
                                tasks_local[request_id].setdefault('burned_videos', [])
                                tasks_local[request_id]['burned_videos'] = burned_videos
                                tasks_local[request_id].setdefault('narrated_videos', [])
                                tasks_local[request_id]['narrated_videos'] = narrated_videos
                                save_tasks(tasks_local)
                            except Exception as e:
                                _report_and_ignore(e, "ignored")
                            continue

                        # If narration disabled in future and burned preview exists, include it
                        if not _add_narr and os.path.exists(tiktok_out):
                            send_discord_message(f"♻️ Đã có video burn phụ đề tập {i}: {tiktok_out} — thêm vào danh sách nối")
                            burned_videos.append(tiktok_out)
                            continue

                    # Otherwise, produce SRT and Vietnamese translation
                    # Ensure deterministic download path
                    if not os.path.exists(dl_video):
                        try:
                            out_dl = convert_stt.download_video(ep_url, dl_video)
                          
                        except Exception:
                            out_dl = None
                        if not out_dl or not os.path.exists(dl_video):
                            raise RuntimeError("Download failed")
                    downloaded.append(dl_video)

                    # Transcribe -> srt (convert_stt returns translated vi.srt when possible)
                   
                    res_srt = convert_stt.transcribe(dl_video, task_id=f"{request_id}_{i}")
                  
                    if not res_srt or not os.path.exists(res_srt):
                        send_discord_message(f"⚠️ Tạo SRT thất bại cho: {dl_video}")
                        continue

                    # move/rename SRT to deterministic vi_srt (if transcribe returned .srt, try translating)
                    try:
                        # If res_srt already a vi.srt, move
                        if res_srt.endswith('.vi.srt'):
                            os.replace(res_srt, vi_srt)
                        else:
                            # attempt to translate to vi using translate_srt_file if available
                            try:
                                api_key = os.environ.get('GEMINI_API_KEY_Translate') or os.environ.get('GOOGLE_TTS_API_KEY')
                                translated = translate_srt_file(res_srt, output_srt=vi_srt, task_id=f"{request_id}_{i}")
                                if not translated or not os.path.exists(translated):
                                    # fallback: rename original
                                    os.replace(res_srt, raw_srt)
                            except Exception:
                                os.replace(res_srt, raw_srt)
                    except Exception as e:
                        send_discord_message(f"⚠️ Lỗi khi lưu SRT: {e}")
                        continue

                    # record srt
                    if os.path.exists(vi_srt):
                        srt_files.append(vi_srt)
                    elif os.path.exists(raw_srt):
                        srt_files.append(raw_srt)

                    # Burn subtitles
                    try:
                        # Burn subtitles using ASS for better styling
                        try:
                            from convert_srt_to_ass import convert as convert_srt_to_ass_convert
                        except Exception:
                            convert_srt_to_ass_convert = None

                        use_srt = vi_srt if os.path.exists(vi_srt) else raw_srt
                        ass_path = use_srt.replace('.srt', '.ass')
                        if convert_srt_to_ass_convert:
                            convert_srt_to_ass_convert(use_srt, ass_path, 30, 11, "Noto Sans", 20, 150)
                        else:
                            try:
                                subprocess.run(["ffmpeg", "-y", "-i", use_srt, ass_path], check=True)
                            except Exception:
                                ass_path = use_srt

                        # Skip creating a TikTok-sized preview; use the original downloaded
                        # video for downstream narration/subtitle mixing to save disk and
                        # preserve original resolution. ASS file is prepared above for
                        # use during single-pass mixes.
                        sub_filter = _ffmpeg_sub_filter(ass_path)
                        tiktok_out = dl_video
                        burned_videos.append(tiktok_out)
                    except Exception as e:
                        send_discord_message(f"⚠️ Burn subtitles (ASS) failed for {out_video}: {e}")
                        # Fallback: mark downloaded video as the source
                        try:
                            tiktok_out = dl_video
                            burned_videos.append(tiktok_out)
                        except Exception as e:
                            _report_and_ignore(e, "ignored")
                    # Optional: create narration per episode and upload link
                    try:
                        if _add_narr:
                            use_srt = vi_srt if os.path.exists(vi_srt) else (raw_srt if os.path.exists(raw_srt) else None)
                            if use_srt:
                                # Store narration temp under per-title run folder to keep artifacts together
                                try:
                                    nar_dir = run_dir
                                    os.makedirs(nar_dir, exist_ok=True)
                                except Exception:
                                    nar_dir = OUTPUT_DIR
                                nar_tmp = os.path.join(nar_dir, f"{ep_label}.nar.flac")
                                # Write narration FLAC under run_dir with deterministic name
                                nar_out_flac = os.path.join(run_dir, f"{ep_label}.nar.flac")
                                # place per-line TTS pieces into a dedicated subfolder to avoid clutter
                                tts_pieces_dir = os.path.join(run_dir, "tts_pieces")
                                try:
                                    os.makedirs(tts_pieces_dir, exist_ok=True)
                                except Exception:
                                    tts_pieces_dir = run_dir

                                nar_audio, _meta = narration_from_srt.build_narration_schedule(
                                    use_srt, nar_out_flac,
                                    voice_name=narration_voice,
                                    speaking_rate=1.0,
                                    lead=0.0,
                                    meta_out=None,
                                    trim=False,
                                    rate_mode=narration_rate_dynamic,
                                    apply_fx=bool(narration_apply_fx),
                                    tmp_subdir=tts_pieces_dir
                                )
                                # Ensure FLAC path reference uses outputs
                                if nar_audio != nar_out_flac:
                                    try:
                                        shutil.copy2(nar_audio, nar_out_flac)
                                        nar_audio = nar_out_flac
                                    except Exception:
                                        nar_audio = nar_audio

                                # Attempt single-pass render: burn subtitles and mix narration
                                ep_narr_out = os.path.join(run_dir, f"{ep_label}.nar.mp4")
                                try:
                                    # prepare ASS for burn
                                    try:
                                        from convert_srt_to_ass import convert as convert_srt_to_ass_convert
                                    except Exception:
                                        convert_srt_to_ass_convert = None

                                    ass_path = use_srt.replace('.srt', '.ass')
                                    if convert_srt_to_ass_convert:
                                        try:
                                            convert_srt_to_ass_convert(use_srt, ass_path, 30, 11, "Noto Sans", 20, 150)
                                        except Exception:
                                            ass_path = use_srt
                                    else:
                                        try:
                                            subprocess.run(["ffmpeg", "-y", "-i", use_srt, ass_path], check=True)
                                        except Exception:
                                            ass_path = use_srt

                                    sub_filter = _ffmpeg_sub_filter(ass_path)
                                    narr_vol_lin = 10 ** (float(narration_volume_db) / 20.0) if narration_volume_db is not None else 10 ** (6.0/20.0)

                                    # Build filter_complex similar to earlier single-pass approach
                                    shift_ms = max(0, int(0.7 * 1000))
                                    # If narration longer than video and we are not replacing audio, extend last frame
                                    pad_sec = max(0.0, (get_media_info(nar_audio)[2] if os.path.exists(nar_audio) else 0.0) - (get_media_info(tiktok_out)[2] if os.path.exists(tiktok_out) else 0.0))
                                    need_pad_local = pad_sec > 0.01 and narration_replace_audio is False
                                    tpad_frag = f"tpad=stop_mode=clone:stop_duration={pad_sec}" if need_pad_local else ""
                                    if tpad_frag:
                                        # preserve original video size; do not force scale/pad for TikTok
                                        vchain = f"[0:v]{tpad_frag},{sub_filter}[v]"
                                    else:
                                        vchain = f"[0:v]{sub_filter}[v]"

                                    nar_chain = f"[1:a]adelay={shift_ms}|{shift_ms},volume={narr_vol_lin}[nar]"

                                    if narration_replace_audio:
                                        filter_complex = ";".join([vchain, nar_chain])
                                        cmd = ["ffmpeg", "-y", "-i", tiktok_out, "-i", nar_audio, "-filter_complex", filter_complex, "-map", "[v]", "-map", "[nar]"]
                                        cmd.extend(_preferred_video_encode_args())
                                        cmd.extend(_preferred_audio_encode_args())
                                        cmd.append(ep_narr_out)
                                    else:
                                        vid_bg_chain = f"[0:a]volume={10 ** ((-5.0)/20):.6f}[bg]"
                                        amix_chain = f"[bg][nar]amix=inputs=2:duration=longest:normalize=0[a]"
                                        filter_complex = ";".join([vchain, vid_bg_chain, nar_chain, amix_chain])
                                        cmd = ["ffmpeg", "-y", "-i", tiktok_out, "-i", nar_audio, "-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]"]
                                        cmd.extend(_preferred_video_encode_args())
                                        cmd.extend(_preferred_audio_encode_args())
                                        cmd.append(ep_narr_out)
                                    subprocess.run(cmd, check=True)
                                    narrated_videos.append(ep_narr_out)
                                    try:
                                        rel = to_project_relative_posix(ep_narr_out)
                                        view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                                        download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                                        send_discord_message(f"🎥 Xem video tập {i} :" + view_link)
                                        send_discord_message(f"⬇️ Tải video tập  {i}:" + download_link)
                                    except Exception as e:
                                        _report_and_ignore(e, "ignored")
                                except Exception:
                                    # Fallback to previous two-step: burn then mix
                                    try:
                                        narration_from_srt.mix_narration_into_video(
                                            tiktok_out if os.path.exists(tiktok_out) else out_video,
                                            nar_audio,
                                            ep_narr_out,
                                            narration_volume_db=narration_volume_db if narration_volume_db is not None else 3.0,
                                            replace_audio=narration_replace_audio,
                                            extend_video=True,
                                            shift_sec=0.7,
                                            video_volume_db=-3.0,
                                        )
                                        narrated_videos.append(ep_narr_out)
                                        rel = to_project_relative_posix(ep_narr_out)
                                        view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                                        download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                                        send_discord_message(f"🎥 Xem video tập {i} :" + view_link)
                                        send_discord_message(f"⬇️ Tải video tập  {i}:" + download_link)
                                    except Exception as e:
                                        send_discord_message(f"⚠️ Fallback tạo thuyết minh thất bại cho tập {i}: {e}")
                    except Exception as e:
                        send_discord_message(f"⚠️ Lỗi tạo thuyết minh cho tập {i}: {e}")

                    # update progress after each processed episode
                    try:
                        tasks_local = load_tasks()
                        tasks_local[request_id]['progress'] = 20 + int((len(srt_files) / len(unique)) * 40)
                        tasks_local[request_id].setdefault('video_file', [])
                        tasks_local[request_id]['video_file'] = downloaded
                        tasks_local[request_id].setdefault('srt_files', [])
                        tasks_local[request_id]['srt_files'] = srt_files
                        tasks_local[request_id].setdefault('burned_videos', [])
                        tasks_local[request_id]['burned_videos'] = burned_videos
                        save_tasks(tasks_local)
                    except Exception as e:
                        try:
                            import traceback
                            send_discord_message(f"⚠️ process_series: error while splitting/uploading group {g_idx}: {e}\n{traceback.format_exc()}")
                        except Exception as e:
                            _report_and_ignore(e, "ignored")
                except Exception as e:
                    try:
                        import traceback
                        tb = traceback.format_exc()
                        err_type = type(e).__name__
                        send_discord_message(f"⚠️ Bỏ qua tập do lỗi: {ep_url}: {err_type}: {e}\n{tb}")
                    except Exception:
                        send_discord_message(f"⚠️ Bỏ qua tập do lỗi: {ep_url}: {e}")
                    continue

            # 4) Concatenate narrated videos into groups (chunk by 4), special-case remaining 5-7 to keep together
            source_list = narrated_videos if narrated_videos else (burned_videos if burned_videos else downloaded)
            if not source_list:
                send_discord_message("❌ Không có video nào được tải thành công. Kết thúc.")
                tasks_local = load_tasks(); tasks_local[request_id]['status'] = 'error'; tasks_local[request_id]['error'] = 'No downloaded videos'; tasks_local[request_id]['progress'] = 0; save_tasks(tasks_local)
                return

            # Build groups of files. If `render_full` requested, make a single group with all episodes.
            if render_full:
                groups = [source_list]
            else:
                # chunks of 4, but if remaining in (5,6,7) then keep them in one group
                groups = []
                i = 0
                total_eps = len(source_list)
                while i < total_eps:
                    remaining = total_eps - i
                    if remaining > 4 and remaining < 8:
                        groups.append(source_list[i:])
                        break
                    else:
                        groups.append(source_list[i:i+4])
                        i += 4

            final_files = []
            # Helper: determine if it's safe to concat-copy (same codec/size/audio)
            def _can_concat_copy(files: list) -> bool:
                try:
                    import json
                    def get_info(p):
                        cmd = ['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', p]
                        proc = subprocess.run(cmd, capture_output=True, text=True)
                        if proc.returncode != 0:
                            return None
                        return json.loads(proc.stdout)

                    base_info = None
                    for p in files:
                        info = get_info(p)
                        if not info or 'streams' not in info:
                            return False
                        # find first video and audio stream
                        v = next((s for s in info['streams'] if s.get('codec_type') == 'video'), None)
                        a = next((s for s in info['streams'] if s.get('codec_type') == 'audio'), None)
                        if not v:
                            return False
                        if base_info is None:
                            base_info = (v.get('codec_name'), int(v.get('width', 0)), int(v.get('height', 0)), v.get('pix_fmt'))
                            base_audio = (a.get('codec_name') if a else None, int(a.get('sample_rate')) if a and a.get('sample_rate') else None, int(a.get('channels')) if a and a.get('channels') else None)
                        else:
                            cur_v = (v.get('codec_name'), int(v.get('width', 0)), int(v.get('height', 0)), v.get('pix_fmt'))
                            cur_a = (a.get('codec_name') if a else None, int(a.get('sample_rate')) if a and a.get('sample_rate') else None, int(a.get('channels')) if a and a.get('channels') else None)
                            if cur_v != base_info:
                                return False
                            # allow slight audio differences (e.g., different codec) but require same sample rate and channels
                            if base_audio[1] and cur_a[1] and base_audio[1] != cur_a[1]:
                                return False
                            if base_audio[2] and cur_a[2] and base_audio[2] != cur_a[2]:
                                return False
                    return True
                except Exception:
                    return False

            def _has_encoder(enc_name: str) -> bool:
                try:
                    p = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True)
                    return enc_name in p.stdout
                except Exception:
                    return False
            # Concatenate each group separately and add a short title overlay indicating starting episode
            for g_idx, grp in enumerate(groups, start=1):
                start_ep = (sum(len(x) for x in groups[:g_idx-1]) + 1)
                # Use deterministic group filename based on base title and group index
                if render_full:
                    group_out = os.path.join(final_dir, f"{base_title_val}_FULL.mp4")
                else:
                    group_out = os.path.join(final_dir, f"{base_title_val}_Tap_{g_idx}.mp4")
                # Prefer concat-copy when all files are compatible; otherwise re-encode with efficient CRF
                try:
                    if _can_concat_copy(grp):
                        concat_list = os.path.join(run_dir, f"concat_{base_title_val}_G{g_idx}.txt")
                        with open(concat_list, 'w', encoding='utf-8') as f:
                            for p in grp:
                                f.write(f"file '{os.path.abspath(p)}'\n")
                        subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list, '-c', 'copy', group_out], check=True)
                        used_encoder = None
                    else:
                        # choose best available encoder (prefer libx265)
                        enc = 'libx265' if _has_encoder('libx265') else 'libx264'
                        if enc == 'libx265':
                            v_args = ['-c:v', 'libx265', '-preset', 'slow', '-crf', '24', '-pix_fmt', 'yuv420p', '-tag:v', 'hvc1']
                        else:
                            v_args = ['-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-pix_fmt', 'yuv420p']
                        a_args = ['-c:a', 'aac', '-b:a', '128k']
                        # Build ffmpeg inputs
                        ff_args = ['ffmpeg', '-y']
                        for p in grp:
                            ff_args.extend(['-i', p])
                        concat_filter = f"concat=n={len(grp)}:v=1:a=1"
                        ff_args.extend(['-filter_complex', concat_filter, '-vsync', 'vfr'])
                        ff_args.extend(v_args)
                        ff_args.extend(a_args)
                        ff_args.append(group_out)
                        subprocess.run(ff_args, check=True)
                        used_encoder = enc
                except Exception:
                    # Last resort: try concat-copy (best effort)
                    concat_list = os.path.join(run_dir, f"concat_{base_title_val}_G{g_idx}.txt")
                    with open(concat_list, 'w', encoding='utf-8') as f:
                        for p in grp:
                            f.write(f"file '{os.path.abspath(p)}'\n")
                    subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list, '-c', 'copy', group_out], check=True)
                    used_encoder = None

                # Overlay title for 3s at start indicating starting episode or FULL
                if title:
                    tmp_title = None
                    try:
                        font_path_try = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
                        try:
                            if not os.path.exists(font_path_try):
                                font_path_try = "C:\\Windows\\Fonts\\arial.ttf" if os.name == "nt" else "times.ttf"
                        except Exception:
                            font_path_try = "C:\\Windows\\Fonts\\arial.ttf" if os.name == "nt" else "times.ttf"
                        # Use group ordinal for the overlay, or [FULL] when requested
                        if render_full:
                            title_text = f"[FULL] {title.upper()}"
                        else:
                            title_text = f"{title.upper()} - Tập {g_idx}"
                        title_text = title_text.replace(":", "\\:").replace("'", "\\'")
                        wrapped_text = wrap_text(title_text, max_chars_per_line=40)
                        drawtext = (
                            f"drawtext=fontfile='{font_path_try}':text_align=center:text='{wrapped_text}':"
                            f"fontcolor=white:fontsize=42:box=1:boxcolor=black@0.6:boxborderw=20:"
                            f"x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,0,3)'"
                        )
                        tmp_title = group_out + ".title.mp4"
                        cmd_title = ["ffmpeg", "-y", "-i", group_out, "-vf", drawtext]
                        cmd_title.extend(_preferred_video_encode_args())
                        cmd_title.extend(["-c:a", "copy", tmp_title])
                        subprocess.run(cmd_title, check=True)
                        os.replace(tmp_title, group_out)
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
                    finally:
                        try:
                            if tmp_title and os.path.exists(tmp_title):
                                os.remove(tmp_title)
                        except Exception:
                            pass
                # If group file exceeds 3600s, split into parts (no re-encode)
                try:
                    _, _, group_dur = get_media_info(group_out)
                except Exception:
                    group_dur = None
                if group_dur and group_dur > 3600:
                    parts = math.ceil(group_dur / 3600)
                    for p in range(parts):
                        start = p * 3600
                        outp = os.path.join(final_dir, f"{base_title_val}_Tap_{g_idx}_P{p+1}.mp4")
                        subprocess.run(['ffmpeg', '-y', '-ss', str(start), '-i', group_out, '-t', '3600', '-c', 'copy', outp], check=True)
                        final_files.append(outp)
                    # Immediately announce and upload each split part for this group
                    try:
                        for p in range(parts):
                            outp = os.path.join(final_dir, f"{base_title_val}_Tap_{g_idx}_P{p+1}.mp4")
                            if os.path.exists(outp):
                                try:
                                    rel = to_project_relative_posix(outp)
                                    view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                                    download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                                    send_discord_message(f"🎥 Xem video (nhóm {g_idx} phần {p+1}):" + view_link)
                                    send_discord_message(f"⬇️ Tải video (nhóm {g_idx} phần {p+1}):" + download_link)
                                    try:
                                        uploaded = uploadOneDrive(outp, title)
                                        if isinstance(uploaded, dict):
                                            link = uploaded.get('webViewLink') or uploaded.get('downloadLink') or uploaded.get('id')
                                            if link:
                                                send_discord_message(f"📤 Drive upload (group {g_idx} part {p+1}): {link}")
                                    except Exception as e:
                                        _report_and_ignore(e, "ignored")
                                except Exception as e:
                                    _report_and_ignore(e, "ignored")
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
                else:
                    final_files.append(group_out)
                    # Announce and upload the concatenated group file
                    try:
                        if os.path.exists(group_out):
                            try:
                                rel = to_project_relative_posix(group_out)
                                view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                                download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                                send_discord_message(f"🎥 Xem video (nhóm {g_idx}):" + view_link)
                                send_discord_message(f"⬇️ Tải video (nhóm {g_idx}):" + download_link)
                                try:
                                    uploaded = uploadOneDrive(group_out, title)
                                    if isinstance(uploaded, dict):
                                        link = uploaded.get('webViewLink') or uploaded.get('downloadLink') or uploaded.get('id')
                                        if link:
                                            send_discord_message(f"📤 Drive upload (group {g_idx}): {link}")
                                except Exception as e:
                                    _report_and_ignore(e, "ignored")
                            except Exception as e:
                                _report_and_ignore(e, "ignored")
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
            # 6) Apply naming rules
            named_outputs = []
            # Compute total duration across final files (best-effort)
            total_dur = 0
            try:
                for fpath in final_files:
                    try:
                        _, _, d = get_media_info(fpath)
                        total_dur += d or 0
                    except Exception:
                        total_dur += 0
            except Exception:
                total_dur = None

            # Keep final output filenames as-produced; do NOT rename here so external
            # sandbox download URLs that use the file path remain valid.
            named_outputs = final_files

            # finalize task
            try:
                tasks_local = load_tasks()
                tasks_local[request_id]['status'] = 'completed'
                tasks_local[request_id]['progress'] = 100
                tasks_local[request_id]['video_file'] = named_outputs
                tasks_local[request_id]['video_path'] = named_outputs[0] if named_outputs else ''
                save_tasks(tasks_local)
            except Exception as e:
                _report_and_ignore(e, "ignored")
            # Also send collected per-episode links (if any)
            if episode_links:
                try:
                    tasks_local = load_tasks(); tasks_local[request_id]['episode_links'] = episode_links; save_tasks(tasks_local)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
            send_discord_message(f"✅ process_series completed: {named_outputs}")
        except Exception as e:
            send_discord_message(f"❌ process_series error: {e}")
            try:
                tasks_local = load_tasks(); tasks_local[request_id]['status'] = 'error'; tasks_local[request_id]['error'] = str(e); tasks_local[request_id]['progress'] = 0; save_tasks(tasks_local)
            except Exception as e:
                _report_and_ignore(e, "ignored")
    loop = asyncio.get_event_loop()
    try:
        tasks_local = load_tasks()
        if request_id in tasks_local:
            tasks_local[request_id]['status'] = 'running'
            save_tasks(tasks_local)
    except Exception:
        pass

    tracked = create_tracked_task(request_id, asyncio.to_thread(_worker))
    if run_in_background:
        return JSONResponse(status_code=202, content={"task_id": request_id, "started": True})
    else:
        try:
            await tracked
            return JSONResponse(status_code=200, content={"task_id": request_id, "completed": True})
        except asyncio.CancelledError:
            return JSONResponse(status_code=400, content={"task_id": request_id, "cancelled": True})


# API: delete episode assets by title and episode number
@app.delete('/delete_episode_assets')
def delete_episode_assets(
    title: str = Query(..., description='Tên phim/series (base title used in filenames)'),
    episode_number: int = Query(..., description='Số tập muốn xoá (1-based, 0 = xóa video final)'),
    components: List[str] | None = Query(None, description='Danh sách tên thành phần: raw, srt_zh, srt_vi, nar_flac, burned, nar_video'),
    components_nums: str | None = Query(None, description='Chuỗi số các thành phần, cách nhau dấu phẩy. Map: 1 raw, 2 srt_zh, 3 srt_vi, 4 nar_flac, 5 burned, 6 nar_video'),
    episode_numbers: str | None = Query(None, description='Xóa nhiều tập, cách nhau dấu phẩy. Hỗ trợ 0 để xóa video final. Ví dụ: 0,1,2,5')
):
    """Delete selected assets for a given episode.

    Filenames follow the convention used by process_series:
      - raw video:        {title}_Tap_{ep}.mp4
      - zh/raw srt:       {title}_Tap_{ep}.srt
      - vi srt:           {title}_Tap_{ep}.vi.srt
      - burned preview:   {title}_Tap_{ep}.tiktok.mp4
      - narration flac:   {title}_Tap_{ep}.nar.flac
      - narrated video:   {title}_Tap_{ep}.nar.mp4

    If `components` is not provided, all above assets are deleted.
    """
    base = safe_filename(title) if title else 'series'
    code_map = {
        '1': 'raw',
        '2': 'srt_zh',
        '3': 'srt_vi',
        '4': 'nar_flac',
        '5': 'burned',
        '6': 'nar_video',
    }

    # Locate candidate run directories for this title. New `process_series` creates
    # per-title run folders under OUTPUT_DIR/<base>/[request_id] or may place files
    # directly under OUTPUT_DIR/<base>.
    run_root = os.path.join(OUTPUT_DIR, base)
    run_dirs = []
    if os.path.isdir(run_root):
        # include the base folder itself
        run_dirs.append(run_root)
        # include any subfolders (individual runs)
        try:
            for name in os.listdir(run_root):
                p = os.path.join(run_root, name)
                if os.path.isdir(p):
                    run_dirs.append(p)
        except Exception:
            pass
    else:
        # fallback: there may still be files named {base}_Tap_X under OUTPUT_DIR
        run_dirs.append(run_root)

    # Helper to collect candidate paths for an episode inside a given folder
    def _candidate_paths(folder: str, ep: int):
        label = f"{base}_Tap_{ep}"
        return {
            'raw': os.path.join(folder, f"{label}.mp4"),
            'srt_zh': os.path.join(folder, f"{label}.srt"),
            'srt_vi': os.path.join(folder, f"{label}.vi.srt"),
            'burned': os.path.join(folder, f"{label}.tiktok.mp4"),
            'nar_flac': os.path.join(folder, f"{label}.nar.flac"),
            'nar_video': os.path.join(folder, f"{label}.nar.mp4"),
        }

    def _delete_file(p: str) -> bool:
        try:
            if os.path.exists(p):
                os.remove(p)
                return True
        except Exception:
            return False
        return False

    # Parse selected components from numeric codes or explicit names
    selected_by_code: List[str] = []
    if components_nums:
        try:
            nums = [n.strip() for n in components_nums.split(',') if n.strip()]
            for n in nums:
                k = code_map.get(n)
                if k:
                    selected_by_code.append(k)
        except Exception:
            pass

    # Build episode list to operate on
    targets = []
    if episode_numbers:
        try:
            targets = [int(e.strip()) for e in episode_numbers.split(',') if e.strip()]
        except Exception:
            targets = [episode_number]
    else:
        targets = [episode_number]

    results = []

    # Special handling for episode==0 (final outputs). Keep previous behavior but
    # also search for variants under OUTPUT_DIR and OUTPUT_DIR/<base> folders.
    def _delete_finals() -> dict:
        safe_title = safe_filename(title)
        candidates = []
        candidates.append(os.path.join(OUTPUT_DIR, f"{safe_title}.mp4"))
        candidates.append(os.path.join(OUTPUT_DIR, f"{safe_filename('[full] ' + title)}.mp4"))
        # also check under OUTPUT_DIR/<base>
        try:
            if os.path.isdir(run_root):
                for fname in os.listdir(run_root):
                    if fname.lower().endswith('.mp4'):
                        candidates.append(os.path.join(run_root, fname))
        except Exception:
            pass

        # scan top-level OUTPUT_DIR for part-named files
        try:
            for fname in os.listdir(OUTPUT_DIR):
                low = fname.lower()
                if low.endswith('.mp4') and low.startswith(safe_title.lower() + ' '):
                    candidates.append(os.path.join(OUTPUT_DIR, fname))
        except Exception:
            pass

        final_deleted = []
        final_not_found = []
        seen = set()
        for p in candidates:
            if not p or p in seen:
                continue
            seen.add(p)
            try:
                if os.path.exists(p):
                    os.remove(p)
                    final_deleted.append(p)
                else:
                    final_not_found.append(p)
            except Exception:
                final_not_found.append(p)
        return {'final_deleted': final_deleted, 'final_not_found': final_not_found}

    for ep in targets:
        if ep == 0:
            finals = _delete_finals()
            results.append({
                'episode': 0,
                'deleted': {},
                'not_found': {},
                'invalid_components': [],
                'final_deleted': finals.get('final_deleted', []),
                'final_not_found': finals.get('final_not_found', []),
            })
            continue

        # For each run_dir attempt deletion of selected components (or all)
        deleted_acc: Dict[str, str] = {}
        not_found_acc: Dict[str, str] = {}
        invalid_acc: List[str] = []

        to_delete_keys = selected_by_code or components or list(code_map.values())

        for rd in run_dirs:
            paths_map = _candidate_paths(rd, ep)
            # If index.json exists in this run dir, we'll try to update it after deletions
            idx_path = os.path.join(rd, 'index.json')
            for comp in to_delete_keys:
                p = paths_map.get(comp)
                if not p:
                    if comp not in invalid_acc:
                        invalid_acc.append(comp)
                    continue
                ok = _delete_file(p)
                if ok:
                    deleted_acc[comp] = p
                else:
                    # only mark not found if the file genuinely doesn't exist
                    if not os.path.exists(p):
                        not_found_acc[comp] = p

            # attempt to update index.json: remove entries for this episode label
            try:
                if os.path.exists(idx_path):
                    try:
                        with open(idx_path, 'r', encoding='utf-8') as fh:
                            idx = json.load(fh)
                    except Exception:
                        idx = None
                    if isinstance(idx, dict):
                        ep_key = f"{base}_Tap_{ep}"
                        if ep_key in idx:
                            try:
                                idx.pop(ep_key, None)
                                with open(idx_path, 'w', encoding='utf-8') as fh:
                                    json.dump(idx, fh, ensure_ascii=False, indent=2)
                            except Exception:
                                _report_and_ignore(Exception('failed to update index'), 'ignored')
            except Exception:
                pass

        results.append({
            'episode': ep,
            'deleted': deleted_acc,
            'not_found': not_found_acc,
            'invalid_components': invalid_acc,
            'final_deleted': [],
            'final_not_found': [],
        })

    msg = f"🧹 Đã xử lý xoá cho '{title}': các tập {', '.join(str(r['episode']) for r in results)}"
    send_discord_message(msg)
    return JSONResponse(content={
        'title': title,
        'results': results,
        'component_codes_map': code_map
    })


# Endpoint: Download video using yt-dlp, create subtitles, translate, narrate, and render with [FULL] title overlay
@app.get('/process_video_ytdl')
async def process_video_ytdl(
    video_url: str = Query(..., description='URL video cần tải (hỗ trợ YouTube, Facebook, v.v.)'),
    title: str = Query('', description='Tiêu đề video (dùng cho tên thư mục và overlay)'),
    run_in_background: bool = Query(True, description='Nếu True thì chạy nền và trả về ngay'),
    add_narration: bool = Query(True, description='Nếu True, tạo thuyết minh từ phụ đề và trộn vào video'),
    with_subtitles: bool = Query(True, description='Nếu True thì burn phụ đề vào video; nếu False chỉ thêm thuyết minh'),
    narration_voice: str = Query('vi-VN-Standard-C', description='Giọng Google TTS'),
    narration_replace_audio: bool = Query(False, description='Thay hoàn toàn audio gốc bằng thuyết minh'),
    narration_volume_db: float = Query(8.0, description='Âm lượng thuyết minh khi trộn (dB)'),
    narration_rate_dynamic: int = Query(0, description='1: dùng tốc độ nói động (1.28–1.40), 0: cố định 1.0'),
    narration_apply_fx: int = Query(1, description='1: áp EQ/tone/time filter cho giọng thuyết minh'),
    bg_choice: str | None = Query(None, description='Tên file nhạc nền (optional)'),
    request_id: str | None = Query(None, description='(internal) reuse existing task_id'),
    use_queue: bool = Query(True, description='If True enqueue the job into TASK_QUEUE instead of running inline')
):
    """Download a video using yt-dlp, create subtitles, translate them, create narration,
    and render with [FULL] title overlay. Saves to folder safename(title).
    
    Flow:
    1. Download video using yt-dlp
    2. Create subtitles (transcribe with Whisper)
    3. Translate subtitles to Vietnamese
    4. Create narration from Vietnamese subtitles
    5. Render video with [FULL] title overlay
    6. Save to folder named safename(title)
    """
    if not request_id:
        request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    
    # If requested, enqueue into TASK_QUEUE and return immediately
    if use_queue:
        try:
            tasks_local = load_tasks()
        except Exception:
            tasks_local = {}
        
        tasks_local[request_id] = {
            "task_id": request_id,
            "status": "pending",
            "progress": 0,
            "video_path": "",
            "video_file": [],
            "title": title,
            "request_urls": [video_url],
            "created_at": time.time(),
            "type": 9,  # New type for ytdl single video processing
            "task_type": "ytdl_video",
            "skip_queue": False,
            "add_narration": bool(add_narration),
            "narration_voice": narration_voice,
            "narration_replace_audio": narration_replace_audio,
            "narration_volume_db": narration_volume_db,
            "narration_rate_dynamic": narration_rate_dynamic,
            "narration_apply_fx": narration_apply_fx,
            "bg_choice": bg_choice,
            "with_subtitles": with_subtitles
        }
        try:
            save_tasks(tasks_local)
        except Exception:
            pass
        
        payload = {
            "task_id": request_id,
            "type": 9,
            "video_url": video_url,
            "title": title,
            "add_narration": bool(add_narration),
            "with_subtitles": bool(with_subtitles),
            "narration_voice": narration_voice,
            "narration_replace_audio": narration_replace_audio,
            "narration_volume_db": narration_volume_db,
            "narration_rate_dynamic": narration_rate_dynamic,
            "narration_apply_fx": narration_apply_fx,
            "bg_choice": bg_choice,
        }
        try:
            await enqueue_task(payload)
        except Exception:
            tasks_local = load_tasks()
            tasks_local[request_id]['status'] = 'error'
            tasks_local[request_id]['error'] = 'failed to enqueue'
            save_tasks(tasks_local)
            return JSONResponse(status_code=500, content={"error": "enqueue failed"})
        
        send_discord_message(f"📨 Đã xếp ytdl video task vào hàng chờ: {request_id}")
        return JSONResponse(status_code=202, content={"task_id": request_id, "started": True})
    
    def _worker():
        import subprocess, time, os, json
        try:
            send_discord_message(f"🔁 process_video_ytdl start: {video_url} (task {request_id})")
            
            # Create task entry
            try:
                tasks_local = load_tasks()
            except Exception:
                tasks_local = {}
            
            tasks_local[request_id] = {
                "task_id": request_id,
                "status": "running",
                "progress": 5,
                "video_path": "",
                "video_file": [],
                "title": title,
                "request_urls": [video_url],
                "created_at": time.time(),
                "type": 9,
                "task_type": "ytdl_video",
                "skip_queue": True,
                "add_narration": add_narration,
                "narration_voice": narration_voice,
                "narration_replace_audio": narration_replace_audio,
                "narration_volume_db": narration_volume_db,
                "narration_rate_dynamic": narration_rate_dynamic,
                "narration_apply_fx": narration_apply_fx,
                "bg_choice": bg_choice,
                "with_subtitles": with_subtitles
            }
            try:
                save_tasks(tasks_local)
            except Exception as e:
                _report_and_ignore(e, "ignored")
            
            # Determine safe folder name from title
            try:
                base_title_val = safe_filename(title) if title else url_hash(video_url)[:8]
            except Exception:
                base_title_val = url_hash(video_url)[:8]
            
            # Create output folder
            try:
                run_dir = os.path.join(OUTPUT_DIR, base_title_val)
                os.makedirs(run_dir, exist_ok=True)
            except Exception:
                run_dir = OUTPUT_DIR
            
            send_discord_message(f"📁 Thư mục lưu: {run_dir}")
            
            # Define all artifact paths
            dl_video = os.path.join(run_dir, f"{base_title_val}_download.mp4")
            raw_srt = os.path.join(run_dir, f"{base_title_val}.srt")
            vi_srt = os.path.join(run_dir, f"{base_title_val}.vi.srt")
            nar_out_flac = os.path.join(run_dir, f"{base_title_val}.nar.flac")
            final_video = os.path.join(run_dir, f"{base_title_val}_final.mp4")
            
            # Check if final video already exists
            if os.path.exists(final_video):
                send_discord_message(f"♻️ Video final đã tồn tại: {final_video}")
                try:
                    # Upload and announce
                    uploaded = uploadOneDrive(final_video, base_title_val)
                    link = uploaded.get('downloadLink') or uploaded.get('webViewLink')
                    if link:
                        send_discord_message(f"☁️ OneDrive: {link}")
                except Exception as e:
                    send_discord_message(f"⚠️ Upload OneDrive thất bại: {e}")
                
                try:
                    rel = to_project_relative_posix(final_video)
                    view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                    download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                    send_discord_message(f"🎥 Xem video: {view_link}")
                    send_discord_message(f"⬇️ Tải video: {download_link}")
                except Exception as e:
                    _report_and_ignore(e, "ignored")
                
                # Update task completion
                try:
                    tasks_local = load_tasks()
                    if request_id not in tasks_local:
                        tasks_local[request_id] = {"task_id": request_id, "created_at": time.time()}
                    tasks_local[request_id]['status'] = 'completed'
                    tasks_local[request_id]['progress'] = 100
                    tasks_local[request_id]['video_path'] = final_video
                    tasks_local[request_id]['video_file'] = [final_video]
                    save_tasks(tasks_local)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
                
                send_discord_message(f"✅ process_video_ytdl hoàn tất (reuse): {request_id}")
                return
            
            # Step 1: Download video using yt-dlp
            if os.path.exists(dl_video):
                send_discord_message(f"♻️ Video đã tải sẵn: {dl_video}")
                downloaded = dl_video
            else:
                send_discord_message(f"⬇️ Bắt đầu tải video từ: {video_url}")
                
                try:
                    tasks_local = load_tasks()
                    if request_id not in tasks_local:
                        tasks_local[request_id] = {"task_id": request_id, "status": "running", "created_at": time.time()}
                    tasks_local[request_id]['progress'] = 10
                    tasks_local[request_id]['status'] = 'running'
                    save_tasks(tasks_local)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
                
                try:
                    import convert_stt
                    downloaded = convert_stt.download_video(video_url, dl_video)
                    if not downloaded or not os.path.exists(downloaded):
                        raise RuntimeError(f"Download failed: {video_url}")
                    send_discord_message(f"✅ Đã tải video: {downloaded}")
                except Exception as e:
                    send_discord_message(f"❌ Lỗi tải video: {e}")
                    tasks_local = load_tasks()
                    tasks_local[request_id]['status'] = 'error'
                    tasks_local[request_id]['error'] = f'Download failed: {str(e)}'
                    save_tasks(tasks_local)
                    return
            
            # Step 2-5: Process video through full pipeline using helper
            def progress_callback(step: str, pct: int):
                try:
                    tasks_local = load_tasks()
                    if request_id not in tasks_local:
                        tasks_local[request_id] = {"task_id": request_id, "status": "running", "created_at": time.time()}
                    tasks_local[request_id]['progress'] = pct
                    save_tasks(tasks_local)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
            
            try:
                import narration_from_srt
                result = process_single_video_pipeline(
                    video_path=downloaded,
                    output_dir=run_dir,
                    base_name=base_title_val,
                    add_narration=add_narration,
                    with_subtitles=with_subtitles,
                    narration_voice=narration_voice,
                    narration_replace_audio=narration_replace_audio,
                    narration_volume_db=narration_volume_db,
                    narration_rate_dynamic=narration_rate_dynamic,
                    narration_apply_fx=narration_apply_fx,
                    voice_fx_func=narration_from_srt.gemini_voice_fx,
                    progress_callback=progress_callback
                )
                final_video = result['final_video']
            except Exception as e:
                send_discord_message(f"❌ Lỗi xử lý video: {e}")
                tasks_local = load_tasks()
                tasks_local[request_id]['status'] = 'error'
                tasks_local[request_id]['error'] = f'Pipeline failed: {str(e)}'
                save_tasks(tasks_local)
                return
            
            # Add [FULL] title overlay
            if title:
                send_discord_message(f"✨ Thêm tiêu đề overlay [FULL]...")
                
                try:
                    tasks_local = load_tasks()
                    if request_id not in tasks_local:
                        tasks_local[request_id] = {"task_id": request_id, "status": "running", "created_at": time.time()}
                    tasks_local[request_id]['progress'] = 90
                    save_tasks(tasks_local)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
                
                try:
                    font_path_try = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
                    if not os.path.exists(font_path_try):
                        font_path_try = "C:\\Windows\\Fonts\\arial.ttf" if os.name == "nt" else "times.ttf"
                    
                    title_text = f"[FULL] {title}"
                    title_text = title_text.replace(":", "\\:").replace("'", "\\'")
                    wrapped_text = wrap_text(title_text, max_chars_per_line=35)
                    
                    drawtext = (
                        f"drawtext=fontfile='{font_path_try}':text_align=center:text='{wrapped_text}':"
                        f"fontcolor=white:fontsize=42:box=1:boxcolor=black@0.6:boxborderw=20:"
                        f"x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,0,3)'"
                    )
                    
                    tmp_title = final_video + ".title.mp4"
                    cmd_title = ["ffmpeg", "-y", "-i", final_video, "-vf", drawtext]
                    cmd_title.extend(_preferred_video_encode_args())
                    cmd_title.extend(["-c:a", "copy", tmp_title])
                    subprocess.run(cmd_title, check=True)
                    os.replace(tmp_title, final_video)
                    send_discord_message(f"✅ Đã thêm tiêu đề overlay")
                except Exception as e:
                    send_discord_message(f"⚠️ Không thể thêm tiêu đề overlay: {e}")
            
            # Mix background audio if provided (in 1 render pass)
            if bg_choice:
                try:
                    send_discord_message(f"🎵 Đang thêm nhạc nền vào video...")
                    
                    # Find background audio file
                    discord_bot_bgaudio = os.path.join(BASE_DIR, "discord-bot", "bgaudio")
                    if os.path.isdir(discord_bot_bgaudio):
                        bgaudio_dir = discord_bot_bgaudio
                    else:
                        bgaudio_dir = os.path.join(OUTPUT_DIR, "bgaudio")
                    
                    bg_file = os.path.join(bgaudio_dir, os.path.basename(bg_choice))
                    if os.path.exists(bg_file):
                        tmp_with_bg = final_video + ".with_bg.mp4"
                        
                        # Mix background audio: loop bg, lower volume, mix with original audio
                        filter_complex = (
                            "[1:a]aloop=loop=-1:size=2e+09,volume=-14dB[bg];"
                            "[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0[a]"
                        )
                        
                        cmd_bg = [
                            "ffmpeg", "-y",
                            "-i", final_video,  # [0] video with audio
                            "-i", bg_file,       # [1] background audio
                            "-filter_complex", filter_complex,
                            "-map", "0:v",       # video from input 0
                            "-map", "[a]",       # mixed audio
                            "-c:v", "copy",      # copy video codec
                            "-c:a", "aac", "-b:a", "128k",
                            tmp_with_bg
                        ]
                        
                        subprocess.run(cmd_bg, check=True, capture_output=True)
                        os.replace(tmp_with_bg, final_video)
                        send_discord_message(f"✅ Đã thêm nhạc nền: {os.path.basename(bg_file)}")
                    else:
                        send_discord_message(f"⚠️ Không tìm thấy nhạc nền: {bg_file}")
                except Exception as e:
                    send_discord_message(f"⚠️ Lỗi khi thêm nhạc nền: {e}")
            
            # Upload to OneDrive and announce
            send_discord_message(f"☁️ Đang upload lên OneDrive...")
            
            try:
                tasks_local = load_tasks()
                if request_id not in tasks_local:
                    tasks_local[request_id] = {"task_id": request_id, "status": "running", "created_at": time.time()}
                tasks_local[request_id]['progress'] = 95
                save_tasks(tasks_local)
            except Exception as e:
                _report_and_ignore(e, "ignored")
            
            try:
                uploaded = uploadOneDrive(final_video, base_title_val)
                link = uploaded.get('downloadLink') or uploaded.get('webViewLink')
                if link:
                    send_discord_message(f"☁️ OneDrive: {link}")
            except Exception as e:
                send_discord_message(f"⚠️ Upload OneDrive thất bại: {e}")
            
            # Announce completion
            try:
                rel = to_project_relative_posix(final_video)
                view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                send_discord_message(f"🎥 Xem video: {view_link}")
                send_discord_message(f"⬇️ Tải video: {download_link}")
            except Exception as e:
                _report_and_ignore(e, "ignored")
            
            # Update task completion
            try:
                tasks_local = load_tasks()
                if request_id not in tasks_local:
                    tasks_local[request_id] = {"task_id": request_id, "created_at": time.time()}
                tasks_local[request_id]['status'] = 'completed'
                tasks_local[request_id]['progress'] = 100
                tasks_local[request_id]['video_path'] = final_video
                tasks_local[request_id]['video_file'] = [final_video]
                save_tasks(tasks_local)
            except Exception as e:
                _report_and_ignore(e, "ignored")
            
            send_discord_message(f"✅ process_video_ytdl hoàn tất: {request_id}")
            
        except Exception as e:
            import traceback
            error_msg = f"❌ process_video_ytdl error: {e}\n{traceback.format_exc()}"
            send_discord_message(error_msg)
            try:
                tasks_local = load_tasks()
                if request_id in tasks_local:
                    tasks_local[request_id]['status'] = 'error'
                    tasks_local[request_id]['error'] = str(e)
                    save_tasks(tasks_local)
            except Exception:
                pass
    
    # Run inline
    if run_in_background:
        loop = asyncio.get_event_loop()
        tracked = create_tracked_task(request_id, loop.run_in_executor(executor, _worker))
        return JSONResponse(status_code=202, content={"task_id": request_id, "started": True})
    else:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(executor, _worker)
        return JSONResponse(status_code=200, content={"task_id": request_id, "completed": True})


# Endpoint: Download playlist using yt-dlp, process each video with episode numbers
@app.get('/process_playlist_ytdl')
async def process_playlist_ytdl(
    playlist_url: str = Query(..., description='URL playlist cần tải (YouTube, Facebook playlist, v.v.)'),
    title: str = Query('', description='Tiêu đề series (dùng cho tên thư mục và overlay)'),
    max_episodes: int | None = Query(None, description='Số GROUP/TẬP tối đa sẽ xử lý (mỗi group = 4 video)'),
    run_in_background: bool = Query(True, description='Nếu True thì chạy nền và trả về ngay'),
    add_narration: bool = Query(True, description='Nếu True, tạo thuyết minh từ phụ đề và trộn vào video'),
    with_subtitles: bool = Query(True, description='Nếu True thì burn phụ đề vào video; nếu False chỉ thêm thuyết minh'),
    render_full: bool = Query(False, description='Nếu True, ghép tất cả video thành 1 video [FULL] thay vì chia group'),
    narration_voice: str = Query('vi-VN-Standard-C', description='Giọng Google TTS'),
    narration_replace_audio: bool = Query(False, description='Thay hoàn toàn audio gốc bằng thuyết minh'),
    narration_volume_db: float = Query(8.0, description='Âm lượng thuyết minh khi trộn (dB)'),
    narration_rate_dynamic: int = Query(0, description='1: dùng tốc độ nói động (1.28–1.40), 0: cố định 1.0'),
    narration_apply_fx: int = Query(1, description='1: áp EQ/tone/time filter cho giọng thuyết minh'),
    bg_choice: str | None = Query(None, description='Tên file nhạc nền (optional, áp dụng cho mỗi group/tập hoặc FULL video)'),
    request_id: str | None = Query(None, description='(internal) reuse existing task_id'),
    use_queue: bool = Query(True, description='If True enqueue the job into TASK_QUEUE instead of running inline')
):
    """Download a playlist using yt-dlp, group 4 videos into 1 episode or create FULL video.
    Similar to process_series but downloads from YouTube playlist.
    
    Flow:
    1. Extract video URLs from playlist using yt-dlp
    2. Group videos: 4 videos = 1 group/episode (Tập 1, Tập 2, ...) OR all videos → 1 FULL video
    3. For each video: download → transcribe → translate → narrate → render
    4. Concatenate videos with overlay ("Tập X" or "[FULL] Title")
    5. Apply background audio to each group or FULL video (if provided)
    6. Save to folder named safename(title)
    """
    if not request_id:
        request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    
    # If requested, enqueue into TASK_QUEUE and return immediately
    if use_queue:
        try:
            tasks_local = load_tasks()
        except Exception:
            tasks_local = {}
        
        tasks_local[request_id] = {
            "task_id": request_id,
            "status": "pending",
            "progress": 0,
            "video_path": "",
            "video_file": [],
            "title": title,
            "request_urls": [playlist_url],
            "created_at": time.time(),
            "type": 10,  # New type for playlist ytdl processing
            "task_type": "playlist_ytdl",
            "skip_queue": False,
            "add_narration": bool(add_narration),
            "narration_voice": narration_voice,
            "narration_replace_audio": narration_replace_audio,
            "narration_volume_db": narration_volume_db,
            "narration_rate_dynamic": narration_rate_dynamic,
            "narration_apply_fx": narration_apply_fx,
            "bg_choice": bg_choice,
            "with_subtitles": with_subtitles,
            "render_full": render_full,
            "max_episodes": max_episodes
        }
        try:
            save_tasks(tasks_local)
        except Exception:
            pass
        
        payload = {
            "task_id": request_id,
            "type": 10,
            "playlist_url": playlist_url,
            "title": title,
            "max_episodes": max_episodes,
            "add_narration": bool(add_narration),
            "with_subtitles": bool(with_subtitles),
            "render_full": render_full,
            "narration_voice": narration_voice,
            "narration_replace_audio": narration_replace_audio,
            "narration_volume_db": narration_volume_db,
            "narration_rate_dynamic": narration_rate_dynamic,
            "narration_apply_fx": narration_apply_fx,
            "bg_choice": bg_choice,
        }
        try:
            await enqueue_task(payload)
        except Exception:
            tasks_local = load_tasks()
            tasks_local[request_id]['status'] = 'error'
            tasks_local[request_id]['error'] = 'failed to enqueue'
            save_tasks(tasks_local)
            return JSONResponse(status_code=500, content={"error": "enqueue failed"})
        
        send_discord_message(f"📨 Đã xếp playlist ytdl task vào hàng chờ: {request_id}")
        return JSONResponse(status_code=202, content={"task_id": request_id, "started": True})
    
    def _worker():
        import subprocess, time, os, json, math
        try:
            send_discord_message(f"🔁 process_playlist_ytdl start: {playlist_url} (task {request_id})")
            
            # Create task entry
            try:
                tasks_local = load_tasks()
            except Exception:
                tasks_local = {}
            
            tasks_local[request_id] = {
                "task_id": request_id,
                "status": "running",
                "progress": 5,
                "video_path": "",
                "video_file": [],
                "title": title,
                "request_urls": [playlist_url],
                "created_at": time.time(),
                "type": 10,
                "task_type": "playlist_ytdl",
                "skip_queue": True,
                "add_narration": add_narration,
                "narration_voice": narration_voice,
                "narration_replace_audio": narration_replace_audio,
                "narration_volume_db": narration_volume_db,
                "narration_rate_dynamic": narration_rate_dynamic,
                "narration_apply_fx": narration_apply_fx,
                "with_subtitles": with_subtitles,
                "bg_choice": bg_choice,
                "render_full": render_full,
                "max_episodes": max_episodes
            }
            try:
                save_tasks(tasks_local)
            except Exception as e:
                _report_and_ignore(e, "ignored")
            
            # Determine safe folder name from title
            try:
                base_title_val = safe_filename(title) if title else url_hash(playlist_url)[:8]
            except Exception:
                base_title_val = url_hash(playlist_url)[:8]
            
            # Create output folder and finalvideo subfolder
            try:
                run_dir = os.path.join(OUTPUT_DIR, base_title_val)
                os.makedirs(run_dir, exist_ok=True)
                final_dir = os.path.join(run_dir, "finalvideo")
                os.makedirs(final_dir, exist_ok=True)
            except Exception:
                run_dir = OUTPUT_DIR
                final_dir = run_dir
            
            send_discord_message(f"📁 Thư mục lưu: {run_dir}")
            
            # Step 1: Extract video URLs from playlist using yt-dlp
            send_discord_message(f"📋 Lấy danh sách video từ playlist...")
            try:
                from yt_dlp import YoutubeDL
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'extract_flat': 'in_playlist',
                    'force_generic_extractor': False,
                }
                
                with YoutubeDL(ydl_opts) as ydl:
                    playlist_info = ydl.extract_info(playlist_url, download=False)
                    
                    if 'entries' in playlist_info:
                        video_urls = []
                        for entry in playlist_info['entries']:
                            if entry:
                                url = entry.get('url') or entry.get('webpage_url') or f"https://www.youtube.com/watch?v={entry.get('id')}"
                                video_urls.append(url)
                    else:
                        # Single video, not a playlist
                        video_urls = [playlist_url]
                
                send_discord_message(f"✅ Tìm thấy {len(video_urls)} video trong playlist")
                
            except Exception as e:
                send_discord_message(f"❌ Lỗi lấy playlist: {e}")
                tasks_local = load_tasks()
                tasks_local[request_id]['status'] = 'error'
                tasks_local[request_id]['error'] = f'Playlist extraction failed: {str(e)}'
                save_tasks(tasks_local)
                return
            
            if not video_urls:
                send_discord_message(f"⚠️ Không tìm thấy video nào trong playlist")
                tasks_local = load_tasks()
                tasks_local[request_id]['status'] = 'error'
                tasks_local[request_id]['error'] = 'No videos found in playlist'
                save_tasks(tasks_local)
                return
            
            # Step 2: Group videos (4 videos = 1 group/episode) OR render full
            total_videos = len(video_urls)
            
            # Build video_index -> group_index map
            video_to_group = {}  # video_idx (1-based) -> group_idx (1-based)
            group_map = {}  # group_idx -> [video_idx, ...]
            
            if render_full:
                # FULL mode: all videos in 1 group
                group_map[1] = list(range(1, total_videos + 1))
                for v in range(1, total_videos + 1):
                    video_to_group[v] = 1
                send_discord_message(f"📊 Chế độ FULL: ghép tất cả {total_videos} video thành 1 video")
            else:
                # Normal mode: group by 4 videos
                group_size = 4
                g_idx = 1
                v_idx = 1
                while v_idx <= total_videos:
                    end_v = min(v_idx + group_size - 1, total_videos)
                    group_videos = list(range(v_idx, end_v + 1))
                    group_map[g_idx] = group_videos
                    for v in group_videos:
                        video_to_group[v] = g_idx
                    g_idx += 1
                    v_idx += group_size
                
                # If max_episodes provided, limit groups (not individual videos)
                if max_episodes and max_episodes > 0:
                    limited_groups = {k: v for k, v in group_map.items() if k <= max_episodes}
                    group_map = limited_groups
                    # Update video URLs to only include videos in limited groups
                    videos_in_groups = []
                    for grp_videos in group_map.values():
                        videos_in_groups.extend(grp_videos)
                    video_urls = [video_urls[i-1] for i in sorted(videos_in_groups)]
                    send_discord_message(f"📊 Giới hạn {max_episodes} group → xử lý {len(video_urls)} video")
                
                total_groups = len(group_map)
                send_discord_message(f"📊 Chia thành {total_groups} group (mỗi group = 1 tập, 4 video/group)")
            
            # Storage for processed videos per index
            video_outputs = {}  # video_idx -> final_video_path
            
            # Step 3: Process each video (download → transcribe → translate → narrate)
            for v_idx, video_url in enumerate(video_urls, start=1):
                send_discord_message(f"🎬 [{v_idx}/{len(video_urls)}] Xử lý video: {video_url}")
                
                # Artifact paths for this video
                video_label = f"{base_title_val}_V{v_idx}"
                dl_video = os.path.join(run_dir, f"{video_label}_download.mp4")
                final_video = os.path.join(run_dir, f"{video_label}_processed.mp4")
                
                # Update progress
                try:
                    tasks_local = load_tasks()
                    if request_id not in tasks_local:
                        tasks_local[request_id] = {"task_id": request_id, "status": "running", "created_at": time.time()}
                    tasks_local[request_id]['progress'] = 10 + int((v_idx - 1) / len(video_urls) * 60)
                    save_tasks(tasks_local)
                except Exception as e:
                    _report_and_ignore(e, "ignored")
                
                # Check if final video already exists
                if os.path.exists(final_video):
                    send_discord_message(f"♻️ Video {v_idx} đã xử lý sẵn: {final_video}")
                    video_outputs[v_idx] = final_video
                    continue
                
                # Download video
                if os.path.exists(dl_video):
                    send_discord_message(f"♻️ Video {v_idx} đã tải sẵn: {dl_video}")
                else:
                    send_discord_message(f"⬇️ Tải video {v_idx}...")
                    try:
                        downloaded = convert_stt.download_video(video_url, dl_video)
                        if not downloaded or not os.path.exists(downloaded):
                            raise RuntimeError(f"Download failed: {video_url}")
                        send_discord_message(f"✅ Đã tải video {v_idx}")
                    except Exception as e:
                        send_discord_message(f"⚠️ Lỗi tải video {v_idx}: {e}, bỏ qua video này")
                        continue
                
                # Progress callback
                def progress_callback(step: str, pct: int):
                    try:
                        tasks_local = load_tasks()
                        if request_id in tasks_local:
                            base_progress = 10 + int((v_idx - 1) / len(video_urls) * 60)
                            video_contribution = int(pct * 0.6 / len(video_urls))
                            tasks_local[request_id]['progress'] = min(70, base_progress + video_contribution)
                            save_tasks(tasks_local)
                    except Exception:
                        pass
                
                # Process pipeline (transcribe → translate → narrate → render)
                try:
                    import narration_from_srt
                    result = process_single_video_pipeline(
                        video_path=dl_video,
                        output_dir=run_dir,
                        base_name=video_label,
                        add_narration=add_narration,
                        with_subtitles=with_subtitles,
                        narration_voice=narration_voice,
                        narration_replace_audio=narration_replace_audio,
                        narration_volume_db=narration_volume_db,
                        narration_rate_dynamic=narration_rate_dynamic,
                        narration_apply_fx=narration_apply_fx,
                        voice_fx_func=narration_from_srt.gemini_voice_fx,
                        progress_callback=progress_callback
                    )
                    
                    final_video = result['final_video']
                    video_outputs[v_idx] = final_video
                    send_discord_message(f"✅ Hoàn tất xử lý video {v_idx}")
                    
                except Exception as e:
                    send_discord_message(f"⚠️ Lỗi xử lý pipeline video {v_idx}: {e}, bỏ qua video này")
                    continue
            
            # Helper: check if group output exists
            def _group_output_exists(g_idx: int) -> bool:
                prefixes = [
                    os.path.join(run_dir, f"{base_title_val}_Tap_{g_idx}"),
                    os.path.join(final_dir, f"{base_title_val}_Tap_{g_idx}"),
                ]
                patterns = []
                for pref in prefixes:
                    patterns.append(pref + ".mp4")
                    patterns.append(pref + "_P*.mp4")
                for pat in patterns:
                    try:
                        import glob
                        for p in glob.glob(pat):
                            if os.path.isfile(p):
                                return True
                    except Exception:
                        continue
                return False
            
            # Helper: check if videos are concat-compatible
            def _can_concat_copy(files: list) -> bool:
                try:
                    def get_info(p):
                        cmd = ['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', p]
                        proc = subprocess.run(cmd, capture_output=True, text=True)
                        if proc.returncode != 0:
                            return None
                        return json.loads(proc.stdout)
                    
                    base_info = None
                    for p in files:
                        info = get_info(p)
                        if not info or 'streams' not in info:
                            return False
                        v = next((s for s in info['streams'] if s.get('codec_type') == 'video'), None)
                        a = next((s for s in info['streams'] if s.get('codec_type') == 'audio'), None)
                        if not v:
                            return False
                        if base_info is None:
                            base_info = (v.get('codec_name'), int(v.get('width', 0)), int(v.get('height', 0)), v.get('pix_fmt'))
                            base_audio = (a.get('codec_name') if a else None, int(a.get('sample_rate')) if a and a.get('sample_rate') else None, int(a.get('channels')) if a and a.get('channels') else None)
                        else:
                            cur_v = (v.get('codec_name'), int(v.get('width', 0)), int(v.get('height', 0)), v.get('pix_fmt'))
                            cur_a = (a.get('codec_name') if a else None, int(a.get('sample_rate')) if a and a.get('sample_rate') else None, int(a.get('channels')) if a and a.get('channels') else None)
                            if cur_v != base_info:
                                return False
                            if base_audio[1] and cur_a[1] and base_audio[1] != cur_a[1]:
                                return False
                            if base_audio[2] and cur_a[2] and base_audio[2] != cur_a[2]:
                                return False
                    return True
                except Exception:
                    return False
            
            # Helper: check encoder availability
            def _has_encoder(enc_name: str) -> bool:
                try:
                    p = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True)
                    return enc_name in p.stdout
                except Exception:
                    return False
            
            # Step 4: Concatenate groups (4 videos → 1 group/episode)
            final_groups = []
            
            for g_idx in sorted(group_map.keys()):
                # Skip if group already exists
                if _group_output_exists(g_idx):
                    send_discord_message(f"♻️ Group {g_idx} đã tồn tại, bỏ qua")
                    try:
                        existing = os.path.join(final_dir, f"{base_title_val}_Tap_{g_idx}.mp4")
                        if os.path.exists(existing):
                            final_groups.append(existing)
                    except Exception:
                        pass
                    continue
                
                # Collect videos for this group
                video_indices = group_map[g_idx]
                group_videos = []
                for v_idx in video_indices:
                    if v_idx in video_outputs:
                        group_videos.append(video_outputs[v_idx])
                
                if not group_videos:
                    send_discord_message(f"⚠️ Group {g_idx} không có video nào, bỏ qua")
                    continue
                
                if render_full:
                    send_discord_message(f"🎬 Ghép {len(group_videos)} video thành 1 video FULL...")
                else:
                    send_discord_message(f"🎬 Ghép {len(group_videos)} video thành Group {g_idx} (Tập {g_idx})...")
                
                # Concatenate videos - use _FULL filename for render_full mode
                if render_full:
                    group_out = os.path.join(final_dir, f"{base_title_val}_FULL.mp4")
                else:
                    group_out = os.path.join(final_dir, f"{base_title_val}_Tap_{g_idx}.mp4")
                try:
                    if _can_concat_copy(group_videos):
                        concat_list = os.path.join(run_dir, f"concat_G{g_idx}.txt")
                        with open(concat_list, 'w', encoding='utf-8') as f:
                            for p in group_videos:
                                f.write(f"file '{os.path.abspath(p)}'\n")
                        subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list, '-c', 'copy', group_out], check=True)
                    else:
                        enc = 'libx265' if _has_encoder('libx265') else 'libx264'
                        if enc == 'libx265':
                            v_args = ['-c:v', 'libx265', '-preset', 'slow', '-crf', '24', '-pix_fmt', 'yuv420p', '-tag:v', 'hvc1']
                        else:
                            v_args = ['-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-pix_fmt', 'yuv420p']
                        a_args = ['-c:a', 'aac', '-b:a', '128k']
                        ff_args = ['ffmpeg', '-y']
                        for p in group_videos:
                            ff_args.extend(['-i', p])
                        concat_filter = f"concat=n={len(group_videos)}:v=1:a=1"
                        ff_args.extend(['-filter_complex', concat_filter, '-vsync', 'vfr'])
                        ff_args.extend(v_args)
                        ff_args.extend(a_args)
                        ff_args.append(group_out)
                        subprocess.run(ff_args, check=True)
                except Exception as e:
                    send_discord_message(f"⚠️ Lỗi ghép group {g_idx}: {e}")
                    continue
                
                # Add title overlay "Tập X" or "[FULL] Title"
                if title:
                    try:
                        font_path_try = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
                        if not os.path.exists(font_path_try):
                            font_path_try = "C:\\Windows\\Fonts\\arial.ttf" if os.name == "nt" else "times.ttf"
                        
                        if render_full:
                            title_text = f"[FULL] {title}"
                        else:
                            title_text = f"{title} - TẬP {g_idx}"
                        title_text = title_text.replace(":", "\\:").replace("'", "\\'")
                        wrapped_text = wrap_text(title_text, max_chars_per_line=35)
                        
                        drawtext = (
                            f"drawtext=fontfile='{font_path_try}':text_align=center:text='{wrapped_text}':"
                            f"fontcolor=white:fontsize=42:box=1:boxcolor=black@0.6:boxborderw=20:"
                            f"x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,0,3)'"
                        )
                        
                        tmp_title = group_out + ".title.mp4"
                        cmd_title = ["ffmpeg", "-y", "-i", group_out, "-vf", drawtext]
                        cmd_title.extend(_preferred_video_encode_args())
                        cmd_title.extend(["-c:a", "copy", tmp_title])
                        subprocess.run(cmd_title, check=True)
                        os.replace(tmp_title, group_out)
                    except Exception as e:
                        send_discord_message(f"⚠️ Không thể thêm title overlay group {g_idx}: {e}")
                
                # Mix background audio if provided
                if bg_choice:
                    try:
                        send_discord_message(f"🎵 Đang thêm nhạc nền cho group {g_idx}...")
                        
                        discord_bot_bgaudio = os.path.join(BASE_DIR, "discord-bot", "bgaudio")
                        if os.path.isdir(discord_bot_bgaudio):
                            bgaudio_dir = discord_bot_bgaudio
                        else:
                            bgaudio_dir = os.path.join(OUTPUT_DIR, "bgaudio")
                        
                        bg_file = os.path.join(bgaudio_dir, os.path.basename(bg_choice))
                        if os.path.exists(bg_file):
                            tmp_with_bg = group_out + ".with_bg.mp4"
                            
                            filter_complex = (
                                "[1:a]aloop=loop=-1:size=2e+09,volume=-14dB[bg];"
                                "[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0[a]"
                            )
                            
                            cmd_bg = [
                                "ffmpeg", "-y",
                                "-i", group_out,
                                "-i", bg_file,
                                "-filter_complex", filter_complex,
                                "-map", "0:v",
                                "-map", "[a]",
                                "-c:v", "copy",
                                "-c:a", "aac", "-b:a", "128k",
                                tmp_with_bg
                            ]
                            
                            subprocess.run(cmd_bg, check=True, capture_output=True)
                            os.replace(tmp_with_bg, group_out)
                            send_discord_message(f"✅ Đã thêm nhạc nền group {g_idx}: {os.path.basename(bg_file)}")
                        else:
                            send_discord_message(f"⚠️ Không tìm thấy nhạc nền: {bg_file}")
                    except Exception as e:
                        send_discord_message(f"⚠️ Lỗi khi thêm nhạc nền group {g_idx}: {e}")
                
                # Split if >3600s
                try:
                    _, _, group_dur = get_media_info(group_out)
                except Exception:
                    group_dur = None
                
                if group_dur and group_dur > 3600:
                    parts = math.ceil(group_dur / 3600)
                    for p in range(parts):
                        start = p * 3600
                        outp = os.path.join(final_dir, f"{base_title_val}_Tap_{g_idx}_P{p+1}.mp4")
                        subprocess.run(['ffmpeg', '-y', '-ss', str(start), '-i', group_out, '-t', '3600', '-c', 'copy', outp], check=True)
                        final_groups.append(outp)
                    # Announce split parts
                    for p in range(parts):
                        outp = os.path.join(final_dir, f"{base_title_val}_Tap_{g_idx}_P{p+1}.mp4")
                        if os.path.exists(outp):
                            try:
                                uploaded = uploadOneDrive(outp, base_title_val)
                                link = uploaded.get('downloadLink') or uploaded.get('webViewLink')
                                rel = to_project_relative_posix(outp)
                                view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                                download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                                send_discord_message(f"🎥 Xem tập {g_idx} phần {p+1}: {view_link}")
                                send_discord_message(f"⬇️ Tải tập {g_idx} phần {p+1}: {download_link}")
                            except Exception as e:
                                _report_and_ignore(e, "ignored")
                else:
                    final_groups.append(group_out)
                    # Announce group
                    try:
                        uploaded = uploadOneDrive(group_out, base_title_val)
                        link = uploaded.get('downloadLink') or uploaded.get('webViewLink')
                        rel = to_project_relative_posix(group_out)
                        view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                        download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                        send_discord_message(f"🎥 Xem tập {g_idx}: {view_link}")
                        send_discord_message(f"⬇️ Tải tập {g_idx}: {download_link}")
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
                
                send_discord_message(f"✅ Hoàn tất Group {g_idx}")
            
            # Update final task status
            try:
                tasks_local = load_tasks()
                if request_id not in tasks_local:
                    tasks_local[request_id] = {"task_id": request_id, "created_at": time.time()}
                tasks_local[request_id]['status'] = 'completed'
                tasks_local[request_id]['progress'] = 100
                tasks_local[request_id]['video_path'] = final_groups[0] if final_groups else ""
                tasks_local[request_id]['video_file'] = final_groups
                save_tasks(tasks_local)
            except Exception as e:
                _report_and_ignore(e, "ignored")
            
            send_discord_message(f"✅ process_playlist_ytdl hoàn tất: {len(final_groups)} group/tập từ {len(video_urls)} video")
            
        except Exception as e:
            import traceback
            error_msg = f"❌ process_playlist_ytdl error: {e}\n{traceback.format_exc()}"
            send_discord_message(error_msg)
            try:
                tasks_local = load_tasks()
                if request_id in tasks_local:
                    tasks_local[request_id]['status'] = 'error'
                    tasks_local[request_id]['error'] = str(e)
                    save_tasks(tasks_local)
            except Exception:
                pass
    
    # Run inline
    if run_in_background:
        loop = asyncio.get_event_loop()
        tracked = create_tracked_task(request_id, loop.run_in_executor(executor, _worker))
        return JSONResponse(status_code=202, content={"task_id": request_id, "started": True})
    else:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(executor, _worker)
        return JSONResponse(status_code=200, content={"task_id": request_id, "completed": True})


# Endpoint: convert a public video URL to Chinese SRT using yt-dlp + whisper
@app.post("/convert_stt")
async def api_convert_stt(
    url: str = Query(..., description="Video URL to download and transcribe"),
    title: str = Query("", description="Title to assign to the generated video"),
    run_in_background: bool = Query(True, description="If true, enqueue task for worker and return task_id immediately"),
    add_narration: bool = Query(False, description="If true, synthesize narration from SRT and mix/replace into output"),
    narration_voice: str = Query("vi-VN-Standard-C", description="Google TTS voice name"),
    narration_replace_audio: bool = Query(False, description="Replace original audio with narration (instead of mixing)"),
    narration_volume_db: float = Query(-4.0, description="Narration volume gain (dB) when mixing"),
    narration_enabled: bool | None = Query(None, description="Enable/disable narration TTS generation (overrides add_narration if provided)"),
):
    try:
        send_discord_message(f"🔁 convert_stt request: {url}")

        # Create the task early and enqueue immediately — worker will perform
        # the download, transcription, translation and burn steps.
        request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        title_slug = extract_slug(title or url)
        final_video_path = os.path.join(OUTPUT_DIR, f"{title_slug}_video.mp4")

        # Determine effective narration toggle (new param overrides old if provided)
        _add_narr = add_narration if narration_enabled is None else bool(narration_enabled)

        tasks = load_tasks()
        task_info = {
            "task_id": request_id,
            "status": "pending",
            "progress": 0,
            "video_path": final_video_path,
            "video_file": [],
            "title": title,
            "downloaded_video": "",
            "burned_video": "",
            "srt_file": "",
            "voice": "",
            "bg_choice": None,
            "refresh": False,
            "temp_videos": [],
            "request_urls": [url],
            "created_at": time.time(),
            "type": 4,
            "part_duration": 3600,
            "start_from_part": 1,
            "total_parts": 0,
            "current_part": 0,
            "add_narration": _add_narr,
            "narration_voice": narration_voice,
            "narration_replace_audio": narration_replace_audio,
            "narration_volume_db": narration_volume_db
        }
        tasks[request_id] = task_info
        save_tasks(tasks)

        if run_in_background:
            # Enqueue for worker to pick up and do the convert_stt preprocessing flow (type=7).
            # This flow is separate from the TikTok Large Video flow (type=4).
            await enqueue_task({
                "task_id": request_id,
                "urls": [url],
                # No story_url — worker will download & transcribe the provided URL
                "story_url": "",
                # Instruct worker: this convert_stt flow must NOT generate TTS
                # and should NOT add background music.
                "skip_tts": True,
                "bg_choice": "__NO_BG__",
                "merged_video_path": "",
                "final_video_path": final_video_path,
                "title_slug": title_slug,
                "key_file": "key.json",
                "title": title,
                "voice": "",
                "type": 7,
                "refresh": False,
                "part_duration": 3600,
                "start_from_part": 1,
                "add_narration": _add_narr,
                "narration_voice": narration_voice,
                "narration_replace_audio": narration_replace_audio,
                "narration_volume_db": narration_volume_db
            })

            send_discord_message(f"📨 Đã xếp task convert_stt vào hàng chờ: {request_id}")
            return JSONResponse({"task_id": request_id})

        # Synchronous path: download → transcribe → translate → burn → optional narration → upload
        try:
            # Ensure unique filenames per request to avoid reusing previous outputs
            ts_suffix = request_id.replace(':', '').replace('-', '').replace(' ', '')
            base_prefix = os.path.join(OUTPUT_DIR, f"{title_slug}_{ts_suffix}")

            # 1) Download
            out_video = base_prefix + ".mp4"
            dl = download_video_url(url, out_video, retries=3, delay=2, target_duration=None, fail_fast=True)
            if not dl or not os.path.exists(out_video):
                raise RuntimeError("Download failed")

            # 2) Transcribe
            raw_srt = base_prefix + ".srt"
            vi_srt = base_prefix + ".vi.srt"
            try:
                import convert_stt as cs
            except Exception:
                cs = None

            if cs and hasattr(cs, 'transcribe'):
                res_srt_path = cs.transcribe(out_video, task_id=request_id)
            else:
                wav = base_prefix + ".wav"
                subprocess.run(['ffmpeg', '-y', '-i', out_video, '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', wav], check=True, capture_output=True)
                whisper_cmd = ['whisper', wav, '--model', 'small', '--output_format', 'srt', '--output_dir', OUTPUT_DIR]
                res = subprocess.run(whisper_cmd, capture_output=True, text=True)
                res_srt_path = os.path.splitext(wav)[0] + '.srt' if res.returncode == 0 and os.path.exists(os.path.splitext(wav)[0] + '.srt') else None
            if not res_srt_path or not os.path.exists(res_srt_path):
                raise RuntimeError("Transcription failed")

            # 3) Translate to Vietnamese if needed
            try:
                if res_srt_path.endswith('.vi.srt'):
                    os.replace(res_srt_path, vi_srt)
                else:
                    api_key = os.environ.get('GEMINI_API_KEY_Translate') or os.environ.get('GOOGLE_TTS_API_KEY')
                    translated = translate_srt_file(res_srt_path, output_srt=vi_srt, task_id=request_id)
                    if not translated or not os.path.exists(translated):
                        os.replace(res_srt_path, raw_srt)
            except Exception:
                if os.path.exists(res_srt_path):
                    os.replace(res_srt_path, raw_srt)

            # 4) Burn subtitles (skip TikTok-specific render). Use the original
            # downloaded video as the source for subtitle + narration mixing to
            # avoid creating extra `{title}.tiktok.mp4` files.
            tiktok_out = out_video
            try:
                use_srt = vi_srt if os.path.exists(vi_srt) else raw_srt
                # Prepare ASS if needed for later mixing, but do not re-encode here.
                try:
                    from convert_srt_to_ass import convert as convert_srt_to_ass_convert
                    ass_path_local = use_srt.replace('.srt', '.ass')
                    try:
                        convert_srt_to_ass_convert(use_srt, ass_path_local, 30, 11, "Noto Sans", 20, 150)
                    except Exception as e:
                        _report_and_ignore(e, "ignored")
                except Exception as e:
                    _report_and_ignore(e, "ignored")
            except Exception as e:
                send_discord_message(f"⚠️ Burn subtitles preparation failed: {e}")

            # 5) Optional narration
            final_out = tiktok_out
            if _add_narr:
                use_srt = vi_srt if os.path.exists(vi_srt) else (raw_srt if os.path.exists(raw_srt) else None)
                if use_srt:
                    nar_tmp = base_prefix + ".nar.flac"
                    nar_audio, _meta = narration_from_srt.build_narration_schedule(use_srt, nar_tmp, voice_name=narration_voice, speaking_rate=1.0, lead=0.0, meta_out=None, trim=False, tmp_subdir=request_id)
                    narr_out = base_prefix + ".narr.mp4"
                    narration_from_srt.mix_narration_into_video(tiktok_out, nar_audio, narr_out, narration_volume_db=narration_volume_db if narration_volume_db is not None else 3.0, replace_audio=narration_replace_audio, extend_video=True, shift_sec=0.0, video_volume_db=-3.0)
                    final_out = narr_out

            # 6) Upload to Drive and return link
            try:
                existing_sched = []
                schedule_file = os.path.join(BASE_DIR, 'cache', 'tiktok_upload_queue.json')
                if os.path.exists(schedule_file):
                    try:
                        with open(schedule_file, 'r', encoding='utf8') as sfh:
                            existing_sched = json.load(sfh)
                    except Exception:
                        existing_sched = []
            except Exception:
                existing_sched = []
            # Announce sandbox view/download links for the final output
            # ensure `link` is always defined (upload may be skipped)
            link = ''
            try:
                rel = to_project_relative_posix(final_out)
                uploaded = uploadOneDrive(final_out,title)
                link = uploaded.get('downloadLink') or uploaded.get('webViewLink')
                view_link = "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(rel)
                download_link = "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(rel)
                send_discord_message("🎥 Xem video:" + view_link)
                send_discord_message("⬇️ Tải video:" + download_link)
            except Exception as e:
                _report_and_ignore(e, "ignored")
            # Update task record
            tasks = load_tasks()
            t = tasks.get(request_id, {})
            t['status'] = 'completed'
            t['progress'] = 100
            t['video_file'] = [final_out]
            t['video_path'] = final_out
            t['drive_link'] = link
            tasks[request_id] = t
            save_tasks(tasks)

            return JSONResponse({
                "output": final_out,
                "drive_link": link,
                "sandbox_view": "https://sandbox.travel.com.vn/api/download-video?video_name=" + quote_plus(to_project_relative_posix(final_out)),
                "sandbox_download": "https://sandbox.travel.com.vn/api/download-video?download=1&video_name=" + quote_plus(to_project_relative_posix(final_out))
            })
        except Exception as e:
            logger.exception("convert_stt synchronous flow failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("convert_stt error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/translate_srt")
def api_translate_srt(
    srt_path: str = Query(..., description="Path to srt file on server (absolute or relative to project)"),
    api_key: str | None = None,
    model: str | None = None,
    bilingual: bool = Query(False, description="If true, output SRT will include original + translation lines"),
    context_window: int = Query(2, description="Number of neighboring subtitle lines to include as context for translation (each side)."),
):
    """Translate an existing SRT file to Vietnamese using Gemini and return the translated SRT."""
    try:
        # Resolve relative paths to project
        if not os.path.isabs(srt_path):
            srt_path = os.path.join(BASE_DIR, srt_path)

        if not os.path.exists(srt_path):
            raise HTTPException(status_code=404, detail=f"SRT file not found: {srt_path}")

        # Determine output path alongside input with .vi.srt
        base_no_ext = os.path.splitext(srt_path)[0]
        out_path = base_no_ext + ".vi.srt"
        # Use a generated task id for this direct endpoint translate
        task_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        out = translate_srt_file(
            srt_path,
            output_srt=out_path,
            task_id=task_id,
        )
        if not out or not os.path.exists(out):
            raise HTTPException(status_code=500, detail="Translation failed")
        return FileResponse(out, media_type="text/plain", filename=os.path.basename(out))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("translate_srt error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


import narration_from_srt


@app.post("/add_narration_from_srt")
async def add_narration_from_srt(
    video_path: str = Query(..., description="Đường dẫn video nguồn (absolute/relative)"),
    srt_path: str = Query(..., description="Đường dẫn file SRT để đọc và đồng bộ thời gian"),
    output_path: str | None = Query(None, description="Đường dẫn video output; nếu trống sẽ tự đặt cùng thư mục"),
    voice: str = Query("vi-VN-Standard-C", description="Giọng Google TTS"),
    speaking_rate: float = Query(1.0, description="Tốc độ nói Google TTS (ví dụ 1.4)"),
    replace_audio: bool = Query(False, description="Nếu True, thay hoàn toàn audio gốc bằng thuyết minh"),
    narration_volume_db: float = Query(-4.0, description="Âm lượng thuyết minh khi trộn (dB, âm là giảm)"),
    extend_video: bool = Query(True, description="Kéo dài video (freeze frame cuối) để thuyết minh phát hết"),
    enabled: bool = Query(True, description="Bật/tắt việc tạo TTS thuyết minh từ SRT"),
):
    request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    try:
        def _resolve(p: str) -> str:
            if os.path.isabs(p):
                return p
            if os.path.exists(os.path.join(OUTPUT_DIR, p)):
                return os.path.join(OUTPUT_DIR, p)
            return os.path.join(BASE_DIR, p)

        vpath = _resolve(video_path)
        spath = _resolve(srt_path)
        if not os.path.exists(vpath):
            raise HTTPException(status_code=404, detail=f"Video not found: {video_path}")
        if not os.path.exists(spath):
            raise HTTPException(status_code=404, detail=f"SRT not found: {srt_path}")

        if not output_path:
            base, _ = os.path.splitext(os.path.basename(vpath))
            output_path = os.path.join(OUTPUT_DIR, f"{base}_narration.mp4")
        elif not os.path.isabs(output_path):
            output_path = os.path.join(OUTPUT_DIR, output_path)

        if not enabled:
            # No-op: just copy input video to output for consistency
            subprocess.run([
                "ffmpeg", "-y", "-i", vpath, "-c", "copy", output_path
            ], check=True)
            send_discord_message("ℹ️ Bỏ qua tạo TTS (enabled=false). Trả về bản sao video gốc: %s", output_path)
            return {"output": output_path, "schedule_meta": None, "narration_enabled": False}

        tmp_narr = os.path.splitext(output_path)[0] + ".flac"
        # Use schedule-based narration so each line starts at SRT start and plays fully (no trimming)
        nar_audio, meta_path = narration_from_srt.build_narration_schedule(
            spath, tmp_narr,
            voice_name=voice,
            speaking_rate=speaking_rate,
            lead=0.0,
            meta_out=None,
            trim=False,
            tmp_subdir=request_id if 'request_id' in locals() else None
        )
        out = narration_from_srt.mix_narration_into_video(
            vpath, nar_audio, output_path,
            narration_volume_db=narration_volume_db,
            replace_audio=replace_audio,
            extend_video=extend_video,
            shift_sec=0.0,
        )
        send_discord_message(f"🗣️ Đã thêm thuyết minh vào video: {out}")
        return {"output": out, "schedule_meta": meta_path, "narration_enabled": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("add_narration_from_srt error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))




@app.get('/api/tiktok_upload')
def api_tiktok_upload(
     video_path: str = Query(..., description="Path to video file (absolute or relative to OUTPUT_DIR)"),
    title: str = Query('', description="Optional title for upload"),
    tags: str | None = Query(None, description="Optional comma-separated tags"),
    cookies: str | None = Query(None, description="Optional cookies file path for uploader"),
    no_headless: bool = Query(False, description="Run uploader with --no-headless flag"),
    run_in_background: bool = Query(False, description="(ignored) run in background")
):
    from tiktok_uploader import TikTokUploader
    """Manual TikTok upload endpoint - completely independent from scheduler.

    This endpoint runs the Python Playwright uploader in a separate thread.
    Does NOT interact with tiktok_upload_queue.json or task scheduling system.
    Use this for direct, immediate uploads without scheduling.
    """
    try:
        # resolve video path to an absolute path inside the project or OUTPUT_DIR
        if not os.path.isabs(video_path):
            candidate = os.path.join(OUTPUT_DIR, video_path)
            if os.path.exists(candidate):
                vpath = candidate
            else:
                vpath = os.path.join(BASE_DIR, video_path)
        else:
            vpath = video_path

        if not os.path.exists(vpath):
            raise HTTPException(status_code=404, detail=f"Video not found: {video_path}")

        tags_list = tags.split(',') if tags else []

        upload_dir = os.path.join(BASE_DIR, 'tiktokupload')

        def do_upload():
            import sys
            # Run uploader in a separate Python process to avoid Playwright
            # sync API detecting the main event loop.
            try:
                script = os.path.join(BASE_DIR, 'tiktok_uploader.py')
                cmd = [
                    sys.executable,
                    script,
                    '--video', vpath,
                    '--caption', title or '',
                ]
                if tags_list:
                    cmd += ['--tags', ','.join(tags_list)]
                # Resolve cookies: if caller provided a name, look under Cookies/ folder
                resolved_cookies = None
                if cookies:
                    if os.path.isabs(cookies) and os.path.exists(cookies):
                        resolved_cookies = cookies
                    else:
                        # try Cookies/<name> and Cookies/<name>.json
                        cbase = os.path.join(BASE_DIR, 'Cookies')
                        candidate = os.path.join(cbase, cookies)
                        candidate_json = os.path.join(cbase, cookies + '.json')
                        if os.path.exists(candidate):
                            resolved_cookies = candidate
                        elif os.path.exists(candidate_json):
                            resolved_cookies = candidate_json
                        else:
                            # fallback: use provided value as-is
                            resolved_cookies = cookies
                if resolved_cookies:
                    cmd += ['--cookies', resolved_cookies]
                if no_headless:
                    cmd += ['--no-headless']

                proc = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True)
                try:
                    logger.debug('tiktok uploader stdout: %s', proc.stdout)
                    logger.debug('tiktok uploader stderr: %s', proc.stderr)
                except Exception:
                    pass
                return {
                    'ok': proc.returncode == 0,
                    'rc': proc.returncode,
                    'stdout': proc.stdout,
                    'stderr': proc.stderr,
                }
            except Exception:
                logger.exception('do_upload subprocess error')
                return False

        # Run the sync Playwright uploader in a dedicated thread and wait
        # so we don't invoke sync_playwright() inside the event loop thread.
        import threading
        result = {}
        def _worker():
            try:
                result['resp'] = do_upload()
            except Exception as e:
                result['exc'] = e

        thr = threading.Thread(target=_worker)
        thr.start()
        thr.join()
        if 'exc' in result:
            raise result['exc']
        resp = result.get('resp') or {}
        ok = bool(resp.get('ok'))
        if ok:
            return JSONResponse(status_code=200, content={"ok": True, "video": vpath, "stdout": resp.get('stdout', '')})
        else:
            # include stderr/stdout for debugging
            return JSONResponse(status_code=500, content={
                "ok": False,
                "error": "upload failed",
                "rc": resp.get('rc'),
                "stdout": resp.get('stdout', ''),
                "stderr": resp.get('stderr', ''),
            })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("tiktok_upload error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


