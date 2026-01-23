from subprocess_helper import run_logged_subprocess

import os
import subprocess
import importlib
import traceback
import whisper
from typing import Optional
from srt_translate import translate_srt_file
from DiscordMethod import send_discord_message
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/app/downloads")
import requests
import time
import hashlib
import json
import re
# ---------------------------------------------------------
# 1) Detect local model file ONLY (never treat as HF repo)
# ---------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "models")
print("Using model:", MODEL_PATH)

# ---------------------------------------------------------
# Whisper model singleton (load once, reuse)
# ---------------------------------------------------------
_WHISPER_MODEL = None

# Faster-Whisper singleton (optional)
_FASTWHISPER_MODELS: dict[str, object] = {}
TRANSLATE_ENDPOINT = os.environ.get(
    "SRT_TRANSLATE_ENDPOINT",
    "https://n8n.vietravel.com/webhook/c892de19-3b20-4b32-b9ee-6b6847b0e77a",
)
USE_GEMINI_TRANSCRIBE = os.environ.get("USE_GEMINI_TRANSCRIBE", "1") == "1"
def get_fast_whisper_model(model_size: str = "large"):
    """Return a faster-whisper model instance keyed by size (tiny/large)."""
    global _FASTWHISPER_MODELS
    if model_size in _FASTWHISPER_MODELS:
        return _FASTWHISPER_MODELS[model_size]
    try:
        from faster_whisper import WhisperModel
    except Exception:
        _FASTWHISPER_MODELS[model_size] = None
        return None

    device = "cpu"
    model_dir = os.path.join(MODEL_PATH, model_size)
    try:
        _FASTWHISPER_MODELS[model_size] = WhisperModel(model_dir, device=device, compute_type="int8")
    except Exception:
        _FASTWHISPER_MODELS[model_size] = None
    return _FASTWHISPER_MODELS[model_size]
def get_whisper_model():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL
    model_name = os.environ.get("WHISPER_MODEL", "large-v3")
    send_discord_message(f"🔍 Khởi tạo Whisper model: {model_name} (lần đầu)")
    _WHISPER_MODEL = whisper.load_model(model_name)
    return _WHISPER_MODEL

# (Removed) Faster-Whisper support: Always use OpenAI Whisper

def _deduplicate_repeated_segments(segments, min_run: int = 3):
    """Remove runs of identical subtitle lines.

    If there are >= min_run consecutive segments whose cleaned text is
    completely identical, only keep the first segment of that run
    (i.e. keep the timestamp of the first line and drop the rest).
    """
    if not segments:
        return segments

    result = []
    i = 0
    n = len(segments)
    while i < n:
        seg_i = segments[i]
        if isinstance(seg_i, dict):
            text_i = (seg_i.get("text", "") or "").strip()
        else:
            text_i = str(seg_i).strip()

        # Empty-text segments are not merged; keep as-is
        if not text_i:
            result.append(seg_i)
            i += 1
            continue

        j = i + 1
        while j < n:
            seg_j = segments[j]
            if isinstance(seg_j, dict):
                text_j = (seg_j.get("text", "") or "").strip()
            else:
                text_j = str(seg_j).strip()

            if text_j != text_i:
                break
            j += 1

        run_len = j - i
        if run_len >= min_run:
            # Keep only the first segment in this identical-text run
            result.append(seg_i)
        else:
            # Keep all segments in shorter runs
            result.extend(segments[i:j])

        i = j

    return result


def _write_srt_segments(srt_path: str, segments):
    # Apply de-duplication rule: if 3+ consecutive lines have identical
    # text, only keep the first one's timestamp (drop the others).
    segments = _deduplicate_repeated_segments(list(segments))

    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            start_raw = seg.get("start")
            end_raw = seg.get("end")
            # normalize timestamps to seconds (float)
            if isinstance(start_raw, (int, float)):
                start = float(start_raw)
            elif isinstance(start_raw, str):
                start = _parse_srt_timestamp_to_seconds(start_raw)
            else:
                start = 0.0

            if isinstance(end_raw, (int, float)):
                end = float(end_raw)
            elif isinstance(end_raw, str):
                end = _parse_srt_timestamp_to_seconds(end_raw)
            else:
                end = start + 2.0

            text = (seg.get("text", "") or "").strip()
            f.write(f"{i}\n")
            f.write(f"{format_ts(start)} --> {format_ts(end)}\n")
            f.write(f"{text}\n\n")

def _strip_diacritics(s: str) -> str:
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', s.lower()) if unicodedata.category(c) != 'Mn')
def has_segment_over_1_minute(data):
    """Return True if any segment duration exceeds 60 seconds.

    Accepts several input shapes returned by different STT backends:
    - A list of items where each item has a 'segments' list (old shape)
    - A flat list of segment dicts where each dict has 'start' and 'end'
    Each start/end may be either an object with Vietnamese keys (Phut/Giay/miligiay),
    a numeric seconds value, or a timestamp string. The function is defensive
    and ignores malformed entries instead of raising KeyError.
    """
    def to_ms(t):
        # handle dict time object from POST/Gemini: Phut/Giay/miligiay or variants
        try:
            if isinstance(t, dict):
                ph = int(t.get("Phut", t.get("phut", 0)))
                gi = int(t.get("Giay", t.get("giay", 0)))
                ms = int(t.get("miligiay", t.get("Ms", t.get("ms", 0))))
                return ph * 60000 + gi * 1000 + int(ms)
            if isinstance(t, (int, float)):
                return int(float(t) * 1000)
            # treat timestamp string via canonical parser
            if isinstance(t, str):
                try:
                    return int(_parse_srt_timestamp_to_seconds(t) * 1000)
                except Exception:
                    # try float fallback
                    try:
                        return int(float(t) * 1000)
                    except Exception:
                        return 0
        except Exception:
            return 0
        return 0

    try:
        for item in data:
            # Decide whether item contains a 'segments' list or is itself a segment
            segs = None
            if isinstance(item, dict) and isinstance(item.get("segments"), list):
                segs = item.get("segments")
            elif isinstance(item, dict) and ("start" in item and "end" in item):
                segs = [item]
            elif isinstance(item, list):
                segs = item
            else:
                # Unknown item shape — skip
                continue

            for seg in segs:
                try:
                    start = seg.get("start") if isinstance(seg, dict) else None
                    end = seg.get("end") if isinstance(seg, dict) else None
                    if start is None or end is None:
                        continue
                    # threshold: 60 seconds (60000 ms)
                    if (to_ms(end) - to_ms(start)) > 40000:
                        return True
                except Exception:
                    continue
    except Exception:
        return False
    return False
def _post_trancribe_api(filePath: str, attempts: int = 5, backoff: float = 2.0) -> object:
    """Send listsub (raw SRT-style blocks) to external API and return translated listsub text.

    Expected form fields:
    - listsub: raw SRT-like text (index, timestamp, text) for a batch slice
    - TaskId: identifier for tracking

    Returns translated listsub text (same format), from either JSON {content|listsub} or raw text body.
    """
    data = {"Type": "2"}
    last_exc = None
    for i in range(1, attempts + 1):
        try:
            # If configured, use Gemini/GenAI directly to analyze audio bytes
            if USE_GEMINI_TRANSCRIBE:
                try:
                    with open(filePath, "rb") as f:
                        audio_bytes = f.read()
                    def analyze_audio(file_bytes: bytes, mime_type: str) -> str:
                        from google import genai
                        from google.genai import types
                        client = genai.Client(api_key=os.environ.get("GENAI_API_KEY") or os.environ.get("GENAI_API_KEY_Translate"))
                        AUDIO_PROMPT = (
                            "BẠN LÀ TRÌNH DỊCH PHỤ ĐỀ PHIM (Chinese zh-CN → Vietnamese).\n\n"
                            "=====================\nNHIỆM VỤ CHÍNH\n=====================\n"
                            "- CHỈ tạo phụ đề khi CÓ lời thoại nói.\n"
                            "- GIỮ NGUYÊN nguyên văn tiếng Trung (zh-CN).\n"
                            "- Dịch sang tiếng Việt NGẮN GỌN, TỰ NHIÊN, đúng thoại phim.\n"
                            "- BỎ QUA hoàn toàn nhạc, âm thanh nền, hiệu ứng (♪, BGM, SFX…).\n\n"
                            "=====================\nQUY TẮC THỜI GIAN (CỰC KỲ NGHIÊM NGẶT – PHẢI TUÂN THỦ TUYỆT ĐỐI)\n=====================\n"
                            "1. TUYỆT ĐỐI KHÔNG DÙNG GIỜ (hour).\n"
                            "2. Thời gian CHỈ GỒM 3 TRƯỜNG RIÊNG BIỆT:\n   - Phut      : số phút (SỐ NGUYÊN, có thể > 60)\n   - Giay      : số giây (CHỈ từ 0 đến 59)\n   - miligiay  : mili giây (CHỈ từ 0 đến 999)\n\n"
                            "3. CÁC TRƯỜNG LÀ ĐƠN VỊ ĐỘC LẬP:\n   - miligiay KHÔNG PHẢI là giây\n   - KHÔNG được cộng miligiay vào giây\n   - KHÔNG được đổi miligiay → giây\n   - KHÔNG được đổi giây → phút\n   - KHÔNG được chuẩn hoá hoặc tính toán lại thời gian\n\n"
                            "4. THỜI GIAN PHẢI ĐƯỢC GHI RA ĐÚNG NGUYÊN GIÁ TRỊ ĐƯỢC NHẬN.\n   - KHÔNG suy luận\n   - KHÔNG làm tròn\n   - KHÔNG sửa logic\n   - KHÔNG “tối ưu” hay “chuẩn hoá”\n\n"
                            "5. GIỚI HẠN GIÁ TRỊ (BẮT BUỘC):\n   - Giay MUST ∈ [0, 59]\n   - miligiay MUST ∈ [0, 999]\n   - Nếu thấy giá trị vượt giới hạn → GIỮ NGUYÊN, KHÔNG ĐƯỢC TỰ SỬA\n\n"
                            "=====================\nVÍ DỤ HỢP LỆ (ĐÚNG)\n=====================\n"
                            "75 phút 15 giây 200 miligiay\n→ {\"Phut\":75,\"Giay\":15,\"miligiay\":200}\n\n"
                            "1 giây 443 miligiay\n→ {\"Phut\":0,\"Giay\":1,\"miligiay\":443}\n\n"
                            "=====================\n❌ CÁC HÀNH VI BỊ CẤM TUYỆT\n=====================\n"
                            "- Đổi 75 phút → 1 giờ 15 phút\n- Đổi 75 phút → 4515 giây\n- Đổi 443 miligiay → 443 giây\n- Gộp miligiay vào giây\n- Chuẩn hoá thời gian dưới bất kỳ hình thức nào\n\n"
                            "=====================\nQUY TẮC PHỤ ĐỀ\n=====================\n"
                            "- Mỗi segment tối đa 1–2 dòng thoại.\n- Thời lượng mỗi segment: 0.8s – 6.0s.\n- KHÔNG chồng lấp thời gian giữa các segment.\n- end >= start (luôn đúng về mặt thứ tự, KHÔNG tính toán lại giá trị).\n\n"
                            "=====================\nOUTPUT (BẮT BUỘC)\n=====================\n"
                            "- CHỈ trả về JSON HỢP LỆ.\n- KHÔNG markdown.\n- KHÔNG chú thích.\n- KHÔNG giải thích.\n- KHÔNG thêm trường ngoài format.\n\n"
                            "=====================\nFORMAT JSON DUY NHẤT ĐƯỢC PHÉP\n=====================\n"
                            "{\n  \"segments\": [\n    {\n      \"index\": 1,\n      \"start\": { \"Phut\": 75, \"Giay\": 15, \"miligiay\": 200 },\n      \"end\":   { \"Phut\": 75, \"Giay\": 18, \"miligiay\": 600 },\n      \"text_zh\": \"中文原句\",\n      \"text_vi\": \"Bản dịch tiếng Việt ngắn gọn\"\n    }\n  ]\n}\n"
                        )

                        response = client.models.generate_content(
                            model="models/gemini-2.5-flash",
                            contents=[
                                types.Content(
                                    role="user",
                                    parts=[
                                        types.Part(
                                            inline_data=types.Blob(
                                                data=file_bytes,
                                                mime_type=mime_type
                                            )
                                        ),
                                        types.Part(text=AUDIO_PROMPT)
                                    ]
                                )
                            ]
                        )
                        return response.text
                    # call analyze_audio
                    text = analyze_audio(audio_bytes, "audio/wav")
                    # Try parse JSON if possible
                    try:
                        return json.loads(text)
                    except Exception:
                        return text
                except Exception as e:
                    send_discord_message(f"⚠️ Gemini direct transcribe failed: {e}")
                    # fall through to webhook mode

            with open(filePath, "rb") as f:
                files = {"file": ("file.wav", f, "audio/wav")}
                resp = requests.post(TRANSLATE_ENDPOINT, data=data, files=files, timeout=60 * 15)

            # treat non-2xx as error to trigger retry
            if not (200 <= resp.status_code < 300):
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

            ctype = resp.headers.get("Content-Type", "")
            if "application/json" in ctype:
                json_data = resp.json()
                # If the returned segments contain any segment > 1 minute,
                # attempt up to 4 additional retries (with backoff) before
                # failing — some transcribe endpoints occasionally emit
                # malformed long segments transiently.
                try:
                    segs = json_data.get("segments") if isinstance(json_data, dict) else None
                except Exception:
                    segs = None
                if segs and has_segment_over_1_minute(segs):
                    send_discord_message(f"⚠️ POST transcribe returned long segment (>1min). Retrying up to 4 times...")
                    last_bad = json_data
                    for rr in range(1, 5):
                        try:
                            sleep_for = backoff * rr
                            time.sleep(sleep_for)
                            with open(filePath, "rb") as f:
                                files2 = {"file": ("file.wav", f, "audio/wav")}
                                resp2 = requests.post(TRANSLATE_ENDPOINT, data=data, files=files2, timeout=60 * 15)
                            if not (200 <= resp2.status_code < 300):
                                send_discord_message(f"⚠️ Retry {rr}/4 HTTP {resp2.status_code}")
                                continue
                            ctype2 = resp2.headers.get("Content-Type", "")
                            if "application/json" in ctype2:
                                try:
                                    json2 = resp2.json()
                                except Exception:
                                    send_discord_message(f"⚠️ Retry {rr}/4 returned non-JSON body")
                                    continue
                                if not has_segment_over_1_minute(json2.get("segments", [])):
                                    send_discord_message(f"✅ Retry {rr}/4 produced acceptable segments")
                                    return json2
                                else:
                                    send_discord_message(f"⚠️ Retry {rr}/4 still contains long segments")
                                    last_bad = json2
                                    continue
                            else:
                                # Non-JSON response; return raw text
                                return resp2.text
                        except Exception as _e:
                            send_discord_message(f"⚠️ Exception during retry {rr}/4: {_e}")
                            continue
                    # After retries, raise to trigger outer retry logic / alert
                    raise RuntimeError("POST transcribe returned long segments after 4 retries")

                return json_data
            return resp.text

        except Exception as e:
            last_exc = e
            send_discord_message(f"⚠️ POST transcribe attempt {i}/{attempts} failed: {e}")
            if i < attempts:
                sleep_for = backoff * (2 ** (i - 1))
                time.sleep(sleep_for)
            else:
                send_discord_message(f"❌ External SRT translate API failed after {attempts} attempts: {e}")
                raise


def _parse_post_time_object(obj) -> float:
    """Parse time objects returned by the external API where time is
    expressed as minutes, seconds and miligiay (ms). Minutes may be > 60.

    Example input:
      {"Phut":1, "Giay":4, "miligiay":657}
    Returns seconds (float).
    """
    if obj is None:
        raise ValueError("Empty time object")
    if not isinstance(obj, dict):
        raise ValueError("Time object must be a dict")
    def get_int(keys, default=0):
        for k in keys:
            if k in obj:
                try:
                    return int(obj[k])
                except Exception:
                    try:
                        return int(float(obj[k]))
                    except Exception:
                        return default
        return default

    hours = get_int(["Gio", "gio", "Hour", "hour", "hours", "H", "h"], 0)
    minutes = get_int(["Phut", "phut", "Minute", "minute", "minutes"], 0)
    seconds = get_int(["Giay", "giay", "Second", "second", "seconds"], 0)
    ms = get_int(["miligiay", "ms", "Milli", "milli", "milliseconds"], 0)

    # carry ms->s
    if ms >= 1000:
        extra_s = ms // 1000
        ms = ms % 1000
        seconds += extra_s
    # carry seconds->minutes
    if seconds >= 60:
        extra_m = seconds // 60
        seconds = seconds % 60
        minutes += extra_m
    # carry minutes->hours (API may return minutes > 60)
    if minutes >= 60:
        extra_h = minutes // 60
        minutes = minutes % 60
        hours += extra_h

    total = hours * 3600 + minutes * 60 + seconds + ms / 1000.0
    return float(total)


def _create_srt_from_post_api(audio_path: str, output_srt: str | None = None, out_vi: str | None = None) -> tuple[str, str]:
    """Call the external POST transcribe API and write SRT(s).

    The API returns JSON with top-level `segments` array where each segment
    contains `start` and `end` objects using minutes/seconds/miligiay keys
    and bilingual text fields `text_zh` and `text_vi`.
    """
    data = _post_trancribe_api(audio_path)
   
    if isinstance(data, str):
        # if the endpoint returned raw text, try parse JSON
        import json
        try:
            data = json.loads(data)
        except Exception:
            raise ValueError("_post_trancribe_api returned non-JSON response")

    segments = data.get("segments") or data.get("subtitles") or []
    if not segments:
        raise ValueError("No segments returned from POST transcribe API")

    base = os.path.splitext(audio_path)[0]
    if output_srt is None:
        output_srt = base + ".srt"
    if out_vi is None:
        out_vi = os.path.splitext(output_srt)[0] + ".vi.srt"

    zh_segs = []
    vi_segs = []
    for seg in segments:
        start_raw = seg.get("start")
        end_raw = seg.get("end")
        text_zh = seg.get("text_zh") or seg.get("text") or seg.get("text_cn") or ""
        text_vi = seg.get("text_vi") or seg.get("translation") or seg.get("text_vi") or ""

        try:
            if isinstance(start_raw, (int, float)):
                start = float(start_raw)
            elif isinstance(start_raw, str):
                # try canonical parser
                start = _parse_srt_timestamp_to_seconds(start_raw)
            elif isinstance(start_raw, dict):
                start = _parse_post_time_object(start_raw)
            else:
                start = 0.0
        except Exception:
            start = 0.0

        try:
            if isinstance(end_raw, (int, float)):
                end = float(end_raw)
            elif isinstance(end_raw, str):
                end = _parse_srt_timestamp_to_seconds(end_raw)
            elif isinstance(end_raw, dict):
                end = _parse_post_time_object(end_raw)
            else:
                end = start + 2.0
        except Exception:
            end = start + 2.0

        zh_segs.append({"start": start, "end": end, "text": (text_zh or "").strip()})
        vi_segs.append({"start": start, "end": end, "text": (text_vi or "").strip()})

    _write_srt_segments(output_srt, zh_segs)
    _write_srt_segments(out_vi, vi_segs)
    send_discord_message("✅ Đã tạo phụ đề từ POST API:", output_srt,out_vi)
    return output_srt, out_vi


def _create_srt_from_post_api_with_retries(audio_path: str, output_srt: str | None = None, out_vi: str | None = None) -> tuple[str, str] | None:
    """Call `_create_srt_from_post_api` and retry when the produced SRT contains flagged keywords.

    Behavior:
    - Attempt up to `max_attempts` times.
    - After each successful write, check `output_srt` with `_srt_contains_keywords`.
      If true, delete the SRT and retry.
    - On exception or final failure, return None (or last path if produced).
    """
  
       
    send_discord_message(f"🔍 Kiểm tra từ khóa đặc biệt trong SRT sau khi tạo từ POST API...",output_srt)
    output_srt,out_vi = _create_srt_from_post_api(audio_path, output_srt=output_srt, out_vi=out_vi)                     
    return  output_srt,out_vi
       



def _normalize_segments(segments):
    """Normalize various segment representations (dicts or objects) into list of dicts
    with keys: start (seconds float), end (seconds float), text (str).
    """
    out = []
    if not segments:
        return out
    for seg in segments:
        try:
            if isinstance(seg, dict):
                start_raw = seg.get('start')
                end_raw = seg.get('end')
                text = seg.get('text') or seg.get('content') or seg.get('sentence') or ''
            else:
                # object from whisper/faster-whisper may have attributes
                start_raw = getattr(seg, 'start', None)
                end_raw = getattr(seg, 'end', None)
                # some implementations use 'text' or 'content'
                text = getattr(seg, 'text', None) or getattr(seg, 'content', None) or str(seg)

            # normalize start/end to float seconds
            def to_seconds(val):
                if val is None:
                    return None
                if isinstance(val, (int, float)):
                    return float(val)
                if isinstance(val, str):
                    # if timestamp string like HH:MM:SS,mmm or with dot
                    try:
                        return _parse_srt_timestamp_to_seconds(val)
                    except Exception:
                        try:
                            return float(val)
                        except Exception:
                            return None
                return None

            start = to_seconds(start_raw)
            end = to_seconds(end_raw)
            if start is None:
                # skip segments without start
                continue
            if end is None:
                end = start + 2.0

            out.append({
                'start': float(start),
                'end': float(end),
                'text': (text or '').strip()
            })
        except Exception:
            # be resilient: skip malformed segment
            continue
    return out

def _srt_contains_keywords(path: str) -> bool:
    """
    Detect specific Chinese series tag to trigger overwrite.
    Target phrase: 明镜与点点栏目
    """

    def sanitize_text(s: str) -> str:
        # Remove BOM, control chars, zero-width chars
        s = s.replace("\ufeff", "")
        return "".join(
            ch for ch in s
            if ch.isprintable() or ch in ("\n", "\r", "\t")
        )

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            raw_content = f.read()

        if not raw_content:
            return False

        text = sanitize_text(raw_content)

        # ⚠️ Không gửi raw content lên Discord
        send_discord_message("🔍 Kiểm tra từ khóa đặc biệt trong SRT...", f"File: {path}")

        # ---- Exact keyword variants ----
        targets = [
            "明镜与点点栏目",
            "明镜点点栏目",
            "明镜 與 點點 欄目",
            "明鏡與點點欄目",
            "明鏡點點欄目",
            "明镜 与 点点 栏目",
            "明镜  点点  栏目",
        ]

        if any(t in text for t in targets):
            return True

        # ---- Partial character heuristic (>= 3 chars) ----
        phrase = "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目"
        allowed_chars = set(phrase.replace(" ", ""))

        for line in text.splitlines():
            try:
                match_count = sum(1 for ch in line if ch in allowed_chars)
                if match_count >= 5:
                    send_discord_message(
                        "🔍 Phát hiện từ khóa đặc biệt trong dòng phụ đề:",
                        sanitize_text(line)
                    )
                    return True
            except Exception:
                continue

        # ---- Structural SRT heuristics ----
        import re
        ts_pattern = re.compile(
            r"(\d{2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{1,3})"
        )

        matches = ts_pattern.findall(text)
        seg_count = len(matches)

        if seg_count == 0 or seg_count < 15:
            send_discord_message("🔍 Phát hiện số đoạn phụ đề thấp:", str(seg_count))
            return True

        for start_s, end_s in matches:
            try:
                start_sec = _parse_srt_timestamp_to_seconds(start_s)
                end_sec = _parse_srt_timestamp_to_seconds(end_s)
                if (end_sec - start_sec) > 25.0:
                    send_discord_message(
                        "🔍 Phát hiện đoạn phụ đề dài hơn 25 giây:",
                        f"{start_s} --> {end_s}"
                    )
                    return True
            except Exception:
                continue

        return False

    except Exception as e:
        send_discord_message("❌ Lỗi khi kiểm tra SRT:", str(e))
        return False


def download_video(url,output_filename="video.mp4"):
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    output_path = os.path.join(DOWNLOAD_DIR, output_filename)

    send_discord_message("🎬 Đang tải video bằng yt-dlp")
    cmd = [
        "yt-dlp",
        "-f", "bv*+ba/b",
        "--merge-output-format", "mp4",
        "-o", output_path,
        url
    ]

    last_exc = None
    for attempt in range(1, 6):
        try:
            print("Running command:", " ".join(cmd))
            run_logged_subprocess(cmd, check=True)
            return output_path
        except Exception as e:
            last_exc = e
            send_discord_message(f"⚠️ Lỗi khi tải video (lần {attempt}/5): {e}")
            if attempt == 5:
                send_discord_message("❌ Tải video thất bại sau 5 lần thử.")
                raise
            time.sleep(1 + attempt)

# ---------------------------------------------------------
# Format SRT timestamp
# ---------------------------------------------------------
def format_ts(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:02}:{m:02}:{s:06.3f}".replace(".", ",")


# ---------------------------------------------------------
# Transcribe using ONLY faster-whisper
# ---------------------------------------------------------
def transcribe(video_path, task_id: Optional[str] = None,passwisper:bool = False) -> str:
    """Transcribe Chinese speech to SRT using OpenAI Whisper (CPU, fp16 disabled)."""
    # If SRT already exists for this video, skip re-transcription
    srt_path = video_path.replace(".mp4", ".srt")
    vi_srt = srt_path.replace(".srt", ".vi.srt")
    if os.path.exists(srt_path):
        send_discord_message("ℹ️ Phát hiện phụ đề đã tồn tại:", srt_path)
        # If existing SRT contains special keywords, re-run transcription with Gemini
        try:
                if _srt_contains_keywords(srt_path):
                    send_discord_message("🔁 Phát hiện từ khóa đặc biệt trong SRT → re-transcribe bằng Gemini...")
                    tmp_wav = os.path.splitext(video_path)[0] + ".gemini.wav"
                    try:
                        run_logged_subprocess(["ffmpeg", "-y", "-i", video_path, "-ar", "16000", "-ac", "1", "-vn", tmp_wav], check=True)
                        srt_path, vi_srt = _create_srt_from_post_api_with_retries(tmp_wav, output_srt=srt_path, out_vi=vi_srt)
                    finally:
                        try:
                            if os.path.exists(tmp_wav):
                                os.remove(tmp_wav)
                        except Exception:
                            pass
                send_discord_message("✅ Đã ghi đè SRT bằng Gemini:", srt_path)
        except Exception as e_existing:
            send_discord_message(f"⚠️ Re-transcribe bằng Gemini thất bại: {e_existing}")

        # Proceed to translation using the existing (or overwritten) SRT
        api_key = os.environ.get("GEMINI_API_KEY_Translate") or os.environ.get("GOOGLE_TTS_API_KEY")
      
        # If Vietnamese SRT already exists, skip translation as well
        if os.path.exists(vi_srt):
            send_discord_message("ℹ️ Phát hiện phụ đề tiếng Việt đã tồn tại, bỏ qua dịch:", vi_srt)
            return vi_srt
        attempts = 3
        last_err = None
        for i in range(1, attempts + 1):
            try:
                send_discord_message(f"🔁 ({i}/{attempts}) Dịch phụ đề sang tiếng Việt bằng Gemini...")
                translated = translate_srt_file(
                    srt_path,
                    output_srt=vi_srt,
                    task_id=task_id,
                )
                # If translation produced/updated vi_srt, purge any existing narration artefacts
                try:
                    # Purge old narration artefacts by filename matching instead of meta.json.
                    # We consider files in the same directory whose basename contains the
                    # SRT base name and end with ".nar.*" (mp4, flac, schedule.json, etc.).
                    import glob
                    srt_base_noext = os.path.splitext(vi_srt)[0]
                    srt_dir = os.path.dirname(vi_srt) or '.'
                    srt_base_name = os.path.basename(srt_base_noext)
                    patterns = [
                        os.path.join(srt_dir, f"{srt_base_name}*.nar.*"),
                        os.path.join(srt_dir, f"{srt_base_name}*.nar*"),
                        os.path.join(srt_dir, f"*{srt_base_name}*.nar.*"),
                    ]
                    candidates = set()
                    for pat in patterns:
                        try:
                            candidates.update(glob.glob(pat))
                        except Exception:
                            continue
                    # Determine whether the SRT filename itself contains the task id.
                    # If the SRT filename does not include the task id, treat as "no task id provided"
                    # and preserve existing narration artefacts (compatibility with old runs).
                    srt_basename = os.path.basename(vi_srt)
                    srt_has_task = bool(task_id) and str(task_id) in srt_basename
                    for p in candidates:
                        try:
                            bn = os.path.basename(p)
                            if srt_has_task:
                                # Remove candidates that do not include this task id in their filename
                                if str(task_id) in bn:
                                    continue
                                try:
                                    os.remove(p)
                                except Exception:
                                    pass
                            else:
                                # SRT filename lacks a task id -> treat as old-format run; keep artifacts
                                continue
                        except Exception:
                            pass
                except Exception:
                    pass
                except Exception:
                    pass
                send_discord_message("✅ Đã tạo phụ đề tiếng Việt:", translated)
                return translated
            except Exception as e:
                last_err = e
                send_discord_message(f"⚠️ Lần dịch {i}/{attempts} thất bại: {e}")
                traceback.print_exc()

        send_discord_message("❌ Dịch phụ đề sang tiếng Việt thất bại sau 3 lần. Dừng tiến trình.")
        raise RuntimeError(f"translate_srt_file failed after {attempts} attempts: {last_err}")

    send_discord_message("🔍 Bắt đầu tạo phụ đề (ưu tiên Faster-Whisper)...")

    segments = []
    # Try faster-whisper first (preferred)
    fw_model = get_fast_whisper_model()
    if fw_model is not None and not passwisper:
        try:
            send_discord_message("🎙️ Đang tạo phụ đề tiếng Trung (Faster-Whisper)...")
            tmp_wav = os.path.splitext(video_path)[0] + ".clean.wav"
            try:
                _export_filtered_wav(video_path, tmp_wav)
            except Exception as e:
                send_discord_message(f"⚠️ Lỗi khi xuất WAV lọc: {e}")
                raise
            fw_result = fw_model.transcribe(
                tmp_wav,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=800,  # chỉ cắt khi silence đủ dài
                    speech_pad_ms=600,            # đệm trước/sau nhiều hơn
                    threshold=0.45,               # dễ nhận là speech hơn
                )
            )
            # faster-whisper may return (segments, info) tuple
            if isinstance(fw_result, tuple) and len(fw_result) >= 1:
                segments = fw_result[0] or []
            elif isinstance(fw_result, dict) and "segments" in fw_result:
                segments = fw_result.get("segments", [])
            else:
                try:
                    # collect iterable of segments
                    segments = [s for s in fw_result]
                except Exception:
                    segments = []
        except Exception as e_fw:
            send_discord_message(f"⚠️ Faster-Whisper thất bại: {e_fw} — chuyển sang Gemini STT...")
            traceback.print_exc()
    elif not passwisper:
        send_discord_message("⚠️ Faster-Whisper không khả dụng, thử dùng local 'whisper' model trước khi gọi Gemini STT...")
        # Try to use OpenAI/Whisper python package as a fallback before using Gemini online STT
        try:
            wm = get_whisper_model()
            if wm is not None:
                send_discord_message("🎙️ Đang tạo phụ đề tiếng Trung (Whisper python)...")
                # whisper.load_model(...).transcribe returns dict with 'segments'
                try:
                    wh_res = wm.transcribe(video_path, language="zh")
                    segments = wh_res.get('segments', []) if isinstance(wh_res, dict) else []
                except Exception as e_wh:
                    send_discord_message(f"⚠️ Whisper model transcription failed: {e_wh}")
                    segments = []
        except Exception as e_wm:
            send_discord_message(f"⚠️ Không thể khởi tạo Whisper local: {e_wm}")
            segments = []

    # If no segments produced by faster-whisper, fallback to Gemini STT
    if not segments:
        send_discord_message("⚠️ Không có kết quả từ Faster-Whisper — chuyển sang Gemini STT...")
        tmp_wav = os.path.splitext(video_path)[0] + ".gemini.wav"
        try:
            run_logged_subprocess(["ffmpeg", "-y", "-i", video_path, "-ar", "16000", "-ac", "1", "-vn", tmp_wav], check=True)
            # create SRT using the external POST transcribe API with retries and keyword checks
            srt_path,vi_srt = _create_srt_from_post_api_with_retries(tmp_wav, output_srt=srt_path, out_vi=vi_srt)
            if srt_path:
                send_discord_message("✅ Đã tạo phụ đề bằng POST transcribe API:", srt_path)
                return  srt_path,vi_srt
            else:
                send_discord_message("⚠️ POST transcribe returned no usable SRT after retries")
                # allow fallback behavior after this block
        finally:
            try:
                if os.path.exists(tmp_wav):
                    os.remove(tmp_wav)
            except Exception:
                pass

    # Normalize and write SRT file
    segments = _normalize_segments(segments)
    _write_srt_segments(srt_path, segments)

    send_discord_message("✅ Đã tạo phụ đề:", srt_path)
    # Keyword-based switch: if sensitive patterns appear, re-run with Gemini and overwrite
    try:
        if _srt_contains_keywords(srt_path):
            send_discord_message("ℹ️ Phát hiện từ khóa đặc biệt trong SRT → re-transcribe bằng Gemini...")
            tmp_wav = os.path.splitext(video_path)[0] + ".gemini.wav"
         
            try:
                run_logged_subprocess(["ffmpeg", "-y", "-i", video_path, "-ar", "16000", "-ac", "1", "-vn", tmp_wav], check=True)
                srt_path, vi_srt = _create_srt_from_post_api_with_retries(tmp_wav, output_srt=srt_path, out_vi=vi_srt)
            finally:
                try:
                    if os.path.exists(tmp_wav):
                        os.remove(tmp_wav)
                except Exception:
                    pass
            send_discord_message("✅ Đã ghi đè SRT bằng POST transcribe API:", srt_path)
    except Exception as e_kw:
        send_discord_message(f"⚠️ Re-transcribe bằng Gemini thất bại: {e_kw}")
        traceback.print_exc()
    # Try to translate to Vietnamese (context-aware) and return the translated SRT.
    api_key = os.environ.get("GEMINI_API_KEY_Translate") or os.environ.get("GOOGLE_TTS_API_KEY")
    vi_srt = srt_path.replace(".srt", ".vi.srt")
    # If Vietnamese SRT already exists, skip translation
    if os.path.exists(vi_srt):
        send_discord_message("ℹ️ Phát hiện phụ đề tiếng Việt đã tồn tại, bỏ qua dịch:", vi_srt)
        return vi_srt
    attempts = 3
    last_err = None
    for i in range(1, attempts + 1):
        try:
            send_discord_message(f"🔁 ({i}/{attempts}) Dịch phụ đề sang tiếng Việt bằng Gemini...")
            translated = translate_srt_file(
                srt_path,
                output_srt=vi_srt,
                task_id=task_id,
            )
            # Purge narration artefacts if SRT changed
            try:
                # Purge old narration artefacts by filename matching instead of meta.json.
                import glob
                srt_base_noext = os.path.splitext(vi_srt)[0]
                srt_dir = os.path.dirname(vi_srt) or '.'
                srt_base_name = os.path.basename(srt_base_noext)
                patterns = [
                    os.path.join(srt_dir, f"{srt_base_name}*.nar.*"),
                    os.path.join(srt_dir, f"{srt_base_name}*.nar*"),
                    os.path.join(srt_dir, f"*{srt_base_name}*.nar.*"),
                ]
                candidates = set()
                for pat in patterns:
                    try:
                        candidates.update(glob.glob(pat))
                    except Exception:
                        continue
                # Determine whether the SRT filename itself contains the task id.
                # If the SRT filename does not include the task id, treat as "no task id provided"
                # and preserve existing narration artefacts (compatibility with old runs).
                srt_basename = os.path.basename(vi_srt)
                srt_has_task = bool(task_id) and str(task_id) in srt_basename
                for p in candidates:
                    try:
                        bn = os.path.basename(p)
                        if srt_has_task:
                            # Remove candidates that do not include this task id in their filename
                            if str(task_id) in bn:
                                continue
                            try:
                                os.remove(p)
                            except Exception:
                                pass
                        else:
                            # SRT filename lacks a task id -> treat as old-format run; keep artifacts
                            continue
                    except Exception:
                        pass
            except Exception:
                pass
            except Exception:
                pass
            send_discord_message("✅ Đã tạo phụ đề tiếng Việt:", translated)
            return translated
        except Exception as e:
            last_err = e
            send_discord_message(f"⚠️ Lần dịch {i}/{attempts} thất bại: {e}")
            traceback.print_exc()

    # All attempts failed → stop the process
    send_discord_message("❌ Dịch phụ đề sang tiếng Việt thất bại sau 3 lần. Dừng tiến trình.")
    raise RuntimeError(f"translate_srt_file failed after {attempts} attempts: {last_err}")

def create_chinese_gemini_srt(video_path: str, passwisper: bool = False) -> str:
    """Generate Chinese subtitles using the POST transcribe API (Gemini)."""
    srt_path = video_path.replace(".mp4", ".srt")
    if os.path.exists(srt_path):
        send_discord_message("ℹ️ Phát hiện phụ đề tiếng Trung đã tồn tại, trả về ngay:", srt_path)
        return srt_path

    tmp_wav = os.path.splitext(video_path)[0] + ".gemini.wav"
    try:
        run_logged_subprocess([
            "ffmpeg", "-y", "-i", video_path, "-ar", "16000", "-ac", "1", "-vn", tmp_wav
        ], check=True)
        result = _create_srt_from_post_api_with_retries(tmp_wav, output_srt=srt_path)
        if not result:
            raise RuntimeError("POST transcribe failed to produce a valid SRT")
        send_discord_message("✅ Đã tạo phụ đề tiếng Trung bằng POST transcribe API:", result[0])
        return result[0]
    finally:
        try:
            if os.path.exists(tmp_wav):
                os.remove(tmp_wav)
        except Exception:
            pass
def _export_filtered_wav(video_path: str, wav_path: str) -> None:
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-af", "highpass=f=80,lowpass=f=8000",
        "-c:a", "pcm_s16le",
        wav_path
    ]
    run_logged_subprocess(cmd, check=True)


def create_chinese_srt(video_path: str, passwisper: bool = False) -> str:
    """Generate Chinese subtitles from a video without any translation or trimming."""
    srt_path = video_path.replace(".mp4", ".srt")
    if os.path.exists(srt_path):
        send_discord_message("ℹ️ Phát hiện phụ đề tiếng Trung đã tồn tại, trả về ngay:", srt_path)
        return srt_path

    tmp_wav = os.path.splitext(video_path)[0] + ".clean.wav"
    try:
        _export_filtered_wav(video_path, tmp_wav)
    except Exception as e:
        send_discord_message(f"⚠️ Lỗi khi xuất WAV lọc: {e}")
        raise

    segments = []
    fw_model = get_fast_whisper_model()
    if fw_model is not None and not passwisper:
        try:
            send_discord_message("🎙️ Tạo phụ đề tiếng Trung (Faster-Whisper)...")
            fw_result  = fw_model.transcribe(
                tmp_wav,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=800,  # chỉ cắt khi silence đủ dài
                    speech_pad_ms=600,            # đệm trước/sau nhiều hơn
                    threshold=0.45,               # dễ nhận là speech hơn
                )
            )
            if isinstance(fw_result, tuple) and len(fw_result) >= 1:
                segments = fw_result[0] or []
            elif isinstance(fw_result, dict) and "segments" in fw_result:
                    segments = fw_result.get("segments", [])
            else:
                try:
                    segments = [s for s in fw_result]
                except Exception:
                    segments = []
        except Exception as e_fw:
            send_discord_message(f"⚠️ Faster-Whisper failed for Chinese srt: {e_fw}")
            traceback.print_exc()
    elif not passwisper:
        send_discord_message("⚠️ Faster-Whisper không khả dụng, thử Whisper local...")
        try:
            wm = get_whisper_model()
            if wm is not None:
                send_discord_message("🎙️ Tạo phụ đề tiếng Trung (Whisper python)...")
                try:
                    wh_res = wm.transcribe(video_path, language="zh")
                    segments = wh_res.get('segments', []) if isinstance(wh_res, dict) else []
                except Exception as e_wh:
                    send_discord_message(f"⚠️ Whisper transcription failed: {e_wh}")
        except Exception as e_wm:
            send_discord_message(f"⚠️ Không thể khởi tạo Whisper local: {e_wm}")

    if not segments:
        send_discord_message("⚠️ Không có kết quả Faster-Whisper — dùng Gemini STT cho phụ đề tiếng Trung...")
        tmp_wav = os.path.splitext(video_path)[0] + ".gemini.wav"
        try:
            run_logged_subprocess(["ffmpeg", "-y", "-i", video_path, "-ar", "16000", "-ac", "1", "-vn", tmp_wav], check=True)
            result = _create_srt_from_post_api_with_retries(tmp_wav, output_srt=srt_path)
            if result:
                send_discord_message("✅ Đã tạo phụ đề tiếng Trung bằng POST transcribe API:", srt_path)
                return srt_path
            send_discord_message("⚠️ POST transcribe không trả về SRT hợp lệ")
        finally:
            try:
                if os.path.exists(tmp_wav):
                    os.remove(tmp_wav)
            except Exception:
                pass

    segments = _normalize_segments(segments)
    _write_srt_segments(srt_path, segments)
    send_discord_message("✅ Đã tạo phụ đề tiếng Trung:", srt_path)

    try:
        if _srt_contains_keywords(srt_path):
            send_discord_message("ℹ️ Phát hiện từ khoá đặc biệt → ghi đè bằng POST transcribe API...")
            tmp_wav = os.path.splitext(video_path)[0] + ".gemini.wav"
            try:
                run_logged_subprocess(["ffmpeg", "-y", "-i", video_path, "-ar", "16000", "-ac", "1", "-vn", tmp_wav], check=True)
                _create_srt_from_post_api_with_retries(tmp_wav, output_srt=srt_path)
            finally:
                try:
                    if os.path.exists(tmp_wav):
                        os.remove(tmp_wav)
                except Exception:
                    pass
    except Exception as e_kw:
        send_discord_message(f"⚠️ Re-transcribe keywords failed: {e_kw}")
        traceback.print_exc()

    return srt_path


def burn_subtitles_tiktok(video_path: str, srt_path: str, output_path: str | None = None) -> str:
    """Burn Vietnamese SRT onto video and produce a TikTok-ready video (9:16 vertical).

    This function will:
    - Render subtitles using ffmpeg's subtitles filter (requires ffmpeg compiled with libass)
    - Resize and pad/crop the video to 1080x1920 vertical aspect ratio suitable for TikTok
    - Output the final MP4 path
    """
    # Enforce Vietnamese subtitles only. Never burn or narrate using Chinese SRT.
    if not srt_path.lower().endswith('.vi.srt'):
        send_discord_message("❌ Không dùng phụ đề Trung để burn. Cần file .vi.srt.")
        raise RuntimeError("Expected Vietnamese SRT (.vi.srt). Refusing to burn non-Vietnamese subtitles.")

    if output_path is None:
        base = os.path.splitext(video_path)[0]
        output_path = base + ".tiktok.mp4"

    # Ensure ffmpeg is available
    try:
        run_logged_subprocess(["ffmpeg", "-version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        raise RuntimeError("ffmpeg not found on PATH. Please install ffmpeg.")

    # Convert SRT to ASS (for nicer rendering) using ffmpeg
    ass_path = srt_path.replace('.srt', '.ass')
    cmd_ass = [
        "ffmpeg", "-y",
        "-i", srt_path,
        ass_path
    ]
    # If direct conversion fails, we will fallback to using subtitles filter with srt
    try:
        run_logged_subprocess(cmd_ass, check=True)
    except Exception:
        # ignore; ffmpeg can render SRT directly
        ass_path = srt_path

    # Build ffmpeg filter: scale and pad to 1080x1920, then burn subtitles
    # First scale video to fit vertical frame while preserving aspect, then pad
    filter_complex = (
        "[0:v]scale=w=1080:h=-2:flags=lanczos,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1[v]"
    )


    # Use subtitles filter referencing ASS or SRT. Apply forced style to reduce font size,
    # add a semi-transparent black background, and move subtitles up (MarginV) so they don't
    # overlap TikTok's description/controls at bottom of the screen.
    subtitle_input = ass_path
    # escape single quotes in path for ffmpeg filter string
    subtitle_input_escaped = subtitle_input.replace("'", "\\'")
    # force style: smaller font, white text, semi-transparent black background, no outline, raised margin
    force_style = "Fontsize=28,PrimaryColour=&H00FFFFFF,BackColour=&H80000000,BorderStyle=3,Outline=0,Shadow=0,MarginV=160"
    sub_filter = f"subtitles='{subtitle_input_escaped}':force_style='{force_style}'"

    # We will run two-step: scale+pad to temp, then burn subtitles to avoid filter complexity
    temp_scaled = os.path.splitext(video_path)[0] + ".scaled.mp4"
    cmd_scale = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", "scale=w=1080:h=-2:flags=lanczos,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1",
        "-c:a", "copy",
        temp_scaled
    ]

    run_logged_subprocess(cmd_scale, check=True)

    # Burn subtitles onto temp_scaled using forced style
    cmd_burn = [
        "ffmpeg", "-y", "-i", temp_scaled,
        "-vf", sub_filter,
        "-c:a", "copy",
        output_path
    ]

    run_logged_subprocess(cmd_burn, check=True)

    # Cleanup temp
    try:
        if os.path.exists(temp_scaled):
            os.remove(temp_scaled)
    except Exception:
        pass

    return output_path


def stt_with_gemini(audio_path: str, api_key: Optional[str] = None, model: str = "gemini-2.5-flash") -> dict:
    """Transcribe `audio_path` using the GenAI `gemini` model and return parsed subtitles JSON.

    The function sends a fixed prompt instructing the model to output valid JSON
    with a `subtitles` array. It attempts to robustly extract the JSON payload from
    the SDK response and returns the parsed Python dictionary.

    Args:
        audio_path: Path to a local audio file (wav, mp3, etc.).
        api_key: Optional API key for GenAI; if omitted, reads from `GENAI_API_KEY` env var.
        model: Model name to call (default: "gemini-2.5-flash").

    Returns:
        A dict parsed from the model's JSON output (expects top-level `subtitles`).
    """
    import json
    import re
    try:
        from google import genai
    except Exception as e:
        raise RuntimeError("genai SDK is required for stt_with_gemini: " + str(e))

    client = genai.Client(api_key=api_key or os.environ.get("GENAI_API_KEY_Translate"))

    prompt = """
You are a professional speech-to-text subtitle engine.

Context of the audio:
- This is a short Chinese drama / web series episode.
- The audio consists mainly of character dialogues.
- Background music may be present.
- Sound effects (wind, footsteps, weapons, ambience) may appear.
- Characters may speak emotionally, quickly, or overlap slightly.
- Some lines may be whispered, shouted, or spoken softly.

Your task:
- Accurately transcribe ONLY spoken dialogue.
- Ignore background music and sound effects.
- Do NOT hallucinate words that are not clearly spoken.
- If a word is unclear, keep the most likely spoken word based on context.

Rules:
- Language: Simplified Chinese (zh-CN)
- Do NOT translate.
- Keep original wording, tone, and sentence structure.
- Use natural subtitle segmentation based on speech pauses and meaning.
- Each subtitle should be 1–2 lines.
- Maximum 15 Chinese characters per subtitle line.
- Do NOT merge dialogues from different speakers into one subtitle.
- Avoid repeating words unless clearly spoken twice.

Timing rules:
- Timestamps must match the spoken audio closely.
- Minimum subtitle duration: 0.8 seconds
- Maximum subtitle duration: 6.0 seconds
- Subtitles must not overlap.

Output rules:
- Output MUST be valid JSON.
- Do NOT use markdown.
- Do NOT add explanations or comments.
- Do NOT add extra fields.

Output format:
{
  "subtitles": [
    {
      "index": 1,
            "start": "00:00:00,000",
            "end": "00:00:02,400",
      "text": "台词内容"
    }
  ]
}
"""
                # NOTE: For robust downstream parsing we PREFER the model output timestamps as objects.
                # Timestamp formatting rules (strict):
                # - You MAY output timestamps as strings in HH:MM:SS,mmm, but PREFER an object form for start/end.
                # - Object form MUST be: {"Gio": <hours>, "Phut": <minutes>, "Giay": <seconds>, "Ms": <milliseconds>}
                #   Example: "start": {"Gio":0,"Phut":0,"Giay":15,"Ms":208}
                # - The model may also use English keys: {"hour":0,"minute":0,"second":15,"ms":208} — accept both.
                # - If both forms are present, the object form takes precedence.
                # - When emitting object fields, all values should be integers (hours/minutes/seconds >=0, ms 0..999).
                # - If milliseconds >=1000, carry into seconds/minutes/hours.
                # - NEVER emit compact malformed forms such as '00:15:208' — prefer object output to avoid ambiguity.

    # Use the same pattern as GeminiSTT.call_gemini: send audio bytes and prompt
    from google.genai import types
    import json

    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
            types.Part(text=prompt)
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )

    # response.text should contain JSON per the config
    try:
        return json.loads(response.text)
    except Exception:
        # fallback: try to to_dict() then extract any JSON-like field
        try:
            return response.to_dict()
        except Exception as e:
            raise ValueError("Failed to parse Gemini response: " + str(e))




def _parse_srt_timestamp_to_seconds(ts: str) -> float:
    """Parse a timestamp like 'HH:MM:SS,mmm' or 'HH:MM:SS.mmm' into seconds (float)."""
    import re
    s = ts.strip()
    if not s:
        raise ValueError(f"Invalid timestamp format: {ts}")

    # Normalize decimal separator to comma for consistent parsing
    s = s.replace('.', ',')

    # Strict patterns for canonical timestamp formats
    # 1) HH:MM:SS,mmm  (hours, minutes, seconds, milliseconds)
    # 2) MM:SS,mmm     (minutes, seconds, milliseconds)
    # 3) SS,mmm        (seconds,milliseconds) or plain float seconds
    full_re = re.compile(r"^\s*(\d{1,2}):(\d{1,2}):(\d{1,2})[,](\d{1,3})\s*$")
    mmss_re = re.compile(r"^\s*(\d{1,2}):(\d{1,2})[,](\d{1,3})\s*$")
    sec_re = re.compile(r"^\s*(\d+)[,](\d{1,3})\s*$")

    def _carry(h, m, ssec, ms):
        # normalize carries: ms->s, s->m, m->h
        if ms >= 1000:
            extra_s = ms // 1000
            ms = ms % 1000
            ssec += extra_s
        if ssec >= 60:
            extra_m = ssec // 60
            ssec = ssec % 60
            m += extra_m
        if m >= 60:
            extra_h = m // 60
            m = m % 60
            h += extra_h
        total = h * 3600 + m * 60 + ssec + ms / 1000.0
        return float(total)

    m = full_re.match(s)
    if m:
        h = int(m.group(1))
        mnt = int(m.group(2))
        sec = int(m.group(3))
        ms = int((m.group(4) + '000')[:3])
        return _carry(h, mnt, sec, ms)

    m = mmss_re.match(s)
    if m:
        mnt = int(m.group(1))
        sec = int(m.group(2))
        ms = int((m.group(3) + '000')[:3])
        return _carry(0, mnt, sec, ms)

    m = sec_re.match(s)
    if m:
        sec = int(m.group(1))
        ms = int((m.group(2) + '000')[:3])
        return float(sec + ms / 1000.0)

    # Fallback: try parse as plain float seconds
    try:
        return float(s.replace(',', '.'))
    except Exception:
        raise ValueError(f"Invalid timestamp format: {ts}")


def _parse_time_object_to_seconds(obj) -> float:
    """Convert a timestamp object to seconds.

    Accepts dicts with keys in Vietnamese (Gio, Phut, Giay, Ms) or English
    (hour, minute, second, ms) and returns total seconds as float.
    Missing fields default to 0. Values may be strings or numbers.
    """
    if obj is None:
        raise ValueError("Empty time object")
    if not isinstance(obj, dict):
        raise ValueError("Time object must be a dict")

    def get_int(keys, default=0):
        for k in keys:
            if k in obj:
                try:
                    return int(obj[k])
                except Exception:
                    try:
                        return int(float(obj[k]))
                    except Exception:
                        return default
        return default

    h = get_int(["Gio", "gio", "Hour", "hour", "hours", "H", "h"], 0)
    m = get_int(["Phut", "phut", "Minute", "minute", "minutes", "M", "m"], 0)
    s = get_int(["Giay", "giay", "Second", "second", "seconds", "S", "s"], 0)
    ms = get_int(["Ms", "ms", "Milli", "milli", "milliseconds", "Milliseconds"], 0)

    # carry ms->s, s->m, m->h
    if ms >= 1000:
        extra_s = ms // 1000
        ms = ms % 1000
        s += extra_s
    if s >= 60:
        extra_m = s // 60
        s = s % 60
        m += extra_m
    if m >= 60:
        extra_h = m // 60
        m = m % 60
        h += extra_h

    total = h * 3600 + m * 60 + s + ms / 1000.0
    return float(total)


_SENTENCE_SPLIT_PATTERN = re.compile(r'.+?[。.!?！？；;:]+|.+$', re.UNICODE)


def _split_text_into_chunks(text: str) -> list[str]:
    if not text:
        return []
    parts = [part.strip() for part in _SENTENCE_SPLIT_PATTERN.findall(text) if part.strip()]
    if not parts:
        parts = [text.strip()]
    return parts or [text.strip()]


def _coerce_to_seconds(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except Exception:
            try:
                return _parse_srt_timestamp_to_seconds(value)
            except Exception:
                return 0.0
    return 0.0


def _split_segment_into_chunks(segment: dict) -> list[dict]:
    text = (segment.get("text") or "").strip()
    if not text:
        return [segment]
    texts = _split_text_into_chunks(text)
    if len(texts) <= 1:
        return [segment]
    start = _coerce_to_seconds(segment.get("start", 0.0))
    end = _coerce_to_seconds(segment.get("end", start + 2.0))
    if end <= start:
        end = start + 0.2 * len(texts)
    duration = end - start
    total = len(texts)
    chunks = []
    for idx, chunk_text in enumerate(texts):
        chunk_start = start + duration * idx / total
        chunk_end = start + duration * (idx + 1) / total
        if idx == total - 1:
            chunk_end = end
        chunks.append({
            "start": chunk_start,
            "end": chunk_end,
            "text": chunk_text
        })
    return chunks


def _expand_segments_by_length(segments: list) -> list:
    result = []
    for seg in segments:
        result.extend(_split_segment_into_chunks(seg))
    return result


def create_bilingual_srt_from_gemini(audio_path: str, out_zh: str | None = None, out_vi: str | None = None, api_key: Optional[str] = None, model: str = "gemini-2.5-flash") -> tuple[str, str]:
    """Call Gemini to produce bilingual subtitles (Chinese + Vietnamese) and write two SRT files.

    Returns (zh_srt_path, vi_srt_path).
    """
    import json
    try:
        from google import genai
        from google.genai import types
    except Exception as e:
        raise RuntimeError("genai SDK is required for create_bilingual_srt_from_gemini: " + str(e))

    if out_zh is None or out_vi is None:
        base = os.path.splitext(audio_path)[0]
        if out_zh is None:
            out_zh = base + ".srt"
        if out_vi is None:
            out_vi = base + ".vi.srt"

    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

        # Prompt instructing Gemini to produce bilingual segments (Chinese + Vietnamese)
        prompt = """
Bạn là trình dịch phụ đề phim chuyên nghiệp (Chinese → Vietnamese).

Ngữ cảnh:
- Audio từ phim ngắn / tập phim ngắn bằng tiếng Trung, chủ yếu là thoại nhân vật.
- Có thể có nhạc nền và hiệu ứng âm thanh; hãy bỏ qua những âm thanh không phải thoại.

Nhiệm vụ:
1. Chuyển lời thoại tiếng Trung chính xác (không dịch sang tiếng Việt ở trường hợp không có lời nói).
2. Dịch mỗi câu thoại sang tiếng Việt theo phong cách bên dưới.
3. Cung cấp mốc thời gian chính xác của âm thanh trên video (Giờ:Phút:Giây:miligiay) cho mỗi phụ đề.

PHONG CÁCH DỊCH:
- Ngôn ngữ tự nhiên, ngắn gọn, đúng thoại phim.
- Ưu tiên ngắn nhất có thể nhưng vẫn đủ nghĩa.
- KHÔNG thêm chú thích, KHÔNG giải thích, KHÔNG thêm từ không có trong thoại.
- Giữ tông và ý nghĩa gốc của lời thoại.
⏱️ Cấu trúc thời gian BẮT BUỘC

Thời gian KHÔNG ĐƯỢC suy diễn từ chuỗi.
Luôn dùng 4 trường JSON tách biệt:

Gio = giờ (0–23)

Phut = phút (0–59)

Giay = giây (0–59)

miligiay = mili giây (0–999)

TUYỆT ĐỐI CẤM

- Không parse từ dạng chuỗi H:M:S:MS

- Không đổi giây thành phút

- Không để Giay > 59
- Không tự “chuẩn hóa” thời gian

- Không suy luận hoặc làm tròn

ÁNH XẠ ĐÚNG (BẮT BUỘC TUÂN THỦ)

Nếu audio là:

- 0 giờ 0 phút 15 giây 200 mili giây

THÌ output CHỈ ĐƯỢC là:

 {"Gio":0,"Phut":0,"Giay":15,"miligiay":200}


Ví dụ SAI (CẤM TUYỆT ĐỐI):

 {"Gio":0,"Phut":15,"Giay":200,"miligiay":0}

Quy tắc kỹ thuật:
- Bản gốc: Simplified Chinese (zh-CN).
- Mỗi phụ đề 1–2 dòng; thời lượng phụ đề: tối thiểu 0.8s, tối đa 6.0s.
- Không để phụ đề chồng lấp.
- Output phải là JSON hợp lệ, không dùng markdown, không có giải thích thêm.

Định dạng đầu ra:
{
    "segments": [
        {
            "index": 1,
            "start": {"Gio":0,"Phut":0,"Giay":0,"miligiay":200},
            "end": {"Gio":0,"Phut":0,"Giay":2,"miligiay":400},
            "text_zh": "中文原句",
            "text_vi": "Bản dịch tiếng Việt ngắn gọn"
        }
    ]
}
"""
                # Timestamp formatting rules (strict):
                # - Prefer object timestamps for start/end using Vietnamese keys:
                #     "start": {"Gio": 0, "Phut": 0, "Giay": 1, "Ms": 200}
                #   Accept English variants as well: {"hour":0,"minute":0,"second":1,"ms":200}
                # - If object form is not used, string timestamps must follow HH:MM:SS,mmm exactly.
                # - All numeric fields should be integers; ms in 0..999 (carry if >=1000).
                # - NEVER output ambiguous compact forms like '00:15:208'. If such output would occur,
                #   instead return the object form or correct string form (e.g. '00:00:15,208').

    client = genai.Client(api_key=api_key or os.environ.get("GENAI_API_KEY_Translate") or os.environ.get("GENAI_API_KEY"))
    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
            types.Part(text=prompt)
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )

    try:
        data = json.loads(response.text)

    except Exception:
        try:
            data = response.to_dict()
        except Exception as e:
            raise ValueError("Failed to parse Gemini response: " + str(e))

    segments = data.get("segments") or data.get("subtitles") or []
    if not segments:
        raise ValueError("No segments returned from Gemini")
    send_discord_message(segments)
    zh_segs = []
    vi_segs = []
    for seg in segments:
        start_raw = seg.get("start")
        end_raw = seg.get("end")
        text_zh = seg.get("text_zh") or seg.get("text") or seg.get("text_cn") or ""
        text_vi = seg.get("text_vi") or seg.get("text_vi") or seg.get("translation") or ""

        try:
            if isinstance(start_raw, (int, float)):
                start = float(start_raw)
            elif isinstance(start_raw, str):
                start = _parse_srt_timestamp_to_seconds(start_raw)
            elif isinstance(start_raw, dict):
                start = _parse_time_object_to_seconds(start_raw)
            else:
                start = 0.0
        except Exception:
            start = 0.0

        try:
            if isinstance(end_raw, (int, float)):
                end = float(end_raw)
            elif isinstance(end_raw, str):
                end = _parse_srt_timestamp_to_seconds(end_raw)
            elif isinstance(end_raw, dict):
                end = _parse_time_object_to_seconds(end_raw)
            else:
                end = start + 2.0
        except Exception:
            end = start + 2.0

        zh_segs.append({"start": start, "end": end, "text": text_zh.strip()})
        vi_segs.append({"start": start, "end": end, "text": text_vi.strip()})

    _write_srt_segments(out_zh, zh_segs)
    _write_srt_segments(out_vi, vi_segs)
    send_discord_message("✅ Đã tạo phụ đề song ngữ (zh/vi):", out_zh)
    send_discord_message("✅ Đã tạo phụ đề song ngữ (zh/vi):", out_vi)
    return out_zh, out_vi


def create_srt_from_gemini(audio_path: str, output_srt: str | None = None, api_key: Optional[str] = None, model: str = "gemini-2.5-flash",out_vi: str | None = None) -> str:
    """Run STT via Gemini and write an SRT file.

    Returns the path to the generated SRT file.
    """
    # Prefer producing bilingual SRTs (zh + vi) using GeminiSTT-style helper
    try:
        base = os.path.splitext(audio_path)[0]
        # If caller provided an explicit output_srt path, use it directly.
        out_zh = output_srt if output_srt is not None else base + ".srt"
        # Determine Vietnamese output path: prefer explicit out_vi, otherwise same base with .vi.srt
        out_vi_path = out_vi if out_vi is not None else (os.path.splitext(out_zh)[0] + ".vi.srt")
        # Create bilingual SRTs (zh + vi) and return the Chinese SRT path (for backward compatibility)
        zh_path, vi_path = create_bilingual_srt_from_gemini(audio_path, out_zh=out_zh, out_vi=out_vi_path, api_key=api_key, model=model)
        return zh_path
    except Exception:
        # Fallback to single-language parsing if bilingual helper fails
        if output_srt is None:
            base = os.path.splitext(audio_path)[0]
            output_srt = base + ".srt"

        parsed = stt_with_gemini(audio_path, api_key=api_key, model=model)
        subs = parsed.get("subtitles") or parsed.get("segments")
        if not subs:
            raise ValueError("No subtitles found in Gemini response")

        segments = []
        for i, item in enumerate(subs, start=1):
            # Accept either 'start'/'end' as strings or numeric seconds
            start_val = item.get("start")
            end_val = item.get("end")
            text = item.get("text") or item.get("content") or item.get("payload") or ""

            if isinstance(start_val, (int, float)):
                start = float(start_val)
            elif isinstance(start_val, str):
                start = _parse_srt_timestamp_to_seconds(start_val)
            elif isinstance(start_val, dict):
                start = _parse_time_object_to_seconds(start_val)
            else:
                start = None

            if isinstance(end_val, (int, float)):
                end = float(end_val)
            elif isinstance(end_val, str):
                end = _parse_srt_timestamp_to_seconds(end_val)
            elif isinstance(end_val, dict):
                end = _parse_time_object_to_seconds(end_val)
            else:
                end = None

            # If end is missing, attempt to infer 2 seconds duration
            if start is None:
                continue
            if end is None:
                end = start + 2.0

            segments.append({"start": start, "end": end, "text": text.strip()})

        _write_srt_segments(output_srt, segments)
        send_discord_message("✅ Đã tạo SRT từ Gemini:", output_srt)
        return output_srt

phrase = "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目"
allowed = set(phrase.replace(" ", ""))
def contains_at_least_n_chars(s, n=4):
    return sum(1 for ch in s if ch in allowed) >= n
if __name__ == "__main__":
    wave_file = "Than_cau_ca_giang_lam_Tap_2_download.gemini.wav";
    _create_srt_from_post_api_with_retries(wave_file, output_srt="Than_cau_ca_giang_lam_Tap_2.srt", out_vi="Than_cau_ca_giang_lam_Tap_2.vi.srt")


