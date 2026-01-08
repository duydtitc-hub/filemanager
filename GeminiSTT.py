from google import genai
from google.genai import types
import json
import os
from config import GEMINI_API_KEY

# ================= CONFIG =================
API_KEY = GEMINI_API_KEY
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY environment variable is required for GeminiSTT")
AUDIO_PATH = "Than_cau_ca_giang_lam_Tap_2.wav"

OUT_ZH_SRT = "output_zh.srt"
OUT_VI_SRT = "output_vi.srt"

MODEL = "gemini-2.5-flash"
# ========================================


def build_prompt():
    return """
You are a professional subtitle transcription engine.

Context:
- This audio is from a Chinese short drama / web series.
- Mostly character dialogues.
- Background music and sound effects may exist.

Tasks:
1. Transcribe spoken dialogue in Chinese (zh-CN).
2. Provide precise timestamps (HH:MM:SS,mmm).
3. Translate each dialogue into Vietnamese.

Rules:
- Ignore background music and sound effects.
- Do NOT hallucinate missing words.
- Keep original meaning and tone.
- Use natural subtitle segmentation.
- Output valid JSON only.
- Do NOT include explanations or markdown.

Output format:
{
  "segments": [
    {
      "index": 1,
      "start": "00:00:01,200",
      "end": "00:00:03,800",
      "text_zh": "原始中文台词",
      "text_vi": "Bản dịch tiếng Việt"
    }
  ]
}
"""


def load_audio_bytes(path: str) -> bytes:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Audio file not found: {path}")
    with open(path, "rb") as f:
        return f.read()


def call_gemini(audio_bytes: bytes) -> dict:
    client = genai.Client(api_key=API_KEY)

    response = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_bytes(
                data=audio_bytes,
                mime_type="audio/wav"
            ),
            types.Part(text=build_prompt())
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )

    return json.loads(response.text)


def build_srt(segments: list, lang: str) -> str:
    """
    lang = 'zh' or 'vi'
    """
    lines = []
    for seg in segments:
        lines.append(str(seg["index"]))
        lines.append(f'{seg["start"]} --> {seg["end"]}')
        lines.append(seg[f"text_{lang}"])
        lines.append("")
    return "\n".join(lines)


def main():
    print("🔊 Loading audio...")
    audio_bytes = load_audio_bytes(AUDIO_PATH)

    print("🧠 Sending audio to Gemini STT...")
    data = call_gemini(audio_bytes)

    segments = data.get("segments", [])
    if not segments:
        raise ValueError("No segments returned from Gemini")

    print("📝 Writing SRT files...")

    with open(OUT_ZH_SRT, "w", encoding="utf-8") as f:
        f.write(build_srt(segments, "zh"))

    with open(OUT_VI_SRT, "w", encoding="utf-8") as f:
        f.write(build_srt(segments, "vi"))

    print("✅ DONE")
    print(f" - {OUT_ZH_SRT}")
    print(f" - {OUT_VI_SRT}")


if __name__ == "__main__":
    main()
