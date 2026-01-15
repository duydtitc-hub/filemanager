from subprocess_helper import run_logged_subprocess

import os
import math
import subprocess
import random
import shutil
from datetime import datetime, timedelta
from base64 import b64encode

from DiscordMethod import send_discord_message


def get_media_info(path):
    """Extract width, height, duration from media file using ffprobe."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    probe = run_logged_subprocess([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-show_entries", "stream=codec_type,width,height",
        "-of", "json", path
    ], capture_output=True, text=True)
    if probe.returncode != 0 or not probe.stdout.strip():
        raise RuntimeError(f"ffprobe failed for file: {path}")
    import json
    data = json.loads(probe.stdout)
    duration = float(data.get("format", {}).get("duration", 0) or 0)
    width = height = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width", 0) or 0)
            height = int(stream.get("height", 0) or 0)
            break
    return width, height, duration


def _create_clip_from_source(src_path: str, out_path: str, desired_duration: float):
    """Create a clip of length desired_duration from src_path by picking a random start.

    If src shorter than desired_duration, loop it and trim.
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
        run_logged_subprocess(cmd, check=True)
        return

    loops = int(math.ceil(desired / dur))
    cmd = ['ffmpeg', '-y', '-stream_loop', str(loops - 1), '-i', src_path, '-t', str(desired), '-c', 'copy', out_path]
    run_logged_subprocess(cmd, check=True)


def concat_crop_audio_with_titles(video_paths, audio_path, output_path="final.mp4",
                                  Title="", font_path=None):
    """Concatenate and crop videos to 9:16, scale to 1080x1920 and add audio.

    This is a simplified, self-contained implementation intended to replace
    the in-app monolithic function during refactor.
    """
    if not video_paths:
        raise ValueError("No video paths provided")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    video_infos = []
    total_video_dur = 0
    valid_video_paths = []
    for p in video_paths:
        try:
            w, h, d = get_media_info(p)
            if d is None:
                continue
            video_infos.append((w, h, d))
            valid_video_paths.append(p)
            total_video_dur += d
        except Exception as e:
            send_discord_message(f"⚠️ Skipping video {p}: {e}")
            continue

    if not valid_video_paths:
        raise RuntimeError("No valid videos after probing")

    _, _, audio_dur = get_media_info(audio_path)
    send_discord_message(f"🎞️ Total video={total_video_dur:.2f}s, Audio={audio_dur:.2f}s")

    loops = math.ceil(audio_dur / total_video_dur) if total_video_dur < audio_dur else 1
    extended_video_paths = valid_video_paths * loops

    filters = []
    for i, p in enumerate(extended_video_paths):
        w, h, d = get_media_info(p)
        aspect = w / h if h and h != 0 else 9/16
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

    concat_inputs = "".join([f"[v{i}]" for i in range(len(extended_video_paths))])
    filters.append(f"{concat_inputs}concat=n={len(extended_video_paths)}:v=1:a=0[vc]")

    filter_complex = ";".join(filters)

    cmd = [
        'ffmpeg', '-y',
        *[arg for pair in [('-i', p) for p in extended_video_paths] for arg in pair],
        '-i', audio_path,
        '-filter_complex', filter_complex,
        '-map', '[vc]', '-map', str(len(extended_video_paths)),
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '28',
        '-c:a', 'aac', '-b:a', '128k',
        output_path
    ]
    send_discord_message(f"🔧 Rendering final video to: {output_path}")
    run_logged_subprocess(cmd, check=True)
    return output_path
