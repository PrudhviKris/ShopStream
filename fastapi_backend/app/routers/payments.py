import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import get_current_user, require_admin, require_staff_or_admin
from ..models import Invoice, Order, OrderStatus, Payment, PaymentStatus, User, UserRole
from ..schemas import AdminPaymentOut, PaymentOut, ReceiptOut
from ..services import order_events, stripe_service
from ..services.notification_service import publish_order_status
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
    previous = payment.order.order_status.value
    payment.status = PaymentStatus.succeeded
    payment.order.payment_status = PaymentStatus.succeeded
    payment.order.order_status = OrderStatus.paid
    invoice = db.query(Invoice).filter(Invoice.order_id == payment.order_id).first()
    if invoice is None:
        invoice = _issue_invoice(db, payment.order)
    db.commit()
    db.refresh(payment)
    order_events.payment_succeeded(db, payment, invoice, previous_status=previous)


def _mark_failed(db: Session, payment: Payment) -> None:
    previous = payment.order.order_status.value
    payment.status = PaymentStatus.failed
    payment.order.payment_status = PaymentStatus.failed
    db.commit()
    db.refresh(payment)
    order_events.payment_failed(db, payment, previous_status=previous)


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


def _confirm_payment_for_order(
    db: Session, order_id: int, outcome: str, cash_only: bool = False
) -> Payment:
    """Shared logic behind the staff/admin payment-confirmation endpoints.

    Works in every mode: Stripe normally confirms itself via the webhook, but
    staff still need a manual override for when a webhook never arrives, or the
    customer paid by another route — that's the whole reason this exists.
    """
    payment = db.query(Payment).filter(Payment.order_id == order_id).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found for this order")
    if cash_only and payment.payment_method != "cash":
        raise HTTPException(status_code=400, detail="Not a cash-on-delivery payment")
    if outcome == "success":
        if payment.status == PaymentStatus.succeeded:
            raise HTTPException(status_code=400, detail="Payment already confirmed")
        _mark_paid(db, payment)
    else:
        _mark_failed(db, payment)
    db.refresh(payment)
    return payment


@router.post("/confirm/{order_id}", response_model=PaymentOut)
def confirm_payment(
    order_id: int,
    db: Session = Depends(get_db),
    _staff: User = Depends(require_staff_or_admin),
    outcome: str = Query(default="success", pattern="^(success|failed)$"),
):
    """Staff/admin: confirm (or fail) an order's payment by order id.

    Marks the payment succeeded, moves the order to `paid`, issues the invoice
    and notifies the customer — the same path the Stripe webhook takes, so a
    manually confirmed order ends up in exactly the same state as an
    automatically confirmed one. Works for Stripe and cash alike.
    """
    return _confirm_payment_for_order(db, order_id, outcome)


def _stripe_card_details(transaction_id: str) -> dict:
    """Cardholder name / card / receipt link for a Stripe checkout session.

    Only Stripe holds these — we never see or store card data. Returns {} for
    cash, mock mode, or anything Stripe won't tell us, so the receipt simply
    omits those lines rather than failing.
    """
    if not (transaction_id or "").startswith("cs_") or not stripe_service.is_live():
        return {}
    try:
        import stripe

        session = stripe.checkout.Session.retrieve(
            transaction_id, expand=["payment_intent.latest_charge"]
        )
        details = {}
        customer = getattr(session, "customer_details", None)
        if customer is not None:
            details["card_holder_name"] = getattr(customer, "name", None)
            details["receipt_email"] = getattr(customer, "email", None)

        intent = getattr(session, "payment_intent", None)
        charge = getattr(intent, "latest_charge", None) if intent is not None else None
        if charge is not None:
            details["receipt_url"] = getattr(charge, "receipt_url", None)
            card = getattr(getattr(charge, "payment_method_details", None), "card", None)
            if card is not None:
                details["card_brand"] = getattr(card, "brand", None)
                details["card_last4"] = getattr(card, "last4", None)
                # Stripe puts the name on the billing details of the charge
                billing = getattr(charge, "billing_details", None)
                if billing is not None and not details.get("card_holder_name"):
                    details["card_holder_name"] = getattr(billing, "name", None)
        return {k: v for k, v in details.items() if v}
    except Exception:
        logger.exception("Could not read Stripe details for %s", transaction_id)
        return {}


@router.get("/receipt", response_model=ReceiptOut)
def payment_receipt(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    session_id: Optional[str] = Query(
        default=None, description="Stripe checkout session id, as handed back on the success redirect."
    ),
    order_id: Optional[int] = Query(default=None, description="Look the receipt up by order instead."),
):
    """The receipt for a completed checkout — what the success page renders.

    Stripe redirects the shopper to {CHECKOUT_SUCCESS_URL}?session_id=... after
    payment; the page passes that straight here. Customers can only read their
    own receipts; staff and admin can read anyone's.
    """
    if not session_id and order_id is None:
        raise HTTPException(status_code=422, detail="Pass either session_id or order_id.")

    query = db.query(Payment)
    payment = (
        query.filter(Payment.transaction_id == session_id).first()
        if session_id
        else query.filter(Payment.order_id == order_id).first()
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="No payment found for this checkout")

    order = payment.order
    if order.user_id != user.id and user.role == UserRole.customer:
        raise HTTPException(status_code=403, detail="Not your order")

    invoice = db.query(Invoice).filter(Invoice.order_id == order.id).first()
    settled = payment.status == PaymentStatus.succeeded

    return ReceiptOut(
        order_id=order.id,
        order_number=order.order_number,
        order_status=order.order_status,
        payment_status=payment.status,
        amount=payment.amount,
        currency=payment.currency,
        payment_method=payment.payment_method,
        transaction_id=payment.transaction_id,
        paid_at=payment.updated_at if settled else None,
        created_at=payment.created_at,
        invoice_number=invoice.invoice_number if invoice else None,
        items=order.items,
        awaiting_confirmation=not settled and payment.payment_method != "cash",
        **_stripe_card_details(payment.transaction_id),
    )


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
            user_id=p.order.user_id,
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
    """Staff/admin confirm cash was received on delivery -> order paid + invoice.

    Same as POST /payments/confirm/{order_id} but refuses anything that isn't a
    cash-on-delivery payment, so the "cash received" action can't be used by
    mistake on a card order that hasn't actually been paid.
    """
    return _confirm_payment_for_order(db, order_id, "success", cash_only=True)


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
    db.refresh(order)
    publish_order_status(order, previous_status=order.order_status.value)


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
