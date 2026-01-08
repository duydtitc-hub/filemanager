import os
import re
import json
import time
import base64
from typing import List, Tuple, Optional
from collections import Counter
import requests
import hashlib
import json as _json
from DiscordMethod import send_discord_message
# ================= CONFIG =================
# External translation API (n8n webhook)
TRANSLATE_ENDPOINT = os.environ.get(
    "SRT_TRANSLATE_ENDPOINT",
    "https://n8n.vietravel.com/webhook/c892de19-3b20-4b32-b9ee-6b6847b0e77a",
)
# Optional Task ID to track jobs
DEFAULT_TASK_ID = os.environ.get("SRT_TASK_ID")
# Batch size for API calls (per user request)
BATCH_SIZE = 100
# =========================================

# Optional: use GenAI (Gemini) directly when the external webhook is unavailable.
USE_GEMINI_DIRECT = os.environ.get("USE_GEMINI_TRANSLATE", "1") == "1"
GENAI_TRANSLATE_MODEL = os.environ.get("GENAI_TRANSLATE_MODEL", "gemini-2.5-flash")

# ---------- SRT ----------
def read_srt(path: str) -> List[Tuple[str, str, str]]:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    blocks = re.split(r"\n\s*\n", content)
    subs = []
    for b in blocks:
        lines = b.splitlines()
        if len(lines) >= 3:
            subs.append((lines[0], lines[1], "\n".join(lines[2:])))
    return subs


def write_srt(entries, out_path):
    with open(out_path, "w", encoding="utf-8") as f:
        for i, t, txt in entries:
            f.write(f"{i}\n{t}\n{txt}\n\n")


# ---------- PROMPT ----------
def build_prompt(sections: List[str]) -> str:
    prompt = """You translate Chinese short-drama subtitles into Vietnamese.

        ROLE:
        You are an experienced subtitle translator for Chinese short dramas.
        Your goal is natural, emotionally accurate Vietnamese that sounds like real movie dialogue.

        CORE RULES:
        - Translate ONLY the text inside 【CURRENT】
        - Each section MUST produce EXACTLY one subtitle
        - NEVER merge, split, expand, or summarize subtitles
        - NEVER include or repeat words, phrases, or ideas from PREV or NEXT

        STYLE & PRONOUNS:
        - Use natural Vietnamese spoken in movies
        - You MAY use "anh / em" when it clearly sounds natural
        - Do NOT overthink relationships; avoid forced formality
        - Keep sentences short, punchy, and suitable for fast-paced scenes
        - Preserve line breaks EXACTLY as in the source

        EMPTY / ANCHOR HANDLING:
        - If 【CURRENT】 is empty, symbols-only, or equals [ANCHOR_DO_NOT_TRANSLATE],
        return an empty string ""

        OUTPUT FORMAT:
        - Return ONLY a RAW JSON ARRAY OF STRINGS
        - The array length MUST exactly match the number of sections
        - Output order MUST match section order
        - NO markdown, NO explanations, NO extra text
        """

    for sec in sections:
        prompt += sec + "\n\n"

    return prompt


# ---------- GEMINI ----------
def _post_translate_api(srt_text: str, task_id: Optional[str]) -> str:
    """Send listsub (raw SRT-style blocks) to external API and return translated listsub text.

    Expected form fields:
    - listsub: raw SRT-like text (index, timestamp, text) for a batch slice
    - TaskId: identifier for tracking

    Returns translated listsub text (same format), from either JSON {content|listsub} or raw text body.
    """
    try:
        if not task_id and not DEFAULT_TASK_ID:
            raise ValueError("TaskId is required for translation API. Provide task_id or set SRT_TASK_ID env.")
        payload = {
            "listsub": srt_text,
            "TaskId": task_id or DEFAULT_TASK_ID,
        }
        try:
            resp = requests.post(TRANSLATE_ENDPOINT, data=payload, timeout=60*15)
        except Exception as net_err:
            send_discord_message(f"❌ External SRT translate API network error: {net_err}")
            raise

        resp_text = None
        try:
            resp_text = resp.text
        except Exception:
            resp_text = None

        if not (200 <= resp.status_code < 300):
            body_preview = resp_text[:1000] if resp_text else "<no body>"
            send_discord_message(f"❌ External SRT translate API HTTP {resp.status_code}: {body_preview}")
            raise RuntimeError(f"HTTP {resp.status_code}: {body_preview}")

        # If JSON, prefer explicit fields
        ctype = resp.headers.get("Content-Type", "")
        if "application/json" in ctype:
            try:
                data = resp.json()
            except Exception as je:
                send_discord_message(f"❌ External SRT translate API returned invalid JSON: {je}; body: {resp_text[:1000] if resp_text else '<no body>'}")
                raise
            content = None
            # include common error/message fields in discord notification if present
            if isinstance(data, dict):
                if data.get("error"):
                    send_discord_message(f"❌ External SRT translate API error: {data.get('error')}")
                if data.get("message"):
                    send_discord_message(f"❌ External SRT translate API message: {data.get('message')}")
                content = data.get("listsub") or data.get("content")
            if not isinstance(content, str):
                send_discord_message(f"❌ External SRT translate API returned unexpected JSON shape: {json.dumps(data)[:1000]}")
                raise ValueError(f"Invalid response JSON: {data}")
            return content

        # Fallback: treat raw text as translated listsub
        return resp_text or ""
    except Exception as e:
        send_discord_message(f"❌ External SRT translate API failed: {e}")
        raise


def _translate_with_gemini_json(slice_entries, task_id: Optional[str]) -> List[str]:
    """Translate a list of subtitle entries ([(idx,timestamp,text),...]) using Gemini/GenAI.

    Returns a list of translated text strings in the same order as slice_entries.
    This function enforces the JSON rules described in the provided prompt: single-line
    "text" values, valid JSON output, no surrounding markup.
    """
    try:
        try:
            from google import genai
            from google.genai import types
        except Exception as e:
            raise RuntimeError("genai SDK not available: " + str(e))

        client = genai.Client(api_key=os.environ.get("GENAI_API_KEY") or os.environ.get("GENAI_API_KEY_Translate"))

        # Build input JSON array expected by the prompt
        inp = []
        for idx, ts, txt in slice_entries:
            # ensure single-line text
            one_line = " ".join(str(txt).splitlines()).strip()
            try:
                idx_num = int(str(idx).strip())
            except Exception:
                idx_num = str(idx)
            inp.append({"index": idx_num, "start": ts, "end": ts, "text": one_line})

        input_json = json.dumps(inp, ensure_ascii=False)

        # Use the exact prompt body requested by user (no memory, no surrounding text)
        prompt = (
            "Bạn là trình dịch phụ đề phim chuyên nghiệp (Chinese → Vietnamese).\n\n"
            "NHIỆM VỤ:\n- Dịch mảng JSON phụ đề từ tiếng Trung sang tiếng Việt.\n- Giữ nguyên index, start, end.\n- Chỉ dịch giá trị \\\"text\\\".\n\n"
            "PHONG CÁCH DỊCH:\n- Ngôn ngữ tự nhiên, ngắn gọn, đúng thoại phim.\n- Ưu tiên ngắn nhất có thể nhưng vẫn đủ nghĩa.\n- KHÔNG thêm chú thích, KHÔNG giải thích.\n\n"
            "NGỮ CẢNH:\n- Sử dụng taskid " + (str(task_id) if task_id else "") + " để giữ ngữ cảnh dịch nhất quán giữa các đoạn.\n\n"
            "QUY TẮC JSON (BẮT BUỘC TUÂN THỦ):\n"
            "1. CHỈ trả về JSON hợp lệ theo RFC 8259.\n"
            "2. KHÔNG dùng markdown.\n"
            "3. KHÔNG dùng ```json hoặc bất kỳ ký hiệu bao quanh nào.\n"
            "4. KHÔNG thêm bất kỳ text nào ngoài JSON.\n"
            "5. Mọi dấu \\\" xuất hiện trong text PHẢI escape thành \\\\\\\".\n"
            "6. Giá trị \\\"text\\\" PHẢI nằm trên 1 dòng, KHÔNG xuống dòng.\n"
            "7. Output PHẢI parse được trực tiếp bằng JSON.parse() trong JavaScript.\n"
            "8. Nếu không chắc chắn về dấu câu, hãy dùng dấu chấm hoặc bỏ dấu ngoặc kép để tránh lỗi JSON.\n\n"
            "INPUT JSON:\n"
        )

        prompt += input_json + "\n\nOUTPUT FORMAT (CHÍNH XÁC):\n{\n  \"subtitles\": [\n    {\n      \"index\": 1,\n      \"start\": \"00:00:00,000\",\n      \"end\": \"00:00:02,000\",\n      \"text\": \"phụ đề tiếng Việt\"\n    }\n  ]\n}\n"


        last_exc = None
        for attempt in range(1, 4):
            try:
                response = client.models.generate_content(
                    model=GENAI_TRANSLATE_MODEL,
                    contents=[types.Part(text=prompt)],
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )

                # Prefer structured candidate path if available (response.candidates[0].content.parts[0].text)
                text = None
                try:
                    candidates = getattr(response, "candidates", None)
                    if candidates and len(candidates) > 0:
                        cand0 = candidates[0]
                        content = getattr(cand0, "content", None)
                        if content is not None:
                            parts = getattr(content, "parts", None)
                            if parts and len(parts) > 0:
                                part0 = parts[0]
                                maybe_text = getattr(part0, "text", None)
                                if maybe_text:
                                    text = maybe_text
                except Exception:
                    text = None

                # Fallback to response.text or to_dict if structured path not present
                if not text:
                    text = getattr(response, "text", None)
                if not text:
                    try:
                        text = json.dumps(response.to_dict(), ensure_ascii=False)
                    except Exception:
                        raise RuntimeError("Empty response from GenAI translate")

                # Try direct JSON parse; if fails, attempt to extract JSON substring
                def _extract_json(s: str) -> object:
                    try:
                        return json.loads(s)
                    except Exception:
                        # find first { or [ and last } or ]
                        first_cur = min([i for i in [s.find('{'), s.find('[')] if i >= 0]) if ('{' in s or '[' in s) else -1
                        if first_cur < 0:
                            raise
                        last_cur = max(s.rfind('}'), s.rfind(']'))
                        if last_cur <= first_cur:
                            raise
                        candidate = s[first_cur:last_cur+1]
                        try:
                            return json.loads(candidate)
                        except Exception as e2:
                            raise RuntimeError(f"JSON parse failed: {e2}")

                parsed = _extract_json(text)

                # 3️⃣ Detect subtitles theo nhiều schema AI có thể trả
                subtitles = None
                if isinstance(parsed, list):
                    subtitles = parsed
                elif isinstance(parsed, dict):
                    if isinstance(parsed.get("subtitles"), list):
                        subtitles = parsed.get("subtitles")
                    elif isinstance(parsed.get("data"), list):
                        subtitles = parsed.get("data")
                    elif parsed.get("result") and isinstance(parsed.get("result").get("subtitles"), list):
                        subtitles = parsed.get("result").get("subtitles")
                if subtitles is None:
                    raise ValueError("Cannot detect subtitles array from AI output")

                out_texts: List[str] = []
                for item in subtitles:
                    if isinstance(item, dict):
                        t = item.get("text") or item.get("text_vi") or item.get("translation") or ""
                    else:
                        t = str(item)
                    t1 = " ".join(str(t).splitlines()).strip()
                    out_texts.append(t1)
                # success
                break
            except Exception as e:
                last_exc = e
                send_discord_message(f"⚠️ Gemini translate attempt {attempt}/3 failed: {e}")
                if attempt < 3:
                    time.sleep(1 * attempt)
                    continue
                else:
                    raise


        # Normalize length
        expected = len(slice_entries)
        if len(out_texts) > expected:
            out_texts = out_texts[:expected]
        elif len(out_texts) < expected:
            out_texts.extend([""] * (expected - len(out_texts)))

        # Check for suspiciously duplicated translations.
        # If Gemini returned the same non-empty text for all (or nearly all)
        # items, treat this as a failure so the caller can fallback to webhook.
        try:
            uniq = set(out_texts)
            if expected > 0:
                most_common, freq = Counter(out_texts).most_common(1)[0]
                # all identical and non-empty -> likely bad
                if len(uniq) == 1 and most_common.strip() != "":
                    send_discord_message(f"⚠️ Gemini translate returned identical text for all {expected} items: '{most_common[:80]}'")
                    raise ValueError("Gemini returned identical translations for all items")
                # or overwhelmingly identical (>=90%) and non-empty -> suspicious
                if freq / expected >= 0.9 and most_common.strip() != "":
                    send_discord_message(f"⚠️ Gemini translate returned {freq}/{expected} identical items — aborting to allow fallback")
                    raise ValueError("Gemini returned overwhelmingly identical translations")
        except Exception:
            # If duplicate-check fails unexpectedly, prefer to raise to trigger fallback.
            raise

        return out_texts

    except Exception as e:
        send_discord_message(f"❌ Gemini translate failed: {e}")
        raise


# ---------- TRANSLATE ----------
def translate_batch(subs, start, end, task_id: Optional[str]) -> List[str]:
    # Build a temporary SRT with only the target slice to keep alignment simple
    slice_entries = subs[start:end]
    temp_srt = ""
    for i, (idx, t, txt) in enumerate(slice_entries, start=1):
        temp_srt += f"{i}\n{t}\n{txt}\n\n"

    # If configured, use Gemini/GenAI directly (JSON in/out)
    if USE_GEMINI_DIRECT:
        try:
            return _translate_with_gemini_json(slice_entries, task_id=task_id)
        except Exception as e:
            send_discord_message(f"⚠ Gemini direct translate failed: {e} — falling back to webhook")

    # Primary: external webhook
    try:
        translated_text = _post_translate_api(temp_srt, task_id=task_id)
        # Parse returned SRT text back into list of strings (one per cue)
        blocks = re.split(r"\n\s*\n", translated_text.strip())
        out_texts: List[str] = []
        for b in blocks:
            lines = b.splitlines()
            if len(lines) >= 3:
                out_texts.append("\n".join(lines[2:]).strip())
        # Normalize length to match input slice
        expected = end - start
        if len(out_texts) > expected:
            out_texts = out_texts[:expected]
        elif len(out_texts) < expected:
            out_texts.extend([""] * (expected - len(out_texts)))
        return out_texts
    except Exception:
        # Fallback: try Gemini direct translation
        try:
            return _translate_with_gemini_json(slice_entries, task_id=task_id)
        except Exception:
            send_discord_message("⚠ Both external webhook and Gemini translate failed; returning empty strings")
            return [""] * (end - start)


# ---------- MAIN ----------
def translate_srt_file(input_srt: str, output_srt: str, task_id: Optional[str]) -> str:
    # Compute fingerprint of input SRT
    def _file_sha1(p: str) -> Optional[str]:
        try:
            h = hashlib.sha1()
            with open(p, "rb") as fh:
                while True:
                    b = fh.read(8192)
                    if not b:
                        break
                    h.update(b)
            return h.hexdigest()
        except Exception:
            return None

    def _write_meta(meta_path: str, meta: dict):
        try:
            tmp = meta_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as mf:
                _json.dump(meta, mf, ensure_ascii=False)
            os.replace(tmp, meta_path)
        except Exception:
            try:
                with open(meta_path, "w", encoding="utf-8") as mf:
                    _json.dump(meta, mf, ensure_ascii=False)
            except Exception:
                pass

    input_sha = _file_sha1(input_srt)
    meta_path = output_srt + ".meta.json"

    # If output exists, verify it was generated from the same input SRT via meta
    if os.path.exists(output_srt):
        try:
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as mf:
                    m = _json.load(mf)
                if input_sha and m.get("input_sha1") == input_sha:
                    return output_srt
        except Exception:
            # If meta is unreadable or mismatch, fall through and regenerate
            pass

    subs = read_srt(input_srt)
    result: List[Tuple[str, str, str]] = []

    for i in range(0, len(subs), BATCH_SIZE):
        end = min(i + BATCH_SIZE, len(subs))
        send_discord_message(f"▶ Translating {i+1} → {end}")

        vi_texts = translate_batch(subs, i, end, task_id=task_id)

        for (idx, t, _), txt in zip(subs[i:end], vi_texts):
            result.append((idx, t, txt))

        time.sleep(2)

    # Write translated SRT atomically
    try:
        tmp_out = output_srt + ".tmp"
        with open(tmp_out, "w", encoding="utf-8") as f:
            for i, t, txt in result:
                f.write(f"{i}\n{t}\n{txt}\n\n")
        os.replace(tmp_out, output_srt)
    except Exception:
        # fallback to direct write
        write_srt(result, output_srt)

    # Write meta so future runs can validate reuse
    try:
        meta = {"input_sha1": input_sha, "generated_at": int(time.time())}
        _write_meta(meta_path, meta)
    except Exception:
        pass

    send_discord_message("✅ DONE – External API translation complete")
    return output_srt
if __name__ == "__main__":
   translate_srt_file("Than_cau_ca_giang_lam_Tap_2_download.srt", "output.vi.srt", task_id=None)



