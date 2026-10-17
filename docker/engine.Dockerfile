# ============================================================
# FreelanceDZ v4 — ENGINE service image
# The core engine (API + discovery + resolution + geo) in its own
# isolated runtime. No Streamlit, no UI code — the engine is fully
# usable and testable without any presentation layer.
# ============================================================
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libxml2 libxslt1.1 libffi8 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Engine code only (the ui/ directory ships in the ui image).
COPY api/ ./api/
COPY config/ ./config/
COPY core/ ./core/
COPY domain/ ./domain/
COPY engine/ ./engine/
COPY infrastructure/ ./infrastructure/
COPY services/ ./services/
COPY utils/ ./utils/
COPY cli.py main.py pyproject.toml ./

RUN mkdir -p /app/data/logs /app/data/exports /app/data/attachments \
    && groupadd -r fdz && useradd -r -g fdz -d /app -s /sbin/nologin fdz \
    && chown -R fdz:fdz /app

ENV PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/app/data/leads.db \
    API_HOST=0.0.0.0 \
    API_PORT=8080

USER fdz

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health', timeout=4).status==200 else 1)"

EXPOSE 8080

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8080"]
