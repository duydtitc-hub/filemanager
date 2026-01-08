import requests
import time
import os
import json
import base64
from datetime import datetime
from dotenv import load_dotenv
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BOT_DIR, ".env"))

try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None
    types = None
def send_discord_message(*args, sep=' ', end='\n'):
    if len(args) == 0:
        content = ''
    elif isinstance(args[0], str) and '%' in args[0] and len(args) > 1:
        try:
            content = args[0] % args[1:]  # dùng kiểu printf
        except Exception:
            content = sep.join(str(a) for a in args)
    else:
        content = sep.join(str(a) for a in args)
    content += end
    try:       
      
        """
        Gửi tin nhắn vào Discord channel bằng requests.
        
        Args:
            channel_id (str): ID của channel.
            content (str): Nội dung tin nhắn.
            token (str, optional): Bot token. Nếu None, sẽ lấy từ biến môi trường DISCORD_BOT_TOKEN.
        
        Returns:
            dict: JSON phản hồi từ Discord hoặc dict chứa lỗi.
        """
        token = os.getenv("DISCORD_BOT_TOKEN")
        time.sleep(1);
        channel_id ='1431324318775775324';
    

        url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        headers = {
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json"
        }
        parts = []
        if len(content) <= 2000:
            parts = [content]
        else:
            # Tách theo dòng nếu có thể để tránh cắt giữa câu
            lines = content.splitlines()
            current = ""
            for line in lines:
                if len(current) + len(line) + 1 > 2000:
                    parts.append(current)
                    current = line
                else:
                    current += ("\n" if current else "") + line
            if current:
                parts.append(current)

            # Nếu vẫn còn phần nào vượt quá 2000 (không có xuống dòng), cắt cứng
            new_parts = []
            for part in parts:
                if len(part) > 2000:
                    chunks = [part[i:i+2000] for i in range(0, len(part), 2000)]
                    new_parts.extend(chunks)
                else:
                    new_parts.append(part)
            parts = new_parts

        responses = []
        for i, part in enumerate(parts, 1):
            payload = {"content": part}
            try:
                resp = requests.post(url, headers=headers, json=payload)
                if resp.status_code in (200, 201):
                    responses.append(resp.json())
                else:
                    responses.append({"error": f"Lỗi {resp.status_code}", "detail": resp.text})
            except Exception as e:
                responses.append({"error": str(e)})

        return responses
    except:
        import logging
        logger = logging.getLogger(__name__)
        logger.info("DiscordErrot")
        logger.info(content)
    
        