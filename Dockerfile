# DocMind — single container, everything open source and free.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-heb tesseract-ocr-eng poppler-utils imagemagick libheif1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt gunicorn

COPY backend backend
COPY frontend frontend

RUN useradd --create-home docmind && mkdir -p /data && chown docmind /data
USER docmind
ENV DOCMIND_DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8000
WORKDIR /app/backend
# One worker: rate limiter + job queue are in-process (see docs/SECURITY.md).
CMD ["gunicorn", "-w", "1", "--threads", "8", "-b", "0.0.0.0:8000", "run:app"]
