import discord
from discord.ext import commands
import requests
import os
import json
from datetime import datetime
import aiohttp
import asyncio
import subprocess
import tempfile
import shutil
import mimetypes
import base64
from dotenv import load_dotenv

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BOT_DIR, ".env"))

API_BASE = "http://tts-audio:8000/generate_video_task"


async def http_get(url: str, params: dict | None = None, timeout: int = 60):
    """Async GET helper that returns (status, parsed_json_or_text)."""
    timeout_obj = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=timeout_obj) as session:
        async with session.get(url, params=params) as resp:
            text = await resp.text()
            try:
                j = await resp.json()
                return resp.status, j
            except Exception:
                return resp.status, text


async def http_post(url: str, params: dict | None = None, timeout: int = 60):
    """Async POST helper that returns (status, parsed_json_or_text)."""
    timeout_obj = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=timeout_obj) as session:
        # Gửi params qua query string cho FastAPI Query parameters
        async with session.post(url, params=params) as resp:
            text = await resp.text()
            try:
                j = await resp.json()
                return resp.status, j
            except Exception:
                return resp.status, text


class TaskStatusView(discord.ui.View):
    def __init__(self, task_id: str):
        super().__init__(timeout=None)
        self.task_id = task_id

    @discord.ui.button(label="Check status", style=discord.ButtonStyle.primary)
    async def check_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            API = "http://tts-audio:8000/task_status"
            params = {"task_id": self.task_id}
            status, data = await http_get(API, params=params)
            if status == 200 and isinstance(data, dict):
                msg = (
                    f"📋 Task `{self.task_id}`\n"
                    f"Status: **{data.get('status')}**\n"
                    f"Progress: **{data.get('progress', 0)}%**\n"
                    f"Created: {data.get('created_at')}\n"
                )
            else:
                msg = f"⚠️ Không lấy được trạng thái (HTTP {status}): {data}"
        except Exception as e:
            msg = f"⚠️ Lỗi khi kiểm tra trạng thái: {e}"

        await interaction.response.send_message(msg, ephemeral=True)


def parse_bg_and_voice(text: str | None) -> tuple[str, str]:
    """Parse a multi-line input that may contain background track(s) and a voice instruction.

    Rules:
    - Lines starting with "voice:" or "v:" (case-insensitive) set the voice value.
    - Lines containing ".wav" are treated as background filenames (first match used).
    - If no explicit markers, first non-empty line -> bg_choice, second non-empty line -> voice.
    Returns (bg_choice, voice) where either may be empty string.
    """
    if not text:
        return "", ""
    # Accept multiple formats: multi-line, comma-separated, or key=value/key:val pairs.
    if not text:
        return "", ""
    import re
    # Split by newline or comma so a single-line "a=b, c=d" works too
    tokens = [t.strip() for t in re.split(r"[\n,]", text) if t.strip()]
    bg = ""
    voice = ""

    def strip_quotes(s: str) -> str:
        s = s.strip()
        if (s.startswith("\"") and s.endswith("\"")) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1]
        return s

    # First pass: explicit key=value or key:val tokens
    for tok in tokens:
        low = tok.lower()
        if "=" in tok or ":" in tok:
            if "=" in tok:
                k, v = tok.split("=", 1)
            else:
                k, v = tok.split(":", 1)
            k = k.strip().lower()
            v = strip_quotes(v)
            if k in ("voice", "v") and v:
                voice = v
                continue
            if k in ("bg", "bg_choice", "background", "bg_track", "track") and v:
                if not bg:
                    bg = v
                continue
        # If token looks like a filename, accept as bg
        lowtok = tok.lower()
        if ".wav" in lowtok or lowtok.endswith(".mp3"):
            if not bg:
                bg = strip_quotes(tok)
            continue

    # Fallback: first token -> bg, second token -> voice
    if not bg and tokens:
        if ".wav" in tokens[0].lower() or tokens[0].lower().startswith("bg"):
            bg = strip_quotes(tokens[0])
        else:
            # if first token is not clearly a file, still allow it as bg
            bg = strip_quotes(tokens[0])
    if not voice and len(tokens) >= 2:
        # try to pick a token that looks like a voice spec
        for t in tokens[1:]:
            lt = t.lower()
            if lt.startswith("voice") or lt.startswith("v:") or lt.startswith("v=") or not lt.endswith('.wav'):
                # parse potential key=val
                if "=" in t or ":" in t:
                    if "=" in t:
                        _, v = t.split("=", 1)
                    else:
                        _, v = t.split(":", 1)
                    voice = strip_quotes(v)
                    break
                else:
                    voice = strip_quotes(t)
                    break
    return bg or "", voice or ""


def parse_bg_voice_and_summary(text: str | None) -> tuple[str, str, bool, bool]:
    """Parse multi-line input into (bg_choice, voice, include_summary, force_refresh).

    Recognizes lines like `include_summary:true`/`summary:false` and `force_refresh:true` (case-insensitive).
    Falls back to: first non-empty line = bg_choice, second = voice.
    Returns `force_refresh` as False by default unless specified.
    """
    bg, voice = parse_bg_and_voice(text)
    include_summary = True
    force_refresh = False
    if not text:
        return bg, voice, include_summary, force_refresh
    import re
    tokens = [t.strip() for t in re.split(r"[\n,]", text) if t.strip()]
    for tok in tokens:
        low = tok.lower()
        # accept include_summary:true or include_summary=true or summary=true
        if "include_summary" in low or low.startswith("summary") or low.startswith("inc"):
            if "=" in tok or ":" in tok:
                if "=" in tok:
                    _, val = tok.split("=", 1)
                else:
                    _, val = tok.split(":", 1)
                val = val.strip().lower().strip('"').strip("'")
                if val in ("false", "0", "no", "n"):
                    include_summary = False
                else:
                    include_summary = True
            else:
                # bare token like 'include_summary' -> True
                include_summary = True
            continue

        # accept force_refresh:true/false or refresh:true/false
        if "force_refresh" in low or low.startswith("refresh"):
            if "=" in tok or ":" in tok:
                if "=" in tok:
                    _, val = tok.split("=", 1)
                else:
                    _, val = tok.split(":", 1)
                val = val.strip().lower().strip('"').strip("'")
                if val in ("true", "1", "yes", "y"):
                    force_refresh = True
                else:
                    force_refresh = False
            else:
                # bare token like 'force_refresh' -> True
                force_refresh = True
            continue

    return bg, voice, include_summary, force_refresh


def sample_bg_voice_templates() -> str:
    """Return a helpful multi-line sample for the combined input field.

    The returned string contains a few example templates users can copy/edit:
    - background file + voice + include_summary
    - voice only
    - background only
    """
    return (
        "# Examples (edit as needed):\n"
        "# 1) Background + voice + include summary:\n"
        "bg_song.wav\nbg=bg_song.wav\nvoice=echo\ninclude_summary=true\n\n"
        "# 2) Voice only (no background):\n"
        "voice=echo\ninclude_summary=false\n\n"
        "# 3) Background only (default include summary):\n"
        "my_bg_track.wav\n"
    )


def sanitize_label(s: str) -> str:
    """Ensure Discord select/button labels are 1-100 chars.

    - Trim whitespace
    - Replace empty labels with '<unnamed>'
    - Truncate to 100 chars (append '...' when truncated)
    """
    if s is None:
        s = ""
    lbl = str(s).strip()
    if not lbl:
        lbl = "<unnamed>"
    if len(lbl) > 100:
        lbl = lbl[:97] + "..."
    return lbl


def sanitize_value(s: str) -> str:
    """Make a safe SelectOption `value` for Discord API.

    Rules:
    - Remove control characters (including newlines).
    - Trim surrounding whitespace.
    - Ensure length is between 1 and 100 characters (Discord limit for option value).
    - If empty after cleaning, return '<unnamed>'.
    """
    if s is None:
        s = ""
    v = str(s)
    # remove control characters
    v = "".join(ch for ch in v if ord(ch) >= 32)
    v = v.strip()
    if not v:
        return "<unnamed>"
    if len(v) > 100:
        # try to preserve file extension if present
        base, ext = os.path.splitext(v)
        ext = ext or ""
        keep = 100 - len(ext)
        if keep <= 0:
            return v[:100]
        return base[:keep] + ext
    return v

# --- Form Modal ---
class VideoTaskForm(discord.ui.Modal, title="🎬 Gửi yêu cầu tạo video (Tiktok/General)"):
    video_url = discord.ui.TextInput(
        label="Video URL(s)",
        style=discord.TextStyle.paragraph,
        placeholder="Nhập 1 hoặc nhiều link video, cách nhau bằng dấu phẩy hoặc xuống dòng",
        required=False,
    )
    story_url = discord.ui.TextInput(label="Story URL", placeholder="Nhập đường dẫn truyện (bắt buộc)", required=True)
    story_name = discord.ui.TextInput(label="Tiêu đề", required=False, placeholder="Tùy chọn")
    bg_choice = discord.ui.TextInput(label="Background track (selected)", required=False, placeholder="Để trống nếu không dùng nhạc nền\nHỗ trợ: bg=track.wav, voice=echo, include_summary=true, force_refresh=true")

    def __init__(self, selected_bg: str | None = None):
        super().__init__()
        if selected_bg:
            try:
                # set default value for bg_choice input if provided
                self.bg_choice.default = selected_bg
            except Exception:
                pass

    async def on_submit(self, interaction: discord.Interaction):
        # Lấy và làm sạch input
        video_raw = self.video_url.value.strip()
        story = self.story_url.value.strip()
        if not story:
            await interaction.response.send_message("❌ `story_url` là bắt buộc!", ephemeral=True)
            return

        # Hợp nhất danh sách video: tách theo dòng hoặc dấu phẩy
        video_list = [v.strip() for v in video_raw.replace("\n", ",").split(",") if v.strip()]
        video_combined = ",".join(video_list)

        # parse combined bg/voice/include_summary/force_refresh single input
        bg_choice_val, voice_val, include_summary, force_refresh = parse_bg_voice_and_summary(self.bg_choice.value or "")
        params = {
            "video_url": video_combined,
            "story_url": story,
            "Title": self.story_name.value.strip(),
            "bg_choice": bg_choice_val,
            "include_summary": "true" if include_summary else "false",
            "force_refresh": "true" if force_refresh else "false",
        }
        if voice_val:
            params["voice"] = voice_val

        try:
            API_ENDPOINT = "http://tts-audio:8000/generate_video_task"
            r = requests.get(API_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()

            # Thử parse JSON
            try:
                data = r.json()
                msg = f"✅ API phản hồi:\n```json\n{data}\n```"
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"

            await interaction.response.send_message(msg[:2000], ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)

@bot.tree.command(name="clear_story_cache", description="🧹 Xóa cache truyện (audio, parts, outputs). Giữ video cache nếu muốn")
async def clear_story_cache(interaction: discord.Interaction):
    """Slash command: open a modal to request clearing cache for a story URL."""
    class ClearStoryCacheForm(discord.ui.Modal, title="🧹 Xóa Cache Truyện"):
        story_url = discord.ui.TextInput(
            label="Story URL (link truyện)",
            style=discord.TextStyle.paragraph,
            placeholder="Nhập URL truyện cần xóa cache",
            required=True,
        )
        preserve_video_cache = discord.ui.TextInput(
            label="Giữ video cache? (True/False)",
            style=discord.TextStyle.short,
            placeholder="True",
            required=False,
            max_length=5,
        )

        def __init__(self):
            super().__init__()

        async def on_submit(self2, interaction: discord.Interaction):
            story = self2.story_url.value.strip()
            preserve_raw = (self2.preserve_video_cache.value or "True").strip().lower()
            preserve = True if preserve_raw in ("1", "true", "yes", "y") else False

            params = {"story_url": story, "preserve_video_cache": preserve}
            API_ENDPOINT = "http://tts-audio:8000/clear_story_cache"
            try:
                r = requests.post(API_ENDPOINT, params=params, timeout=30)
                r.raise_for_status()
                try:
                    data = r.json()
                    deleted = data.get("deleted", [])
                    skipped = data.get("skipped", [])
                    errors = data.get("errors", [])
                    msg = (
                        f"✅ Đã xóa {len(deleted)} file.\n"
                        f"⚠️ Bỏ qua {len(skipped)} file.\n"
                        f"❗ Lỗi: {len(errors)} mục (xem chi tiết trong phản hồi).\n"
                    )
                    # Keep response reasonable size
                    details = []
                    if deleted:
                        details.append("Deleted: " + ", ".join([os.path.basename(p) for p in deleted[:10]]))
                    if skipped:
                        details.append("Skipped: " + ", ".join([os.path.basename(p) for p in skipped[:10]]))
                    if errors:
                        details.append("Errors: " + ", ".join([e.get('file','?') for e in errors[:10]]))
                    full_msg = msg + "\n" + "\n".join(details)
                except Exception:
                    # Fallback: return raw text response
                    full_msg = "✅ API phản hồi:\n" + (r.text if isinstance(r.text, str) else str(r.text))

                await interaction.response.send_message(full_msg[:2000], ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)

    await interaction.response.send_modal(ClearStoryCacheForm())


# --- New: Process Series (multi-episode) slash command and modal ---
class ProcessSeriesForm(discord.ui.Modal, title="📥 Process Series"):
    start_url = discord.ui.TextInput(label="Start URL (tập 1)", style=discord.TextStyle.short, required=True)
    titles = discord.ui.TextInput(label="Tiêu đề (tùy chọn)", style=discord.TextStyle.short, required=False)
    max_episodes = discord.ui.TextInput(label="Số tập tối đa (tùy chọn)", style=discord.TextStyle.short, required=False, placeholder="ví dụ: 10")
    render_mode = discord.ui.TextInput(
        label="Render",
        style=discord.TextStyle.short,
        required=False,
        placeholder="Chế độ render (0=cả 2, 1=chỉ thuyết minh, 2=chỉ phụ đề)"
    )
    render_full = discord.ui.TextInput(
        label="Render full (0=không, 1=có)",
        style=discord.TextStyle.short,
        required=False,
        placeholder="0"
    )

    async def on_submit(self, interaction: discord.Interaction):
        start = self.start_url.value.strip()
        t = self.titles.value.strip()
        max_ep_raw = (self.max_episodes.value or '').strip()
        params = {"start_url": start, "title": t, "run_in_background": "true"}
        if max_ep_raw:
            try:
                params['max_episodes'] = int(max_ep_raw)
            except Exception:
                params['max_episodes'] = max_ep_raw

        # Render mode: 0=both (default), 1=narration only, 2=subtitles only
        mode_raw = (self.render_mode.value or '').strip()
        try:
            mode = int(mode_raw) if mode_raw != '' else 0
        except Exception:
            lr = mode_raw.lower()
            if lr in ("narration", "nar", "1"):
                mode = 1
            elif lr in ("subtitles", "subtitle", "sub", "2"):
                mode = 2
            else:
                mode = 0

        if mode == 0:
            params['narration_enabled'] = 1
            params['with_subtitles'] = "true"
        elif mode == 1:
            params['narration_enabled'] = 1
            params['with_subtitles'] = "false"
        elif mode == 2:
            params['narration_enabled'] = 0
            params['with_subtitles'] = "true"
        else:
            params['narration_enabled'] = 1
            params['with_subtitles'] = "true"

        # Render full flag: accept 0/1 or textual true/false
        render_full_raw = (self.render_full.value or '').strip()
        try:
            render_full = int(render_full_raw) if render_full_raw != '' else 0
        except Exception:
            lr = render_full_raw.lower()
            render_full = 1 if lr in ("1", "true", "yes", "y") else 0

        params['render_full'] = "true" if render_full == 1 else "false"

        API = "http://tts-audio:8000/process_series"
        try:
            r = requests.post(API, params=params, timeout=30)
            r.raise_for_status()
            try:
                data = r.json()
                task = data.get('task_id') or data.get('task') or data
                msg = f"✅ Đã khởi tạo task: {task}\n\n```json\n{data}\n```"
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"
            await interaction.response.send_message(msg[:2000], ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)


@bot.tree.command(name="process_series", description="Download series, generate VN SRTs, concat and split")
async def process_series(interaction: discord.Interaction):
    """Slash command mở form ProcessSeriesForm.

    Thỉnh thoảng Discord trả về lỗi 10062 (Unknown interaction) nếu
    interaction đã hết hạn hoặc đã được ack ở nơi khác. Bọc trong
    try/except để không làm command crash toàn bộ.
    """
    try:
        await interaction.response.send_modal(ProcessSeriesForm())
    except discord.errors.NotFound:
        # Interaction đã hết hạn hoặc không còn hợp lệ; báo nhẹ cho user nếu còn gửi được.
        try:
            if interaction.followup:
                await interaction.followup.send(
                    "⚠️ Interaction đã hết hạn, hãy thử gọi lại /process_series.",
                    ephemeral=True,
                )
        except Exception:
            pass
    except Exception as e:
        # Bắt mọi lỗi khác để tránh CommandInvokeError noisy.
        try:
            if interaction.followup:
                await interaction.followup.send(f"⚠️ Lỗi khi mở form: {e}", ephemeral=True)
        except Exception:
            pass


class ProcessSeriesEpisodesForm(discord.ui.Modal, title="📥 Process Series (Episodes Range)"):
    start_url = discord.ui.TextInput(label="Start URL (tập 1)", style=discord.TextStyle.short, required=True)
    titles = discord.ui.TextInput(label="Tiêu đề (tùy chọn)", style=discord.TextStyle.short, required=False)
    episodes = discord.ui.TextInput(label="Episodes range (eg. 1-5)", style=discord.TextStyle.short, required=False, placeholder="Ví dụ: 1-5")
    render_mode = discord.ui.TextInput(
        label="Render",
        style=discord.TextStyle.short,
        required=False,
        placeholder="Chế độ render (0=cả 2, 1=chỉ thuyết minh, 2=chỉ phụ đề)"
    )
    render_full = discord.ui.TextInput(
        label="Render full (0=không, 1=có)",
        style=discord.TextStyle.short,
        required=False,
        placeholder="0"
    )

    async def on_submit(self, interaction: discord.Interaction):
        start = self.start_url.value.strip()
        t = self.titles.value.strip()
        episodes_raw = (self.episodes.value or '').strip()
        params = {"start_url": start, "title": t, "run_in_background": "true"}
        if episodes_raw:
            params['episodes'] = episodes_raw

        # Render mode handling (same as ProcessSeriesForm)
        mode_raw = (self.render_mode.value or '').strip()
        try:
            mode = int(mode_raw) if mode_raw != '' else 0
        except Exception:
            lr = mode_raw.lower()
            if lr in ("narration", "nar", "1"):
                mode = 1
            elif lr in ("subtitles", "subtitle", "sub", "2"):
                mode = 2
            else:
                mode = 0

        if mode == 0:
            params['narration_enabled'] = 1
            params['with_subtitles'] = "true"
        elif mode == 1:
            params['narration_enabled'] = 1
            params['with_subtitles'] = "false"
        elif mode == 2:
            params['narration_enabled'] = 0
            params['with_subtitles'] = "true"
        else:
            params['narration_enabled'] = 1
            params['with_subtitles'] = "true"

        render_full_raw = (self.render_full.value or '').strip()
        try:
            render_full = int(render_full_raw) if render_full_raw != '' else 0
        except Exception:
            lr = render_full_raw.lower()
            render_full = 1 if lr in ("1", "true", "yes", "y") else 0
        params['render_full'] = "true" if render_full == 1 else "false"

        API = "http://tts-audio:8000/process_series_episodes"
        try:
            r = requests.post(API, params=params, timeout=30)
            r.raise_for_status()
            try:
                data = r.json()
                task = data.get('task_id') or data.get('task') or data
                msg = f"✅ Đã khởi tạo task: {task}\n\n```json\n{data}\n```"
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"
            await interaction.response.send_message(msg[:2000], ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)


@bot.tree.command(name="process_series_episodes", description="Process a series by episode range (eg. 1-5)")
async def process_series_episodes(interaction: discord.Interaction):
    await interaction.response.send_modal(ProcessSeriesEpisodesForm())


# --- New: Delete Episode Assets slash command ---
class DeleteEpisodeAssetsForm(discord.ui.Modal, title="🧹 Xóa thành phần của tập"):
    title = discord.ui.TextInput(label="Tên phim/series", style=discord.TextStyle.short, required=True)
    episode_number = discord.ui.TextInput(label="Số tập (1,2,...)", style=discord.TextStyle.short, required=True)
    components_nums = discord.ui.TextInput(
        label="Thành phần (mã số, cách nhau dấu ,)",
        style=discord.TextStyle.short,
        required=False,
        placeholder="Ví dụ: 1,3,6 (1 raw, 2 srt_zh, 3 srt_vi, 4 nar_flac, 5 burned, 6 nar_video)"
    )
    episode_numbers = discord.ui.TextInput(
        label="Xóa nhiều tập (danh sách, cách nhau ,)",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="Ví dụ: 0,1,2,5 (0 = xóa video final)"
    )

    async def on_submit(self, interaction: discord.Interaction):
        ttl = (self.title.value or '').strip()
        ep_raw = (self.episode_number.value or '').strip()
        comps = (self.components_nums.value or '').strip()
        eps_list = (self.episode_numbers.value or '').strip()

        # Validate episode number
        try:
            ep = int(ep_raw)
        except ValueError:
            await interaction.response.send_message("⚠️ `Số tập` phải là số nguyên.", ephemeral=True)
            return

        params = {
            "title": ttl,
            "episode_number": ep,
        }
        if comps:
            params["components_nums"] = comps
        if eps_list:
            params["episode_numbers"] = eps_list

        API = "http://tts-audio:8000/delete_episode_assets"
        try:
            r = requests.delete(API, params=params, timeout=30)
            r.raise_for_status()
            try:
                data = r.json()
                deleted = data.get('deleted', {})
                not_found = data.get('not_found', {})
                invalid = data.get('invalid_components', [])
                msg = (
                    f"✅ Đã yêu cầu xoá cho tập {ep} của '{ttl}'.\n"
                    f"🗑️ Xóa: {len(deleted)}\n"
                    f"⚠️ Không tìm thấy: {len(not_found)}\n"
                    f"❗ Không hợp lệ: {len(invalid)}"
                )
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"
            await interaction.response.send_message(msg[:1900], ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)


@bot.tree.command(name="delete_episode_assets", description="Xóa asset của một tập theo mã thành phần")
async def slash_delete_episode_assets(interaction: discord.Interaction):
    await interaction.response.send_modal(DeleteEpisodeAssetsForm())


class VideoTaskFormYouTube(discord.ui.Modal, title="🎬 Gửi yêu cầu tạo video (YouTube)"):
    # YouTube endpoint expects only story_url (per existing API) — keep title metadata
    story_url = discord.ui.TextInput(label="Story URL", placeholder="Nhập đường dẫn truyện (bắt buộc)", required=True)
    story_name = discord.ui.TextInput(label="Tiêu đề", required=False, placeholder="Tùy chọn")
    bg_choice = discord.ui.TextInput(
        label="Background track (selected)",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="Để trống nếu không dùng nhạc. Hỗ trợ nhiều dòng: bg=track.wav\\nvoice=echo\\ninclude_summary=true\\nforce_refresh=true",
    )

    def __init__(self, selected_bg: str | None = None):
        super().__init__()
        if selected_bg:
            try:
                # If a background was selected from the chooser, prefill it
                # and also include the forced OpenAI voice and default summary flag.
                self.bg_choice.default = f"{selected_bg}\nvoice=echo\ninclude_summary=true\n"
            except Exception:
                pass
        else:
            # Prefill with voice=echo and helpful templates when no bg selected
            try:
                self.bg_choice.default = "voice=echo\ninclude_summary=true\n\n" + sample_bg_voice_templates()
            except Exception:
                pass

    async def on_submit(self, interaction: discord.Interaction):
        story = self.story_url.value.strip()
        if not story:
            await interaction.response.send_message("❌ `story_url` là bắt buộc!", ephemeral=True)
            return

        params = {
            "story_url": story,
            "Title": self.story_name.value.strip(),
        }
        # parse combined bg/voice/include_summary/force_refresh single input
        bg_choice_val, voice_val, include_summary, force_refresh = parse_bg_voice_and_summary(self.bg_choice.value or "")
        params["bg_choice"] = bg_choice_val
        if voice_val:
            params["voice"] = voice_val
        params["include_summary"] = "true" if include_summary else "false"
        params["force_refresh"] = "true" if force_refresh else "false"

        try:
            API_ENDPOINT = "http://108.108.1.4:8005/generate_video_task_youtube"
            r = requests.get(API_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()
            try:
                data = r.json()
                msg = f"✅ API phản hồi:\n```json\n{data}\n```"
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"
            await interaction.response.send_message(msg[:2000], ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)


class FacebookDownloadForm(discord.ui.Modal, title="📥 Tải video Facebook và chia nhỏ"):
    fb_url = discord.ui.TextInput(label="Facebook video URL", placeholder="Dán link Facebook video (bắt buộc)", required=True)
    Title = discord.ui.TextInput(label="Tiêu đề (để ghép vào split)", required=False)
    part_time = discord.ui.TextInput(label="Thời lượng part (giây)", required=False, placeholder="3600")
    avoid_copyright = discord.ui.TextInput(label="Apply tiny transform? (true/false)", required=False, placeholder="true")

    async def on_submit(self, interaction: discord.Interaction):
        fb_url = self.fb_url.value.strip()
        if not fb_url:
            await interaction.response.send_message("❌ `fb_url` là bắt buộc!", ephemeral=True)
            return

        params = {
            "fb_url": fb_url,
            "Title": (self.Title.value or "").strip(),
        }
        # parse part_time
        try:
            pt = int((self.part_time.value or "").strip()) if (self.part_time.value or "").strip() else 3600
        except Exception:
            pt = 3600
        params["part_time"] = pt

        ac = (self.avoid_copyright.value or "").strip().lower()
        params["avoid_copyright"] = "true" if ac in ("true", "1", "yes", "y") or ac == "" else "false"

        try:
            API_ENDPOINT = "http://tts-audio:8000/download_facebook_and_split"
            r = requests.post(API_ENDPOINT, params=params, timeout=120)
            r.raise_for_status()
            try:
                data = r.json()
                # keep message short enough for Discord
                msg = f"✅ Hoàn tất. Files:\n{data.get('files') or data}"
            except Exception:
                # fallback: return raw text in a short message
                raw = (r.text or "").strip()
                snippet = raw[:1500] + ("..." if len(raw) > 1500 else "")
                msg = f"✅ API phản hồi:\n{snippet}"
            await interaction.response.send_message(msg[:1900], ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)


class TikTokLargeVideoForm(discord.ui.Modal, title="🎬 TikTok Large Video"):
    video_url = discord.ui.TextInput(
        label="Video URL(s) (tùy chọn)",
        style=discord.TextStyle.paragraph,
        placeholder="Để trống sẽ lấy random từ cache. Hoặc nhập link, cách nhau bằng dấu phẩy",
        required=False,
    )
    story_url = discord.ui.TextInput(label="Story URL", placeholder="Nhập đường dẫn truyện (bắt buộc)", required=True)
    story_name = discord.ui.TextInput(label="Tiêu đề", required=False, placeholder="Tùy chọn")
    start_from_part = discord.ui.TextInput(
        label="Bắt đầu từ part (để trống = từ đầu)",
        required=False,
        placeholder="Ví dụ: 3 (để tiếp tục từ part 3)"
    )
    bg_choice = discord.ui.TextInput(
        label="Background track (selected)",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="Để trống nếu không dùng nhạc. Hỗ trợ nhiều dòng: bg=track.wav\\nvoice=echo",
    )

    def __init__(self, selected_bg: str | None = None):
        super().__init__()
        if selected_bg:
            try:
                # If a background was selected from the chooser, prefill it
                # and also include the forced OpenAI voice and default summary flag.
                self.bg_choice.default = f"{selected_bg}\nvoice=echo\ninclude_summary=true\n"
            except Exception:
                pass
        else:
            # Prefill with voice=echo and helpful templates when no bg selected
            try:
                self.bg_choice.default = "voice=echo\ninclude_summary=true\n\n" + sample_bg_voice_templates()
            except Exception:
                pass

    async def on_submit(self, interaction: discord.Interaction):
        # Lấy và làm sạch input
        video_raw = self.video_url.value.strip()
        story = self.story_url.value.strip()
        if not story:
            await interaction.response.send_message("❌ `story_url` là bắt buộc!", ephemeral=True)
            return

        # Hợp nhất danh sách video: tách theo dòng hoặc dấu phẩy
        video_list = [v.strip() for v in video_raw.replace("\n", ",").split(",") if v.strip()]
        video_combined = ",".join(video_list)

        bg_choice_val, voice_val, include_summary, force_refresh = parse_bg_voice_and_summary(self.bg_choice.value or "")
        params = {
            "video_url": video_combined,
            "story_url": story,
            "title": self.story_name.value.strip(),
            "bg_choice": bg_choice_val,
            "include_summary": "true" if include_summary else "false",
            "force_refresh": "true" if force_refresh else "false",
        }
        if voice_val:
            params["voice"] = voice_val

        # Xử lý start_from_part
        start_part_value = (self.start_from_part.value or "").strip()
        if start_part_value:
            try:
                params["start_from_part"] = int(start_part_value)
            except ValueError:
                await interaction.response.send_message(
                    f"⚠️ `start_from_part` phải là số nguyên. Giá trị nhận được: '{start_part_value}'",
                    ephemeral=True
                )
                return

        try:
            API_ENDPOINT = "http://tts-audio:8000/render_tiktok_large_video"
            r = requests.post(API_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()

            # Thử parse JSON
            try:
                data = r.json()
                task_id = data.get('task_id', 'N/A')
                msg = f"✅ Đã tạo task TikTok Large Video!\n📋 Task ID: `{task_id}`\n\n```json\n{data}\n```"
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"

            await interaction.response.send_message(msg[:2000], ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)


class TikTokLargeVideoGeminiForm(discord.ui.Modal, title="🎬 TikTok Large Video (Gemini)"):
    video_url = discord.ui.TextInput(
        label="Video URL(s) (tùy chọn)",
        style=discord.TextStyle.paragraph,
        placeholder="Để trống sẽ lấy random từ cache. Hoặc nhập link, cách nhau bằng dấu phẩy",
        required=False,
    )
    story_url = discord.ui.TextInput(label="Story URL", placeholder="Nhập đường dẫn truyện (bắt buộc)", required=True)
    story_name = discord.ui.TextInput(label="Tiêu đề", required=False, placeholder="Tùy chọn")
    start_from_part = discord.ui.TextInput(
        label="Bắt đầu từ part (để trống = từ đầu)",
        required=False,
        placeholder="Ví dụ: 3 (để tiếp tục từ part 3)"
    )
    bg_choice = discord.ui.TextInput(
        label="Background track (selected)",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="Để trống nếu không dùng nhạc. Hỗ trợ nhiều dòng: bg=track.wav\\nvoice=echo",
    )

    def __init__(self, selected_bg: str | None = None):
        super().__init__()
        if selected_bg:
            try:
                # Prefill with the selected background and default include_summary (do NOT set voice for Gemini)
                self.bg_choice.default = f"bg={selected_bg}\ninclude_summary=true\nvoice=gfemale\n"
            except Exception:
                pass
        else:
            # No background selected: prefill the combined input with voice=echo, include_summary=true and helpful templates
            try:
                # For Gemini, do not prefill a voice. Only include the summary flag and examples.
                self.bg_choice.default = "include_summary=true\nvoice=gfemale\n\n" + sample_bg_voice_templates()
            except Exception:
                pass

    async def on_submit(self, interaction: discord.Interaction):
        # Lấy và làm sạch input
        video_raw = self.video_url.value.strip()
        story = self.story_url.value.strip()
        if not story:
            await interaction.response.send_message("❌ `story_url` là bắt buộc!", ephemeral=True)
            return

        # Hợp nhất danh sách video: tách theo dòng hoặc dấu phẩy
        video_list = [v.strip() for v in video_raw.replace("\n", ",").split(",") if v.strip()]
        video_combined = ",".join(video_list)

        bg_choice_val, voice_val, include_summary, force_refresh = parse_bg_voice_and_summary(self.bg_choice.value or "")
        params = {
            "video_url": video_combined,
            "story_url": story,
            "title": self.story_name.value.strip(),
            "bg_choice": bg_choice_val,
            "include_summary": "true" if include_summary else "false",
            "force_refresh": "true" if force_refresh else "false",
            
        }
        # Do NOT pass `voice` when using Gemini backend — Gemini uses its own voice selection.
        if voice_val:
            params["voice"] = voice_val
        # Xử lý start_from_part
        start_part_value = (self.start_from_part.value or "").strip()
        if start_part_value:
            try:
                params["start_from_part"] = int(start_part_value)
            except ValueError:
                await interaction.response.send_message(
                    f"⚠️ `start_from_part` phải là số nguyên. Giá trị nhận được: '{start_part_value}'",
                    ephemeral=True
                )
                return

        try:
            API_ENDPOINT = "http://tts-audio:8000/render_tiktok_large_video_gemini"
            r = requests.post(API_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()

            # Thử parse JSON
            try:
                data = r.json()
                task_id = data.get('task_id', 'N/A')
                msg = f"✅ Đã tạo task TikTok Large Video (Gemini)!\n📋 Task ID: `{task_id}`\n\n```json\n{data}\n```"
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"

            await interaction.response.send_message(msg[:2000], ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)


class ConvertSTTForm(discord.ui.Modal, title="🔊 Convert & Subtitles (STT -> SRT -> TikTok)"):
    # Put title first (short input) so it's visible immediately in the modal
    VideoName = discord.ui.TextInput(label="Title Name", required=False, placeholder="Tùy chọn")
    video_url = discord.ui.TextInput(
        label="Video URL",
        style=discord.TextStyle.paragraph,
        placeholder="Nhập link video để tải và transcribe (bắt buộc)",
        required=True,
    )
    narration_enabled = discord.ui.TextInput(label="Thuyết minh (0=không, 1=có)", required=False, placeholder="0")

    async def on_submit(self, interaction: discord.Interaction):
        video = (self.video_url.value or "").strip()
        ttl = (self.VideoName.value or "").strip()

        if not video:
            await interaction.response.send_message("❌ `video_url` là bắt buộc!", ephemeral=True)
            return

        params = {
            "url": video,
            "title": ttl,
        }

        narr_raw = (self.narration_enabled.value or '').strip()
        if narr_raw:
            try:
                params['narration_enabled'] = 1 if int(narr_raw) == 1 else 0
            except Exception:
                params['narration_enabled'] = 0
        else:
            params['narration_enabled'] = 0

        try:
            API_ENDPOINT = "http://tts-audio:8000/convert_stt"
            r = requests.post(API_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()
            try:
                data = r.json()
                # If background, API returns task_id; otherwise a link
                if isinstance(data, dict) and data.get('task_id'):
                    task_id = data.get('task_id')
                    msg = f"✅ Đã xếp task: `{task_id}`"
                    view = TaskStatusView(task_id)
                    # Provide the task_id and a Check Status button
                    await interaction.response.send_message(msg, view=view, ephemeral=True)
                    return
                else:
                    msg = f"✅ API phản hồi:\n```json\n{data}\n```"
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"
            await interaction.response.send_message(msg[:2000], ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)


@bot.tree.command(name="convert_stt", description="Convert video -> subtitles and enqueue TikTok render (open form)")
async def slash_convert_stt(interaction: discord.Interaction):
    await interaction.response.send_modal(ConvertSTTForm())


class TikTokLargeVideoPartsForm(discord.ui.Modal, title="🎯 TikTok Large Video (Parts)"):
    video_url = discord.ui.TextInput(
        label="Video URL(s) (tùy chọn)",
        style=discord.TextStyle.paragraph,
        placeholder="Để trống sẽ lấy random từ cache. Hoặc nhập link, cách nhau bằng dấu phẩy",
        required=False,
    )
    story_url = discord.ui.TextInput(label="Story URL", placeholder="Nhập đường dẫn truyện (bắt buộc)", required=True)
    story_name = discord.ui.TextInput(label="Tiêu đề", required=False, placeholder="Tùy chọn")
    parts = discord.ui.TextInput(
        label="Danh sách part cần render (bắt buộc)",
        required=True,
        placeholder="VD: 1,3,5,7 hoặc 2,4,6"
    )
    bg_choice = discord.ui.TextInput(label="Background track (selected)", required=False, placeholder="Để trống nếu không dùng nhạc nền")

    def __init__(self, selected_bg: str | None = None):
        super().__init__()
        if selected_bg:
            try:
                # Prefill only the selected background for the Parts form
                self.bg_choice.default = selected_bg
            except Exception:
                pass

    async def on_submit(self, interaction: discord.Interaction):
        # Lấy và làm sạch input
        video_raw = self.video_url.value.strip()
        story = self.story_url.value.strip()
        parts = self.parts.value.strip()
        
        if not story:
            await interaction.response.send_message("❌ `story_url` là bắt buộc!", ephemeral=True)
            return
        
        if not parts:
            await interaction.response.send_message("❌ `parts` là bắt buộc! VD: 1,3,5", ephemeral=True)
            return

        # Hợp nhất danh sách video: tách theo dòng hoặc dấu phẩy
        video_list = [v.strip() for v in video_raw.replace("\n", ",").split(",") if v.strip()]
        video_combined = ",".join(video_list)

        bg_choice_val, voice_val, include_summary, force_refresh = parse_bg_voice_and_summary(self.bg_choice.value or "")
        params = {
            "video_url": video_combined,
            "story_url": story,
            "title": self.story_name.value.strip(),
            "bg_choice": bg_choice_val,
            "include_summary": "true" if include_summary else "false",
            "force_refresh": "true" if force_refresh else "false",
            "parts": parts,
        }
        if voice_val:
            params["voice"] = voice_val

        try:
            API_ENDPOINT = "http://tts-audio:8000/render_tiktok_large_video_parts"
            r = requests.post(API_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()

            # Thử parse JSON
            try:
                data = r.json()
                task_id = data.get('task_id', 'N/A')
                parts_list = data.get('parts_to_render', [])
                msg = f"✅ Đã tạo task TikTok Large Video (Parts)!\n📋 Task ID: `{task_id}`\n🎯 Parts: {parts_list}\n\n```json\n{data}\n```"
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"

            await interaction.response.send_message(msg[:2000], ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)


class TikTokLargeVideoNoSummaryForm(discord.ui.Modal, title="📖 TikTok Large (No Summary)"):
    video_url = discord.ui.TextInput(
        label="Video URL(s) (tùy chọn)",
        style=discord.TextStyle.paragraph,
        placeholder="Để trống sẽ lấy random từ cache. Hoặc nhập link, cách nhau bằng dấu phẩy",
        required=False,
    )
    story_url = discord.ui.TextInput(label="Story URL", placeholder="Nhập đường dẫn truyện (bắt buộc)", required=True)
    story_name = discord.ui.TextInput(label="Tiêu đề", required=False, placeholder="Tùy chọn")
    start_from_part = discord.ui.TextInput(
        label="Bắt đầu từ part (để trống = từ đầu)",
        required=False,
        placeholder="Ví dụ: 3 (để tiếp tục từ part 3)"
    )
    bg_choice = discord.ui.TextInput(
        label="Background track (selected)",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="Để trống nếu không dùng nhạc. Hỗ trợ nhiều dòng: bg=track.wav\\nvoice=echo",
    )

    def __init__(self, selected_bg: str | None = None):
        super().__init__()
        if selected_bg:
            try:
                # Prefill with the selected background and force OpenAI echo + NO summary
                self.bg_choice.default = f"{selected_bg}\nvoice=echo\ninclude_summary=false\n"
            except Exception:
                pass
        else:
            # No background selected: prefill with voice=echo, include_summary=true and helpful templates
            try:
                # default for NoSummary form should disable the summary
                self.bg_choice.default = "voice=echo\ninclude_summary=false\n\n" + sample_bg_voice_templates()
            except Exception:
                pass


class TikTokLargeVideoOpenAIEchoForm(discord.ui.Modal, title="🎧 TikTok Large (OpenAI Echo)"):
    video_url = discord.ui.TextInput(
        label="Video URL(s) (tùy chọn)",
        style=discord.TextStyle.paragraph,
        placeholder="Để trống sẽ lấy random từ cache. Hoặc nhập link, cách nhau bằng dấu phẩy",
        required=False,
    )
    story_url = discord.ui.TextInput(label="Story URL", placeholder="Nhập đường dẫn truyện (bắt buộc)", required=True)
    story_name = discord.ui.TextInput(label="Tiêu đề", required=False, placeholder="Tùy chọn")
    start_from_part = discord.ui.TextInput(
        label="Bắt đầu từ part (để trống = từ đầu)",
        required=False,
        placeholder="Ví dụ: 3 (để tiếp tục từ part 3)"
    )
    bg_choice = discord.ui.TextInput(
        label="Background track (selected)",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="Để trống nếu không dùng nhạc. Hỗ trợ nhiều dòng: bg=track.wav\\nvoice=echo",
    )

    def __init__(self, selected_bg: str | None = None):
        super().__init__()
        if selected_bg:
            try:
                # Prefill with key=value style so it's easy to edit
                self.bg_choice.default = f"bg={selected_bg}\nvoice=echo\ninclude_summary=true\n"
            except Exception:
                pass
        else:
            # No background selected: prefill with voice=echo and helpful templates
            try:
                self.bg_choice.default = "voice=echo\ninclude_summary=true\n\n" + sample_bg_voice_templates()
            except Exception:
                pass

    async def on_submit(self, interaction: discord.Interaction):
        video_raw = self.video_url.value.strip()
        story = self.story_url.value.strip()
        if not story:
            await interaction.response.send_message("❌ `story_url` là bắt buộc!", ephemeral=True)
            return

        video_list = [v.strip() for v in video_raw.replace("\n", ",").split(",") if v.strip()]
        video_combined = ",".join(video_list)

        # parse combined bg/voice/include_summary/force_refresh single input
        bg_choice_val, voice_val, include_summary, force_refresh = parse_bg_voice_and_summary(self.bg_choice.value or "")
        params = {
            "video_url": video_combined,
            "story_url": story,
            "title": self.story_name.value.strip(),
            "bg_choice": bg_choice_val,
            "include_summary": "true" if include_summary else "false",
            "force_refresh": "true" if force_refresh else "false",
        }
        if voice_val:
            params["voice"] = voice_val

        start_part_value = (self.start_from_part.value or "").strip()
        if start_part_value:
            try:
                params["start_from_part"] = int(start_part_value)
            except ValueError:
                await interaction.response.send_message(
                    f"⚠️ `start_from_part` phải là số nguyên. Giá trị nhận được: '{start_part_value}'",
                    ephemeral=True
                )
                return

        try:
            API_ENDPOINT = "http://tts-audio:8000/render_tiktok_large_video_openai_echo"
            r = requests.post(API_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()

            try:
                data = r.json()
                task_id = data.get('task_id', 'N/A')
                msg = f"✅ Đã tạo task TikTok Large Video (OpenAI echo)!\n📋 Task ID: `{task_id}`\n\n```json\n{data}\n```"
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"

            await interaction.response.send_message(msg[:2000], ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)


# --- Slash command mở form ---
@bot.tree.command(name="video_form", description="Gửi form tạo video")
async def video_form(interaction: discord.Interaction):
    # Build a Select menu listing files under discord-bot/bgaudio (max 25 options)
    bot_dir = os.path.dirname(os.path.abspath(__file__))
    bgaudio_dir = os.path.join(bot_dir, "bgaudio")
    options = []

    if os.path.isdir(bgaudio_dir):
        files = sorted(
            [f for f in os.listdir(bgaudio_dir) if f.lower().endswith('.wav')],
            key=lambda x: x.lower()
        )
        # limit to 25 options for Discord select
        for f in files[:25]:
            options.append(discord.SelectOption(label=sanitize_label(f), value=sanitize_value(f)))

    class BGSelect(discord.ui.View):
        def __init__(self, options):
            super().__init__(timeout=60)
            # add a Select with options if available and a fallback button to open modal without selection
            if options:
                sel = discord.ui.Select(placeholder="Chọn nhạc nền (tùy chọn)", options=options, min_values=0, max_values=1)
                # bind callback (use closure to access sel.values)
                async def _sel_callback(interaction: discord.Interaction):
                    selected = sel.values[0] if sel.values else None
                    await interaction.response.send_modal(VideoTaskForm(selected_bg=selected))
                sel.callback = _sel_callback
                self.add_item(sel)

            # create fallback button dynamically and bind its callback
            btn = discord.ui.Button(label="Mở form (không chọn nhạc)", style=discord.ButtonStyle.primary)
            async def _btn_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(VideoTaskForm(selected_bg=None))
            btn.callback = _btn_callback
            self.add_item(btn)

    view = BGSelect(options)
    # If there are no options, open the modal directly
    if not options:
        await interaction.response.send_modal(VideoTaskForm())
    else:
        await interaction.response.send_message("Chọn nhạc nền (tùy chọn) hoặc mở form:", view=view, ephemeral=True)


@bot.tree.command(name="video_form_youtube", description="Gửi form tạo video (YouTube endpoint)")
async def video_form_youtube(interaction: discord.Interaction):
    # Similar select behavior for YouTube form — use discord-bot/bgaudio
    bot_dir = os.path.dirname(os.path.abspath(__file__))
    bgaudio_dir = os.path.join(bot_dir, "bgaudio")
    options = []
    if os.path.isdir(bgaudio_dir):
        files = sorted(
            [f for f in os.listdir(bgaudio_dir) if f.lower().endswith('.wav')],
            key=lambda x: x.lower()
        )
        for f in files[:25]:
            options.append(discord.SelectOption(label=sanitize_label(f), value=sanitize_value(f)))

    class BGSelectYT(discord.ui.View):
        def __init__(self, options):
            super().__init__(timeout=60)
            # add a Select with options if available and a fallback button to open modal without selection
            if options:
                sel = discord.ui.Select(placeholder="Chọn nhạc nền (tùy chọn)", options=options, min_values=0, max_values=1)
                async def _sel_callback(interaction: discord.Interaction):
                    selected = sel.values[0] if sel.values else None
                    await interaction.response.send_modal(VideoTaskFormYouTube(selected_bg=selected))
                sel.callback = _sel_callback
                self.add_item(sel)

            btn = discord.ui.Button(label="Mở form (không chọn nhạc)", style=discord.ButtonStyle.primary)
            async def _btn_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(VideoTaskFormYouTube(selected_bg=None))
            btn.callback = _btn_callback
            self.add_item(btn)

    view = BGSelectYT(options)
    if not options:
        await interaction.response.send_modal(VideoTaskFormYouTube())
    else:
        await interaction.response.send_message("Chọn nhạc nền (tùy chọn) hoặc mở form:", view=view, ephemeral=True)


@bot.tree.command(name="download_facebook", description="Tải video Facebook rồi chia nhỏ bằng server")
async def download_facebook(interaction: discord.Interaction):
    # simply open the modal
    await interaction.response.send_modal(FacebookDownloadForm())


class DownloadAudioForm(discord.ui.Modal, title="📥 Tải audio vào music_folder"):
    """Modal to accept a URL and optional filename to save into `music_folder` on the server."""
    url = discord.ui.TextInput(
        label="Audio/Video URL",
        style=discord.TextStyle.paragraph,
        placeholder="Dán link YouTube hoặc HTTP tới file audio/video",
        required=True
    )
    filename = discord.ui.TextInput(
        label="Tên file đích (tùy chọn, không cần .wav)",
        style=discord.TextStyle.short,
        placeholder="Ví dụ: my_bg_track (kết quả sẽ lưu là my_bg_track.wav)",
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        url_val = (self.url.value or "").strip()
        fn = (self.filename.value or "").strip()

        if not url_val:
            await interaction.followup.send("⚠️ Vui lòng cung cấp một URL hợp lệ.", ephemeral=True)
            return

        API_ENDPOINT = "http://tts-audio:8000/download_music"
        payload = {"url": url_val}
        if fn:
            # ensure no extension
            base = os.path.splitext(fn)[0]
            payload["filename"] = base + ".wav"

        try:
            timeout_obj = aiohttp.ClientTimeout(total=300)
            async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                async with session.post(API_ENDPOINT, json=payload) as resp:
                    text = await resp.text()
                    try:
                        data = await resp.json()
                    except Exception:
                        data = {"error": text}

            if resp.status >= 200 and resp.status < 300:
                saved = data.get("filename") or os.path.basename(data.get("saved_file", ""))
                saved_path = data.get("saved_file") or f"music_folder/{saved}"
                await interaction.followup.send(f"✅ Đã tải và lưu: **{saved}**\nĐường dẫn: `{saved_path}`", ephemeral=True)
            else:
                err = data.get("error") or text
                await interaction.followup.send(f"⚠️ Lỗi server ({resp.status}): {err}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"⚠️ Lỗi khi gọi API: {e}", ephemeral=True)


@bot.tree.command(name="download_audio", description="Tải audio từ link và lưu vào music_folder (server-side)")
async def download_audio(interaction: discord.Interaction):
    """Open a modal to download audio via the server's yt-dlp + ffmpeg pipeline into `music_folder`."""
    await interaction.response.send_modal(DownloadAudioForm())


@bot.tree.command(name="tiktok_large_video", description="Render TikTok Large Video (chia audio trước, render từng part)")
async def tiktok_large_video(interaction: discord.Interaction):
    # Build a Select menu listing files under discord-bot/bgaudio
    bot_dir = os.path.dirname(os.path.abspath(__file__))
    bgaudio_dir = os.path.join(bot_dir, "bgaudio")
    options = []

    if os.path.isdir(bgaudio_dir):
        files = sorted(
            [f for f in os.listdir(bgaudio_dir) if f.lower().endswith('.wav')],
            key=lambda x: x.lower()
        )
        for f in files[:25]:
            options.append(discord.SelectOption(label=sanitize_label(f), value=sanitize_value(f)))

    class BGSelectTikTokLarge(discord.ui.View):
        def __init__(self, options):
            super().__init__(timeout=60)
            if options:
                sel = discord.ui.Select(placeholder="Chọn nhạc nền (tùy chọn)", options=options, min_values=0, max_values=1)
                async def _sel_callback(interaction: discord.Interaction):
                    selected = sel.values[0] if sel.values else None
                    await interaction.response.send_modal(TikTokLargeVideoForm(selected_bg=selected))
                sel.callback = _sel_callback
                self.add_item(sel)

            btn = discord.ui.Button(label="Mở form (không chọn nhạc)", style=discord.ButtonStyle.primary)
            async def _btn_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(TikTokLargeVideoForm(selected_bg=None))
            btn.callback = _btn_callback
            self.add_item(btn)

    view = BGSelectTikTokLarge(options)
    if not options:
        await interaction.response.send_modal(TikTokLargeVideoForm())
    else:
        await interaction.response.send_message("Chọn nhạc nền (tùy chọn) hoặc mở form:", view=view, ephemeral=True)


@bot.tree.command(name="tiktok_large_video_parts", description="Render TikTok Large Video (chỉ render các part cụ thể)")
async def tiktok_large_video_parts(interaction: discord.Interaction):
    # Build a Select menu listing files under discord-bot/bgaudio
    bot_dir = os.path.dirname(os.path.abspath(__file__))
    bgaudio_dir = os.path.join(bot_dir, "bgaudio")
    options = []

    if os.path.isdir(bgaudio_dir):
        files = sorted(
            [f for f in os.listdir(bgaudio_dir) if f.lower().endswith('.wav')],
            key=lambda x: x.lower()
        )
        for f in files[:25]:
            options.append(discord.SelectOption(label=sanitize_label(f), value=sanitize_value(f)))

    class BGSelectTikTokLargeParts(discord.ui.View):
        def __init__(self, options):
            super().__init__(timeout=60)
            if options:
                sel = discord.ui.Select(placeholder="Chọn nhạc nền (tùy chọn)", options=options, min_values=0, max_values=1)
                async def _sel_callback(interaction: discord.Interaction):
                    selected = sel.values[0] if sel.values else None
                    await interaction.response.send_modal(TikTokLargeVideoPartsForm(selected_bg=selected))
                sel.callback = _sel_callback
                self.add_item(sel)

            btn = discord.ui.Button(label="Mở form (không chọn nhạc)", style=discord.ButtonStyle.primary)
            async def _btn_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(TikTokLargeVideoPartsForm(selected_bg=None))
            btn.callback = _btn_callback
            self.add_item(btn)

    view = BGSelectTikTokLargeParts(options)
    if not options:
        await interaction.response.send_modal(TikTokLargeVideoPartsForm())
    else:
        await interaction.response.send_message("Chọn nhạc nền (tùy chọn) hoặc mở form:", view=view, ephemeral=True)


@bot.tree.command(name="tiktok_large_no_summary", description="Render TikTok Large Video (chỉ lấy nội dung, bỏ văn án)")
async def tiktok_large_no_summary(interaction: discord.Interaction):
    # Build a Select menu listing files under discord-bot/bgaudio
    bot_dir = os.path.dirname(os.path.abspath(__file__))
    bgaudio_dir = os.path.join(bot_dir, "bgaudio")
    options = []

    if os.path.isdir(bgaudio_dir):
        files = sorted(
            [f for f in os.listdir(bgaudio_dir) if f.lower().endswith('.wav')],
            key=lambda x: x.lower()
        )
        for f in files[:25]:
            options.append(discord.SelectOption(label=sanitize_label(f), value=sanitize_value(f)))

    class BGSelectTikTokLargeNoSummary(discord.ui.View):
        def __init__(self, options):
            super().__init__(timeout=60)
            if options:
                sel = discord.ui.Select(placeholder="Chọn nhạc nền (tùy chọn)", options=options, min_values=0, max_values=1)
                async def _sel_callback(interaction: discord.Interaction):
                    selected = sel.values[0] if sel.values else None
                    await interaction.response.send_modal(TikTokLargeVideoNoSummaryForm(selected_bg=selected))
                sel.callback = _sel_callback
                self.add_item(sel)

            btn = discord.ui.Button(label="Mở form (không chọn nhạc)", style=discord.ButtonStyle.primary)
            async def _btn_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(TikTokLargeVideoNoSummaryForm(selected_bg=None))
            btn.callback = _btn_callback
            self.add_item(btn)

    view = BGSelectTikTokLargeNoSummary(options)
    if not options:
        await interaction.response.send_modal(TikTokLargeVideoNoSummaryForm())
    else:
        await interaction.response.send_message("Chọn nhạc nền (tùy chọn) hoặc mở form:", view=view, ephemeral=True)


@bot.tree.command(name="tiktok_large_openai_echo", description="Render TikTok Large Video using OpenAI TTS voice 'echo' (optional summary)")
async def tiktok_large_openai_echo(interaction: discord.Interaction):
    # Build a Select menu listing files under discord-bot/bgaudio
    bot_dir = os.path.dirname(os.path.abspath(__file__))
    bgaudio_dir = os.path.join(bot_dir, "bgaudio")
    options = []

    if os.path.isdir(bgaudio_dir):
        files = sorted(
            [f for f in os.listdir(bgaudio_dir) if f.lower().endswith('.wav')],
            key=lambda x: x.lower()
        )
        for f in files[:25]:
            options.append(discord.SelectOption(label=sanitize_label(f), value=sanitize_value(f)))

    class BGSelectTikTokLargeOpenAI(discord.ui.View):
        def __init__(self, options):
            super().__init__(timeout=60)
            if options:
                sel = discord.ui.Select(placeholder="Chọn nhạc nền (tùy chọn)", options=options, min_values=0, max_values=1)
                async def _sel_callback(interaction: discord.Interaction):
                    selected = sel.values[0] if sel.values else None
                    await interaction.response.send_modal(TikTokLargeVideoOpenAIEchoForm(selected_bg=selected))
                sel.callback = _sel_callback
                self.add_item(sel)

            btn = discord.ui.Button(label="Mở form (không chọn nhạc)", style=discord.ButtonStyle.primary)
            async def _btn_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(TikTokLargeVideoOpenAIEchoForm(selected_bg=None))
            btn.callback = _btn_callback
            self.add_item(btn)

    view = BGSelectTikTokLargeOpenAI(options)
    if not options:
        await interaction.response.send_modal(TikTokLargeVideoOpenAIEchoForm())
    else:
        await interaction.response.send_message("Chọn nhạc nền (tùy chọn) hoặc mở form:", view=view, ephemeral=True)


@bot.tree.command(name="tiktok_large_video_gemini", description="Render TikTok Large Video using Gemini TTS")
async def tiktok_large_video_gemini(interaction: discord.Interaction):
    # Build a Select menu listing files under discord-bot/bgaudio
    bot_dir = os.path.dirname(os.path.abspath(__file__))
    bgaudio_dir = os.path.join(bot_dir, "bgaudio")
    options = []

    if os.path.isdir(bgaudio_dir):
        files = sorted(
            [f for f in os.listdir(bgaudio_dir) if f.lower().endswith('.wav')],
            key=lambda x: x.lower()
        )
        for f in files[:25]:
            options.append(discord.SelectOption(label=sanitize_label(f), value=sanitize_value(f)))

    class BGSelectTikTokLargeGemini(discord.ui.View):
        def __init__(self, options):
            super().__init__(timeout=60)
            if options:
                sel = discord.ui.Select(placeholder="Chọn nhạc nền (tùy chọn)", options=options, min_values=0, max_values=1)
                async def _sel_callback(interaction: discord.Interaction):
                    selected = sel.values[0] if sel.values else None
                    await interaction.response.send_modal(TikTokLargeVideoGeminiForm(selected_bg=selected))
                sel.callback = _sel_callback
                self.add_item(sel)

            btn = discord.ui.Button(label="Mở form (không chọn nhạc)", style=discord.ButtonStyle.primary)
            async def _btn_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(TikTokLargeVideoGeminiForm(selected_bg=None))
            btn.callback = _btn_callback
            self.add_item(btn)

    view = BGSelectTikTokLargeGemini(options)
    if not options:
        await interaction.response.send_modal(TikTokLargeVideoGeminiForm())
    else:
        await interaction.response.send_message("Chọn nhạc nền (tùy chọn) hoặc mở form:", view=view, ephemeral=True)


# ==================== STORY TO VIDEO FORMS ====================

class StoryToVideoHorrorForm(discord.ui.Modal, title="👻 Tạo Truyện Kinh Dị → Video"):
    """Form tạo truyện kinh dị tự động và render video"""
    video_url = discord.ui.TextInput(
        label="Video URL(s) (background)",
        style=discord.TextStyle.paragraph,
        placeholder="Để trống sẽ lấy random từ cache. Hoặc nhập 1 hoặc nhiều link YouTube/video, cách nhau bằng dấu phẩy",
        required=False,
    )
    horror_theme = discord.ui.TextInput(
        label="Chủ đề kinh dị (tùy chọn)",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="VD: Làng cổ có lời nguyền... Để trống = ngẫu nhiên"
    )
    horror_setting = discord.ui.TextInput(
        label="Bối cảnh (tùy chọn)",
        required=False,
        placeholder="VD: làng quê xa xôi miền Bắc. Để trống = ngẫu nhiên"
    )
    # backend selection is now driven by `voice` parsed from the combined `bg_choice` input
    bg_choice = discord.ui.TextInput(
        label="Nhạc nền (đã chọn)",
        required=False,
        placeholder="Để trống nếu không dùng nhạc nền"
    )

    def __init__(self, selected_bg: str | None = None):
        super().__init__()
        if selected_bg:
            try:
                self.bg_choice.default = selected_bg
            except Exception:
                pass

    async def on_submit(self, interaction: discord.Interaction):
        video_raw = (self.video_url.value or "").strip()
        # allow empty -> server will pick random cached videos
        video_list = [v.strip() for v in video_raw.replace("\n", ",").split(",") if v.strip()]
        video_combined = ",".join(video_list)

        # parse combined bg/voice/include_summary/force_refresh single input
        bg_choice_val, voice_val, include_summary, force_refresh = parse_bg_voice_and_summary(self.bg_choice.value or "")
        params = {
            "genre": "horror",
            "video_urls": video_combined,
            "title": "",  # Để trống, sẽ lấy từ truyện được tạo
            "bg_choice": bg_choice_val,
            "include_summary": "true" if include_summary else "false",
            "force_refresh": "true" if force_refresh else "false",
            "horror_theme": self.horror_theme.value.strip(),
            "horror_setting": self.horror_setting.value.strip(),
        }
        if voice_val:
            params["voice"] = voice_val

        try:
            API_ENDPOINT = "http://tts-audio:8000/generate_story_to_video"
            r = requests.post(API_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()

            try:
                data = r.json()
                task_id = data.get("task_id", "N/A")
                ai_display = (voice_val.upper() if voice_val else 'GEMINI')
                msg = f"✅ **Đã tạo task Truyện Kinh Dị → Video**\n📋 Task ID: `{task_id}`\n🎬 Genre: {data.get('genre', 'horror').upper()}\n🤖 AI: {ai_display}\n\n💡 Dùng `/task_status {task_id}` để theo dõi tiến trình\n⏱️ Thời gian ước tính: 10-30 phút"
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"

            await interaction.response.send_message(msg[:2000], ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)


class StoryToVideoFaceSlap(discord.ui.Modal, title="💥 Tạo Truyện Vả Mặt → Video"):
    """Form tạo truyện vả mặt (giả nghèo phản đòn) và render video"""
    video_url = discord.ui.TextInput(
        label="Video URL(s) (background)",
        style=discord.TextStyle.paragraph,
        placeholder="Để trống sẽ lấy random từ cache. Hoặc nhập 1 hoặc nhiều link YouTube/video, cách nhau bằng dấu phẩy",
        required=False,
    )
    face_slap_theme = discord.ui.TextInput(
        label="Chủ đề vả mặt (tùy chọn)",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="VD: Chủ tịch giả làm nhân viên tạp vụ... Để trống = ngẫu nhiên"
    )
    face_slap_role = discord.ui.TextInput(
        label="Vai giả nghèo (tùy chọn)",
        required=False,
        placeholder="VD: Chủ tịch tập đoàn, Thiên tài y học... Để trống = ngẫu nhiên"
    )
    # backend selection is now driven by `voice` parsed from the combined `bg_choice` input
    bg_choice = discord.ui.TextInput(
        label="Nhạc nền (đã chọn)",
        required=False,
        placeholder="Để trống nếu không dùng nhạc nền"
    )

    def __init__(self, selected_bg: str | None = None):
        super().__init__()
        if selected_bg:
            try:
                self.bg_choice.default = selected_bg
            except Exception:
                pass

    async def on_submit(self, interaction: discord.Interaction):
        video_raw = (self.video_url.value or "").strip()
        # allow empty -> server will pick random cached videos
        video_list = [v.strip() for v in video_raw.replace("\n", ",").split(",") if v.strip()]
        video_combined = ",".join(video_list)

        # parse combined bg/voice/include_summary/force_refresh single input
        bg_choice_val, voice_val, include_summary, force_refresh = parse_bg_voice_and_summary(self.bg_choice.value or "")
        params = {
            "genre": "face_slap",
            "video_urls": video_combined,
            "title": "",  # Để trống, sẽ lấy từ truyện được tạo
            "bg_choice": bg_choice_val,
            "include_summary": "true" if include_summary else "false",
            "force_refresh": "true" if force_refresh else "false",
            "face_slap_theme": self.face_slap_theme.value.strip(),
            "face_slap_role": self.face_slap_role.value.strip(),
        }
        if voice_val:
            params["voice"] = voice_val

        try:
            API_ENDPOINT = "http://tts-audio:8000/generate_story_to_video"
            r = requests.post(API_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()

            try:
                data = r.json()
                task_id = data.get("task_id", "N/A")
                ai_display = (voice_val.upper() if voice_val else 'GEMINI')
                msg = f"✅ **Đã tạo task Truyện Vả Mặt → Video**\n📋 Task ID: `{task_id}`\n🎬 Genre: {data.get('genre', 'face_slap').upper()}\n🤖 AI: {ai_display}\n\n💡 Dùng `/task_status {task_id}` để theo dõi tiến trình\n⏱️ Thời gian ước tính: 10-30 phút"
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"

            await interaction.response.send_message(msg[:2000], ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)




class StoryToVideoRandomMix(discord.ui.Modal, title="🎲 Tạo Truyện Random Mix → Video"):
    """Form tạo truyện random mix (kết hợp nhiều thể loại) và render video"""
    video_url = discord.ui.TextInput(
        label="Video URL(s) (background)",
        style=discord.TextStyle.paragraph,
        placeholder="Để trống sẽ lấy random từ cache. Hoặc nhập 1 hoặc nhiều link YouTube/video, cách nhau bằng dấu phẩy",
        required=False,
    )
    user_idea = discord.ui.TextInput(
        label="💡 Ý tưởng của bạn (tùy chọn)",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="VD: 'tình cảm bị phản bội' hoặc 'lạc trên tàu với quy tắc kỳ lạ'"
    )
    # `ai_backend` removed: backend selection is now driven by the combined `bg_choice` input's `voice` value.
    random_elements = discord.ui.TextInput(
        label="Tùy chỉnh chi tiết (tùy chọn)",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="Nếu cần điều chỉnh chi tiết: main_genre=..., character=...\nThường không cần điền"
    )
    bg_choice = discord.ui.TextInput(
        label="Nhạc nền (đã chọn)",
        required=False,
        placeholder="Để trống nếu không dùng nhạc nền"
    )

    def __init__(self, selected_bg: str | None = None, initial_sample: dict | None = None):
        super().__init__()
        # prefill bg if provided
        if selected_bg:
            try:
                self.bg_choice.default = selected_bg
            except Exception:
                pass

        # If an initial sample is provided, convert it into the 'random_elements' short syntax
        try:
            if initial_sample and isinstance(initial_sample, dict):
                parts = []
                main = initial_sample.get('the_loai_chinh') or initial_sample.get('random_main_genre')
                if main:
                    parts.append(f"main_genre={main}")
                sub = initial_sample.get('the_loai_phu') or initial_sample.get('random_sub_genre')
                if sub:
                    parts.append(f"sub_genre={sub}")
                char = initial_sample.get('nhan_vat') or initial_sample.get('random_character')
                if char:
                    parts.append(f"character={char}")
                setting = initial_sample.get('boi_canh') or initial_sample.get('random_setting')
                if setting:
                    parts.append(f"setting={setting}")
                motif = initial_sample.get('mo_tip') or initial_sample.get('random_plot_motif')
                if motif:
                    parts.append(f"plot={motif}")

                if parts:
                    try:
                        self.random_elements.default = ", ".join(parts)
                    except Exception:
                        pass

                # If sample suggests a preferred backend, prefill the combined `bg_choice`
                # so it contains the selected background (if any) plus a voice token and
                # include_summary=true. Mapping:
                # - openai -> voice=nova
                # - gemini -> voice=gfmale
                try:
                    backend_val = (initial_sample.get('ai_backend') if isinstance(initial_sample, dict) else None) or initial_sample.get('backend') if isinstance(initial_sample, dict) else None
                    if backend_val and isinstance(backend_val, str):
                        b = backend_val.strip().lower()
                        voice_pref = None
                        if 'openai' in b:
                            voice_pref = 'nova'
                        elif 'gemini' in b:
                            voice_pref = 'gfemale'

                        if voice_pref:
                            try:
                                base = selected_bg or ''
                                lines = []
                                if base:
                                    # use key=value style for clarity
                                    lines.append(f"bg={base}")
                                lines.append(f"voice={voice_pref}")
                                lines.append("include_summary=true")
                                self.bg_choice.default = "\n".join(lines) + "\n"
                            except Exception:
                                pass
                except Exception:
                    pass
        except Exception:
            pass

    async def on_submit(self, interaction: discord.Interaction):
        video_raw = (self.video_url.value or "").strip()
        # allow empty -> server will pick random cached videos
        video_list = [v.strip() for v in video_raw.replace("\n", ",").split(",") if v.strip()]
        video_combined = ",".join(video_list)

        # parse combined bg/voice/include_summary/force_refresh single input
        bg_choice_val, voice_val, include_summary, force_refresh = parse_bg_voice_and_summary(self.bg_choice.value or "")
        params = {
            "genre": "random_mix",
            "video_urls": video_combined,
            "title": "",  # Để trống, sẽ lấy từ truyện được tạo
            "bg_choice": bg_choice_val,
            "include_summary": "true" if include_summary else "false",
            "force_refresh": "true" if force_refresh else "false",
        }
        if voice_val:
            params["voice"] = voice_val
        
        # Thêm user_idea vào custom_requirements nếu có
        user_idea_text = (self.user_idea.value or "").strip()
        if user_idea_text:
            params["custom_requirements"] = f"Ý tưởng user: {user_idea_text}"

        # Parse custom random elements if provided
        custom = (self.random_elements.value or "").strip()
        if custom:
            # Simple parser: main_genre=xxx, character=yyy, ...
            for part in custom.split(","):
                if "=" in part:
                    key, val = part.split("=", 1)
                    key = key.strip().lower()
                    val = val.strip()
                    if key == "main_genre":
                        params["random_main_genre"] = val
                    elif key in ["character", "char"]:
                        params["random_character"] = val
                    elif key == "setting":
                        params["random_setting"] = val
                    elif key == "sub_genre":
                        params["random_sub_genre"] = val
                    elif key in ["plot", "motif"]:
                        params["random_plot_motif"] = val

        try:
            API_ENDPOINT = "http://tts-audio:8000/generate_story_to_video"
            r = requests.post(API_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()

            try:
                data = r.json()
                task_id = data.get("task_id", "N/A")
                idea_msg = f"\n💡 Ý tưởng: {user_idea_text[:100]}" if user_idea_text else ""
                ai_display = (voice_val.upper() if voice_val else 'GEMINI')
                msg = f"✅ **Đã tạo task Truyện Random Mix → Video**\n📋 Task ID: `{task_id}`\n🎬 Genre: {data.get('genre', 'random_mix').upper()}\n🤖 AI: {ai_display}{idea_msg}\n\n💡 Dùng `/task_status {task_id}` để theo dõi tiến trình\n⏱️ Thời gian ước tính: 10-30 phút"
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"

            await interaction.response.send_message(msg[:2000], ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)



class StoryToVideoXuyenKhongForm(discord.ui.Modal, title="🌀 Tạo Truyện Xuyên Không → Video"):
    video_url = discord.ui.TextInput(
        label="Video URL(s) (background)",
        style=discord.TextStyle.paragraph,
        placeholder="Để trống sẽ lấy random từ cache. Hoặc nhập 1 hoặc nhiều link YouTube/video, cách nhau bằng dấu phẩy",
        required=False,
    )
    xuyen_theme = discord.ui.TextInput(
        label="Chủ đề (tùy chọn)",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="VD: Xuyên về làm con nuôi của gia tộc quyền lực"
    )
    xuyen_setting = discord.ui.TextInput(
        label="Bối cảnh (tùy chọn)",
        required=False,
        placeholder="VD: triều đại giả tưởng"
    )
    # backend selection is now driven by `voice` parsed from the combined `bg_choice` input
    bg_choice = discord.ui.TextInput(
        label="Nhạc nền (đã chọn)",
        required=False,
        placeholder="Để trống nếu không dùng nhạc nền"
    )

    def __init__(self, selected_bg: str | None = None):
        super().__init__()
        if selected_bg:
            try:
                self.bg_choice.default = selected_bg
            except Exception:
                pass

    async def on_submit(self, interaction: discord.Interaction):
        video_raw = (self.video_url.value or "").strip()
        video_list = [v.strip() for v in video_raw.replace("\n", ",").split(",") if v.strip()]
        video_combined = ",".join(video_list)

        # parse combined bg/voice/include_summary/force_refresh single input
        bg_choice_val, voice_val, include_summary, force_refresh = parse_bg_voice_and_summary(self.bg_choice.value or "")
        params = {
            "genre": "xuyen_khong",
            "video_urls": video_combined,
            "title": "",
            "bg_choice": bg_choice_val,
            "include_summary": "true" if include_summary else "false",
            "force_refresh": "true" if force_refresh else "false",
            "xuyen_theme": self.xuyen_theme.value.strip(),
            "xuyen_setting": self.xuyen_setting.value.strip(),
        }
        if voice_val:
            params["voice"] = voice_val

        try:
            API_ENDPOINT = "http://tts-audio:8000/generate_story_to_video"
            r = requests.post(API_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()
            try:
                data = r.json()
                task_id = data.get("task_id", "N/A")
                ai_display = (voice_val.upper() if voice_val else 'GEMINI')
                msg = f"✅ **Đã tạo task Xuyên Không → Video**\n📋 Task ID: `{task_id}`\n🎬 Genre: {data.get('genre', 'xuyen_khong').upper()}\n🤖 AI: {ai_display}\n\n💡 Dùng `/task_status {task_id}` để theo dõi tiến trình\n⏱️ Thời gian ước tính: 10-30 phút"
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"
            await interaction.response.send_message(msg[:2000], ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)


class StoryToVideoTrinhThamForm(discord.ui.Modal, title="🕵️ Tạo Truyện Trinh Thám → Video"):
    video_url = discord.ui.TextInput(
        label="Video URL(s) (background)",
        style=discord.TextStyle.paragraph,
        placeholder="Để trống sẽ lấy random từ cache. Hoặc nhập 1 hoặc nhiều link YouTube/video, cách nhau bằng dấu phẩy",
        required=False,
    )
    trinh_theme = discord.ui.TextInput(
        label="Chủ đề (tùy chọn)",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="VD: Vụ án mạng trong khu chung cư"
    )
    trinh_setting = discord.ui.TextInput(
        label="Bối cảnh (tùy chọn)",
        required=False,
        placeholder="VD: khu chung cư thành phố"
    )
    # backend selection is now driven by `voice` parsed from the combined `bg_choice` input
    bg_choice = discord.ui.TextInput(
        label="Nhạc nền (đã chọn)",
        required=False,
        placeholder="Để trống nếu không dùng nhạc nền"
    )

    def __init__(self, selected_bg: str | None = None):
        super().__init__()
        if selected_bg:
            try:
                self.bg_choice.default = selected_bg
            except Exception:
                pass

    async def on_submit(self, interaction: discord.Interaction):
        video_raw = (self.video_url.value or "").strip()
        video_list = [v.strip() for v in video_raw.replace("\n", ",").split(",") if v.strip()]
        video_combined = ",".join(video_list)

        # parse combined bg/voice/include_summary/force_refresh single input
        bg_choice_val, voice_val, include_summary, force_refresh = parse_bg_voice_and_summary(self.bg_choice.value or "")
        params = {
            "genre": "trinh_tham",
            "video_urls": video_combined,
            "title": "",
            "bg_choice": bg_choice_val,
            "include_summary": "true" if include_summary else "false",
            "force_refresh": "true" if force_refresh else "false",
            "trinh_theme": self.trinh_theme.value.strip(),
            "trinh_setting": self.trinh_setting.value.strip(),
        }
        if voice_val:
            params["voice"] = voice_val

        try:
            API_ENDPOINT = "http://tts-audio:8000/generate_story_to_video"
            r = requests.post(API_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()
            try:
                data = r.json()
                task_id = data.get("task_id", "N/A")
                ai_display = (voice_val.upper() if voice_val else 'GEMINI')
                msg = f"✅ **Đã tạo task Trinh Thám → Video**\n📋 Task ID: `{task_id}`\n🎬 Genre: {data.get('genre', 'trinh_tham').upper()}\n🤖 AI: {ai_display}\n\n💡 Dùng `/task_status {task_id}` để theo dõi tiến trình\n⏱️ Thời gian ước tính: 10-30 phút"
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"
            await interaction.response.send_message(msg[:2000], ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)


class StoryToVideoHeThongForm(discord.ui.Modal, title="⚙️ Tạo Truyện Hệ Thống → Video"):
    video_url = discord.ui.TextInput(
        label="Video URL(s) (background)",
        style=discord.TextStyle.paragraph,
        placeholder="Để trống sẽ lấy random từ cache. Hoặc nhập 1 hoặc nhiều link YouTube/video, cách nhau bằng dấu phẩy",
        required=False,
    )
    system_theme = discord.ui.TextInput(
        label="Chủ đề (tùy chọn)",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="VD: Hệ thống tăng level, skill"
    )
    system_setting = discord.ui.TextInput(
        label="Bối cảnh (tùy chọn)",
        required=False,
        placeholder="VD: thế giới game-like"
    )
    # backend selection is now driven by `voice` parsed from the combined `bg_choice` input
    bg_choice = discord.ui.TextInput(
        label="Nhạc nền (đã chọn)",
        required=False,
        placeholder="Để trống nếu không dùng nhạc nền"
    )

    def __init__(self, selected_bg: str | None = None):
        super().__init__()
        if selected_bg:
            try:
                self.bg_choice.default = selected_bg
            except Exception:
                pass

    async def on_submit(self, interaction: discord.Interaction):
        video_raw = (self.video_url.value or "").strip()
        video_list = [v.strip() for v in video_raw.replace("\n", ",").split(",") if v.strip()]
        video_combined = ",".join(video_list)

        # parse combined bg/voice/include_summary/force_refresh single input
        bg_choice_val, voice_val, include_summary, force_refresh = parse_bg_voice_and_summary(self.bg_choice.value or "")
        params = {
            "genre": "he_thong",
            "video_urls": video_combined,
            "title": "",
            "bg_choice": bg_choice_val,
            "include_summary": "true" if include_summary else "false",
            "force_refresh": "true" if force_refresh else "false",
            "system_theme": self.system_theme.value.strip(),
            "system_setting": self.system_setting.value.strip(),
        }
        if voice_val:
            params["voice"] = voice_val

        try:
            API_ENDPOINT = "http://tts-audio:8000/generate_story_to_video"
            r = requests.post(API_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()
            try:
                data = r.json()
                task_id = data.get("task_id", "N/A")
                ai_display = (voice_val.upper() if voice_val else 'GEMINI')
                msg = f"✅ **Đã tạo task Hệ Thống → Video**\n📋 Task ID: `{task_id}`\n🎬 Genre: {data.get('genre', 'he_thong').upper()}\n🤖 AI: {ai_display}\n\n💡 Dùng `/task_status {task_id}` để theo dõi tiến trình\n⏱️ Thời gian ước tính: 10-30 phút"
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"
            await interaction.response.send_message(msg[:2000], ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)


class StoryToVideoGameWorldForm(discord.ui.Modal, title="🎮 Tạo Truyện Vào Thế Giới Game → Video"):
    video_url = discord.ui.TextInput(
        label="Video URL(s) (background)",
        style=discord.TextStyle.paragraph,
        placeholder="Để trống sẽ lấy random từ cache. Hoặc nhập 1 hoặc nhiều link YouTube/video, cách nhau bằng dấu phẩy",
        required=False,
    )
    game_theme = discord.ui.TextInput(
        label="Chủ đề (tùy chọn)",
        style=discord.TextStyle.paragraph,
        required=False,
        placeholder="VD: Mắc kẹt trong MMORPG"
    )
    game_setting = discord.ui.TextInput(
        label="Bối cảnh (tùy chọn)",
        required=False,
        placeholder="VD: thế giới giả lập MMORPG"
    )
    # backend selection is now driven by `voice` parsed from the combined `bg_choice` input
    bg_choice = discord.ui.TextInput(
        label="Nhạc nền (đã chọn)",
        required=False,
        placeholder="Để trống nếu không dùng nhạc nền"
    )

    def __init__(self, selected_bg: str | None = None):
        super().__init__()
        if selected_bg:
            try:
                self.bg_choice.default = selected_bg
            except Exception:
                pass

    async def on_submit(self, interaction: discord.Interaction):
        video_raw = (self.video_url.value or "").strip()
        video_list = [v.strip() for v in video_raw.replace("\n", ",").split(",") if v.strip()]
        video_combined = ",".join(video_list)

        # parse combined bg/voice/include_summary/force_refresh single input
        bg_choice_val, voice_val, include_summary, force_refresh = parse_bg_voice_and_summary(self.bg_choice.value or "")
        params = {
            "genre": "vao_the_gioi_game",
            "video_urls": video_combined,
            "title": "",
            "bg_choice": bg_choice_val,
            "include_summary": "true" if include_summary else "false",
            "force_refresh": "true" if force_refresh else "false",
            "game_theme": self.game_theme.value.strip(),
            "game_setting": self.game_setting.value.strip(),
        }
        if voice_val:
            params["voice"] = voice_val

        try:
            API_ENDPOINT = "http://tts-audio:8000/generate_story_to_video"
            r = requests.post(API_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()
            try:
                data = r.json()
                task_id = data.get("task_id", "N/A")
                ai_display = (voice_val.upper() if voice_val else 'GEMINI')
                msg = f"✅ **Đã tạo task Vào Thế Giới Game → Video**\n📋 Task ID: `{task_id}`\n🎬 Genre: {data.get('genre', 'vao_the_gioi_game').upper()}\n🤖 AI: {ai_display}\n\n💡 Dùng `/task_status {task_id}` để theo dõi tiến trình\n⏱️ Thời gian ước tính: 10-30 phút"
            except Exception:
                msg = f"✅ API phản hồi:\n```\n{r.text}\n```"
            await interaction.response.send_message(msg[:2000], ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Lỗi gọi API: {e}", ephemeral=True)


@bot.tree.command(name="story_to_video", description="🎬 Tạo Truyện → Audio → Video (3 thể loại)")
async def story_to_video(interaction: discord.Interaction):
    """
    Command chính để chọn 1 trong 3 thể loại truyện:
    1. 👻 Kinh Dị (Horror)
    2. 💥 Vả Mặt (Face Slap)
    3. 🎲 Random Mix (Ngẫu nhiên)
    """
    # Build background music select menu
    bot_dir = os.path.dirname(os.path.abspath(__file__))
    bgaudio_dir = os.path.join(bot_dir, "bgaudio")
    bg_options = []

    if os.path.isdir(bgaudio_dir):
        files = sorted(
            [f for f in os.listdir(bgaudio_dir) if f.lower().endswith('.wav')],
            key=lambda x: x.lower()
        )
        for f in files[:25]:
            bg_options.append(discord.SelectOption(label=sanitize_label(f), value=sanitize_value(f)))

    class StoryToVideoView(discord.ui.View):
        def __init__(self, bg_options):
            super().__init__(timeout=120)
            self.selected_bg = None
            
            # Add background music selector if available
            if bg_options:
                bg_select = discord.ui.Select(
                    placeholder="🎵 Chọn nhạc nền (tùy chọn)",
                    options=bg_options,
                    min_values=0,
                    max_values=1
                )
                async def _bg_callback(interaction: discord.Interaction):
                    self.selected_bg = bg_select.values[0] if bg_select.values else None
                    await interaction.response.send_message(
                        f"✅ Đã chọn nhạc nền: **{self.selected_bg}**\nBây giờ chọn thể loại truyện bên dưới.",
                        ephemeral=True
                    )
                bg_select.callback = _bg_callback
                self.add_item(bg_select)
            
            # Add genre buttons
            horror_btn = discord.ui.Button(
                label="👻 Kinh Dị",
                style=discord.ButtonStyle.danger,
                emoji="👻"
            )
            async def _horror_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(StoryToVideoHorrorForm(selected_bg=self.selected_bg))
            horror_btn.callback = _horror_callback
            self.add_item(horror_btn)
            
            face_slap_btn = discord.ui.Button(
                label="💥 Vả Mặt",
                style=discord.ButtonStyle.success,
                emoji="💥"
            )
            async def _face_slap_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(StoryToVideoFaceSlap(selected_bg=self.selected_bg))
            face_slap_btn.callback = _face_slap_callback
            self.add_item(face_slap_btn)
            
            random_btn = discord.ui.Button(
                label="🎲 Random Mix",
                style=discord.ButtonStyle.primary,
                emoji="🎲"
            )
            async def _random_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(StoryToVideoRandomMix(selected_bg=self.selected_bg))
            random_btn.callback = _random_callback
            self.add_item(random_btn)
            
            # New genre buttons (requested): Xuyên không, Trinh thám, Hệ thống, Vào thế giới game
            xuyen_btn = discord.ui.Button(
                label="🌀 Xuyên Không",
                style=discord.ButtonStyle.secondary,
                emoji="🌀"
            )
            async def _xuyen_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(StoryToVideoXuyenKhongForm(selected_bg=self.selected_bg))
            xuyen_btn.callback = _xuyen_callback
            self.add_item(xuyen_btn)

            trinh_btn = discord.ui.Button(
                label="🕵️ Trinh Thám",
                style=discord.ButtonStyle.secondary,
                emoji="🕵️"
            )
            async def _trinh_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(StoryToVideoTrinhThamForm(selected_bg=self.selected_bg))
            trinh_btn.callback = _trinh_callback
            self.add_item(trinh_btn)

            hethong_btn = discord.ui.Button(
                label="⚙️ Hệ Thống",
                style=discord.ButtonStyle.secondary,
                emoji="⚙️"
            )
            async def _hethong_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(StoryToVideoHeThongForm(selected_bg=self.selected_bg))
            hethong_btn.callback = _hethong_callback
            self.add_item(hethong_btn)

            game_btn = discord.ui.Button(
                label="🎮 Vào Thế Giới Game",
                style=discord.ButtonStyle.secondary,
                emoji="🎮"
            )
            async def _game_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(StoryToVideoGameWorldForm(selected_bg=self.selected_bg))
            game_btn.callback = _game_callback
            self.add_item(game_btn)

    view = StoryToVideoView(bg_options)
    
    embed = discord.Embed(
        title="🎬 TẠO TRUYỆN → AUDIO → VIDEO",
        description=(
            "**Pipeline tự động hoàn toàn:**\n"
            "1️⃣ AI tạo truyện (~10,000 từ)\n"
            "2️⃣ Chuyển văn bản → Audio (TTS)\n"
            "3️⃣ Xử lý audio (tăng tốc + nhạc nền)\n"
            "4️⃣ Render video cuối cùng\n\n"
            "**Chọn 1 trong 3 thể loại:**\n"
            "👻 **Kinh Dị** - Ma mị, u ám, huyền bí Việt Nam\n"
            "💥 **Vả Mặt** - Giả nghèo phản đòn, drama sảng khoái\n"
            "🎲 **Random Mix** - Kết hợp ngẫu nhiên nhiều thể loại\n\n"
            "💡 **Lưu ý:** Quá trình mất 10-30 phút tùy độ dài"
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text="Chọn nhạc nền (tùy chọn) rồi chọn thể loại bên dưới")
    
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="example_randommix", description="🎲 AI chọn kết hợp Random Mix hợp lý — Tạo video hoặc Random lại")
async def example_randommix(
    interaction: discord.Interaction,
    y_tuong: str = None
):
    """Slash command: fetch an AI-selected random_mix param set and show two buttons:
    1) Tạo video — call backend to create the story+video task
    2) Random lại — fetch another AI-selected sample and update the embed
    
    Args:
        y_tuong: Ý tưởng truyện (VD: "tình cảm bị phản bội rồi trả thù" hoặc "lạc trên tàu với quy tắc kỳ lạ")
    """
    
    # Defer immediately vì AI selection mất thời gian
    await interaction.response.defer(ephemeral=True)

    try:
        API_ENDPOINT = "http://tts-audio:8000/sample_random_mix_ai"
        params = {"count": 1}
        if y_tuong:
            params["user_idea"] = y_tuong
        
        status, data_or_text = await http_get(API_ENDPOINT, params=params, timeout=120)
        if status < 200 or status >= 300:
            await interaction.followup.send(f"⚠️ API lỗi: status {status} - {data_or_text}", ephemeral=True)
            return
        data = data_or_text if isinstance(data_or_text, dict) else {}
        samples = data.get('samples') or []
        if not samples:
            await interaction.followup.send("⚠️ Không nhận được sample từ server.", ephemeral=True)
            return
        sample = samples[0]
    except Exception as e:
        await interaction.followup.send(f"⚠️ Lỗi khi lấy AI sample: {e}", ephemeral=True)
        return

    def build_embed(s):
        emb = discord.Embed(title="🤖 AI Random Mix — Kết hợp hợp lý", color=discord.Color.purple())
        
        # Hiển thị ý tưởng user nếu có
        user_idea = s.get('user_idea')
        if user_idea:
            emb.add_field(name="💡 Ý tưởng của bạn", value=user_idea[:300], inline=False)
        
        emb.add_field(name="Thể loại chính", value=s.get('the_loai_chinh', 'N/A'), inline=False)
        emb.add_field(name="Thể loại phụ", value=s.get('the_loai_phu', 'N/A'), inline=False)
        emb.add_field(name="Nhân vật", value=(s.get('nhan_vat') or '')[:400] or 'N/A', inline=False)
        emb.add_field(name="Bối cảnh", value=(s.get('boi_canh') or '')[:400] or 'N/A', inline=False)
        emb.add_field(name="Mô típ", value=(s.get('mo_tip') or '')[:400] or 'N/A', inline=False)
        
        # Hiển thị lý do AI chọn
        reason = s.get('selection_reason', 'N/A')
        emb.add_field(name="🎯 Lý do AI chọn", value=reason[:500], inline=False)
        
        emb.set_footer(text=f"Sample ID: {s.get('task_id')} — AI đã chọn kết hợp hài hòa")
        return emb

    class RandomMixView(discord.ui.View):
        def __init__(self, sample, user_idea=None):
            super().__init__(timeout=120)
            self.sample = sample
            self.selected_bg = None
            self.user_idea = user_idea  # Lưu ý tưởng để dùng khi random lại

            # Build background select menu from discord-bot/bgaudio (if exists)
            try:
                bot_dir = os.path.dirname(os.path.abspath(__file__))
                bgaudio_dir = os.path.join(bot_dir, "bgaudio")
                options = []
                if os.path.isdir(bgaudio_dir):
                    files = sorted([f for f in os.listdir(bgaudio_dir) if f.lower().endswith('.wav')], key=lambda x: x.lower())
                    for f in files[:25]:
                        options.append(discord.SelectOption(label=sanitize_label(f), value=sanitize_value(f)))

                if options:
                    sel = discord.ui.Select(placeholder="Chọn nhạc nền (tùy chọn)", options=options, min_values=0, max_values=1)

                    async def _sel_callback(interaction: discord.Interaction):
                        # store selection on view, acknowledge quickly using defer+followup
                        self.selected_bg = sel.values[0] if sel.values else None
                        try:
                            await interaction.response.defer(ephemeral=True)
                            await interaction.followup.send(f"✅ Đã chọn nhạc nền: **{self.selected_bg or 'Không chọn'}**", ephemeral=True)
                        except Exception:
                            try:
                                await interaction.response.send_message(f"✅ Đã chọn nhạc nền: **{self.selected_bg or 'Không chọn'}**", ephemeral=True)
                            except Exception:
                                pass

                    sel.callback = _sel_callback
                    self.add_item(sel)
            except Exception:
                # if anything fails, ignore and continue without bg selector
                pass

        @discord.ui.button(label="Tạo video", style=discord.ButtonStyle.primary)
        async def create_video(self, interaction: discord.Interaction, button=None):
            # Open a prefilled modal so the user can edit values before submitting
            try:
                await interaction.response.send_modal(StoryToVideoRandomMix(selected_bg=self.selected_bg, initial_sample=self.sample))
            except Exception as e:
                try:
                    await interaction.response.send_message(f"⚠️ Không thể mở form: {e}", ephemeral=True)
                except Exception:
                    pass

        @discord.ui.button(label="Tạo video (OpenAI)", style=discord.ButtonStyle.success)
        async def create_video_openai(self, interaction: discord.Interaction, button=None):
            # Open the same prefilled modal but request OpenAI as backend
            try:
                s = dict(self.sample) if isinstance(self.sample, dict) else {}
                s['ai_backend'] = 'openai'
                await interaction.response.send_modal(StoryToVideoRandomMix(selected_bg=self.selected_bg, initial_sample=s))
            except Exception as e:
                try:
                    await interaction.response.send_message(f"⚠️ Không thể mở form (OpenAI): {e}", ephemeral=True)
                except Exception:
                    pass

        @discord.ui.button(label="Random lại", style=discord.ButtonStyle.secondary)
        async def random_again(self, interaction: discord.Interaction, button=None):
            # Defer response NGAY để tránh timeout (vì gọi AI)
            try:
                await interaction.response.defer()
            except Exception:
                pass
            
            # Fetch a new AI-selected sample với user_idea nếu có
            try:
                API_ENDPOINT = "http://tts-audio:8000/sample_random_mix_ai"
                params = {"count": 1}
                if self.user_idea:  # Truyền lại user_idea vào request
                    params["user_idea"] = self.user_idea
                
                status, d2_or_text = await http_get(API_ENDPOINT, params=params, timeout=120)
                if status < 200 or status >= 300:
                    await interaction.followup.send(f"⚠️ API lỗi: status {status} - {d2_or_text}", ephemeral=True)
                    return
                d2 = d2_or_text if isinstance(d2_or_text, dict) else {}
                s2 = (d2.get('samples') or [None])[0]
                if not s2:
                    await interaction.followup.send("⚠️ Không lấy được sample mới.", ephemeral=True)
                    return
                self.sample = s2
                new_emb = build_embed(s2)
                try:
                    await interaction.edit_original_response(embed=new_emb, view=self)
                except Exception:
                    await interaction.followup.send(embed=new_emb, ephemeral=True)
            except Exception as e:
                try:
                    await interaction.followup.send(f"⚠️ Lỗi khi lấy sample mới: {e}", ephemeral=True)
                except Exception:
                    pass

        @discord.ui.button(label="Tạo Preview (Tiêu đề + Tóm tắt)", style=discord.ButtonStyle.primary)
        async def generate_preview(self, interaction: discord.Interaction, button=None):
            """Call backend to generate title, full story file and a short summary in one request."""
            try:
                await interaction.response.defer()
            except Exception:
                pass

            # Build params from current sample
            try:
                s = dict(self.sample) if isinstance(self.sample, dict) else {}
                params = {
                    'random_main_genre': s.get('the_loai_chinh'),
                    'random_sub_genre': s.get('the_loai_phu'),
                    'random_character': s.get('nhan_vat'),
                    'random_setting': s.get('boi_canh'),
                    'random_plot_motif': s.get('mo_tip'),
                }
                if self.user_idea:
                    params['user_idea'] = self.user_idea

                API_ENDPOINT = "http://tts-audio:8000/generate_full_preview"
                status, data_or_text = await http_post(API_ENDPOINT, params=params, timeout=600)
                if status < 200 or status >= 300:
                    raise Exception(f"API lỗi: status {status} - {data_or_text}")
                data = data_or_text if isinstance(data_or_text, dict) else {}

                title = data.get('title') or 'Không có tiêu đề'
                summary = data.get('summary') or '(Không có tóm tắt)'
                file_path = data.get('file_path') or data.get('file') or None

                # Build embed with title + summary
                emb = discord.Embed(title=title[:256], description=(summary[:1500] if summary else ''), color=0x2F3136)
                if file_path:
                    emb.add_field(name="File lưu", value=os.path.basename(file_path), inline=False)

                view2 = discord.ui.View()
                # allow attaching a selected bg to the view
                setattr(view2, 'selected_bg', None)
                # store original preview params so create-video can include required fields (e.g., genre)
                try:
                    setattr(view2, 'base_params', dict(params))
                except Exception:
                    setattr(view2, 'base_params', {})

                # add background music selector if files exist under discord-bot/bgaudio
                try:
                    bot_dir2 = os.path.dirname(os.path.abspath(__file__))
                    bgaudio_dir2 = os.path.join(bot_dir2, "bgaudio")
                    bg_options2 = []
                    if os.path.isdir(bgaudio_dir2):
                        files2 = sorted([f for f in os.listdir(bgaudio_dir2) if f.lower().endswith('.wav')], key=lambda x: x.lower())
                        for f in files2[:25]:
                            bg_options2.append(discord.SelectOption(label=sanitize_label(f), value=sanitize_value(f)))

                    if bg_options2:
                        sel_bg = discord.ui.Select(placeholder="Chọn nhạc nền (tùy chọn)", options=bg_options2, min_values=0, max_values=1)

                        async def _sel_bg_cb(interaction: discord.Interaction):
                            try:
                                view2.selected_bg = sel_bg.values[0] if sel_bg.values else None
                                if view2.selected_bg:
                                    await interaction.response.send_message(f"✅ Đã chọn nhạc nền: **{view2.selected_bg}**", ephemeral=True)
                                else:
                                    await interaction.response.send_message(f"✅ Bỏ chọn nhạc nền", ephemeral=True)
                            except Exception:
                                try:
                                    await interaction.response.send_message("✅ Đã cập nhật nhạc nền.", ephemeral=True)
                                except Exception:
                                    pass

                        sel_bg.callback = _sel_bg_cb
                        view2.add_item(sel_bg)
                except Exception:
                    pass

                # Button: Create video from preview (supports specifying backend and bg_choice)
                class CreateFromPreview(discord.ui.Button):
                    def __init__(self, story_path, view_obj: discord.ui.View | None = None, backend: str = "gemini"):
                        label = f"Tạo video ({backend.capitalize()})"
                        super().__init__(label=label, style=discord.ButtonStyle.success)
                        self.story_path = story_path
                        self.view_obj = view_obj
                        self.backend = (backend or "gemini").lower()

                    async def callback(self2, button_interaction: discord.Interaction):
                        try:
                            api = "http://tts-audio:8000/create_video_from_story"
                            # Build params for create_video_from_story (expects story_path)
                            params2 = {}
                            try:
                                bp = getattr(self2.view_obj, 'base_params', {}) or {}
                                params2.update(bp)
                            except Exception:
                                pass
                            # send basename for story_path (server prefers filename)
                            try:
                                sp = os.path.basename(self2.story_path) if self2.story_path else self2.story_path
                            except Exception:
                                sp = self2.story_path
                            params2.update({"story_path": sp})
                            try:
                                bgc = getattr(self2.view_obj, 'selected_bg', None)
                                if bgc:
                                    params2["bg_choice"] = bgc
                            except Exception:
                                pass
                            # Ensure ai_backend is included so server knows which TTS flow to use
                            try:
                                params2["ai_backend"] = (self2.backend or "gemini").lower()
                            except Exception:
                                pass
                            # include title if present in base_params
                            try:
                                if isinstance(bp, dict) and bp.get('title'):
                                    params2.setdefault('title', bp.get('title'))
                            except Exception:
                                pass

                            status2, info_or_text = await http_post(api, params=params2, timeout=30)
                            if status2 < 200 or status2 >= 300:
                                raise Exception(f"API lỗi: status {status2} - {info_or_text}")
                            info = info_or_text if isinstance(info_or_text, dict) else {}
                            tid = info.get('task_id') or info.get('task') or 'N/A'
                            await button_interaction.response.send_message(f"✅ Đã tạo task video: `{tid}` (AI: {self2.backend.upper()})", ephemeral=True)
                        except Exception as e:
                            await button_interaction.response.send_message(f"⚠️ Lỗi tạo video: {e}", ephemeral=True)

                # Button: View full story (fetch content via /story_content)
                class ViewFullStory(discord.ui.Button):
                    def __init__(self, story_path):
                        super().__init__(label="Xem nội dung đầy đủ", style=discord.ButtonStyle.primary)
                        self.story_path = story_path

                    async def callback(self2, button_interaction: discord.Interaction):
                        try:
                            if not self2.story_path:
                                await button_interaction.response.send_message("⚠️ Không có đường dẫn truyện để hiển thị.", ephemeral=True)
                                return
                            status3, res_or_text = await http_get("http://tts-audio:8000/story_content", params={"story_path": os.path.basename(self2.story_path)}, timeout=30)
                            if status3 < 200 or status3 >= 300:
                                raise Exception(f"API lỗi: status {status3} - {res_or_text}")
                            res = res_or_text if isinstance(res_or_text, dict) else {}
                            chunks = res.get('chunks', [])
                            title2 = res.get('title', os.path.basename(self2.story_path))
                        except Exception as e:
                            await button_interaction.response.send_message(f"⚠️ Lỗi lấy nội dung: {e}", ephemeral=True)
                            return

                        if not chunks:
                            await button_interaction.response.send_message("(Truyện rỗng)", ephemeral=True)
                            return

                        # Send first chunk as response and rest as followups
                        title_line = f"**{title2}**\n\n"
                        try:
                            await button_interaction.response.send_message(title_line + (chunks[0][:1900] if chunks[0] else '(empty)'), ephemeral=True)
                        except Exception:
                            try:
                                await button_interaction.followup.send(title_line, ephemeral=True)
                            except Exception:
                                pass

                        for ch in chunks[1:]:
                            try:
                                await button_interaction.followup.send(ch[:1900], ephemeral=True)
                            except Exception:
                                pass

                # Button: Regenerate the preview using the same base params
                class RegeneratePreview(discord.ui.Button):
                    def __init__(self, view_obj: discord.ui.View | None = None):
                        super().__init__(label="Tạo lại Preview", style=discord.ButtonStyle.secondary)
                        self.view_obj = view_obj

                    async def callback(self2, button_interaction: discord.Interaction):
                        try:
                            await button_interaction.response.defer()
                        except Exception:
                            pass

                        try:
                            bp = getattr(self2.view_obj, 'base_params', {}) or {}
                            # Call preview endpoint with same params
                            status4, data4 = await http_post("http://tts-audio:8000/generate_full_preview", params=bp, timeout=600)
                            if status4 < 200 or status4 >= 300:
                                raise Exception(f"API lỗi: status {status4} - {data4}")
                            payload = data4 if isinstance(data4, dict) else {}

                            title_n = payload.get('title') or 'Không có tiêu đề'
                            summary_n = payload.get('summary') or '(Không có tóm tắt)'
                            file_path_n = payload.get('file_path') or payload.get('file') or None

                            new_emb = discord.Embed(title=title_n[:256], description=(summary_n[:1500] if summary_n else ''), color=0x2F3136)
                            if file_path_n:
                                new_emb.add_field(name="File lưu", value=os.path.basename(file_path_n), inline=False)

                            # Build a new view similar to the original so user can immediately create video
                            new_view = discord.ui.View()
                            setattr(new_view, 'selected_bg', getattr(self2.view_obj, 'selected_bg', None))
                            try:
                                setattr(new_view, 'base_params', dict(bp))
                            except Exception:
                                setattr(new_view, 'base_params', {})

                            # Add background selector if available
                            try:
                                bot_dir3 = os.path.dirname(os.path.abspath(__file__))
                                bgaudio_dir3 = os.path.join(bot_dir3, "bgaudio")
                                bg_options3 = []
                                if os.path.isdir(bgaudio_dir3):
                                    files3 = sorted([f for f in os.listdir(bgaudio_dir3) if f.lower().endswith('.wav')], key=lambda x: x.lower())
                                    for f in files3[:25]:
                                        bg_options3.append(discord.SelectOption(label=sanitize_label(f), value=sanitize_value(f)))

                                if bg_options3:
                                    sel_bg2 = discord.ui.Select(placeholder="Chọn nhạc nền (tùy chọn)", options=bg_options3, min_values=0, max_values=1)

                                    async def _sel_bg_cb2(interaction: discord.Interaction):
                                        try:
                                            new_view.selected_bg = sel_bg2.values[0] if sel_bg2.values else None
                                            if new_view.selected_bg:
                                                await interaction.response.send_message(f"✅ Đã chọn nhạc nền: **{new_view.selected_bg}**", ephemeral=True)
                                            else:
                                                await interaction.response.send_message(f"✅ Bỏ chọn nhạc nền", ephemeral=True)
                                        except Exception:
                                            try:
                                                await interaction.response.send_message("✅ Đã cập nhật nhạc nền.", ephemeral=True)
                                            except Exception:
                                                pass

                                    sel_bg2.callback = _sel_bg_cb2
                                    new_view.add_item(sel_bg2)
                            except Exception:
                                pass

                            # Reuse the local helper button classes to allow viewing full story and creating video
                            try:
                                if file_path_n:
                                    new_view.add_item(ViewFullStory(file_path_n))
                            except Exception:
                                pass

                            try:
                                new_view.add_item(CreateFromPreview(file_path_n, new_view, backend='gemini'))
                                new_view.add_item(CreateFromPreview(file_path_n, new_view, backend='openai'))
                            except Exception:
                                try:
                                    new_view.add_item(CreateFromPreview(file_path_n, new_view, backend='gemini'))
                                except Exception:
                                    pass

                            # Send a fresh ephemeral followup with the regenerated preview
                            try:
                                await button_interaction.followup.send(embed=new_emb, view=new_view, ephemeral=True)
                            except Exception:
                                try:
                                    await button_interaction.response.send_message(embed=new_emb, view=new_view, ephemeral=True)
                                except Exception:
                                    pass
                        except Exception as e:
                            try:
                                await button_interaction.response.send_message(f"⚠️ Lỗi khi tạo lại preview: {e}", ephemeral=True)
                            except Exception:
                                pass

                if file_path:
                    # Add full-story viewer; backend-specific create buttons are added below
                    view2.add_item(ViewFullStory(file_path))

                # Add regenerate button so user can re-run preview with same genparams
                try:
                    view2.add_item(RegeneratePreview(view2))
                except Exception:
                    pass

                # Add create-video-by-backend buttons (Gemini + OpenAI)
                try:
                    view2.add_item(CreateFromPreview(file_path, view2, backend='gemini'))
                    view2.add_item(CreateFromPreview(file_path, view2, backend='openai'))
                except Exception:
                    # fallback: single generic create button
                    view2.add_item(CreateFromPreview(file_path, view2, backend='gemini'))

                await interaction.followup.send(embed=emb, view=view2, ephemeral=True)

            except Exception as e:
                try:
                    await interaction.followup.send(f"⚠️ Lỗi khi tạo preview: {e}", ephemeral=True)
                except Exception:
                    pass

    view = RandomMixView(sample, user_idea=y_tuong)
    embed = build_embed(sample)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="read_story", description="📖 Chọn truyện đã tạo và đọc nội dung (split cho Discord). Có thể tạo video từ truyện đã chọn")
async def read_story(interaction: discord.Interaction):
    """Show a select menu of generated stories, display the story split into multiple messages,
    and offer a button to create a video from the selected story file.
    """
    API_LIST = "http://tts-audio:8000/stories_list"
    try:
        r = requests.get(API_LIST, timeout=10)
        r.raise_for_status()
        data = r.json()
        stories = data.get('stories', [])
    except Exception as e:
        await interaction.response.send_message(f"⚠️ Lỗi khi lấy danh sách truyện: {e}", ephemeral=True)
        return

    if not stories:
        await interaction.response.send_message("ℹ️ Không tìm thấy truyện nào trong thư mục `stories/`.", ephemeral=True)
        return

    # Build select options (limit 25)
    options = []
    for s in stories[:25]:
        label = s.get('name') or os.path.basename(s.get('path', ''))
        # use basename as the option value (must be 1-100 chars) to avoid Discord errors
        value = os.path.basename(s.get('path', ''))
        if not value:
            continue
        options.append(discord.SelectOption(label=sanitize_label(label), value=value))

    class StorySelectView(discord.ui.View):
        def __init__(self, options):
            super().__init__(timeout=120)
            if options:
                sel = discord.ui.Select(placeholder="Chọn 1 truyện để xem nội dung...", options=options, min_values=1, max_values=1)

                async def _sel_callback(interaction: discord.Interaction):
                    selected = sel.values[0]
                    # Fetch content split into chunks
                    try:
                        status, res_or_text = await http_get("http://tts-audio:8000/story_content", params={"story_path": selected}, timeout=15)
                        if status < 200 or status >= 300:
                            raise Exception(f"API lỗi: status {status} - {res_or_text}")
                        res = res_or_text if isinstance(res_or_text, dict) else {}
                        chunks = res.get('chunks', [])
                        title = res.get('title', os.path.basename(selected))
                    except Exception as e:
                        await interaction.response.send_message(f"⚠️ Lỗi khi lấy nội dung truyện: {e}", ephemeral=True)
                        return

                    # Send chunks: first as response, rest as followups
                    if not chunks:
                        await interaction.response.send_message("(Truyện rỗng)", ephemeral=True)
                        return

                    # Create a button to create video
                    class CreateVideoButton(discord.ui.Button):
                        def __init__(self, story_path):
                            super().__init__(label="Tạo video từ truyện này", style=discord.ButtonStyle.primary)
                            self.story_path = story_path

                        async def callback(self, button_interaction: discord.Interaction):
                            # Open a modal so the user can adjust parameters (bg_choice, voice, include_summary, force_refresh)
                            class CreateFromStoryModal(discord.ui.Modal, title="Tạo video từ truyện"):
                                bg_choice = discord.ui.TextInput(
                                    label="Nhạc nền / Tham số (bg, voice, include_summary, force_refresh)",
                                    style=discord.TextStyle.paragraph,
                                    required=False,
                                    placeholder=("Để trống lấy mặc định. Có thể nhập tên nhạc nền hoặc nhiều dòng:\n"
                                                 "Ví dụ:\nmybg.wav\nvoice=gman\ninclude_summary=true\nforce_refresh=false")
                                )

                                def __init__(self, story_path: str):
                                    super().__init__()
                                    self.story_path = story_path

                                async def on_submit(self, interaction: discord.Interaction):
                                    try:
                                        # parse combined bg/voice/include_summary/force_refresh
                                        try:
                                            bg_val, voice_val, include_summary_val, force_refresh_val = parse_bg_voice_and_summary(self.bg_choice.value or "")
                                        except Exception:
                                            # Fallbacks
                                            bg_val = (self.bg_choice.value or "").splitlines()[0] if (self.bg_choice.value or "") else None
                                            voice_val = None
                                            include_summary_val = True
                                            force_refresh_val = False

                                        params = {
                                            "story_path": self.story_path,
                                        }
                                        if bg_val:
                                            params["bg_choice"] = bg_val
                                        if voice_val:
                                            params["voice"] = voice_val
                                        params["include_summary"] = bool(include_summary_val)
                                        params["force_refresh"] = bool(force_refresh_val)

                                        api = "http://tts-audio:8000/create_video_from_story"
                                        status4, info_or_text = await http_post(api, params=params, timeout=15)
                                        if status4 < 200 or status4 >= 300:
                                            raise Exception(f"API lỗi: status {status4} - {info_or_text}")
                                        info = info_or_text if isinstance(info_or_text, dict) else {}
                                        tid = info.get('task_id') or info.get('task') or 'N/A'
                                        await interaction.response.send_message(f"✅ Đã tạo task video: `{tid}`", ephemeral=True)
                                    except Exception as e:
                                        await interaction.response.send_message(f"⚠️ Lỗi tạo video: {e}", ephemeral=True)

                            # show the modal to the user
                            try:
                                await button_interaction.response.send_modal(CreateFromStoryModal(self.story_path))
                            except Exception as e:
                                # fallback: try to notify user of error
                                try:
                                    await button_interaction.response.send_message(f"⚠️ Không thể mở form: {e}", ephemeral=True)
                                except Exception:
                                    pass

                    btn = CreateVideoButton(selected)
                    view = discord.ui.View()
                    view.add_item(btn)

                    # Prepare and send the first message ensuring it's under Discord's 2000-char limit
                    title_line = f"**{title}**\n\n"
                    MAX_CONTENT = 1900  # leave margin for formatting
                    # If title_line itself is too long, truncate the title
                    if len(title_line) > 200:
                        short_title = (title[:80] + '...') if len(title) > 80 else title
                        title_line = f"**{short_title}**\n\n"

                    first_chunk = chunks[0] if chunks else "(Truyện rỗng)"
                    allowed = MAX_CONTENT - len(title_line)
                    if allowed <= 0:
                        # fallback: send only the title
                        first_message = title_line.strip()
                    else:
                        if len(first_chunk) > allowed:
                            first_message = title_line + first_chunk[: allowed - 3] + "..."
                        else:
                            first_message = title_line + first_chunk

                    # Send first message (this creates the interaction response so followups work)
                    try:
                        await interaction.response.send_message(first_message, view=view, ephemeral=True)
                    except Exception as e:
                        # As a last resort, try to send a very small reply
                        try:
                            await interaction.response.send_message(title_line.strip()[:1900], ephemeral=True)
                        except Exception:
                            # cannot send response; bail out
                            await interaction.followup.send("⚠️ Không thể gửi nội dung truyện lên Discord.", ephemeral=True)
                            return

                    # Helper to safely send followup chunks (will split if a chunk is still too long)
                    async def _send_followup_text(text: str):
                        max_len = 1900
                        start = 0
                        while start < len(text):
                            part = text[start : start + max_len]
                            try:
                                await interaction.followup.send(part, ephemeral=True)
                            except Exception:
                                # stop silently if followup fails
                                return
                            start += max_len

                    # Send remaining chunks as followups
                    for c in chunks[1:]:
                        await _send_followup_text(c)

                sel.callback = _sel_callback
                self.add_item(sel)

    view = StorySelectView(options)
    await interaction.response.send_message("Chọn truyện để đọc (dữ liệu lấy từ thư mục `stories/`):", view=view, ephemeral=True)



@bot.tree.command(name="task_status", description="📊 Kiểm tra trạng thái task")
async def task_status(interaction: discord.Interaction, task_id: str):
    """Kiểm tra trạng thái của một task"""
    try:
        API_ENDPOINT = "http://tts-audio:8000/task_status"
        status, data_or_text = await http_get(API_ENDPOINT, params={"task_id": task_id}, timeout=15)
        if status < 200 or status >= 300:
            raise Exception(f"API lỗi: status {status} - {data_or_text}")
        data = data_or_text if isinstance(data_or_text, dict) else {}
        status = data.get("status", "unknown")
        progress = data.get("progress", 0)
        phase = data.get("phase", "N/A")
        error = data.get("error")
        
        # Create progress bar
        bar_length = 20
        filled = int(bar_length * progress / 100)
        bar = "█" * filled + "░" * (bar_length - filled)
        
        # Status emoji
        status_emoji = {
            "pending": "⏳",
            "running": "🔄",
            "completed": "✅",
            "error": "❌"
        }.get(status, "❓")
        
        embed = discord.Embed(
            title=f"{status_emoji} Task Status: {task_id}",
            color=discord.Color.green() if status == "completed" else discord.Color.blue()
        )
        embed.add_field(name="Status", value=status.upper(), inline=True)
        embed.add_field(name="Progress", value=f"{progress}%", inline=True)
        embed.add_field(name="Phase", value=phase, inline=True)
        embed.add_field(name="Progress Bar", value=f"`{bar}` {progress}%", inline=False)
        
        if status == "completed":
            video_files = data.get("video_file", [])
            if video_files:
                embed.add_field(name="📹 Video Files", value="\n".join(f"• `{f}`" for f in video_files[:5]), inline=False)
            story_path = data.get("story_path")
            if story_path:
                embed.add_field(name="📖 Story", value=f"`{os.path.basename(story_path)}`", inline=False)
        
        if error:
            embed.add_field(name="❌ Error", value=f"```\n{error[:500]}\n```", inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except Exception as e:
        await interaction.response.send_message(f"⚠️ Lỗi kiểm tra task: {e}", ephemeral=True)


@bot.tree.command(name="top_task", description="🔎 Trả về task gần nhất để kiểm tra (tùy chọn số lượng)")
async def top_task(interaction: discord.Interaction, count: int = 1):
    """Return the most recently created task(s) from cache/tasks.json for quick inspection.

    Parameters:
        count: number of recent tasks to return (default 1, max 10)
    """
    try:
        API_ENDPOINT = "http://tts-audio:8000/tasks"
        status, tasks_or_text = await http_get(API_ENDPOINT, timeout=15)
        if status < 200 or status >= 300:
            raise Exception(f"API lỗi: status {status} - {tasks_or_text}")
        tasks = tasks_or_text if isinstance(tasks_or_text, list) else tasks_or_text or {}
        if not tasks:
            await interaction.response.send_message("ℹ️ Không có task nào trong danh sách.", ephemeral=True)
            return

        # Server already returns tasks sorted by created_at desc — take first N
        try:
            req = int(count)
        except Exception:
            req = 1
        cap = max(1, min(req, 10))

        selected = tasks[:cap]

        embed = discord.Embed(title=f"🔎 Top {len(selected)} Task(s)", color=discord.Color.orange())

        for idx, tdata in enumerate(selected, start=1):
            tid = tdata.get("task_id") or tdata.get("id") or f"unknown-{idx}"
            status = str(tdata.get("status", "N/A"))
            prog = tdata.get("progress", 0)
            phase = tdata.get("phase", "N/A")
            title = tdata.get("title") or (tdata.get("request_urls") or [None])[0] or tdata.get("task_type") or "(no title)"

            created_raw = tdata.get("created_at")
            try:
                # Server returns ISO timestamp
                created_h = datetime.fromisoformat(created_raw).isoformat() if isinstance(created_raw, str) else str(created_raw)
            except Exception:
                created_h = str(created_raw)

            video_files = tdata.get("video_file") or tdata.get("video_File") or tdata.get("video_files") or tdata.get("video_path")
            vf_str = ""
            if video_files:
                if isinstance(video_files, (list, tuple)):
                    vf_str = ", ".join([os.path.basename(v) for v in video_files[:3]])
                else:
                    vf_str = os.path.basename(str(video_files))

            # Build compact value
            val_lines = [
                f"Title: {str(title)[:120]}",
                f"Status: {status} | Progress: {prog}% | Phase: {phase}",
                f"Created: {created_h}",
            ]
            if vf_str:
                val_lines.append(f"Video: {vf_str}")

            # If there are video files, also add a dedicated field showing up to 5 files
            if video_files:
                try:
                    if isinstance(video_files, (list, tuple)):
                        vf_display = "\n".join(f"• `{v}`" for v in video_files[:5])
                    else:
                        vf_display = f"• `{str(video_files)}`"
                    embed.add_field(name="📹 Video Files", value=vf_display, inline=False)
                except Exception:
                    # Fallback: add a short single-line mention
                    embed.add_field(name="📹 Video Files", value=(vf_str or "(see details)"), inline=False)
            if tdata.get("error"):
                err = str(tdata.get("error"))
                val_lines.append(f"Error: {err[:200]}")

            field_name = f"{idx}. {tid}"
            embed.add_field(name=field_name, value="\n".join(val_lines), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    except Exception as e:
        await interaction.response.send_message(f"⚠️ Lỗi khi đọc task từ API: {e}", ephemeral=True)


# ==========================
# TikTok Ad Video Form
# ==========================
class TikTokAdMultiForm(discord.ui.Modal, title="🎬 Tạo Video TikTok (Multi-Image)"):
    """Form tạo video quảng cáo TikTok từ nhiều ảnh reference"""
    
    style = discord.ui.TextInput(
        label="Phong cách (1-4)",
        style=discord.TextStyle.short,
        placeholder="1=trẻ trung năng động | 2=mềm mại nữ tính | 3=storytelling/sang trọng | 4=hiện đại unisex",
        required=False,
        default="1"
    )
  
    product_type = discord.ui.TextInput(
        label="Loại sản phẩm (1-5)",
        style=discord.TextStyle.short,
        placeholder="1=fashion | 2=electronics | 3=home_goods | 4=beauty | 5=food",
        required=False,
        default="1"
    )
    
    prompt_text = discord.ui.TextInput(
        label="Mô tả sản phẩm",
        style=discord.TextStyle.paragraph,
        placeholder="VD: Áo thun nam big size chất cotton cao cấp...",
        required=False
    )
    
    bg_choice = discord.ui.TextInput(
        label="Nhạc nền (tùy chọn)",
        style=discord.TextStyle.short,
        placeholder="Để trống = auto chọn từ music_folder",
        required=False
    )
    
    output_filename = discord.ui.TextInput(
        label="Tên file output (tùy chọn)",
        style=discord.TextStyle.short,
        placeholder="VD: ao_thun_bigsize.mp4 (để trống = tên tự động)",
        required=False
    )

    def __init__(self, images_base64: list, image_filenames: list):
        super().__init__()
        self.images_base64 = images_base64
        self.image_filenames = image_filenames

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Map style number to name
            style_map = {
                "1": "trẻ trung năng động",
                "2": "mềm mại nữ tính",
                "3": "storytelling / sang trọng",
                "4": "hiện đại unisex"
            }
            style_num = (self.style.value or "1").strip()
            style_name = style_map.get(style_num, "trẻ trung năng động")
            
            # Map product type number to name
            product_type_map = {
                "1": "fashion",
                "2": "electronics",
                "3": "home_goods",
                "4": "beauty",
                "5": "food"
            }
            product_type_num = (self.product_type.value or "1").strip()
            product_type_name = product_type_map.get(product_type_num, "fashion")
            
            # Call API endpoint
            API_ENDPOINT = "http://tts-audio:8000/tiktok_ad/create_from_multi_images"
            
            # Create JSON payload
            payload = {
                "images_base64": self.images_base64,
                "image_filenames": self.image_filenames,
                "style": style_name
            }
            
            if product_type_name:
                payload["product_type"] = product_type_name
            
            if self.prompt_text.value.strip():
                payload["prompt_text"] = self.prompt_text.value.strip()
            
            if self.bg_choice.value.strip():
                payload["bg_choice"] = self.bg_choice.value.strip()
            
            if self.output_filename.value.strip():
                payload["output_filename"] = self.output_filename.value.strip()
            
            await interaction.response.defer(ephemeral=True)
            
            timeout_obj = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                async with session.post(API_ENDPOINT, json=payload) as resp:
                    status = resp.status
                    try:
                        data = await resp.json()
                    except Exception:
                        data = {"error": await resp.text()}
            
            if status >= 200 and status < 300:
                task_id = data.get("task_id", "N/A")
                msg = (
                    f"✅ **Đã tạo task video quảng cáo TikTok (Multi-Image)!**\n"
                    f"📋 Task ID: `{task_id}`\n"
                    f"🎨 Style: {style_name}\n"
                    f"🖼️ Images: {len(self.images_base64)} ảnh\n\n"
                    f"💡 Dùng `/task_status {task_id}` để theo dõi tiến trình\n"
                    f"⏱️ Thời gian ước tính: 5-15 phút"
                )
            else:
                error_msg = data.get("error", data)
                msg = f"⚠️ Lỗi từ API (status {status}): {error_msg}"
            
            await interaction.followup.send(msg[:2000], ephemeral=True)
            
        except Exception as e:
            try:
                await interaction.followup.send(f"⚠️ Lỗi khi gọi API: {e}", ephemeral=True)
            except Exception:
                await interaction.response.send_message(f"⚠️ Lỗi: {e}", ephemeral=True)


class TikTokAdForm(discord.ui.Modal, title="🎬 Tạo Video Quảng Cáo TikTok"):
    """Form tạo video quảng cáo TikTok từ ảnh sản phẩm"""
    
    style = discord.ui.TextInput(
        label="Phong cách (1-4)",
        style=discord.TextStyle.short,
        placeholder="1=trẻ trung năng động | 2=mềm mại nữ tính | 3=storytelling/sang trọng | 4=hiện đại unisex",
        required=False,
        default="1"
    )
  
    product_type = discord.ui.TextInput(
        label="Loại sản phẩm (1-5)",
        style=discord.TextStyle.short,
        placeholder="1=fashion | 2=electronics | 3=home_goods | 4=beauty | 5=food",
        required=False,
        default="1"
    )
    
    prompt_text = discord.ui.TextInput(
        label="Mô tả sản phẩm",
        style=discord.TextStyle.paragraph,
        placeholder="VD: Áo thun nam big size chất cotton cao cấp...",
        required=False
    )
    
    bg_choice = discord.ui.TextInput(
        label="Nhạc nền (tùy chọn)",
        style=discord.TextStyle.short,
        placeholder="Để trống = auto chọn từ music_folder",
        required=False
    )
    
    output_filename = discord.ui.TextInput(
        label="Tên file output (tùy chọn)",
        style=discord.TextStyle.short,
        placeholder="VD: ao_thun_bigsize.mp4 (để trống = tên tự động)",
        required=False
    )

    def __init__(self, image_base64: str, image_filename: str):
        super().__init__()
        self.image_base64 = image_base64
        self.image_filename = image_filename

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Map style number to name
            style_map = {
                "1": "trẻ trung năng động",
                "2": "mềm mại nữ tính",
                "3": "storytelling / sang trọng",
                "4": "hiện đại unisex"
            }
            style_num = (self.style.value or "1").strip()
            style_name = style_map.get(style_num, "trẻ trung năng động")
            
            # Map product type number to name
            product_type_map = {
                "1": "fashion",
                "2": "electronics",
                "3": "home_goods",
                "4": "beauty",
                "5": "food"
            }
            product_type_num = (self.product_type.value or "1").strip()
            product_type_name = product_type_map.get(product_type_num, "fashion")
            
            # Prepare API parameters - location is always us-central1
            params = {
                "style": style_name
            }
            
            if self.prompt_text.value.strip():
                params["prompt_text"] = self.prompt_text.value.strip()
            
            if self.output_filename.value.strip():
                params["output_filename"] = self.output_filename.value.strip()
            
            # Call API endpoint
            API_ENDPOINT = "http://tts-audio:8000/tiktok_ad/create_from_base64"
            
            # Create JSON payload
            payload = {
                "image_base64": self.image_base64,
                "image_filename": self.image_filename,
                "style": style_name
            }
            
            if product_type_name:
                payload["product_type"] = product_type_name
            
            if self.prompt_text.value.strip():
                payload["prompt_text"] = self.prompt_text.value.strip()
            
            if self.bg_choice.value.strip():
                payload["bg_choice"] = self.bg_choice.value.strip()
            
            if self.output_filename.value.strip():
                payload["output_filename"] = self.output_filename.value.strip()
            
            await interaction.response.defer(ephemeral=True)
            
            timeout_obj = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                async with session.post(API_ENDPOINT, json=payload) as resp:
                    status = resp.status
                    try:
                        data = await resp.json()
                    except Exception:
                        data = {"error": await resp.text()}
            
            if status >= 200 and status < 300:
                task_id = data.get("task_id", "N/A")
                msg = (
                    f"✅ **Đã tạo task video quảng cáo TikTok!**\n"
                    f"📋 Task ID: `{task_id}`\n"
                    f"🎨 Style: {style_name}\n"
                    f"🖼️ Image: {self.image_filename}\n\n"
                    f"💡 Dùng `/task_status {task_id}` để theo dõi tiến trình\n"
                    f"⏱️ Thời gian ước tính: 5-15 phút"
                )
            else:
                error_msg = data.get("error", data)
                msg = f"⚠️ Lỗi từ API (status {status}): {error_msg}"
            
            await interaction.followup.send(msg[:2000], ephemeral=True)
            
        except Exception as e:
            try:
                await interaction.followup.send(f"⚠️ Lỗi khi gọi API: {e}", ephemeral=True)
            except Exception:
                await interaction.response.send_message(f"⚠️ Lỗi: {e}", ephemeral=True)


async def tiktok_ad_command(
    interaction: discord.Interaction,
    image: discord.Attachment
):
    """
    Command để tạo video quảng cáo TikTok.
    User phải attach file ảnh khi gọi command này.
    """
    try:
        # Check if it's an image
        if not any(image.filename.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.jfif', '.webp']):
            await interaction.response.send_message(
                "⚠️ File phải là ảnh (jpg/png/jfif/webp)!",
                ephemeral=True
            )
            return
        
        # Download image and convert to base64
        await interaction.response.defer(ephemeral=True)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(image.url) as resp:
                if resp.status != 200:
                    await interaction.followup.send("⚠️ Không thể tải ảnh!", ephemeral=True)
                    return
                image_data = await resp.read()
        
        import base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        # Create a view with button to open modal
        class TikTokAdView(discord.ui.View):
            def __init__(self, img_b64, img_filename):
                super().__init__(timeout=300)
                self.img_b64 = img_b64
                self.img_filename = img_filename
            
            @discord.ui.button(label="📝 Điền thông tin", style=discord.ButtonStyle.primary)
            async def open_form(self, interaction: discord.Interaction, button):
                await interaction.response.send_modal(
                    TikTokAdForm(image_base64=self.img_b64, image_filename=self.img_filename)
                )
        
        view = TikTokAdView(image_base64, image.filename)
        embed = discord.Embed(
            title="🎬 TẠO VIDEO QUẢNG CÁO TIKTOK",
            description=f"✅ Đã nhận ảnh: **{image.filename}**\n\nNhấn button bên dưới để điền thông tin",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=image.url)
        
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        
    except Exception as e:
        try:
            await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)
        except Exception:
            await interaction.response.send_message(f"⚠️ Lỗi: {e}", ephemeral=True)


@bot.tree.command(name="fashion_ad", description="🎬 Tạo video quảng cáo thời trang (catwalk) — music only, no TTS")
async def fashion_ad_command(
    interaction: discord.Interaction,
    image: discord.Attachment
):
    """
    Create a fashion ad (single image) with music-only (no TTS). Calls server endpoint to queue a task.
    """
    try:
        # Validate image
        if not any(image.filename.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.jfif', '.webp']):
            await interaction.response.send_message(
                "⚠️ File phải là ảnh (jpg/png/jfif/webp)!",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        async with aiohttp.ClientSession() as session:
            async with session.get(image.url) as resp:
                image_data = await resp.read()

        image_b64 = base64.b64encode(image_data).decode('utf-8')

        # Fetch music list from server and ask user to choose (or none/auto)
        try:
            status, ml = await http_get("http://tts-audio:8000/music_list", timeout=10)
            music_files = ml.get("music_files", []) if isinstance(ml, dict) else []
        except Exception:
            music_files = []

        # Build select options
        options = [
            discord.SelectOption(label="🔇 Không dùng nhạc nền", value="no_music", description="Chỉ dùng hình ảnh, không thêm nhạc"),
            discord.SelectOption(label="🎲 Auto chọn ngẫu nhiên", value="auto", description="Server tự chọn nhạc phù hợp")
        ]
        for mf in music_files[:20]:
            options.append(discord.SelectOption(label=sanitize_label(f"🎵 {mf}"), value=mf, description=f"{mf}"))

        class MusicSelectView(discord.ui.View):
            def __init__(self, image_b64, image_filename, options):
                super().__init__(timeout=300)
                self.image_b64 = image_b64
                self.image_filename = image_filename
                self.options = options
                sel = discord.ui.Select(placeholder="Chọn nhạc nền cho quảng cáo (tùy chọn)", options=options, min_values=1, max_values=1)
                sel.callback = self.on_select
                self.add_item(sel)

            async def on_select(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True)
                selected = interaction.data['values'][0]

                # Map selection to bg_choice value expected by server
                if selected == "no_music":
                    bg_choice = "1"
                elif selected == "auto":
                    bg_choice = ""
                else:
                    bg_choice = selected

                API_ENDPOINT = "http://tts-audio:8000/tiktok_ad/create_from_base64"
                payload = {
                    "image_base64": self.image_b64,
                    "image_filename": self.image_filename,
                    "style": "storytelling / sang trọng",
                    "product_type": "fashion",
                    "skip_tts": True,
                    "bg_choice": bg_choice
                }

                timeout_obj = aiohttp.ClientTimeout(total=120)
                try:
                    async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                        async with session.post(API_ENDPOINT, json=payload) as resp2:
                            try:
                                data2 = await resp2.json()
                            except Exception:
                                text2 = await resp2.text()
                                data2 = {"error": text2}

                    if resp2.status >= 200 and resp2.status < 300:
                        task_id = data2.get("task_id", "N/A")
                        msg = (
                            f"✅ **Đã tạo task Fashion Ad (music-only)!**\n"
                            f"📋 Task ID: `{task_id}`\n"
                            f"🎨 Style: storytelling / sang trọng\n"
                            f"🖼️ Image: {self.image_filename}\n"
                            f"🎵 Chọn nhạc: {('Không dùng' if bg_choice=='1' else ('Auto' if bg_choice=='' else bg_choice))}\n\n"
                            f"💡 Dùng `/task_status {task_id}` để theo dõi tiến trình\n"
                            f"⏱️ Thời gian ước tính: 5-15 phút"
                        )
                    else:
                        err = data2.get('error') or data2
                        msg = f"⚠️ Lỗi từ API (status {resp2.status}): {err}"

                except Exception as e:
                    msg = f"⚠️ Lỗi khi gọi API tạo task: {e}"

                try:
                    await interaction.followup.send(msg[:2000], ephemeral=True)
                except Exception:
                    await interaction.response.send_message(msg[:2000], ephemeral=True)

        # Send selection view
        view = MusicSelectView(image_b64, image.filename, options)
        await interaction.followup.send("Chọn nhạc nền cho quảng cáo (hoặc chọn Auto/No Music):", view=view, ephemeral=True)

    except Exception as e:
        try:
            await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)
        except Exception:
            await interaction.response.send_message(f"⚠️ Lỗi: {e}", ephemeral=True)


async def tiktok_ad_multi_command(
    interaction: discord.Interaction,
    image1: discord.Attachment,
    image2: discord.Attachment = None,
    image3: discord.Attachment = None
):
    """
    Command để tạo video quảng cáo TikTok từ nhiều ảnh reference.
    User phải attach ít nhất 1 ảnh, tối đa 3 ảnh.
    """
    try:
        images = [image1]
        if image2:
            images.append(image2)
        if image3:
            images.append(image3)
        
        # Check if all are images
        for img in images:
            if not any(img.filename.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.jfif', '.webp']):
                await interaction.response.send_message(
                    f"⚠️ File {img.filename} phải là ảnh (jpg/png/jfif/webp)!",
                    ephemeral=True
                )
                return
        
        # Download images and convert to base64
        await interaction.response.defer(ephemeral=True)
        
        import base64
        images_base64 = []
        image_filenames = []
        
        for img in images:
            async with aiohttp.ClientSession() as session:
                async with session.get(img.url) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(f"⚠️ Không thể tải ảnh {img.filename}!", ephemeral=True)
                        return
                    image_data = await resp.read()
            
            images_base64.append(base64.b64encode(image_data).decode('utf-8'))
            image_filenames.append(img.filename)
        
        # Create a view with button to open modal
        class TikTokAdMultiView(discord.ui.View):
            def __init__(self, imgs_b64, img_filenames):
                super().__init__(timeout=300)
                self.imgs_b64 = imgs_b64
                self.img_filenames = img_filenames
            
            @discord.ui.button(label="📝 Điền thông tin", style=discord.ButtonStyle.primary)
            async def open_form(self, interaction: discord.Interaction, button):
                await interaction.response.send_modal(
                    TikTokAdMultiForm(images_base64=self.imgs_b64, image_filenames=self.img_filenames)
                )
        
        view = TikTokAdMultiView(images_base64, image_filenames)
        embed = discord.Embed(
            title="🎬 TẠO VIDEO QUẢNG CÁO TIKTOK (MULTI-IMAGE)",
            description=f"✅ Đã nhận **{len(images)}** ảnh:\n" + "\n".join([f"• {fn}" for fn in image_filenames]) + "\n\nNhấn button bên dưới để điền thông tin",
            color=discord.Color.green()
        )
        if images:
            embed.set_thumbnail(url=images[0].url)
        
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        
    except Exception as e:
        try:
            await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)
        except Exception:
            await interaction.response.send_message(f"⚠️ Lỗi: {e}", ephemeral=True)


@bot.tree.command(name="fashion_ad_multi", description="🎬 Tạo video quảng cáo thời trang (1-3 ảnh) — music only, no TTS")
async def fashion_ad_multi_command(
    interaction: discord.Interaction,
    image1: discord.Attachment,
    image2: discord.Attachment = None,
    image3: discord.Attachment = None
):
    """
    Create a fashion ad from multiple images (1-3) with music-only (no TTS).
    Calls the existing multi-image endpoint with skip_tts=True and product_type='fashion'.
    """
    try:
        images = [image1]
        if image2:
            images.append(image2)
        if image3:
            images.append(image3)

        # Validate
        for img in images:
            if not any(img.filename.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.jfif', '.webp']):
                await interaction.response.send_message("⚠️ Tất cả files phải là ảnh (jpg/png/jfif/webp)", ephemeral=True)
                return

        await interaction.response.defer(ephemeral=True)
        images_base64 = []
        image_filenames = []
        for img in images:
            async with aiohttp.ClientSession() as session:
                async with session.get(img.url) as resp:
                    image_data = await resp.read()
            images_base64.append(base64.b64encode(image_data).decode('utf-8'))
            image_filenames.append(img.filename)

        # Ask user to choose music from server (or no/auto)
        try:
            status, ml = await http_get("http://tts-audio:8000/music_list", timeout=10)
            music_files = ml.get("music_files", []) if isinstance(ml, dict) else []
        except Exception:
            music_files = []

        options = [
            discord.SelectOption(label="🔇 Không dùng nhạc nền", value="no_music", description="Chỉ dùng hình ảnh, không thêm nhạc"),
            discord.SelectOption(label="🎲 Auto chọn ngẫu nhiên", value="auto", description="Server tự chọn nhạc phù hợp")
        ]
        for mf in music_files[:20]:
            options.append(discord.SelectOption(label=sanitize_label(f"🎵 {mf}"), value=mf, description=f"{mf}"))

        class MusicSelectMultiView(discord.ui.View):
            def __init__(self, imgs_b64, img_filenames, options):
                super().__init__(timeout=300)
                self.imgs_b64 = imgs_b64
                self.img_filenames = img_filenames
                sel = discord.ui.Select(placeholder="Chọn nhạc nền cho quảng cáo (tùy chọn)", options=options, min_values=1, max_values=1)
                sel.callback = self.on_select
                self.add_item(sel)

            async def on_select(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True)
                selected = interaction.data['values'][0]
                if selected == "no_music":
                    bg_choice = "1"
                elif selected == "auto":
                    bg_choice = ""
                else:
                    bg_choice = selected

                API_ENDPOINT = "http://tts-audio:8000/tiktok_ad/create_from_multi_images"
                payload = {
                    "images_base64": self.imgs_b64,
                    "image_filenames": self.img_filenames,
                    "style": "storytelling / sang trọng",
                    "product_type": "fashion",
                    "skip_tts": True,
                    "merge_multi": True,
                    "bg_choice": bg_choice
                }

                timeout_obj = aiohttp.ClientTimeout(total=240)
                try:
                    async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                        async with session.post(API_ENDPOINT, json=payload) as resp2:
                            try:
                                data2 = await resp2.json()
                            except Exception:
                                text2 = await resp2.text()
                                data2 = {"error": text2}

                    if resp2.status >= 200 and resp2.status < 300:
                        task_id = data2.get("task_id", "N/A")
                        msg = (
                            f"✅ **Đã tạo task Fashion Ad (music-only)!**\n"
                            f"📋 Task ID: `{task_id}`\n"
                            f"🎨 Style: storytelling / sang trọng\n"
                            f"🖼️ Images: {len(self.imgs_b64)} ảnh\n"
                            f"🎵 Chọn nhạc: {('Không dùng' if bg_choice=='1' else ('Auto' if bg_choice=='' else bg_choice))}\n\n"
                            f"💡 Dùng `/task_status {task_id}` để theo dõi tiến trình\n"
                            f"⏱️ Thời gian ước tính: 5-15 phút"
                        )
                    else:
                        err = data2.get('error') or data2
                        msg = f"⚠️ Lỗi từ API (status {resp2.status}): {err}"

                except Exception as e:
                    msg = f"⚠️ Lỗi khi gọi API tạo task: {e}"

                try:
                    await interaction.followup.send(msg[:2000], ephemeral=True)
                except Exception:
                    await interaction.response.send_message(msg[:2000], ephemeral=True)

        view = MusicSelectMultiView(images_base64, image_filenames, options)
        await interaction.followup.send("Chọn nhạc nền cho quảng cáo (hoặc chọn Auto/No Music):", view=view, ephemeral=True)

    except Exception as e:
        try:
            await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)
        except Exception:
            await interaction.response.send_message(f"⚠️ Lỗi: {e}", ephemeral=True)


async def tiktok_ad_sessions_command(interaction: discord.Interaction):
    """
    Lấy danh sách tất cả sessions và cho phép:
    - Xem metadata chi tiết
    - Re-render scene
    - Re-render toàn bộ video
    """

    await interaction.response.defer(ephemeral=True)
    
    try:
        API_ENDPOINT = "http://tts-audio:8000/tiktok_ad/sessions"
        status, data = await http_get(API_ENDPOINT, timeout=30)
        
        if status < 200 or status >= 300:
            await interaction.followup.send(f"⚠️ API lỗi: {data}", ephemeral=True)
            return
        
        sessions = data.get("sessions", [])
        total = data.get("total", 0)
        
        if not sessions:
            await interaction.followup.send("ℹ️ Chưa có session nào được tạo.", ephemeral=True)
            return
        
        # Tạo embed hiển thị sessions (max 25 sessions gần nhất)
        embed = discord.Embed(
            title="📋 DANH SÁCH SESSIONS VIDEO TIKTOK",
            description=f"Tổng số: **{total}** sessions\nHiển thị **{min(25, len(sessions))}** sessions gần nhất",
            color=discord.Color.blue()
        )
        
        for i, session in enumerate(sessions[:10], 1):
            session_id = session.get("session_id", "N/A")
            final_video = session.get("final_video", "N/A")
            style = session.get("style", "N/A")
            num_scenes = session.get("num_scenes", 0)
            created_at = session.get("created_at", "N/A")
            
            # Tạo link tải video và link xem video
            from urllib.parse import quote_plus
            download_link = f"https://sandbox.travel.com.vn/api/download-video?download=1&video_name={quote_plus(final_video)}"
            view_link = f"https://sandbox.travel.com.vn/api/download-video?video_name={quote_plus(final_video)}"
            
            # Extract filename from path
            import os
            video_filename = os.path.basename(final_video) if final_video != "N/A" else "N/A"
            
            embed.add_field(
                name=f"{i}. 🎬 {video_filename} - {session_id}",
                value=(
                    f"📝 Style: {style}\n"
                    f"🎞️ Scenes: {num_scenes}\n"
                    f"🕐 {created_at}\n"
                    f"👁️ [Xem video]({view_link}) | ⬇️ [Tải video]({download_link})"
                ),
                inline=False
            )
        
        # Tạo view với select menu và buttons để chọn action
        class SessionActionView(discord.ui.View):
            def __init__(self, sessions):
                super().__init__(timeout=300)
                self.sessions = sessions
                self.selected_session_id = None
                
                # Tạo select menu để chọn session
                import os
                options = [
                    discord.SelectOption(
                        label=sanitize_label(f"{os.path.basename(s.get('final_video', 'N/A'))} - {s.get('session_id', 'N/A')}"),
                        value=s.get('session_id', ''),
                        description=f"{s.get('style', 'N/A')} | {s.get('num_scenes', 0)} scenes"
                    )
                    for s in sessions[:25]  # Discord limit 25 options
                ]
                
                if options:
                    select = discord.ui.Select(
                        placeholder="Chọn session để thao tác...",
                        options=options
                    )
                    select.callback = self.on_session_select
                    self.add_item(select)
            
            async def on_session_select(self, interaction: discord.Interaction):
                self.selected_session_id = interaction.data['values'][0]
                await interaction.response.send_message(
                    f"✅ Đã chọn session: **{self.selected_session_id}**\nBây giờ nhấn button bên dưới để thao tác.",
                    ephemeral=True
                )
            
            @discord.ui.button(label="📖 Xem metadata", style=discord.ButtonStyle.primary)
            async def view_metadata(self, interaction: discord.Interaction, button):
                if not self.selected_session_id:
                    await interaction.response.send_message("⚠️ Vui lòng chọn session trước!", ephemeral=True)
                    return
                
                await interaction.response.defer(ephemeral=True)
                
                try:
                    # Load metadata trực tiếp
                    API_ENDPOINT = f"http://tts-audio:8000/tiktok_ad/metadata/{self.selected_session_id}"
                    status, data = await http_get(API_ENDPOINT, timeout=30)
                    
                    if status < 200 or status >= 300:
                        await interaction.followup.send(f"⚠️ Không tìm thấy session: {data}", ephemeral=True)
                        return
                    
                    # Hiển thị metadata
                    scenes = data.get("scenes", [])
                    style = data.get("style", "N/A")
                    final_video = data.get("final_video", "N/A")
                    num_scenes = data.get("num_scenes", 0)
                    prompt_text = data.get("prompt_text", "N/A")
                    
                    embed = discord.Embed(
                        title=f"📖 METADATA - {self.selected_session_id}",
                        description=f"**Style:** {style}\n**Prompt:** {prompt_text[:100]}...\n**Video:** {final_video}\n**Scenes:** {num_scenes}",
                        color=discord.Color.green()
                    )
                    
                    # Hiển thị từng scene
                    for i, scene in enumerate(scenes, 1):
                        scene_num = scene.get("scene_number", i)
                        purpose = scene.get("purpose", "N/A")
                        duration = scene.get("duration", 0)
                        script = scene.get("script", "N/A")
                        visual = scene.get("visual_prompt", "N/A")
                        
                        embed.add_field(
                            name=f"Scene {scene_num} - {purpose} ({duration}s)",
                            value=f"📝 Script: {script[:100]}...\n🎨 Visual: {visual[:100]}...",
                            inline=False
                        )
                    
                    # Tạo EditSceneView với select menu để chọn scene hoặc TTS cần chỉnh sửa
                    class EditSceneView(discord.ui.View):
                        def __init__(self, session_id, scenes_data, style):
                            super().__init__(timeout=300)
                            self.session_id = session_id
                            self.scenes_data = scenes_data
                            self.style = style
                            
                            # Tạo select menu để chọn scene cần chỉnh sửa HOẶC chỉnh sửa TTS
                            options = [
                                discord.SelectOption(
                                    label="🎤 Chỉnh sửa TTS Script (toàn bộ)",
                                    value="edit_tts",
                                    description="Sửa nội dung TTS cho tất cả scenes",
                                    emoji="🎤"
                                )
                            ]
                            
                            # Thêm options cho từng scene
                            for i, s in enumerate(scenes_data, 1):
                                options.append(
                                    discord.SelectOption(
                                        label=sanitize_label(f"Scene {s.get('scene_number', i)} - {s.get('purpose', 'N/A')}"),
                                        value=f"scene_{s.get('scene_number', i)}",
                                        description=f"{s.get('duration', 0)}s - Sửa visual prompt",
                                        emoji="🎬"
                                    )
                                )
                            
                            if options:
                                select = discord.ui.Select(
                                    placeholder="Chọn scene hoặc TTS để chỉnh sửa...",
                                    options=options,
                                    row=0
                                )
                                select.callback = self.on_select
                                self.add_item(select)
                        
                        async def on_select(self, interaction: discord.Interaction):
                            selected_value = interaction.data['values'][0]
                            
                            # Nếu chọn edit TTS
                            if selected_value == "edit_tts":
                                # Gộp script từ tất cả scenes với ngắt dòng giữa các scene
                                full_script_parts = []
                                for i, scene in enumerate(self.scenes_data):
                                    script = scene.get('script', '')
                                    if script:
                                        full_script_parts.append(script)
                                
                                # Join với newline để mỗi scene 1 dòng
                                full_script = "\n".join(full_script_parts)
                                
                                await interaction.response.send_modal(
                                    EditTTSScriptForm(
                                        session_id=self.session_id,
                                        current_script=full_script,
                                        style=self.style
                                    )
                                )
                            # Nếu chọn scene
                            elif selected_value.startswith("scene_"):
                                scene_num = int(selected_value.replace("scene_", ""))
                                
                                # Tìm scene data
                                scene_data = None
                                for s in self.scenes_data:
                                    if s.get('scene_number') == scene_num:
                                        scene_data = s
                                        break
                                
                                if scene_data:
                                    # Mở modal với thông tin đã điền sẵn
                                    current_visual = scene_data.get('visual_prompt', '')
                                    await interaction.response.send_modal(
                                        RerenderSceneForm(
                                            session_id=self.session_id,
                                            scene_number=scene_num,
                                            current_visual_prompt=current_visual
                                        )
                                    )
                                else:
                                    await interaction.response.send_message(
                                        f"⚠️ Không tìm thấy scene {scene_num}",
                                        ephemeral=True
                                    )
                    
                    view = EditSceneView(self.selected_session_id, scenes, style)
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                    
                except Exception as e:
                    await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)
            
            @discord.ui.button(label="🔧 Reassemble video", style=discord.ButtonStyle.success, row=1)
            async def reassemble_video(self, interaction: discord.Interaction, button):
                if not self.selected_session_id:
                    await interaction.response.send_message("⚠️ Vui lòng chọn session trước!", ephemeral=True)
                    return
                
                await interaction.response.defer(ephemeral=True)
                
                try:
                    # Load metadata và reassemble trực tiếp (không mở modal)
                    API_META = f"http://tts-audio:8000/tiktok_ad/metadata/{self.selected_session_id}"
                    status_meta, meta_data = await http_get(API_META, timeout=30)
                    
                    if status_meta < 200 or status_meta >= 300:
                        await interaction.followup.send(f"⚠️ Không load được metadata: {meta_data}", ephemeral=True)
                        return
                    
                    scene_videos_dict = meta_data.get("scene_videos", {})
                    
                    # Reassemble với scene_videos từ metadata
                    import json
                    scene_videos_json = json.dumps(scene_videos_dict)
                    
                    API_REASSEMBLE = "http://tts-audio:8000/tiktok_ad/reassemble"
                    params = {
                        "session_id": self.selected_session_id,
                        "scene_videos": scene_videos_json
                    }
                    
                    await interaction.followup.send(
                        f"🔧 Đang reassemble video cho session {self.selected_session_id}...\n"
                        "⏳ Vui lòng chờ...",
                        ephemeral=True
                    )
                    
                    status, data = await http_post(API_REASSEMBLE, params=params, timeout=120)
                    
                    if status < 200 or status >= 300:
                        await interaction.followup.send(f"⚠️ Lỗi reassemble: {data}", ephemeral=True)
                        return
                    
                    final_video = data.get("final_video", "N/A")
                    download_url = data.get("download_url", "N/A")
                    
                    # Tạo view với 2 buttons
                    from urllib.parse import quote_plus
                    view_url = f"https://sandbox.travel.com.vn/api/download-video?video_name={quote_plus(final_video)}"
                    
                    class VideoActionsView(discord.ui.View):
                        def __init__(self, view_link, download_link):
                            super().__init__(timeout=None)
                            self.add_item(discord.ui.Button(
                                label="👁️ Xem video",
                                url=view_link,
                                style=discord.ButtonStyle.link
                            ))
                            self.add_item(discord.ui.Button(
                                label="⬇️ Tải video",
                                url=download_link,
                                style=discord.ButtonStyle.link
                            ))
                    
                    embed = discord.Embed(
                        title="✅ Video đã reassemble thành công!",
                        description=(
                            f"**Session:** {self.selected_session_id}\n"
                            f"**Video:** {final_video}"
                        ),
                        color=discord.Color.green()
                    )
                    
                    await interaction.followup.send(embed=embed, view=VideoActionsView(view_url, download_url), ephemeral=True)
                    
                except Exception as e:
                    await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)
            
            @discord.ui.button(label="🎨 Regenerate Visual", style=discord.ButtonStyle.primary, row=2)
            async def regenerate_visual(self, interaction: discord.Interaction, button):
                """Mở flow regenerate visual với AI hoặc manual edit"""
                if not self.selected_session_id:
                    await interaction.response.send_message("⚠️ Vui lòng chọn session trước!", ephemeral=True)
                    return
                
                await interaction.response.defer(ephemeral=True)
                
                try:
                    # Load metadata để lấy danh sách scenes
                    API_ENDPOINT = f"http://tts-audio:8000/tiktok_ad/metadata/{self.selected_session_id}"
                    status, data = await http_get(API_ENDPOINT, timeout=30)
                    
                    if status < 200 or status >= 300:
                        await interaction.followup.send(f"⚠️ Không tìm thấy session: {data}", ephemeral=True)
                        return
                    
                    scenes = data.get("scenes", [])
                    if not scenes:
                        await interaction.followup.send("⚠️ Session này không có scene nào!", ephemeral=True)
                        return
                    
                    # Tạo view với select menu để chọn scene
                    class SelectSceneForVisualView(discord.ui.View):
                        def __init__(self, session_id, scenes_data):
                            super().__init__(timeout=300)
                            self.session_id = session_id
                            self.scenes_data = scenes_data
                            
                            # Tạo select menu với danh sách scenes
                            options = []
                            for s in scenes_data:
                                scene_num = s.get("scene_number")
                                purpose = s.get("purpose", "N/A")
                                duration = s.get("duration", 0)
                                options.append(
                                    discord.SelectOption(
                                        label=sanitize_label(f"Scene {scene_num} - {purpose} ({duration}s)"),
                                        value=str(scene_num),
                                        description=f"Visual: {s.get('visual_prompt', '')[:50]}...",
                                        emoji="🎬"
                                    )
                                )
                            
                            select = discord.ui.Select(
                                placeholder="Chọn scene cần regenerate visual...",
                                options=options
                            )
                            select.callback = self.on_select
                            self.add_item(select)
                        
                        async def on_select(self, interaction: discord.Interaction):
                            scene_num = int(interaction.data["values"][0])
                            
                            # Tìm scene data
                            scene = None
                            for s in self.scenes_data:
                                if s.get("scene_number") == scene_num:
                                    scene = s
                                    break
                            
                            if scene:
                                current_visual = scene.get("visual_prompt", "")
                                # Hiển thị options: AI tạo mới hoặc tự chỉnh sửa
                                await interaction.response.send_message(
                                    f"**Scene {scene_num} - {scene.get('purpose', 'N/A')}**\n\n"
                                    f"🎨 Visual hiện tại: {current_visual[:200]}...\n\n"
                                    "Chọn cách tạo lại visual prompt:",
                                    view=RegenerateVisualOptionsView(
                                        session_id=self.session_id,
                                        scene_number=scene_num,
                                        current_visual_prompt=current_visual
                                    ),
                                    ephemeral=True
                                )
                            else:
                                await interaction.response.send_message(
                                    f"⚠️ Không tìm thấy scene {scene_num}",
                                    ephemeral=True
                                )
                    
                    embed = discord.Embed(
                        title=f"🎨 Regenerate Visual - {self.selected_session_id}",
                        description="Chọn scene cần regenerate visual prompt từ menu bên dưới:",
                        color=discord.Color.blue()
                    )
                    
                    view = SelectSceneForVisualView(self.selected_session_id, scenes)
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                    
                except Exception as e:
                    await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)
            
            @discord.ui.button(label="🔁 Re-render full", style=discord.ButtonStyle.success, row=2)
            async def rerender_full(self, interaction: discord.Interaction, button):
                await interaction.response.send_modal(RerenderFullForm(session_id=self.selected_session_id))
            
            @discord.ui.button(label="🎵 Đổi nhạc nền", style=discord.ButtonStyle.primary, row=3)
            async def change_music(self, interaction: discord.Interaction, button):
                if not self.selected_session_id:
                    await interaction.response.send_message("⚠️ Vui lòng chọn session trước!", ephemeral=True)
                    return
                
                await interaction.response.defer(ephemeral=True)
                
                try:
                    # Get music list from API
                    API_ENDPOINT = "http://tts-audio:8000/music_list"
                    status, data = await http_get(API_ENDPOINT, timeout=10)
                    
                    if status < 200 or status >= 300:
                        await interaction.followup.send(f"⚠️ Không thể lấy danh sách nhạc: {data}", ephemeral=True)
                        return
                    
                    music_files = data.get("music_files", [])
                    
                    # Build music select menu
                    music_options = []
                    
                    # Add default options
                    music_options.append(
                        discord.SelectOption(
                            label="🔇 Không dùng nhạc nền",
                            value="no_music",
                            description="Chỉ dùng TTS thuần túy",
                            emoji="🔇"
                        )
                    )
                    music_options.append(
                        discord.SelectOption(
                            label="🎲 Auto chọn ngẫu nhiên",
                            value="auto",
                            description="Tự động chọn nhạc từ music_folder",
                            emoji="🎲"
                        )
                    )
                    
                    # Add music files from API response
                    for music_file in music_files[:20]:  # Limit to 20 files
                        music_options.append(
                            discord.SelectOption(
                                label=sanitize_label(f"🎵 {music_file}"),
                                value=music_file,
                                description=f"File: {music_file}",
                                emoji="🎵"
                            )
                        )
                    
                    if not music_options:
                        await interaction.followup.send("⚠️ Không có file nhạc nào trong music_folder!", ephemeral=True)
                        return
                    
                    # Create view with select menu
                    class SelectMusicView(discord.ui.View):
                        def __init__(self, session_id, music_options):
                            super().__init__(timeout=300)
                            self.session_id = session_id
                            self.music_options = music_options
                            
                            select = discord.ui.Select(
                                placeholder="Chọn nhạc nền cho video...",
                                options=music_options
                            )
                            select.callback = self.on_select
                            self.add_item(select)
                        
                        async def on_select(self, interaction: discord.Interaction):
                            selected_value = interaction.data['values'][0]
                            
                            # Map values
                            if selected_value == "no_music":
                                bg_choice = "1"
                                music_desc = "🔇 Không dùng nhạc nền"
                            elif selected_value == "auto":
                                bg_choice = ""
                                music_desc = "🎲 Auto chọn ngẫu nhiên"
                            else:
                                bg_choice = selected_value
                                music_desc = f"🎵 {selected_value}"
                            
                            # Open modal with selected music
                            await interaction.response.send_modal(
                                ChangeMusicForm(
                                    session_id=self.session_id,
                                    selected_bg_choice=bg_choice,
                                    music_description=music_desc
                                )
                            )
                    
                    embed = discord.Embed(
                        title=f"🎵 Chọn nhạc nền - {self.selected_session_id}",
                        description="Chọn nhạc nền cho video từ menu bên dưới:",
                        color=discord.Color.blue()
                    )
                    
                    view = SelectMusicView(self.selected_session_id, music_options)
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                    
                except Exception as e:
                    await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)
        
        view = SessionActionView(sessions)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)


class ViewMetadataForm(discord.ui.Modal, title="📖 Xem Metadata Session"):
    def __init__(self, session_id=None):
        super().__init__()
        self.session_id = discord.ui.TextInput(
            label="Session ID",
            placeholder="VD: 20251123_153045",
            default=session_id or "",
            required=True
        )
        self.add_item(self.session_id)
    
    async def on_submit(self, interaction: discord.Interaction):
        session_id = self.session_id.value.strip()
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            API_ENDPOINT = f"http://tts-audio:8000/tiktok_ad/metadata/{session_id}"
            status, data = await http_get(API_ENDPOINT, timeout=30)
            
            if status < 200 or status >= 300:
                await interaction.followup.send(f"⚠️ Không tìm thấy session: {data}", ephemeral=True)
                return
            
            # Hiển thị metadata
            scenes = data.get("scenes", [])
            style = data.get("style", "N/A")
            final_video = data.get("final_video", "N/A")
            num_scenes = data.get("num_scenes", 0)
            
            embed = discord.Embed(
                title=f"📖 METADATA - {session_id}",
                description=f"**Style:** {style}\n**Video:** {final_video}\n**Scenes:** {num_scenes}",
                color=discord.Color.green()
            )
            
            # Hiển thị từng scene
            for i, scene in enumerate(scenes, 1):
                scene_num = scene.get("scene_number", i)
                purpose = scene.get("purpose", "N/A")
                duration = scene.get("duration", 0)
                script = scene.get("script", "N/A")
                visual = scene.get("visual_prompt", "N/A")
                
                embed.add_field(
                    name=f"Scene {scene_num} - {purpose} ({duration}s)",
                    value=f"📝 Script: {script[:100]}...\n🎨 Visual: {visual[:100]}...",
                    inline=False
                )
            
            # Tạo view với buttons để chỉnh sửa từng scene và TTS
            class EditSceneView(discord.ui.View):
                def __init__(self, session_id, scenes_data, style):
                    super().__init__(timeout=300)
                    self.session_id = session_id
                    self.scenes_data = scenes_data
                    self.style = style
                    
                    # Tạo select menu để chọn scene cần chỉnh sửa HOẶC chỉnh sửa TTS
                    options = [
                        discord.SelectOption(
                            label="🎤 Chỉnh sửa TTS Script (toàn bộ)",
                            value="edit_tts",
                            description="Sửa nội dung TTS cho tất cả scenes",
                            emoji="🎤"
                        )
                    ]
                    
                    # Thêm options cho từng scene
                    for i, s in enumerate(scenes_data, 1):
                        options.append(
                            discord.SelectOption(
                                label=sanitize_label(f"Scene {s.get('scene_number', i)} - {s.get('purpose', 'N/A')}"),
                                value=f"scene_{s.get('scene_number', i)}",
                                description=f"{s.get('duration', 0)}s - Sửa visual prompt",
                                emoji="🎬"
                            )
                        )
                    
                    if options:
                        select = discord.ui.Select(
                            placeholder="Chọn scene hoặc TTS để chỉnh sửa...",
                            options=options,
                            row=0
                        )
                        select.callback = self.on_select
                        self.add_item(select)
                
                async def on_select(self, interaction: discord.Interaction):
                    selected_value = interaction.data['values'][0]
                    
                    # Nếu chọn edit TTS
                    if selected_value == "edit_tts":
                        # Gộp script từ tất cả scenes với ngắt dòng giữa các scene
                        full_script_parts = []
                        for i, scene in enumerate(self.scenes_data):
                            script = scene.get('script', '')
                            if script:
                                full_script_parts.append(script)
                        
                        # Join với newline để mỗi scene 1 dòng
                        full_script = "\n".join(full_script_parts)
                        
                        await interaction.response.send_modal(
                            EditTTSScriptForm(
                                session_id=self.session_id,
                                current_script=full_script,
                                style=self.style
                            )
                        )
                    # Nếu chọn scene
                    elif selected_value.startswith("scene_"):
                        scene_num = int(selected_value.replace("scene_", ""))
                        
                        # Tìm scene data
                        scene_data = None
                        for s in self.scenes_data:
                            if s.get('scene_number') == scene_num:
                                scene_data = s
                                break
                        
                        if scene_data:
                            # Mở modal với thông tin đã điền sẵn
                            current_visual = scene_data.get('visual_prompt', '')
                            await interaction.response.send_modal(
                                RerenderSceneForm(
                                    session_id=self.session_id,
                                    scene_number=scene_num,
                                    current_visual_prompt=current_visual
                                )
                            )
                        else:
                            await interaction.response.send_message(
                                f"⚠️ Không tìm thấy scene {scene_num}",
                                ephemeral=True
                            )
            
            view = EditSceneView(session_id, scenes, style)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)


class RerenderSceneForm(discord.ui.Modal, title="🔄 Re-render Scene"):
    def __init__(self, session_id=None, scene_number=None, current_visual_prompt=None):
        super().__init__()
        self.session_id = discord.ui.TextInput(
            label="Session ID",
            placeholder="VD: 20251123_153045",
            default=session_id or "",
            required=True
        )
        self.scene_number = discord.ui.TextInput(
            label="Scene Number",
            placeholder="VD: 4 (scene thứ mấy cần render lại)",
            default=str(scene_number) if scene_number else "",
            required=True
        )
        self.new_visual_prompt = discord.ui.TextInput(
            label="Visual Prompt mới",
            style=discord.TextStyle.paragraph,
            placeholder="Chỉnh sửa visual prompt...",
            default=current_visual_prompt or "",
            required=False,
            max_length=2000
        )
        self.add_item(self.session_id)
        self.add_item(self.scene_number)
        self.add_item(self.new_visual_prompt)
    
    async def on_submit(self, interaction: discord.Interaction):
        session_id = self.session_id.value.strip()
        
        try:
            scene_num = int(self.scene_number.value.strip())
        except:
            await interaction.response.send_message("⚠️ Scene number phải là số!", ephemeral=True)
            return
        
        new_visual = self.new_visual_prompt.value.strip() or None
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            API_ENDPOINT = "http://tts-audio:8000/tiktok_ad/rerender_scene"
            params = {
                "session_id": session_id,
                "scene_number": int(scene_num)
            }
            if new_visual:
                params["new_visual_prompt"] = new_visual
            
            status, data = await http_post(API_ENDPOINT, params=params, timeout=300)
            
            if status < 200 or status >= 300:
                await interaction.followup.send(f"⚠️ Lỗi: {data}", ephemeral=True)
                return
            
            new_video_path = data.get("new_video_path", "N/A")
            message = data.get("message", "")
            
            embed = discord.Embed(
                title=f"✅ Scene {scene_num} đã render lại",
                description=f"**Session:** {session_id}\n**Video mới:** {new_video_path}\n\n{message}",
                color=discord.Color.green()
            )
            
            # Tạo button để reassemble với metadata mới nhất
            class ReassembleButton(discord.ui.View):
                def __init__(self, session_id, scene_num, new_path):
                    super().__init__(timeout=300)
                    self.session_id = session_id
                    self.scene_num = scene_num
                    self.new_path = new_path
                
                @discord.ui.button(label="🔧 Ghép video final", style=discord.ButtonStyle.success)
                async def reassemble(self, interaction: discord.Interaction, button):
                    await interaction.response.defer(ephemeral=True)
                    
                    try:
                        # Load metadata để lấy tất cả scene_videos mới nhất
                        API_META = f"http://tts-audio:8000/tiktok_ad/metadata/{self.session_id}"
                        status_meta, meta_data = await http_get(API_META, timeout=30)
                        
                        if status_meta < 200 or status_meta >= 300:
                            await interaction.followup.send(f"⚠️ Không load được metadata: {meta_data}", ephemeral=True)
                            return
                        
                        # Lấy scene_videos từ metadata (đã cập nhật sau re-render)
                        scene_videos = meta_data.get("scene_videos", {})
                        
                        import json
                        scene_videos_json = json.dumps(scene_videos)
                        
                        API_ENDPOINT = "http://tts-audio:8000/tiktok_ad/reassemble"
                        params = {
                            "session_id": self.session_id,
                            "scene_videos": scene_videos_json
                        }
                        
                        status2, data2 = await http_post(API_ENDPOINT, params=params, timeout=120)
                        
                        if status2 < 200 or status2 >= 300:
                            await interaction.followup.send(f"⚠️ Lỗi reassemble: {data2}", ephemeral=True)
                            return
                        
                        final_video = data2.get("final_video", "N/A")
                        download_url = data2.get("download_url", "N/A")
                        
                        await interaction.followup.send(
                            f"✅ **Video final đã ghép xong!**\n📹 {final_video}\n⬇️ {download_url}",
                            ephemeral=True
                        )
                    except Exception as e:
                        await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)
            
            view = ReassembleButton(session_id, scene_num, new_video_path)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)


class RerenderFullForm(discord.ui.Modal, title="🔁 Re-render Full Video"):
    def __init__(self, session_id=None):
        super().__init__()
        self.session_id = discord.ui.TextInput(
            label="Session ID",
            placeholder="VD: 20251123_153045",
            default=session_id or "",
            required=True
        )
        self.output_filename = discord.ui.TextInput(
            label="Tên file output (optional)",
            placeholder="VD: ad_v2.mp4 (để trống = auto)",
            required=False
        )
        self.add_item(self.session_id)
        self.add_item(self.output_filename)
    
    async def on_submit(self, interaction: discord.Interaction):
        session_id = self.session_id.value.strip()
        output_filename = self.output_filename.value.strip() or None
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            API_ENDPOINT = "http://tts-audio:8000/tiktok_ad/rerender_full"
            params = {
                "session_id": session_id
            }
            if output_filename:
                params["output_filename"] = output_filename
            
            status, data = await http_post(API_ENDPOINT, params=params, timeout=30)
            
            if status < 200 or status >= 300:
                await interaction.followup.send(f"⚠️ Lỗi: {data}", ephemeral=True)
                return
            
            task_id = data.get("task_id", "N/A")
            
            embed = discord.Embed(
                title="🔁 Đang re-render toàn bộ video",
                description=(
                    f"**Session:** {session_id}\n"
                    f"**Task ID:** `{task_id}`\n\n"
                    f"💡 Dùng `/task_status {task_id}` để theo dõi tiến trình\n"
                    f"⏱️ Thời gian ước tính: 5-15 phút"
                ),
                color=discord.Color.blue()
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)


class ChangeMusicForm(discord.ui.Modal, title="🎵 Đổi nhạc nền"):
    def __init__(self, session_id=None, selected_bg_choice=None, music_description=None):
        super().__init__()
        self.session_id = discord.ui.TextInput(
            label="Session ID",
            placeholder="VD: 20251123_153045",
            default=session_id or "",
            required=True
        )
        self.bg_choice = discord.ui.TextInput(
            label="Nhạc nền đã chọn",
            placeholder="Nhạc nền đã chọn từ menu",
            default=selected_bg_choice or "",
            required=False
        )
        self.music_display = discord.ui.TextInput(
            label="Mô tả nhạc",
            placeholder="Mô tả nhạc đã chọn",
            default=music_description or "",
            required=False
        )
        self.output_filename = discord.ui.TextInput(
            label="Tên file output (optional)",
            placeholder="VD: ad_new_music.mp4 (để trống = auto)",
            required=False
        )
        self.add_item(self.session_id)
        self.add_item(self.bg_choice)
        self.add_item(self.music_display)
        self.add_item(self.output_filename)
    
    async def on_submit(self, interaction: discord.Interaction):
        session_id = self.session_id.value.strip()
        bg_choice = self.bg_choice.value.strip() or None
        output_filename = self.output_filename.value.strip() or None
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            API_ENDPOINT = "http://tts-audio:8000/tiktok_ad/change_music"
            params = {
                "session_id": session_id
            }
            if bg_choice is not None:
                params["bg_choice"] = bg_choice
            if output_filename:
                params["output_filename"] = output_filename
            
            status, data = await http_post(API_ENDPOINT, params=params, timeout=30)
            
            if status < 200 or status >= 300:
                await interaction.followup.send(f"⚠️ Lỗi: {data}", ephemeral=True)
                return
            
            task_id = data.get("task_id", "N/A")
            
            # Get music description for display
            music_desc = self.music_display.value.strip() or ("Không dùng nhạc nền" if bg_choice == "1" else ("Auto chọn" if not bg_choice else bg_choice))
            
            embed = discord.Embed(
                title="🎵 Đang thay đổi nhạc nền video",
                description=(
                    f"**Session:** {session_id}\n"
                    f"**Nhạc nền:** {music_desc}\n"
                    f"**Task ID:** `{task_id}`\n\n"
                    f"💡 Dùng `/task_status {task_id}` để theo dõi tiến trình\n"
                    f"⏱️ Thời gian ước tính: 5-15 phút\n\n"
                    f"Sau khi task hoàn thành, dùng button bên dưới để reassemble video"
                ),
                color=discord.Color.blue()
            )
            
            # Thêm button reassemble để user quyết định có tạo lại video không
            class ReassembleButtonAfterMusic(discord.ui.View):
                def __init__(self, sess_id):
                    super().__init__(timeout=600)  # 10 phút timeout
                    self.sess_id = sess_id
                
                @discord.ui.button(label="🔧 Reassemble video", style=discord.ButtonStyle.success)
                async def reassemble(self, interaction: discord.Interaction, button):
                    await interaction.response.defer(ephemeral=True)
                    try:
                        # Load metadata để lấy scene_videos mới nhất
                        API_META = f"http://tts-audio:8000/tiktok_ad/metadata/{self.sess_id}"
                        status_meta, meta_data = await http_get(API_META, timeout=30)
                        
                        if status_meta < 200 or status_meta >= 300:
                            await interaction.followup.send(f"⚠️ Không load được metadata: {meta_data}", ephemeral=True)
                            return
                        
                        scene_videos = meta_data.get("scene_videos", {})
                        import json
                        scene_videos_json = json.dumps(scene_videos)
                        
                        API_ENDPOINT = "http://tts-audio:8000/tiktok_ad/reassemble"
                        params = {
                            "session_id": self.sess_id,
                            "scene_videos": scene_videos_json
                        }
                        
                        status2, data2 = await http_post(API_ENDPOINT, params=params, timeout=120)
                        
                        if status2 < 200 or status2 >= 300:
                            await interaction.followup.send(f"⚠️ Lỗi reassemble: {data2}", ephemeral=True)
                            return
                        
                        final_video2 = data2.get("final_video", "N/A")
                        download_url2 = data2.get("download_url", "N/A")
                        
                        await interaction.followup.send(
                            f"✅ **Video đã reassemble!**\n📹 {final_video2}\n⬇️ {download_url2}",
                            ephemeral=True
                        )
                    except Exception as e:
                        await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)
            
            view = ReassembleButtonAfterMusic(session_id)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)


class EditTTSScriptForm(discord.ui.Modal, title="🎤 Chỉnh sửa TTS Script"):
    def __init__(self, session_id=None, current_script=None, style=None):
        super().__init__()
        self.session_id = discord.ui.TextInput(
            label="Session ID",
            placeholder="VD: 20251123_153045",
            default=session_id or "",
            required=True
        )
        self.tts_script = discord.ui.TextInput(
            label="TTS Script (toàn bộ)",
            style=discord.TextStyle.paragraph,
            placeholder="Chỉnh sửa script TTS...",
            default=current_script or "",
            required=True,
            max_length=2000
        )
        self.tts_style = discord.ui.TextInput(
            label="Style giọng nói (1-4, optional)",
            placeholder="1=trẻ trung năng động | 2=mềm mại nữ tính | 3=storytelling/sang trọng | 4=hiện đại unisex",
            default=style or "",
            required=False
        )
        self.output_filename = discord.ui.TextInput(
            label="Tên file output (optional)",
            placeholder="VD: ad_new_tts.mp4 (để trống = auto)",
            required=False
        )
        self.add_item(self.session_id)
        self.add_item(self.tts_script)
        self.add_item(self.tts_style)
        self.add_item(self.output_filename)
    
    async def on_submit(self, interaction: discord.Interaction):
        session_id = self.session_id.value.strip()
        new_script = self.tts_script.value.strip()
        new_style = self.tts_style.value.strip() or None
        output_filename = self.output_filename.value.strip() or None
        
        # Map style number to name (đồng nhất với TikTokAdForm)
        style_map = {
            "1": "trẻ trung năng động",
            "2": "mềm mại nữ tính",
            "3": "storytelling / sang trọng",
            "4": "hiện đại unisex"
        }
        if new_style and new_style in style_map:
            new_style = style_map[new_style]
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            API_ENDPOINT = "http://tts-audio:8000/tiktok_ad/regenerate_tts"
            params = {
                "session_id": session_id,
                "new_script": new_script
            }
            if new_style:
                params["style"] = new_style
            if output_filename:
                params["output_filename"] = output_filename
            
            status, data = await http_post(API_ENDPOINT, params=params, timeout=120)
            
            if status < 200 or status >= 300:
                await interaction.followup.send(f"⚠️ Lỗi: {data}", ephemeral=True)
                return
            
            final_video = data.get("final_video", "N/A")
            from urllib.parse import quote_plus
            download_url = f"https://sandbox.travel.com.vn/api/download-video?download=1&video_name={quote_plus(final_video)}"
            view_url = f"https://sandbox.travel.com.vn/api/download-video?video_name={quote_plus(final_video)}"
            
            # Tạo view với 2 buttons + reassemble button
            class TTSActionsView(discord.ui.View):
                def __init__(self, sess_id, view_link, download_link):
                    super().__init__(timeout=300)
                    self.sess_id = sess_id
                    # Add link buttons
                    self.add_item(discord.ui.Button(
                        label="👁️ Xem video",
                        url=view_link,
                        style=discord.ButtonStyle.link,
                        row=0
                    ))
                    self.add_item(discord.ui.Button(
                        label="⬇️ Tải video",
                        url=download_link,
                        style=discord.ButtonStyle.link,
                        row=0
                    ))
                
                @discord.ui.button(label="🔧 Reassemble lại video", style=discord.ButtonStyle.primary, row=1)
                async def reassemble(self, interaction: discord.Interaction, button):
                    await interaction.response.defer(ephemeral=True)
                    try:
                        # Load metadata để lấy scene_videos mới nhất
                        API_META = f"http://tts-audio:8000/tiktok_ad/metadata/{self.sess_id}"
                        status_meta, meta_data = await http_get(API_META, timeout=30)
                        
                        if status_meta < 200 or status_meta >= 300:
                            await interaction.followup.send(f"⚠️ Không load được metadata: {meta_data}", ephemeral=True)
                            return
                        
                        scene_videos = meta_data.get("scene_videos", {})
                        import json
                        scene_videos_json = json.dumps(scene_videos)
                        
                        API_ENDPOINT = "http://tts-audio:8000/tiktok_ad/reassemble"
                        params = {
                            "session_id": self.sess_id,
                            "scene_videos": scene_videos_json
                        }
                        
                        status2, data2 = await http_post(API_ENDPOINT, params=params, timeout=120)
                        
                        if status2 < 200 or status2 >= 300:
                            await interaction.followup.send(f"⚠️ Lỗi reassemble: {data2}", ephemeral=True)
                            return
                        
                        final_video2 = data2.get("final_video", "N/A")
                        from urllib.parse import quote_plus
                        download_url2 = f"https://sandbox.travel.com.vn/api/download-video?download=1&video_name={quote_plus(final_video2)}"
                        view_url2 = f"https://sandbox.travel.com.vn/api/download-video?video_name={quote_plus(final_video2)}"
                        
                        class VideoActionsView(discord.ui.View):
                            def __init__(self, vl, dl):
                                super().__init__(timeout=None)
                                self.add_item(discord.ui.Button(label="👁️ Xem video", url=vl, style=discord.ButtonStyle.link))
                                self.add_item(discord.ui.Button(label="⬇️ Tải video", url=dl, style=discord.ButtonStyle.link))
                        
                        await interaction.followup.send(
                            f"✅ **Video đã reassemble lại!**\n📹 {final_video2}",
                            view=VideoActionsView(view_url2, download_url2),
                            ephemeral=True
                        )
                    except Exception as e:
                        await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)
            
            embed = discord.Embed(
                title="✅ TTS đã regenerate và video đã reassemble!",
                description=(
                    f"**Session:** {session_id}\n"
                    f"**Video mới:** {final_video}"
                ),
                color=discord.Color.green()
            )
            
            view = TTSActionsView(session_id, view_url, download_url)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)


async def tiktok_ad_reassemble_command(interaction: discord.Interaction, session_id: str = None):
    """
    Reassemble video từ các scene videos đã có sẵn.
    Dùng khi đã re-render một số scene và muốn ghép lại video final.
    Auto-load scene_videos từ metadata.
    """
    try:
        scene_videos_dict = None
        
        # Nếu có session_id, load metadata trước (không defer - cần mở modal)
        if session_id:
            try:
                # Load metadata đồng bộ bằng cách gọi API trong background
                import aiohttp
                API_META = f"http://tts-audio:8000/tiktok_ad/metadata/{session_id.strip()}"
                
                # Tạo async request để load metadata
                timeout_obj = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                    async with session.get(API_META) as resp:
                        if resp.status >= 200 and resp.status < 300:
                            meta_data = await resp.json()
                            scene_videos_dict = meta_data.get("scene_videos", {})
            except Exception as e:
                # Nếu lỗi, vẫn mở form nhưng không có pre-fill
                pass
        
        # Mở modal (KHÔNG defer trước đó)
        await interaction.response.send_modal(ReassembleVideoForm(session_id=session_id, scene_videos_dict=scene_videos_dict))
    except Exception as e:
        try:
            await interaction.response.send_message(f"⚠️ Lỗi: {e}", ephemeral=True)
        except Exception:
            pass


class ReassembleVideoForm(discord.ui.Modal, title="🔧 Reassemble Video"):
    def __init__(self, session_id=None, scene_videos_dict=None):
        super().__init__()
        self.session_id = discord.ui.TextInput(
            label="Session ID",
            placeholder="VD: 20251123_153045",
            default=session_id or "",
            required=True
        )
        
        # Auto-fill scene_videos từ metadata nếu có
        import json
        default_scene_videos = ""
        if scene_videos_dict:
            default_scene_videos = json.dumps(scene_videos_dict, indent=2, ensure_ascii=False)
        
        self.scene_videos_json = discord.ui.TextInput(
            label="Scene Videos (auto-loaded từ metadata)",
            style=discord.TextStyle.paragraph,
            placeholder='Đã tự động load từ session metadata. Chỉnh sửa nếu cần.',
            default=default_scene_videos,
            required=False
        )
        self.output_filename = discord.ui.TextInput(
            label="Tên file output (optional)",
            placeholder="VD: ad_v2.mp4 (để trống = auto)",
            required=False
        )
        self.add_item(self.session_id)
        self.add_item(self.scene_videos_json)
        self.add_item(self.output_filename)
    
    async def on_submit(self, interaction: discord.Interaction):
        session_id = self.session_id.value.strip()
        scene_videos_input = self.scene_videos_json.value.strip()
        output_filename = self.output_filename.value.strip() or None
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Nếu không nhập scene_videos, load từ metadata
            if not scene_videos_input:
                API_META = f"http://tts-audio:8000/tiktok_ad/metadata/{session_id}"
                status_meta, meta_data = await http_get(API_META, timeout=30)
                
                if status_meta < 200 or status_meta >= 300:
                    await interaction.followup.send(f"⚠️ Không load được metadata: {meta_data}", ephemeral=True)
                    return
                
                scene_videos_dict = meta_data.get("scene_videos", {})
                import json
                scene_videos_json = json.dumps(scene_videos_dict)
            else:
                scene_videos_json = scene_videos_input
            
            API_ENDPOINT = "http://tts-audio:8000/tiktok_ad/reassemble"
            params = {
                "session_id": session_id,
                "scene_videos": scene_videos_json
            }
            if output_filename:
                params["output_filename"] = output_filename
            
            status, data = await http_post(API_ENDPOINT, params=params, timeout=120)
            
            if status < 200 or status >= 300:
                await interaction.followup.send(f"⚠️ Lỗi: {data}", ephemeral=True)
                return
            
            final_video = data.get("final_video", "N/A")
            from urllib.parse import quote_plus
            download_url = f"https://sandbox.travel.com.vn/api/download-video?download=1&video_name={quote_plus(final_video)}"
            view_url = f"https://sandbox.travel.com.vn/api/download-video?video_name={quote_plus(final_video)}"
            
            class VideoActionsView(discord.ui.View):
                def __init__(self, view_link, download_link):
                    super().__init__(timeout=None)
                    self.add_item(discord.ui.Button(
                        label="👁️ Xem video",
                        url=view_link,
                        style=discord.ButtonStyle.link
                    ))
                    self.add_item(discord.ui.Button(
                        label="⬇️ Tải video",
                        url=download_link,
                        style=discord.ButtonStyle.link
                    ))
            
            embed = discord.Embed(
                title="✅ Video đã reassemble thành công!",
                description=(
                    f"**Session:** {session_id}\n"
                    f"**Video:** {final_video}"
                ),
                color=discord.Color.green()
            )
            
            await interaction.followup.send(embed=embed, view=VideoActionsView(view_url, download_url), ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)


@bot.tree.command(name="regenerate_visual", description="🎨 Chỉnh sửa visual prompt và tạo lại video cho một scene")
async def regenerate_visual_command(
    interaction: discord.Interaction,
    session_id: str
):
    """
    Command để xem và chỉnh sửa visual prompt của một scene cụ thể.
    User nhập session_id, chọn scene, sau đó chỉnh sửa visual prompt.
    """
    await interaction.response.defer(ephemeral=True)
    
    try:
        # Load metadata để lấy danh sách scenes
        API_ENDPOINT = f"http://tts-audio:8000/tiktok_ad/metadata/{session_id}"
        status, data = await http_get(API_ENDPOINT, timeout=30)
        
        if status < 200 or status >= 300:
            await interaction.followup.send(f"⚠️ Không tìm thấy session: {data}", ephemeral=True)
            return
        
        scenes = data.get("scenes", [])
        if not scenes:
            await interaction.followup.send("⚠️ Session này không có scene nào!", ephemeral=True)
            return
        
        # Tạo view với select menu để chọn scene
        class SelectSceneView(discord.ui.View):
            def __init__(self, session_id, scenes_data):
                super().__init__(timeout=300)
                self.session_id = session_id
                self.scenes_data = scenes_data
                
                # Tạo select menu với danh sách scenes
                options = []
                for s in scenes_data:
                    scene_num = s.get("scene_number")
                    purpose = s.get("purpose", "N/A")
                    duration = s.get("duration", 0)
                    options.append(
                        discord.SelectOption(
                            label=f"Scene {scene_num} - {purpose} ({duration}s)",
                            value=str(scene_num),
                            description=f"Visual: {s.get('visual_prompt', '')[:50]}...",
                            emoji="🎬"
                        )
                    )
                
                select = discord.ui.Select(
                    placeholder="Chọn scene cần chỉnh sửa visual...",
                    options=options
                )
                select.callback = self.on_select
                self.add_item(select)
            
            async def on_select(self, interaction: discord.Interaction):
                scene_num = int(interaction.data["values"][0])
                
                # Tìm scene data
                scene = None
                for s in self.scenes_data:
                    if s.get("scene_number") == scene_num:
                        scene = s
                        break
                
                if scene:
                    current_visual = scene.get("visual_prompt", "")
                    # Hiển thị options: AI tạo mới hoặc tự chỉnh sửa
                    await interaction.response.send_message(
                        f"**Scene {scene_num} - {scene.get('purpose', 'N/A')}**\n\n"
                        f"🎨 Visual hiện tại: {current_visual[:200]}...\n\n"
                        "Chọn cách tạo lại visual prompt:",
                        view=RegenerateVisualOptionsView(
                            session_id=self.session_id,
                            scene_number=scene_num,
                            current_visual_prompt=current_visual
                        ),
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        f"⚠️ Không tìm thấy scene {scene_num}",
                        ephemeral=True
                    )
        
        embed = discord.Embed(
            title=f"🎨 Chỉnh sửa Visual Prompt - {session_id}",
            description="Chọn scene cần chỉnh sửa visual prompt từ menu bên dưới:",
            color=discord.Color.blue()
        )
        
        view = SelectSceneView(session_id, scenes)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)


class RegenerateVisualOptionsView(discord.ui.View):
    """View với 2 buttons: AI tạo mới hoặc Tự chỉnh sửa"""
    def __init__(self, session_id, scene_number, current_visual_prompt):
        super().__init__(timeout=300)
        self.session_id = session_id
        self.scene_number = scene_number
        self.current_visual = current_visual_prompt
    
    @discord.ui.button(label="🤖 Nhờ AI tạo visual mới", style=discord.ButtonStyle.primary)
    async def ai_generate(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True)
        
        try:
            # BƯỚC 1: Chỉ generate visual prompt, KHÔNG render video
            API_ENDPOINT = "http://tts-audio:8000/tiktok_ad/generate_visual_prompt"
            params = {
                "session_id": self.session_id,
                "scene_number": int(self.scene_number)
            }
            
            await interaction.followup.send(
                f"🤖 Đang nhờ AI tạo visual prompt mới cho scene {self.scene_number}...\n"
                "⏳ Vui lòng chờ...",
                ephemeral=True
            )
            
            status, data = await http_post(API_ENDPOINT, params=params, timeout=60)
            
            if status < 200 or status >= 300:
                await interaction.followup.send(f"⚠️ Lỗi: {data}", ephemeral=True)
                return
            
            visual_prompt = data.get("visual_prompt", "N/A")
            scene_context = data.get("scene_context", {})
            
            # Hiển thị visual prompt cho user xem và confirm
            embed = discord.Embed(
                title=f"🤖 AI đã tạo Visual Prompt - Scene {self.scene_number}",
                description=(
                    f"**Session:** {self.session_id}\n"
                    f"**Scene:** {self.scene_number}\n"
                    f"**Purpose:** {scene_context.get('purpose', 'N/A')}\n"
                    f"**Duration:** {scene_context.get('duration', 0)}s\n\n"
                    f"📝 **Script:** {scene_context.get('script', 'N/A')[:200]}...\n\n"
                    f"👇 Xem visual prompt bên dưới và quyết định:"
                ),
                color=discord.Color.blue()
            )
            
            # Hiển thị visual prompt (chia nhỏ nếu quá dài)
            if len(visual_prompt) > 1024:
                embed.add_field(
                    name="🎨 Visual Prompt (Phần 1)",
                    value=visual_prompt[:1024],
                    inline=False
                )
                embed.add_field(
                    name="🎨 Visual Prompt (Phần 2)",
                    value=visual_prompt[1024:2048] + ("..." if len(visual_prompt) > 2048 else ""),
                    inline=False
                )
            else:
                embed.add_field(
                    name="🎨 Visual Prompt",
                    value=visual_prompt,
                    inline=False
                )       
            # BƯỚC 2: Tạo buttons để user confirm hoặc regenerate
            class ConfirmVisualView(discord.ui.View):
                def __init__(self, sess_id, scene_num, visual_text):
                    super().__init__(timeout=600)
                    self.sess_id = sess_id
                    self.scene_num = scene_num
                    self.visual_text = visual_text
                
                @discord.ui.button(label="✅ OK - Render video", style=discord.ButtonStyle.success)
                async def confirm_render(self, interaction: discord.Interaction, button):
                    await interaction.response.defer(ephemeral=True)
                    
                    try:
                        # Render video với visual prompt đã confirm
                        API_RENDER = "http://tts-audio:8000/tiktok_ad/rerender_scene"
                        params_render = {
                            "session_id": self.sess_id,
                            "scene_number": int(self.scene_num),
                            "new_visual_prompt": self.visual_text
                        }
                        
                        await interaction.followup.send(
                            f"🎬 Đang render video cho scene {self.scene_num}...\n"
                            "⏳ Quá trình này mất 2-3 phút, vui lòng chờ...",
                            ephemeral=True
                        )
                        
                        status_render, data_render = await http_post(API_RENDER, params=params_render, timeout=300)
                        
                        if status_render < 200 or status_render >= 300:
                            await interaction.followup.send(f"⚠️ Lỗi render: {data_render}", ephemeral=True)
                            return
                        
                        new_video_path = data_render.get("new_video_path", "N/A")
                        
                        # Tạo link xem và tải scene video
                        from urllib.parse import quote_plus
                        scene_view_url = f"https://sandbox.travel.com.vn/api/download-video?video_name={quote_plus(new_video_path)}"
                        scene_download_url = f"https://sandbox.travel.com.vn/api/download-video?download=1&video_name={quote_plus(new_video_path)}"
                        
                        embed_done = discord.Embed(
                            title=f"✅ Scene {self.scene_num} đã render xong!",
                            description=(
                                f"**Session:** {self.sess_id}\n"
                                f"**Video mới:** {new_video_path}\n\n"
                                f"👁️ [Xem scene]({scene_view_url}) | ⬇️ [Tải scene]({scene_download_url})\n\n"
                                f"💡 Dùng button bên dưới để reassemble video final"
                            ),
                            color=discord.Color.green()
                        )
                        
                        # View với buttons reassemble và re-render
                        class SceneActionView(discord.ui.View):
                            def __init__(self, sid, scene_num):
                                super().__init__(timeout=300)
                                self.sid = sid
                                self.scene_num = scene_num
                            
                            @discord.ui.button(label="🔧 Ghép video final", style=discord.ButtonStyle.primary)
                            async def reassemble(self, interaction: discord.Interaction, btn):
                                await interaction.response.defer(ephemeral=True)
                                try:
                                    API_META = f"http://tts-audio:8000/tiktok_ad/metadata/{self.sid}"
                                    st, mt = await http_get(API_META, timeout=30)
                                    if st >= 200 and st < 300:
                                        sv = mt.get("scene_videos", {})
                                        import json
                                        sv_json = json.dumps(sv)
                                        API_REASM = "http://tts-audio:8000/tiktok_ad/reassemble"
                                        st2, dt2 = await http_post(API_REASM, params={"session_id": self.sid, "scene_videos": sv_json}, timeout=120)
                                        if st2 >= 200 and st2 < 300:
                                            fv = dt2.get("final_video", "N/A")
                                            dl = dt2.get("download_url", "N/A")
                                            await interaction.followup.send(f"✅ **Video final đã ghép!**\n📹 {fv}\n⬇️ {dl}", ephemeral=True)
                                        else:
                                            await interaction.followup.send(f"⚠️ Lỗi: {dt2}", ephemeral=True)
                                    else:
                                        await interaction.followup.send(f"⚠️ Lỗi: {mt}", ephemeral=True)
                                except Exception as e:
                                    await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)
                            
                            @discord.ui.button(label="🔄 Tạo lại scene này", style=discord.ButtonStyle.secondary)
                            async def rerender_again(self, interaction: discord.Interaction, btn):
                                await interaction.response.send_message(
                                    f"🎬 Nhờ AI tạo visual mới cho scene {self.scene_num}...",
                                    ephemeral=True
                                )
                                # Gọi API generate visual prompt
                                try:
                                    API_GEN = "http://tts-audio:8000/tiktok_ad/generate_visual_prompt"
                                    params = {
                                        "session_id": self.sid,
                                        "scene_number": int(self.scene_num)
                                    }
                                    st, dt = await http_post(API_GEN, params=params, timeout=60)
                                    
                                    if st >= 200 and st < 300:
                                        visual = dt.get("visual_prompt", "N/A")
                                        
                                        # Hiển thị confirmation view
                                        confirm_view = ConfirmVisualView(self.sid, self.scene_num, visual)
                                        
                                        embed = discord.Embed(
                                            title=f"🤖 AI đã tạo visual prompt mới cho scene {self.scene_num}",
                                            description=f"**Visual Prompt:**\n```{visual}```\n\n💡 Xác nhận để render hoặc tạo lại",
                                            color=discord.Color.blue()
                                        )
                                        
                                        await interaction.followup.send(embed=embed, view=confirm_view, ephemeral=True)
                                    else:
                                        await interaction.followup.send(f"⚠️ Lỗi: {dt}", ephemeral=True)
                                except Exception as e:
                                    await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)
                        
                        await interaction.followup.send(embed=embed_done, view=SceneActionView(self.sess_id, self.scene_num), ephemeral=True)
                        
                    except Exception as e:
                        await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)
                
                @discord.ui.button(label="🔄 Tạo lại prompt khác", style=discord.ButtonStyle.secondary)
                async def regenerate(self, interaction: discord.Interaction, button):
                    await interaction.response.send_message(
                        "♻️ Đang tạo visual prompt mới...\n"
                        "Vui lòng đợi AI generate lại.",
                        ephemeral=True
                    )
                    # Trigger lại AI generate bằng cách gọi lại button
                    # (User sẽ click lại button "Nhờ AI tạo visual mới")
                
                @discord.ui.button(label="✏️ Chỉnh sửa thủ công", style=discord.ButtonStyle.primary)
                async def edit_manual(self, interaction: discord.Interaction, button):
                    await interaction.response.send_modal(
                        RegenerateVisualForm(
                            session_id=self.sess_id,
                            scene_number=self.scene_num,
                            current_visual_prompt=self.visual_text
                        )
                    )
            
            view = ConfirmVisualView(self.session_id, self.scene_number, visual_prompt)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"⚠️ Lỗi: {e}", ephemeral=True)
    
    @discord.ui.button(label="✏️ Tự chỉnh sửa visual", style=discord.ButtonStyle.secondary)
    async def manual_edit(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(
            RegenerateVisualForm(
                session_id=self.session_id,
                scene_number=self.scene_number,
                current_visual_prompt=self.current_visual
            )
        )


class RegenerateVisualForm(discord.ui.Modal, title="🎨 Chỉnh sửa Visual Prompt"):
    def __init__(self, session_id=None, scene_number=None, current_visual_prompt=None):
        super().__init__()
        self.session_id = discord.ui.TextInput(
            label="Session ID",
            placeholder="VD: 20251123_153045",
            default=session_id or "",
            required=True
        )
        self.scene_number = discord.ui.TextInput(
            label="Scene Number",
            placeholder="VD: 2 (scene thứ mấy)",
            default=str(scene_number) if scene_number else "",
            required=True
        )
        self.visual_prompt = discord.ui.TextInput(
            label="Visual Prompt",
            style=discord.TextStyle.paragraph,
            placeholder="Chỉnh sửa visual prompt cho scene này...",
            default=current_visual_prompt or "",
            required=True,
            max_length=2000
        )
        self.add_item(self.session_id)
        self.add_item(self.scene_number)
        self.add_item(self.visual_prompt)
    
    async def on_submit(self, interaction: discord.Interaction):
        session_id = self.session_id.value.strip()
        
        try:
            scene_num = int(self.scene_number.value.strip())
        except:
            await interaction.response.send_message("⚠️ Scene number phải là số!", ephemeral=True)
            return
        
        new_visual = self.visual_prompt.value.strip()
        
        if not new_visual:
            await interaction.response.send_message("⚠️ Visual prompt không được để trống!", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            API_ENDPOINT = "http://tts-audio:8000/tiktok_ad/rerender_scene"
            params = {
                "session_id": session_id,
                "scene_number": int(scene_num),
                "new_visual_prompt": new_visual
            }
            
            status, data = await http_post(API_ENDPOINT, params=params, timeout=300)
            
            if status < 200 or status >= 300:
                await interaction.followup.send(f"⚠️ Lỗi: {data}", ephemeral=True)
                return
            
            new_video_path = data.get("new_video_path", "N/A")
            message = data.get("message", "")
            
            embed = discord.Embed(
                title=f"✅ Scene {scene_num} đã render lại với visual prompt mới!",
                description=(
                    f"**Session:** {session_id}\n"
                    f"**Scene:** {scene_num}\n"
                    f"**Video mới:** {new_video_path}\n\n"
                    f"📝 {message}\n\n"
                    f"💡 **Lưu ý:** Video scene đã được tạo lại. Nếu muốn ghép lại video final với scene mới, "
                    f"hãy dùng lệnh `/reassemble_video` với session này."
                ),
                color=discord.Color.green()
            )
            
            # Hiển thị visual prompt đã sử dụng
            embed.add_field(
                name="🎨 Visual Prompt đã dùng",
                value=new_visual[:1000] + ("..." if len(new_visual) > 1000 else ""),
                inline=False
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"⚠️ Lỗi khi tạo lại video: {e}", ephemeral=True)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Bot đã đăng nhập thành {bot.user}")

token = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError(
        "Missing Discord bot token; set DISCORD_BOT_TOKEN in discord-bot/.env or via the environment."
    )

bot.run(token)
