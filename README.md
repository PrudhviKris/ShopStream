# Smart E-Commerce Platform

Full-stack e-commerce system with three services:

| Service | Stack | Port | Responsibility |
|---|---|---|---|
| `fastapi_backend/` | FastAPI + SQLAlchemy | 8000 | User APIs: auth, products, cart, checkout, payments, notifications |
| `django_admin/` | Django | 8001 | Admin panel + analytics over the same database |
| `frontend/` | React (Vite) | 3000 | Customer storefront |

**New here?** [docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md) walks through everything
that was built, phase by phase, with the tools used for each part.

## Quick start

### 1. FastAPI backend (user APIs)

```bash
cd fastapi_backend
pip install -r requirements.txt
cp .env.example .env        # set MYSQL_PASSWORD here (see Database below)
python seed.py              # role reference table + 12 sample products (no user accounts)
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

### User accounts & roles

There are **no built-in accounts**. Every user — email/password registration or
Google/Facebook login — is always created with role **customer**; that is the
only role the application ever assigns itself. To make someone staff or admin,
promote them by hand directly in MySQL:

```sql
UPDATE users SET role = 'admin'    WHERE email = 'someone@example.com';
UPDATE users SET role = 'staff'    WHERE email = 'someone@example.com';
UPDATE users SET role = 'customer' WHERE email = 'someone@example.com';  -- demote
```

This takes effect on the user's very next request — no re-login needed, since
every request re-reads the role from the database rather than trusting the JWT.
The `role` column is a native MySQL `ENUM('admin','staff','customer')`, so the
database itself refuses any value outside those three; there is no way — through
the API, the admin panel, or a raw SQL edit — to introduce a fourth role.

### 2. Django admin panel

```bash
cd django_admin
pip install -r requirements.txt
python manage.py migrate            # creates Django's own tables only
python manage.py createsuperuser
python manage.py runserver 8001
```

- Admin panel: http://localhost:8001/admin/
  - **Users** — view and edit accounts, assign roles (admin/staff/customer) inline, and
    activate/deactivate. Deactivating blocks login *and* invalidates tokens the user already
    holds; the last active admin can't be deactivated, and users are never deleted.
  - **Products** — add, edit and delete, update stock, and **upload images** (stored in
    `fastapi_backend/media/`, served by FastAPI at `/media/...`). A product that appears on
    an order can't be deleted; set its stock to 0 to retire it.
  - **Orders** — every order with its payment inline (amount, method, transaction id,
    status) and ship/deliver/cancel actions that enforce the allowed transitions.
  - **Notifications** and the **email log**, with a sandboxed HTML preview.

  Order actions here call the API (`SERVICE_API_TOKEN`), so shipping from the admin
  sends the customer's email and updates their screen live, exactly like shipping from
  the storefront. If the API is unreachable the status still changes and the in-app
  notification is written, and the admin says so.
- Analytics dashboard: http://localhost:8001/analytics/ — **Chart.js** charts for total
  sales, the revenue trend, orders by status, sales by category, top-selling products,
  revenue by payment method and email delivery, plus low-stock alerts and recent orders.
  `?days=7|30|90`; the same numbers as JSON at http://localhost:8001/analytics/data/.
  Chart.js is vendored at `analytics/static/analytics/chart.umd.js` (no CDN at runtime); to
  update it: `npm i chart.js && cp node_modules/chart.js/dist/chart.umd.js <that path>`.
- Export reports: http://localhost:8001/reports/ — orders, sales and users as **CSV or
  PDF**, scoped by a date range. CSVs carry a UTF-8 BOM for Excel; PDFs are written by a
  small built-in writer (no reportlab dependency) and spell amounts `INR 1,234.00`, since
  the base PDF fonts have no ₹ glyph.

The store models are `managed = False` — Django reads/writes the tables owned by
the FastAPI service in the same MySQL database (credentials come from
`fastapi_backend/.env`; SQLite fallback when no MySQL password is set).

### 3. Frontend

For live-reload development:

```bash
cd frontend
npm install
npm run dev
```

http://localhost:3000 — login, browse, add to cart, checkout, live notification toasts.
Requests to `/api/*` (including the notifications WebSocket) are proxied to the
FastAPI backend on port 8000.

For a single-URL setup matching the backend's own port — the same layout as
`/docs` for Swagger — build the frontend and let FastAPI serve it:

```bash
cd frontend
npm run build
```

Then **http://127.0.0.1:8000/** serves the storefront and **http://127.0.0.1:8000/docs**
stays Swagger UI, from the one running `uvicorn` process. Rerun `npm run build`
after any frontend change to refresh it.

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

**Notifications** — each order event stores a notification (`id`, `user`, `type`, `message`,
`read_status`, `timestamp`) with one of these types: `order_placed`, `order_confirmed`
(cash on delivery), `payment_successful`, `payment_failed`, `order_shipped`,
`order_delivered`, `order_cancelled`. All of it goes through
`app/services/order_events.py`, so the notification, the email and the live update always
go out together.

| Endpoint | |
|---|---|
| `GET /notifications` | newest first; `?unread_only=true`, `?type=order_shipped`, `?limit=` |
| `POST /notifications/read` | `{"notification_ids": [1, 2]}` for those, or `{"all": true}` |
| `GET /notifications/unread-count` | badge count |

**Email notifications** — order confirmation, payment success/failure and shipping updates
(shipped / delivered / cancelled), as text + HTML with INR amounts. Every email is logged in
`development_emails` with a delivery `status`. `EMAIL_BACKEND` in `.env` decides delivery:

- `database` (default): stored only, readable in the storefront's **Emails** page and at
  `GET /dev/emails`. No mail server needed.
- `smtp`: sent through `SMTP_*`, on a background worker, so a slow mail server never
  blocks checkout. Failures are recorded (`status=failed`, `error`) and admins can retry
  them (`POST /admin/emails/{id}/retry`). SendGrid and AWS SES are SMTP relays, so they
  plug in here too; see the comments in `app/config.py` for their host/port/credentials.
  Placeholder addresses (Facebook accounts without an email) are skipped, and so are
  local email/password accounts (their address is never verified) unless
  `SMTP_SEND_TO_LOCAL_ACCOUNTS=true`.

**Inbox** — every user reads their emails in the storefront's **Inbox** page, even when
  the address is made up (e.g. a local account registered as `bruce@gmail.com`): a copy of
  each email is always kept. Unread emails are marked and counted in the sidebar badge,
  open one to mark it read, or "Mark all read". API: `GET /dev/emails` (`?unread_only=true`),
  `GET /dev/emails/summary`, `POST /dev/emails/read` (`{"email_ids": [..]}` or
  `{"all": true}`); new mail arrives live as the `email` WebSocket event.

**Real-time (WebSockets)** — connect to
`ws://localhost:8000/ws/notifications?token=<access_token>`. Every message is
`{"event", "data", "sent_at"}`:

| event | when | who receives it |
|---|---|---|
| `order_status_updated` | order placed, paid, payment failed, shipped, delivered, cancelled | the order's customer + every connected staff/admin |
| `cart_updated` | item added / updated / removed, cart cleared at checkout (full cart in `data`) | that user (all their tabs) |
| `notification` | a notification was stored | its user |
| `notifications_read` | notifications marked read | that user (keeps badges in sync) |
| `order_deleted` | an admin deleted an order | the customer + staff/admin |
| `connected` / `pong` | on connect / reply to a `ping` text frame | that socket |

The storefront keeps one socket per session, reconnects with backoff, and refreshes the
order lists, admin tables and analytics live.

**Order lifecycle** — pending → paid → shipped → delivered (or cancelled), invalid
transitions rejected; staff/admin update statuses, customers get notified in real time.

**Returns & refunds** — a customer can request a return on a **delivered** order within
`RETURN_WINDOW_DAYS` (7 by default, counted from delivery). `POST /orders/{id}/return`
takes a `reason` and optional `comment`, creates a `ReturnRequest` (pending) and moves the
order to `return_requested`. Staff work the queue with `GET /returns/all` and
`POST /returns/{id}/approve|reject`:

- **Approve** refunds the payment (a real Stripe refund for live card payments, a local
  reference for cash/mock), puts the items back in stock, marks the order `returned` and
  the payment `refunded`, and emails the customer.
- **Reject** puts the order back to `delivered` with the note the operator wrote.

The storefront shows a **Request return** button with the deadline on eligible orders and
the live state of any request; staff get a **Returns** tab, and the Django admin has a
read-only screen whose approve/decline actions call the same API.

**Reviews & ratings** — a customer can rate and review a product once they've actually
received it: `POST /reviews` requires a **delivered** order containing that product, and
only one review per product per customer. A new review starts `pending`; staff moderate
with `GET /reviews/all` (`?status=pending` is the queue) and
`POST /reviews/{id}/approve|reject`. Only `approved` reviews count towards a product's
average rating or show up on its page.

`GET /products/{id}/reviews` returns the approved reviews plus the average rating and
total count (computed over every approved review, not just the page shown), with
`?sort=recent` (default) or `?sort=top`. `GET /products/{id}/reviews/mine` tells the
storefront whether the signed-in customer may leave a review right now, and their existing
one if they already have. The product page shows a star rating badge on every card, and
the product detail view shows the full breakdown: average + count, a write-a-review form
gated by eligibility, and the review list with a recent/top toggle. Staff/admin get a
**Reviews** tab on the Products page — a moderation queue (filterable by status) with
approve/reject actions, the reviewer's identity, and the product it's for.

**Display numbers** — every department has a friendly number that counts 1, 2, 3 with
no gaps: Customer #, Order #, Payment #, Invoice # (`INV-2026-00001`), Return #,
Product # and Review #. They
come from the `sequences` table, which only advances when a row is actually committed —
unlike the raw `id` (MySQL AUTO_INCREMENT), which leaves holes wherever a row was deleted
or a transaction rolled back. Both are shown in the UI: the friendly number leads, the raw
id sits beneath it for support and SQL. Primary keys are never renumbered — JWTs embed
`user.id`, every foreign key points at these values, and invoices already quote them.

**Invoices** — issued automatically when a payment succeeds (`invoices` table,
numbers like `INV-2026-00001`). Customers see their own (`GET /invoices`); admins see
everyone's (`GET /invoices/all`) plus all payments (`GET /payments/all`) and all orders
with customer identity (`GET /orders/all`).

**Admin panel (frontend)** — staff/admin get a ⚙️ Store management view: inline product
editing (rename, category, price, stock, photo URL), create and delete products, and
order-status management; admins additionally get Payments and Invoices tabs across all
customers, plus:

- **Analytics**: revenue for the last 7/30/90 days with a daily trend (chart or table),
  pending / awaiting-shipment / stock alerts, orders by status, sales by category and payment
  method, top products, restock list, recent orders, accounts by role, email delivery.
  Updates live as orders change. API: `GET /admin/analytics?days=30`.
- **Users**: every account with order count and lifetime spend, with search and a role
  filter (`GET /admin/users`). Read-only on purpose: roles are changed in MySQL.
- **Emails**: everyone sees their own inbox; admins also get the full log with a delivery
  status filter and retry (`GET /admin/emails`).

The Django admin at port 8001 covers the same data over the same MySQL database.

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

## Deployment, migrations and API collection

- **Docker:** `cp .env.docker.example .env && docker compose up --build` brings up
  MySQL, the API/storefront (8000) and the Django admin (8001). See
  [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the production checklist, TLS settings
  and scaling notes.
- **Migrations:** the store schema is managed by Alembic in `fastapi_backend/`:
  `alembic upgrade head` applies it, `alembic revision --autogenerate -m "..."` writes a
  new one, `alembic check` reports drift. In containers `AUTO_CREATE_SCHEMA=false`, so
  migrations are the only thing that changes the schema. Django's `manage.py migrate`
  still creates its own auth/session tables.
- **Postman:** [docs/postman_collection.json](docs/postman_collection.json) — 64 requests
  in 11 folders, generated from the OpenAPI schema by
  `python tools/generate_postman.py`. Import it, set `base_url`, run
  **Authentication → Login** and the tokens are stored for every other request.
- **Demo script:** [docs/DEMO.md](docs/DEMO.md) — a 6–8 minute walkthrough with the
  screenshots worth capturing.
- **Hardening:** with `APP_ENV=production` the API refuses to boot on development
  secrets, wildcard CORS, SQLite or auto-created tables; responses carry
  `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and (behind TLS)
  HSTS; `/auth/login`, `/auth/register` and `/auth/refresh` are rate-limited per IP.

## Testing

- **Swagger UI** (http://localhost:8000/docs) is the interactive way to exercise every
  endpoint — login, copy the token into **Authorize**, and try requests in the browser.
- `fastapi_backend/smoke_test.py` — 300 end-to-end checks (auth, role promotion via direct
  MySQL update, RBAC, filters, cart math, Stripe + cash checkout, admin deletes, notification
  types and `POST /notifications/read`, WebSocket `order_status_updated` / `cart_updated`
  events, emails on both backends including SMTP failure and retry, returns and refunds,
  reviews and ratings, admin analytics/users/email APIs, the user inbox, account
  deactivation, security headers, the auth rate limit and the production config guard)
  against the configured database:
  `python smoke_test.py`. It restores stock, popularity and the display-number
  counters afterwards, so it leaves the database exactly as it found it.

- `django_admin`: `python manage.py test analytics` — 58 tests covering the admin
  screens (users, products with image upload, orders), the Chart.js dashboard, the
  CSV/PDF exports and the PDF writer itself. It registers its own
  throwaway users and deletes them again when it finishes, so it never leaves demo data
  behind.
