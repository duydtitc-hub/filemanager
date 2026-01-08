FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# ==========================
# System dependencies
# ==========================
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    chromium-browser \
    chromium-chromedriver \
    sox \
    libsox-fmt-all \
    rubberband-cli \
    fontconfig \
    fonts-noto \
    fonts-dejavu-core \
    ca-certificates \
    curl \
    # Playwright dependencies for headless Chromium
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libxshmfence1 \
    libpangocairo-1.0-0 \
    libx11-xcb1 \
    libxss1 \
    libxcb1 \
    libdrm2 \
    libxkbcommon0 \
    libgtk-3-0 \
    # ALSA userspace (some Ubuntu releases provide different package names)
    libasound2-data \
    alsa-utils \
    libdbus-1-3 \
    fonts-noto-color-emoji \
 && fc-cache -fv \
 && rm -rf /var/lib/apt/lists/*
# ==========================
# Copy font custom (nếu có)
# ==========================
COPY *.ttf /usr/share/fonts/truetype/custom/
RUN fc-cache -fv || true

# ==========================
# App setup
# ==========================
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt
RUN pip install --no-cache-dir --break-system-packages \
    playwright \
    faster-whisper>=1.0.0 \
    ctranslate2>=4.5.0 \
    yt-dlp

# Install Playwright browsers (Chromium) so `playwright.sync_api` can launch
# and avoid runtime errors like: "Executable doesn't exist ..."
RUN python3 -m playwright install chromium


# ==========================
# Expose + start
# ==========================
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
