import argparse
import pysubs2
import textwrap
from DiscordMethod import send_discord_message

import convert_stt

MIN_WORDS_FOR_COMMA_SPLIT = 15
MAX_CLAUSES_PER_SUBTITLE = 3

def build_args():
    p = argparse.ArgumentParser(description="Convert SRT → ASS with TikTok-friendly style")
    p.add_argument("input", help="input SRT path")
    p.add_argument("output", help="output ASS path")
    p.add_argument("--max-chars", type=int, default=30, help="Max chars per line before wrap")
    p.add_argument("--fontsize", type=int, default=11, help="Font size for subtitles")
    p.add_argument("--font", default="Noto Sans", help="Font name to use")
    p.add_argument("--marginv", type=int, default=20, help="Vertical margin (MarginV) to push subtitles up")
    p.add_argument("--back-opacity", type=int, default=150, help="Background alpha for ASS (0-255, ASS alpha where 0=opaque)")
    return p.parse_args()


def _wrap_text_for_ass(text: str, max_chars: int) -> str:
    parts = text.split("\\N")
    wrapped_parts = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part) <= max_chars:
            wrapped_parts.append(part)
        else:
            wrapped_parts.extend(textwrap.wrap(part, max_chars))
    return "\\N".join(wrapped_parts) if wrapped_parts else ""


def _split_segment_by_commas(segment: dict, min_words: int, max_clauses: int) -> list[dict]:
    text = (segment.get("text", "") or "").strip()
    if not text:
        return []
    clauses = [cls.strip() for cls in text.split(",") if cls.strip()]
    words = text.split()
    should_split = len(clauses) > 1 and (len(words) > min_words or len(clauses) > max_clauses)
    if not should_split:
        return [segment]

    groups = []
    buffer: list[str] = []
    for clause in clauses:
        buffer.append(clause)
        if len(buffer) == max_clauses:
            groups.append(", ".join(buffer))
            buffer = []
    if buffer:
        groups.append(", ".join(buffer))

    if not groups:
        return [segment]

    duration = max(0.0, float(segment.get("end", 0.0)) - float(segment.get("start", 0.0)))
    if duration <= 0:
        duration = 0.2

    per_piece = duration / len(groups)
    start = float(segment.get("start", 0.0))
    pieces = []
    for idx, grp in enumerate(groups):
        piece_start = start + per_piece * idx
        piece_end = piece_start + per_piece if idx < len(groups) - 1 else start + duration
        pieces.append({
            "start": piece_start,
            "end": piece_end,
            "text": grp
        })
    return pieces


def _build_ass_segments(subs: pysubs2.SSAFile) -> list[dict]:
    segments: list[dict] = []
    for ev in subs:
        text = ev.text.replace("\\N", " ").strip()
        if not text:
            continue
        segments.append({
            "start": ev.start / 1000.0,
            "end": ev.end / 1000.0,
            "text": text
        })

    expanded = convert_stt._expand_segments_by_length(segments)
    final_segments: list[dict] = []
    for seg in expanded:
        final_segments.extend(_split_segment_by_commas(seg, MIN_WORDS_FOR_COMMA_SPLIT, MAX_CLAUSES_PER_SUBTITLE))
    return sorted(final_segments, key=lambda s: float(s.get("start", 0.0)))


def convert(input_srt: str, output_ass: str, max_chars: int, fontsize: int, font: str, marginv: int, back_opacity: int):
    subs = pysubs2.load(input_srt, encoding="utf-8")
    ass_segments = _build_ass_segments(subs)

    # Create TikTok-friendly style
    style = pysubs2.SSAStyle()
    style.name = "TikTok"
    style.fontname = font
    style.fontsize = fontsize
    # Keep original style defaults created by the user
    style.primarycolor = pysubs2.Color(255, 255, 255, 0)
    style.backcolor = pysubs2.Color(0, 0, 0, max(0, min(255, back_opacity)))
    style.borderstyle = 3
    style.outline = 2
    style.shadow = 0
    style.marginv = marginv

    new_subs = pysubs2.SSAFile()
    new_subs.styles["Default"] = style

    for seg in ass_segments:
        wrapped = _wrap_text_for_ass(seg.get("text", ""), max_chars)
        if not wrapped:
            continue
        start_ms = max(0, int(round(seg.get("start", 0.0) * 1000)))
        end_ms = max(start_ms + 20, int(round(seg.get("end", seg.get("start", 0.0) + 0.02) * 1000)))
        new_subs.append(pysubs2.SSAEvent(start=start_ms, end=end_ms, text=wrapped))

    new_subs.save(output_ass, encoding="utf-8")
    print("Saved:", output_ass)


if __name__ == "__main__":
    args = build_args()
    send_discord_message(args.input, args.output, args.max_chars, args.fontsize, args.font, args.marginv, args.back_opacity)
