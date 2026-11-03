FROM python:3.12-slim

# OCR for scanned letters/photos, poppler for PDF page images
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN useradd -m appuser && mkdir -p /data && chown -R appuser /data /app
USER appuser
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8000
CMD ["./scripts/start.sh"]
