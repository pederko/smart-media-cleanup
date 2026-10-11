# ---------- 1) Build the web UI ----------
FROM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2) Runtime ----------
FROM python:3.12-slim
ARG APP_VERSION=1.1.2
LABEL org.opencontainers.image.title="smart-media-cleanup" \
      org.opencontainers.image.description="Explainable cleanup suggestions for a Plex media library on TrueNAS SCALE" \
      org.opencontainers.image.source="https://github.com/pederko/smart-media-cleanup"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SMC_VERSION=${APP_VERSION} \
    SMC_DATA_DIR=/data \
    SMC_STATIC_DIR=/app/static \
    TZ=UTC

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /src/dist ./static

# 568:568 = the «apps» user on TrueNAS SCALE. Can be overridden with user: in the compose file.
RUN mkdir -p /data && chown 568:568 /data
USER 568:568
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# One worker: the background jobs run in the process and must not be duplicated.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
