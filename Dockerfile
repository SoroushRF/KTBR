# KTBR - Face Blur Telegram Bot
# Production Docker Image

FROM python:3.11-slim

# Install system dependencies including FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Set working directory
WORKDIR /app

# Copy requirements first (for better Docker layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY bot.py .
COPY face_detection_yunet_2023mar.onnx .

# Create a directory for persistent data
RUN mkdir -p /app/data

# The authorized_ids.json will be stored in /app/data for persistence
# You can mount a volume to /app/data to persist across container restarts

# Environment variables (set these when running the container)
ENV BOT_TOKEN=""
ENV ALLOWED_USERNAMES=""
ENV DATA_DIR="/app/data"
ENV PYTHONUNBUFFERED=1

# Health check - verify ffmpeg is available
RUN ffmpeg -version && python --version

# Run the bot
CMD ["python", "bot.py"]
