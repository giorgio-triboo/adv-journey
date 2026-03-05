# Cepu-lavorazioni backend - produzione
# Build context: repo root (deploy/Dockerfile usato da afterinstall)
# Identico a backend/Dockerfile ma senza --reload

FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Rome
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright in /ms-playwright (deve coincidere con PLAYWRIGHT_BROWSERS_PATH a runtime)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN mkdir -p /ms-playwright && playwright install --with-deps chromium

COPY backend/ .
COPY frontend/ ./frontend

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
