import hashlib
import hmac
import json
import time

from sqlalchemy import text

from app.database import SessionLocal
from tests.conftest import add_to_cart, checkout, make_user

WEBHOOK_SECRET = "whsec_test_secret_for_unit_tests"


def signed_webhook(client, event: dict, secret: str = WEBHOOK_SECRET):
    """POST an event the way Stripe does: HMAC-SHA256 over '<timestamp>.<payload>'."""
    payload = json.dumps(event)
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    return client.post(
        "/payments/webhook",
        content=payload,
        headers={"Stripe-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"},
    )


def session_completed(transaction_id: str, order_id: int, event_id: str = "evt_test_1") -> dict:
    return {
        "id": event_id,
        "object": "event",
        "type": "checkout.session.completed",
        "data": {"object": {"id": transaction_id, "object": "checkout.session", "metadata": {"order_id": str(order_id)}}},
    }


def payment_status(order_id: int) -> str:
    with SessionLocal() as db:
        return db.execute(text("SELECT status FROM payments WHERE order_id = :o"), {"o": order_id}).scalar()


def invoice_count(order_id: int) -> int:
    with SessionLocal() as db:
        return db.execute(text("SELECT COUNT(*) FROM invoices WHERE order_id = :o"), {"o": order_id}).scalar()


def stock_of(product_id: int) -> int:
    with SessionLocal() as db:
        return db.execute(text("SELECT stock FROM products WHERE id = :p"), {"p": product_id}).scalar()


def test_stripe_checkout_returns_a_checkout_url_in_mock_mode(client, customer, product_id):
    add_to_cart(client, customer["headers"], product_id, 1)
    data = checkout(client, customer["headers"], "stripe")
    assert data["payment_provider"] == "stripe-mock"
    assert data["checkout_url"]
    assert payment_status(data["order_id"]) == "pending"


def test_checkout_reduces_stock_and_empties_cart(client, customer, product_id):
    before = stock_of(product_id)
    add_to_cart(client, customer["headers"], product_id, 2)
    checkout(client, customer["headers"], "cash")
    assert stock_of(product_id) == before - 2
    assert client.get("/cart", headers=customer["headers"]).json()["items"] == []


def test_cart_refuses_more_than_stock(client, customer, product_id):
    add_to_cart(client, customer["headers"], product_id, 1)
    r = client.put("/cart/update", json={"product_id": product_id, "quantity": 10_000}, headers=customer["headers"])
    assert r.status_code == 400


def test_checkout_rechecks_stock_if_it_dropped_after_adding_to_cart(client, customer, product_id):
    """Someone else bought the stock between 'add to cart' and 'pay': checkout must refuse, not oversell."""
    original = stock_of(product_id)
    add_to_cart(client, customer["headers"], product_id, 3)
    try:
        with SessionLocal() as db:
            db.execute(text("UPDATE products SET stock = 1 WHERE id = :p"), {"p": product_id})
            db.commit()
        r = client.post("/checkout?payment_method=cash", headers=customer["headers"])
        assert r.status_code == 400
        assert "Insufficient stock" in r.json()["detail"]
        assert stock_of(product_id) == 1  # nothing was reserved
    finally:
        with SessionLocal() as db:
            db.execute(text("UPDATE products SET stock = :s WHERE id = :p"), {"s": original, "p": product_id})
            db.commit()


def test_empty_cart_cannot_check_out(client, customer):
    assert client.post("/checkout", headers=customer["headers"]).status_code == 400


def test_webhook_with_bad_signature_is_rejected(client, customer, product_id):
    add_to_cart(client, customer["headers"], product_id)
    data = checkout(client, customer["headers"])
    r = signed_webhook(client, session_completed(data["transaction_id"], data["order_id"]), secret="whsec_wrong")
    assert r.status_code == 400
    assert payment_status(data["order_id"]) == "pending"


def test_signed_webhook_marks_order_paid_and_issues_one_invoice(client, customer, product_id):
    add_to_cart(client, customer["headers"], product_id)
    data = checkout(client, customer["headers"])

    r = signed_webhook(client, session_completed(data["transaction_id"], data["order_id"]))
    assert r.status_code == 200, r.text
    assert r.json()["matched"] is True
    assert payment_status(data["order_id"]) == "succeeded"
    assert invoice_count(data["order_id"]) == 1


def test_duplicate_webhook_delivery_is_a_no_op(client, customer, product_id):
    """Stripe retries events; a repeat must not create a second invoice or re-notify."""
    add_to_cart(client, customer["headers"], product_id)
    data = checkout(client, customer["headers"])
    event = session_completed(data["transaction_id"], data["order_id"])

    assert signed_webhook(client, event).json().get("duplicate") is None
    notifications_before = len(client.get("/notifications", headers=customer["headers"]).json())

    again = signed_webhook(client, event)
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    assert invoice_count(data["order_id"]) == 1
    assert len(client.get("/notifications", headers=customer["headers"]).json()) == notifications_before


def test_late_failure_event_cannot_undo_a_paid_order(client, customer, product_id):
    add_to_cart(client, customer["headers"], product_id)
    data = checkout(client, customer["headers"])
    signed_webhook(client, session_completed(data["transaction_id"], data["order_id"]))

    failed = {
        "id": "evt_test_failed",
        "object": "event",
        "type": "payment_intent.payment_failed",
        "data": {"object": {"id": data["transaction_id"], "object": "payment_intent",
                            "metadata": {"order_id": str(data["order_id"])}}},
    }
    assert signed_webhook(client, failed).status_code == 200
    assert payment_status(data["order_id"]) == "succeeded"


def test_webhook_for_unknown_payment_is_acknowledged_but_unmatched(client):
    r = signed_webhook(client, session_completed("cs_does_not_exist", 999999))
    assert r.status_code == 200
    assert r.json()["matched"] is False


def test_only_staff_can_confirm_cash_and_it_issues_an_invoice(client, customer, staff, product_id):
    add_to_cart(client, customer["headers"], product_id)
    data = checkout(client, customer["headers"], "cash")
    order_id = data["order_id"]

    assert client.post(f"/payments/cash/confirm/{order_id}", headers=customer["headers"]).status_code == 403
    assert client.post(f"/payments/cash/confirm/{order_id}", headers=staff["headers"]).status_code == 200
    assert payment_status(order_id) == "succeeded"
    assert invoice_count(order_id) == 1
    # confirming twice is refused
    assert client.post(f"/payments/cash/confirm/{order_id}", headers=staff["headers"]).status_code == 400


def test_cash_confirm_endpoint_refuses_card_orders(client, customer, staff, product_id):
    add_to_cart(client, customer["headers"], product_id)
    data = checkout(client, customer["headers"], "stripe")
    r = client.post(f"/payments/cash/confirm/{data['order_id']}", headers=staff["headers"])
    assert r.status_code == 400


def test_customers_cannot_read_each_others_payments_or_receipts(client, customer, product_id):
    add_to_cart(client, customer["headers"], product_id)
    data = checkout(client, customer["headers"])
    other = make_user(client, "customer")

    assert client.get(f"/payments/{data['order_id']}", headers=customer["headers"]).status_code == 200
    assert client.get(f"/payments/{data['order_id']}", headers=other["headers"]).status_code == 403
    assert client.get(f"/payments/receipt?order_id={data['order_id']}", headers=other["headers"]).status_code == 403


def test_only_admin_can_list_all_payments(client, customer, admin):
    assert client.get("/payments/all", headers=customer["headers"]).status_code == 403
    assert client.get("/payments/all", headers=admin["headers"]).status_code == 200
