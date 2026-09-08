# Smart E-Commerce Platform

Full-stack e-commerce system with three services:

| Service | Stack | Port | Responsibility |
|---|---|---|---|
| `fastapi_backend/` | FastAPI + SQLAlchemy | 8000 | User APIs: auth, products, cart, checkout, payments, notifications |
| `django_admin/` | Django | 8001 | Admin panel + analytics over the same database |
| `frontend/` | React (Vite) | 3000 | Customer storefront |

## Quick start

### 1. FastAPI backend (user APIs)

```bash
cd fastapi_backend
pip install -r requirements.txt
cp .env.example .env        # optional — runs with safe defaults without it
python seed.py              # admin/staff/customer demo users + 12 products
uvicorn app.main:app --reload --port 8000
```

Interactive API docs: http://localhost:8000/docs

Seeded logins:

| Role | Email | Password |
|---|---|---|
| admin | admin@example.com | AdminPass123! |
| staff | staff@example.com | StaffPass123! |
| customer | customer@example.com | CustomerPass123! |

### 2. Django admin panel

```bash
cd django_admin
pip install -r requirements.txt
python manage.py migrate            # creates Django's own tables only
python manage.py createsuperuser
python manage.py runserver 8001
```

- Admin panel: http://localhost:8001/admin/ (manage users, products, orders, payments)
- Analytics JSON: http://localhost:8001/analytics/ (revenue, orders by status, top products)

The store models are `managed = False` — Django reads/writes the tables owned by
the FastAPI service (shared SQLite by default; set `STORE_DB_ENGINE=postgres` + `STORE_DB_*` for Postgres).

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

http://localhost:3000 — login, browse, add to cart, checkout, live notification toasts.

## Features by milestone

**Auth & RBAC** — email/password register + login, pbkdf2 password hashing, JWT access
(30 min) + refresh (7 days) tokens, `GET /auth/me`, Auth0 social login
(`POST /auth/social/auth0` verifies the Google/Facebook ID token against the tenant JWKS
and auto-provisions the user), roles admin/staff/customer enforced via `require_roles` dependency.

**Catalog & cart** — product list with category / price-range / stock / search filters and
popularity / price / newest sorting, pagination, per-user cart with stock validation and
automatic item total / cart total / tax / grand total calculation.

**Checkout & payments** — `POST /checkout` validates the cart, snapshots line items into an
order, reserves stock, clears the cart, and creates a Stripe Checkout Session
(`?flow=intent` for a PaymentIntent instead). Payment records track transaction id + status.
`POST /payments/webhook` handles Stripe events (`checkout.session.completed`,
`payment_intent.succeeded/payment_failed`). Without a `STRIPE_SECRET_KEY` the service runs
in **mock mode**: checkout works end-to-end and `POST /payments/mock/confirm/{order_id}`
simulates the webhook.

**Notifications & real-time** — every order/payment/status event persists a notification and
pushes it live over `ws://localhost:8000/ws/notifications?token=<access_token>`.
REST: `GET /notifications`, `PUT /notifications/{id}/read`, `PUT /notifications/read-all`.

**Order lifecycle** — pending → paid → shipped → delivered (or cancelled), invalid
transitions rejected; staff/admin update statuses, customers get notified in real time.

## Stripe setup (live mode)

1. Put `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` in `fastapi_backend/.env`.
2. Forward webhooks locally: `stripe listen --forward-to localhost:8000/payments/webhook`
3. Checkout responses then contain a real `checkout_url` (hosted page) or `client_secret` (Elements).

## Auth0 setup (social login)

1. Create an Auth0 application (SPA), enable the **Google** and **Facebook** connections.
2. Set `AUTH0_DOMAIN` and `AUTH0_CLIENT_ID` in `fastapi_backend/.env`.
3. Frontend obtains an ID token via Auth0 Universal Login and POSTs it to `/auth/social/auth0`;
   the backend verifies it (RS256 / JWKS) and returns the platform's own JWT pair.

## Testing

- `fastapi_backend/smoke_test.py` — 40+ end-to-end checks (auth, RBAC, filters, cart math,
  checkout, payment, WebSocket push): `python smoke_test.py`
- `postman/Smart-ECommerce.postman_collection.json` — import into Postman; the Login request
  auto-stores tokens into collection variables.
