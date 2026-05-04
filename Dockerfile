FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY analisar_video.py .
COPY video_analyzer_web.py .

ENV PYTHONUNBUFFERED=1

EXPOSE 3340

CMD ["python", "video_analyzer_web.py"]
