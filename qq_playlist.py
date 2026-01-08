from playwright.sync_api import sync_playwright
import re
import time
from DiscordMethod import send_discord_message

def parse_eps(html: str) -> list[str]:
    items = re.findall(
        r'data-vid="([A-Za-z0-9]+)".*?data-cid="([A-Za-z0-9]+)"',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    result = []
    for vid, cid in items:
        url = f"https://v.qq.com/x/cover/{cid}/{vid}.html"
        if url not in result:
            result.append(url)
    return result


def get_episode_links(url: str, headless: bool = True, slow_mo: int = 0, timeout_ms: int = 120000) -> list[str]:
    BTN_TEXT = "全部"
    OVERLAY_SELECTOR = "div.b-sticky.episode-overlay__container"
    EPISODE_LIST_SELECTOR = (
        "#app div.page-play.view-content main "
        "div.container-main__wrapper "
        "div.container-episode "
        "div.b-sticky__scroller "
        "div:nth-child(1) "
        "div.episode-list"
    )
    TAB_SELECTOR = "div.b-tab__item"

    playlist: list[str] = []

    def _ensure_unique_add(items: list[str]):
        for ep in items:
            if ep and ep not in playlist:
                playlist.append(ep)

    # Attempt multiple times to reduce flakiness (network, anti-bot, slow JS)
    attempts = 3
    for attempt in range(attempts):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless, slow_mo=slow_mo)
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

                # helpful small interaction to reduce anti-bot gating
                try:
                    page.mouse.move(100, 100)
                    page.keyboard.press("End")
                except Exception:
                    pass

                # Try overlay path first; add fallback matching for different button texts
                try:
                    btn_all = page.locator("div.b-btn.b-btn--round", has_text=BTN_TEXT)
                    if btn_all.count() == 0:
                        # broader search for buttons containing common variants
                        alt = page.locator("text=/全部|所有|All/i")
                        if alt.count() > 0:
                            # pick the first clickable ancestor that looks like a button
                            try:
                                btn_handle = alt.first
                                btn_handle.scroll_into_view_if_needed()
                                btn_handle.click()
                            except Exception:
                                pass
                    else:
                        try:
                            btn_all.first.scroll_into_view_if_needed()
                            btn_all.first.click()
                        except Exception:
                            pass

                    # wait for overlay and parse tabs if present
                    try:
                        page.wait_for_selector(f"{OVERLAY_SELECTOR} [data-vid][data-cid]", timeout=60000)
                        tabs = page.locator(TAB_SELECTOR)
                        tab_count = tabs.count()
                        for i in range(tab_count):
                            tab = tabs.nth(i)
                            try:
                                tab.scroll_into_view_if_needed()
                                tab.click()
                            except Exception:
                                pass
                            # allow JS render and lazy load
                            time.sleep(0.8)
                            # attempt to scroll overlay to load lazy items
                            try:
                                page.eval_on_selector(OVERLAY_SELECTOR, "el => { el.scrollTop = 0; el.scrollTop = el.scrollHeight; }")
                            except Exception:
                                pass
                            overlay_html = page.inner_html(OVERLAY_SELECTOR)
                            _ensure_unique_add(parse_eps(overlay_html))
                    except Exception:
                        # overlay not found — fallthrough to episode-list strategy
                        pass
                except Exception:
                    # any click/match error; continue to fallback
                    pass

                # CASE: episode-list path (tabs + episode-list container)
                try:
                    tabs = page.locator(TAB_SELECTOR)
                    tab_count = tabs.count()
                    for i in range(tab_count):
                        tab = tabs.nth(i)
                        try:
                            tab.scroll_into_view_if_needed()
                            tab.click()
                        except Exception:
                            pass
                        time.sleep(0.8)
                        # try to wait for elements to appear, with retries
                        found = False
                        for _ in range(3):
                            try:
                                page.wait_for_selector(f"{EPISODE_LIST_SELECTOR} [data-vid][data-cid]", timeout=5000)
                                found = True
                                break
                            except Exception:
                                # try to nudge the container to load
                                try:
                                    page.eval_on_selector(EPISODE_LIST_SELECTOR, "el => { el.scrollTop = el.scrollHeight; }")
                                except Exception:
                                    pass
                                time.sleep(0.6)
                        if found:
                            list_html = page.inner_html(EPISODE_LIST_SELECTOR)
                            _ensure_unique_add(parse_eps(list_html))

                except Exception:
                    pass

                # Final fallback: parse whole page content for any data-vid/data-cid occurrences
                try:
                    if not playlist:
                        content = page.content()
                        _ensure_unique_add(parse_eps(content))
                except Exception:
                    pass

                browser.close()
                send_discord_message(f"✅ Lấy danh sách tập hoàn tất (attempt {attempt+1}/{attempts}), tổng {len(playlist)} tập.")
                break
        except Exception as e:
            send_discord_message(f"⚠️ get_episode_links attempt {attempt+1}/{attempts} thất bại: {e}")
            time.sleep(1 + attempt * 2)
            # last attempt will naturally exit loop and return whatever collected

    return playlist
if __name__ == "__main__":
    test_url = "https://m.v.qq.com/play/play.html?vid=u3553bptjqz&url_from=share&second_share=0&share_from=copy"
    eps_links = get_episode_links(test_url, headless=True, slow_mo=200)
    for link in eps_links:
        print(link)
