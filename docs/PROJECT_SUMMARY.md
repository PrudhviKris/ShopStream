# Smart E-Commerce Platform — what was built

A full-stack online store with a shop front, a JSON API, a staff admin panel,
payments, real-time updates, email, analytics and reports.

Built in seven phases. This document walks through each phase:
what was asked for, what was built, and which tools were used.

---

## The stack at a glance

| Layer | Technology | What it does here |
|---|---|---|
| **API + storefront server** | FastAPI (Python) | Every business rule: auth, catalogue, cart, checkout, orders, notifications, email. Also serves the React app. |
| **Shop front** | React + Vite | What customers and staff use to browse, buy and manage orders. |
| **Admin panel** | Django admin | Staff tools: users, products, orders, notifications, email log. |
| **Analytics & reports** | Django + Chart.js | Dashboard charts and CSV/PDF exports. |
| **Database** | MySQL 8/9 | One database shared by both services. |
| **ORM** | SQLAlchemy (API), Django ORM (admin) | The admin reads the API's tables without owning them. |
| **Migrations** | Alembic | Versioned schema changes. |
| **Payments** | Stripe | Hosted checkout + webhooks, with a mock mode for development. |
| **Auth** | JWT (PyJWT) + Google/Facebook OAuth | Tokens for local and social logins. |
| **Real-time** | WebSockets | Live order, cart and notification updates. |
| **Email** | SMTP (SendGrid / AWS SES compatible) | Order emails, plus an in-app inbox. |
| **Deployment** | Docker + docker compose, gunicorn | One command brings up the whole stack. |
| **Public access** | ngrok | Public HTTPS for OAuth callbacks and Stripe webhooks. |

---

## Phase 1 — Foundation, accounts and roles

**Goal:** a working project skeleton where people can sign up and are allowed
to do different things.

**What was built**

- Three services in one repo: FastAPI, Django admin, React frontend.
- Register and login with email + password; passwords hashed, never stored.
- **JWT tokens** — a short-lived access token plus a refresh token that is
  single-use and can be revoked (logout really logs you out).
- **Google and Facebook login**, done directly against the providers (no
  Auth0), returning the platform's own tokens.
- **Three roles, enforced on every request:**
  - **Admin** — everything, including shopping
  - **Staff** — manage products and orders, and shop
  - **Customer** — shop only
- Roles are changed in MySQL or the Django admin and take effect immediately,
  without the user logging in again.
- No built-in demo accounts: every new sign-up is a customer.

**Tech:** FastAPI, SQLAlchemy, PyJWT, passlib, Google/Facebook OAuth, MySQL.

---

## Phase 2 — Catalogue, cart and the storefront

**Goal:** a shop people actually want to use.

**What was built**

- Product catalogue with filters (category, price range, in-stock, search),
  sorting and pagination.
- Per-user cart with stock checks and automatic totals, tax and grand total.
- A designed React storefront: split-screen sign-in, role-aware navigation,
  dashboard, product grid, cart drawer.
- 68 products priced in **Indian Rupees**, including the full iPhone lineup
  (11 through 15, every model with one variant each), Samsung phones, 13
  laptops, headsets, smartwatches, power banks and large appliances (AC,
  refrigerator, washing machine, microwave, TV, air and water purifiers).
- The API serves the built React app, so `http://127.0.0.1:8000` is the shop
  and `/docs` is the API documentation.

**Tech:** React 18, Vite, plain CSS design system, FastAPI static serving,
`Intl.NumberFormat` for ₹ formatting.

---

## Phase 3 — Checkout, payments and invoices

**Goal:** take money and keep proper records.

**What was built**

- Checkout validates the cart, snapshots prices into an order, reserves stock
  and clears the cart.
- **Stripe Checkout** for cards, plus **cash on delivery**. Without Stripe keys
  the app runs in mock mode, so the whole flow still works.
- **Stripe webhooks** mark orders paid automatically and issue the invoice.
- Staff/admin can confirm a payment by hand when a webhook never arrives.
- A **receipt page** after payment showing card holder, amount, transaction ID
  and time — instead of raw JSON.
- **Invoices** issued automatically (`INV-2026-00001`).
- **Friendly numbers**: Order #7, Customer #3, with no gaps, kept separate from
  database IDs so nothing ever has to be renumbered.
- Order lifecycle with enforced transitions:
  `pending → paid → shipped → delivered`, or `cancelled`.

**Tech:** Stripe SDK + webhook signature verification, SQLAlchemy transactions,
a sequence table for gapless numbering.

---

## Phase 4 — Notifications, real-time and email

**Goal:** tell customers what's happening, as it happens.

**What was built**

- **Notifications** for every order event: placed, confirmed, payment
  successful/failed, shipped, delivered, cancelled.
- **Real-time updates over WebSockets** — the customer's screen updates with no
  refresh, and staff order lists update live too. Events: order status, cart
  changes, new notifications, new mail.
- **Emails** for order confirmation, payment result and shipping updates, in
  text and HTML with ₹ amounts.
- **Two email modes:** keep them in the app (no mail server needed), or send
  them for real over SMTP/SendGrid/SES in a background worker so checkout is
  never slowed down.
- **An in-app inbox** so every user can read their mail — including local
  accounts with made-up addresses — with unread counts and a sidebar badge.
- **A privacy rule:** real email is never sent to unverified local addresses
  (a made-up `bruce@gmail.com` may belong to a stranger).
- One place in the code sends the notification, the email and the live update
  together, so none can be forgotten.

**Tech:** WebSockets (FastAPI/Starlette), `asyncio`, `smtplib` with a background
thread pool, React hooks with automatic reconnect.

---

## Phase 5 — Admin panel, analytics and reports

**Goal:** give staff a place to run the store, and management a view of it.

**What was built**

**User management** — view and edit users, assign roles inline,
activate/deactivate. Deactivating blocks login *and* invalidates tokens the
user already holds. The last active admin can't be locked out, and users are
never deleted (that would orphan their orders).

**Product management** — add, edit, delete, update stock, and **upload images**
into a folder the shop serves. A product that appears on an order can't be
deleted; the admin explains to set its stock to 0 instead.

**Order management** — every order with payment details inline (amount, method,
transaction ID, status) and ship/deliver/cancel actions that follow the allowed
transitions. These call the API, so an order shipped from the admin sends the
customer's email and updates their screen live, exactly like the storefront.

**Analytics dashboard (Chart.js)** — total sales, revenue trend, orders by
status, sales by category, top-selling products, email delivery, plus low-stock
alerts and recent orders. Ranges of 7 / 30 / 90 days. Chart.js is stored in the
repo, so no internet is needed at runtime. The storefront has its own live
version of this for admins.

**Report exports** — orders, sales and users, each as **CSV or PDF**, over a
date range. Each report is defined once and rendered into both formats, so the
two can never disagree.

**Tech:** Django admin (actions, inlines, custom forms), Chart.js 4.5,
Django ORM aggregation, Python `csv`, and a small **custom PDF writer** built
for the project so no extra dependency is needed.

---

## Phase 6 — Returns and refunds

**Goal:** let customers send things back, and staff handle the money.

**What was built**

- A **Request return** button on delivered orders in the storefront, shown only inside
  the return window (7 days from delivery, configurable), with the deadline
  spelled out. The customer picks a reason and can add a note.
- A **ReturnRequest** record — order, customer, reason, comment, status,
  timestamps — plus the refund amount, reference and who decided, so the money
  has an audit trail.
- **Order statuses** `return_requested` and `returned`, reachable only through
  the return flow (never by a manual status flip), and a `delivered_at`
  timestamp the window counts from.
- **Staff queue** in the storefront and a read-only screen in the Django admin.
  Approving **refunds the payment** (a real Stripe refund for live card
  payments), **restocks the items**, and emails the customer; rejecting returns
  the order to delivered with the operator's note.
- Notifications, emails and live updates for all three moments — request,
  approval, rejection — reusing the same event pipeline as the rest of the shop.

**Tech:** FastAPI, SQLAlchemy, Stripe Refunds API, Alembic migration 0003,
React modal + queue, Django admin actions through the service token.

## Phase 7 — Production readiness

**Goal:** something that can actually be deployed, not just demoed.

**What was built**

- **Database migrations (Alembic)** — versioned schema, tested upgrade *and*
  downgrade. Autogenerate is restricted to the app's own tables, so it can
  never propose dropping Django's.
- **Docker deployment** — `docker compose up --build` starts MySQL, the API
  (which migrates itself first) and the admin. Non-root containers,
  healthchecks, a shared volume for images.
- **Security hardening**
  - The API refuses to start in production with development secrets, wildcard
    CORS, SQLite, or auto-created tables.
  - Security headers on every response; HSTS behind HTTPS.
  - Rate limiting on login, register and refresh.
  - Django: enforced secret key and allowed hosts, secure cookies, CSRF
    trusted origins, optional HTTPS redirect.
- **Postman collection** — 51 requests, generated from the live API schema;
  logging in stores the token for every other request.
- **Documentation** — deployment guide with a production checklist, and a timed
  demo script.

**Tech:** Alembic, Docker, docker compose, gunicorn + uvicorn workers,
whitenoise, custom FastAPI middleware.

---

## What each role can do

| | Customer | Staff | Admin |
|---|---|---|---|
| Browse, cart, checkout, pay | ✅ | ✅ | ✅ |
| Own orders, invoices, inbox | ✅ | ✅ | ✅ |
| Manage products | — | ✅ | ✅ |
| See all orders, update status | — | ✅ | ✅ |
| Confirm payments | — | ✅ | ✅ |
| All payments and invoices | — | — | ✅ |
| Analytics, user directory, email log | — | — | ✅ |
| Django admin panel | separate login | separate login | separate login |

> The Django admin uses its own accounts (`createsuperuser`), separate from
> shop accounts.

---

## Testing

| Suite | Size | Covers |
|---|---|---|
| `fastapi_backend/smoke_test.py` | **235 checks** | Auth, roles, deactivation, filters, cart maths, Stripe and cash checkout, order lifecycle, invoices, notifications, WebSocket events, email in both modes, inbox, admin APIs, rate limiting, security headers |
| `django_admin` tests | **50 tests** | Admin screens, user/product/order management, image upload, dashboard, CSV/PDF exports, the PDF writer, the admin→API client |

The API suite runs against the real database and puts everything back
afterwards — the users it creates, the stock it buys and the order numbers it
uses.

---

## Notable bugs found and fixed

1. **Stripe webhooks failed in production** — the SDK returns typed objects, not
   dictionaries, so every real payment silently stayed unpaid.
2. **Google login failed** — the PC's clock was ~8 seconds fast and Google's
   tokens were rejected as "not valid yet".
3. **Logins broke store-wide** — an uncommitted SQL transaction held a row lock
   for 31 minutes.
4. **Adding a product in the admin was impossible** — a read-only date field was
   saved as empty.
5. **Deleting an ordered product crashed** — now refused with an explanation.
6. **Four missing database indexes** — inbox and email-log filters were scanning
   whole tables.
7. **The test suite was draining real stock** — one product had reached zero.
   Fixed, and the catalogue repaired.
8. **Admin order changes sent no email** — now routed through the API.

---

## Running it

```bash
# API + storefront            → http://127.0.0.1:8000 (docs at /docs)
cd fastapi_backend && alembic upgrade head && uvicorn app.main:app --reload --port 8000

# Django admin + analytics    → http://127.0.0.1:8001/admin/
cd django_admin && python manage.py runserver 8001
```

Everything else (MySQL, the frontend build) needs no extra terminal.
With Docker: `cp .env.docker.example .env && docker compose up --build`.

Tests:

```bash
cd fastapi_backend && python smoke_test.py
cd django_admin && python manage.py test analytics
```

---

## Still open

- **Docker images have not been built yet** — the configuration is written and
  valid, but the first `docker compose up --build` may need small fixes.
- **Demo screenshots and video** — the script is in [DEMO.md](DEMO.md).
- **Scaling past one API worker** needs Redis: WebSocket connections and the
  rate limiter currently live in a single process.
- `schema_upgrade.py` is now redundant with Alembic and can be removed once
  every environment is migrated.

---

## Where things live

```
fastapi_backend/     API, storefront server, business rules
  app/routers/       endpoints (auth, products, cart, checkout, orders, payments, admin)
  app/services/      order events, email, notifications, Stripe
  alembic/           database migrations
  smoke_test.py      the 235-check suite
django_admin/        admin panel, analytics, reports
  analytics/         models (read-only views of store tables), admin screens, charts, exports
frontend/            React storefront
docs/                deployment guide, demo script, Postman collection, this file
```
