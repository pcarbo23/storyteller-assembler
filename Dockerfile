FROM python:3.10-slim

# Install system dependencies: espeak-ng (for Coqui TTS), default-jre (for java-based dtb_encryptor)
RUN apt-get update && apt-get install -y --no-install-recommends \
    espeak-ng \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app

CMD ["python", "src/main.py"]
