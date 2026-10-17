# ============================================================
# FreelanceDZ v3 — multi-stage image
# Stage 1 builds the C++20 SIMD native core (g++), stage 2 runs
# the Python engine with the compiled library in place.
# ============================================================
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY engine_native/ ./engine_native/
RUN bash engine_native/build.sh /build/out

# ------------------------------------------------------------
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libxml2 libxslt1.1 libffi8 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=builder /build/out/libfdz_engine.so /app/engine_native/libfdz_engine.so

RUN mkdir -p /app/data/logs /app/data/exports /app/data/attachments \
    && groupadd -r fdz && useradd -r -g fdz -d /app -s /sbin/nologin fdz \
    && chown -R fdz:fdz /app

ENV PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/app/data/leads.db \
    API_HOST=0.0.0.0

USER fdz

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health').status==200 else 1)"

EXPOSE 8080
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8080"]
