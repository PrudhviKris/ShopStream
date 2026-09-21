# Demo walkthrough

A 6–8 minute script for a recording or a live run-through, with the
screenshots worth capturing. Two terminals are enough (see the README);
add ngrok only if you want to show Google/Facebook login or live Stripe
webhooks.

**Before you start**

```bash
# terminal 1
cd fastapi_backend && uvicorn app.main:app --reload --port 8000
# terminal 2
cd django_admin && python manage.py runserver 8001
```

Have two browsers (or a normal and a private window) side by side: one
signed in as a **customer**, one as an **admin**. The live updates are the
part people remember, and they only land if both are visible.

---

### 1. The storefront (1 min) — *screenshot: catalogue*

`http://127.0.0.1:8000`

- Filter by category and price, sort by popularity.
- Open a product, add it to the cart, show the cart totals with tax.

### 2. Checkout (1 min) — *screenshot: receipt page*

- Check out with **Cash on delivery** (no Stripe keys needed).
- The receipt page shows amount, transaction reference and order number.
- Point out the 🔔 bell: "Order confirmed" arrived instantly.

### 3. Real-time (1 min) — *screencast: both windows at once*

In the admin window: **Orders → Update status → Confirm payment**, then
**Ship**.

In the customer window, without touching anything:

- the order status changes,
- two notifications arrive,
- the **Inbox** badge increments.

### 4. The inbox (30 s) — *screenshot: an order email*

Customer window → **Inbox**. Open "Shipping update". Explain that every
email is kept in-app, so even a made-up address can read its mail, and that
real delivery is one `EMAIL_BACKEND=smtp` away.

### 5. Admin analytics in the storefront (1 min) — *screenshot: analytics*

Admin window → **Analytics**: revenue trend, orders by status, top products,
low stock. Switch the range to 7 days; toggle the trend to a table.

### 6. Django admin (1.5 min) — *screenshots: user list, product form, dashboard*

`http://127.0.0.1:8001/admin/`

- **Users** — change a role inline; deactivate an account, then show that the
  customer's next click returns "account has been deactivated".
  Re-activate them.
- **Products** — upload an image, watch it appear in the storefront.
- **Orders** — the payment inline and the ship/deliver/cancel actions. These go
  through the API, so watch the customer window: the notification, the email and
  the status all arrive live from here too.
- **Analytics** (`/analytics/`) — the Chart.js dashboard.

### 7. Reports (30 s) — *screenshot: a PDF open in a viewer*

`/reports/` → set a date range → download **Orders CSV** and **Sales PDF**.
Open both.

### 8. API docs (1 min) — *screenshot: Swagger*

`http://127.0.0.1:8000/docs`

- `POST /auth/login`, copy the token into **Authorize**.
- `GET /notifications`, then `POST /notifications/read`.
- Mention `docs/postman_collection.json` for Postman users.

### 9. Tests (30 s) — *screenshot: the passing summary*

```bash
cd fastapi_backend && python smoke_test.py      # 228 checks
cd django_admin && python manage.py test analytics   # 46 tests
```

Worth saying out loud: the suite creates its own users and deletes them
afterwards, and restores stock and the order/invoice counters, so it can be
run against the real database without leaving anything behind.

---

## Recording tips

- 1280×800 or larger; hide bookmarks and unrelated tabs.
- Zoom the browser to 110–125% — text stays readable when the video is
  scaled down.
- For the real-time section, put both windows side by side rather than
  switching tabs; the simultaneity is the point.
- Windows: `Win + Alt + R` records the focused window; OBS if you want both
  windows and a webcam.
