from subprocess_helper import run_logged_subprocess

import os
import json
import subprocess
import tempfile
import uuid
import math
from typing import List, Tuple, Dict, Any, Callable

import pysubs2

from GoogleTTS import text_to_wav
from DiscordMethod import send_discord_message
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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

def apply_voice_fx(in_path: str, out_path: str) -> str:
    """Apply narration voice FX chain to enhance clarity.
    Chain: asetrate=44100*0.6, aresample=44100, atempo=1.4, highpass=80Hz, lowpass=8kHz, bass +6dB @120Hz, treble -6dB @6kHz.
    """
    fx = "asetrate=44100*1.1,aresample=44100,atempo=1.6,highpass=f=80,lowpass=f=8000,bass=g=6:f=120,treble=g=-6:f=6000"
    cmd = [
        "ffmpeg", "-y", "-i", in_path,
        "-af", fx,
        "-c:a", "flac",
        out_path
    ]
    print( "Applying voice FX:", " ".join(cmd))
    run_logged_subprocess(cmd, check=True, capture_output=True)
    return out_path


def gemini_voice_fx(in_path: str, out_path: str) -> str:
    """Apply Gemini-style narration voice FX chain.
    Chain: asetrate=44100*0.6, aresample=44100, atempo=1.4, highpass=80Hz, lowpass=8kHz, 
           bass +6dB @120Hz, treble -6dB @6kHz, dynaudnorm, volume=6dB
    """
    fx = "asetrate=44100*1.3,aresample=44100,atempo=1.18,highpass=f=80,lowpass=f=8000,bass=g=6:f=120,treble=g=-6:f=6000,dynaudnorm=f=150:g=15,volume=6dB"
    cmd = [
        "ffmpeg", "-y", "-i", in_path,
        "-af", fx,
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
        "-c:a", "flac",
        out_path
    ]
    run_logged_subprocess(cmd, check=True, capture_output=True)
    return out_path


def concat_audio(parts: List[str], out_path: str) -> str:
    # Use concat demuxer for reliable concatenation
    # Ensure each part is 48kHz stereo FLAC; if not, transcode to a temp file
    norm_parts = []
    for p in parts:
        # create normalized temp file
        try:
            nf = tempfile.NamedTemporaryFile("wb", delete=False, suffix=".flac")
            nf.close()
            cmd = [
                "ffmpeg", "-y", "-i", p,
                "-ar", "48000", "-ac", "2", "-c:a", "flac",
                nf.name
            ]
            run_logged_subprocess(cmd, check=True, capture_output=True)
            norm_parts.append(nf.name)
        except Exception:
            # fallback to original if conversion fails
            norm_parts.append(p)

    try:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as f:
            for p in norm_parts:
                f.write(f"file '{p}'\n")
            list_path = f.name
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-ar", "48000", "-ac", "2", "-c:a", "flac",
            out_path
        ]
        run_logged_subprocess(cmd, check=True, capture_output=True)
    finally:
        try:
            os.unlink(list_path)
        except Exception:
            pass
        for p in norm_parts:
            try:
                if p not in parts:
                    os.unlink(p)
            except Exception:
                pass
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
            run_logged_subprocess(["ffmpeg", "-y", "-i", natural_src, "-c:a", "flac", natural], check=True, capture_output=True)
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
    max_lead_overlap: float = 0.6,
    voice_fx_func: Callable[[str, str], str] | None = None,
) -> Tuple[str, str]:
    """Generate per-line audio, then mix by scheduling each clip at its start time using adelay.
    Returns (final_audio_path, metadata_json_path)."""
    subs = pysubs2.load(srt_path, encoding="utf-8")
    subs.events.sort(key=lambda ev: ev.start)
    # Use provided voice FX function or default to apply_voice_fx
    fx_func = voice_fx_func if voice_fx_func is not None else apply_voice_fx
    # Place temp files under BASE_DIR/temp_narr_sched/<tmp_subdir> if provided
    tmpdir = os.path.join(BASE_DIR, "temp_narr_sched", tmp_subdir) if tmp_subdir else os.path.join(BASE_DIR, "temp_narr_sched")
    os.makedirs(tmpdir, exist_ok=True)
    # Create subfolders to reduce per-directory file counts (tts, norm, fx, piece, trim)
    tts_dir = os.path.join(tmpdir, "tts")
    norm_dir = os.path.join(tmpdir, "norm")
    fx_dir = os.path.join(tmpdir, "fx")
    piece_dir = os.path.join(tmpdir, "piece")
    trim_dir = os.path.join(tmpdir, "trim")
    for d in (tts_dir, norm_dir, fx_dir, piece_dir, trim_dir):
        os.makedirs(d, exist_ok=True)

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
        raw_wav = os.path.join(tts_dir, f"{srt_base}_tts_{piece_idx}.wav")
        raw_wav_vi = os.path.join(tts_dir, f"{srt_base}.vi_tts_{piece_idx}.wav")
        # Speaking rate: dynamic when rate_mode=1, else fixed base_rate
        slot = end - start
        norm_wav = os.path.join(norm_dir, f"norm_{srt_base}_{piece_idx}.flac")
        
        # Check if cached TTS exists (either format)
        if os.path.exists(raw_wav_vi):
            # Prefer .vi_tts format if exists
            src_wav = raw_wav_vi
        elif os.path.exists(raw_wav):
            # Use regular _tts format
            src_wav = raw_wav
        else:
            # Generate new TTS
            rate_use = _compute_dynamic_speaking_rate(text, slot, base_rate=speaking_rate) if rate_mode == 1 else speaking_rate
            res = text_to_wav(text, raw_wav, voice_name=voice_name, speaking_rate=rate_use, sendNotify=False)
            if not res or not os.path.exists(raw_wav):
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
            trimmed = os.path.join(trim_dir, f"{srt_base}_trim_{piece_idx}.wav")
            trim_silence(src_wav, trimmed, threshold_db=trim_threshold_db)
            src_wav = trimmed
        # Produce a piece fitted to the slot to reduce overlaps when scheduling
        # Apply FX if requested, then fit piece to slot to reduce overlaps
        slot_src = src_wav
        if apply_fx:
            slot_fx = os.path.join(fx_dir, f"{srt_base}_fx_{piece_idx}.flac")
            slot_src = fx_func(src_wav, slot_fx)
        piece = os.path.join(piece_dir, f"{srt_base}_piece_{piece_idx}.flac")
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
            if os.path.exists(piece) and os.path.getsize(piece) > 0:
                piece_created = True
        except Exception:
            pass
        
        if not piece_created:
            # Fallback: fit to slot to ensure a piece exists
            fit_audio_to_slot(slot_src, slot, piece)
        
        # Wait briefly for file system sync on Linux
        import time
        if not os.name == 'nt':  # Not Windows
            time.sleep(0.01)  # 10ms delay for file sync
        
        dur = ffprobe_duration(piece)
        if dur <= 0:
            # Fallback: use source duration if probe fails
            dur = ffprobe_duration(slot_src) if os.path.exists(slot_src) else slot

        soft_allow = slot + 0.2
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
                fast_piece = os.path.join(piece_dir, f"{srt_base}_piece_{piece_idx}_fast_{attempt}.flac")
                try:
                    accelerate_audio(orig_piece, fast_piece, next_ratio)
                    if not os.path.exists(fast_piece):
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
        cursor_t = eff_start + dur
        items.append({"start": eff_start, "duration": dur, "file": piece,"end": eff_start + dur})

    if not items:
        # create a tiny silent file to avoid downstream failures
        os.makedirs(os.path.dirname(out_audio) or ".", exist_ok=True)
        make_silence(0.5, out_audio)
        meta_path = meta_out or os.path.splitext(out_audio)[0] + ".schedule.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"items": []}, f, ensure_ascii=False, indent=2)
        return out_audio, meta_path

    # Save metadata JSON
    meta_path = meta_out or os.path.splitext(out_audio)[0] + ".schedule.json"
    os.makedirs(os.path.dirname(meta_path) or ".", exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, ensure_ascii=False, indent=2)

    # ✅ STUDIO-GRADE APPROACH: silence baseline + adelay overlay
    # Create a silent timeline, then overlay each piece at exact position using adelay
    # This prevents ANY overlap and is standard in professional audio mixing
    
    # Calculate total timeline duration (last item end + 1s buffer)
    total_duration = max(it["end"] for it in items) + 1.0
    
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
    # Cleanup temporary files: keep only WAV files (remove generated .flac and other aux files)
    try:
        for root, _, files in os.walk(tmpdir):
            for fname in files:
                path = os.path.join(root, fname)
                # Skip WAV files; keep them. Also avoid touching final outputs.
                if fname.lower().endswith('.wav'):
                    continue
                try:
                    os.remove(path)
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
