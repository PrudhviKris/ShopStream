import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import get_current_user, require_admin, require_staff_or_admin
from ..models import Invoice, Order, OrderStatus, Payment, PaymentStatus, User, UserRole
from ..schemas import AdminPaymentOut, PaymentOut
from ..services import stripe_service
from ..services.notification_service import notify
from ..services.sequence_service import next_sequence_value

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments", tags=["Payments"])


def _issue_invoice(db: Session, order: Order) -> Invoice:
    invoice_number = next_sequence_value(db, "invoice_number")
    invoice = Invoice(
        invoice_number=f"INV-{datetime.utcnow():%Y}-{invoice_number:05d}",
        order_id=order.id,
        user_id=order.user_id,
        subtotal=order.subtotal,
        tax=order.tax,
        total=order.total,
        currency=order.payment.currency if order.payment else "usd",
    )
    db.add(invoice)
    return invoice


def _mark_paid(db: Session, payment: Payment) -> None:
    payment.status = PaymentStatus.succeeded
    payment.order.payment_status = PaymentStatus.succeeded
    payment.order.order_status = OrderStatus.paid
    if db.query(Invoice).filter(Invoice.order_id == payment.order_id).first() is None:
        invoice = _issue_invoice(db, payment.order)
        db.commit()
        notify(
            db,
            payment.order.user_id,
            "payment",
            f"Invoice {invoice.invoice_number}",
            f"Invoice {invoice.invoice_number} issued for order #{payment.order_id} "
            f"({invoice.currency.upper()} {invoice.total:.2f}).",
        )
    else:
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

    try:
        obj = event["data"]["object"]
        # obj is a typed Stripe resource (e.g. checkout.Session), not a plain dict —
        # newer stripe-python raises on dict-style .get()/.items(); use attributes.
        transaction_id = obj.id
        payment = db.query(Payment).filter(Payment.transaction_id == transaction_id).first()
        if payment is None:
            # Fall back to metadata order_id (PaymentIntent created from a Session, etc.)
            metadata = obj.metadata.to_dict() if obj.metadata else {}
            order_id = metadata.get("order_id")
            if order_id:
                payment = db.query(Payment).filter(Payment.order_id == int(order_id)).first()
        if payment is None:
            return {"received": True, "matched": False}

        if event["type"] in ("checkout.session.completed", "payment_intent.succeeded"):
            _mark_paid(db, payment)
        elif event["type"] == "payment_intent.payment_failed":
            _mark_failed(db, payment)
        return {"received": True, "matched": True}
    except Exception:
        # Log the full traceback (visible in the server console) before letting
        # this surface as a 500 — Stripe retries non-2xx responses for days, so
        # a real transient failure still resolves once fixed/retried.
        logger.exception("Stripe webhook processing failed for event %s", event["id"])
        raise


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


@router.get("/all", response_model=List[AdminPaymentOut])
def all_payments(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Admin only: every customer's payments."""
    payments = (
        db.query(Payment)
        .options(joinedload(Payment.order).joinedload(Order.user))
        .order_by(Payment.created_at.desc())
        .all()
    )
    return [
        AdminPaymentOut(
            **PaymentOut.model_validate(p).model_dump(),
            user_name=p.order.user.name,
            user_email=p.order.user.email,
        )
        for p in payments
    ]


@router.post("/cash/confirm/{order_id}", response_model=PaymentOut)
def confirm_cash_payment(
    order_id: int,
    db: Session = Depends(get_db),
    _staff: User = Depends(require_staff_or_admin),
):
    """Staff/admin confirm cash was received on delivery -> order paid + invoice."""
    payment = db.query(Payment).filter(Payment.order_id == order_id).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.payment_method != "cash":
        raise HTTPException(status_code=400, detail="Not a cash-on-delivery payment")
    if payment.status == PaymentStatus.succeeded:
        raise HTTPException(status_code=400, detail="Payment already confirmed")
    _mark_paid(db, payment)
    db.refresh(payment)
    return payment


@router.delete("/{payment_id}", status_code=204)
def delete_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin only: delete a payment record. The order reverts to payment pending."""
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    order = payment.order
    order.payment_status = PaymentStatus.pending
    db.delete(payment)
    db.commit()


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
