FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Tesseract is the system OCR executable; language models are shipped with the
# project in backend/tessdata.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

RUN useradd --create-home --shell /usr/sbin/nologin app \
    && mkdir -p data uploads/originals uploads/processed logs reports \
    && chown -R app:app /app

USER app

EXPOSE 10000

CMD ["sh", "-c", "python -m alembic upgrade head && exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
