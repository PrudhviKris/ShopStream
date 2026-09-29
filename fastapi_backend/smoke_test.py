"""End-to-end smoke test using FastAPI's TestClient (no server needed).

Covers: register/login/refresh/me, RBAC, product filters, cart CRUD + totals,
checkout -> order -> payment (Stripe + cash), admin deletes, order status
flow, invoices, notifications (DB + WebSocket real-time push).

No seeded demo accounts are used or required. This suite registers its own
throwaway users (always created as "customer" — the platform's only default),
then promotes two of them to staff/admin the same way a real operator would:
an UPDATE directly against the `role` column in MySQL. That also proves role
changes take effect immediately, without reissuing a token. Every user this
run creates is deleted again at the end, pass or fail, so repeated runs never
leave demo data behind in the real database.
"""
import os
import uuid
from datetime import datetime, timedelta

# Force mock payments for the test run even when real Stripe keys are in .env —
# the suite must not create real Stripe sessions. Set BEFORE importing the app.
os.environ["STRIPE_SECRET_KEY"] = ""
os.environ["STRIPE_WEBHOOK_SECRET"] = ""
# Keep email in the database inbox: the suite must never send real mail either.
os.environ["EMAIL_BACKEND"] = "database"
os.environ["EMAIL_ENABLED"] = "true"
# The suite registers and logs in far more often than a person would; the
# limiter is exercised directly further down instead.
os.environ["AUTH_RATE_LIMIT"] = "1000"

from fastapi.testclient import TestClient
from sqlalchemy import text

import seed
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.security import create_access_token

seed.seed()
client = TestClient(app)
client.__enter__()  # run app lifespan so real-time WebSocket pushes are wired up
passed = 0
created_user_ids = []  # every user this run creates, for teardown


def check(name, condition, detail=""):
    global passed
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not condition else ""))
    assert condition, f"{name}: {detail}"
    passed += 1


def register(email, name, password="SmokePass123!"):
    r = client.post("/auth/register", json={"name": name, "email": email, "password": password})
    check(f"register {name}", r.status_code == 201, r.text)
    tokens = r.json()
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/auth/me", headers=auth).json()
    created_user_ids.append(me["id"])
    check(f"{name} defaults to role=customer on registration", me["role"] == "customer", str(me))
    check(f"{name} was assigned a gapless customer_number",
          isinstance(me.get("customer_number"), int) and me["customer_number"] > 0, str(me))
    return tokens, auth, me["id"]


def receive_until(ws, predicate, limit=8):
    """Read WebSocket messages until one matches; returns (match, everything seen).
    Several events can arrive for one action, in no guaranteed order."""
    seen = []
    for _ in range(limit):
        msg = ws.receive_json()
        seen.append(msg)
        if predicate(msg):
            return msg, seen
    return None, seen


def in_stock_product(quantity=1):
    """An id of a product with at least `quantity` in stock.

    The suite must not assume a particular product still has stock — the real
    catalogue moves as people buy things.
    """
    items = client.get("/products", params={"in_stock": True, "page_size": 50}).json()["items"]
    for item in items:
        if item["stock"] >= quantity:
            return item["id"]
    raise RuntimeError(f"No catalogue product has {quantity} unit(s) in stock — cannot run the suite.")


def set_active_in_mysql(user_id: int, active: bool) -> None:
    """What the Django admin's activate/deactivate action does:
    UPDATE users SET is_active = 0/1 WHERE id = <user_id>;
    """
    with SessionLocal() as db:
        db.execute(text("UPDATE users SET is_active = :a WHERE id = :id"),
                   {"a": 1 if active else 0, "id": user_id})
        db.commit()


def set_role_in_mysql(user_id: int, role: str) -> None:
    """Exactly what a human operator runs by hand to promote/demote a user:
    UPDATE users SET role = '<role>' WHERE id = <user_id>;
    """
    with SessionLocal() as db:
        db.execute(text("UPDATE users SET role = :role WHERE id = :id"), {"role": role, "id": user_id})
        db.commit()


def snapshot_sequences():
    """Capture the gapless-sequence counters before this run touches them, so
    cleanup can put them back — otherwise every test run would permanently
    burn real order/invoice/customer numbers, silently drifting the sequence
    real customers see even though no real activity happened."""
    with SessionLocal() as db:
        return dict(db.execute(text("SELECT name, value FROM sequences")).fetchall())


def restore_sequences(before: dict):
    with SessionLocal() as db:
        for name, value in before.items():
            db.execute(text("UPDATE sequences SET value = :v WHERE name = :n"), {"v": value, "n": name})
        # Any sequence that didn't exist yet before this run (fresh database) -> remove it.
        after = dict(db.execute(text("SELECT name, value FROM sequences")).fetchall())
        for name in set(after) - set(before):
            db.execute(text("DELETE FROM sequences WHERE name = :n"), {"n": name})
        db.commit()


def snapshot_products():
    """Stock and popularity before this run.

    Checking out decrements stock and bumps popularity, and deleting the test
    order afterwards does NOT put them back — so without this every run
    quietly drained the real catalogue (it took Mechanical Keyboard from 60
    to 0 before this was caught).
    """
    with SessionLocal() as db:
        return {
            row[0]: (row[1], row[2])
            for row in db.execute(text("SELECT id, stock, popularity FROM products"))
        }


def restore_products(before: dict):
    with SessionLocal() as db:
        for product_id, (stock, popularity) in before.items():
            db.execute(
                text("UPDATE products SET stock = :s, popularity = :p WHERE id = :id"),
                {"s": stock, "p": popularity, "id": product_id},
            )
        db.commit()


def cleanup(user_ids):
    """Delete everything this run created, in FK-safe order — leaves MySQL
    exactly as it was before the test ran."""
    if not user_ids:
        return
    with SessionLocal() as db:
        placeholders = ",".join(str(i) for i in user_ids)  # ids are ints from our own inserts
        order_ids = [
            r[0] for r in db.execute(text(f"SELECT id FROM orders WHERE user_id IN ({placeholders})"))
        ]
        order_ph = ",".join(str(i) for i in order_ids) if order_ids else "NULL"
        db.execute(text(f"DELETE FROM return_requests WHERE user_id IN ({placeholders}) "
                        f"OR order_id IN ({order_ph})"))
        db.execute(text(f"DELETE FROM reviews WHERE user_id IN ({placeholders})"))
        db.execute(text(f"DELETE FROM invoices WHERE order_id IN ({order_ph}) OR user_id IN ({placeholders})"))
        db.execute(text(f"DELETE FROM payments WHERE order_id IN ({order_ph})"))
        db.execute(text(f"DELETE FROM order_items WHERE order_id IN ({order_ph})"))
        db.execute(text(f"DELETE FROM orders WHERE user_id IN ({placeholders})"))
        db.execute(text(f"DELETE FROM cart_items WHERE user_id IN ({placeholders})"))
        db.execute(text(f"DELETE FROM notifications WHERE user_id IN ({placeholders})"))
        db.execute(text(f"DELETE FROM development_emails WHERE user_id IN ({placeholders})"))
        db.execute(text(f"DELETE FROM refresh_tokens WHERE user_id IN ({placeholders})"))
        db.execute(text(f"DELETE FROM users WHERE id IN ({placeholders})"))
        db.commit()


RUN_ID = uuid.uuid4().hex[:8]
CUSTOMER_EMAIL = f"smoke-customer-{RUN_ID}@example.com"
ADMIN_EMAIL = f"smoke-admin-{RUN_ID}@example.com"
STAFF_EMAIL = f"smoke-staff-{RUN_ID}@example.com"
# A second admin and second staff account — proves the role column has no
# uniqueness constraint and any number of users can share a role.
ADMIN2_EMAIL = f"smoke-admin2-{RUN_ID}@example.com"
STAFF2_EMAIL = f"smoke-staff2-{RUN_ID}@example.com"

sequences_before = snapshot_sequences()
products_before = snapshot_products()

try:
    # ---- Auth: register -> always customer; login; refresh rotation; logout ----
    tokens, auth, customer_id = register(CUSTOMER_EMAIL, "Smoke Customer")

    r = client.post("/auth/login", json={"email": CUSTOMER_EMAIL, "password": "wrong-password"})
    check("login rejects bad password", r.status_code == 401)

    r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    check("refresh", r.status_code == 200, r.text)
    rotated = r.json()
    r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    check("refresh token rotation (old token revoked)", r.status_code == 401, r.text)
    r = client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
    check("refresh rejects access token", r.status_code == 401)
    r = client.post("/auth/logout", json={"refresh_token": rotated["refresh_token"]})
    check("logout revokes refresh token", r.status_code == 200)
    r = client.post("/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    check("revoked token cannot refresh", r.status_code == 401)
    r = client.post("/auth/login", json={"email": CUSTOMER_EMAIL, "password": "SmokePass123!"})
    tokens = r.json()
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}

    r = client.get("/auth/me", headers=auth)
    check("me", r.status_code == 200 and r.json()["email"] == CUSTOMER_EMAIL, r.text)
    check("me requires auth", client.get("/auth/me").status_code == 401)

    # ---- Products & filters ----
    r = client.get("/products")
    check("list products", r.status_code == 200 and r.json()["total"] >= 12, r.text)
    r = client.get("/products", params={"category": "electronics", "min_price": 10, "max_price": 100, "in_stock": True})
    data = r.json()
    check(
        "filters (category+price+stock)",
        all(i["category"] == "electronics" and 10 <= i["price"] <= 100 and i["stock"] > 0 for i in data["items"]),
        r.text,
    )
    r = client.get("/products", params={"sort": "price_asc"})
    prices = [i["price"] for i in r.json()["items"]]
    check("sort by price", prices == sorted(prices))
    r = client.get("/products/category/home")
    check("by category endpoint", all(i["category"] == "home" for i in r.json()["items"]))
    r = client.get("/products/1")
    check("product detail", r.status_code == 200 and r.json()["id"] == 1)
    check("product 404", client.get("/products/99999").status_code == 404)

    # ---- RBAC: register two more customers, then promote them the way an
    # operator does — directly in MySQL, not through any API ----
    new_product = {"name": "RBAC Test Item", "price": 9.99, "stock": 5, "category": "test"}
    check("customer cannot create product", client.post("/products", json=new_product, headers=auth).status_code == 403)

    admin_tokens, admin_auth, admin_id = register(ADMIN_EMAIL, "Smoke Admin")
    staff_tokens, staff_auth, staff_id = register(STAFF_EMAIL, "Smoke Staff")

    set_role_in_mysql(admin_id, "admin")
    check(
        "role promoted in MySQL takes effect on the existing token (no re-login)",
        client.get("/auth/me", headers=admin_auth).json()["role"] == "admin",
    )
    set_role_in_mysql(staff_id, "staff")
    check(
        "staff promotion in MySQL also takes effect immediately",
        client.get("/auth/me", headers=staff_auth).json()["role"] == "staff",
    )

    # The role column is a native MySQL ENUM('admin','staff','customer') —
    # confirm the database itself refuses any other value.
    try:
        set_role_in_mysql(customer_id, "superadmin")
        check("MySQL enum rejects a role outside admin/staff/customer", False, "invalid role was accepted!")
    except Exception:
        check("MySQL enum rejects a role outside admin/staff/customer", True)

    r = client.post("/products", json=new_product, headers=admin_auth)
    check("admin can create product", r.status_code == 201, r.text)
    rbac_id = r.json()["id"]
    r = client.put(f"/products/{rbac_id}", json={"name": "Renamed by staff", "stock": 9,
        "images": ["https://example.com/new-photo.jpg"]}, headers=staff_auth)
    check("staff can rename/restock/re-photo product",
          r.status_code == 200 and r.json()["name"] == "Renamed by staff"
          and r.json()["stock"] == 9 and r.json()["images"] == ["https://example.com/new-photo.jpg"], r.text)
    check("customer cannot update product",
          client.put(f"/products/{rbac_id}", json={"price": 1.0}, headers=auth).status_code == 403)
    check("staff can delete product", client.delete(f"/products/{rbac_id}", headers=staff_auth).status_code == 204)

    # ---- Multiple admins and multiple staff — the role column has no
    # uniqueness constraint, so any number of users may share a role ----
    admin2_tokens, admin2_auth, admin2_id = register(ADMIN2_EMAIL, "Smoke Admin Two")
    staff2_tokens, staff2_auth, staff2_id = register(STAFF2_EMAIL, "Smoke Staff Two")
    set_role_in_mysql(admin2_id, "admin")
    set_role_in_mysql(staff2_id, "staff")
    check("a second admin account works independently",
          client.get("/auth/me", headers=admin2_auth).json()["role"] == "admin"
          and client.get("/orders/all", headers=admin2_auth).status_code == 200)
    r = client.post("/products", json=new_product, headers=staff2_auth)
    check("a second staff account works independently",
          client.get("/auth/me", headers=staff2_auth).json()["role"] == "staff" and r.status_code == 201, r.text)
    client.delete(f"/products/{r.json()['id']}", headers=staff2_auth)  # leave no test debris in the catalog
    id_list = ",".join(str(i) for i in created_user_ids)
    with SessionLocal() as _db:
        role_counts = dict(_db.execute(
            text(f"SELECT role, COUNT(*) FROM users WHERE id IN ({id_list}) GROUP BY role")
        ).fetchall())
    check("two admins and two staff coexist among this run's users",
          role_counts.get("admin", 0) == 2 and role_counts.get("staff", 0) == 2, str(role_counts))

    # ---- Cart ----
    r = client.post("/cart/add", json={"product_id": 1, "quantity": 2}, headers=auth)
    check("cart add", r.status_code == 201, r.text)
    r = client.post("/cart/add", json={"product_id": 5, "quantity": 1}, headers=auth)
    cart = r.json()
    check("cart merge/add second", len(cart["items"]) == 2, r.text)
    r = client.put("/cart/update", json={"product_id": 1, "quantity": 3}, headers=auth)
    cart = r.json()
    item = next(i for i in cart["items"] if i["product_id"] == 1)
    check("cart update quantity", item["quantity"] == 3)
    expected_total = round(sum(i["item_total"] for i in cart["items"]), 2)
    check("cart totals", cart["cart_total"] == expected_total and cart["grand_total"] == round(cart["cart_total"] + cart["tax"], 2))

    # ---- Real-time cart_updated: another tab sees the change without polling ----
    with client.websocket_connect(f"/ws/notifications?token={tokens['access_token']}") as ws:
        hello = ws.receive_json()
        check("websocket greets with a connected event carrying role and unread count",
              hello["event"] == "connected" and hello["data"]["role"] == "customer"
              and "unread_count" in hello["data"], str(hello))
        ws.send_text("ping")
        check("websocket answers ping with pong", ws.receive_json()["event"] == "pong")
        r = client.put("/cart/update", json={"product_id": 5, "quantity": 2}, headers=auth)
        msg, seen = receive_until(ws, lambda m: m["event"] == "cart_updated")
        check("cart_updated pushed over websocket with the full new cart",
              msg is not None and msg["data"]["reason"] == "updated"
              and msg["data"]["grand_total"] == r.json()["grand_total"]
              and any(i["product_id"] == 5 and i["quantity"] == 2 for i in msg["data"]["items"]), str(seen))
        client.put("/cart/update", json={"product_id": 5, "quantity": 1}, headers=auth)
        msg, seen = receive_until(ws, lambda m: m["event"] == "cart_updated")
        check("every cart change pushes an event (update back to 1)",
              msg is not None and any(i["product_id"] == 5 and i["quantity"] == 1 for i in msg["data"]["items"]),
              str(seen))
    r = client.post("/cart/add", json={"product_id": 10, "quantity": 1}, headers=auth)
    check("stock validation on add", r.status_code == 400, r.text)  # product 10 seeded with stock 0

    # ---- Checkout -> Order -> Payment (Stripe) ----
    stock_before = client.get("/products/1").json()["stock"]
    r = client.post("/checkout", headers=auth)
    check("checkout", r.status_code == 200, r.text)
    co = r.json()
    check("checkout returns stripe session", co["transaction_id"] is not None and co["checkout_url"] is not None)
    order_id = co["order_id"]
    check("cart cleared after checkout", client.get("/cart", headers=auth).json()["items"] == [])
    check("stock decremented", client.get("/products/1").json()["stock"] == stock_before - 3)
    check("checkout with empty cart rejected", client.post("/checkout", headers=auth).status_code == 400)

    # Product 1 is now on this run's order: deleting it would break order
    # history, and order_items would refuse on the foreign key anyway.
    r = client.delete("/products/1", headers=admin_auth)
    check("deleting a product that appears on an order is refused with an explanation",
          r.status_code == 409 and "stock to 0" in r.json()["detail"], r.text)
    check("that product is still in the catalog", client.get("/products/1").status_code == 200)

    r = client.get(f"/orders/{order_id}", headers=auth)
    order = r.json()
    check("order created", r.status_code == 200 and order["order_status"] == "pending" and order["total"] == co["amount"])
    r = client.get(f"/payments/{order_id}", headers=auth)
    check("payment tracked", r.status_code == 200 and r.json()["status"] == "pending", r.text)

    # ---- Payment confirmation by order id (staff/admin only) ----
    check("customer cannot confirm a payment",
          client.post(f"/payments/confirm/{order_id}", headers=auth).status_code == 403)
    check("confirming an unknown order 404s as JSON",
          client.post("/payments/confirm/999999", headers=admin_auth).status_code == 404)

    # ---- Real-time notifications over WebSocket + payment confirmation ----
    customer_ws = client.websocket_connect(f"/ws/notifications?token={tokens['access_token']}")
    staff_ws_ctx = client.websocket_connect(f"/ws/notifications?token={staff_tokens['access_token']}")
    with customer_ws as ws, staff_ws_ctx as staff_ws:
        ws.receive_json()
        staff_ws.receive_json()  # connected greetings
        r = client.post(f"/payments/confirm/{order_id}", headers=staff_auth)
        check("staff confirms payment by order id (works with live Stripe keys too)",
              r.status_code == 200 and r.json()["status"] == "succeeded", r.text)
        note, seen = receive_until(ws, lambda m: m["event"] == "notification")
        check("websocket payment_successful notification pushed to the customer",
              note is not None and note["data"]["type"] == "payment_successful"
              and "Invoice INV-" in note["data"]["message"] and note["data"]["order_id"] == order_id
              and note["data"]["read_status"] is False and note["data"]["timestamp"], str(seen))
        update, seen = receive_until(ws, lambda m: m["event"] == "order_status_updated")
        check("websocket order_status_updated pushed to the customer (pending -> paid)",
              update is not None and update["data"]["order_id"] == order_id
              and update["data"]["previous_status"] == "pending"
              and update["data"]["order_status"] == "paid"
              and update["data"]["payment_status"] == "succeeded", str(seen))
        staff_update, seen = receive_until(staff_ws, lambda m: m["event"] == "order_status_updated")
        check("staff also receive order_status_updated for a customer's order",
              staff_update is not None and staff_update["data"]["order_id"] == order_id, str(seen))

    r = client.get(f"/orders/{order_id}", headers=auth)
    check("order marked paid", r.json()["order_status"] == "paid" and r.json()["payment_status"] == "succeeded")

    # ---- Real Stripe webhook processing (regression test) ----
    # Found live in production: obj = event["data"]["object"] is a *typed*
    # Stripe resource (e.g. checkout.Session), not a plain dict — newer
    # stripe-python raises AttributeError on dict-style .get()/.items(), which
    # crashed every real webhook delivery with a 500 while mock-mode tests (the
    # block above) never touched this code at all. These checks build genuine
    # typed Stripe objects (stripe.Event.construct_from, no network) so this
    # class of bug can't silently reappear.
    import stripe as _stripe
    from unittest.mock import patch as _patch

    def _fake_stripe_event(session_id, metadata=None):
        return _stripe.Event.construct_from(
            {
                "id": "evt_test_" + session_id,
                "object": "event",
                "type": "checkout.session.completed",
                "data": {"object": {
                    "id": session_id,
                    "object": "checkout.session",
                    "payment_status": "paid",
                    "metadata": metadata or {},
                }},
            },
            "sk_test_fake",
        )

    r = client.post("/cart/add", json={"product_id": in_stock_product(), "quantity": 1}, headers=auth)
    r = client.post("/checkout", headers=auth)
    webhook_order_id = r.json()["order_id"]
    real_txn_id = r.json()["transaction_id"]

    with _patch("app.routers.payments.stripe_service.construct_webhook_event",
                return_value=_fake_stripe_event(real_txn_id)):
        r = client.post("/payments/webhook", content=b"{}", headers={"Stripe-Signature": "test"})
    check("webhook: direct transaction_id match (typed obj.id, not .get())",
          r.status_code == 200 and r.json()["matched"] is True, r.text)
    check("webhook direct-match order now paid",
          client.get(f"/orders/{webhook_order_id}", headers=auth).json()["order_status"] == "paid")

    r = client.post("/cart/add", json={"product_id": 3, "quantity": 1}, headers=auth)
    r = client.post("/checkout", headers=auth)
    fallback_order_id = r.json()["order_id"]

    with _patch("app.routers.payments.stripe_service.construct_webhook_event",
                return_value=_fake_stripe_event("cs_unrelated_id", metadata={"order_id": str(fallback_order_id)})):
        r = client.post("/payments/webhook", content=b"{}", headers={"Stripe-Signature": "test"})
    check("webhook: metadata.order_id fallback match (typed obj.metadata, not .get())",
          r.status_code == 200 and r.json()["matched"] is True, r.text)
    check("webhook fallback-match order now paid",
          client.get(f"/orders/{fallback_order_id}", headers=auth).json()["order_status"] == "paid")

    # ---- Receipt page data (what Stripe redirects back to) ----
    r = client.get(f"/payments/receipt?order_id={order_id}", headers=auth)
    receipt = r.json()
    check("receipt by order id carries the payment details",
          r.status_code == 200
          and receipt["order_id"] == order_id
          and receipt["transaction_id"] == co["transaction_id"]
          and receipt["amount"] == co["amount"]
          and receipt["payment_status"] == "succeeded", r.text)
    check("a settled receipt reports a paid time and its invoice",
          receipt["paid_at"] is not None and receipt["invoice_number"].startswith("INV-"), r.text)
    check("receipt lists the purchased items", len(receipt["items"]) >= 1, r.text)
    check("a settled receipt is not awaiting confirmation",
          receipt["awaiting_confirmation"] is False, r.text)

    # Stripe hands the session id back on the success redirect, so that must work too.
    r = client.get(f"/payments/receipt?session_id={co['transaction_id']}", headers=auth)
    check("receipt by stripe session id resolves the same order",
          r.status_code == 200 and r.json()["order_id"] == order_id, r.text)

    check("receipt needs some way to find the payment",
          client.get("/payments/receipt", headers=auth).status_code == 422)
    check("unknown session id has no receipt",
          client.get("/payments/receipt?session_id=cs_nope", headers=auth).status_code == 404)
    check("staff may read any customer's receipt",
          client.get(f"/payments/receipt?order_id={order_id}", headers=staff_auth).status_code == 200)
    _, other_auth, _ = register(f"smoke-other-{RUN_ID}@example.com", "Smoke Other Customer")
    check("a customer cannot read someone else's receipt",
          client.get(f"/payments/receipt?order_id={order_id}", headers=other_auth).status_code == 403)

    # ---- The API says what can be done next, so callers never have to guess ----
    r = client.get(f"/orders/{order_id}/status-options", headers=staff_auth)
    opts = r.json()
    check("status-options lists the legal next statuses for a paid order",
          r.status_code == 200 and opts["order_status"] == "paid"
          and set(opts["allowed_next_statuses"]) == {"shipped", "cancelled"}, r.text)
    check("status-options says a settled payment can't be confirmed again",
          opts["can_confirm_payment"] is False, r.text)
    check("customer denied status-options",
          client.get(f"/orders/{order_id}/status-options", headers=auth).status_code == 403)
    check("every order response carries its own allowed_next_statuses",
          set(client.get(f"/orders/{order_id}", headers=auth).json()["allowed_next_statuses"])
          == {"shipped", "cancelled"})

    # ---- Order status flow (staff/admin) — the transitions the status box offers ----
    check("customer cannot update status", client.put(f"/orders/{order_id}/status?status=shipped", headers=auth).status_code == 403)
    with client.websocket_connect(f"/ws/notifications?token={tokens['access_token']}") as ws:
        ws.receive_json()  # connected
        r = client.put(f"/orders/{order_id}/status?status=shipped", headers=admin_auth)
        check("paid -> shipped", r.status_code == 200 and r.json()["order_status"] == "shipped", r.text)
        note, seen = receive_until(ws, lambda m: m["event"] == "notification")
        check("order_shipped notification pushed live",
              note is not None and note["data"]["type"] == "order_shipped", str(seen))
        update, seen = receive_until(ws, lambda m: m["event"] == "order_status_updated")
        check("order_status_updated pushed live (paid -> shipped)",
              update is not None and update["data"]["previous_status"] == "paid"
              and update["data"]["order_status"] == "shipped"
              and update["data"]["allowed_next_statuses"] == ["delivered", "cancelled"], str(seen))
    check("invalid transition rejected", client.put(f"/orders/{order_id}/status?status=paid", headers=admin_auth).status_code == 400)
    # shipped can now also be cancelled (previously only delivered was allowed)
    r = client.put(f"/orders/{fallback_order_id}/status", json={"status": "shipped"}, headers=staff_auth)
    check("staff can ship too", r.status_code == 200, r.text)
    r = client.put(f"/orders/{fallback_order_id}/status?status=cancelled", headers=staff_auth)
    check("shipped -> cancelled is allowed", r.status_code == 200 and r.json()["order_status"] == "cancelled", r.text)
    check("cancelled is terminal",
          client.put(f"/orders/{fallback_order_id}/status?status=delivered", headers=admin_auth).status_code == 400)
    # pending -> paid must go through payment confirmation, not a raw status flip,
    # otherwise the order would be "paid" with a pending payment and no invoice.
    r = client.post("/cart/add", json={"product_id": 5, "quantity": 1}, headers=auth)
    r = client.post("/checkout?payment_method=cash", headers=auth)
    raw_paid_order = r.json()["order_id"]
    r = client.put(f"/orders/{raw_paid_order}/status?status=paid", headers=admin_auth)
    check("pending -> paid rejected on the status endpoint (must confirm the payment)",
          r.status_code == 400 and "confirm" in r.json()["detail"].lower(), r.text)
    r = client.put(f"/orders/{raw_paid_order}/status?status=cancelled", headers=admin_auth)
    check("pending -> cancelled is allowed", r.status_code == 200, r.text)
    # Omitting the status entirely explains what to do instead of a bare 422.
    r = client.put(f"/orders/{raw_paid_order}/status", headers=admin_auth)
    check("missing status explains how to pick one",
          r.status_code == 422 and "status=" in r.json()["detail"], r.text)
    check("a final order reports no next statuses",
          client.get(f"/orders/{raw_paid_order}/status-options", headers=admin_auth)
          .json()["allowed_next_statuses"] == [])
    check("staff/admin order list", client.get("/orders/all", headers=admin_auth).status_code == 200)
    check("customer denied /orders/all", client.get("/orders/all", headers=auth).status_code == 403)

    # ---- Notifications API ----
    r = client.get("/notifications", headers=auth)
    notifs = r.json()
    types = {n["type"] for n in notifs}
    check("notifications persisted for each order event",
          {"order_placed", "order_confirmed", "payment_successful", "order_shipped", "order_cancelled"} <= types,
          str(types))
    first = notifs[0]
    check("notification exposes id/type/message/read_status/timestamp",
          {"id", "type", "message", "read_status", "timestamp"} <= first.keys()
          and first["read_status"] == first["is_read"] and first["timestamp"] == first["created_at"], str(first))
    r = client.get("/notifications", params={"type": "order_shipped"}, headers=auth)
    check("filter notifications by type", r.status_code == 200 and len(r.json()) >= 1
          and all(n["type"] == "order_shipped" for n in r.json()), r.text)
    check("unknown notification type is a 422, not an empty list",
          client.get("/notifications", params={"type": "bogus"}, headers=auth).status_code == 422)
    unread_before = client.get("/notifications/unread-count", headers=auth).json()["unread_count"]
    check("unread count reflects unread notifications",
          unread_before == sum(not n["is_read"] for n in notifs), str(unread_before))

    r = client.post("/notifications/read", json={"notification_ids": []}, headers=auth)
    check("POST /notifications/read with an empty id list marks nothing",
          r.status_code == 200 and r.json()["marked_read"] == 0, r.text)
    staff_notif_ids = [n["id"] for n in client.get("/notifications", headers=staff_auth).json()]
    if staff_notif_ids:
        r = client.post("/notifications/read", json={"notification_ids": staff_notif_ids}, headers=auth)
        check("a user cannot mark someone else's notifications read", r.json()["marked_read"] == 0, r.text)
    with client.websocket_connect(f"/ws/notifications?token={tokens['access_token']}") as ws:
        ws.receive_json()
        r = client.post("/notifications/read", json={"notification_ids": [first["id"]]}, headers=auth)
        check("POST /notifications/read marks the given ids",
              r.status_code == 200 and r.json()["marked_read"] == 1
              and r.json()["unread_count"] == unread_before - 1, r.text)
        msg, seen = receive_until(ws, lambda m: m["event"] == "notifications_read")
        check("notifications_read pushed so other tabs update their badge",
              msg is not None and msg["data"]["notification_ids"] == [first["id"]], str(seen))
    marked = next(n for n in client.get("/notifications", headers=auth).json() if n["id"] == first["id"])
    check("marked notification now reads as read", marked["read_status"] is True)
    r = client.post("/notifications/read", json={"all": True}, headers=auth)
    check("POST /notifications/read {all: true} marks every one read",
          r.status_code == 200 and r.json()["unread_count"] == 0, r.text)
    check("unread_only now empty", client.get("/notifications?unread_only=true", headers=auth).json() == [])
    check("the old PUT mark-read endpoints are gone (POST /notifications/read replaces them)",
          client.put("/notifications/read-all", headers=auth).status_code in (404, 405)
          and client.put(f"/notifications/{first['id']}/read", headers=auth).status_code in (404, 405))

    # ---- Email notifications (EMAIL_BACKEND=database in tests) ----
    emails = client.get("/dev/emails", headers=auth).json()
    subjects = [e["subject"] for e in emails]
    check("order confirmation email recorded",
          any(x.startswith("Order confirmation") for x in subjects), str(subjects))
    check("payment success email recorded",
          any(x.startswith("Payment successful") for x in subjects), str(subjects))
    check("shipping update emails recorded (shipped + cancelled)",
          sum(x.startswith("Shipping update") for x in subjects) >= 2, str(subjects))
    shipped_mail = next(e for e in emails if e["notification_type"] == "order_shipped")
    check("emails go to the customer, in text + HTML, stored by the database backend",
          shipped_mail["to_email"] == CUSTOMER_EMAIL and shipped_mail["status"] == "stored"
          and "Smoke Customer" in shipped_mail["body"] and "<table" in shipped_mail["html_body"],
          str(shipped_mail)[:300])
    paid_mail = next(e for e in emails if e["notification_type"] == "payment_successful")
    check("amounts in emails are formatted in rupees", "\u20b9" in paid_mail["body"], paid_mail["body"][:300])
    check("a user's emails are private",
          client.get(f"/dev/emails/{shipped_mail['id']}", headers=other_auth).status_code == 404)
    check("unknown email id is a 404 (not a 500)",
          client.get("/dev/emails/999999999", headers=auth).status_code == 404)

    # SMTP backend (SendGrid / SES are SMTP relays too): delivery runs on a
    # worker thread and the outcome is recorded on the row.
    import time as _time
    from unittest.mock import patch as _p
    from app.models import DevelopmentEmail as _Email, User as _User
    from app.services import email_service as _es

    def _wait_status(email_id, timeout=10):
        deadline = _time.time() + timeout
        while True:
            with SessionLocal() as _db:
                row = _db.get(_Email, email_id)
                _db.expunge(row)
            if row.status != "queued" or _time.time() > deadline:
                return row
            _time.sleep(0.1)

    sent_messages = []
    # Test users are local accounts on @example.com, which real sends skip; delivery
    # here is mocked or refused, so let them through for these checks.
    with _p.object(settings, "EMAIL_BACKEND", "smtp"), _p.object(_es, "smtp_skip_reason", return_value=None), \
            _p.object(_es, "smtp_send", side_effect=sent_messages.append):
        with SessionLocal() as _db:
            row = _es.send_email(_db, _db.get(_User, customer_id), "SMTP check", "plain body",
                                 "<p>html body</p>", notification_type="info")
            smtp_id, smtp_status = row.id, row.status
        check("smtp backend queues instead of storing", smtp_status == "queued", smtp_status)
        row = _wait_status(smtp_id)
    check("smtp backend sends the message and marks it sent",
          row.status == "sent" and row.sent_at is not None and len(sent_messages) == 1, row.status)
    if sent_messages:
        msg = sent_messages[0]
        check("sent message is multipart text + HTML addressed to the user",
              msg["To"] == CUSTOMER_EMAIL and msg.get_body(("html",)) is not None
              and msg.get_body(("plain",)).get_content().strip() == "plain body", str(msg["To"]))

    # A real SMTP connection attempt to a port nothing listens on: the call
    # still returns normally and the failure is recorded, not raised.
    with _p.object(settings, "EMAIL_BACKEND", "smtp"), _p.object(_es, "smtp_skip_reason", return_value=None), \
            _p.object(settings, "SMTP_HOST", "127.0.0.1"), \
            _p.object(settings, "SMTP_PORT", 9), _p.object(settings, "SMTP_TIMEOUT", 3):
        with SessionLocal() as _db:
            failing_id = _es.send_email(_db, _db.get(_User, customer_id), "Unreachable", "x").id
        row = _wait_status(failing_id)
        check("unreachable SMTP server marks the email failed with the reason",
              row.status == "failed" and bool(row.error), f"{row.status} {row.error}")
        check("staff cannot retry emails",
              client.post(f"/admin/emails/{failing_id}/retry", headers=staff_auth).status_code == 403)
        with _p.object(_es, "smtp_send", return_value=None):
            r = client.post(f"/admin/emails/{failing_id}/retry", headers=admin_auth)
            check("admin can retry a failed email", r.status_code == 200 and r.json()["status"] == "queued", r.text)
            row = _wait_status(failing_id)
    check("retried email is delivered", row.status == "sent", row.status)

    # ---- Inbox for a local account with a made-up @gmail.com address ----
    # The address can't be trusted to receive mail, so the in-app inbox is how
    # this user reads what the store sent them.
    INBOX_EMAIL = f"smoke-inbox-{RUN_ID}@gmail.com"
    inbox_tokens, inbox_auth, inbox_id = register(INBOX_EMAIL, "Smoke Inbox User")
    r = client.get("/dev/emails/summary", headers=inbox_auth)
    check("a new local user starts with an empty inbox",
          r.status_code == 200 and r.json()["address"] == INBOX_EMAIL
          and r.json()["total"] == 0 and r.json()["unread_count"] == 0, r.text)
    with client.websocket_connect(f"/ws/notifications?token={inbox_tokens['access_token']}") as ws:
        ws.receive_json()
        client.post("/cart/add", json={"product_id": 5, "quantity": 1}, headers=inbox_auth)
        r = client.post("/checkout?payment_method=cash", headers=inbox_auth)
        inbox_order_id = r.json()["order_id"]
        msg, seen = receive_until(ws, lambda m: m["event"] == "email")
        check("new mail is pushed live with the unread count",
              msg is not None and msg["data"]["subject"].startswith("Order confirmation")
              and msg["data"]["unread_count"] == 1, str(seen))
    summary = client.get("/dev/emails/summary", headers=inbox_auth).json()
    check("the inbox summary counts the new unread email and says it stays in the app",
          summary["total"] == 1 and summary["unread_count"] == 1 and "in-app inbox" in summary["delivery"],
          str(summary))
    inbox = client.get("/dev/emails?unread_only=true", headers=inbox_auth).json()
    check("the local gmail user can read the full email in their inbox",
          len(inbox) == 1 and inbox[0]["to_email"] == INBOX_EMAIL and inbox[0]["is_read"] is False
          and "Smoke Inbox User" in inbox[0]["body"] and inbox[0]["html_body"], str(inbox)[:300])
    check("reading one email doesn't mark it read on its own",
          client.get(f"/dev/emails/{inbox[0]['id']}", headers=inbox_auth).json()["is_read"] is False)
    check("someone else can't mark your email read",
          client.post("/dev/emails/read", json={"email_ids": [inbox[0]["id"]]}, headers=auth).json()["marked_read"] == 0)
    check("an empty id list marks nothing",
          client.post("/dev/emails/read", json={"email_ids": []}, headers=inbox_auth).json()["marked_read"] == 0)
    with client.websocket_connect(f"/ws/notifications?token={inbox_tokens['access_token']}") as ws:
        ws.receive_json()
        r = client.post("/dev/emails/read", json={"email_ids": [inbox[0]["id"]]}, headers=inbox_auth)
        check("POST /dev/emails/read marks it read",
              r.status_code == 200 and r.json() == {"marked_read": 1, "unread_count": 0}, r.text)
        msg, seen = receive_until(ws, lambda m: m["event"] == "emails_read")
        check("emails_read pushed so other tabs clear the badge",
              msg is not None and msg["data"]["unread_count"] == 0, str(seen))
    check("unread-only is now empty and the email is still in the inbox",
          client.get("/dev/emails?unread_only=true", headers=inbox_auth).json() == []
          and len(client.get("/dev/emails", headers=inbox_auth).json()) == 1)

    # With real SMTP on, a local account's unverified address is never emailed —
    # the copy still lands in the inbox. Google accounts (verified) are emailed.
    smtp_calls = []
    with _p.object(settings, "EMAIL_BACKEND", "smtp"), _p.object(_es, "smtp_send", side_effect=smtp_calls.append):
        with SessionLocal() as _db:
            local_row = _es.send_email(_db, _db.get(_User, inbox_id), "Local SMTP check", "body")
            local_status, local_error = local_row.status, local_row.error
        check("smtp never sends to a local account's unverified address",
              local_status == "skipped" and "Local account" in local_error, f"{local_status} {local_error}")
        summary = client.get("/dev/emails/summary", headers=inbox_auth).json()
        check("...but the email is still readable in their inbox",
              summary["total"] == 2 and summary["unread_count"] == 1 and "isn't verified" in summary["delivery"],
              str(summary))
        with _p.object(settings, "SMTP_SEND_TO_LOCAL_ACCOUNTS", True), SessionLocal() as _db:
            opted_in = _es.send_email(_db, _db.get(_User, inbox_id), "Opt-in check", "body")
            check("SMTP_SEND_TO_LOCAL_ACCOUNTS=true sends to local accounts", opted_in.status == "queued", opted_in.status)
            _wait_status(opted_in.id)
        with SessionLocal() as _db:
            _db.execute(text("UPDATE users SET auth_provider = 'google' WHERE id = :id"), {"id": inbox_id})
            _db.commit()
            google_row = _es.send_email(_db, _db.get(_User, inbox_id), "Google check", "body")
            check("google accounts (verified address) are sent over smtp", google_row.status == "queued", google_row.status)
            _wait_status(google_row.id)
    check("only the opted-in and google emails reached SMTP", len(smtp_calls) == 2, str(len(smtp_calls)))
    client.delete(f"/orders/{inbox_order_id}", headers=admin_auth)  # returns the reserved stock

    # ---- Deactivating an account (admin panel) locks it out immediately ----
    off_tokens, off_auth, off_id = register(f"smoke-off-{RUN_ID}@example.com", "Smoke Deactivated")
    check("a new account is active", client.get("/auth/me", headers=off_auth).json()["is_active"] is True)
    set_active_in_mysql(off_id, False)
    r = client.get("/auth/me", headers=off_auth)
    check("a token issued before deactivation stops working on the next request",
          r.status_code == 403 and "deactivated" in r.json()["detail"], r.text)
    r = client.post("/auth/login", json={"email": f"smoke-off-{RUN_ID}@example.com", "password": "SmokePass123!"})
    check("a deactivated user cannot log in", r.status_code == 403 and "deactivated" in r.json()["detail"], r.text)
    r = client.post("/auth/refresh", json={"refresh_token": off_tokens["refresh_token"]})
    check("a deactivated user cannot refresh their token", r.status_code == 403, r.text)
    check("shopping is blocked too",
          client.get("/cart", headers=off_auth).status_code == 403
          and client.post("/checkout", headers=off_auth).status_code == 403)
    r = client.get("/admin/users", params={"is_active": False}, headers=admin_auth)
    check("admins can list deactivated accounts",
          r.status_code == 200 and any(u["id"] == off_id and u["is_active"] is False for u in r.json()), r.text)
    set_active_in_mysql(off_id, True)
    check("reactivating restores access immediately",
          client.get("/auth/me", headers=off_auth).status_code == 200)
    check("and login works again",
          client.post("/auth/login",
                      json={"email": f"smoke-off-{RUN_ID}@example.com", "password": "SmokePass123!"}
                      ).status_code == 200)

    # ---- Returns and refunds ----
    # A delivered order, bought and paid for by the customer.
    client.post("/cart/add", json={"product_id": in_stock_product(), "quantity": 1}, headers=auth)
    ret_order_id = client.post("/checkout?payment_method=cash", headers=auth).json()["order_id"]
    client.post(f"/payments/cash/confirm/{ret_order_id}", headers=staff_auth)
    client.put(f"/orders/{ret_order_id}/status?status=shipped", headers=staff_auth)
    client.put(f"/orders/{ret_order_id}/status?status=delivered", headers=staff_auth)

    order = client.get(f"/orders/{ret_order_id}", headers=auth).json()
    check("delivery is timestamped, and the order offers a return inside the window",
          order["delivered_at"] is not None and order["can_request_return"] is True
          and order["return_deadline"] is not None, str(order)[:200])
    check("the return window is the configured number of days",
          (datetime.fromisoformat(order["return_deadline"])
           - datetime.fromisoformat(order["delivered_at"])).days == settings.RETURN_WINDOW_DAYS)

    r = client.get("/returns/reasons")
    check("the reason list is available for the storefront dropdown",
          r.status_code == 200 and {"value": "damaged", "label": "Arrived damaged"} in r.json(), r.text)
    check("an unknown reason is rejected",
          client.post(f"/orders/{ret_order_id}/return", json={"reason": "because"},
                      headers=auth).status_code == 422)

    # Only the owner may open it, and only on a delivered order.
    check("another customer cannot open a return on someone else's order",
          client.post(f"/orders/{ret_order_id}/return", json={"reason": "damaged"},
                      headers=other_auth).status_code == 403)
    check("a pending order cannot be returned",
          client.post(f"/orders/{fallback_order_id}/return", json={"reason": "damaged"},
                      headers=auth).status_code in (403, 409))

    with client.websocket_connect(f"/ws/notifications?token={tokens['access_token']}") as ws, \
            client.websocket_connect(f"/ws/notifications?token={staff_tokens['access_token']}") as staff_ws:
        ws.receive_json(), staff_ws.receive_json()
        r = client.post(f"/orders/{ret_order_id}/return",
                        json={"reason": "damaged", "comment": "Screen cracked in transit."},
                        headers=auth)
        check("the customer opens a return request",
              r.status_code == 201 and r.json()["status"] == "pending"
              and r.json()["reason"] == "damaged"
              and r.json()["reason_label"] == "Arrived damaged"
              and r.json()["comment"] == "Screen cracked in transit.", r.text)
        return_id = r.json()["id"]
        note, seen = receive_until(ws, lambda m: m["event"] == "notification")
        check("the customer is notified that the request was received",
              note is not None and note["data"]["type"] == "return_requested", str(seen))
        queued, seen = receive_until(staff_ws, lambda m: m["event"] == "return_requested")
        check("staff see the new request land in their queue live",
              queued is not None and queued["data"]["return_id"] == return_id, str(seen))

    order = client.get(f"/orders/{ret_order_id}", headers=auth).json()
    check("the order moves to return_requested",
          order["order_status"] == "return_requested" and order["return_status"] == "pending"
          and order["can_request_return"] is False, str(order)[:200])
    check("a second request is refused while one is open",
          client.post(f"/orders/{ret_order_id}/return", json={"reason": "damaged"},
                      headers=auth).status_code == 409)
    mails = [e["subject"] for e in client.get("/dev/emails", headers=auth).json()]
    check("the customer gets a return-received email",
          any(m.startswith("Return request received") for m in mails), str(mails[:3]))

    check("the customer sees their own requests",
          any(x["id"] == return_id for x in client.get("/returns", headers=auth).json()))
    check("another customer cannot read it",
          client.get(f"/returns/{return_id}", headers=other_auth).status_code == 403)
    check("customers cannot open the staff queue",
          client.get("/returns/all", headers=auth).status_code == 403)
    queue = client.get("/returns/all", params={"status": "pending"}, headers=staff_auth)
    check("staff queue lists it with the customer's identity",
          queue.status_code == 200
          and any(x["id"] == return_id and x["user_email"] == CUSTOMER_EMAIL for x in queue.json()),
          queue.text[:200])
    check("customers cannot approve their own return",
          client.post(f"/returns/{return_id}/approve", headers=auth).status_code == 403)

    # ---- Rejection puts the order back to delivered ----
    r = client.post(f"/returns/{return_id}/reject", json={"note": "Outside our policy."},
                    headers=staff_auth)
    check("staff can reject a return",
          r.status_code == 200 and r.json()["status"] == "rejected"
          and r.json()["decision_note"] == "Outside our policy."
          and r.json()["decided_by"] == "Smoke Staff", r.text)
    order = client.get(f"/orders/{ret_order_id}", headers=auth).json()
    check("a rejected return returns the order to delivered",
          order["order_status"] == "delivered" and order["payment_status"] == "succeeded", str(order)[:160])
    check("deciding twice is refused",
          client.post(f"/returns/{return_id}/reject", headers=staff_auth).status_code == 409)
    mails = [e["subject"] for e in client.get("/dev/emails", headers=auth).json()]
    check("the customer is emailed about the rejection",
          any(m.startswith("Return request declined") for m in mails), str(mails[:3]))

    # ---- Approval refunds the money and restocks the goods ----
    ret_product_id = client.get(f"/orders/{ret_order_id}", headers=auth).json()["items"][0]["product_id"]
    stock_before = client.get(f"/products/{ret_product_id}").json()["stock"]
    r = client.post(f"/orders/{ret_order_id}/return", json={"reason": "wrong_item"}, headers=auth)
    check("a return can be opened again after a rejection", r.status_code == 201, r.text)
    second_id = r.json()["id"]

    with client.websocket_connect(f"/ws/notifications?token={tokens['access_token']}") as ws:
        ws.receive_json()
        r = client.post(f"/returns/{second_id}/approve", json={"note": "Refunded in full."},
                        headers=admin_auth)
        check("staff approve the return and the refund is recorded",
              r.status_code == 200 and r.json()["status"] == "approved"
              and r.json()["refund_amount"] == order["total"]
              and r.json()["refund_reference"], r.text)
        note, seen = receive_until(ws, lambda m: m["event"] == "notification")
        check("the customer is notified of the approved refund",
              note is not None and note["data"]["type"] == "return_approved", str(seen))

    order = client.get(f"/orders/{ret_order_id}", headers=auth).json()
    check("the order is returned and the payment refunded",
          order["order_status"] == "returned" and order["payment_status"] == "refunded",
          str(order)[:160])
    check("the returned stock goes back on the shelf",
          client.get(f"/products/{ret_product_id}").json()["stock"] == stock_before + 1)
    mails = [e["subject"] for e in client.get("/dev/emails", headers=auth).json()]
    check("the customer is emailed about the refund",
          any(m.startswith("Return approved") for m in mails), str(mails[:3]))
    check("a returned order offers no further status moves",
          client.get(f"/orders/{ret_order_id}/status-options", headers=staff_auth)
          .json()["allowed_next_statuses"] == [])
    check("and no new return can be opened on it",
          client.post(f"/orders/{ret_order_id}/return", json={"reason": "damaged"},
                      headers=auth).status_code == 409)

    # The Django admin decides returns with SERVICE_API_TOKEN, not a JWT — the
    # same door the order-status endpoint opens. Without this the admin's
    # approve/decline actions could never work.
    from unittest.mock import patch as _rp

    client.post("/cart/add", json={"product_id": in_stock_product(), "quantity": 1}, headers=auth)
    svc_ret_order = client.post("/checkout?payment_method=cash", headers=auth).json()["order_id"]
    client.post(f"/payments/cash/confirm/{svc_ret_order}", headers=staff_auth)
    client.put(f"/orders/{svc_ret_order}/status?status=shipped", headers=staff_auth)
    client.put(f"/orders/{svc_ret_order}/status?status=delivered", headers=staff_auth)
    svc_ret_id = client.post(f"/orders/{svc_ret_order}/return",
                             json={"reason": "missing_parts"}, headers=auth).json()["id"]

    check("an unauthenticated caller cannot decide a return",
          client.post(f"/returns/{svc_ret_id}/approve").status_code == 401)
    with _rp.object(settings, "SERVICE_API_TOKEN", "test-service-token"):
        check("a wrong service token is rejected on returns",
              client.post(f"/returns/{svc_ret_id}/reject",
                          headers={"X-Service-Token": "nope"}).status_code == 401)
        r = client.post(f"/returns/{svc_ret_id}/approve", json={"note": "Approved from /admin/."},
                        headers={"X-Service-Token": "test-service-token"})
        check("the Django admin's service token can approve and refund a return",
              r.status_code == 200 and r.json()["status"] == "approved"
              and r.json()["refund_reference"] and r.json()["decided_by"] is None, r.text)
    check("that order is returned and refunded",
          client.get(f"/orders/{svc_ret_order}", headers=auth).json()["payment_status"] == "refunded")
    client.delete(f"/orders/{svc_ret_order}", headers=admin_auth)

    # Outside the window: a delivery backdated past the deadline.
    client.post("/cart/add", json={"product_id": in_stock_product(), "quantity": 1}, headers=auth)
    old_order_id = client.post("/checkout?payment_method=cash", headers=auth).json()["order_id"]
    client.post(f"/payments/cash/confirm/{old_order_id}", headers=staff_auth)
    client.put(f"/orders/{old_order_id}/status?status=shipped", headers=staff_auth)
    client.put(f"/orders/{old_order_id}/status?status=delivered", headers=staff_auth)
    with SessionLocal() as _db:
        _db.execute(text("UPDATE orders SET delivered_at = :d WHERE id = :id"),
                    {"d": datetime.utcnow() - timedelta(days=settings.RETURN_WINDOW_DAYS + 1),
                     "id": old_order_id})
        _db.commit()
    check("an order delivered outside the window offers no return",
          client.get(f"/orders/{old_order_id}", headers=auth).json()["can_request_return"] is False)
    r = client.post(f"/orders/{old_order_id}/return", json={"reason": "damaged"}, headers=auth)
    check("and the API refuses it, naming the deadline",
          r.status_code == 409 and "window" in r.json()["detail"], r.text)
    client.delete(f"/orders/{old_order_id}", headers=admin_auth)

    # ---- Service token: the Django admin moving an order through the API ----
    # Same endpoint as the storefront, so the customer still gets the
    # notification, the email and the live update.
    from unittest.mock import patch as _sp

    r = client.post("/cart/add", json={"product_id": in_stock_product(), "quantity": 1}, headers=auth)
    svc_order_id = client.post("/checkout?payment_method=cash", headers=auth).json()["order_id"]
    client.post(f"/payments/cash/confirm/{svc_order_id}", headers=staff_auth)

    check("without a service token configured, the header is ignored",
          client.put(f"/orders/{svc_order_id}/status?status=shipped",
                     headers={"X-Service-Token": "anything"}).status_code == 401)

    with _sp.object(settings, "SERVICE_API_TOKEN", "test-service-token"):
        r = client.put(f"/orders/{svc_order_id}/status?status=shipped",
                       headers={"X-Service-Token": "wrong-token"})
        check("a wrong service token is rejected", r.status_code == 401, r.text)

        with client.websocket_connect(f"/ws/notifications?token={tokens['access_token']}") as ws:
            ws.receive_json()  # connected
            r = client.put(f"/orders/{svc_order_id}/status?status=shipped",
                           headers={"X-Service-Token": "test-service-token"})
            check("the service token moves the order without a JWT",
                  r.status_code == 200 and r.json()["order_status"] == "shipped", r.text)
            note, seen = receive_until(ws, lambda m: m["event"] == "notification")
            check("a service-token change still notifies the customer live",
                  note is not None and note["data"]["type"] == "order_shipped", str(seen))
            update, seen = receive_until(ws, lambda m: m["event"] == "order_status_updated")
            check("...and still pushes order_status_updated",
                  update is not None and update["data"]["order_status"] == "shipped", str(seen))
        mails = [e["subject"] for e in client.get("/dev/emails", headers=auth).json()]
        check("...and still sends the shipping email",
              any(f"order #{r.json()['order_number']} shipped" in m for m in mails), str(mails[:3]))
        check("transition rules still apply to the service token",
              client.put(f"/orders/{svc_order_id}/status?status=paid",
                         headers={"X-Service-Token": "test-service-token"}).status_code == 400)
    client.delete(f"/orders/{svc_order_id}", headers=admin_auth)  # returns the reserved stock

    # ---- Reviews and ratings ----
    review_product_id = in_stock_product()
    check("cannot review a product you haven't received",
          client.post("/reviews", json={"product_id": review_product_id, "rating": 5},
                      headers=auth).status_code == 403)
    check("reviewing an unknown product 404s",
          client.post("/reviews", json={"product_id": 999999, "rating": 5},
                      headers=auth).status_code == 404)
    check("a rating outside 1-5 is rejected",
          client.post("/reviews", json={"product_id": review_product_id, "rating": 6},
                      headers=auth).status_code == 422)

    # Deliver an order containing this product so the customer becomes eligible.
    client.post("/cart/add", json={"product_id": review_product_id, "quantity": 1}, headers=auth)
    review_order_id = client.post("/checkout?payment_method=cash", headers=auth).json()["order_id"]
    client.post(f"/payments/cash/confirm/{review_order_id}", headers=staff_auth)
    client.put(f"/orders/{review_order_id}/status?status=shipped", headers=staff_auth)
    client.put(f"/orders/{review_order_id}/status?status=delivered", headers=staff_auth)

    elig = client.get(f"/products/{review_product_id}/reviews/mine", headers=auth)
    check("eligible to review once the order has been delivered",
          elig.status_code == 200 and elig.json()["can_review"] is True, elig.text)

    r = client.post("/reviews", json={"product_id": review_product_id, "rating": 4,
                                       "comment": "Solid product, works as advertised."},
                    headers=auth)
    check("the customer submits a review, starting pending",
          r.status_code == 201 and r.json()["status"] == "pending" and r.json()["rating"] == 4, r.text)
    review_id = r.json()["id"]

    check("a second review on the same product is refused",
          client.post("/reviews", json={"product_id": review_product_id, "rating": 3},
                      headers=auth).status_code == 409)
    elig = client.get(f"/products/{review_product_id}/reviews/mine", headers=auth)
    check("eligibility now reflects the existing (pending) review",
          elig.status_code == 200 and elig.json()["can_review"] is False
          and elig.json()["review"]["id"] == review_id, elig.text)

    check("a pending review doesn't appear on the product page yet",
          client.get(f"/products/{review_product_id}/reviews").json()["total_reviews"] == 0)
    check("customers cannot open the moderation queue",
          client.get("/reviews/all", headers=auth).status_code == 403)
    queue = client.get("/reviews/all", params={"status": "pending"}, headers=staff_auth)
    check("staff see the pending review with the reviewer's identity",
          queue.status_code == 200
          and any(x["id"] == review_id and x["user_email"] == CUSTOMER_EMAIL for x in queue.json()),
          queue.text[:200])

    r = client.post(f"/reviews/{review_id}/approve", headers=staff_auth)
    check("staff approve the review", r.status_code == 200 and r.json()["status"] == "approved", r.text)

    page = client.get(f"/products/{review_product_id}/reviews")
    check("the approved review now appears on the product page with the aggregate",
          page.status_code == 200 and page.json()["total_reviews"] == 1
          and page.json()["average_rating"] == 4.0
          and any(x["id"] == review_id for x in page.json()["items"]), page.text[:200])
    product = client.get(f"/products/{review_product_id}").json()
    check("the product's own average_rating/review_count match the same numbers",
          product["average_rating"] == 4.0 and product["review_count"] == 1, str(product)[:200])

    # A second reviewer, rating higher, to check sort=top vs sort=recent and averaging.
    client.post("/cart/add", json={"product_id": review_product_id, "quantity": 1}, headers=other_auth)
    review_order2_id = client.post("/checkout?payment_method=cash", headers=other_auth).json()["order_id"]
    client.post(f"/payments/cash/confirm/{review_order2_id}", headers=staff_auth)
    client.put(f"/orders/{review_order2_id}/status?status=shipped", headers=staff_auth)
    client.put(f"/orders/{review_order2_id}/status?status=delivered", headers=staff_auth)
    r = client.post("/reviews", json={"product_id": review_product_id, "rating": 5}, headers=other_auth)
    review2_id = r.json()["id"]
    client.post(f"/reviews/{review2_id}/approve", headers=staff_auth)

    top = client.get(f"/products/{review_product_id}/reviews", params={"sort": "top"})
    check("sort=top ranks the 5-star review first, aggregate over both",
          top.json()["items"][0]["id"] == review2_id
          and top.json()["average_rating"] == 4.5 and top.json()["total_reviews"] == 2, top.text[:200])
    recent = client.get(f"/products/{review_product_id}/reviews", params={"sort": "recent"})
    check("sort=recent (default) puts the newest review first",
          recent.json()["items"][0]["id"] == review2_id, recent.text[:200])

    r = client.post(f"/reviews/{review2_id}/reject", headers=admin_auth)
    check("staff can reject a review instead of approving it",
          r.status_code == 200 and r.json()["status"] == "rejected", r.text)
    after_reject = client.get(f"/products/{review_product_id}/reviews").json()
    check("a rejected review drops back out of the product page and the average",
          after_reject["total_reviews"] == 1 and after_reject["average_rating"] == 4.0,
          str(after_reject)[:200])
    check("an unknown review id 404s on approve/reject",
          client.post("/reviews/999999/approve", headers=staff_auth).status_code == 404)

    client.delete(f"/orders/{review_order_id}", headers=admin_auth)
    client.delete(f"/orders/{review_order2_id}", headers=admin_auth)

    # ---- Display numbers: every department counts 1, 2, 3 with no gaps ----
    # Raw ids are AUTO_INCREMENT and keep the holes left by deleted rows;
    # these numbers are what people quote, so they must stay unbroken.
    with SessionLocal() as _db:
        for table, column in (("users", "customer_number"), ("orders", "order_number"),
                              ("payments", "payment_number"), ("return_requests", "return_number")):
            rows = _db.execute(text(
                f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL ORDER BY id")).fetchall()
            numbers = [row[1] for row in rows]
            # Numbers are handed out 1, 2, 3... in creation order and never
            # reused. A number can be missing from this list only because the
            # row was deleted — renumbering the survivors would rewrite
            # invoices and emails that already quote the old number.
            check(f"{table}.{column} is unique and rises with creation order",
                  len(set(numbers)) == len(numbers) and numbers == sorted(numbers)
                  and (not numbers or min(numbers) >= 1),
                  f"{numbers[:5]}...{numbers[-5:]}" if numbers else "none assigned")
            counter = _db.execute(text("SELECT value FROM sequences WHERE name = :n"),
                                  {"n": column}).scalar()
            check(f"the {column} counter is at least the highest number in use",
                  counter >= (numbers[-1] if numbers else 0),
                  f"counter={counter} highest={numbers[-1:]}")

        invoice_numbers = [row[0] for row in _db.execute(
            text("SELECT invoice_number FROM invoices ORDER BY id"))]
        parsed = [int(n.split("-")[-1]) for n in invoice_numbers]
        check("invoice numbers are unique and rise with creation order",
              len(set(parsed)) == len(parsed) and parsed == sorted(parsed), str(invoice_numbers[:3]))

    # Each new row takes exactly the next number from the counter — never a
    # jump, and never a number that was already handed out (even to a row
    # that has since been deleted).
    def counter_value(name):
        with SessionLocal() as _db:
            return _db.execute(text("SELECT value FROM sequences WHERE name = :n"),
                               {"n": name}).scalar() or 0

    before_payment, before_order = counter_value("payment_number"), counter_value("order_number")
    client.post("/cart/add", json={"product_id": in_stock_product(), "quantity": 1}, headers=auth)
    numbered_order = client.post("/checkout?payment_method=cash", headers=auth).json()["order_id"]
    order_row = client.get(f"/orders/{numbered_order}", headers=auth).json()
    payment = client.get(f"/payments/{numbered_order}", headers=auth).json()
    check("a new order takes exactly the next order number",
          order_row["order_number"] == before_order + 1,
          f'{order_row["order_number"]} after counter {before_order}')
    check("its payment takes exactly the next payment number",
          payment["payment_number"] == before_payment + 1,
          f'{payment["payment_number"]} after counter {before_payment}')
    check("both counters advanced by exactly one",
          counter_value("order_number") == before_order + 1
          and counter_value("payment_number") == before_payment + 1)
    client.delete(f"/orders/{numbered_order}", headers=admin_auth)

    # ---- Production hardening ----
    r = client.get("/health")
    check("security headers on every response",
          r.headers.get("x-content-type-options") == "nosniff"
          and r.headers.get("x-frame-options") == "DENY"
          and r.headers.get("referrer-policy") == "same-origin", str(dict(r.headers)))

    from fastapi import FastAPI as _FastAPI
    from app.hardening import RateLimitMiddleware as _RateLimit, check_production_config as _check_prod

    _limited = _FastAPI()
    _limited.add_middleware(_RateLimit, paths=("/auth/login",), limit=3, window_seconds=60)

    @_limited.post("/auth/login")
    def _fake_login():
        return {"ok": True}

    @_limited.post("/auth/other")
    def _other():
        return {"ok": True}

    with TestClient(_limited) as _c:
        codes = [_c.post("/auth/login", json={}).status_code for _ in range(4)]
        check("auth endpoints rate-limit repeated attempts",
              codes[:3] == [200, 200, 200] and codes[3] == 429, str(codes))
        blocked = _c.post("/auth/login", json={})
        check("the 429 says when to retry", blocked.headers.get("retry-after", "").isdigit()
              and "Try again" in blocked.json()["detail"], blocked.text)
        check("other endpoints are unaffected", _c.post("/auth/other", json={}).status_code == 200)

    # The production guard refuses dev secrets rather than serving with them.
    from unittest.mock import patch as _hp
    with _hp.object(settings, "APP_ENV", "production"), _hp.object(settings, "AUTO_CREATE_SCHEMA", False):
        with _hp.object(settings, "JWT_SECRET_KEY", "dev-only-insecure-secret-change-me-in-production-0123456789"):
            try:
                _check_prod()
                check("production refuses the default JWT secret", False, "it started anyway")
            except RuntimeError as exc:
                check("production refuses the default JWT secret", "JWT_SECRET_KEY" in str(exc), str(exc))
        with _hp.object(settings, "CORS_ORIGINS", ["*"]):
            try:
                _check_prod()
                check("production refuses wildcard CORS", False, "it started anyway")
            except RuntimeError as exc:
                check("production refuses wildcard CORS", "CORS_ORIGINS" in str(exc), str(exc))
        try:
            _check_prod()
            check("a correctly configured production start is allowed", True)
        except RuntimeError as exc:
            check("a correctly configured production start is allowed", False, str(exc))

    # ---- Admin panel APIs ----
    r = client.get("/admin/analytics", headers=admin_auth)
    stats = r.json()
    check("admin analytics", r.status_code == 200 and len(stats["trend"]) == 30, r.text[:300])
    k = stats["kpis"]
    check("analytics KPIs are consistent",
          k["total_orders"] == sum(stats["orders_by_status"].values())
          and k["total_revenue"] >= co["amount"] and k["paid_orders"] >= 1
          and k["average_order_value"] > 0, str(k))
    check("analytics trend covers today's orders", stats["trend"][-1]["orders"] >= 1, str(stats["trend"][-1]))
    check("analytics top products and categories come from real sales",
          len(stats["top_products"]) >= 1 and len(stats["sales_by_category"]) >= 1
          and all(p["units_sold"] > 0 for p in stats["top_products"]), str(stats["top_products"])[:300])
    check("analytics reports roles and email delivery",
          set(stats["users_by_role"]) == {"admin", "staff", "customer"}
          and stats["emails"]["total"] >= 1, str(stats["emails"]))
    check("analytics window is adjustable",
          len(client.get("/admin/analytics?days=7", headers=admin_auth).json()["trend"]) == 7)
    check("staff cannot see analytics", client.get("/admin/analytics", headers=staff_auth).status_code == 403)
    check("customer cannot see analytics", client.get("/admin/analytics", headers=auth).status_code == 403)
    r = client.get("/admin/users", params={"search": f"smoke-customer-{RUN_ID}"}, headers=admin_auth)
    users = r.json()
    check("admin user directory with order stats",
          r.status_code == 200 and len(users) == 1 and users[0]["orders"] >= 1
          and users[0]["total_spent"] >= co["amount"], r.text)
    check("filter users by role",
          all(u["role"] == "staff" for u in client.get("/admin/users?role=staff", headers=admin_auth).json()))
    check("staff cannot list users", client.get("/admin/users", headers=staff_auth).status_code == 403)
    r = client.get("/admin/emails?status=failed", headers=admin_auth)
    check("admin email log filters by delivery status",
          r.status_code == 200 and all(e["status"] == "failed" for e in r.json()), r.text[:200])
    check("admin email log shows who each email went to",
          any(e["user_name"] == "Smoke Customer" for e in client.get("/admin/emails", headers=admin_auth).json()))

    # ---- Invoices ----
    r = client.get("/invoices", headers=auth)
    check("customer sees own invoices", r.status_code == 200 and len(r.json()) >= 1, r.text)
    # Pick the invoice for *this* order rather than assuming it sorts first —
    # several orders get invoiced within the same second during this run, so
    # "newest first" is ambiguous and [0] made the assertion flaky.
    invoice = next((i for i in r.json() if i["order_id"] == order_id), None)
    check("invoice matches paid order",
          invoice is not None and invoice["total"] == co["amount"]
          and invoice["invoice_number"].startswith("INV-"), str(r.json()))
    r = client.get(f"/invoices/{invoice['id']}", headers=auth)
    check("customer reads own invoice", r.status_code == 200)
    check("customer denied /invoices/all", client.get("/invoices/all", headers=auth).status_code == 403)
    check("staff denied /invoices/all", client.get("/invoices/all", headers=staff_auth).status_code == 403)
    r = client.get("/invoices/all", headers=admin_auth)
    check("admin sees everyone's invoices",
          r.status_code == 200 and any(i["user_email"] == CUSTOMER_EMAIL for i in r.json()), r.text)
    r = client.get(f"/invoices/{invoice['id']}", headers=admin_auth)
    check("admin reads any customer's invoice", r.status_code == 200)

    # ---- Admin oversight: payments and orders of every customer ----
    check("customer denied /payments/all", client.get("/payments/all", headers=auth).status_code == 403)
    r = client.get("/payments/all", headers=admin_auth)
    check("admin sees everyone's payments",
          r.status_code == 200 and any(p["user_email"] == CUSTOMER_EMAIL for p in r.json()), r.text)
    r = client.get("/orders/all", headers=admin_auth)
    check("admin order list shows customer identity",
          r.status_code == 200 and all("user_email" in o for o in r.json()), r.text)
    r = client.get("/roles", headers=admin_auth)
    check("roles table (admin) — exactly 3 roles defined",
          r.status_code == 200 and {x["name"] for x in r.json()} == {"admin", "staff", "customer"}, r.text)
    check("customer denied /roles", client.get("/roles", headers=auth).status_code == 403)

    # ---- Admin can shop and buy like anyone ----
    r = client.post("/cart/add", json={"product_id": in_stock_product(), "quantity": 1}, headers=admin_auth)
    check("admin can add to cart", r.status_code == 201, r.text)
    r = client.post("/checkout", headers=admin_auth)
    check("admin can checkout", r.status_code == 200, r.text)
    admin_order = r.json()["order_id"]
    r = client.post(f"/payments/confirm/{admin_order}", headers=admin_auth)
    check("admin can pay", r.status_code == 200 and r.json()["status"] == "succeeded", r.text)
    check("confirming an already-paid order is rejected",
          client.post(f"/payments/confirm/{admin_order}", headers=admin_auth).status_code == 400)
    # Staff shop too — same cart/checkout/pay path as any customer.
    r = client.post("/cart/add", json={"product_id": 3, "quantity": 1}, headers=staff_auth)
    check("staff can add to cart", r.status_code == 201, r.text)
    r = client.post("/checkout?payment_method=cash", headers=staff_auth)
    check("staff can checkout", r.status_code == 200, r.text)
    staff_order = r.json()["order_id"]
    check("staff sees their own purchase in their order list",
          any(o["id"] == staff_order for o in client.get("/orders", headers=staff_auth).json()))
    r = client.post(f"/payments/confirm/{staff_order}", headers=admin_auth)
    check("staff's own order can be confirmed and invoiced",
          r.status_code == 200 and r.json()["status"] == "succeeded", r.text)

    r = client.get("/invoices", headers=admin_auth)
    check("admin gets own invoice after buying", any(i["order_id"] == admin_order for i in r.json()), r.text)

    # ---- Cash on delivery: checkout, transaction id, staff confirm ----
    r = client.post("/cart/add", json={"product_id": 5, "quantity": 1}, headers=auth)
    check("cash: add to cart", r.status_code == 201, r.text)
    r = client.post("/checkout?payment_method=cash", headers=auth)
    check("cash checkout", r.status_code == 200, r.text)
    cash = r.json()
    check("cash transaction id issued",
          cash["payment_provider"] == "cash" and cash["transaction_id"].startswith("CASH-"), str(cash))
    cash_order = cash["order_id"]
    r = client.get(f"/orders/{cash_order}", headers=auth)
    check("order exposes payment method + txn id",
          r.json()["payment"]["payment_method"] == "cash"
          and r.json()["payment"]["transaction_id"] == cash["transaction_id"], r.text)
    check("customer cannot confirm cash",
          client.post(f"/payments/cash/confirm/{cash_order}", headers=auth).status_code == 403)
    r = client.post(f"/payments/cash/confirm/{cash_order}", headers=staff_auth)
    check("staff confirms cash received", r.status_code == 200 and r.json()["status"] == "succeeded", r.text)
    check("cash order paid + invoiced",
          client.get(f"/orders/{cash_order}", headers=auth).json()["order_status"] == "paid"
          and any(i["order_id"] == cash_order for i in client.get("/invoices", headers=auth).json()))
    check("double cash confirm rejected",
          client.post(f"/payments/cash/confirm/{cash_order}", headers=staff_auth).status_code == 400)

    # ---- Admin deletes payments and orders ----
    r = client.post("/cart/add", json={"product_id": 9, "quantity": 2}, headers=auth)
    r = client.post("/checkout?payment_method=cash", headers=auth)
    del_order = r.json()["order_id"]
    del_order_number = client.get(f"/orders/{del_order}", headers=auth).json()["order_number"]
    payment_id = client.get(f"/payments/{del_order}", headers=auth).json()["id"]
    check("customer cannot delete payment",
          client.delete(f"/payments/{payment_id}", headers=auth).status_code == 403)
    check("staff cannot delete payment",
          client.delete(f"/payments/{payment_id}", headers=staff_auth).status_code == 403)
    check("admin deletes payment", client.delete(f"/payments/{payment_id}", headers=admin_auth).status_code == 204)
    check("payment gone", client.get(f"/payments/{del_order}", headers=auth).status_code == 404)

    stock_before_del = client.get("/products/9").json()["stock"]
    check("customer cannot delete order",
          client.delete(f"/orders/{del_order}", headers=auth).status_code == 403)
    check("admin deletes order", client.delete(f"/orders/{del_order}", headers=admin_auth).status_code == 204)
    check("order gone", client.get(f"/orders/{del_order}", headers=auth).status_code == 404)
    check("stock restored after order delete",
          client.get("/products/9").json()["stock"] == stock_before_del + 2)

    # Deleting an order must NOT free up its order_number for reuse — the next
    # order placed should continue the sequence, not fill the gap. This is the
    # whole point of a dedicated sequence table over MySQL's own AUTO_INCREMENT.
    r = client.post("/cart/add", json={"product_id": 1, "quantity": 1}, headers=auth)
    r = client.post("/checkout?payment_method=cash", headers=auth)
    next_order_id = r.json()["order_id"]
    next_order_number = client.get(f"/orders/{next_order_id}", headers=auth).json()["order_number"]
    check("order_number is gapless and never reused after a delete",
          next_order_number == del_order_number + 1,
          f"deleted order was #{del_order_number}, next order got #{next_order_number}")

    # ---- Google ID token clock-skew tolerance (regression test) ----
    # Found live: a real Google login failed with jwt.exceptions.ImmatureSignature
    # Error ("not yet valid (iat)") on a machine whose clock ran ~8s behind —
    # PyJWT's default leeway is 0, so any negative drift rejects a freshly
    # issued token. Builds a genuine RS256-signed token (no network) with iat
    # a few seconds in the future to prove _verify_google_id_token now tolerates it.
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from datetime import datetime as _dt, timedelta, timezone
    import jwt as _pyjwt
    from app.routers import auth as auth_module

    _rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _pub_pem = _rsa_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    _now = _dt.now(timezone.utc)
    _drifted_token = _pyjwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": settings.GOOGLE_CLIENT_ID or "test-client-id",
            "email": "clock-drift-test@example.com",
            "email_verified": True,
            "name": "Clock Drift Test",
            "iat": _now + timedelta(seconds=5),  # "issued" slightly in the future
            "exp": _now + timedelta(hours=1),
        },
        _rsa_key,
        algorithm="RS256",
    )

    class _FakeSigningKey:
        key = _pub_pem

    with _patch(
        "jwt.PyJWKClient.get_signing_key_from_jwt",
        return_value=_FakeSigningKey(),
    ), _patch.object(settings, "GOOGLE_CLIENT_ID", settings.GOOGLE_CLIENT_ID or "test-client-id"):
        claims = auth_module._verify_google_id_token(_drifted_token)
    check("Google id token with a few seconds of future iat is tolerated (leeway)",
          claims["email"] == "clock-drift-test@example.com", str(claims))

    # ---- Unknown API paths answer with JSON, not the SPA's HTML shell ----
    # The SPA catch-all used to swallow every unmatched GET and return
    # index.html with a 200, so a slightly-wrong API call looked like "the API
    # returned HTML instead of JSON".
    r = client.get("/auth/not-a-real-endpoint")
    check("unknown path under an API prefix returns JSON, not HTML",
          r.status_code == 404 and r.headers["content-type"].startswith("application/json"),
          f"{r.status_code} {r.headers.get('content-type')} {r.text[:80]}")
    r = client.get("/orders/nope/deeper/still")
    check("deep unknown API path returns JSON too",
          r.status_code == 404 and r.headers["content-type"].startswith("application/json"),
          f"{r.status_code} {r.headers.get('content-type')} {r.text[:80]}")
    # ...while a genuine SPA route still gets the app shell.
    r = client.get("/some/client-side/route")
    check("non-API paths still serve the SPA",
          r.status_code == 200 and r.headers["content-type"].startswith("text/html"),
          f"{r.status_code} {r.headers.get('content-type')}")

    # ---- Social login endpoints exist (503 until provider keys are configured) ----
    r = client.post("/auth/social/google", json={"id_token": "x"})
    check("google endpoint present", r.status_code in (401, 503), r.text)
    r = client.post("/auth/social/facebook", json={"access_token": "x"})
    check("facebook endpoint present", r.status_code in (401, 503), r.text)
    # 404 without the SPA catch-all; 405 with it (catch-all serves GET only)
    check("auth0 endpoint removed", client.post("/auth/social/auth0", json={"id_token": "x"}).status_code in (404, 405))

    # ---- OAuth redirect flow (redirect URLs for ngrok) ----
    r = client.get("/auth/google/login", follow_redirects=False)
    check("google oauth redirect",
          r.status_code in (302, 307) and "accounts.google.com" in r.headers.get("location", "")
          and "auth%2Fgoogle%2Fcallback" in r.headers.get("location", "")
          or r.status_code == 503,  # not configured yet
          r.text)
    r = client.get("/auth/facebook/login", follow_redirects=False)
    check("facebook oauth redirect",
          r.status_code in (302, 307) and "facebook.com" in r.headers.get("location", "")
          and "auth%2Ffacebook%2Fcallback" in r.headers.get("location", "")
          or r.status_code == 503,
          r.text)
    r = client.get("/auth/google/callback?code=bogus&state=bogus", follow_redirects=False)
    check("google callback rejects bad state",
          r.status_code in (302, 307) and "social_error" in r.headers.get("location", ""), r.text)

    # ?json=1 opt-in: the callback should raise an HTTP error (JSON body) on
    # failure instead of redirecting, when the login was started with it.
    from app.security import create_oauth_state
    json_state = create_oauth_state(want_json=True)
    r = client.get(f"/auth/google/callback?code=bogus&state={json_state}", follow_redirects=False)
    check("google callback (json mode) returns a JSON error instead of a redirect",
          r.status_code == 401 and "detail" in r.json(), r.text)

    # Facebook mock-email fallback: an account with no email gets a stable,
    # schema-valid synthetic address rather than being blocked from logging in.
    from app.routers.auth import _get_or_create_social_user, _mock_email
    mock_email = _mock_email("facebook", "999999")
    # Assert the properties that matter (stable, unique per account, accepted by
    # EmailStr) rather than one hardcoded domain, so changing the placeholder
    # domain doesn't break the suite.
    from pydantic import TypeAdapter, EmailStr as _EmailStr
    check("mock email is unique per facebook account and passes EmailStr",
          "999999" in mock_email
          and mock_email == _mock_email("facebook", "999999")
          and mock_email != _mock_email("facebook", "888888")
          and TypeAdapter(_EmailStr).validate_python(mock_email) == mock_email,
          mock_email)
    with SessionLocal() as fb_db:
        fb_user = _get_or_create_social_user(fb_db, mock_email, "No Email User", "facebook")
        fb_user_id, fb_user_email, fb_user_provider = fb_user.id, fb_user.email, fb_user.auth_provider
    created_user_ids.append(fb_user_id)
    check("facebook user with no real email was created with the synthetic one",
          fb_user_email == mock_email and fb_user_provider == "facebook", fb_user_email)
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {create_access_token(fb_user_id, 'customer')}"})
    check("that user's profile round-trips through the API (EmailStr accepts the synthetic address)",
          r.status_code == 200 and r.json()["email"] == mock_email, r.text)
    from app.models import User as _FbUser
    from app.services.email_service import send_email as _send_email
    from unittest.mock import patch as _fb_patch
    with _fb_patch.object(settings, "EMAIL_BACKEND", "smtp"),             _fb_patch("app.services.email_service.smtp_send") as fb_smtp, SessionLocal() as fb_db:
        fb_status = _send_email(fb_db, fb_db.get(_FbUser, fb_user_id), "Hello", "body").status
    check("nothing is handed to SMTP for a placeholder address", not fb_smtp.called)
    check("emails to a placeholder address are recorded as skipped, never sent",
          fb_status == "skipped", fb_status)

    print(f"\nAll {passed} checks passed.")
finally:
    cleanup(created_user_ids)
    restore_sequences(sequences_before)
    restore_products(products_before)
    print(f"Cleaned up {len(created_user_ids)} smoke-test user(s) and their data — MySQL left as it was, "
          f"including order/invoice/customer sequence counters and every product's stock and popularity.")
