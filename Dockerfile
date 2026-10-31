# NEXUS AI backend image: FastAPI + LangGraph orchestrator + simulated enterprise
# tool adapters. Build context is the `backend/` directory.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so the layer is reused when only application code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# The orchestrator writes checkpoints and generated documents under /app/data.
RUN useradd --create-home --uid 10001 nexus \
    && mkdir -p /app/data \
    && chown -R nexus:nexus /app
USER nexus

EXPOSE 8000

# Compose waits for this before starting the web container.
HEALTHCHECK --interval=15s --timeout=10s --start-period=25s --retries=5 \
    CMD python -c "import urllib.request,json; json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health'))" || exit 1

# One worker only: workflow runs live in this process's thread pool and the
# LangGraph checkpointer is a local SQLite file, so multiple workers would each
# hold a different view of the same run.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
