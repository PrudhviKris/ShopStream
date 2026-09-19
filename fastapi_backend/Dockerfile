# Storefront + API. The React build is produced in a first stage and copied
# in, so this one image serves both the SPA and the JSON API on port 8000.
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS runtime

# - PYTHONUNBUFFERED: logs reach docker logs immediately
# - PIP_NO_CACHE_DIR: keeps the image small
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# curl is used by the compose healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY fastapi_backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt gunicorn

COPY fastapi_backend/ ./
COPY --from=frontend /build/dist ../frontend/dist

# Run as a non-root user, and let it own the media directory it writes to.
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /app/media/products \
 && chown -R appuser:appuser /app /frontend
USER appuser

EXPOSE 8000

# Uvicorn workers under gunicorn: real process management, and the
# WebSocket endpoint keeps working (plain gunicorn sync workers can't).
# Sticky state lives in MySQL, but in-memory WebSocket connections do not —
# see docs/DEPLOYMENT.md before raising WEB_CONCURRENCY above 1.
ENV WEB_CONCURRENCY=1
CMD ["sh", "-c", "alembic upgrade head && exec gunicorn app.main:app \
     --worker-class uvicorn.workers.UvicornWorker \
     --workers ${WEB_CONCURRENCY} --bind 0.0.0.0:8000 \
     --access-logfile - --error-logfile - --timeout 60"]
