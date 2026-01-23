import os
import re
import time
from playwright.sync_api import sync_playwright
from DiscordMethod import send_discord_message

START_URL = "https://v.qq.com/x/cover/mzc003mxhxhg3xb.html"

MAX_PRESS = 2000
INTERVAL = 0.4
LINK_CACHE_FILENAME = "episode_links.txt"


def parse_cid_vid(url: str) -> tuple[str | None, str | None]:
    m = re.search(r"/x/cover/([^/]+)(?:/([^/.]+))?", url)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def _cache_path(run_dir: str | None) -> str | None:
    if not run_dir:
        return None
    return os.path.join(run_dir, LINK_CACHE_FILENAME)


def _load_cached_links(cache_path: str | None) -> list[str]:
    if not cache_path:
        return []
    if not os.path.isfile(cache_path):
        return []
    try:
        with open(cache_path, "r", encoding="utf-8") as fh:
            return [line.strip() for line in fh if line.strip()]
    except Exception as exc:
        send_discord_message(f"⚠️ Không đọc được cache tập: {exc}")
        return []


def _save_cached_links(cache_path: str | None, links: list[str]) -> None:
    if not cache_path or not links:
        return
    try:
        with open(cache_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(links))
    except Exception as exc:
        send_discord_message(f"⚠️ Không ghi được cache tập: {exc}")


def get_episode_links(url: str = START_URL, *, headless: bool = True, interval: float = INTERVAL, max_press: int = MAX_PRESS, run_dir: str | None = None) -> list[str]:
    visited = set()
    episodes: list[str] = []

    send_discord_message(f"🔍 Lấy các tập bằng cách keyboard crawl: {url}")
    cache_path = _cache_path(run_dir)
    cached_links = _load_cached_links(cache_path)
    if cached_links:
        episodes.extend(cached_links)
        start_url = cached_links[-1]
        send_discord_message(f"ℹ️ Resume từ cache ({len(cached_links)} tập), bắt đầu tại {start_url}")
    else:
        start_url = url
    seen_urls = set(episodes)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled", "--mute-audio"])
        page = browser.new_page()
        page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("video", timeout=30000)
        time.sleep(2)
        page.mouse.click(640, 360)
        time.sleep(1)

        base_cid, _ = parse_cid_vid(page.url)
        current_url = page.url

        while True:
            cid, vid = parse_cid_vid(current_url)

            if vid and vid in visited:
                send_discord_message("🛑 VID lặp lại, dừng lại")
                break
            if cid and base_cid and cid != base_cid:
                send_discord_message("🛑 CID khác, dừng lại")
                break

            if current_url not in seen_urls:
                episodes.append(current_url)
                seen_urls.add(current_url)
                if vid:
                    visited.add(vid)
            send_discord_message(f"▶️ Collected {len(episodes)}: {current_url}")

            next_url = current_url
            presses = 0
            while presses < max_press:
                page.keyboard.press("ArrowRight")
                time.sleep(interval)
                presses += 1
                if page.url != current_url:
                    next_url = page.url
                    break

            if next_url == current_url:
                send_discord_message("🛑 Không tim được tập mới, kết thúc")
                break

            current_url = next_url
            time.sleep(2)
            page.mouse.click(640, 360)
            time.sleep(1)

        browser.close()

    _save_cached_links(cache_path, episodes)
    send_discord_message(f"✅ Tổng {len(episodes)} tập thu thập được")
    return episodes


if __name__ == "__main__":
    for link in get_episode_links(START_URL, headless=True):
        print(link)
