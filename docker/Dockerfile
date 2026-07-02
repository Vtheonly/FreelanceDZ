# syntax=docker/dockerfile:1
# ============================================================
#  FreelanceDZ Refactored — Production Docker Image
#  Multi-stage build: build deps in 'builder', copy to slim runtime.
# ============================================================

FROM python:3.11-slim AS builder

# Build-time dependencies. lxml needs libxml2/libxslt dev headers.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libxml2-dev \
        libxslt1-dev \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt


# ---------- Runtime stage ----------
FROM python:3.11-slim AS runtime

# Runtime shared libs for lxml + httpx[http2].
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxml2 \
        libxslt1.1 \
        libffi8 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed Python packages from the builder stage.
COPY --from=builder /install /usr/local

# Copy the application source.
COPY . /app/

# Create data directories so the container can write logs/db/exports.
RUN mkdir -p /app/data/logs /app/data/cache/llm /app/data/exports

# Create a non-root user and grant ownership of the data directory.
# Running as non-root is a container-security best practice that limits
# the blast radius of any exploit.
RUN groupadd -r deephuntr && \
    useradd -r -g deephuntr -d /app -s /sbin/nologin deephuntr && \
    chown -R deephuntr:deephuntr /app

# Default to production settings.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LOG_LEVEL=INFO \
    LOG_FORMAT=json \
    DATABASE_PATH=/app/data/deephuntr.db

EXPOSE 8080

USER deephuntr

# Health check — hit the FastAPI /health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health').status == 200 else 1)"

# Run the API server by default. Override with `cli <command>` for one-shot ops.
CMD ["python", "-m", "uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8080"]
