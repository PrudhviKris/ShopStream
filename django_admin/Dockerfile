# Django admin + analytics dashboard + report exports, on port 8001.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY django_admin/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt gunicorn

COPY django_admin/ ./

# Collect admin + Chart.js assets so gunicorn can serve them via whitenoise.
ENV DJANGO_SECRET_KEY=build-time-only-not-used-at-runtime \
    DJANGO_DEBUG=0
RUN python manage.py collectstatic --noinput

RUN useradd --create-home --uid 10002 djangouser \
 && mkdir -p /app/media \
 && chown -R djangouser:djangouser /app
USER djangouser

EXPOSE 8001

# migrate creates Django's own auth/session tables only — the store tables
# are managed=False and owned by the FastAPI service's Alembic migrations.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn ecommerce_admin.wsgi:application \
     --workers ${WEB_CONCURRENCY:-2} --bind 0.0.0.0:8001 \
     --access-logfile - --error-logfile - --timeout 60"]
