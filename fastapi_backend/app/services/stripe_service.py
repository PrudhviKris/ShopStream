"""Stripe integration.

Runs in two modes:
- Live mode: STRIPE_SECRET_KEY is set -> creates a real Checkout Session + PaymentIntent.
- Mock mode: no key configured -> returns a deterministic mock session so the
  full checkout flow can be developed and tested without Stripe credentials.
"""
import uuid
from typing import Optional

from ..config import settings

try:
    import stripe as _stripe
except ImportError:  # stripe SDK optional in mock mode
    _stripe = None

if _stripe and settings.STRIPE_SECRET_KEY:
    _stripe.api_key = settings.STRIPE_SECRET_KEY


def is_live() -> bool:
    return bool(_stripe and settings.STRIPE_SECRET_KEY)


def create_checkout_session(order_id: int, amount: float, currency: str, line_items: list) -> dict:
    """Returns {transaction_id, checkout_url, client_secret}."""
    if not is_live():
        return {
            "transaction_id": f"mock_cs_{uuid.uuid4().hex[:16]}",
            "checkout_url": f"http://localhost:8000/mock-checkout/{order_id}",
            "client_secret": f"mock_pi_{uuid.uuid4().hex[:16]}_secret",
        }

    session = _stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[
            {
                "price_data": {
                    "currency": currency,
                    "unit_amount": int(round(item["unit_price"] * 100)),
                    "product_data": {"name": item["name"]},
                },
                "quantity": item["quantity"],
            }
            for item in line_items
        ],
        metadata={"order_id": str(order_id)},
        success_url=settings.CHECKOUT_SUCCESS_URL + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=settings.CHECKOUT_CANCEL_URL,
    )
    return {
        "transaction_id": session.id,
        "checkout_url": session.url,
        "client_secret": None,
    }


def create_payment_intent(order_id: int, amount: float, currency: str) -> dict:
    """Alternative flow for custom payment UIs (Stripe Elements)."""
    if not is_live():
        return {
            "transaction_id": f"mock_pi_{uuid.uuid4().hex[:16]}",
            "client_secret": f"mock_pi_{uuid.uuid4().hex[:16]}_secret",
        }
    intent = _stripe.PaymentIntent.create(
        amount=int(round(amount * 100)),
        currency=currency,
        metadata={"order_id": str(order_id)},
        automatic_payment_methods={"enabled": True},
    )
    return {"transaction_id": intent.id, "client_secret": intent.client_secret}


def construct_webhook_event(payload: bytes, sig_header: Optional[str]):
    """Verify and parse a Stripe webhook. Raises ValueError on bad signature/payload."""
    if not (_stripe and settings.STRIPE_WEBHOOK_SECRET):
        raise ValueError("Stripe webhook secret not configured")
    try:
        return _stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except Exception as exc:
        raise ValueError(str(exc))
