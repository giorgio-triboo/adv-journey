FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (needed for some python packages or playwright)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for better Docker layer caching)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (chromium only to save space/time)
RUN playwright install --with-deps chromium

# Copy backend code
COPY backend/ .

# Copy frontend (build context is project root)
COPY frontend/ ./frontend

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
