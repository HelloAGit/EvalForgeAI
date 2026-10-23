# syntax=docker/dockerfile:1
# Targets:
#   web    - lean API image (FastAPI, PDF generation)            -> ghcr.io/helloagit/evalforgeai
#   worker - web image + FFmpeg for video rendering/scheduler    -> ghcr.io/helloagit/evalforgeai-worker
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_ENV=production PORT=8000 DATABASE_URL=sqlite:////data/evalforge.db ARTIFACT_DIR=/data/artifacts
WORKDIR /app
RUN groupadd --system --gid 10001 evalforge && useradd --system --uid 10001 --gid evalforge --home /app --shell /usr/sbin/nologin evalforge \
    && mkdir -p /data && chown evalforge:evalforge /data
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
VOLUME ["/data"]

FROM base AS web
USER evalforge
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/api/v1/health', timeout=4)"
# exec so SIGTERM reaches uvicorn and in-flight requests finish (graceful shutdown)
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --timeout-graceful-shutdown 30"]

FROM base AS worker
COPY requirements-render.txt .
RUN pip install -r requirements-render.txt \
    && apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
USER evalforge
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,sys,time; p=os.environ.get('WORKER_HEARTBEAT_FILE','/tmp/evalforge-worker-heartbeat'); sys.exit(0 if time.time()-os.path.getmtime(p)<60 else 1)"
STOPSIGNAL SIGTERM
CMD ["python", "-m", "app.worker"]
