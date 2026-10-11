# ---------- 1) Bygg frontend ----------
FROM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2) Kjøretid ----------
FROM python:3.12-slim
ARG APP_VERSION=0.9.0
LABEL org.opencontainers.image.title="smart-media-cleanup" \
      org.opencontainers.image.description="Skrivebeskyttet analyse av mediebibliotek på TrueNAS SCALE"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SMC_VERSION=${APP_VERSION} \
    SMC_DATA_DIR=/data \
    SMC_STATIC_DIR=/app/static \
    TZ=Europe/Oslo

WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /src/dist ./static

# 568:568 = «apps»-brukeren på TrueNAS SCALE. Kan overstyres med user: i YAML.
RUN mkdir -p /data && chown 568:568 /data
USER 568:568
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# Én arbeider: bakgrunnsjobbene kjører i prosessen og skal ikke dupliseres.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
