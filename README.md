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
cp .env.example .env        # set MYSQL_PASSWORD here (see Database below)
python seed.py              # admin/staff/customer demo users + 12 products
uvicorn app.main:app --reload --port 8000
```

**API documentation is Swagger UI**: http://localhost:8000/docs — click **Authorize**
and paste the `access_token` from `POST /auth/login` to call protected endpoints
(authorization persists across page reloads). ReDoc alternative: http://localhost:8000/redoc

### Database: MySQL 8.0+

The platform connects to the local MySQL Windows service (`MySQL80` / `MySQL90`) on
port 3306 via PyMySQL. Set your credentials in `fastapi_backend/.env`:

```
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=<your password>
MYSQL_DB=ecommerce
```

The `ecommerce` database is **created automatically on first run** (utf8mb4).
The Django service reads the same `.env`, so both services share one MySQL database.
If `MYSQL_PASSWORD` is not set, both services fall back to a local SQLite file so
the project still runs.

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
the FastAPI service in the same MySQL database (credentials come from
`fastapi_backend/.env`; SQLite fallback when no MySQL password is set).

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

http://localhost:3000 — login, browse, add to cart, checkout, live notification toasts.

## Features by milestone

**Auth & RBAC** — email/password register + login, pbkdf2 password hashing, JWT access
(30 min) + refresh (7 days) tokens, `GET /auth/me`. Every login (local **and** social)
issues a token pair; refresh tokens are persisted in the `refresh_tokens` table with
rotation (single-use) and revocation (`POST /auth/logout`). Social login endpoints for
global users: `POST /auth/social/google` (Google Identity Services ID token) and
`POST /auth/social/facebook` (FB JS SDK access token) — each verifies the provider
token, auto-provisions the user, and returns the platform's own JWT pair.
Roles (stored in the `roles` table, enforced via `require_roles`):

| Role | Can |
|---|---|
| **admin** | Everything: shop & buy, manage products, see every customer's orders / payments / invoices, update order statuses, view roles |
| **staff** | Shop & buy, manage products (create / rename / price / stock / photos / delete), update order statuses |
| **customer** | Shop only: browse, cart, checkout, pay, view their own orders & invoices |

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

**Invoices** — issued automatically when a payment succeeds (`invoices` table,
numbers like `INV-2026-00001`). Customers see their own (`GET /invoices`); admins see
everyone's (`GET /invoices/all`) plus all payments (`GET /payments/all`) and all orders
with customer identity (`GET /orders/all`).

**Admin panel (frontend)** — staff/admin get a ⚙️ Store management view: inline product
editing (rename, category, price, stock, photo URL), create and delete products, and
order-status management; admins additionally get Payments and Invoices tabs across all
customers. The Django admin at port 8001 mirrors this over the same MySQL database.

## Social login setup (Google / Facebook)

Provider keys cannot be generated locally — create them once in each console and paste
into `fastapi_backend/.env`:

1. **Google** — https://console.cloud.google.com/apis/credentials → Create credentials →
   OAuth client ID → Web application → add `http://localhost:3000` to authorized
   JavaScript origins → copy the client id into `GOOGLE_CLIENT_ID`.
2. **Facebook** — https://developers.facebook.com/apps → Create app → add the
   "Facebook Login" product → Settings > Basic → copy `FACEBOOK_APP_ID` and
   `FACEBOOK_APP_SECRET`.
3. Frontend obtains the provider token (Google Identity Services / FB JS SDK) and POSTs
   it to `/auth/social/google` or `/auth/social/facebook`; the backend verifies it and
   returns the same JWT pair local users get.

## Stripe setup (live mode)

1. Put `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` in `fastapi_backend/.env`.
2. Forward webhooks locally: `stripe listen --forward-to localhost:8000/payments/webhook`
3. Checkout responses then contain a real `checkout_url` (hosted page) or `client_secret` (Elements).

## Public access with ngrok

The Vite dev server proxies `/api/*` (HTTP **and** WebSocket) to the FastAPI backend,
so one tunnel exposes the entire app:

```bash
ngrok http 3000
```

The printed `https://….ngrok-free.dev` URL serves the storefront, the API, and live
notifications (wss) to anyone. Set it as `PUBLIC_URL` in `fastapi_backend/.env` —
the OAuth redirect URLs are built from it:

| Provider | Where to register | Redirect URL |
|---|---|---|
| Google | Google Cloud Console → Credentials → your OAuth client → *Authorized redirect URIs* | `{PUBLIC_URL}/api/auth/google/callback` |
| Facebook | developers.facebook.com → your app → Facebook Login → Settings → *Valid OAuth Redirect URIs* | `{PUBLIC_URL}/api/auth/facebook/callback` |

Register the `http://localhost:3000/...` variants too so login also works without the
tunnel (then set `PUBLIC_URL=http://localhost:3000`). The login flow: the Sign-in page's
**Google / Facebook** buttons hit `GET /api/auth/<provider>/login`, which redirects to the
provider's consent page; the provider redirects back to the callback URL above; the
backend exchanges the code, creates the user if new, and hands the SPA its JWT pair via
the URL fragment. A CSRF `state` token (10 min) protects the round-trip.

Note: a free-plan ngrok URL changes on every restart (visitors also see a one-time
interstitial page); reserve a static domain in the ngrok dashboard to keep OAuth
origins stable.

## Testing

- **Swagger UI** (http://localhost:8000/docs) is the interactive way to exercise every
  endpoint — login, copy the token into **Authorize**, and try requests in the browser.
- `fastapi_backend/smoke_test.py` — 39 end-to-end checks (auth, RBAC, filters, cart math,
  checkout, payment, WebSocket push) against the configured database: `python smoke_test.py`
