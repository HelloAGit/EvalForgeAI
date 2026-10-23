# syntax=docker/dockerfile:1
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Empty API base => browser calls the same origin that serves the UI.
ENV NEXT_PUBLIC_API_BASE_URL="" NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000 STATIC_DIR=/app/static \
    DATABASE_URL=sqlite:////app/data/evalforge.db APP_ENV=production
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY datasets ./datasets
COPY --from=frontend /app/frontend/out ./static
RUN useradd --system --uid 10001 --no-create-home evalforge \
    && mkdir -p /app/data && chown -R evalforge /app/data
USER evalforge
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/health'%os.environ.get('PORT','8000'),timeout=3)"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
