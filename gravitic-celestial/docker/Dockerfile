# ---- Stage 1: builder ----
FROM python:3.9-slim AS builder

WORKDIR /build

# Install build deps for psycopg2, sentencepiece, etc.
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements-docker.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements-docker.txt

# ---- Stage 2: runtime ----
FROM python:3.9-slim

WORKDIR /app

# Runtime deps for psycopg2
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 && \
    rm -rf /var/lib/apt/lists/*

# Copy installed Python packages
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Default env vars
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8000 8501

# Default command (overridden per-service in docker-compose)
CMD ["uvicorn", "services.api:app", "--host", "0.0.0.0", "--port", "8000"]
