"""
Reusable TikTok uploader using Playwright (sync API).

Install dependency:
  pip install playwright
  playwright install

Usage example at bottom shows how to call from a script.
"""
from pathlib import Path
import time
from typing import List, Optional, Union
import json
import os
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from DiscordMethod import send_discord_message
# Async uploader removed — keep sync-only Playwright usage
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
cookies_dir = os.path.join(BASE_DIR, 'Cookies')
class TikTokUploader:
    UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=creator_center"
    DRAFT_SELECTOR = '.notranslate.public-DraftEditor-content[contenteditable="true"], .public-DraftEditor-content[contenteditable="true"]'

    def __init__(self, headless: bool = True, action_delay_ms: int = 300):
        self.headless = headless
        self.action_delay = action_delay_ms / 1000.0
        self._pw = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        # tags storage file
        self._tags_file = os.path.join(BASE_DIR, 'tiktok_tags.json')

    def _sleep(self, s: float):
        time.sleep(s)

    def start(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless,  args=[
            "--no-sandbox",
          
        ])
        self._context = self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            extra_http_headers={
                "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7"
            }
        )
       
        self._page = self._context.new_page()

    def stop(self):
        try:
            if self._context:
                self._context.close()
        finally:
            try:
                if self._browser:
                    self._browser.close()
            finally:
                if self._pw:
                    self._pw.stop()

    def load_cookies(self, cookies_path: str):
        
        p = Path(cookies_path)
        if not p.exists():
            return
        import json
        try:
            data = json.loads(p.read_text(encoding='utf8'))
            # Playwright expects list of cookie dicts
            self._context.add_cookies(data)
        except Exception as exc:
            send_discord_message(f"⚠️ TikTok cookies load failed: {exc}")

    # --- Tags helper persistence ------------------------------------------------
    def _load_tags(self) -> List[str]:
        try:
            if os.path.exists(self._tags_file):
                with open(self._tags_file, 'r', encoding='utf8') as fh:
                    data = json.load(fh)
                    if isinstance(data, list):
                        return [str(x) for x in data if x]
        except Exception:
            pass
        return []

    def _save_tags(self, tags: List[str]):
        try:
            uniq = []
            seen = set()
            for t in tags:
                tt = str(t).strip()
                if not tt:
                    continue
                if tt not in seen:
                    uniq.append(tt)
                    seen.add(tt)
            with open(self._tags_file, 'w', encoding='utf8') as fh:
                json.dump(uniq, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _parse_tags_input(self, tags_input: Union[str, List[str]]) -> List[str]:
        if not tags_input:
            return []
        if isinstance(tags_input, list):
            items = [str(x).strip() for x in tags_input]
        else:
            # split on commas or newlines; allow spaces as separators when commas absent
            if ',' in tags_input:
                parts = tags_input.split(',')
            else:
                parts = tags_input.split()  # whitespace
            items = [p.strip() for p in parts]
        # normalize tags: remove leading # and empty ones
        out = []
        for it in items:
            if not it:
                continue
            t = it.lstrip('#').strip()
            if t:
                out.append(t)
        return out

    def _merge_and_save_tags(self, new_tags: List[str]):
        if not new_tags:
            return
        try:
            existing = self._load_tags() or []
            # keep existing order, append new tags at the end if not present
            seen = set(existing)
            merged = list(existing)
            for t in new_tags:
                tt = str(t).strip()
                if not tt:
                    continue
                if tt not in seen:
                    merged.append(tt)
                    seen.add(tt)
            self._save_tags(merged)
        except Exception:
            pass

    def wait_for_upload_complete(self, timeout: int = 300) -> bool:
        # wait until .info-progress.success shows 100% or Post button enabled
        page = self._page
        end = time.time() + timeout
        while time.time() < end:
            try:
                ok = page.evaluate(r"""
                (() => {
                  const p = document.querySelector('.info-progress.success');
                  if (p) {
                    const inline = p.getAttribute('style') || '';
                    if (/width\s*:\s*100%/.test(inline)) return true;
                    const txt = (p.textContent || '').trim();
                    if (txt.includes('100%')) return true;
                    const parent = p.parentElement;
                    if (parent) {
                      const pw = parent.getBoundingClientRect().width;
                      const ew = p.getBoundingClientRect().width;
                      if (pw > 0 && Math.abs(ew - pw) < 2) return true;
                    }
                  }
                  const list = Array.from(document.querySelectorAll('.Button__content')) || [];
                  for (const c of list) {
                    if (!c) continue;
                    if ((c.textContent || '').toLowerCase().includes('post')) {
                      const btn = c.closest('button, [role="button"], a');
                      if (!btn) continue;
                      const aria = btn.getAttribute && btn.getAttribute('aria-disabled');
                      if (aria === 'true') continue;
                      if (btn.disabled || btn.hasAttribute('disabled')) continue;
                      return true;
                    }
                  }
                  return false;
                })();
                """)
                if ok:
                    return True
            except Exception:
                pass
            self._sleep(self.action_delay)
        return False

    def wait_for_music_clear(self, timeout: int = 120) -> bool:
        page = self._page
        end = time.time() + timeout
        while time.time() < end:
            try:
                ok = page.evaluate(r"""
                (() => {
                  const root = document.querySelector('.copyright-check') || document.querySelector('[data-e2e="copyright_container"]');
                  if (!root) return false;
                  if (root.querySelector('.status-result.status-success')) return true;
                  const sw = root.querySelector('.Switch__content[aria-checked="true"], .Switch__root--checked-true');
                  if (sw) return true;
                  const text = (root.textContent || '').toLowerCase();
                  if (text.includes('no issues found') || text.includes('no issues')) return true;
                  return false;
                })();
                """)
                if ok:
                    return True
            except Exception:
                pass
            self._sleep(self.action_delay)
        return False

    def clear_filename_and_field_with_backspaces(self, video_path: str):
        page = self._page
        base = Path(video_path).stem
        to_press = len(base) + 8
        # focus draft editor if present
        try:
            editor = page.query_selector(self.DRAFT_SELECTOR)
            if editor:
                editor.focus()
                self._sleep(self.action_delay)
                for _ in range(to_press):
                    page.keyboard.press('Backspace')
                    self._sleep(0.03)
                    try:
                        page.keyboard.press('Delete')
                        self._sleep(0.03)
                    except Exception:
                        # ignore if Delete not supported in this environment
                        pass
        except Exception:
            pass

    def set_caption_and_tags(self, caption: str, tags: List[str]):
        page = self._page
        caption = caption or ''
        tags = (tags or [])[:5]
        # Dismiss "Got it" button/dialog if present before entering caption/tags
        try:
            # Prefer explicit button matching the Button__root + Button__content structure
            got = page.query_selector("xpath=//button[contains(@class,'Button__root') and .//div[contains(@class,'Button__content') and normalize-space(string(.))='Đã hiểu']]")
            if got:
                got.click()
                self._sleep(self.action_delay)
        except Exception:
            pass
        # Try Draft editor
        editor = page.query_selector(self.DRAFT_SELECTOR)
        if editor:
            editor.focus()
            self._sleep(self.action_delay)
            if caption:
                page.keyboard.type(caption)
                page.keyboard.press('Enter')
                self._sleep(0.12)
            # For tags, prefer getting the Hashtag button once and reusing it.
            if tags:
                btn = page.query_selector('#web-creation-caption-hashtag-button, button[aria-label="Hashtag"], [aria-label="Hashtag"]')
                for t in tags:
                    tag = t.strip().lstrip('#')
                    try:
                        if btn:
                            try:
                                btn.click()
                            except Exception:
                                # try re-query if handle became stale
                                btn = page.query_selector('#web-creation-caption-hashtag-button, button[aria-label="Hashtag"], [aria-label="Hashtag"]')
                                if btn:
                                    btn.click()
                            # allow time for the hashtag UI to open and suggestions to render
                            self._sleep(1.0)
                            page.keyboard.type(tag)
                            # wait for suggestion to appear before pressing Enter
                            self._sleep(2.0)
                            page.keyboard.press('Enter')
                            # give time for the tag to commit
                            self._sleep(1.0)
                        else:
                            # fallback: directly type hashtag text
                            page.keyboard.press('Enter')
                            self._sleep(0.04)
                            page.keyboard.type(f"#{tag} ")
                            self._sleep(0.08)
                    except Exception:
                        try:
                            page.keyboard.type(f" #{tag}")
                            self._sleep(0.06)
                        except Exception:
                            pass
            return True

        # Fallback to textarea or contenteditable
        for sel in ['textarea[placeholder*="Describe"]', 'textarea', '[data-e2e="caption-input"]', '[contenteditable="true"]']:
            el = page.query_selector(sel)
            if not el:
                continue
            try:
                el.focus()
                if el.evaluate('e => e.tagName.toLowerCase()') == 'textarea':
                    # fill caption first
                    el.fill((caption).strip())
                    self._sleep(0.06)
                    # then use hashtag button flow for tags (query button once)
                    btn = page.query_selector('#web-creation-caption-hashtag-button, button[aria-label="Hashtag"], [aria-label="Hashtag"]')
                    for t in tags:
                        tag = t.strip().lstrip('#')
                        try:
                            if btn:
                                try:
                                    btn.click()
                                except Exception:
                                    btn = page.query_selector('#web-creation-caption-hashtag-button, button[aria-label="Hashtag"], [aria-label="Hashtag"]')
                                    if btn:
                                        btn.click()
                                # allow time for the hashtag UI to open and suggestions to render
                                self._sleep(1.0)
                                page.keyboard.type(tag)
                                # wait for suggestion to appear before pressing Enter
                                self._sleep(0.8)
                                page.keyboard.press('Enter')
                                # give time for the tag to commit
                                self._sleep(1.0)
                            else:
                                # fallback: append into textarea
                                cur = (el.input_value() or '')
                                el.fill((cur + ' ' + f"#{tag}").strip())
                                self._sleep(0.06)
                        except Exception:
                            cur = (el.input_value() or '')
                            el.fill((cur + ' ' + f"#{tag}").strip())
                            self._sleep(0.06)
                else:
                    # set innerText via JS
                    page.evaluate('(s, v) => { const el = document.querySelector(s); if (el) { el.innerText = v; el.dispatchEvent(new Event(\'input\', {bubbles: true})); } }', sel, caption.strip())
                    self._sleep(self.action_delay)
                    # then tag via hashtag button flow (query once)
                    btn = page.query_selector('#web-creation-caption-hashtag-button, button[aria-label="Hashtag"], [aria-label="Hashtag"]')
                    for t in tags:
                        tag = t.strip().lstrip('#')
                        try:
                            if btn:
                                try:
                                    btn.click()
                                except Exception:
                                    btn = page.query_selector('#web-creation-caption-hashtag-button, button[aria-label="Hashtag"], [aria-label="Hashtag"]')
                                    if btn:
                                        btn.click()
                                # allow time for the hashtag UI to open and suggestions to render
                                self._sleep(1.0)
                                page.keyboard.type(tag)
                                # wait for suggestion to appear before pressing Enter
                                self._sleep(0.8)
                                page.keyboard.press('Enter')
                                # give time for the tag to commit
                                self._sleep(1.0)
                            else:
                                page.evaluate('(s, v) => { const el = document.querySelector(s); if (el) { el.innerText = (el.innerText || "") + " " + v; el.dispatchEvent(new Event(\'input\', {bubbles: true})); } }', sel, f"#{tag}")
                                self._sleep(0.06)
                        except Exception:
                            page.evaluate('(s, v) => { const el = document.querySelector(s); if (el) { el.innerText = (el.innerText || "") + " " + v; el.dispatchEvent(new Event(\'input\', {bubbles: true})); } }', sel, f"#{tag}")
                            self._sleep(0.06)
                self._sleep(self.action_delay)
                return True
            except Exception:
                continue
        return False

    def click_post(self):
        page = self._page
        # Prefer Button__content exact matches
        try:
            for sel in ['.Button__content.Button__content--shape-default.Button__content--size-large.Button__content--type-primary.Button__content--loading-false', '.Button__content.Button__content--type-primary']:
                el = page.query_selector(f'{sel} >> text=Đăng')
                if el:
                    el.evaluate('(e)=>{ const b = e.closest("button, [role=\\"button\\"], a"); (b||e).click(); }')
                    self._sleep(self.action_delay)
                    return True
        except Exception as e:
            try:
                print('click_post preferred selectors error:', repr(e))
            except Exception:
                pass

        # Fallback search for visible text 'post'
        try:
            el = page.query_selector("xpath=//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'dang') and (self::div or self::button or self::span or self::a)]")
            if el:
                el.evaluate('(e)=>{ const b = e.closest("button, [role=\\\"button\\\"], a"); (b||e).click(); }')
                self._sleep(self.action_delay)
                return True
        except Exception as e:
            try:
                print('click_post preferred selectors error:', repr(e))
            except Exception:
                pass
        return False

    def click_post_confirmation(self):
        page = self._page
        try:
            btn = page.query_selector('button.TUXButton.TUXButton--primary, button.TUXButton--primary')
            if btn:
                txt = btn.inner_text().strip().lower()
                if 'post now' in txt or "đăng ngay" in txt:
                    self._sleep(0.12)
                    btn.click()
                    self._sleep(self.action_delay)
                    return True
        except Exception:
            pass
        # xpath fallback
        try:
            xp = "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'dang ngay')]"
            h = page.query_selector(f'xpath={xp}')
            if h:
                h.click()
                self._sleep(self.action_delay)
                return True
        except Exception:
            pass
        return False

    def upload(self, video_path: str, caption: str = '', tags: Optional[Union[List[str], str]] = None, cookies_path: Optional[str] = None, wait_times: dict = None) -> bool:
        # Start browser if needed
        if not self._page:
            self.start()
        send_discord_message(f"🚀 TikTok upload starting: {os.path.basename(video_path)}")

        page = self._page
        cookies_path =os.path.join(cookies_dir, cookies_path) if cookies_path else os.path.join(cookies_dir, 'DemNgheChuyen.json')
        if cookies_path:
            try:
                self.load_cookies(cookies_path)
                self._sleep(self.action_delay)
                page.reload()
                self._sleep(self.action_delay)
                send_discord_message(f"🗂️ Cookies applied from {os.path.basename(cookies_path)}")
            except Exception:
                send_discord_message(f"⚠️ Cookie reload failed for {os.path.basename(cookies_path)}")

        page.goto(self.UPLOAD_URL)
        self._sleep(self.action_delay)

        # attach file - wait for the file input to appear (page may render it asynchronously)
        file_input = None
        try:
            file_input = page.wait_for_selector('input[type=file]', timeout=10000)
        except Exception:
            # fallback: try a few times with small delays
            for _ in range(6):
                file_input = page.query_selector('input[type=file]')
                if file_input:
                    break
                self._sleep(self.action_delay)

        if not file_input:
            raise RuntimeError('Upload input not found; are you logged in?')

        # attach file via the file input handle
        file_input.set_input_files(str(Path(video_path).resolve()))
        self._sleep(self.action_delay)

        # wait for upload
        uploaded = self.wait_for_upload_complete(timeout=wait_times.get('upload', 300) if wait_times else 300)
        send_discord_message(f"📤 Upload progress indicator {'reached' if uploaded else 'did not reach'} completion for {os.path.basename(video_path)}")

        # clear filename-like text and then type caption/tags
        self.clear_filename_and_field_with_backspaces(video_path)
        # normalize tags input: allow comma-separated string or list
        tags_list: List[str] = []
        try:
            if tags:
                tags_list = self._parse_tags_input(tags)
                # persist new tags for helper suggestions
                try:
                    self._merge_and_save_tags(tags_list)
                except Exception:
                    pass
        except Exception:
            tags_list = []

        self.set_caption_and_tags(caption, tags_list or [])

        # wait for music check
        music_ok = self.wait_for_music_clear(timeout=wait_times.get('music', 120) if wait_times else 120)
        send_discord_message(f"🎵 Music check status: {'OK' if music_ok else 'Not OK'}")
        if not music_ok:
            # do not auto-publish
            send_discord_message("🚫 Music requirement blocked TikTok upload")
            return False

        # click post
        clicked = self.click_post()
        if clicked:
            # try confirmation
            self._sleep(self.action_delay)
            self.click_post_confirmation()
            send_discord_message("✅ TikTok post action clicked")
        # allow server to process
        self._sleep(5)
        send_discord_message("🏁 TikTok upload flow completed")
        return True


# CLI entry: run upload in a separate process to avoid Playwright sync/async conflicts
if __name__ == '__main__':
    import argparse
    import sys

    parser = argparse.ArgumentParser(description='TikTok uploader CLI')
    parser.add_argument('--video', required=True, help='Path to video file')
    parser.add_argument('--caption', default='', help='Caption/text')
    parser.add_argument('--tags', default='', help='Comma-separated tags')
    parser.add_argument('--cookies', default=None, help='Cookies filename inside Cookies/ directory')
    parser.add_argument('--no-headless', action='store_true', help='Run browser with visible UI')

    args = parser.parse_args()
    tags = args.tags.split(',') if args.tags else []
    uploader = TikTokUploader(headless=not args.no_headless)
    try:
        ok = False
        try:
            ok = uploader.upload(args.video, caption=args.caption, tags=tags, cookies_path=args.cookies)
        except Exception as e:
            print('Upload failed:', e, file=sys.stderr)
            ok = False
        sys.exit(0 if ok else 2)
    finally:
        try:
            uploader.stop()
        except Exception:
            pass
# if __name__ == '__main__':
#     uploader = TikTokUploader(headless=False)
#     try:
#         ok = uploader.upload(r'Bac_thay_dau_bep_Tap_7.mp4', caption='Bậc thầy đầu bếp tập 7', tags=[ "xuhuong","phimhay","reviewphim","phimhaymoingay","phimngantrungquoc"], cookies_path='DemNgheChuyen.json')
#         print('Upload result:', ok)
#     finally:
#         try:
#             uploader.stop()
#         except Exception:
#             pass
