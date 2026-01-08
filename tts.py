import os
import os
import re
import time
import shutil
import subprocess
from typing import List

from config import OUTPUT_DIR, OPENAI_API_KEY
from DiscordMethod import send_discord_message
from GoogleTTS import text_to_wav
import openai
from audio_helpers import _write_concat_list, _concat_audio_from_list, _create_flac_copy, get_tts_part_files, _write_part_manifest

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY environment variable is required for TTS generation")

openai.api_key = OPENAI_API_KEY

# Text splitting helpers
def split_text_with_space(text, max_chars=4096):
    chunks = []
    start = 0
    text_length = len(text)
    while start < text_length:
        end = min(start + max_chars, text_length)
        chunk = text[start:end]
        if end < text_length:
            last_dot = chunk.rfind('.')
            if last_dot != -1 and last_dot > max_chars * 0.7:
                chunk = chunk[:last_dot+1]
        chunks.append(chunk.strip())
        start = end
    send_discord_message("✂️ Chia truyện thành %d đoạn", len(chunks))
    return chunks


def split_text_by_bytes(text, max_bytes=5000):
    chunks = []
    start = 0
    text_bytes = text.encode('utf-8')
    text_length = len(text_bytes)
    while start < text_length:
        end = min(start + max_bytes, text_length)
        while end < text_length and (text_bytes[end] & 0b11000000) == 0b10000000:
            end -= 1
        chunk_bytes = text_bytes[start:end]
        chunk = chunk_bytes.decode('utf-8', errors='ignore')
        if end < text_length:
            last_dot = chunk.rfind('.')
            if last_dot != -1 and last_dot > len(chunk) * 0.7:
                chunk = chunk[:last_dot+1]
        chunks.append(chunk.strip())
        start = end
    send_discord_message("✂️ Chia truyện thành %d đoạn", len(chunks))
    return chunks


def split_text(text, max_words=1320):
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunk = " ".join(words[start:end])
        last_dot = chunk.rfind('.')
        if 0 < last_dot < len(chunk) - 1:
            chunk = chunk[:last_dot + 1]
        chunks.append(chunk.strip())
        start += len(chunk.split())
    send_discord_message("✂️ Chia truyện thành %d đoạn", len(chunks))
    return chunks


# Summary TTS
def generate_audio_summary(summary_text: str, title_slug: str, voice="nova"):
    if not summary_text or not summary_text.strip():
        return None
    if voice =="gman":
        voice ="vi-VN-Chirp3-HD-Algieba"
    elif voice =="gfemale":
        voice ="vi-VN-Wavenet-C"
    else:
        voice =voice
    # Prefer voice-specific summary filename (WAV) and corresponding FLAC copy
    summary_wav = os.path.join(OUTPUT_DIR, f"{title_slug}_summary_{voice}.wav")
    summary_flac = os.path.join(OUTPUT_DIR, f"{title_slug}_summary_{voice}.flac")

    # If FLAC cache exists, prefer it
    if os.path.exists(summary_flac):
        send_discord_message("♻️ Dùng cache audio summary (FLAC, voice): %s", summary_flac)
        return summary_flac

    # If WAV exists but FLAC missing, try to create FLAC copy and return it
    if os.path.exists(summary_wav):
        try:
            _create_flac_copy(summary_wav, summary_flac)
            if os.path.exists(summary_flac):
                send_discord_message("♻️ Tạo FLAC từ cache WAV: %s", summary_flac)
                _write_part_manifest(summary_flac)
                return summary_flac
        except Exception:
            pass
        send_discord_message("♻️ Dùng cache audio summary (WAV, voice): %s", summary_wav)
        _write_part_manifest(summary_wav)
        return summary_wav

    send_discord_message("🎙️ Tạo audio văn án (summary)...")
    # Create WAV first then convert to FLAC for consistent downstream concatenation
    try:
        if voice == "nova" or voice == "echo":
            resp = openai.audio.speech.create(
                model="tts-1-hd",
                voice=voice,
                input=summary_text,
                instructions="Đọc bằng giọng hơi robotic, nhịp điệu nhanh giống giọng review phim.",
                response_format="wav",
            )
            # write WAV
            if hasattr(resp, 'stream_to_file'):
                resp.stream_to_file(summary_wav)
            elif hasattr(resp, 'read'):
                with open(summary_wav, 'wb') as f:
                    f.write(resp.read())
            elif isinstance(resp, (bytes, bytearray)):
                with open(summary_wav, 'wb') as f:
                    f.write(resp)
            else:
                data = getattr(resp, 'content', None) or getattr(resp, 'audio', None)
                if data:
                    with open(summary_wav, 'wb') as f:
                        f.write(data)
                else:
                    raise RuntimeError("Unsupported TTS response format")
        else:
            # Use Google/other TTS writer (already writes WAV)
            text_to_wav(
                text=summary_text,
                output_path=summary_wav,
                voice_name=voice,
            )

        # Ensure WAV created
        if not os.path.exists(summary_wav) or os.path.getsize(summary_wav) == 0:
            raise RuntimeError(f"TTS không tạo được file summary: {summary_wav}")

        # Try to create FLAC copy and prefer returning it
        try:
            _create_flac_copy(summary_wav, summary_flac)
            if os.path.exists(summary_flac):
                _write_part_manifest(summary_flac)
                send_discord_message("✅ Hoàn tất tạo audio summary (FLAC): %s", summary_flac)
                return summary_flac
        except subprocess.CalledProcessError:
            pass

        # Fallback: return WAV if FLAC couldn't be created
        _write_part_manifest(summary_wav)
        send_discord_message("✅ Hoàn tất tạo audio summary (WAV fallback): %s", summary_wav)
        return summary_wav
    except Exception as e:
        send_discord_message(f"❌ Lỗi khi tạo audio summary: {e}")
        raise


# Content TTS
def generate_audio_content(content_text: str, title_slug: str, voice="nova"):
    # Final content filename: prefer FLAC so it concatenates cleanly with other FLAC parts
    content_file_voice = os.path.join(OUTPUT_DIR, f"{title_slug}_content_{voice}.flac")

    if os.path.exists(content_file_voice):
        send_discord_message("♻️ Dùng cache audio content (FLAC, voice): %s", content_file_voice)
        return content_file_voice

    # We'll create per-part WAVs (from TTS) and then concat/encode to final FLAC
    content_file = content_file_voice
    send_discord_message("🎙️ Tạo audio nội dung truyện (FLAC)...")
    intro_text = (
        "cảm ơn đã các bạn đã nghe truyện, thích truyện thì hãy bình luận đôi câu và ấn theo dõi nhà tui để nghe thêm nhiều truyện khác nhé"
    )
    intro_file = os.path.join(OUTPUT_DIR, f"intro_{voice}.wav")
    if not os.path.exists(intro_file):
        send_discord_message("🎙️ Tạo đoạn intro kêu gọi follow...")
        resp_intro = openai.audio.speech.create(
            model="tts-1-hd",
            voice=voice,
            input=intro_text,
            instructions="Giọng kêu gọi, hào hứng. thân thiện.",
            response_format="wav",
        )
        try:
            if hasattr(resp_intro, 'stream_to_file'):
                resp_intro.stream_to_file(intro_file)
            else:
                with open(intro_file, 'wb') as f:
                    f.write(resp_intro.read() if hasattr(resp_intro, 'read') else resp_intro)
            _write_part_manifest(intro_file)
        except Exception:
            pass

    chunks = split_text_with_space(content_text, 3000)
    part_files = []
    listToRemove = []
    for i, part in enumerate(chunks, 1):
        # Part filenames include voice suffix to distinguish different TTS voices
        part_file = os.path.join(OUTPUT_DIR, f"{title_slug}_content_part_{i}_{voice}.wav")
       
        if not os.path.exists(part_file):
            send_discord_message("🎙️ Tạo đoạn content %d/%d (%s từ)...", i, len(chunks), len(part.split()))
            resp = openai.audio.speech.create(
                model="tts-1-hd",
                voice=voice,
                input=part,
              
                response_format="wav",
            )
            try:
                if hasattr(resp, 'stream_to_file'):
                    resp.stream_to_file(part_file)
                elif hasattr(resp, 'read'):
                    with open(part_file, 'wb') as f:
                        f.write(resp.read())
                elif isinstance(resp, (bytes, bytearray)):
                    with open(part_file, 'wb') as f:
                        f.write(resp)
                else:
                    data = getattr(resp, 'content', None) or getattr(resp, 'audio', None)
                    if data:
                        with open(part_file, 'wb') as f:
                            f.write(data)
                    else:
                        raise RuntimeError("Unsupported TTS response format for part")
                # After successful write, create manifest marker
                _write_part_manifest(part_file)
            except Exception as e:
                send_discord_message(f"❌ Lỗi khi tạo part content: {e}")
                raise
        part_files.append(part_file)
        if i % 8 == 0:
            send_discord_message("📢 Chèn đoạn kêu gọi follow sau đoạn %d", i)
            part_files.append(intro_file)
        listToRemove.append(part_file)

    send_discord_message("🔧 Ghép %d đoạn audio content...", len(part_files))
    concat_list_file = os.path.join(OUTPUT_DIR, f"{title_slug}_content_concat_list.txt")
    valid_items = []
    with open(concat_list_file, 'w', encoding='utf-8') as f:
        for pf in part_files:
            if not pf:
                continue
            if not os.path.exists(pf):
                continue
            f.write(f"file '{os.path.abspath(pf)}'\n")
            valid_items.append(pf)
    if not valid_items:
        raise RuntimeError("Không có file audio hợp lệ để ghép (content)")
    try:
        # Concatenate WAV parts into a temporary WAV, then create a FLAC copy
        temp_wav = os.path.join(OUTPUT_DIR, f"{title_slug}_content_{voice}.wav")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_file,
            "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", temp_wav
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        # Use centralized flac encoder to ensure consistent encoding across flows
        try:
            _create_flac_copy(temp_wav, content_file)
            send_discord_message("✅ Hoàn tất tạo audio content (FLAC): %s", content_file)
        except subprocess.CalledProcessError:
            # If flac creation fails, fall back to temp_wav
            send_discord_message("⚠️ Không thể tạo FLAC (dùng WAV tạm): %s", temp_wav)
            try:
                _write_part_manifest(temp_wav)
            except Exception:
                pass
            return temp_wav

        # cleanup concat list and temporary wav
        try:
            os.remove(concat_list_file)
        except Exception:
            pass
        try:
            if os.path.exists(temp_wav):
                os.remove(temp_wav)
        except Exception:
            pass

        try:
            _write_part_manifest(content_file)
        except Exception:
            pass

        # cleanup per-part manifests created for content parts
        try:
            for pf in valid_items:
                try:
                    if os.path.exists(pf + ".done"):
                        os.remove(pf + ".done")
                except Exception:
                    pass
        except Exception:
            pass
        return content_file
    except Exception as e:
        send_discord_message(f"❌ Lỗi khi ghép audio content: {e}")
        raise


# Full final audio (concatenate per-TTS parts if present otherwise run TTS)
def generate_audio(text: str, title_slug: str, voice="nova"):
    # Final audio filename includes voice to distinguish variants.
    final_audio_voice = os.path.join(OUTPUT_DIR, f"{title_slug}_{voice}.wav")
    final_audio_legacy = os.path.join(OUTPUT_DIR, f"{title_slug}.wav")
    final_flac_voice = os.path.join(OUTPUT_DIR, f"{title_slug}_{voice}.flac")
    final_flac_legacy = os.path.join(OUTPUT_DIR, f"{title_slug}.flac")

    # prefer voice-specific final files if present, fallback to legacy
    if os.path.exists(final_audio_voice):
        send_discord_message("🎧 Dùng cache audio (WAV, voice): %s", final_audio_voice)
        if os.path.exists(final_flac_voice):
            send_discord_message("♻️ Dùng cache audio (FLAC preferred, voice): %s", final_flac_voice)
            return final_flac_voice
        return final_audio_voice
    if os.path.exists(final_audio_legacy):
        send_discord_message("🎧 Dùng cache audio (WAV): %s", final_audio_legacy)
        if os.path.exists(final_flac_legacy):
            send_discord_message("♻️ Dùng cache audio (FLAC preferred): %s", final_flac_legacy)
            return final_flac_legacy
        return final_audio_legacy
    # default to voice-specific path when creating new files
    final_audio = final_audio_voice
    final_flac = final_flac_voice

   
    # fallback: generate parts via OpenAI TTS
    intro_text = (
        "cảm ơn các bạn đã nghe truyện, thích truyện thì hãy bình luận đôi câu và ấn theo dõi nhà tui để nghe thêm nhiều truyện khác nhé"
    )
    intro_file = os.path.join(OUTPUT_DIR, f"intro_{voice}.wav")
    if not os.path.exists(intro_file):
        send_discord_message("🎙️ Tạo đoạn intro kêu gọi follow...")
        resp_intro = openai.audio.speech.create(
            model="tts-1-hd",
            voice=voice,
            input=intro_text,
            instructions="Giọng kêu gọi, hào hứng. thân thiện.",
            response_format="wav",
        )
        try:
            if hasattr(resp_intro, 'stream_to_file'):
                resp_intro.stream_to_file(intro_file)
            else:
                with open(intro_file, 'wb') as f:
                    f.write(resp_intro.read() if hasattr(resp_intro, 'read') else resp_intro)
            _write_part_manifest(intro_file)
        except Exception:
            pass

    chunks = split_text_with_space(text, 4096)
    part_files = []
    listToRemove = []
    for i, part in enumerate(chunks, 1):
        # Per-part files include voice suffix
        part_file = os.path.join(OUTPUT_DIR, f"{title_slug}_part_{i}_{voice}.wav")
        send_discord_message("🎙️ Tạo đoạn audio %d/%d (%s từ)...", i, len(chunks), len(part.split()))
        if not os.path.exists(part_file):
            resp = openai.audio.speech.create(
                model="tts-1-hd",
                voice=voice,
                input=part,
               
                response_format="wav",
                
            )
            # Support SDK variations
            try:
                if hasattr(resp, 'stream_to_file'):
                    resp.stream_to_file(part_file)
                elif hasattr(resp, 'read'):
                    with open(part_file, 'wb') as f:
                        f.write(resp.read())
                elif isinstance(resp, (bytes, bytearray)):
                    with open(part_file, 'wb') as f:
                        f.write(resp)
                else:
                    data = getattr(resp, 'content', None) or getattr(resp, 'audio', None)
                    if data:
                        with open(part_file, 'wb') as f:
                            f.write(data)
                    else:
                        raise RuntimeError('Không thể lưu kết quả TTS')
                if not os.path.exists(part_file) or os.path.getsize(part_file) == 0:
                    raise RuntimeError(f"TTS không tạo được file phần {i}: {part_file}")
                _write_part_manifest(part_file)
            except Exception as e:
                send_discord_message(f"❌ Lỗi khi tạo part: {e}")
                raise
        part_files.append(part_file)
        if i % 8 == 0:
            send_discord_message("📢 Chèn đoạn kêu gọi follow sau đoạn %d", i)
            part_files.append(intro_file)
        listToRemove.append(part_file)

    concat_list_file = os.path.join(OUTPUT_DIR, f"{title_slug}_concat_list.txt")
    _write_concat_list(part_files, concat_list_file)
    try:
        _concat_audio_from_list(concat_list_file, final_audio)
        send_discord_message("✅ Hoàn tất tạo audio (WAV): %s", final_audio)
        try:
            _create_flac_copy(final_audio, final_flac)
            send_discord_message("✅ Hoàn tất tạo audio (FLAC): %s", final_flac)
        except subprocess.CalledProcessError:
            final_flac = None
        try:
            os.remove(concat_list_file)
        except Exception:
            pass
        try:
            _write_part_manifest(final_audio)
        except Exception:
            pass
        # cleanup per-part manifests created during TTS generation
        try:
            for p in part_files:
                try:
                    if os.path.exists(p + ".done"):
                        os.remove(p + ".done")
                except Exception:
                    pass
        except Exception:
            pass
        if final_flac and os.path.exists(final_flac):
            return final_flac
        return final_audio
    except subprocess.CalledProcessError as e:
        send_discord_message(f"❌ Lỗi khi concat audio: {e.stderr.decode()}")
        raise


# Gemini flow
def generate_audio_Gemini(text: str, title_slug: str, voices: str = "vi-VN-Standard-C"):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    final_audio = os.path.join(OUTPUT_DIR, f"{title_slug}_{voices}.wav")
    final_flac = os.path.join(OUTPUT_DIR, f"{title_slug}_{voices}.flac")
    if os.path.exists(final_audio):
        send_discord_message("🎧 Dùng cache audio: %s", final_audio)
        if os.path.exists(final_flac):
            send_discord_message("♻️ Dùng cache audio (FLAC preferred): %s", final_flac)
            return final_flac
        return final_audio

  

    # create intro (reuse OpenAI TTS)
    if voices =="vi-VN-Standard-D" :
        intro_text = (
            "cảm ơn các bạn đã nghe truyện, thích truyện thì hãy bình luận đôi câu và ấn theo dõi nhà toi để nghe thêm nhiều truyện hay nữa nhé"
        )
    else:
        intro_text = (
            "cảm ơn các bạn đã nghe truyện, iu tui iu truyện thì hãy bình luận đôi câu và ấn theo dõi nhà tui để nghe thêm nhiều truyện hay nhoaaa ❤️‍🔥❤️‍🔥❤️‍🔥"
        )
    intro_file = os.path.join(OUTPUT_DIR, f"intro_gemini_{voices}.wav")
    if not os.path.exists(intro_file):
        try:
            text_to_wav(intro_text, intro_file, voice_name=voices)
            _write_part_manifest(intro_file)
        except Exception as e:
            send_discord_message(f"⚠️ Không thể tạo intro bằng OpenAI TTS: {e}")

    text = re.sub(r"[\x00-\x1F\x7F]", " ", text).strip()
    chunks = split_text_by_bytes(text, 5000)
    part_files = []
    listToRemove = []
    for i, part in enumerate(chunks, 1):
        part_file = os.path.join(OUTPUT_DIR, f"{title_slug}_gemini_{voices}_part_{i}.wav")
        send_discord_message("🎙️ Gemini TTS: tạo đoạn %d/%d (%s từ)...", i, len(chunks), len(part.split()))
        if not os.path.exists(part_file):
            try:
                text_to_wav(part, part_file, voice_name=voices)
                _write_part_manifest(part_file)
            except Exception as e:
                send_discord_message(f"❌ Lỗi khi gọi Gemini TTS cho đoạn {i}: {e}")
                raise
        if not part_file or not os.path.exists(part_file):
            send_discord_message(f"⚠️ Không tạo được file audio cho đoạn {i} (file missing or None), bỏ qua.")
            continue
        part_files.append(part_file)
        if i % 6 == 0:
            if os.path.exists(intro_file):
                part_files.append(intro_file)
        listToRemove.append(part_file)

    concat_list_file = os.path.join(OUTPUT_DIR, f"{title_slug}_gemini_concat_list.txt")
    _write_concat_list(part_files, concat_list_file)
    try:
        _concat_audio_from_list(concat_list_file, final_audio)
        send_discord_message("✅ Hoàn tất tạo audio (Gemini WAV): %s", final_audio)
        try:
            _create_flac_copy(final_audio, final_flac)
        except subprocess.CalledProcessError:
            final_flac = None
        try:
            os.remove(concat_list_file)
        except Exception:
            pass
        try:
            _write_part_manifest(final_audio)
        except Exception:
            pass
        # cleanup per-part manifests created during Gemini TTS generation
        try:
            for p in part_files:
                try:
                    if os.path.exists(p + ".done"):
                        os.remove(p + ".done")
                except Exception:
                    pass
        except Exception:
            pass
        if final_flac and os.path.exists(final_flac):
            return final_flac
        return final_audio
    except subprocess.CalledProcessError as e:
        send_discord_message(f"❌ Lỗi khi ghép audio (Gemini): {e.stderr.decode()}")
        raise
