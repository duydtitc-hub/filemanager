from subprocess_helper import run_logged_subprocess

import os
import json
import subprocess
import tempfile
import uuid
import math
import time
from typing import List, Tuple, Dict, Any, Callable

import pysubs2

from GoogleTTS import text_to_wav
from DiscordMethod import send_discord_message
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SAMPLE_FMT = "s16"

def _compute_dynamic_speaking_rate(
    text: str,
    slot_duration: float,
    base_rate: float = 1.0,
    per_word_sec: float = 0.33,
    punctuation_pause_sec: float = 0.2,
    min_rate: float = 1.28,
    max_rate: float = 1.30,
) -> float:
    """Estimate a speaking rate multiplier that fits text into the slot.

    Heuristic:
    - Estimate natural duration at base_rate by words * per_word_sec + punctuation pauses.
    - Compute desired_rate = estimated_duration / slot_duration.
    - Clamp to [min_rate, max_rate].

    Note: This is an approximation; final alignment is enforced by time-stretching/padding.
    """
    try:
        if slot_duration <= 0:
            return base_rate
        # Rough word count for Vietnamese: split on spaces
        words = [w for w in text.strip().split() if w]
        num_words = len(words)
        punct_count = sum(text.count(p) for p in [",", ".", "!", "?", ";", ":"])
        estimated = (num_words * per_word_sec) + (punct_count * punctuation_pause_sec)
        # Avoid zero estimates
        if estimated <= 0:
            estimated = max(0.8, min(1.5, slot_duration * 0.5))
        desired = estimated / max(slot_duration, 1e-6)
        # Scale around base_rate
        rate = base_rate * desired
        return max(min_rate, min(max_rate, rate))
    except Exception:
        return base_rate

def apply_voice_fx(in_path: str, out_path: str, atempo: float = 1.6) -> str:
    """Apply narration voice FX chain to enhance clarity.

    Args:
        atempo: Speed-up factor inserted into the FFmpeg chain; default mirrors the previous hard-coded 1.6 value.
    """
    fx = (
        f"asetrate=44100*1.1,aresample=44100,atempo={atempo},"
        "highpass=f=80,lowpass=f=8000,bass=g=6:f=120,treble=g=-6:f=6000"
    )
    cmd = [
        "ffmpeg", "-y", "-i", in_path,
        "-af", fx,
        "-c:a", "flac",
        "-sample_fmt", DEFAULT_SAMPLE_FMT,
        out_path
    ]
    print( "Applying voice FX:", " ".join(cmd))
    run_logged_subprocess(cmd, check=True, capture_output=True)
    return out_path


def gemini_voice_fx(in_path: str, out_path: str, atempo: float = 1.18) -> str:
    """Apply Gemini-style narration voice FX chain.
    Chain: asetrate=44100*0.6, aresample=44100, atempo=1.4, highpass=80Hz, lowpass=8kHz, 
           bass +6dB @120Hz, treble -6dB @6kHz, dynaudnorm, volume=6dB

    Args:
        atempo: Speed-up factor inside the Gemini FX chain.
    """
    fx = (
        "aresample=48000,"
        f"rubberband=pitch=1.09051,"
        f"atempo={atempo},"
        "highpass=f=90,"
        "lowpass=f=9000,"
        "bass=g=3:f=120,"
        "acompressor=threshold=-18dB:ratio=3:attack=5:release=100,"
        "alimiter=limit=0.95"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", in_path,
        "-af", fx,
        "-ar", "48000",
        "-ac", "2",
        "-sample_fmt", "s16",
        "-c:a", "flac",
        out_path
    ]
    print("Applying Gemini voice FX:", " ".join(cmd))
    run_logged_subprocess(cmd, check=True, capture_output=True)
    return out_path




def normalize_audio_to_flac(in_path: str, out_path: str, sr: int = 48000, ac: int = 2) -> str:
    """Transcode any audio file to 48kHz stereo FLAC to ensure consistent format and durations.

    This prevents issues where container/codec mismatches lead ffmpeg/ffprobe to misreport durations.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", in_path,
        "-ar", str(sr), "-ac", str(ac),
        "-sample_fmt", DEFAULT_SAMPLE_FMT,
        "-c:a", "flac",
        out_path
    ]
    run_logged_subprocess(cmd, check=True, capture_output=True)
    return out_path
def ffprobe_duration(path: str) -> float:
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", path
        ]
        out = subprocess.check_output(cmd, text=True).strip()
        return float(out)
    except Exception:
        return 0.0


def make_silence(duration: float, out_path: str, sr: int = 48000) -> str:
    # Generate stereo silence of given duration
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"anullsrc=r={sr}:cl=stereo",
        "-t", str(max(0.0, duration)),
        "-ar", str(sr), "-ac", "2",
        "-sample_fmt", DEFAULT_SAMPLE_FMT,
        "-c:a", "flac",
        out_path
    ]
    run_logged_subprocess(cmd, check=True, capture_output=True)
    return out_path


def trim_silence(in_path: str, out_path: str, threshold_db: int = -40) -> str:
    # Remove leading/trailing silence to improve alignment
    # Adjust thresholds if needed
    filt = (
        f"silenceremove=start_periods=1:start_threshold={threshold_db}dB:start_silence=0.05:" \
        f"stop_periods=1:stop_threshold={threshold_db}dB:stop_silence=0.1"
    )
    cmd = [
        "ffmpeg", "-y", "-i", in_path,
        "-af", filt,
        "-ar", "48000", "-ac", "2",
        "-sample_fmt", DEFAULT_SAMPLE_FMT,
        "-c:a", "flac",
        out_path
    ]
    run_logged_subprocess(cmd, check=True, capture_output=True)
    return out_path


def fit_audio_to_slot(in_path: str, slot_duration: float, out_path: str) -> str:
    # Best-effort: try to time-stretch with atempo if within [0.5, 2.0].
    wav_dur = ffprobe_duration(in_path)
    if slot_duration <= 0:
        # Just trim to tiny duration if invalid
        cmd = ["ffmpeg", "-y", "-i", in_path, "-t", "0.001", "-c:a", "flac", out_path]
        run_logged_subprocess(cmd, check=True, capture_output=True)
        return out_path

    filters = []
    tempo = 1.0
    if wav_dur > 0:
        # Need output duration = slot_duration
        factor = wav_dur / slot_duration
        tempo = 1.0 / factor if factor != 0 else 1.0
        # Limit time-stretch to a safer range to avoid artifacts
        if 0.8 <= tempo <= 1.25:
            filters.append(f"atempo={tempo}")
    # Pad or trim to exact slot duration
    filters.append("apad=1")
    filters.append(f"atrim=0:{slot_duration}")

    cmd = [
        "ffmpeg", "-y", "-i", in_path,
        "-af", ",".join(filters),
        "-ar", "48000", "-ac", "2",
        "-sample_fmt", DEFAULT_SAMPLE_FMT,
        "-c:a", "flac",
        out_path
    ]
    run_logged_subprocess(cmd, check=True, capture_output=True)
    return out_path


def accelerate_audio(in_path: str, out_path: str, ratio: float, sr: int = 48000, ac: int = 2) -> str:
    """Adjust the audio tempo (ratio>1 speeds up, ratio<1 slows down)."""
    tempo = max(ratio, 0.01)
    stages: List[float] = []
    remaining = tempo
    # ffmpeg atempo accepts [0.5, 2.0], so split extreme ratios into valid stages
    while remaining > 2.0:
        stages.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        stages.append(0.5)
        remaining /= 0.5
    stages.append(remaining)

    filter_chain = ",".join(f"atempo={s:.6f}" for s in stages)
    cmd = [
        "ffmpeg", "-y", "-i", in_path,
        "-af", filter_chain,
        "-ar", str(sr), "-ac", str(ac),
        "-sample_fmt", DEFAULT_SAMPLE_FMT,
        "-c:a", "flac",
        out_path
    ]
    run_logged_subprocess(cmd, check=True, capture_output=True)
    return out_path


def concat_audio(parts: List[str], out_path: str) -> str:
    # Use concat demuxer for reliable concatenation
    # Ensure each part is 48kHz stereo FLAC; if not, transcode to a temp file
    if not parts:
        send_discord_message("⚠️ concat_audio: No parts to concatenate")
        make_silence(0.5, out_path)
        return out_path
    
    # Create temp directory in same location as output file
    work_dir = os.path.dirname(out_path) or "."
    temp_dir = os.path.join(work_dir, "concat_temp")
    os.makedirs(temp_dir, exist_ok=True)
    
    send_discord_message(f"🔗 concat_audio: Processing {len(parts)} parts...")
    norm_parts = []
    for idx, p in enumerate(parts):
        # Verify source exists
        if not os.path.exists(p):
            send_discord_message(f"⚠️ Part {idx+1} not found: {p}")
            continue
        
        size_kb = os.path.getsize(p) / 1024
        # send_discord_message(f"  Part {idx+1}: {size_kb:.1f}KB")
        
        # Create normalized file in work directory
        try:
            norm_file = os.path.join(temp_dir, f"norm_{idx}.flac")
            cmd = [
                "ffmpeg", "-y", "-i", p,
                "-ar", "48000", "-ac", "2", "-sample_fmt", DEFAULT_SAMPLE_FMT, "-c:a", "flac",
                norm_file
            ]
            run_logged_subprocess(cmd, check=True, capture_output=True)
            
            # Verify normalized file
            norm_size = os.path.getsize(norm_file) / 1024
            norm_dur = ffprobe_duration(norm_file)
            # send_discord_message(f"    Normalized: {norm_size:.1f}KB, {norm_dur:.2f}s")
            norm_parts.append(norm_file)
        except Exception as e:
            send_discord_message(f"⚠️ Failed to normalize part {idx+1}: {e}, using original")
            # fallback to original if conversion fails
            norm_parts.append(p)

    if not norm_parts:
        send_discord_message("⚠️ No parts to concatenate after normalization")
        make_silence(0.5, out_path)
        return out_path

    try:
        # Write concat list in work directory
        list_path = os.path.join(temp_dir, "concat_list.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for p in norm_parts:
                # Use absolute path and proper escaping for concat demuxer
                abs_path = os.path.abspath(p)
                f.write(f"file '{abs_path}'\n")
        
        # Log concat list contents for debugging
        with open(list_path, "r", encoding="utf-8") as f:
            list_contents = f.read()
            send_discord_message(f"📝 Concat list ({len(norm_parts)} files):\n{list_contents[:500]}")
        
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", list_path,
                "-ar", "48000", "-ac", "2", "-sample_fmt", DEFAULT_SAMPLE_FMT, "-c:a", "flac",
                out_path
            ]
        send_discord_message(f"🔨 Running ffmpeg concat...")
        
        # Capture stderr to see warnings
        result = run_logged_subprocess(cmd, check=True, capture_output=True, log_command=True, text=True)
       
        
        final_size = os.path.getsize(out_path) / 1024
        final_dur = ffprobe_duration(out_path)
        send_discord_message(f"✅ concat_audio complete: {final_dur:.2f}s, {final_size:.1f}KB")
    except Exception as e:
        send_discord_message(f"❌ concat_audio failed: {e}")
    # finally:
        # Cleanup temp directory
        try:
            import shutil
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
        except Exception as e:
            send_discord_message(f"⚠️ Failed to cleanup temp dir: {e}")
    return out_path


def build_narration_from_srt(srt_path: str, out_audio: str, voice_name: str = "vi-VN-Standard-C", speaking_rate: float = 1.0, lead: float = 0.3, start_only: bool = False, trim: bool = False, trim_threshold_db: int = -40, rate_mode: int = 0, apply_fx: bool = False, tmp_subdir: str | None = None, voice_fx_func: Callable[[str, str], str] | None = None) -> str:
    subs = pysubs2.load(srt_path, encoding="utf-8")
    # Ensure chronological order to avoid early playback when SRT lines are out-of-order
    subs.events.sort(key=lambda ev: ev.start)
    # Use provided voice FX function or default to apply_voice_fx
    fx_func = voice_fx_func if voice_fx_func is not None else apply_voice_fx
    # Normalize to FLAC 48k stereo pieces
    # Place temp files under BASE_DIR/temp_narr/<tmp_subdir> if provided
    tmpdir = os.path.join(BASE_DIR, "temp_narr", tmp_subdir) if tmp_subdir else os.path.join(BASE_DIR, "temp_narr")
    os.makedirs(tmpdir, exist_ok=True)
    parts: List[str] = []
    current_t = 0.0
    # readable prefix derived from srt filename
    srt_base = os.path.splitext(os.path.basename(srt_path))[0]
    line_idx = 0
    for ev in subs:
        line_idx += 1
        start = ev.start / 1000.0
        end = ev.end / 1000.0
        if end <= start:
            continue
        # Insert silence gap if needed
        adj_start = max(0.0, start - max(0.0, lead))
        if adj_start > current_t:
            gap = adj_start - current_t
            silence_path = os.path.join(tmpdir, f"{srt_base}_sil_{line_idx}.flac")
            make_silence(gap, silence_path)
            parts.append(silence_path)

        # Synthesize this subtitle text
        text = pysubs2.SSAEvent(text=ev.text).text
        # Remove ASS linebreaks if any
        text = text.replace("\\N", " ").strip()
        raw_wav = os.path.join(tmpdir, f"{srt_base}_tts_{line_idx}.wav")
        # Compute speaking rate (dynamic when rate_mode=1, else fixed base_rate)
        slot = end - start
        rate_use = _compute_dynamic_speaking_rate(text, slot, base_rate=speaking_rate) if rate_mode == 1 else speaking_rate
        res = text_to_wav(text, raw_wav, voice_name=voice_name, speaking_rate=rate_use, sendNotify=False)
        if not res or not os.path.exists(raw_wav):
            # If failed, just produce silence of slot duration
            slot = end - start
            missing_sil = os.path.join(tmpdir, f"{srt_base}_miss_{line_idx}.flac")
            make_silence(slot, missing_sil)
            parts.append(missing_sil)
            current_t = end
            continue

        # Normalize TTS output to 48kHz stereo FLAC to avoid container/codec duration bugs
        try:
            norm_wav = os.path.join(tmpdir, f"norm_{srt_base}_{line_idx}.flac")
            normalize_audio_to_flac(raw_wav, norm_wav)
            src_wav = norm_wav
        except Exception:
            src_wav = raw_wav

        # Optionally trim silence
        if trim:
            trimmed = os.path.join(tmpdir, f"{srt_base}_trim_{line_idx}.wav")
            trim_silence(raw_wav, trimmed, threshold_db=trim_threshold_db)
            src_wav = trimmed
        if start_only:
            # Do not force duration to subtitle; just speak naturally at start time
            # Inserted gap already placed us at adj_start; append trimmed audio
            natural_src = src_wav
            if apply_fx:
                natural_fx = os.path.join(tmpdir, f"{srt_base}_natfx_{line_idx}.flac")
                natural_src = fx_func(src_wav, natural_fx)
            natural = os.path.join(tmpdir, f"{srt_base}_nat_{line_idx}.flac")
            # Convert to FLAC (no time-stretch)
            run_logged_subprocess(["ffmpeg", "-y", "-i", natural_src, "-sample_fmt", DEFAULT_SAMPLE_FMT, "-c:a", "flac", natural], check=True, capture_output=True)
            parts.append(natural)
            current_t = adj_start + ffprobe_duration(natural)
        else:
            # Fit to subtitle slot duration (time-stretch + pad/trim)
            fit_src = src_wav
            if apply_fx:
                fit_fx = os.path.join(tmpdir, f"{srt_base}_fitfx_{line_idx}.flac")
                fit_src = fx_func(src_wav, fit_fx)
            fitted = os.path.join(tmpdir, f"{srt_base}_fit_{line_idx}.flac")
            fit_audio_to_slot(fit_src, slot, fitted)
            parts.append(fitted)
            current_t = end

    # Concatenate all parts to a single FLAC
    final_audio = out_audio
    os.makedirs(os.path.dirname(final_audio) or ".", exist_ok=True)
    concat_audio(parts, final_audio)
    return final_audio


# def build_narration_schedule(
#     srt_path: str,
#     out_audio: str,
#     voice_name: str = "vi-VN-Standard-C",
#     speaking_rate: float = 1.0,
#     lead: float = 0.2,
#     meta_out: str | None = None,
#     trim: bool = False,
#     trim_threshold_db: int = -40,
#     rate_mode: int = 0,
#     apply_fx: bool = False,
#     tmp_subdir: str | None = None,
#     no_overlap: bool = True,
#     max_speed_rate: float = 1.25,
#     max_lead_overlap: float = 0.2,
#     voice_fx_func: Callable[[str, str], str] | None = None,
#     chunk_duration: float | None = None,
#     narration_atempo: float = 1.18,
#     slot_duration_scale: float = 1.0,
#     regeneration_attempt: int = 0,
# ) -> Tuple[str, str]:
#     """Generate per-line audio, then mix by scheduling each clip at its start time using adelay.
    
#     Args:
#         chunk_duration: Maximum duration for narration. If provided and narration exceeds this,
#                         all pieces will be regenerated with adjusted atempo to fit.
    
#     Returns (final_audio_path, metadata_json_path)."""
#     # Ensure module references are clear
#     import os as _os
#     import time as _time
    
#     subs = pysubs2.load(srt_path, encoding="utf-8")
#     subs.events.sort(key=lambda ev: ev.start)
#     # Use provided voice FX function or default to apply_voice_fx
#     fx_func = voice_fx_func if voice_fx_func is not None else apply_voice_fx
#     # Place temp files under BASE_DIR/temp_narr_sched/<tmp_subdir> if provided
#     tmpdir = _os.path.join(BASE_DIR, "temp_narr_sched", tmp_subdir) if tmp_subdir else _os.path.join(BASE_DIR, "temp_narr_sched")
#     _os.makedirs(tmpdir, exist_ok=True)
#     # Create subfolders to reduce per-directory file counts (tts, norm, fx, piece, trim)
#     tts_dir = _os.path.join(tmpdir, "tts")
#     norm_dir = _os.path.join(tmpdir, "norm")
#     fx_dir = _os.path.join(tmpdir, "fx")
#     piece_dir = _os.path.join(tmpdir, "piece")
#     trim_dir = _os.path.join(tmpdir, "trim")
#     for d in (tts_dir, norm_dir, fx_dir, piece_dir, trim_dir):
#         _os.makedirs(d, exist_ok=True)

#     items: List[Dict[str, Any]] = []
#     # Cursor to enforce non-overlapping playback when requested
#     cursor_t = 0.0
#     # readable prefix from srt filename
#     srt_base = os.path.splitext(os.path.basename(srt_path))[0]
#     piece_idx = 0
#     for ev in subs:
#         start = ev.start / 1000.0
#         end = ev.end / 1000.0
#         if end <= start:
#             continue
#         adj_start = max(0.0, start - max(0.0, lead))

#         text = pysubs2.SSAEvent(text=ev.text).text
#         text = text.replace("\\N", " ").strip()
#         piece_idx += 1
#         raw_wav = _os.path.join(tts_dir, f"{srt_base}_tts_{piece_idx}.wav")
#         raw_wav_vi = _os.path.join(tts_dir, f"{srt_base}.vi_tts_{piece_idx}.wav")
#         # Speaking rate: dynamic when rate_mode=1, else fixed base_rate
#         slot = end - start
#         norm_wav = _os.path.join(norm_dir, f"norm_{srt_base}_{piece_idx}.flac")
        
#         # Check if cached TTS exists (either format)
#         if _os.path.exists(raw_wav_vi):
#             # Prefer .vi_tts format if exists
#             src_wav = raw_wav_vi
#         elif _os.path.exists(raw_wav):
#             # Use regular _tts format
#             src_wav = raw_wav
#         else:
#             # Generate new TTS
#             rate_use = _compute_dynamic_speaking_rate(text, slot, base_rate=speaking_rate) if rate_mode == 1 else speaking_rate
#             res = text_to_wav(text, raw_wav, voice_name=voice_name, speaking_rate=rate_use, sendNotify=False)
#             if not res or not _os.path.exists(raw_wav):
#                 # Skip TTS failure by inserting no audio for this item
#                 continue
#             src_wav = raw_wav

#         # Normalize TTS output to 48kHz stereo FLAC to avoid container/codec duration bugs
#         try:
#             normalize_audio_to_flac(src_wav, norm_wav)
#             src_wav = norm_wav
#         except Exception:
#             pass  # Keep using src_wav if normalization fails
        
#         if trim:
#             trimmed = _os.path.join(trim_dir, f"{srt_base}_trim_{piece_idx}.wav")
#             trim_silence(src_wav, trimmed, threshold_db=trim_threshold_db)
#             src_wav = trimmed
#         # Produce a piece fitted to the slot to reduce overlaps when scheduling
#         # Apply FX if requested, then fit piece to slot to reduce overlaps
#         slot_src = src_wav
#         if apply_fx:
#             slot_fx = _os.path.join(fx_dir, f"{srt_base}_fx_{piece_idx}.flac")
#             # Use default atempo from fx_func (1.6 or 1.18) - speed adjustment only for long pieces
#             slot_src = fx_func(src_wav, slot_fx,atempo=narration_atempo)
#         piece = _os.path.join(piece_dir, f"{srt_base}_piece_{piece_idx}.flac")
#         # For scheduled narration we prefer to keep the natural TTS duration
#         # to avoid cutting a sentence when the subtitle slot ends. Convert
#         # the source to FLAC preserving its full length. If conversion fails,
#         # fall back to fitting to the slot to ensure a piece exists.
#         piece_created = False
#         try:
#             result = run_logged_subprocess([
#                 "ffmpeg", "-y", "-i", slot_src,
#                 "-ar", "48000", "-ac", "2", "-sample_fmt", DEFAULT_SAMPLE_FMT, "-c:a", "flac", piece
#             ], check=True, capture_output=True)
#             # Ensure file is fully written (important for Linux)
#             if _os.path.exists(piece) and _os.path.getsize(piece) > 0:
#                 piece_created = True
#         except Exception:
#             pass
        
#         if not piece_created:
#             # Fallback: fit to slot to ensure a piece exists
#             fit_audio_to_slot(slot_src, slot, piece)
        
#         # Wait briefly for file system sync on Linux
#         if not _os.name == 'nt':  # Not Windows
#             _time.sleep(0.01)  # 10ms delay for file sync
        
#         dur = ffprobe_duration(piece)
#         if dur <= 0:
#             # Fallback: use source duration if probe fails
#             dur = ffprobe_duration(slot_src) if _os.path.exists(slot_src) else slot

#         # Apply slot_duration_scale to reduce allowed duration during regeneration
#         soft_allow = (slot + 0.2) * slot_duration_scale
#         allowed_duration = soft_allow
#         speed_capped = False
#         if dur > allowed_duration:
#             # Keep narration within the slot by gradually speeding it up in small steps.
#             orig_piece = piece
#             orig_dur = dur
#             target_ratio = min(
#                 max(orig_dur / max(allowed_duration, 1e-6), 1.0),
#                 max_speed_rate,
#             )
#             if target_ratio >= max_speed_rate:
#                 speed_capped = True
#             current_ratio = 1.0
#             attempt = 0
#             while dur > allowed_duration and current_ratio < target_ratio:
#                 attempt += 1
#                 remaining = target_ratio - current_ratio
#                 # Use a finer increment near the end for smoother durations
#                 delta = 0.05
#                 next_ratio = min(current_ratio + delta, target_ratio)
#                 if next_ratio <= current_ratio:
#                     break
#                 fast_piece = _os.path.join(piece_dir, f"{srt_base}_piece_{piece_idx}_fast_{attempt}.flac")
#                 try:
#                     accelerate_audio(orig_piece, fast_piece, next_ratio)
#                     if not _os.path.exists(fast_piece):
#                         break
#                     piece = fast_piece
#                     new_dur = ffprobe_duration(piece)
#                     if new_dur <= 0 or new_dur >= dur:
#                         break
#                     dur = new_dur
#                     current_ratio = next_ratio
#                 except Exception:
#                     break

#         # Enforce sequential narration if no_overlap=True while keeping pacing natural.
#         eff_start = adj_start
#         if no_overlap:
#             if speed_capped:
#                 eff_start = max(
#                     max(0.0, adj_start - max_lead_overlap),
#                     cursor_t + 0.05,
#                 )
#             else:
#                 eff_start = max(adj_start, cursor_t + 0.05)
        
#         # # From 2nd regeneration attempt onwards: check if piece ends after subtitle and scale it
#         # if regeneration_attempt >= 1:
#         #     piece_end = eff_start + dur
#         #     subtitle_end = end  # from ev.end
#         #     if piece_end > subtitle_end:
#         #         # Narration overflows subtitle: compress piece to fit exactly within subtitle
#         #         available_time = subtitle_end - eff_start
#         #         if available_time > 0.1:  # Minimum 0.1s to avoid zero/negative duration
#         #             scale_ratio = dur / available_time
#         #             # Apply accelerate_audio to compress piece
#         #             attempt_scale = 0
#         #             while dur > available_time and scale_ratio < max_speed_rate * 2:
#         #                 attempt_scale += 1
#         #                 scaled_piece = _os.path.join(piece_dir, f"{srt_base}_piece_{piece_idx}_scale_{attempt_scale}.flac")
#         #                 try:
#         #                     accelerate_audio(piece, scaled_piece, min(scale_ratio, max_speed_rate * 2))
#         #                     if _os.path.exists(scaled_piece):
#         #                         piece = scaled_piece
#         #                         new_dur = ffprobe_duration(piece)
#         #                         if new_dur > 0 and new_dur < dur:
#         #                             dur = new_dur
#         #                             if dur <= available_time:
#         #                                 break
#         #                     # Increase ratio for next attempt if still not fitting
#         #                     scale_ratio *= 1.1
#         #                 except Exception:
#         #                     break
        
#         cursor_t = eff_start + dur
#         items.append({"start": eff_start, "duration": dur, "file": piece,"end": eff_start + dur, "subtitle_end": end})

#     if not items:
#         # create a tiny silent file to avoid downstream failures
#         _os.makedirs(_os.path.dirname(out_audio) or ".", exist_ok=True)
#         make_silence(0.5, out_audio)
#         meta_path = meta_out or _os.path.splitext(out_audio)[0] + ".schedule.json"
#         with open(meta_path, "w", encoding="utf-8") as f:
#             json.dump({"items": []}, f, ensure_ascii=False, indent=2)
#         return out_audio, meta_path

#     # Save metadata JSON
#     meta_path = meta_out or _os.path.splitext(out_audio)[0] + ".schedule.json"
#     _os.makedirs(_os.path.dirname(meta_path) or ".", exist_ok=True)
#     with open(meta_path, "w", encoding="utf-8") as f:
#         json.dump({"items": items}, f, ensure_ascii=False, indent=2)

#     # ✅ PHƯƠNG PHÁP MỚI: GHÉP TUẦN TỰ VỚI SILENCE CHÍNH XÁC
#     # Tạo danh sách pieces + silence theo thứ tự thời gian
#     # Concat tất cả lại để tránh rè nhiễu từ adelay/amix
    
#     send_discord_message(f"🔨 Ghép {len(items)} đoạn narration với silence chính xác...")
    
#     # Tạo thư mục cho silence files
#     silence_dir = _os.path.join(tmpdir, "silence")
#     _os.makedirs(silence_dir, exist_ok=True)
    
#     # Danh sách các file để concat (piece + silence)
#     concat_parts: List[str] = []
#     concat_cursor = 0.0  # Vị trí hiện tại trong timeline
    
#     for idx, item in enumerate(items):
#         start_time = item["start"]
#         piece_file = item["file"]
#         piece_dur = item["duration"]
        
#         # Tính khoảng cách cần chèn silence
#         gap = start_time - concat_cursor
        
#         if gap > 0.001:  # Nếu có khoảng cách > 1ms
#             # Tạo silence file với duration chính xác
#             silence_file = _os.path.join(silence_dir, f"silence_{idx}_{gap:.3f}s.flac")
#             make_silence(gap, silence_file, sr=48000)
#             concat_parts.append(silence_file)
#             # send_discord_message(f"  Silence {idx}: {gap:.3f}s")
        
#         # Thêm piece vào danh sách concat
#         concat_parts.append(piece_file)
#     #    send_discord_message(f"  Piece {idx+1}: {piece_dur:.3f}s @ {start_time:.3f}s")
        
#         # Cập nhật cursor
#         concat_cursor = start_time + piece_dur
    
#     # Ghép tất cả pieces + silence lại bằng concat_audio
#     send_discord_message(f"🔗 Nối {len(concat_parts)} files (pieces + silence)...")
#     concat_audio(concat_parts, out_audio)
    
#     # Verify final output
#     final_dur = ffprobe_duration(out_audio)
#     final_size_kb = _os.path.getsize(out_audio) / 1024
#     send_discord_message(f"✅ Narration hoàn tất: {final_dur:.2f}s, {final_size_kb:.1f}KB")
#     # ⚠️ Check if narration exceeds chunk duration BEFORE building (faster than probing after)
#     if chunk_duration is not None:
#         # Check last narration piece end time instead of waiting for final file
#         last_narration_end = max(it["end"] for it in items)
#         if last_narration_end > chunk_duration:
#             send_discord_message(f"⚠️ Narration end time ({last_narration_end:.2f}s) exceeds video duration ({chunk_duration:.2f}s). Increasing atempo... (attempt {regeneration_attempt + 1})")
            
#             # Increment narration_atempo by 0.05
#             new_atempo = narration_atempo + 0.05
            
#             # Clear cache to force reprocessing (keep TTS .wav files)
#             import shutil
#             try:
#                 for subdir in [norm_dir, fx_dir, piece_dir, trim_dir]:
#                     if _os.path.exists(subdir):
#                         shutil.rmtree(subdir)
#                         _os.makedirs(subdir, exist_ok=True)
#             except Exception:
#                 pass
            
#             send_discord_message(f"🔧 Old atempo: {narration_atempo:.2f} → New atempo: {new_atempo:.2f}")
            
#             # Regenerate with increased atempo
#             return build_narration_schedule(
#                 srt_path=srt_path,
#                 out_audio=out_audio,
#                 voice_name=voice_name,
#                 speaking_rate=speaking_rate,
#                 lead=lead,
#                 meta_out=meta_out,
#                 trim=trim,
#                 trim_threshold_db=trim_threshold_db,
#                 rate_mode=rate_mode,
#                 apply_fx=apply_fx,
#                 tmp_subdir=tmp_subdir,
#                 no_overlap=no_overlap,
#                 max_speed_rate=max_speed_rate,
#                 max_lead_overlap=max_lead_overlap,
#                 voice_fx_func=voice_fx_func,
#                 chunk_duration=chunk_duration,
#                 narration_atempo=new_atempo,
#                 slot_duration_scale=slot_duration_scale,
#                 regeneration_attempt=regeneration_attempt + 1,
#             )
    
#     # Cleanup temporary files: keep only WAV files (remove generated .flac and other aux files)
#     try:
#         for root, _, files in _os.walk(tmpdir):
#             for fname in files:
#                 path = _os.path.join(root, fname)
#                 # Skip WAV files; keep them. Also avoid touching final outputs.
#                 if fname.lower().endswith('.wav'):
#                     continue
#                 try:
#                     _os.remove(path)
#                 except Exception:
#                     pass
#     except Exception:
#         pass

#     return out_audio, meta_path

def build_narration_schedule(
    srt_path: str,
    out_audio: str,
    voice_name: str = "vi-VN-Standard-C",
    speaking_rate: float = 1.0,
    lead: float = 0.2,
    meta_out: str | None = None,
    trim: bool = False,
    trim_threshold_db: int = -40,
    rate_mode: int = 0,
    apply_fx: bool = False,
    tmp_subdir: str | None = None,
    no_overlap: bool = True,
    max_speed_rate: float = 1.25,
    max_lead_overlap: float = 0.2,
    voice_fx_func: Callable[[str, str], str] | None = None,
    chunk_duration: float | None = None,
    narration_atempo: float = 1.18,
    slot_duration_scale: float = 1.0,
    regeneration_attempt: int = 0,
) -> Tuple[str, str]:
    """Generate per-line audio, then mix by scheduling each clip at its start time using adelay.
    
    Args:
        chunk_duration: Maximum duration for narration. If provided and narration exceeds this,
                        all pieces will be regenerated with adjusted atempo to fit.
    
    Returns (final_audio_path, metadata_json_path)."""
    # Ensure module references are clear
    import os as _os
    import time as _time
    
    subs = pysubs2.load(srt_path, encoding="utf-8")
    subs.events.sort(key=lambda ev: ev.start)
    # Use provided voice FX function or default to apply_voice_fx
    fx_func = voice_fx_func if voice_fx_func is not None else apply_voice_fx
    # Place temp files under BASE_DIR/temp_narr_sched/<tmp_subdir> if provided
    tmpdir = _os.path.join(BASE_DIR, "temp_narr_sched", tmp_subdir) if tmp_subdir else _os.path.join(BASE_DIR, "temp_narr_sched")
    _os.makedirs(tmpdir, exist_ok=True)
    # Create subfolders to reduce per-directory file counts (tts, norm, fx, piece, trim)
    tts_dir = _os.path.join(tmpdir, "tts")
    norm_dir = _os.path.join(tmpdir, "norm")
    fx_dir = _os.path.join(tmpdir, "fx")
    piece_dir = _os.path.join(tmpdir, "piece")
    trim_dir = _os.path.join(tmpdir, "trim")
    for d in (tts_dir, norm_dir, fx_dir, piece_dir, trim_dir):
        _os.makedirs(d, exist_ok=True)

    items: List[Dict[str, Any]] = []
    # Cursor to enforce non-overlapping playback when requested
    cursor_t = 0.0
    # readable prefix from srt filename
    srt_base = os.path.splitext(os.path.basename(srt_path))[0]
    piece_idx = 0
    for ev in subs:
        start = ev.start / 1000.0
        end = ev.end / 1000.0
        if end <= start:
            continue
        adj_start = max(0.0, start - max(0.0, lead))

        text = pysubs2.SSAEvent(text=ev.text).text
        text = text.replace("\\N", " ").strip()
        piece_idx += 1
        raw_wav = _os.path.join(tts_dir, f"{srt_base}_tts_{piece_idx}.wav")
        raw_wav_vi = _os.path.join(tts_dir, f"{srt_base}.vi_tts_{piece_idx}.wav")
        # Speaking rate: dynamic when rate_mode=1, else fixed base_rate
        slot = end - start
        norm_wav = _os.path.join(norm_dir, f"norm_{srt_base}_{piece_idx}.flac")
        
        # Check if cached TTS exists (either format)
        if _os.path.exists(raw_wav_vi):
            # Prefer .vi_tts format if exists
            src_wav = raw_wav_vi
        elif _os.path.exists(raw_wav):
            # Use regular _tts format
            src_wav = raw_wav
        else:
            # Generate new TTS
            rate_use = _compute_dynamic_speaking_rate(text, slot, base_rate=speaking_rate) if rate_mode == 1 else speaking_rate
            res = text_to_wav(text, raw_wav, voice_name=voice_name, speaking_rate=rate_use, sendNotify=False)
            if not res or not _os.path.exists(raw_wav):
                # Skip TTS failure by inserting no audio for this item
                continue
            src_wav = raw_wav

        # Normalize TTS output to 48kHz stereo FLAC to avoid container/codec duration bugs
        try:
            normalize_audio_to_flac(src_wav, norm_wav)
            src_wav = norm_wav
        except Exception:
            pass  # Keep using src_wav if normalization fails
        
        if trim:
            trimmed = _os.path.join(trim_dir, f"{srt_base}_trim_{piece_idx}.wav")
            trim_silence(src_wav, trimmed, threshold_db=trim_threshold_db)
            src_wav = trimmed
        # Produce a piece fitted to the slot to reduce overlaps when scheduling
        # Apply FX if requested, then fit piece to slot to reduce overlaps
        slot_src = src_wav
        if apply_fx:
            slot_fx = _os.path.join(fx_dir, f"{srt_base}_fx_{piece_idx}.flac")
            # Use default atempo from fx_func (1.6 or 1.18) - speed adjustment only for long pieces
            slot_src = fx_func(src_wav, slot_fx,atempo=narration_atempo)
        piece = _os.path.join(piece_dir, f"{srt_base}_piece_{piece_idx}.flac")
        # For scheduled narration we prefer to keep the natural TTS duration
        # to avoid cutting a sentence when the subtitle slot ends. Convert
        # the source to FLAC preserving its full length. If conversion fails,
        # fall back to fitting to the slot to ensure a piece exists.
        piece_created = False
        try:
            result = run_logged_subprocess([
                "ffmpeg", "-y", "-i", slot_src,
                "-ar", "48000", "-ac", "2", "-c:a", "flac", piece
            ], check=True, capture_output=True)
            # Ensure file is fully written (important for Linux)
            if _os.path.exists(piece) and _os.path.getsize(piece) > 0:
                piece_created = True
        except Exception:
            pass
        
        if not piece_created:
            # Fallback: fit to slot to ensure a piece exists
            fit_audio_to_slot(slot_src, slot, piece)
        
        # Wait briefly for file system sync on Linux
        if not _os.name == 'nt':  # Not Windows
            _time.sleep(0.01)  # 10ms delay for file sync
        
        dur = ffprobe_duration(piece)
        if dur <= 0:
            # Fallback: use source duration if probe fails
            dur = ffprobe_duration(slot_src) if _os.path.exists(slot_src) else slot

        # Apply slot_duration_scale to reduce allowed duration during regeneration
        soft_allow = (slot + 0.2) * slot_duration_scale
        allowed_duration = soft_allow
        speed_capped = False
        if dur > allowed_duration:
            # Keep narration within the slot by gradually speeding it up in small steps.
            orig_piece = piece
            orig_dur = dur
            target_ratio = min(
                max(orig_dur / max(allowed_duration, 1e-6), 1.0),
                max_speed_rate,
            )
            if target_ratio >= max_speed_rate:
                speed_capped = True
            current_ratio = 1.0
            attempt = 0
            while dur > allowed_duration and current_ratio < target_ratio:
                attempt += 1
                remaining = target_ratio - current_ratio
                # Use a finer increment near the end for smoother durations
                delta = 0.05
                next_ratio = min(current_ratio + delta, target_ratio)
                if next_ratio <= current_ratio:
                    break
                fast_piece = _os.path.join(piece_dir, f"{srt_base}_piece_{piece_idx}_fast_{attempt}.flac")
                try:
                    accelerate_audio(orig_piece, fast_piece, next_ratio)
                    if not _os.path.exists(fast_piece):
                        break
                    piece = fast_piece
                    new_dur = ffprobe_duration(piece)
                    if new_dur <= 0 or new_dur >= dur:
                        break
                    dur = new_dur
                    current_ratio = next_ratio
                except Exception:
                    break

        # Enforce sequential narration if no_overlap=True while keeping pacing natural.
        eff_start = adj_start
        if no_overlap:
            if speed_capped:
                eff_start = max(
                    max(0.0, adj_start - max_lead_overlap),
                    cursor_t + 0.05,
                )
            else:
                eff_start = max(adj_start, cursor_t + 0.05)
        
        # # From 2nd regeneration attempt onwards: check if piece ends after subtitle and scale it
        # if regeneration_attempt >= 1:
        #     piece_end = eff_start + dur
        #     subtitle_end = end  # from ev.end
        #     if piece_end > subtitle_end:
        #         # Narration overflows subtitle: compress piece to fit exactly within subtitle
        #         available_time = subtitle_end - eff_start
        #         if available_time > 0.1:  # Minimum 0.1s to avoid zero/negative duration
        #             scale_ratio = dur / available_time
        #             # Apply accelerate_audio to compress piece
        #             attempt_scale = 0
        #             while dur > available_time and scale_ratio < max_speed_rate * 2:
        #                 attempt_scale += 1
        #                 scaled_piece = _os.path.join(piece_dir, f"{srt_base}_piece_{piece_idx}_scale_{attempt_scale}.flac")
        #                 try:
        #                     accelerate_audio(piece, scaled_piece, min(scale_ratio, max_speed_rate * 2))
        #                     if _os.path.exists(scaled_piece):
        #                         piece = scaled_piece
        #                         new_dur = ffprobe_duration(piece)
        #                         if new_dur > 0 and new_dur < dur:
        #                             dur = new_dur
        #                             if dur <= available_time:
        #                                 break
        #                     # Increase ratio for next attempt if still not fitting
        #                     scale_ratio *= 1.1
        #                 except Exception:
        #                     break
        
        cursor_t = eff_start + dur
        items.append({"start": eff_start, "duration": dur, "file": piece,"end": eff_start + dur, "subtitle_end": end})

    if not items:
        # create a tiny silent file to avoid downstream failures
        _os.makedirs(_os.path.dirname(out_audio) or ".", exist_ok=True)
        make_silence(0.5, out_audio)
        meta_path = meta_out or _os.path.splitext(out_audio)[0] + ".schedule.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"items": []}, f, ensure_ascii=False, indent=2)
        return out_audio, meta_path

    # Save metadata JSON
    meta_path = meta_out or _os.path.splitext(out_audio)[0] + ".schedule.json"
    _os.makedirs(_os.path.dirname(meta_path) or ".", exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, ensure_ascii=False, indent=2)

    # ✅ STUDIO-GRADE APPROACH: silence baseline + adelay overlay
    # Create a silent timeline, then overlay each piece at exact position using adelay
    # This prevents ANY overlap and is standard in professional audio mixing
    
    # Calculate total timeline duration (last item end + 1s buffer)
    total_duration = max(it["end"] for it in items) + 1.0
    
    # ⚠️ Check if narration exceeds chunk duration and regenerate if needed
    # if chunk_duration is not None and total_duration > chunk_duration:
    #     send_discord_message(f"⚠️ Narration duration ({total_duration:.2f}s) exceeds chunk duration ({chunk_duration:.2f}s). Regenerating... (attempt {regeneration_attempt + 1})")
        
    #     # Calculate required speed ratio to fit narration into chunk
    #     base_ratio = total_duration / chunk_duration
    #     # Amplify the delta to converge faster (10x acceleration for rapid convergence)
    #     delta = base_ratio - 1.0
    #     amplified_delta = delta * 45.0
    #     required_ratio = min(1.0 + amplified_delta, 2.0)
        
    #     # Adjust speaking_rate and max_speed_rate for regeneration
    #     new_speaking_rate = speaking_rate * required_ratio
    #     new_max_speed_rate = max_speed_rate * required_ratio
    #     # Calculate slot_duration_scale to force more pieces into speed-up loop (cumulative)
    #     new_slot_duration_scale = slot_duration_scale / required_ratio
        
    #     send_discord_message(f"🔧 Old: speaking_rate={speaking_rate:.3f}, max_speed_rate={max_speed_rate:.3f}, slot_scale={slot_duration_scale:.3f}")
    #     send_discord_message(f"🔧 New: speaking_rate={new_speaking_rate:.3f}, max_speed_rate={new_max_speed_rate:.3f}, slot_scale={new_slot_duration_scale:.3f}, ratio={required_ratio:.3f}")
        
    #     # Clear cache directory to force reprocessing with new max_speed_rate
    #     # Keep TTS .wav files since speaking_rate doesn't affect them much
    #     # Speed is controlled by fx_func (atempo) and accelerate_audio (max_speed_rate)
    #     import shutil
    #     try:
    #         # Delete processed subdirectories but keep tts_dir with .wav files
    #         for subdir in [norm_dir, fx_dir, piece_dir, trim_dir]:
    #             if _os.path.exists(subdir):
    #                 shutil.rmtree(subdir)
    #                 _os.makedirs(subdir, exist_ok=True)
    #     except Exception:
    #         pass
        
    #     # Recursively regenerate with adjusted parameters and incremented attempt counter
    #     return build_narration_schedule(
    #         srt_path=srt_path,
    #         out_audio=out_audio,
    #         voice_name=voice_name,
    #         speaking_rate=new_speaking_rate,
    #         lead=lead,
    #         meta_out=meta_out,
    #         trim=trim,
    #         trim_threshold_db=trim_threshold_db,
    #         rate_mode=rate_mode,
    #         apply_fx=apply_fx,
    #         tmp_subdir=tmp_subdir,
    #         no_overlap=no_overlap,
    #         max_speed_rate=new_max_speed_rate,
    #         max_lead_overlap=max_lead_overlap,
    #         voice_fx_func=voice_fx_func,
    #         chunk_duration=chunk_duration,  # Pass through to verify after regeneration
    #         narration_atempo=narration_atempo,
    #         slot_duration_scale=new_slot_duration_scale,
    #         regeneration_attempt=regeneration_attempt + 1,
    #     )
    
    # ⚠️ If too many pieces (>80), build in batches to avoid ffmpeg filter_complex limit
    MAX_BATCH_SIZE = 80
    if len(items) > MAX_BATCH_SIZE:
        send_discord_message(f"📦 Building narration in batches ({len(items)} pieces, {(len(items) + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE} batches)...")
        
        batch_outputs = []
        num_batches = (len(items) + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE
        
        for batch_idx in range(num_batches):
            start_idx = batch_idx * MAX_BATCH_SIZE
            end_idx = min((batch_idx + 1) * MAX_BATCH_SIZE, len(items))
            batch_items = items[start_idx:end_idx]
            
            # Calculate batch duration (from first item start to last item end)
            batch_start = batch_items[0]["start"]
            batch_end = batch_items[-1]["end"]
            batch_duration = batch_end - batch_start + 1.0
            
            # Build this batch
            batch_file = _os.path.join(_os.path.dirname(out_audio), f"batch_{batch_idx}.flac")
            
            cmd: List[str] = ["ffmpeg", "-y"]
            cmd += ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={batch_duration}"]
            
            for it in batch_items:
                cmd += ["-i", it["file"]]
            
            delays = []
            labels = []
            for idx, it in enumerate(batch_items, start=1):
                # Adjust delay relative to batch start
                ms = max(0, int((it["start"] - batch_start) * 1000))
                lbl = f"a{idx}"
                delays.append(f"[{idx}:a]adelay={ms}|{ms}[{lbl}]")
                labels.append(f"[{lbl}]")
            
            filter_complex = ";".join(delays) + f";[0:a]{''.join(labels)}amix=inputs={len(batch_items)+1}:duration=longest:normalize=0"
            
            cmd += ["-filter_complex", filter_complex, "-ar", "48000", "-ac", "2", "-c:a", "flac", batch_file]
            run_logged_subprocess(cmd, check=True, capture_output=True)
            
            # Verify batch file
            batch_dur_actual = ffprobe_duration(batch_file)
            batch_size_kb = _os.path.getsize(batch_file) / 1024
            send_discord_message(f"📦 Batch {batch_idx+1}: {len(batch_items)} pieces, expected={batch_duration:.2f}s, actual={batch_dur_actual:.2f}s, size={batch_size_kb:.1f}KB")
            
            batch_outputs.append({"file": batch_file, "start": batch_start, "duration": batch_duration, "actual_duration": batch_dur_actual})
        
        # Concatenate batches directly (no gaps needed - each batch has its own timeline)
        # Each batch was built with anullsrc baseline + adelay, so just concat sequentially
        concat_parts = [batch["file"] for batch in batch_outputs]
        
        send_discord_message(f"🔗 Nối {len(concat_parts)} batches tuần tự...")
        concat_audio(concat_parts, out_audio)
        
        # Verify final output
        final_dur = ffprobe_duration(out_audio)
        final_size_kb = _os.path.getsize(out_audio) / 1024
        send_discord_message(f"✅ Final narration: duration={final_dur:.2f}s, size={final_size_kb:.1f}KB")
        
        # Cleanup batch files
        try:
            for batch in batch_outputs:
                _os.remove(batch["file"])
            for part in concat_parts:
                if "gap_" in part:
                    _os.remove(part)
        except Exception:
            pass
            
    else:
        # Original single-pass approach for <=80 pieces
        # Build ffmpeg command with anullsrc baseline as input [0]
        cmd: List[str] = ["ffmpeg", "-y"]
        cmd += ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={total_duration}"]
        
        # Add all pieces as inputs [1], [2], ..., [N]
        for it in items:
            cmd += ["-i", it["file"]]
        
        # Build filter_complex: adelay each piece, then amix with baseline
        delays = []
        labels = []
        for idx, it in enumerate(items, start=1):  # Start from 1 because [0] is anullsrc
            ms = max(0, int(it["start"] * 1000))
            lbl = f"a{idx}"
            delays.append(f"[{idx}:a]adelay={ms}|{ms}[{lbl}]")
            labels.append(f"[{lbl}]")
        
        # amix: baseline [0:a] + all delayed pieces
        filter_complex = ";".join(delays) + f";[0:a]{''.join(labels)}amix=inputs={len(items)+1}:duration=longest:normalize=0"
        
        cmd += [
            "-filter_complex", filter_complex,
            "-c:a", "flac",
            out_audio
        ]
        
        # send_discord_message(cmd) 
        run_logged_subprocess(cmd, check=True, capture_output=True)
    # ⚠️ Check if narration exceeds chunk duration BEFORE building (faster than probing after)
    if chunk_duration is not None:
        # Check last narration piece end time instead of waiting for final file
        last_narration_end = max(it["end"] for it in items)
        if last_narration_end > chunk_duration:
            send_discord_message(f"⚠️ Narration end time ({last_narration_end:.2f}s) exceeds video duration ({chunk_duration:.2f}s). Increasing atempo... (attempt {regeneration_attempt + 1})")
            
            # Increment narration_atempo by 0.05
            new_atempo = narration_atempo + 0.05
            
            # Clear cache to force reprocessing (keep TTS .wav files)
            import shutil
            try:
                for subdir in [norm_dir, fx_dir, piece_dir, trim_dir]:
                    if _os.path.exists(subdir):
                        shutil.rmtree(subdir)
                        _os.makedirs(subdir, exist_ok=True)
            except Exception:
                pass
            
            send_discord_message(f"🔧 Old atempo: {narration_atempo:.2f} → New atempo: {new_atempo:.2f}")
            
            # Regenerate with increased atempo
            return build_narration_schedule(
                srt_path=srt_path,
                out_audio=out_audio,
                voice_name=voice_name,
                speaking_rate=speaking_rate,
                lead=lead,
                meta_out=meta_out,
                trim=trim,
                trim_threshold_db=trim_threshold_db,
                rate_mode=rate_mode,
                apply_fx=apply_fx,
                tmp_subdir=tmp_subdir,
                no_overlap=no_overlap,
                max_speed_rate=max_speed_rate,
                max_lead_overlap=max_lead_overlap,
                voice_fx_func=voice_fx_func,
                chunk_duration=chunk_duration,
                narration_atempo=new_atempo,
                slot_duration_scale=slot_duration_scale,
                regeneration_attempt=regeneration_attempt + 1,
            )
    
    # Cleanup temporary files: keep only WAV files (remove generated .flac and other aux files)
    try:
        for root, _, files in _os.walk(tmpdir):
            for fname in files:
                path = _os.path.join(root, fname)
                # Skip WAV files; keep them. Also avoid touching final outputs.
                if fname.lower().endswith('.wav'):
                    continue
                try:
                    _os.remove(path)
                except Exception:
                    pass
    except Exception:
        pass

    return out_audio, meta_path
def mix_narration_into_video(video_path: str, narration_path: str, out_path: str, narration_volume_db: float = 6.0, replace_audio: bool = False, shift_sec: float = 0.7, extend_video: bool = False, video_volume_db: float = -4.0) -> str:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    vid_dur = ffprobe_duration(video_path)
    nar_dur = ffprobe_duration(narration_path)
    pad_sec = max(0.0, nar_dur - vid_dur)
    need_pad = extend_video and pad_sec > 0.01
    narration_volume_db = 8.0
    video_volume_db = -5.0
    if replace_audio:
        # Replace video audio entirely with narration; optionally extend video
        if need_pad:
            vfilter = f"tpad=stop_mode=clone:stop_duration={pad_sec}"
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path, "-i", narration_path,
                "-filter_complex", f"[0:v]{vfilter}[v]",
                "-map", "[v]", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                out_path
            ]
        else:
                cmd = [
                "ffmpeg", "-y",
                "-i", video_path, "-i", narration_path,
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-profile:v", "high", "-level", "4.0", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
                out_path
            ]
        run_logged_subprocess(cmd, check=True)
        return out_path

    # Mix with original audio; if original has no audio, this still works by mapping only narration
    # Optional global shift: positive shifts narration later (adelay), negative trims narration start (atrim)
    pre = []
    if shift_sec > 0:
        ms = max(0, int(shift_sec * 1000))
        pre.append(f"adelay={ms}|{ms}")
    elif shift_sec < 0:
        pre.append(f"atrim={abs(shift_sec)}:")
        pre.append("asetpts=PTS-STARTPTS")

    pre_chain = ",".join(pre) if pre else ""
    bg_gain = 0.4 * (10 ** (video_volume_db / 20))
    nar_gain = 1.4 * (10 ** (narration_volume_db / 20))
    nar_prefix = f"[1:a]{pre_chain}," if pre_chain else "[1:a]"
    nar_chain = f"{nar_prefix}aresample=48000,volume={nar_gain:.6f}[nar]"
    vid_pre = f"[0:a]aresample=48000,volume={bg_gain:.6f}[bg]"

    if need_pad:
        vfilter = f"[0:v]tpad=stop_mode=clone:stop_duration={pad_sec}[v]"
        filter_complex = (
            vfilter + ";" +
            vid_pre + ";" +
            nar_chain + ";" +
            f"[bg][nar]amix=inputs=2:duration=longest:normalize=1[a]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path, "-i", narration_path,
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            out_path
        ]
    else:
        filter_complex = (
            vid_pre + ";" +
            nar_chain + ";" +
            f"[bg][nar]amix=inputs=2:duration=first:normalize=1[a]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path, "-i", narration_path,
            "-filter_complex", filter_complex,
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "libx264", "-profile:v", "high", "-level", "4.0", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
            out_path
        ]
    try:
        run_logged_subprocess(cmd, check=True, capture_output=True)
        return out_path
    except subprocess.CalledProcessError:
        # Fallback: replace
        cmd2 = [
            "ffmpeg", "-y",
            "-i", video_path, "-i", narration_path,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-profile:v", "high", "-level", "4.0", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
            out_path
        ]
        run_logged_subprocess(cmd2, check=True)
        return out_path


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Create narration from SRT using Google TTS and mix into video")
    p.add_argument("--srt", required=True)
    p.add_argument("--video", required=True)
    p.add_argument("--out", required=True, help="Output video with narration")
    p.add_argument("--voice", default="vi-VN-Standard-C")
    p.add_argument("--rate", type=float, default=1.0, help="Google TTS speaking rate (e.g., 1.4)")
    p.add_argument("--replace", action="store_true", help="Replace original audio instead of mixing")
    p.add_argument("--vol", type=float, default=6.0, help="Narration volume gain in dB when mixing (negative to reduce)")
    p.add_argument("--lead", type=float, default=0.0, help="Start narration this many seconds earlier (per line, e.g., 0.1)")
    p.add_argument("--shift", type=float, default=0.0, help="Global shift for the whole narration track in seconds (positive = later)")
    p.add_argument("--start-only", action="store_true", help="Speak naturally at each start time (do not force duration to subtitle slot)")
    p.add_argument("--use-schedule", action="store_true", help="Build narration via per-line scheduling (adelay + amix) and emit JSON metadata")
    p.add_argument("--meta-out", type=str, default=None, help="Optional path to write schedule metadata JSON")
    p.add_argument("--extend-video", action="store_true", help="Extend video (freeze last frame) so narration can finish without being cut")
    p.add_argument("--trim-silence", action="store_true", help="Trim leading/trailing silence from each TTS line (off by default)")
    p.add_argument("--trim-threshold", type=int, default=-40, help="Silence threshold in dB for trimming (used when --trim-silence)")

    args = p.parse_args()

    tmp_audio = os.path.join(BASE_DIR, f"narr_{uuid.uuid4().hex}.flac")
    if args.use_schedule:
        nar, meta_path = build_narration_schedule(
            args.srt, tmp_audio,
            voice_name=args.voice, speaking_rate=args.rate, lead=args.lead,
            meta_out=args.meta_out, trim=args.trim_silence, trim_threshold_db=args.trim_threshold
        )
        print("📝 Schedule saved:", meta_path)
    else:
        nar = build_narration_from_srt(
            args.srt, tmp_audio,
            voice_name=args.voice, speaking_rate=args.rate, lead=args.lead,
            start_only=args.start_only, trim=args.trim_silence, trim_threshold_db=args.trim_threshold
        )
    mix_narration_into_video(args.video, nar, args.out, narration_volume_db=args.vol, replace_audio=args.replace, shift_sec=args.shift, extend_video=args.extend_video)
    print("✅ Created:", args.out)
