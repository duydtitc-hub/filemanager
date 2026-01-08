import os
import subprocess
import traceback

from convert_stt import create_srt_from_gemini


def main():
    video = "Than_cau_ca_giang_lam_Tap_2.mp4"
    if not os.path.exists(video):
        print(f"Error: video file not found: {video}")
        return 2

    tmpwav = os.path.splitext(video)[0] + ".gemini.wav"
    out_srt = os.path.splitext(video)[0] + ".gemini.srt"

    try:
        print("Extracting audio to", tmpwav)
        subprocess.run(["ffmpeg", "-y", "-i", video, "-ar", "16000", "-ac", "1", "-vn", tmpwav], check=True)
    except Exception as e:
        print("ffmpeg audio extraction failed:", e)
        traceback.print_exc()
        return 3

    try:
        print("Calling create_srt_from_gemini... (this will use GENAI_API_KEY_Translate env var)")
        srt_path = create_srt_from_gemini(tmpwav, output_srt=out_srt, api_key=os.environ.get("GENAI_API_KEY_Translate"))
        print("SRT created:", srt_path)
    except Exception as e:
        print("create_srt_from_gemini failed:", e)
        traceback.print_exc()
        return 4
    finally:
        try:
            if os.path.exists(tmpwav):
                os.remove(tmpwav)
        except Exception:
            pass

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
