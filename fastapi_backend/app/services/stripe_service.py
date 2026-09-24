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


def create_checkout_session(
    order_id: int,
    amount: float,
    currency: str,
    line_items: list,
    return_base: Optional[str] = None,
) -> dict:
    """Returns {transaction_id, checkout_url, client_secret}.

    return_base is the origin the shopper is actually browsing from, so Stripe
    sends them back where they came from — a hardcoded URL breaks the moment a
    tunnel goes down or changes address.
    """
    if not is_live():
        return {
            "transaction_id": f"mock_cs_{uuid.uuid4().hex[:16]}",
            "checkout_url": f"http://localhost:8000/mock-checkout/{order_id}",
            "client_secret": f"mock_pi_{uuid.uuid4().hex[:16]}_secret",
        }

    base = (return_base or "").rstrip("/")
    success_url = f"{base}/receipt" if base else settings.CHECKOUT_SUCCESS_URL
    cancel_url = f"{base}/receipt?cancelled=1" if base else settings.CHECKOUT_CANCEL_URL

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
        success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=cancel_url,
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


def refund_payment(transaction_id: Optional[str], amount: float, currency: str) -> dict:
    """Refund a settled payment. Returns {reference, provider, live}.

    Live Stripe payments are refunded through the API; cash, mock-mode and
    anything Stripe can't refund get a locally generated reference so the
    money still has an audit trail. Raises only when Stripe itself rejects
    the refund, so the caller can tell the operator.
    """
    reference_prefix = "REFUND"
    if not is_live() or not (transaction_id or "").startswith(("cs_", "pi_")):
        return {
            "reference": f"{reference_prefix}-{uuid.uuid4().hex[:12].upper()}",
            "provider": "manual",
            "live": False,
        }

    intent_id = transaction_id
    if transaction_id.startswith("cs_"):
        # A Checkout Session isn't refundable itself — its PaymentIntent is.
        session = _stripe.checkout.Session.retrieve(transaction_id)
        intent_id = getattr(session, "payment_intent", None)
        if intent_id is None:
            raise RuntimeError(f"Stripe session {transaction_id} has no payment to refund.")
        if not isinstance(intent_id, str):
            intent_id = intent_id.id

    refund = _stripe.Refund.create(
        payment_intent=intent_id,
        # Stripe counts in the currency's smallest unit (paise for INR).
        amount=int(round(amount * 100)),
        reason="requested_by_customer",
    )
    return {"reference": refund.id, "provider": "stripe", "live": True}
