import requests
import base64
import os
import time
from dotenv import load_dotenv
from DiscordMethod import send_discord_message

# Load environment variables
load_dotenv()

# Read Google TTS API key from environment
# Prefer explicit `GOOGLE_TTS_API_KEY`.
API_KEY = os.environ.get("GOOGLE_TTS_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""

def text_to_wav(text: str, output_path: str, voice_name: str = "vi-VN-Standard-C", speaking_rate: float = 1.0,sendNotify:bool = True) -> str | None:
    # 2️⃣ Chuẩn bị payload API
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={API_KEY}"
    payload = {
        "input": {"text": text},
        "voice": {"languageCode": "vi-VN", "name": voice_name},
        "audioConfig": {"audioEncoding": "LINEAR16", "speakingRate": float(speaking_rate)}  # WAV
    }

    # 3️⃣ Gửi request với retry (3 attempts)
    max_attempts = 3
    backoff_secs = 1
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(url, json=payload, timeout=15)
            response.raise_for_status()

            # 4️⃣ Giải mã base64 và lưu file WAV
            audio_base64 = response.json().get("audioContent")
            if not audio_base64:
                raise RuntimeError("No audioContent in response")
            with open(output_path, "wb") as f:
                f.write(base64.b64decode(audio_base64))
            # if sendNotify:
            send_discord_message(f"✅ Tạo file WAV thành công: {output_path} (voice={voice_name})")
            return output_path

        except Exception as e:
            send_discord_message(f"⚠️ (attempt {attempt}/{max_attempts}) Lỗi khi gọi API/text->wav: {e}")
            if attempt < max_attempts:
                time.sleep(backoff_secs)
                backoff_secs *= 2
                continue
            else:
                send_discord_message(f"❌ Tạo WAV thất bại sau {max_attempts} lần: {e}")
                return None
            
if __name__ == "__main__":
    # Example usage
    text = "Xin chào, đây là ví dụ chuyển văn bản thành giọng nói sử dụng Google TTS."
    output_wav_path = "output.wav"
    text_to_wav(text, output_wav_path, voice_name="vi-VN-Standard-C", speaking_rate=1.0)


