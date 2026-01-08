#!/bin/sh
set -e

# Start album Flask app via Gunicorn on port 5000 (chdir into transcribe-api folder where app.py lives).
# Use 2 workers; run in background so we can start the main FastAPI app afterwards.
if [ -d "/app/transcribe-api" ]; then
  echo "Starting album app (gunicorn) on :5000"
  gunicorn -w 2 -b 0.0.0.0:5000 --chdir /app/transcribe-api app:app &
else
  echo "transcribe-api folder not present; skipping album app start"
fi

# Start tts-audio FastAPI app with uvicorn in foreground (PID 1)
echo "Starting tts-audio (uvicorn) on :8000"
exec uvicorn app:app --host 0.0.0.0 --port 8000
