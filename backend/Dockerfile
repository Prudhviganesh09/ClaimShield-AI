FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_THREAD_LIMIT=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --uid 10001 --create-home claimshield && mkdir -p /data/uploads && chown -R claimshield:claimshield /data
COPY --chown=claimshield:claimshield app ./app
COPY --chown=claimshield:claimshield migrations ./migrations
COPY --chown=claimshield:claimshield certs ./certs
COPY --chown=claimshield:claimshield alembic.ini .
USER claimshield
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log"]
