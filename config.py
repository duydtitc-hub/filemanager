import os
from concurrent.futures import ThreadPoolExecutor
import asyncio
import logging
from dotenv import load_dotenv

# Load .env (if present)
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
VIDEO_CACHE_DIR = os.path.join(OUTPUT_DIR, "video_cache")

# Read API keys from environment variables (default empty)
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GOOGLE_TTS_API_KEY = os.environ.get("GOOGLE_TTS_API_KEY", "")
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(VIDEO_CACHE_DIR, exist_ok=True)

# Executor and task queue used across modules
executor = ThreadPoolExecutor(max_workers=int(os.environ.get("MAX_WORKERS", "4")))
TASK_QUEUE: asyncio.Queue = asyncio.Queue()
WORKER_COUNT = int(os.environ.get("WORKER_COUNT", "2"))

# Basic logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("truyen-video")
