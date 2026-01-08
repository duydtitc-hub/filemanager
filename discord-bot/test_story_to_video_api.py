#!/usr/bin/env python3
"""
Simple test helper to invoke the same API used by StoryToVideo forms
without needing the Discord modal. Use this to quickly validate server
behavior from the command line or from other scripts.

Example:
  python test_story_to_video_api.py --genre horror --video_urls "https://youtu.be/xxx" --model gpt-4o-mini

This script prints the server response (JSON or text) and returns non-zero
exit code on network failure.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
import requests
import random

# Default endpoint used by the modal classes in DiscordForm.py
DEFAULT_API = "https://localhost:8000/generate_story_to_video"


def test_story_to_video(
    genre: str,
    video_urls: List[str],
    model: str = "gpt-4o-mini",
    bg_choice: str = "",
    extra: Optional[Dict[str, Any]] = None,
    api_endpoint: str = DEFAULT_API,
    timeout: int = 30,
) -> Optional[Dict[str, Any]]:
    """Call the story->video endpoint mirroring the form parameters.

    Returns parsed JSON on success, prints text on non-JSON success, and
    returns None on failure.
    """
    params: Dict[str, Any] = {
        "genre": genre,
        "video_urls": ",".join(video_urls) if isinstance(video_urls, (list, tuple)) else str(video_urls),
        "title": "",
        "model": model,
        "bg_choice": bg_choice,
    }
    if extra:
        params.update(extra)

    print(f"-> Calling {api_endpoint} with params:\n{json.dumps(params, ensure_ascii=False, indent=2)}")

    try:
        r = requests.post(api_endpoint, params=params, timeout=timeout)
        r.raise_for_status()
    except Exception as e:
        print(f"Request failed: {e}")
        return None

    # Try parse JSON
    try:
        data = r.json()
        print("<-- JSON response:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return data
    except Exception:
        print("<-- Non-JSON response (text):")
        text = r.text or ""
        print(text[:4000])
        return {"raw_text": text}


def _parse_comma_list(value: str) -> List[str]:
    return [v.strip() for v in value.replace('\n', ',').split(',') if v.strip()]


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Test story->video API without Discord form")
    p.add_argument("--genre", required=True, choices=["horror", "face_slap", "random_mix"], help="Genre to request")
    p.add_argument("--video_urls", required=False, default="", help="Comma or newline separated video URLs to use as backgrounds (optional)")
    p.add_argument("--model", default="gpt-4o-mini", help="AI model (gpt-4o-mini|gpt-4o|gpt-4-turbo)")
    p.add_argument("--bg_choice", default="", help="Selected background audio filename (optional)")
    p.add_argument("--horror_theme", default="", help="(horror) horror_theme")
    p.add_argument("--horror_setting", default="", help="(horror) horror_setting")
    p.add_argument("--face_slap_theme", default="", help="(face_slap) theme")
    p.add_argument("--face_slap_role", default="", help="(face_slap) role")
    p.add_argument("--randomize", action="store_true", help="Auto-generate random themes/roles/settings like the Discord form")
    p.add_argument("--api", default=DEFAULT_API, help="API endpoint to call (overrides default)")
    p.add_argument("--mode", choices=["http", "call_func", "enqueue"], default="http",
                   help="How to invoke the pipeline: 'http' = POST to endpoint (default), 'call_func' = call the FastAPI function directly, 'enqueue' = put a task into app.TASK_QUEUE bypassing endpoint validation")
    p.add_argument("--timeout", type=int, default=30, help="Request timeout seconds")

    args = p.parse_args(argv)

    video_list = _parse_comma_list(args.video_urls) if (args.video_urls and args.video_urls.strip()) else []


    def _gen_random_fields(genre: str) -> Dict[str, str]:
        """Return a dict of randomly chosen fields for the given genre."""
        # Prefer using StoryPrompts from story_generator so random choices match server behavior
        try:
            from story_generator import StoryPrompts
            out: Dict[str, str] = {}
            if genre == "horror":
                out["horror_theme"] = random.choice(StoryPrompts.KINH_DI.get("themes", []))
                out["horror_setting"] = random.choice(StoryPrompts.KINH_DI.get("settings", []))
            elif genre == "face_slap":
                out["face_slap_theme"] = random.choice(StoryPrompts.VA_MAT.get("themes", []))
                # VA_MAT uses 'vai_tro_gia' for role
                out["face_slap_role"] = random.choice(StoryPrompts.VA_MAT.get("vai_tro_gia", []))
                out["face_slap_setting"] = random.choice(StoryPrompts.VA_MAT.get("settings", []))
            else:
                # RANDOM_MIX keys: the_loai_chinh, the_loai_phu, nhan_vat, boi_canh, mo_tip
                out["random_main_genre"] = random.choice(StoryPrompts.RANDOM_MIX.get("the_loai_chinh", []))
                out["random_sub_genre"] = random.choice(StoryPrompts.RANDOM_MIX.get("the_loai_phu", []))
                out["random_character"] = random.choice(StoryPrompts.RANDOM_MIX.get("nhan_vat", []))
                out["random_setting"] = random.choice(StoryPrompts.RANDOM_MIX.get("boi_canh", []))
                out["random_plot_motif"] = random.choice(StoryPrompts.RANDOM_MIX.get("mo_tip", []))
            return out
        except Exception:
            # Fallback to simple local lists if story_generator not importable
            horror_themes = [
                "Làng cổ có lời nguyền",
                "Ngôi nhà hoang giữa rừng",
                "Bí ẩn dưới hồ làng",
            ]
            face_slap_roles = ["Chủ tịch tập đoàn", "Thiên tài y học", "Ngôi sao mạng xã hội"]
            out: Dict[str, str] = {}
            if genre == "horror":
                out["horror_theme"] = random.choice(horror_themes)
                out["horror_setting"] = "làng quê xa xôi"
            elif genre == "face_slap":
                out["face_slap_theme"] = "Chủ tịch giả làm người lao động"
                out["face_slap_role"] = random.choice(face_slap_roles)
            else:
                out["random_main_genre"] = random.choice(["romance", "sci-fi", "mystery"])
            return out

    # If user asked to randomize, fill missing fields
    if args.randomize:
        rand = _gen_random_fields(args.genre)
        # Only set values if they were not provided explicitly
        if args.genre == "horror":
            if not args.horror_theme:
                args.horror_theme = rand.get("horror_theme", "")
            if not args.horror_setting:
                args.horror_setting = rand.get("horror_setting", "")
        elif args.genre == "face_slap":
            if not args.face_slap_theme:
                args.face_slap_theme = rand.get("face_slap_theme", "")
            if not args.face_slap_role:
                args.face_slap_role = rand.get("face_slap_role", "")
        else:
            # random_mix
            if not getattr(args, "random_main_genre", None):
                # attach attribute dynamically for downstream use
                setattr(args, "random_main_genre", rand.get("random_main_genre"))

    extra: Dict[str, Any] = {}
    if args.genre == "horror":
        if args.horror_theme:
            extra["horror_theme"] = args.horror_theme
        if args.horror_setting:
            extra["horror_setting"] = args.horror_setting
    if args.genre == "face_slap":
        if args.face_slap_theme:
            extra["face_slap_theme"] = args.face_slap_theme
        if args.face_slap_role:
            extra["face_slap_role"] = args.face_slap_role

    # Only call HTTP when mode == http
    result = None
    if args.mode == "http":
        result = test_story_to_video(
            genre=args.genre,
            video_urls=video_list,
            model=args.model,
            bg_choice=args.bg_choice,
            extra=extra or None,
            api_endpoint=args.api,
            timeout=args.timeout,
        )

        if result is None:
            print("Test failed (network or server error).")
            return 2
        print("Done (HTTP mode).")
        return 0

    # For local modes, import app and call functions directly
    # Support running this helper from other directories by inserting the
    # repository root (two levels up from this file: ../) into sys.path
    try:
        import app as server_app
    except Exception:
        # Attempt to add repo root to sys.path and retry import
        from pathlib import Path
        import importlib

        repo_root = Path(__file__).resolve().parents[1]
        repo_root_str = str(repo_root)
        if repo_root_str not in sys.path:
            sys.path.insert(0, repo_root_str)

        try:
            server_app = importlib.import_module("app")
        except Exception as e:
            print(f"Cannot import local app module after adding repo root ({repo_root_str}): {e}")
            return 3

    if args.mode == "call_func":
        # Call the FastAPI handler coroutine directly. It expects query-like args (strings).
        # Use asyncio to run the coroutine.
        import asyncio

        video_urls_str = ",".join(video_list) if video_list else ""

        coro = server_app.generate_story_to_video(
            genre=args.genre,
            video_urls=video_urls_str,
            title="",
            model=args.model,
            voice="",
            bg_choice=args.bg_choice or None,
            part_duration=3600,
            horror_theme=args.horror_theme or None,
            horror_setting=args.horror_setting or None,
            face_slap_theme=args.face_slap_theme or None,
            face_slap_role=args.face_slap_role or None,
            face_slap_setting=getattr(args, 'face_slap_setting', None),
            random_main_genre=getattr(args, 'random_main_genre', None),
            random_sub_genre=getattr(args, 'random_sub_genre', None),
            random_character=getattr(args, 'random_character', None),
            random_setting=getattr(args, 'random_setting', None),
            random_plot_motif=getattr(args, 'random_plot_motif', None),
        )

        try:
            out = asyncio.run(coro)
            print("Local function returned:")
            print(out)
            return 0
        except Exception as e:
            print(f"Local call raised: {e}")
            return 4

    if args.mode == "enqueue":
        # Construct a task dict similar to endpoint and put it into TASK_QUEUE directly.
        import asyncio
        request_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        urls = video_list

        task_info = {
            "task_id": request_id,
            "task_type": "story_to_video",
            "urls": urls,
            "title": "",
            "voice": "",
            "bg_choice": args.bg_choice or None,
            "part_duration": 3600,
            "genre_params": {
                "genre": args.genre,
                "model": args.model,
                "horror_theme": args.horror_theme or None,
                "horror_setting": args.horror_setting or None,
                "face_slap_theme": args.face_slap_theme or None,
                "face_slap_role": args.face_slap_role or None,
                "random_main_genre": getattr(args, 'random_main_genre', None),
                "random_sub_genre": getattr(args, 'random_sub_genre', None),
                "random_character": getattr(args, 'random_character', None),
                "random_setting": getattr(args, 'random_setting', None),
                "random_plot_motif": getattr(args, 'random_plot_motif', None),
            },
        }

        async def _put_task():
            # Ensure tasks file is updated like endpoint
            try:
                tasks = server_app.load_tasks()
                tasks[request_id] = {
                    "task_id": request_id,
                    "status": "pending",
                    "progress": 0,
                    "phase": "queued_via_test",
                    "video_path": "",
                    "story_path": "",
                    "audio_path": "",
                    "video_file": [],
                    "title": "",
                    "genre": args.genre,
                    "model": args.model,
                    "voice": "",
                    "bg_choice": args.bg_choice or None,
                    "temp_videos": [],
                    "request_urls": urls,
                    "created_at": time.time(),
                    "type": 7,
                    "part_duration": 3600,
                    "total_parts": 0,
                    "current_part": 0,
                }
                server_app.save_tasks(tasks)
                await server_app.TASK_QUEUE.put(task_info)
                return {"task_id": request_id, "status": "queued"}
            except Exception as e:
                return {"error": str(e)}

        try:
            out = asyncio.run(_put_task())
            print("Enqueue result:", out)
            return 0 if out.get("task_id") else 5
        except Exception as e:
            print(f"Failed to enqueue task: {e}")
            return 6

    # fallback
    print("Unknown mode")
    return 99


if __name__ == "__main__":
    raise SystemExit(main())
