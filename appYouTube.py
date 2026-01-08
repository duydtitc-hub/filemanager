from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.responses import StreamingResponse, HTMLResponse, Response
import os, re, logging, hashlib, subprocess, json, math, requests
from datetime import datetime
from bs4 import BeautifulSoup
from yt_dlp import YoutubeDL
import openai
from openai import AsyncOpenAI
import tempfile
from typing import List
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import time
from fastapi import HTTPException
from google import genai
from google.genai import types
import wave
import base64
import struct
import signal
import random
from urllib.parse import urljoin
import shutil
from urllib.parse import quote, quote_plus
from appTest import upload_bytes_to_drive
from DiscordMethod import send_discord_message
from GetTruyen import get_novel_text_laophatgia,get_novel_text_vivutruyen
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
import os
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BOT_DIR, ".env"))
# Cấu hình logging
# ==============================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("truyen-video")
app = FastAPI(title="Truyen Video API")
openai.api_key = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
POLL_INTERVAL = 5  # giây chờ file audio sẵn sàng
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
VEO3_CACHE_DIR = os.path.join(OUTPUT_DIR, "veo3_clips")
SORA_CACHE_DIR = os.path.join(OUTPUT_DIR, "sora_clips")
VIDEO_CACHE_DIR = os.path.join(OUTPUT_DIR, "video_cache")

# Gain (in dB) to apply to narration audio when rendering YouTube videos.
# Positive values boost the voice (e.g. 4-8 dB). Set to 0 to leave unchanged.
NARRATION_GAIN_DB = 6

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(VEO3_CACHE_DIR, exist_ok=True)
os.makedirs(SORA_CACHE_DIR, exist_ok=True)
os.makedirs(VIDEO_CACHE_DIR, exist_ok=True)
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

# def generate_audio_fpt(text: str, title_slug: str, key_manager: FPTKeyManager, voice="banmai"):
#     final_audio = os.path.join(OUTPUT_DIR, f"{title_slug}.wav")
#     if os.path.exists(final_audio):
#         send_discord_message("🎧 Dùng cache audio: %s", final_audio)
#         return final_audio

#     if not os.path.exists(OUTPUT_DIR):
#         os.makedirs(OUTPUT_DIR)

#     chunk_size = 2000
#     chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
#     audio_segments = []

#     for i, part in enumerate(chunks, 1):
#         part_file = os.path.join(OUTPUT_DIR, f"{title_slug}_part_{i}.mp3")
#         send_discord_message("🎙️ Tạo đoạn audio %d/%d (%s ký tự)...", i, len(chunks), len(part))
#         api_key = key_manager.get_key(chunk_size)
#         seg = create_audio_chunk_fpt(part, part_file, api_key, voice)
#         audio_segments.append(seg)

#     combined = sum(audio_segments, AudioSegment.empty())
#     combined.export(final_audio, format="wav")
#     send_discord_message("✅ Hoàn tất tạo audio: %s", final_audio)
#     return final_audio
# ============================================================================================

# ==============================
# Hàm phụ trợ
# ==============================
TASK_FILE = os.path.join(CACHE_DIR, "tasks.json")

def load_tasks():
    if os.path.exists(TASK_FILE):
        with open(TASK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_tasks(tasks):
    with open(TASK_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2, ensure_ascii=False)

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
def enhance_audio(input_path: str) -> str:
    """
    Dùng ffmpeg để tăng tốc và tinh chỉnh giọng giống CapCut.

    Produces a FLAC file with suffix _capcut.flac. If input is .wav or .flac,
    the output is <base>_capcut.flac. Uses cached output when present.
    """
    base = os.path.splitext(input_path)[0]
    output_path = f"{base}_capcut.flac"
    if os.path.exists(output_path):
        send_discord_message("🎧 Dùng cache audio đã chỉnh: %s", output_path)
        return output_path

    send_discord_message("⚙️ Đang tăng tốc và lọc âm thanh bằng ffmpeg (FLAC output)...")
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter:a", "atempo=1.40,asetrate=29000,aresample=48000,highpass=f=200,lowpass=f=8000",
        "-c:a", "flac",
        output_path
    ]
    subprocess.run(cmd, check=True)
    send_discord_message("✅ Đã tạo audio đã chỉnh tốc: %s", output_path)
    return output_path
def enhance_audio_gemini(input_path: str) -> str:
    """
    Dùng ffmpeg để tăng tốc và tinh chỉnh giọng giống CapCut.

    Produces a FLAC file with suffix _capcut.flac. Works with .wav or .flac inputs.
    """
    base = os.path.splitext(input_path)[0]
    output_path = f"{base}_capcut.flac"
    if os.path.exists(output_path):
        send_discord_message("🎧 Dùng cache audio đã chỉnh: %s", output_path)
        return output_path

    send_discord_message("⚙️ Đang tăng tốc và lọc âm thanh bằng ffmpeg (FLAC output)...")
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter:a", "atempo=1.4",
        "-c:a", "flac",
        output_path
    ]
    subprocess.run(cmd, check=True)
    send_discord_message("✅ Đã tạo audio đã chỉnh tốc: %s", output_path)
    return output_path
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

def get_novel_text(url: str) -> str:
    """
    Lấy toàn bộ nội dung truyện (MetruyenHot, TruyenFull, v.v.)
    - MetruyenHot: hỗ trợ cả <p> text thường và <p> có text trong attribute lạ
    - Tự loại watermark
    - Dùng cache
    """
    info = extract_domain_structure(url)
    base_url = re.match(r"https?://[^/]+", url).group(0)
    cache_file = os.path.join(CACHE_DIR, f"{url_hash(url)}.txt")

    # Dùng cache nếu có
    if os.path.exists(cache_file):
        send_discord_message("📦 Dùng cache truyện từ %s", cache_file)
        with open(cache_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return content
            else:
                logger.warning("⚠️ File cache rỗng, tải lại nội dung...")

    all_text = ""
    chapter = 1

    while url:
        send_discord_message("📖 Đang tải chương %s: %s", chapter, url)
        try:
            response = requests.get(url, timeout=15)
            response.encoding = "utf-8"
        except Exception as e:
            logger.warning("❌ Lỗi tải trang %s: %s", url, e)
            break

        soup = BeautifulSoup(response.text, "lxml")

        # === Xóa watermark & script ===
        for wm in soup.select("div.show-c, div.ads, script, style"):
            wm.decompose()

        domain = re.search(r"https?://([^/]+)/", url).group(1)
        clean_text = ""

        # === MetruyenHot ===
        if "metruyenhot" in domain:
            container = soup.select_one("div.book-list.full-story.content.chapter-c")
            if not container:
                logger.warning("❌ Không tìm thấy nội dung truyện trong MetruyenHot")
                break

            paragraphs = []
            default_attrs = {"class", "style", "onmousedown", "onselectstart", "oncopy", "oncut"}

            for p in container.find_all("p"):
                text_content = ""

                # Nếu <p> có text trực tiếp
                if p.get_text(strip=True):
                    text_content = p.get_text(" ", strip=True)
                else:
                    # Nếu text nằm trong attribute lạ
                    for attr, val in p.attrs.items():
                        if attr not in default_attrs and isinstance(val, str) and val.strip():
                            text_content = val.strip()
                            break

                # Bỏ watermark hoặc dòng rác
                if text_content and not re.search(r"metruyen\s*hot", text_content, re.I):
                    paragraphs.append(text_content)

            clean_text = "\n\n".join(paragraphs)
        elif "laophatgia" in domain:
            return get_novel_text_laophatgia(url)
        elif "vivutruyen" in domain or "vivutruyen2" in domain:

            return get_novel_text_vivutruyen(url)
        # === TruyenFull hoặc site khác ===
        else:
            content = soup.select_one(info["content_selector"])
            if not content:
                logger.warning("❌ Không tìm thấy nội dung tại %s", url)
                break

            # Xóa các watermark hoặc phần quảng cáo
            for wm in content.select("div.show-c, div.ads, script, style"):
                wm.decompose()

            clean_text = content.get_text("\n", strip=True)

        # === Làm sạch nội dung ===
        clean_text = re.sub(r"(?im)\b(chương|chuong)\s*\d+[\.:–-]?\s*", "", clean_text)
        clean_text = re.sub(r"\b\d+\.\s*", "", clean_text)
        clean_text = re.sub(r"(?m)^\d+[\.:–-]?\s*", "", clean_text)
        clean_text = re.sub(r"\n{2,}", "\n\n", clean_text).strip()

        all_text += clean_text + "\n\n"

        # === Xác định link chương tiếp theo ===
        next_url = None
        if "truyenfull" in domain:
            next_link = soup.find("a", id="next_chap")
            if next_link and next_link.get("href"):
                next_url = next_link["href"]
        elif "metruyenhot" in domain:
            next_link = soup.find("a", attrs={"rel": "next"}) or \
                        soup.find("a", string=re.compile("Tiếp", re.I))
            if next_link and next_link.get("href"):
                next_url = next_link["href"]

        # Fallback chung
        if not next_url:
            for a in soup.select("a"):
                href = a.get("href")
                if href and re.search(r"(chương\s*tiếp|tiếp|next)", a.get_text(strip=True), re.I):
                    next_url = href
                    break

        # Chuẩn hóa URL
        if next_url and not next_url.startswith("javascript"):
            url = next_url if next_url.startswith("http") else base_url + next_url
            chapter += 1
        else:
            send_discord_message("🚪 Hết chương tại: %s", url)
            url = None
        # === Ghi cache từng chương (overwrite) === 
    with open(cache_file, "w", encoding="utf-8") as f: 
        f.write(all_text) 
        
    return all_text.strip()
def split_text_with_space(text, max_chars=4096):
    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + max_chars, text_length)
        chunk = text[start:end]

        # Nếu chưa hết text, cố gắng ngắt ở dấu chấm gần nhất trước end
        if end < text_length:
            last_dot = chunk.rfind(".")
            if last_dot != -1 and last_dot > max_chars * 0.7:  # chỉ cắt nếu dấu chấm ở nửa sau đoạn
                end = start + last_dot + 1
                chunk = text[start:end]

        chunks.append(chunk.strip())
        start = end

    send_discord_message("✂️ Chia truyện thành %d đoạn", len(chunks))
    return chunks
def split_text(text, max_words=1320):
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunk = " ".join(words[start:end])
        last_dot = chunk.rfind(".")
        if 0 < last_dot < len(chunk) - 1:
            chunk = chunk[:last_dot + 1]
        chunks.append(chunk.strip())
        start += len(chunk.split())
    send_discord_message("✂️ Chia truyện thành %d đoạn", len(chunks))
    return chunks

# ============================== DEPRECATED - Uses AudioSegment ==============================
# def generate_audio(text: str, title_slug: str,style="Đọc bằng giọng hơi robotic, nhịp điệu nhanh giống giọng review phim."):
#     final_audio = os.path.join(OUTPUT_DIR, f"{title_slug}.wav")
#     if os.path.exists(final_audio):
#         send_discord_message("🎧 Dùng cache audio: %s", final_audio)
#         return final_audio

#     # --- Tạo đoạn intro kêu gọi follow ---
#     intro_text = (
#         "cẻm ơn đã các tình iu đã nghe truyện, iu tui iu truyện thì hãy bình luận đôi câu và ấn theo dõi nhà tui để nghe thêm nhiều truyện hay nhoaaa ❤️‍🔥❤️‍🔥❤️‍🔥"
#     )
#     intro_file = os.path.join(OUTPUT_DIR, f"intro.wav")
#     if not os.path.exists(intro_file):
#         send_discord_message("🎙️ Tạo đoạn intro kêu gọi follow...")
#         resp_intro = openai.audio.speech.create(
#             model="tts-1-hd",
#             voice="nova",
#             input=intro_text,
#             instructions="Giọng kêu gọi, hào hứng. thân thiện.",
#             response_format="wav",
#         )
#         resp_intro.stream_to_file(intro_file)
#     intro_segment = AudioSegment.from_wav(intro_file)

#     # --- Tạo các đoạn chính ---
#     chunks = split_text_with_space(text, 4096)
#     audio_segments = []
#     for i, part in enumerate(chunks, 1):
#         part_file = os.path.join(OUTPUT_DIR, f"{title_slug}_part_{i}.wav")
#         send_discord_message("🎙️ Tạo đoạn audio %d/%d (%s từ)...", i, len(chunks), len(part.split()))
#        
#         if not os.path.exists(part_file):
#             resp = openai.audio.speech.create(
#                 model="tts-1-hd",
#                 voice="nova",
#                 input=part,
#                 instructions=style,
#                 response_format="wav",
#             )
#             resp.stream_to_file(part_file)
#         seg = AudioSegment.from_wav(part_file)

#         # Nếu là đoạn chia hết cho 6 và audio tổng dự kiến > 60p => chèn kêu gọi
#         if i % 6 == 0:
#             send_discord_message("📢 Chèn đoạn kêu gọi follow sau đoạn %d", i)
#             seg = seg + intro_segment

#         audio_segments.append(seg)
#         os.remove(part_file)

#     # --- Ghép tất cả lại ---
#     combined = AudioSegment.empty()
#     
#     for seg in audio_segments:
#         combined += seg

#     # --- Kiểm tra độ dài ---
#     total_minutes = len(combined) / 1000 / 60
#     send_discord_message("🕒 Tổng độ dài audio: %.2f phút", total_minutes)

#     combined.export(final_audio, format="wav")
#     send_discord_message("✅ Hoàn tất tạo audio: %s", final_audio)
#     return final_audio
# ============================================================================================

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

# ============================== DEPRECATED - Uses AudioSegment ==============================
# def generate_audio_Gemini(text: str, title_slug: str):
#    
#     final_audio = os.path.join(OUTPUT_DIR, f"{title_slug}.wav")
#     if os.path.exists(final_audio):
#         send_discord_message("🎧 Dùng cache audio: %s", final_audio)
#         return final_audio

#     chunks = split_text(text, 3000)
#     audio_segments = []
#     for i, part in enumerate(chunks, 1):
#         part_file = os.path.join(OUTPUT_DIR, f"{title_slug}_part_{i}.wav")      
#         send_discord_message("🎙️ Tạo đoạn audio %d/%d (%s từ)...", i, len(chunks), len(part.split()))
#         send_discord_message(part)
#         if not os.path.exists(part_file):        
#          
#             response = client.models.generate_content(
#                 model="gemini-2.5-pro-preview-tts",
#                 contents="Đọc với giọng Sulafat, nhịp điệu nhanh, tự nhiên: " +part
#                 ,                
#                 config=types.GenerateContentConfig(
#                     automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),     
#                 
#                     response_modalities=["AUDIO"],
#                     speech_config=types.SpeechConfig(
#                         voice_config=types.VoiceConfig(
#                             prebuilt_voice_config=types.PrebuiltVoiceConfig(
#                             voice_name='sulafat'
#                             )                           
#                         ),
#                         language_code="vi"
#                     ),                   
#                     temperature=0.3
#                 )
#             )

#             inline_data = response.candidates[0].content.parts[0].inline_data          
#             wave_file(part_file, inline_data.data)          
#         audio_segments.append(AudioSegment.from_wav(part_file))

#     # Ghép các đoạn audio trực tiếp
#     combined = sum(audio_segments, AudioSegment.empty())
#     combined.export(final_audio, format="wav")
# ============================================================================================
   
def download_video_url(url: str, output="temp_video.mp4", retries=3, delay=2):
    """
    Tải video YouTube với yt-dlp, thử lại tối đa `retries` lần nếu lỗi.
    """
    attempt = 0
    while attempt < retries:
        try:
            send_discord_message("📥 Đang tải video YouTube (lần %d/%d): %s", attempt+1, retries, url)
            ydl_opts = {
                "format": "bestvideo+bestaudio/best",
                "outtmpl": output,
                "cookies": "youtube_cookies.txt",
                "merge_output_format": "mp4",
                "quiet": True,
                "noprogress": True
            }
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            send_discord_message("✅ Hoàn tất tải video: %s", output)
            return output
        except Exception as e:
            attempt += 1
            send_discord_message("⚠️ Tải video thất bại (lần %d/%d): %s", attempt, retries, e)
            time.sleep(delay)
    send_discord_message("❌ Tải video không thành công sau %d lần: %s", retries, url)
    raise RuntimeError(f"Tải video không thành công sau {retries} lần: {url}")
   
    



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


def _master_render_cache_path(video_paths, audio_path, title: str | None, mode: str = "master") -> str:
    """Return a deterministic cache path for a master render based on inputs.

    This helps avoid re-encoding the same large master file multiple times.
    """
    m = hashlib.md5()
    try:
        for p in video_paths:
            m.update(os.path.abspath(p).encode('utf-8'))
            # include file mtime to invalidate when source changes
            try:
                m.update(str(os.path.getmtime(p)).encode('utf-8'))
            except Exception:
                pass
        m.update(os.path.abspath(audio_path).encode('utf-8'))
        try:
            m.update(str(os.path.getmtime(audio_path)).encode('utf-8'))
        except Exception:
            pass
        if title:
            m.update(str(title).encode('utf-8'))
        m.update(mode.encode('utf-8'))
    except Exception:
        # fall back to simple hash of joined paths
        m = hashlib.md5(("|".join(video_paths) + "|" + audio_path + "|" + (title or "") + "|" + mode).encode('utf-8'))

    filename = f"master_{m.hexdigest()}.mp4"
    return os.path.join(VIDEO_CACHE_DIR, filename)
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

    if probe.returncode != 0 or not probe.stdout.strip():
        raise RuntimeError(f"ffprobe thất bại cho file: {path}")

    try:
        data = json.loads(probe.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Không đọc được JSON từ ffprobe: {probe.stdout[:200]}")

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
def concat_crop_audio_youtube(
    video_paths,
    audio_path,
    output_path="final.mp4",
    Title="",
    font_path="/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
):
    """
    🎬 Gộp nhiều video → crop 16:9 → scale 1920x1080 → lặp video cho đủ thời gian audio → thêm audio + tiêu đề từng phần.
    ⚙️ Xuất video tối ưu cho YouTube: h.264 baseline, aac 192k, faststart.
    """
    import os, math, subprocess, logging

    if not video_paths:
        raise ValueError("Danh sách video trống.")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Không tìm thấy file âm thanh: {audio_path}")

    # --- 1️⃣ Lấy thông tin video và audio ---
    video_infos = []
    total_video_dur = 0
    fps_values = []

    for p in video_paths:
        w, h, d, fps = get_media_info_fbs(p)
        video_infos.append((w, h, d, fps))
        fps_values.append(fps)
        total_video_dur += d

    _, _, audio_dur = get_media_info(audio_path)
    send_discord_message(f"🎞️ Tổng video={total_video_dur:.2f}s, Audio={audio_dur:.2f}s")
    if audio_dur <= 0:
        raise RuntimeError("Audio duration is 0s — không thể render. Kiểm tra file audio đầu vào.")

    min_fps = min(fps_values) if fps_values else 30

    # --- 2️⃣ Tính số lần cần lặp video ---
    loops = math.ceil(audio_dur / total_video_dur)
    extended_video_paths = video_paths * loops
    total_video_dur *= loops
    send_discord_message(f"🔁 Lặp video {loops} lần để đủ thời lượng {audio_dur:.2f}s")

    # --- 3️⃣ Build filter_complex ---
    filters = []
    for i, (w, h, _, fps) in enumerate(video_infos * loops):
        aspect = w / h
        target = 16 / 9
        if aspect > target:  # crop ngang
            new_w = int(h * target)
            x_offset = (w - new_w) // 2
            crop = f"crop={new_w}:{h}:{x_offset}:0"
        else:  # crop dọc
            new_h = int(w / target)
            y_offset = (h - new_h) // 2
            crop = f"crop={w}:{new_h}:0:{y_offset}"
        filters.append(f"[{i}:v]{crop},scale=1920:1080,fps={min_fps},setsar=1[v{i}]")

    concat_inputs = "".join([f"[v{i}]" for i in range(len(extended_video_paths))])
    filters.append(f"{concat_inputs}concat=n={len(extended_video_paths)}:v=1:a=0[vc]")

    # --- 4️⃣ Tiêu đề ---
    title_filters = []
    if Title:
        total_parts = math.floor(audio_dur / 4800) + 1
        part_duration = audio_dur / total_parts
        for i in range(total_parts):
            start_time = i * part_duration
            text = f"{Title.upper()} - PHẦN {i+1}" if total_parts > 1 else Title.upper()
            text = text.replace(":", "\\:").replace("'", "\\'")
            wrapped = wrap_text(text, 40)
            title_filters.append(
                f"drawtext=fontfile='{font_path}':text='{wrapped}':"
                f"fontcolor=white:fontsize=42:box=1:boxcolor=black@0.5:boxborderw=20:"
                f"x=(w-text_w)/2:y=(h-text_h)/2:"
                f"enable='between(t,{start_time},{start_time+3})'"
            )

    if title_filters:
        filters.append(f"[vc]{','.join(title_filters)}[v]")
    else:
        filters.append("[vc]copy[v]")

    # Increase narration audio level if configured to make voice clearer vs music
    if NARRATION_GAIN_DB and NARRATION_GAIN_DB != 0:
        filters.append(f"[{len(extended_video_paths)}:a]volume={NARRATION_GAIN_DB}dB,aresample=48000[a]")
    else:
        filters.append(f"[{len(extended_video_paths)}:a]aresample=48000[a]")
    filter_complex = ";".join(filters)

    # --- 5️⃣ Render video chính ---
    # Use cached master file when available to avoid re-rendering duplicate masters
    master_cache = _master_render_cache_path(extended_video_paths, audio_path, Title, mode="concat_crop_audio_youtube")
    if os.path.exists(master_cache):
        send_discord_message(f"♻️ Dùng master cache: {master_cache}")
        # create a copy so later code that removes master won't delete cache
        try:
            shutil.copy(master_cache, output_path)
            send_discord_message(f"✅ Tạo bản sao từ cache: {output_path}")
        except Exception:
            # fallback to rendering if copy fails
            send_discord_message("⚠️ Không thể copy từ cache, sẽ render lại.")
    else:
        cmd = ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "warning", "-fflags", "+genpts"]
        for p in extended_video_paths:
            cmd += ["-i", p]
        cmd += ["-i", audio_path]
        cmd += [
            "-t", str(audio_dur),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-profile:v", "high", "-level", "4.2",
            "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            "-shortest",
            output_path
        ]

        send_discord_message("🎬 Render video (concat + crop + loop + audio + title multi-parts)...")
        result = subprocess.run(cmd, text=True, capture_output=True)
        if result.returncode != 0:
            logging.error(f"❌ FFmpeg error:\n{result.stderr}")
            raise RuntimeError(f"Lỗi khi render video: {result.stderr}")

        # save a copy into cache for later reuse
        try:
            shutil.copy(output_path, master_cache)
            send_discord_message(f"💾 Lưu master cache: {master_cache}")
        except Exception:
            # non-fatal
            pass

    # --- 6️⃣ Chia part nếu dài > 80 phút ---
    total_seconds = audio_dur
    num_parts = math.floor(total_seconds / 43200) + 1 if total_seconds > 43200 else 1
    part_duration = total_seconds / num_parts

    base, ext = os.path.splitext(output_path)
    output_files = []

    for i in range(num_parts):
        start = i * part_duration
        duration = min(part_duration, total_seconds - start)
        part_path = f"{base}_part_{i+1}{ext}"

        cut_cmd = [
            "ffmpeg", "-y",
            "-ss", str(start), "-t", str(duration),
            "-i", output_path,
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            part_path
        ]
        subprocess.run(cut_cmd, check=True)
        output_files.append(part_path)

        send_discord_message(f"✅ Xuất video hoàn tất: {part_path}")

    
    return output_files
import os
import subprocess
import math
import tempfile

def render_video_only(video_paths, audio_path, output_path="video_ready.mp4",duration=None):
    """
    🎬 Ghép nhiều video → crop 16:9 → scale 1920x1080 → loop cho đủ độ dài audio
    ⚙️ Xuất video im lặng (chưa có audio)
    """
    if not video_paths:
        raise ValueError("Danh sách video trống.")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Không tìm thấy file âm thanh: {audio_path}")

    # --- Lấy độ dài audio ---
    cmd_audio = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    audio_duration = float(subprocess.check_output(cmd_audio).decode().strip())
    if  duration is None:
        audio_duration = duration
 
    # --- Tạo file tạm list video ---
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        for v in video_paths:
            f.write(f"file '{os.path.abspath(v)}'\n")
        list_file = f.name

    # --- Gộp video tạm ---
    merged_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file, "-c", "copy", merged_tmp
    ], check=True)

    # --- Lấy độ dài video ---
    cmd_video = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
        merged_tmp
    ]
    video_duration = float(subprocess.check_output(cmd_video).decode().strip())

    # --- Tính số lần lặp ---
    loop_count = math.ceil(audio_duration / video_duration)

    # --- Lặp video đủ độ dài audio ---
    loop_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
    subprocess.run([
        "ffmpeg", "-y", "-stream_loop", str(loop_count - 1),
        "-i", merged_tmp,
        "-t", str(audio_duration),
        "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080",
        "-an", "-c:v", "libx264", "-preset", "veryfast",
        "-pix_fmt", "yuv420p", output_path
    ], check=True)

    # Dọn file tạm
    os.remove(list_file)
    os.remove(merged_tmp)

    print(f"✅ Video hoàn chỉnh (mute) được lưu tại: {output_path}")
    return output_path
def add_audio_to_video(video_path, audio_path, output_path="final_with_audio.mp4"):
    # Apply optional narration gain so voice is louder relative to any music
    if NARRATION_GAIN_DB and NARRATION_GAIN_DB != 0:
        subprocess.run([
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-filter:a", f"volume={NARRATION_GAIN_DB}dB",
            "-shortest",
            output_path
        ], check=True)
    else:
        subprocess.run([
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_path
        ], check=True)
    send_discord_message(f"✅ Video + audio đã hoàn tất: {output_path}")
    return output_path


def render_add_audio_and_split(video_paths, audio_path, output_path="final.mp4", Title="", 
                               font_path="/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
                               part_time=4800):
    """
    Gộp nhiều video -> crop 16:9 -> scale 1920x1080 -> lặp video nếu cần -> thêm audio -> chèn tiêu đề
    trên timeline (enable drawtext cho mỗi phần) và encode 1 lần duy nhất. Sau đó chia thành phần bằng copy
    để tránh re-encode.

    Trả về danh sách các file part.
    """
    if not video_paths:
        raise ValueError("Danh sách video trống.")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Không tìm thấy file âm thanh: {audio_path}")

    # --- 1️⃣ Lấy thông tin và tính loops ---
    video_infos = []
    total_video_dur = 0
    fps_values = []
    for p in video_paths:
        w, h, d, fps = get_media_info_fbs(p)
        video_infos.append((w, h, d, fps))
        fps_values.append(fps or 30)
        total_video_dur += d

    _, _, audio_dur = get_media_info(audio_path)
    send_discord_message(f"🎞️ Tổng video={total_video_dur:.2f}s, Audio={audio_dur:.2f}s")
    if audio_dur <= 0:
        raise RuntimeError("Audio duration is 0s — không thể render. Kiểm tra file audio đầu vào.")

    loops = math.ceil(audio_dur / total_video_dur) if total_video_dur > 0 else 1
    extended_video_paths = video_paths * loops
    total_video_dur *= loops

    min_fps = min(fps_values) if fps_values else 30

    # --- 2️⃣ Build filter_complex: crop/scale each input, concat, then drawtext overlays per part ---
    filters = []
    for i, (w, h, _, fps) in enumerate(video_infos * loops):
        aspect = w / h if (w and h) else (16/9)
        target = 16 / 9
        if aspect > target:
            new_w = int(h * target)
            x_offset = (w - new_w) // 2
            crop = f"crop={new_w}:{h}:{x_offset}:0"
        else:
            new_h = int(w / target)
            y_offset = (h - new_h) // 2
            crop = f"crop={w}:{new_h}:0:{y_offset}"
    # memory-friendly scaling (avoid heavy filters to reduce OOM risks)
    filters.append(f"[{i}:v]{crop},scale=1920:1080:flags=fast_bilinear,setsar=1,fps={min_fps}[v{i}]")

    concat_inputs = "".join([f"[v{i}]" for i in range(len(extended_video_paths))])
    filters.append(f"{concat_inputs}concat=n={len(extended_video_paths)}:v=1:a=0[vc]")

    # drawtext overlays per part based on part_time
    title_filters = []
    if Title:
        # split into parts of length 'part_time' seconds
        num_parts = math.floor(audio_dur / part_time) + 1 if audio_dur > part_time else 1
        for i in range(num_parts):
            start_time = i * part_time
            if num_parts == 1:
                text = f"[FULL] {Title.upper()}"
            else:
                text = f"{Title.upper()} - PHẦN {i+1}"
            text = text.replace(":", "\\:").replace("'", "\\'")
            wrapped = wrap_text(text, 40)
            title_filters.append(
                f"drawtext=fontfile='{font_path}':text='{wrapped}':fontcolor=white:fontsize=42:box=1:boxcolor=black@0.6:boxborderw=20:x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,{start_time},{start_time+3})'"
            )

    if title_filters:
        filters.append(f"[vc]{','.join(title_filters)}[v]")
    else:
        filters.append("[vc]copy[v]")

    # audio resample
    # Apply narration gain if configured so the narration is louder relative to other tracks
    if NARRATION_GAIN_DB and NARRATION_GAIN_DB != 0:
        filters.append(f"[{len(extended_video_paths)}:a]volume={NARRATION_GAIN_DB}dB,aresample=48000[a]")
    else:
        filters.append(f"[{len(extended_video_paths)}:a]aresample=48000[a]")
    filter_complex = ";".join(filters)

    # --- 3️⃣ Single-pass render with audio included ---
    master_cache = _master_render_cache_path(extended_video_paths, audio_path, Title, mode="render_add_audio_and_split")
    if os.path.exists(master_cache):
        send_discord_message(f"♻️ Dùng master cache: {master_cache}")
        try:
            shutil.copy(master_cache, output_path)
            send_discord_message(f"✅ Tạo bản sao từ cache: {output_path}")
        except Exception:
            send_discord_message("⚠️ Không thể copy từ cache, sẽ render lại.")
    else:
        cmd = ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "warning", "-fflags", "+genpts"]
        for p in extended_video_paths:
            cmd += ["-i", p]
        cmd += ["-i", audio_path]
        cmd += [
            "-t", str(audio_dur),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-threads", "2",
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            "-shortest",
            output_path
        ]

        send_discord_message("🎬 Render single-pass (concat+audio+titles)...")
        # Tránh treo do buffer stdout/stderr khi encode lâu: không capture output
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            # Fallback nhẹ nếu bị kill (thường do OOM): render mute video rồi ghép audio và chia part
            if e.returncode in (-9, 137):
                send_discord_message("⚠️ FFmpeg bị kill (mã %s). Thử pipeline dự phòng: render_video_only -> add_audio_to_video -> split.", e.returncode)
                try:
                    base, ext = os.path.splitext(output_path)
                    mute_path = f"{base}_mute{ext}"
                    merged_path = output_path
                    # 1) Render video im lặng đủ độ dài audio
                    render_parth = render_video_only(video_paths, audio_path, mute_path, duration=3600)
                    # 2) Ghép audio vào
                    files = concat_crop_audio_youtube(video_paths=[render_parth], audio_path=audio_path,Title=Title,output_path=merged_path,
                    
                    font_path= "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf")
                    # 3) Chia part + chèn title 3s đầu mỗi part
                    split_video_by_time_with_title(merged_path, output_path, part_time=part_time, Title=Title, font_path=font_path)
                    # Dọn file tạm
                    try:
                        if os.path.exists(mute_path):
                            os.remove(mute_path)
                        if os.path.exists(merged_path):
                            os.remove(merged_path)
                    except Exception:
                        pass
                    return files
                except Exception as e2:
                    raise RuntimeError(f"Fallback render failed: {e2}")
            else:
                raise RuntimeError(f"Lỗi khi render video (ffmpeg exit {e.returncode}).")

        # save a copy into cache for later reuse
        try:
            shutil.copy(output_path, master_cache)
            send_discord_message(f"💾 Lưu master cache: {master_cache}")
        except Exception:
            pass

        # --- 4️⃣ Split into parts by copying (no re-encode) ---
    total_seconds = audio_dur
    if total_seconds > part_time:
        num_parts = math.floor(total_seconds / part_time) + 1
        part_duration = total_seconds / num_parts
    else:
        num_parts = 1
        part_duration = total_seconds

    base, ext = os.path.splitext(output_path)
    output_files = []

    for i in range(num_parts):
        start = i * part_duration
        duration = min(part_duration, total_seconds - start)
        part_path = f"{base}_part_{i+1}{ext}"

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
        send_discord_message(f"✅ Xuất video hoàn tất: {part_path}")

    # remove master encoded file to save space
    try:
        os.remove(output_path)
    except Exception:
        pass

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
        filters.append(f"[{i}:v]{crop},scale=1080:1920,setsar=1[v{i}]")

    # Concat tất cả video
    concat_inputs = "".join([f"[v{i}]" for i in range(len(extended_video_paths))])
    filters.append(f"{concat_inputs}concat=n={len(extended_video_paths)}:v=1:a=0[v]")

    # Audio
    filters.append(f"[{len(extended_video_paths)}:a]aresample=48000[a]")

    filter_complex = ";".join(filters)

    # --- 4️⃣ Tạo lệnh ffmpeg ---
    # Use cache to avoid re-encoding identical master files
    master_cache = _master_render_cache_path(extended_video_paths, audio_path, Title, mode="concat_and_add_audio")
    if os.path.exists(master_cache):
        send_discord_message(f"♻️ Dùng master cache: {master_cache}")
        try:
            shutil.copy(master_cache, output_path)
        except Exception:
            send_discord_message("⚠️ Không thể copy từ cache, sẽ render lại.")
    else:
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

        # save a copy into cache for later reuse
        try:
            shutil.copy(output_path, master_cache)
            send_discord_message(f"💾 Lưu master cache: {master_cache}")
        except Exception:
            pass

    # --- 5️⃣ Optional: chia video, upload ---
    list_output = split_video_by_time_with_title(output_path, Title, "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf")
    for o in list_output:
        try:
            upload_bytes_to_drive(o)
            send_discord_message(f"✅ Xuất video hoàn tất: {o}")
        except Exception:
            send_discord_message("⚠️ Upload không thành công")

    return list_output



def split_video_by_time_with_title(input_path, base_title=None, font_path="times.ttf",time = 3600):
    """
    🔹 Chia video >1h, thêm tiêu đề 3s đầu mà không encode toàn bộ video
    """
    import math
    logger.info(f"spilit file: {input_path}")
    _,_,total_seconds = get_media_info(input_path)
  
    output_files = []

    if total_seconds > time:
        num_parts = math.floor(total_seconds / time) + 1
        part_duration = total_seconds / num_parts
    else:
        num_parts = 1
        part_duration = total_seconds

    base, ext = os.path.splitext(input_path)

    # If only one part is needed, avoid re-encoding / creating temp clips:
    # just rename/move the original file to *_part_1 and return immediately.
    if num_parts == 1:
        output_path = f"{base}_part_1{ext}"
        try:
            # Prefer atomic replace
            os.replace(input_path, output_path)
        except Exception:
            # fallback to copy+remove
            shutil.copy(input_path, output_path)
            try:
                os.remove(input_path)
            except Exception:
                pass
        return [output_path]

    for i in range(num_parts):
        start = i * part_duration
        duration = min(part_duration, total_seconds - start)
        output_path = f"{base}_part_{i+1}{ext}"

        if base_title:
            if num_parts == 1:
                title_text = f"[FULL] {base_title}"
            else:
                title_text = f"{base_title} - P.{i+1}"
            wrapped_text = wrap_text(title_text, max_chars_per_line=40)
            pad_h = 40
            drawtext = (
                f"drawtext=fontfile='{font_path}':text='{wrapped_text}':"
                f"fontcolor=white:fontsize=42:box=1:boxcolor=black@1:boxborderw=20:"
                f"text_align=center:"
                f"x=(w-text_w)/2:y=(h-text_h-line_h)/2:enable='between(t,0,3)':boxborderw={pad_h}"
            )

            # 1️⃣ Clip title (up to 3s) and 2️⃣ rest encoded with same codec params so concat -c copy works
            title_len = min(3, duration)
            clip_title = f"{base}_part_{i+1}_title{ext}"
            # encode title portion with drawtext
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(start), "-t", str(title_len),
                "-i", input_path, "-vf", drawtext,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p",
                clip_title
            ], check=True)

            clip_rest = None
            if duration > title_len:
                clip_rest = f"{base}_part_{i+1}_rest{ext}"
                # encode rest with matching codec/settings (avoid -c copy to ensure identical parameters)
                subprocess.run([
                    "ffmpeg", "-y", "-ss", str(start + title_len), "-t", str(duration - title_len),
                    "-i", input_path,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p",
                    clip_rest
                ], check=True)

            # 3️⃣ Concat 2 clips (or use single title clip if duration <= title_len)
            if clip_rest:
                concat_file = f"{base}_part_{i+1}_list.txt"
                with open(concat_file, "w", encoding="utf-8") as f:
                    f.write(f"file '{clip_title}'\nfile '{clip_rest}'\n")
                subprocess.run([
                    "ffmpeg", "-y", "-fflags", "+genpts", "-f", "concat", "-safe", "0",
                    "-i", concat_file, "-c", "copy", "-movflags", "+faststart", output_path
                ], check=True)

                # Xóa tạm
                try:
                    os.remove(clip_title)
                except Exception:
                    pass
                try:
                    os.remove(clip_rest)
                except Exception:
                    pass
                try:
                    os.remove(concat_file)
                except Exception:
                    pass
            else:
                # No rest part - title clip is the whole segment
                # Move/rename title clip to output_path
                try:
                    os.replace(clip_title, output_path)
                except Exception:
                    # fallback to copy
                    shutil.copy(clip_title, output_path)
                    os.remove(clip_title)

        else:
            # Copy toàn bộ nếu không cần title
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(start), "-t", str(duration),
                "-i", input_path, "-c", "copy", output_path
            ], check=True)

        output_files.append(output_path)
    # Remove original input file only if all parts were created successfully
    try:
        all_ok = True
        for p in output_files:
            if not os.path.exists(p) or os.path.getsize(p) == 0:
                all_ok = False
                break
        if all_ok:
            try:
                if os.path.exists(input_path):
                    os.remove(input_path)
                    send_discord_message("🧹 Xóa file gốc sau khi split: %s", input_path)
            except Exception as e:
                send_discord_message("⚠️ Không xóa được file gốc sau khi split: %s", e)
        else:
            send_discord_message("⚠️ Một số part không tạo được, giữ file gốc: %s", input_path)
    except Exception as e:
        send_discord_message("⚠️ Lỗi kiểm tra phần kết quả split: %s", e)

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
    
def _pick_random_cached_veo3_clip():
    files = []
    try:
        files = [
            os.path.join(VEO3_CACHE_DIR, f)
            for f in os.listdir(VEO3_CACHE_DIR)
            if f.lower().endswith(".mp4")
        ]
    except Exception:
        pass
    if not files:
        raise FileNotFoundError("Không có clip nào trong cache Veo3 để dùng lại")
    return random.choice(files)

def generatevideoveo3(title):
    """
    Mỗi lần gọi:
    - Gọi API Veo để tạo clip nền, sau đó lưu vào thư mục cache (outputs/veo3_clips)
    - Nếu hết quota hoặc lỗi API, lấy ngẫu nhiên một clip đã cache để dùng lại
    Trả về: đường dẫn file mp4 đã chọn/tạo
    """
    prompt = (
        "Một video nền lặp lại (loop) tỉ lệ 1920x1080 với phong cách tối giản, tông màu tím neon. "
        "Ở giữa màn hình là dòng chữ phát sáng \"Tale Waves Studio\", từ từ đổi màu giữa tím và hồng. "
        "Ở góc phải là một cô gái chibi dễ thương, đeo tai nghe và cầm micro, cử động miệng và hơi đung đưa nhẹ như đang kể truyện. "
        "Phía sau là những làn sóng ánh sáng neon tím chuyển động chậm rãi, gợn nhẹ liên tục tạo cảm giác thư giãn. "
        "Không khí tổng thể nhẹ nhàng, ấm áp, hiện đại, phù hợp cho video kể truyện audio. "
        "Hiệu ứng ánh sáng mềm mại, bố cục cân đối, chuyển động mượt mà, có thể lặp lại liên tục mà không bị khựng."
    )

    # Chuẩn hóa tên file an toàn
    try:
        slug = safe_filename(str(title)) if 'safe_filename' in globals() else re.sub(r"[\\/*?:\"<>|]", "_", str(title))
    except Exception:
        slug = re.sub(r"[\\/*?:\"<>|]", "_", str(title))

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is required for Veo3 generation")
    client = genai.Client(api_key=GEMINI_API_KEY)
    try:
        operation = client.models.generate_videos(
            model="veo-3.1-generate-preview",
            prompt=prompt,
            config=types.GenerateVideosConfig(
                aspectRatio="16:9",
                resolution="1080p",
                
            ),
        )

        # Chờ đến khi xong
        while not operation.done:
            send_discord_message("⏳ Đang tạo video nền (Veo3)...")
            time.sleep(10)
            operation = client.operations.get(operation)

        # Tải video kết quả và lưu vào cache
        generated_video = operation.response.generated_videos[0]
        client.files.download(file=generated_video.video)
        filename = f"veo3_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug}.mp4"
        save_path = os.path.join(VEO3_CACHE_DIR, filename)
        generated_video.video.save(save_path)
        send_discord_message(f"✅ Đã tạo và lưu clip nền vào cache: {filename}")
        return save_path

    except Exception as e:
        # Hết quota hoặc lỗi khác -> fallback dùng clip cache
        err = str(e)
        if any(k in err.lower() for k in ["quota", "429", "rate", "exhausted", "resource_exhausted", "limit"]):
            send_discord_message(f"⚠️ Hết quota/Rate limit Veo3, dùng clip cache: {err}")
        else:
            send_discord_message(f"⚠️ Lỗi tạo clip Veo3, dùng clip cache: {err}")
        # Chọn ngẫu nhiên 1 clip trong cache
        cached = _pick_random_cached_veo3_clip()
        send_discord_message(f"♻️ Dùng lại: {os.path.basename(cached)}")
        return cached

def _pick_random_cached_sora_clip():
    files = []
    try:
        files = [
            os.path.join(SORA_CACHE_DIR, f)
            for f in os.listdir(SORA_CACHE_DIR)
            if f.lower().endswith(".mp4")
        ]
    except Exception:
        pass
    if not files:
        raise FileNotFoundError("Không có clip nào trong cache Sora để dùng lại")
    return random.choice(files)

def generate_video_sora(title: str, prompt: str | None = None) -> str:
    """
    Tạo video nền bằng OpenAI Sora (nếu khả dụng), lưu vào cache outputs/sora_clips.
    - Nếu lỗi API/ hết quota hoặc chưa tích hợp Sora API, sẽ fallback:
        1) Dùng ngẫu nhiên clip đã cache của Sora nếu có
        2) Nếu cache Sora trống, dùng generatevideoveo3 để tạo clip và chép sang cache Sora
    Trả về: đường dẫn file mp4

    Lưu ý: API Sora chưa được tích hợp vì phụ thuộc vào SDK/chế độ truy cập. 
    Bạn có thể thay thế phần TODO bên dưới bằng lệnh gọi SDK/HTTP chính thức của OpenAI khi có quyền truy cập.
    """
    default_prompt = (
        "Nền video loop 1920x1080 phong cách tối giản, tông tím neon. "
        "Chữ \"Tale Waves Studio\" phát sáng ở giữa, đổi màu tím-hồng chậm rãi. "
        "Góc phải có nhân vật chibi đeo tai nghe, cử động nhẹ khi kể chuyện. "
        "Hiệu ứng sóng ánh sáng neon tím chuyển động mượt, dễ chịu, lặp mượt."
    )
    prompt = prompt or default_prompt

    # Tạo tên file an toàn
    try:
        slug = safe_filename(str(title)) if 'safe_filename' in globals() else re.sub(r"[\\/*?:\"<>|]", "_", str(title))
    except Exception:
        slug = re.sub(r"[\\/*?:\"<>|]", "_", str(title))

    # Use OpenAI Python SDK (create → retrieve/poll → download_content)
    try:
       
        
        client =openai

        send_discord_message("🎬 Gửi job Sora qua SDK...")
        video = client.videos.create(model="sora-2", prompt=prompt)
        send_discord_message(f"🎬 Sora job started: id={getattr(video, 'id', None)}, status={getattr(video, 'status', None)}")

        progress = getattr(video, "progress", 0)
        bar_length = 30

        # Poll until finished
        while getattr(video, "status", None) in ("in_progress", "queued"):
            video = client.videos.retrieve(video.id)
            progress = getattr(video, "progress", 0) or 0
            filled_length = int((progress / 100) * bar_length)
            bar = "=" * filled_length + "-" * (bar_length - filled_length)
            status_text = "Queued" if video.status == 'queued' else 'Processing'
            send_discord_message(f"⏳ Sora: {status_text}: [{bar}] {progress:.1f}%")
            time.sleep(2)

        # Final status
        if getattr(video, "status", None) == 'failed':
            message = getattr(getattr(video, "error", None), "message", "Video generation failed")
            raise RuntimeError(message)

        send_discord_message(f"✅ Sora completed: id={video.id}")

        # Download content (variant=video)
        send_discord_message("⬇️ Tải nội dung video từ Sora...")
        content = client.videos.download_content(video.id, variant="video")
        filename = f"sora_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug}.mp4"
        save_path = os.path.join(SORA_CACHE_DIR, filename)
        # SDK provides write helper
        try:
            content.write_to_file(save_path)
        except Exception:
            # Fallback: content may be a stream-like object
            data = content.read() if hasattr(content, 'read') else content
            with open(save_path, 'wb') as f:
                if isinstance(data, (bytes, bytearray)):
                    f.write(data)
                else:
                    # if it's an iterator of chunks
                    for chunk in data:
                        f.write(chunk)

        send_discord_message(f"✅ Đã tải video Sora về: {filename}")
        return save_path

    except Exception as e:
        err = str(e)
        send_discord_message(f"⚠️ Không tạo được video bằng Sora: {err}")
        # Fallback thứ tự theo yêu cầu: 1) Veo3  2) Cache
        try:
            send_discord_message("➡️ Fallback: thử tạo bằng Veo3")
            veo_path = generatevideoveo3(title)
            return veo_path
        except Exception as e2:
            send_discord_message(f"⚠️ Veo3 cũng không tạo được: {e2}. Dùng cache.")
            # Thử cache Sora trước, rồi đến cache Veo3
            try:
                cached = _pick_random_cached_sora_clip()
                send_discord_message(f"♻️ Dùng lại clip Sora cache: {os.path.basename(cached)}")
                return cached
            except Exception:
                pass
            cached_veo = _pick_random_cached_veo3_clip()
            send_discord_message(f"♻️ Dùng lại clip Veo3 cache: {os.path.basename(cached_veo)}")
            return cached_veo
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

    filter_complex = f"[0:v]{crop},scale=1080:1920,setsar=1[v];[1:a]aresample=48000[a]"

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
    # Loại bỏ ký tự không hợp lệ
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    # Nếu dài quá, cắt và thêm hash ở cuối để tránh trùng
    if len(name) > max_length:
        import hashlib
        hash_suffix = hashlib.md5(name.encode()).hexdigest()[:8]
        name = name[:max_length - 9] + "_" + hash_suffix
    return name

def extract_slug(url: str, max_length: int = 100) -> str:
    # Bỏ phần giao thức
    url = re.sub(r"^https?://", "", url)
    # Thay các dấu đặc biệt bằng _
    name = re.sub(r"[\/\?\&\=\#\.]+", "_", url)
    # Loại bỏ dấu _ ở đầu/cuối
    name = name.strip("_")
    # Đảm bảo an toàn và không quá dài
    return safe_filename(name, max_length)
# Quyền đọc và upload video
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]

def get_authenticated_service():
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

    # Nếu chưa có token hoặc token hết hạn thì xác thực lại
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        # Lưu token ra file
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return build("youtube", "v3", credentials=creds)

def test_auth():
    youtube = get_authenticated_service()
    res = youtube.channels().list(part="snippet,contentDetails,statistics", mine=True).execute()
    send_discord_message("✅ Đăng nhập thành công với kênh:")
    send_discord_message(res["items"][0]["snippet"]["title"])
def get_video_categories(region="VN"):
    youtube = get_authenticated_service()
    request = youtube.videoCategories().list(
        part="snippet",
        regionCode=region
    )
    response = request.execute()

    send_discord_message(f"\n🎬 Danh mục video  {response['items']}:")
    category_map = {}
    for item in response["items"]:
        if item["snippet"]["assignable"]:
            name = item["snippet"]["title"]
            cid = item["id"]
            category_map[name.lower()] = cid
          
    return category_map

def upload_video(file_path, title, description="", category=None, privacy="public", tags=None):
    youtube = get_authenticated_service()

    # Cho phép chọn category theo tên (vd: "Music" hoặc "Education")
    category_id = None
    if category:
        categories = get_video_categories("VN")
        category_id = categories.get(category.lower(), category)  # nếu không tìm thấy, dùng nguyên giá trị

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": category_id or "22",  # default: People & Blogs
            "tags": tags or [],
        },
        "status": {"privacyStatus": privacy}
    }
    print(body)
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True)

    send_discord_message(f"🎬 Uploading: {title} ...")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            send_discord_message(f"⬆️ Tiến độ: {int(status.progress() * 100)}%")

    send_discord_message("✅ Upload hoàn tất!")
    send_discord_message(f"Video ID: {response['id']}")
    send_discord_message(f"🔗 Link: https://youtu.be/{response['id']}")





   