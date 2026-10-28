# OpenRun: single container (FastAPI + built React UI). Data lives in the /data volume.

FROM node:22.11-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    TZ=Europe/Madrid \
    OPENRUN_DATA=/data OPENRUN_DB=/data/openrun.db OPENRUN_GARMIN_TOKENS=/data/garmin \
    OPENRUN_TRUST_LOCAL=0 OPENRUN_TRUST_PROXY=1 OPENRUN_HOST=0.0.0.0 PORT=8000
WORKDIR /app
# curl: Coolify's health check runs curl/wget inside the container
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=web /web/dist frontend/dist
RUN useradd --uid 1000 --create-home openrun && mkdir -p /data && chown openrun:openrun /data
USER openrun
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1
WORKDIR /app/backend
# --proxy-headers: Traefik passes the real client IP and https scheme
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
