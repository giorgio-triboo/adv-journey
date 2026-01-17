FROM python:3.13-slim

WORKDIR /app

# Install system dependencies (needed for some python packages or playwright)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set timezone to Europe/Rome (CET/CEST)
ENV TZ=Europe/Rome
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Copy requirements first (for better Docker layer caching)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (chromium only to save space/time)
RUN playwright install --with-deps chromium

# Copy backend code
COPY backend/ .

# Copy frontend (build context is project root)
COPY frontend/ ./frontend

# Healthcheck configuration
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
