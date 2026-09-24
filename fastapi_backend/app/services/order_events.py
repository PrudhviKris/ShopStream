"""One place that decides what happens when an order changes.

Each business event below does all three deliveries together, so no call
site can remember one and forget another:

    in-app notification  (stored, and pushed as the `notification` WS event)
    email                (via email_service — database inbox or SMTP)
    order_status_updated (WS event to the owner and all staff/admin)

| event                | notification type   | email                        |
|----------------------|---------------------|------------------------------|
| card order placed    | order_placed        | Order confirmation           |
| cash order placed    | order_confirmed     | Order confirmation           |
| payment succeeded    | payment_successful  | Payment successful + invoice |
| payment failed       | payment_failed      | Payment failed               |
| shipped              | order_shipped       | Shipping update              |
| delivered            | order_delivered     | Shipping update              |
| cancelled            | order_cancelled     | Shipping update              |
"""
import html
import logging
from typing import Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models import RETURN_REASONS, Invoice, NotificationType, Order, OrderStatus, Payment
from .email_service import send_email
from .notification_service import notify, publish, publish_order_status

logger = logging.getLogger(__name__)

_CURRENCY_SYMBOLS = {"inr": "₹", "usd": "$", "eur": "€", "gbp": "£"}


def money(amount: float, currency: Optional[str] = None) -> str:
    """₹1,23,456.00 — Indian digit grouping for INR, western for the rest."""
    currency = (currency or settings.STRIPE_CURRENCY or "inr").lower()
    symbol = _CURRENCY_SYMBOLS.get(currency, currency.upper() + " ")
    whole, _, cents = f"{abs(amount):.2f}".partition(".")
    if currency == "inr" and len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    else:
        whole = f"{int(whole):,}"
    return f"{'-' if amount < 0 else ''}{symbol}{whole}.{cents}"


def _label(order: Order) -> str:
    return f"#{order.order_number or order.id}"


def _currency(order: Order) -> str:
    return order.payment.currency if order.payment else settings.STRIPE_CURRENCY


# ---------- email rendering ----------

def _items_text(order: Order) -> str:
    cur = _currency(order)
    lines = [
        f"  {item.quantity} x {item.product_name}  —  {money(item.unit_price * item.quantity, cur)}"
        for item in order.items
    ]
    lines += [
        "",
        f"  Subtotal: {money(order.subtotal, cur)}",
        f"  Tax:      {money(order.tax or 0, cur)}",
        f"  Total:    {money(order.total, cur)}",
    ]
    return "\n".join(lines)


def _items_html(order: Order) -> str:
    cur = _currency(order)
    rows = "".join(
        f"<tr><td style='padding:6px 0'>{item.quantity} &times; {html.escape(item.product_name)}</td>"
        f"<td style='padding:6px 0;text-align:right'>{money(item.unit_price * item.quantity, cur)}</td></tr>"
        for item in order.items
    )
    totals = (
        "<tr><td style='padding:6px 0;color:#72778a;border-top:1px solid #e9eaf0'>Subtotal</td>"
        f"<td style='padding:6px 0;text-align:right;border-top:1px solid #e9eaf0'>{money(order.subtotal, cur)}</td></tr>"
        "<tr><td style='padding:6px 0;color:#72778a'>Tax</td>"
        f"<td style='padding:6px 0;text-align:right'>{money(order.tax or 0, cur)}</td></tr>"
        "<tr><td style='padding:6px 0;font-weight:700'>Total</td>"
        f"<td style='padding:6px 0;text-align:right;font-weight:700'>{money(order.total, cur)}</td></tr>"
    )
    return f"<table style='width:100%;border-collapse:collapse;font-size:14px'>{rows}{totals}</table>"


def _render(order: Order, heading: str, intro: str, details=()) -> tuple:
    """(plain text, HTML) for an order email. Plain text carries the full
    content; the HTML part is the same thing, styled, for clients that show it."""
    name = order.user.name if order.user else "there"
    details = [(k, v) for k, v in details if v]

    text_lines = [f"Hi {name},", "", intro, ""]
    if details:
        text_lines += [f"{k}: {v}" for k, v in details] + [""]
    text_lines += [
        f"Order {_label(order)}",
        _items_text(order),
        "",
        f"Track it any time at {settings.PUBLIC_URL}",
        "",
        f"— {settings.APP_NAME}",
    ]

    detail_rows = "".join(
        f"<tr><td style='padding:4px 14px 4px 0;color:#72778a'>{html.escape(k)}</td>"
        f"<td style='padding:4px 0;font-weight:600'>{html.escape(str(v))}</td></tr>"
        for k, v in details
    )
    detail_table = f"<table style='margin:0 0 18px;font-size:14px'>{detail_rows}</table>" if details else ""
    public_url = html.escape(settings.PUBLIC_URL)
    body_html = (
        "<div style='background:#f7f8fb;padding:24px;font-family:Segoe UI,Arial,sans-serif;color:#121522'>"
        "<div style='max-width:560px;margin:0 auto;background:#fff;border:1px solid #e9eaf0;"
        "border-radius:14px;padding:28px'>"
        "<p style='margin:0 0 6px;font-size:11px;font-weight:800;letter-spacing:1.8px;color:#5b4bff'>"
        f"{html.escape(settings.APP_NAME.upper())}</p>"
        f"<h1 style='margin:0 0 14px;font-size:22px'>{html.escape(heading)}</h1>"
        f"<p style='margin:0 0 16px'>Hi {html.escape(name)},</p>"
        f"<p style='margin:0 0 18px;line-height:1.55'>{html.escape(intro)}</p>"
        f"{detail_table}"
        f"<h3 style='margin:0 0 8px;font-size:15px'>Order {html.escape(_label(order))}</h3>"
        f"{_items_html(order)}"
        "<p style='margin:22px 0 0;font-size:13px;color:#72778a'>Track your order at "
        f"<a href='{public_url}' style='color:#5b4bff'>{public_url}</a></p>"
        "</div></div>"
    )
    return "\n".join(text_lines), body_html


def _deliver(db: Session, order: Order, type_: NotificationType, title: str, message: str,
             subject: str, heading: str, intro: str, details=()) -> None:
    notify(db, order.user_id, type_, title, message, order_id=order.id)
    if order.user is None:
        return
    try:
        text, body_html = _render(order, heading, intro, details)
        send_email(db, order.user, subject, text, body_html, notification_type=type_.value)
    except Exception:
        # A broken email must never undo or fail the order change itself —
        # the notification above has already reached the customer.
        logger.exception("Could not send %s email for order %s", type_.value, order.id)
        db.rollback()


# ---------- events ----------

def order_placed(db: Session, order: Order, payment: Payment) -> None:
    cur = payment.currency
    label = _label(order)
    if payment.payment_method == "cash":
        _deliver(
            db, order, NotificationType.order_confirmed,
            title=f"Order {label} confirmed",
            message=(f"Order {label} is confirmed — cash on delivery. Pay "
                     f"{money(order.total, cur)} when it arrives (ref {payment.transaction_id})."),
            subject=f"Order confirmation — {label}",
            heading="Your order is confirmed",
            intro=("Thanks for your order! You chose cash on delivery, so there's nothing to pay "
                   "now — just have the amount ready when it arrives."),
            details=[("Amount due on delivery", money(order.total, cur)),
                     ("Payment reference", payment.transaction_id)],
        )
    else:
        _deliver(
            db, order, NotificationType.order_placed,
            title=f"Order {label} placed",
            message=f"Order {label} created for {money(order.total, cur)}. Complete payment to confirm it.",
            subject=f"Order confirmation — {label}",
            heading="We've received your order",
            intro=("Thanks for your order! It's reserved for you and will be confirmed as soon "
                   "as your card payment goes through."),
            details=[("Amount", money(order.total, cur))],
        )
    publish_order_status(order, previous_status=None)


def payment_succeeded(db: Session, payment: Payment, invoice: Optional[Invoice],
                      previous_status: Optional[str]) -> None:
    order = payment.order
    label = _label(order)
    invoice_note = f" Invoice {invoice.invoice_number} has been issued." if invoice else ""
    _deliver(
        db, order, NotificationType.payment_successful,
        title="Payment successful",
        message=(f"Payment of {money(payment.amount, payment.currency)} for order {label} "
                 f"succeeded. Your order is confirmed!{invoice_note}"),
        subject=f"Payment successful — order {label} confirmed",
        heading="Payment received — order confirmed",
        intro="We've received your payment and your order is confirmed. We'll let you know as soon as it ships.",
        details=[
            ("Amount paid", money(payment.amount, payment.currency)),
            ("Transaction ID", payment.transaction_id),
            ("Invoice", invoice.invoice_number if invoice else None),
        ],
    )
    publish_order_status(order, previous_status)


def payment_failed(db: Session, payment: Payment, previous_status: Optional[str]) -> None:
    order = payment.order
    label = _label(order)
    _deliver(
        db, order, NotificationType.payment_failed,
        title="Payment failed",
        message=f"Payment for order {label} failed. Please try again.",
        subject=f"Payment failed — order {label}",
        heading="Your payment didn't go through",
        intro=("We couldn't take payment for your order, so it hasn't been confirmed yet. "
               "Please try again or choose another payment method."),
        details=[("Amount", money(payment.amount, payment.currency)),
                 ("Transaction ID", payment.transaction_id)],
    )
    publish_order_status(order, previous_status)


# status -> (notification type, title, message, email heading, email intro)
_SHIPPING_COPY = {
    OrderStatus.shipped: (
        NotificationType.order_shipped,
        "Order {label} shipped",
        "Good news — order {label} is on its way!",
        "Your order has shipped",
        "Your order has left our warehouse and is on its way to you.",
    ),
    OrderStatus.delivered: (
        NotificationType.order_delivered,
        "Order {label} delivered",
        "Order {label} has been delivered. Enjoy!",
        "Your order has been delivered",
        "Your order has been delivered. We hope you love it — thanks for shopping with us!",
    ),
    OrderStatus.cancelled: (
        NotificationType.order_cancelled,
        "Order {label} cancelled",
        "Order {label} has been cancelled.",
        "Your order has been cancelled",
        "Your order has been cancelled. If you already paid, a refund will follow — "
        "contact us if this wasn't expected.",
    ),
}


def return_requested(db: Session, order: Order, return_request) -> None:
    """The customer asked to send an order back."""
    label = _label(order)
    reason = RETURN_REASONS.get(return_request.reason, return_request.reason)
    _deliver(
        db, order, NotificationType.return_requested,
        title=f"Return requested for order {label}",
        message=(f"We've received your return request for order {label} ({reason}). "
                 "Our team will review it shortly."),
        subject=f"Return request received — order {label}",
        heading="We've got your return request",
        intro=("Thanks — your request is with our team. We'll email you as soon as it's "
               "reviewed, usually within a couple of working days."),
        details=[("Reason", reason), ("Your note", return_request.comment),
                 ("Request ID", f"#{return_request.id}")],
    )
    publish_order_status(order, previous_status=OrderStatus.delivered.value)
    # Staff see it in their returns queue without refreshing.
    publish([], "return_requested", {
        "return_id": return_request.id,
        "order_id": order.id,
        "order_number": order.order_number,
        "reason": return_request.reason,
        "status": return_request.status.value,
    }, include_staff=True)


def return_approved(db: Session, order: Order, return_request, previous_status: str) -> None:
    """Approved and refunded."""
    label = _label(order)
    cur = _currency(order)
    amount = money(return_request.refund_amount or order.total, cur)
    _deliver(
        db, order, NotificationType.return_approved,
        title=f"Return approved for order {label}",
        message=(f"Your return for order {label} was approved and {amount} has been refunded."),
        subject=f"Return approved — {amount} refunded for order {label}",
        heading="Your return has been approved",
        intro=("Good news — we've approved your return and issued the refund. Card refunds "
               "usually appear within 5–10 working days, depending on your bank."),
        details=[("Refunded", amount), ("Reference", return_request.refund_reference),
                 ("Note from our team", return_request.decision_note)],
    )
    publish_order_status(order, previous_status)
    publish([], "return_resolved", {
        "return_id": return_request.id, "order_id": order.id, "status": "approved",
    }, include_staff=True)


def return_rejected(db: Session, order: Order, return_request, previous_status: str) -> None:
    """Declined, with the reason the operator gave."""
    label = _label(order)
    _deliver(
        db, order, NotificationType.return_rejected,
        title=f"Return declined for order {label}",
        message=(f"Your return request for order {label} wasn't approved."
                 + (f" {return_request.decision_note}" if return_request.decision_note else "")),
        subject=f"Return request declined — order {label}",
        heading="We couldn't approve this return",
        intro=("We've reviewed your request and can't accept this return. If you think this "
               "is a mistake, reply to this email and we'll take another look."),
        details=[("Reason given", return_request.decision_note)],
    )
    publish_order_status(order, previous_status)
    publish([], "return_resolved", {
        "return_id": return_request.id, "order_id": order.id, "status": "rejected",
    }, include_staff=True)


def order_status_changed(db: Session, order: Order, previous_status: str) -> None:
    copy = _SHIPPING_COPY.get(order.order_status)
    if copy is not None:
        type_, title, message, heading, intro = copy
        label = _label(order)
        _deliver(
            db, order, type_,
            title=title.format(label=label),
            message=message.format(label=label),
            subject=f"Shipping update — order {label} {order.order_status.value}",
            heading=heading,
            intro=intro,
            details=[("Status", f"{previous_status} → {order.order_status.value}")],
        )
    publish_order_status(order, previous_status)
