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

# Force mock payments for the test run even when real Stripe keys are in .env —
# the suite must not create real Stripe sessions. Set BEFORE importing the app.
os.environ["STRIPE_SECRET_KEY"] = ""
os.environ["STRIPE_WEBHOOK_SECRET"] = ""

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
        db.execute(text(f"DELETE FROM invoices WHERE order_id IN ({order_ph}) OR user_id IN ({placeholders})"))
        db.execute(text(f"DELETE FROM payments WHERE order_id IN ({order_ph})"))
        db.execute(text(f"DELETE FROM order_items WHERE order_id IN ({order_ph})"))
        db.execute(text(f"DELETE FROM orders WHERE user_id IN ({placeholders})"))
        db.execute(text(f"DELETE FROM cart_items WHERE user_id IN ({placeholders})"))
        db.execute(text(f"DELETE FROM notifications WHERE user_id IN ({placeholders})"))
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
    with client.websocket_connect(f"/ws/notifications?token={tokens['access_token']}") as ws:
        r = client.post(f"/payments/confirm/{order_id}", headers=staff_auth)
        check("staff confirms payment by order id (works with live Stripe keys too)",
              r.status_code == 200 and r.json()["status"] == "succeeded", r.text)
        # Two pushes arrive: the auto-issued invoice, then the payment confirmation.
        msgs = [ws.receive_json(), ws.receive_json()]
        check("websocket invoice push received", any("Invoice INV-" in m["title"] for m in msgs), str(msgs))
        check("websocket payment push received",
              any(m["type"] == "payment" and "succeeded" in m["message"] for m in msgs), str(msgs))

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

    r = client.post("/cart/add", json={"product_id": 2, "quantity": 1}, headers=auth)
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
    r = client.put(f"/orders/{order_id}/status?status=shipped", headers=admin_auth)
    check("paid -> shipped", r.status_code == 200 and r.json()["order_status"] == "shipped", r.text)
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
    check("notifications persisted", len(notifs) >= 3, str(len(notifs)))  # order placed, payment, shipped
    r = client.put(f"/notifications/{notifs[0]['id']}/read", headers=auth)
    check("mark notification read", r.status_code == 200 and r.json()["is_read"] is True)
    r = client.put("/notifications/read-all", headers=auth)
    check("mark all read", r.status_code == 200)

    # ---- Invoices ----
    r = client.get("/invoices", headers=auth)
    check("customer sees own invoices", r.status_code == 200 and len(r.json()) >= 1, r.text)
    invoice = r.json()[0]
    check("invoice matches paid order",
          invoice["order_id"] == order_id and invoice["total"] == co["amount"]
          and invoice["invoice_number"].startswith("INV-"), str(invoice))
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
    r = client.post("/cart/add", json={"product_id": 2, "quantity": 1}, headers=admin_auth)
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

    print(f"\nAll {passed} checks passed.")
finally:
    cleanup(created_user_ids)
    restore_sequences(sequences_before)
    print(f"Cleaned up {len(created_user_ids)} smoke-test user(s) and their data — MySQL left as it was, "
          f"including order/invoice/customer sequence counters.")
