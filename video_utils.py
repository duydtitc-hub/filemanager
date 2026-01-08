import subprocess
import tempfile
import os
import shlex
from typing import List, Tuple


def _run(cmd: List[str]):
    res = subprocess.run(cmd, capture_output=True)
    return res.returncode, res.stdout.decode(errors='ignore'), res.stderr.decode(errors='ignore')


def concat_videos(input_paths: List[str], output_path: str, target_resolution: Tuple[int, int] = (1080, 1920)) -> str:
    """
    Concatenate multiple videos into one file.

    Strategy:
      1) Try ffmpeg's concat demuxer (lossless, uses `-c copy`). This preserves original content
         and is fastest, but requires the same codec/format for all inputs.
      2) If concat demuxer fails, fall back to re-encoding with a single ffmpeg command that
         scales/crops/pads each input to `target_resolution` (useful for TikTok vertical 9:16)
         and concatenates using the filter_complex concat filter (keeps content visually unchanged
         except for scaling to a common size).

    Args:
        input_paths: list of input video file paths (in order).
        output_path: resulting output file path.
        target_resolution: (width, height) to re-encode to if needed. Default 1080x1920 (TikTok vertical).

    Returns:
        output_path on success.

    Raises:
        RuntimeError on failure with ffmpeg stderr attached.
    """
    # 1) Try concat demuxer (lossless) using a temp file list
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        listfile = f.name
        for p in input_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")

    try:
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
            "-c", "copy", output_path
        ]
        code, out, err = _run(cmd)
        if code == 0:
            os.unlink(listfile)
            return output_path
        # if failed, fallthrough to re-encode
    except Exception:
        pass

    # 2) Re-encode fallback using filter_complex concat
    # Build inputs and filter chains that scale each input to target_resolution
    width, height = target_resolution
    inputs = []
    filters = []
    maps = []
    for idx, p in enumerate(input_paths):
        inputs += ["-i", p]
        # name each video stream v{idx} and audio a{idx}
        # Scale video while preserving aspect using pad to avoid stretching
        filters.append(f"[{idx}:v]scale=w={width}:h={height}:force_original_aspect_ratio=decrease, pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{idx}]")
        filters.append(f"[{idx}:a]aresample=48000[a{idx}]")

    # concat n=<len> v=1 a=1 requires listing v0 v1 ... and a0 a1 ...
    v_inputs = ''.join(f"[v{idx}]" for idx in range(len(input_paths)))
    a_inputs = ''.join(f"[a{idx}]" for idx in range(len(input_paths)))
    filters.append(f"{v_inputs}{a_inputs}concat=n={len(input_paths)}:v=1:a=1[outv][outa]")

    filter_complex = ';'.join(filters)

    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "160k",
        output_path
    ]

    code, out, err = _run(cmd)
    try:
        os.unlink(listfile)
    except Exception:
        pass
    if code != 0:
        raise RuntimeError(f"ffmpeg concat failed: {err}\nstdout:{out}")

    return output_path


if __name__ == '__main__':
    # quick CLI helper
    import sys
    if len(sys.argv) < 4:
        print("Usage: python video_utils.py out.mp4 in1.mp4 in2.mp4 [in3.mp4 ...]")
        raise SystemExit(2)
    out = sys.argv[1]
    ins = sys.argv[2:]
    print("Concatenating:", ins, "->", out)
    print(concat_videos(ins, out))
