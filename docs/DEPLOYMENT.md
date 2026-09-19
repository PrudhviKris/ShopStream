# Deployment

Two services share one MySQL database:

| Service | Port | What it serves |
|---|---|---|
| `api` (FastAPI) | 8000 | The storefront (built React app), the JSON API, Swagger at `/docs`, the WebSocket at `/ws/notifications`, uploaded images at `/media/...` |
| `admin` (Django) | 8001 | `/admin/` (users, products, orders, notifications, emails), `/analytics/`, `/reports/` |

The API owns the store schema through Alembic; Django owns only its own
auth/session tables (the store models are `managed = False`).

## Docker (recommended)

```bash
cp .env.docker.example .env      # then fill in the secrets
docker compose up --build
```

Generate the two required secrets:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

- `api` runs `alembic upgrade head` before serving, so the schema is created
  and migrated on every deploy.
- `admin` runs `manage.py migrate` for Django's own tables, and serves static
  files through whitenoise.
- Product images live in the shared `media` volume, written by the admin and
  served by the API.
- Both containers run as non-root and have healthchecks; `db` uses a named
  volume, so `docker compose down` keeps your data (`down -v` deletes it).

Create the first Django superuser once the stack is up:

```bash
docker compose exec admin python manage.py createsuperuser
```

Seed the catalogue (optional):

```bash
docker compose exec api python seed.py
```

> **Not yet verified:** the Dockerfiles and compose file were written and the
> compose file parses, but no image has been built in this environment
> (no Docker CLI available). Expect to iterate on the first `docker compose
> up --build`.

## Without Docker

```bash
# API + storefront
cd fastapi_backend
pip install -r requirements.txt
alembic upgrade head
cd ../frontend && npm ci && npm run build
cd ../fastapi_backend
uvicorn app.main:app --port 8000          # dev
# production: gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000

# Django admin
cd django_admin
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput  # production only
python manage.py runserver 8001           # dev
# production: gunicorn ecommerce_admin.wsgi:application -b 0.0.0.0:8001
```

## Production checklist

**Required — the API refuses to start with `APP_ENV=production` otherwise:**

- [ ] `JWT_SECRET_KEY` is a real random value, at least 32 characters
- [ ] `CORS_ORIGINS` lists exact origins, never `*`
- [ ] `DATABASE_URL`/`MYSQL_*` points at MySQL, not SQLite
- [ ] `AUTO_CREATE_SCHEMA=false` — schema changes come from `alembic upgrade head`

**Django refuses to start with `DJANGO_DEBUG=0` unless:**

- [ ] `DJANGO_SECRET_KEY` is set to something other than the development default
- [ ] `DJANGO_ALLOWED_HOSTS` lists your hostnames
- [ ] `DJANGO_CSRF_TRUSTED_ORIGINS` lists the admin's public origin (`https://...`)

**Behind HTTPS:**

- [ ] `TRUST_PROXY_HEADERS=true` (API) so client IPs in rate limiting are real
- [ ] `HSTS_SECONDS=31536000` (API) and `DJANGO_HSTS_SECONDS=31536000`
- [ ] `DJANGO_SSL_REDIRECT=1`
- [ ] `TRUSTED_HOSTS` (API) lists your hostnames if the API is exposed directly

**Database:**

- [ ] The app connects as a non-root user with rights on the store database
      only (the compose stack already creates `MYSQL_USER` for this)
- [ ] Backups: `mysqldump` on a schedule, restore tested at least once
- [ ] `alembic upgrade head` runs as a release step, before new code serves

**Payments and email:**

- [ ] Live Stripe keys, and the webhook endpoint registered at
      `https://<your-domain>/payments/webhook` with its signing secret in
      `STRIPE_WEBHOOK_SECRET`
- [ ] `EMAIL_BACKEND=smtp` with a provider (SendGrid/SES) and a verified
      `EMAIL_FROM`; decide on `SMTP_SEND_TO_LOCAL_ACCOUNTS`

## Scaling notes

Two pieces of state live in the API process, so **`WEB_CONCURRENCY=1` is the
safe default**:

1. **WebSocket connections** are held per process. With several workers, a
   customer connected to worker A won't receive an event published by worker
   B. Fix by moving the fan-out to Redis pub/sub (`notification_service.publish`
   is the single place that would change).
2. **Rate limiting** counts per process, so N workers means N× the limit. Move
   it to Redis, or enforce it in the proxy.

Everything else — orders, payments, sessions, the email outbox — is in MySQL
and scales horizontally already.

## Health and logs

- `GET /health` on the API returns service, version and status; compose uses
  it as the healthcheck.
- Both containers log to stdout (`docker compose logs -f api admin`).
- Set `LOG_LEVEL=DEBUG` on the API for verbose logs; Stripe webhook failures
  and email delivery failures are logged with full context.
