# ============================================================
# FreelanceDZ v4 — STREAMLIT UI service image
# A pure API client of the engine: only ui/ + the slim UI dependency
# set. It contains no engine code and never touches the database —
# all data flows through the engine's documented HTTP API.
# ============================================================
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-ui.txt .
RUN pip install --no-cache-dir -r requirements-ui.txt

COPY ui/ ./ui/

RUN groupadd -r fdzui && useradd -r -g fdzui -d /app -s /sbin/nologin fdzui \
    && chown -R fdzui:fdzui /app

ENV PYTHONUNBUFFERED=1 \
    ENGINE_URL=http://engine:8080 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0

USER fdzui

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4).status==200 else 1)"

EXPOSE 8501

CMD ["streamlit", "run", "ui/app.py"]
