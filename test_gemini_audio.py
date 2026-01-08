"""Quick manual tester for Gemini TTS and Gemini audio preparation.

Usage examples (PowerShell):

# Generate full Gemini audio from text (uses generate_audio_Gemini from app.py)
python .\test_gemini_audio.py --mode generate --text "Xin chao cac ban" --title test_gemini

# Prepare Gemini-style audio (apply voice transform + optional bg)
python .\test_gemini_audio.py --mode prepare --text "Xin chao cac ban" --bg_choice some_bg.wav

Notes:
- This script is meant as a lightweight manual test helper. It will call real functions in
  `app.py` and `GoogleTTS.py`, so network/API keys may be required (Google TTS / OpenAI).
- It writes temporary files into the current working directory (output files are printed).
"""
import argparse
import tempfile
import os
import time

from app import generate_audio_Gemini, prepare_audio_for_video_gemini,prepare_audio_for_video_gemini_male
from GoogleTTS import text_to_wav


def ensure_dir(d):
    if not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def test_generate(text: str, title: str):
    """Call generate_audio_Gemini(text, title) and report result."""
    print(f"[test] Generating Gemini audio for title='{title}' (text length={len(text)})")
    start = time.time()
    try:
        out = generate_audio_Gemini(text, title)
    except Exception as e:
        print(f"[test][ERROR] generate_audio_Gemini raised: {e}")
        raise
    elapsed = time.time() - start
    print(f"[test] Done in {elapsed:.1f}s -> {out}")
    if out and os.path.exists(out):
        print(f"[test] Output exists, size={os.path.getsize(out)} bytes")
    else:
        print(f"[test] Output file missing: {out}")
    return out


def test_prepare(text: str, bg_choice: str | None = None, narration_boost_db: float = 6.0,voice_name: str = "vi-VN-Wavenet-C"):
    """Create a temp WAV from text (via GoogleTTS.text_to_wav) then call prepare_audio_for_video_gemini.

    Returns processed audio path.
    """
    tmp_dir = os.getcwd()
    ensure_dir(tmp_dir)
    tmp_wav = os.path.join(tmp_dir, f"test_gemini_input_{int(time.time())}.wav")
    print(f"[test] Creating temp WAV via GoogleTTS: {tmp_wav}")
    try:
        created = text_to_wav(text, tmp_wav, voice_name=voice_name)
        if not created or not os.path.exists(tmp_wav):
            # text_to_wav may return path or None; check existence
            if created and os.path.exists(created):
                tmp_wav = created
            else:
                raise RuntimeError("GoogleTTS.text_to_wav failed or returned no file")
    except Exception as e:
        print(f"[test][ERROR] Failed to create temp WAV: {e}")
        raise

    print(f"[test] Calling prepare_audio_for_video_gemini on {tmp_wav} (bg_choice={bg_choice})")
    try:
        out = prepare_audio_for_video_gemini(tmp_wav, bg_choice, narration_boost_db)
    except Exception as e:
        print(f"[test][ERROR] prepare_audio_for_video_gemini raised: {e}")
        raise

    print(f"[test] Processed audio -> {out}")
    if out and os.path.exists(out):
        print(f"[test] Output exists, size={os.path.getsize(out)} bytes")
    else:
        print(f"[test] Output file missing: {out}")
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Manual tests for Gemini audio flows')
    
   
    parser.add_argument('--title', type=str, default='test_gemini')
    parser.add_argument('--bg_choice', type=str, default=None, help='Optional background WAV filename (relative to bgaudio dirs)')
    parser.add_argument('--narr_boost', type=float, default=6.0, help='Narration boost dB for prepare flow')

    args = parser.parse_args()

    test_prepare("""Về đến nhà, tôi vội tắm bằng nước nóng, rồi nằm xuống định chợp mắt một lát, nhưng cơn đau đầu khiến tôi trằn trọc mãi không ngủ nổi.

Càng lúc tôi càng khó chịu, mồ hôi lạnh túa ra khắp người, từng đợt co rút ở bụng khiến tôi kiệt sức đến mức gần như ngất đi.

Gượng dậy bước vào nhà vệ sinh, tôi mới phát hiện mình đã đến kỳ kinh nguyệt.



""", args.bg_choice, args.narr_boost, voice_name="vi-VN-Wavenet-A")
