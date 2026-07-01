FROM python:3.11-slim-buster

# ---------- Metadata ----------
LABEL org.opencontainers.image.title="DZ Sales Intelligence"
LABEL org.opencontainers.image.description="AI-powered business discovery & lead intelligence platform for Algeria"
LABEL org.opencontainers.image.version="1.0.0"

# ---------- Runtime environment ----------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Africa/Algiers

WORKDIR /app

# ---------- System deps (kept minimal for low-RAM footprint) ----------
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        tzdata \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && ln -fs /usr/share/zoneinfo/Africa/Algiers /etc/localtime

# ---------- Python deps (cached layer) ----------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------- Application code ----------
COPY . .

# ---------- Persistent data volume ----------
RUN mkdir -p /app/data/cache /app/data/exports /app/data/logs
VOLUME ["/app/data"]

EXPOSE 8080

# Default: run the CLI menu. Override with `python cli.py discover ...` etc.
CMD ["python", "cli.py", "--help"]
