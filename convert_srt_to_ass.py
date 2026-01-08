import argparse
import pysubs2
import textwrap
from DiscordMethod import send_discord_message

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


def convert(input_srt: str, output_ass: str, max_chars: int, fontsize: int, font: str, marginv: int, back_opacity: int):
    subs = pysubs2.load(input_srt, encoding="utf-8")

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
    style.marginv = 28

    # Replace/ensure Default style name to force use
    subs.styles["Default"] = style

    # Wrap text lines preserving existing linebreaks and ASS tags
    for ev in subs:
        text = ev.text.strip()
        parts = text.split("\\N")
        wrapped_parts = []
        for p in parts:
            if len(p) <= max_chars:
                wrapped_parts.append(p)
            else:
                wrapped_parts.extend(textwrap.wrap(p, max_chars))
        ev.text = "\\N".join(wrapped_parts)

    subs.save(output_ass, encoding="utf-8")
    print("Saved:", output_ass)


if __name__ == "__main__":
    args = build_args()
    send_discord_message(args.input, args.output, args.max_chars, args.fontsize, args.font, args.marginv, args.back_opacity)
