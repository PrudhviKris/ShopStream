from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Order, OrderStatus, Payment, PaymentStatus, User, UserRole
from ..schemas import PaymentOut
from ..services import stripe_service
from ..services.notification_service import notify

router = APIRouter(prefix="/payments", tags=["Payments"])


def _mark_paid(db: Session, payment: Payment) -> None:
    payment.status = PaymentStatus.succeeded
    payment.order.payment_status = PaymentStatus.succeeded
    payment.order.order_status = OrderStatus.paid
    db.commit()
    notify(
        db,
        payment.order.user_id,
        "payment",
        "Payment received",
        f"Payment of {payment.currency.upper()} {payment.amount:.2f} for order "
        f"#{payment.order_id} succeeded. Your order is confirmed!",
    )


def _mark_failed(db: Session, payment: Payment) -> None:
    payment.status = PaymentStatus.failed
    payment.order.payment_status = PaymentStatus.failed
    db.commit()
    notify(
        db,
        payment.order.user_id,
        "payment",
        "Payment failed",
        f"Payment for order #{payment.order_id} failed. Please try again.",
    )


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
    stripe_signature: str = Header(default=None, alias="Stripe-Signature"),
):
    """Stripe webhook: point your Stripe dashboard endpoint at POST /payments/webhook.

    Handles checkout.session.completed and payment_intent.succeeded/failed.
    """
    payload = await request.body()
    try:
        event = stripe_service.construct_webhook_event(payload, stripe_signature)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Webhook error: {exc}")

    obj = event["data"]["object"]
    transaction_id = obj.get("id")
    payment = db.query(Payment).filter(Payment.transaction_id == transaction_id).first()
    if payment is None:
        # Fall back to metadata order_id (PaymentIntent created from a Session, etc.)
        order_id = (obj.get("metadata") or {}).get("order_id")
        if order_id:
            payment = db.query(Payment).filter(Payment.order_id == int(order_id)).first()
    if payment is None:
        return {"received": True, "matched": False}

    if event["type"] in ("checkout.session.completed", "payment_intent.succeeded"):
        _mark_paid(db, payment)
    elif event["type"] == "payment_intent.payment_failed":
        _mark_failed(db, payment)
    return {"received": True, "matched": True}


@router.post("/mock/confirm/{order_id}", response_model=PaymentOut)
def mock_confirm_payment(
    order_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    outcome: str = "success",
):
    """Development-only endpoint: simulates the Stripe webhook when running
    in mock mode (no STRIPE_SECRET_KEY). Disabled automatically in live mode."""
    if stripe_service.is_live():
        raise HTTPException(status_code=404, detail="Not available in live mode")
    payment = db.query(Payment).filter(Payment.order_id == order_id).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.order.user_id != user.id and user.role == UserRole.customer:
        raise HTTPException(status_code=403, detail="Not your order")
    if outcome == "success":
        _mark_paid(db, payment)
    else:
        _mark_failed(db, payment)
    db.refresh(payment)
    return payment


@router.get("/{order_id}", response_model=PaymentOut)
def payment_for_order(
    order_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    payment = db.query(Payment).filter(Payment.order_id == order_id).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    order = db.get(Order, order_id)
    if order.user_id != user.id and user.role == UserRole.customer:
        raise HTTPException(status_code=403, detail="Not your order")
    return payment
