"""One place that decides what happens when a review changes — the review
counterpart to order_events.py. Each function does both deliveries together:

    in-app notification  (stored, and pushed as the `notification` WS event)
    email                (via email_service — database inbox or SMTP)

Submission also pushes a `review_submitted` WS event to staff/admin so the
moderation queue updates live, the same way `return_requested` does for the
returns queue.
"""
import html
import logging

from sqlalchemy.orm import Session

from ..config import settings
from ..models import NotificationType, Review
from .email_service import send_email
from .notification_service import notify, publish

logger = logging.getLogger(__name__)


def _label(review: Review) -> str:
    return f"#{review.review_number or review.id}"


def _product_name(review: Review) -> str:
    return review.product.name if review.product else "your product"


def _render(review: Review, heading: str, intro: str, details=()) -> tuple:
    """(plain text, HTML) for a review email — same visual style as order
    emails in order_events.py, adapted for a product instead of an order."""
    name = review.user.name if review.user else "there"
    details = [(k, v) for k, v in details if v]

    text_lines = [f"Hi {name},", "", intro, ""]
    if details:
        text_lines += [f"{k}: {v}" for k, v in details] + [""]
    text_lines += [
        f"Product: {_product_name(review)}",
        f"Your rating: {review.rating}/5",
        f"Review {_label(review)}",
        "",
        f"— {settings.APP_NAME}",
    ]

    detail_rows = "".join(
        f"<tr><td style='padding:4px 14px 4px 0;color:#72778a'>{html.escape(k)}</td>"
        f"<td style='padding:4px 0;font-weight:600'>{html.escape(str(v))}</td></tr>"
        for k, v in details
    )
    detail_table = f"<table style='margin:0 0 18px;font-size:14px'>{detail_rows}</table>" if details else ""
    stars = "★" * review.rating + "☆" * (5 - review.rating)
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
        f"<h3 style='margin:0 0 4px;font-size:15px'>{html.escape(_product_name(review))}</h3>"
        f"<p style='margin:0 0 18px;color:#e8ab00;font-size:18px'>{stars}"
        f"<span style='margin-left:8px;color:#72778a;font-size:13px'>{review.rating}/5</span></p>"
        "</div></div>"
    )
    return "\n".join(text_lines), body_html


def _deliver(db: Session, review: Review, type_: NotificationType, title: str, message: str,
             subject: str, heading: str, intro: str, details=()) -> None:
    notify(db, review.user_id, type_, title, message)
    if review.user is None:
        return
    try:
        text, body_html = _render(review, heading, intro, details)
        send_email(db, review.user, subject, text, body_html, notification_type=type_.value)
    except Exception:
        # A broken email must never undo or fail the review decision itself —
        # the notification above has already reached the customer.
        logger.exception("Could not send %s email for review %s", type_.value, review.id)
        db.rollback()


def review_submitted(db: Session, review: Review) -> None:
    """The customer posted a review — pending, awaiting staff approval."""
    label = _label(review)
    product = _product_name(review)
    _deliver(
        db, review, NotificationType.review_submitted,
        title=f"Review {label} submitted",
        message=f"Your review of {product} was received and is awaiting approval.",
        subject=f"Review received — {product}",
        heading="Thanks for your review",
        intro=("We've received your review and it's awaiting approval from our team. "
               "We'll let you know as soon as it's live."),
    )
    # Staff see it in their moderation queue without refreshing.
    publish([], "review_submitted", {
        "review_id": review.id,
        "review_number": review.review_number,
        "product_id": review.product_id,
        "status": review.status.value,
    }, include_staff=True)


def review_approved(db: Session, review: Review) -> None:
    """Published — now counts towards the product's average and shows on its page."""
    label = _label(review)
    product = _product_name(review)
    _deliver(
        db, review, NotificationType.review_approved,
        title=f"Review {label} approved",
        message=f"Your review of {product} is now live.",
        subject=f"Your review is live — {product}",
        heading="Your review has been approved",
        intro="Good news — we've approved your review and it's now visible on the product page.",
    )


def review_rejected(db: Session, review: Review) -> None:
    """Declined — stays hidden."""
    label = _label(review)
    product = _product_name(review)
    _deliver(
        db, review, NotificationType.review_rejected,
        title=f"Review {label} declined",
        message=f"Your review of {product} wasn't approved.",
        subject=f"About your review — {product}",
        heading="We couldn't approve this review",
        intro=("We've reviewed what you submitted and can't publish it as-is — usually because "
               "it doesn't meet our content guidelines. If you think this is a mistake, reply to "
               "this email and we'll take another look."),
    )
