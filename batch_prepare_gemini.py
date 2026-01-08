"""Batch-run prepare_audio_for_video_gemini across female voices.

This script uses the `voices` JSON provided by the user (embedded below), selects
voices with `ssmlGender == 'FEMALE'`, and for each voice calls
`test_gemini_audio.test_prepare(...)` to create a processed audio file.

It writes a `batch_prepare_results.json` file with the mapping voice->output_path or error.

Usage (PowerShell):
python .\batch_prepare_gemini.py

Notes:
- This will call GoogleTTS and ffmpeg and may require API keys and ffmpeg available on PATH.
- Long-running: each voice may take several seconds to tens of seconds depending on network and ffmpeg.
"""
import json
import time
import traceback
import shutil
import re
from pathlib import Path

from test_gemini_audio import test_prepare

# voices JSON (embedded)
VOICES_JSON = {
  "voices": [
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Achernar", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Achird", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Algenib", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Algieba", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Alnilam", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Aoede", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Autonoe", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Callirrhoe", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Charon", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Despina", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Enceladus", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Erinome", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Fenrir", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Gacrux", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Iapetus", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Kore", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Laomedeia", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Leda", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Orus", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Puck", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Pulcherrima", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Rasalgethi", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Sadachbia", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Sadaltager", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Schedar", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Sulafat", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Umbriel", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Vindemiatrix", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Zephyr", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Chirp3-HD-Zubenelgenubi", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Neural2-A", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Neural2-D", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Standard-A", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Standard-B", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    {"languageCodes": ["vi-VN"], "name": "vi-VN-Standard-C", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Standard-D", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000}
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Wavenet-A", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Wavenet-B", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000},
    {"languageCodes": ["vi-VN"], "name": "vi-VN-Wavenet-C", "ssmlGender": "FEMALE", "naturalSampleRateHertz": 24000},
    # {"languageCodes": ["vi-VN"], "name": "vi-VN-Wavenet-D", "ssmlGender": "MALE", "naturalSampleRateHertz": 24000}
  ]
}

# Text to synthesize (reusing the sample from test_gemini_audio.py)
SAMPLE_TEXT = (
"""
Tiếng người con gái thổn thức đứt quãng qua điện thoại, lọt vào tai Trường lại giống như một luồng điện giật tung não anh, vừa chuyển ánh nhìn từ dưới vô lăng lên cửa kính, trong khoảng ánh sáng đèn pha, đột ngột xuất hiện một vật. Anh còn chưa kịp định thần, xe đã lao tới, thứ kia lập tức bị đâm trúng, cái chóp đầu lòa xòa đập thẳng vào cửa kính xe. Trường vội vứt điện thoại sang một bên, hai tay ghì chặt vô lăng, chân nhả ga, chân đạp phanh hết cỡ, nhưng vẫn không ngăn được cú va chạm đó. Thứ trước mặt giống như vỡ tan thành một đống dính trên cửa kính.
"""
)

OUT_JSON = Path("batch_prepare_results.json")
results = {}

female_voices = [v["name"] for v in VOICES_JSON["voices"] if v.get("ssmlGender", "").upper() == "FEMALE"]
print(f"Found {len(female_voices)} female voices.\n")

for idx, voice in enumerate(female_voices, start=1):
    print(f"[{idx}/{len(female_voices)}] Synthesizing with voice: {voice}")
    try:
        out = test_prepare(SAMPLE_TEXT, bg_choice=None, narration_boost_db=6.0, voice_name=voice)
        # If process succeeded and file exists, rename it to include the voice name for easy ID
        if out and Path(out).exists():
            p = Path(out)
            # sanitize voice name to be filesystem-safe
            safe_voice = re.sub(r"[^A-Za-z0-9._-]", "_", voice)
            new_name = f"{p.stem}__{safe_voice}{p.suffix}"
            new_path = p.with_name(new_name)
            try:
                shutil.move(str(p), str(new_path))
                out = str(new_path)
                print(f"[info] Renamed output to include voice: {out}")
            except Exception as move_e:
                print(f"[warning] Failed to rename {p} -> {new_path}: {move_e}")
        results[voice] = {"status": "ok", "output": out}
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERROR] Voice {voice} failed: {e}\n{tb}")
        results[voice] = {"status": "error", "error": str(e)}
    # small pause to avoid rapid-fire requests
    time.sleep(1)

# Save results
with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"Batch complete. Results written to {OUT_JSON}")
