import os
import re
import subprocess
import math
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

                # send_discord_message not available here; just skip
import os
import re
import subprocess
import math

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")


def _write_concat_list(parts: list, list_path: str):
    os.makedirs(os.path.dirname(list_path), exist_ok=True)
    with open(list_path, 'w', encoding='utf-8') as f:
        for p in parts:
            if not p:
                continue
            if not os.path.exists(p):
                # skip missing entries; caller should have filtered but be defensive
                continue
            f.write(f"file '{os.path.abspath(p)}'\n")


def _concat_audio_from_list(concat_list_path: str, output_path: str):
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list_path,
        "-ar", "24000",
        "-ac", "1",
        "-b:a", "192k",
        output_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def _write_part_manifest(file_path: str):
    """Write a small manifest marker next to a TTS part file.

    Creates/overwrites `file_path + '.done'` containing simple metadata
    (source filename, size bytes, timestamp). Callers use existence of
    the `.done` file to prefer manifest-backed parts.
    """
    try:
        if not file_path:
            return
        if not os.path.exists(file_path):
            return
        manifest_path = file_path + ".done"
        os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
        with open(manifest_path, 'w', encoding='utf-8') as f:
            f.write(f"source: {os.path.basename(file_path)}\n")
            try:
                f.write(f"size: {os.path.getsize(file_path)}\n")
            except Exception:
                f.write("size: unknown\n")
            f.write(f"timestamp: {int(time.time())}\n")
    except Exception:
        # Best-effort: manifest writing must not break TTS generation
        pass


def _create_flac_copy(input_path: str, out_flac: str):
    cmd = ["ffmpeg", "-y", "-i", input_path, "-c:a", "flac", out_flac]
    subprocess.run(cmd, check=True, capture_output=True)


def get_tts_part_files(title_slug: str, output_dir: str | None = None) -> list:
    """Detect existing per-TTS-generated part files for a given title_slug.

    Prefer parts that have a corresponding manifest marker `<part>.done`. If no
    manifest-backed parts exist, fall back to filename heuristics.
    Returns a sorted list of file paths (by numeric index) or empty list if none found.
    """
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR

    found = []
    try:
        for p in os.listdir(output_dir):
            # gemini parts: allow wav or flac
            m = re.match(rf"^{re.escape(title_slug)}_gemini_part_(\d+)(?:_[^_.]+)?\.(wav|flac)$", p, flags=re.I)
            if m:
                found.append(os.path.join(output_dir, p))
                continue

            m = re.match(rf"^{re.escape(title_slug)}_content_part_(\d+)(?:_[^_.]+)?\.(wav|flac)$", p, flags=re.I)
            if m:
                found.append(os.path.join(output_dir, p))
                continue

            m = re.match(rf"^{re.escape(title_slug)}_part_(\d+)(?:_[^_.]+)?\.(wav|flac|wav)$", p, flags=re.I)
            if m:
                found.append(os.path.join(output_dir, p))
                continue
    except Exception:
        return []

    def _key(fn: str):
        b = os.path.basename(fn)
        m = re.search(r"_(\d+)\.(wav|flac)$", b, flags=re.I)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return 0
        return 0

    # Prefer files that have an accompanying .done manifest marker
    manifest_backed = [f for f in found if os.path.exists(f + ".done")]
    if manifest_backed:
        manifest_backed.sort(key=_key)
        return manifest_backed

    found.sort(key=_key)
    return found


def create_final_parts_from_tts(tts_parts: list, title_slug: str, output_dir: str | None = None) -> list:
    """Create standardized final audio parts from per-TTS files.

    Converts each per-TTS file into a final part named `{title_slug}_part{n}.flac`.
    """
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR

    out_parts = []

    def _idx(p: str) -> int:
        m = re.search(r"(\d+)(?=\.(wav|flac)$)", os.path.basename(p), flags=re.I)
        try:
            return int(m.group(1)) if m else 0
        except Exception:
            return 0

    tts_sorted = sorted(tts_parts, key=_idx)

    for i, src in enumerate(tts_sorted):
        out_path = os.path.join(output_dir, f"{title_slug}_part{i+1}.flac")
        try:
            cmd = [
                "ffmpeg", "-y",
                "-i", src,
                "-af", "aresample=24000",
                "-c:a", "flac",
                "-sample_fmt", "s16",
                out_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            out_parts.append(out_path)
        except subprocess.CalledProcessError as e:
            raise

    return out_parts


def split_audio_by_duration(audio_path: str, max_part_duration: int = 3600, output_dir: str | None = None) -> list:
    """Split an audio file into balanced parts and always write fresh final parts.

    Returns list of generated part file paths.
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(audio_path)

    probe = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_path
    ], capture_output=True, text=True)
    total_duration = float(probe.stdout.strip() or 0)

    if output_dir is None:
        output_dir = os.path.dirname(audio_path)

    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    num_parts = math.ceil(total_duration / max_part_duration) if max_part_duration and total_duration > 0 else 1
    actual_part_duration = total_duration / num_parts if num_parts else total_duration

    audio_parts = []
    for i in range(num_parts):
        start_time = i * actual_part_duration
        duration = (total_duration - start_time) if (i == num_parts - 1) else actual_part_duration
        part_file = os.path.join(output_dir, f"{base_name}_part{i+1}.flac")
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_time),
            "-t", str(duration),
            "-i", audio_path,
            "-af", "aresample=24000",
            "-c:a", "flac",
            "-sample_fmt", "s16",
            part_file
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        audio_parts.append(part_file)

    return audio_parts
