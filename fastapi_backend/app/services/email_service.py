"""Email service.

Every email is recorded in `development_emails`, which is also the user's
in-app inbox (GET /dev/emails) — so every user can read their mail, including
local accounts whose address is made up. What else happens depends on
EMAIL_BACKEND:

* ``database`` (default) — that row *is* the delivery. It shows up in the
  development inbox (GET /dev/emails), so the whole flow works with no mail
  server at all.
* ``smtp`` — the message is also sent through SMTP_HOST (SendGrid and AWS SES
  are SMTP relays, so this covers both). Sending happens on a background
  worker so a slow or unreachable mail server never delays or fails the
  request that triggered it; the row's `status` / `error` / `sent_at` record
  the outcome.

Callers don't change between backends.
"""
import logging
import smtplib
import ssl
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models import DevelopmentEmail, EmailStatus, User
from .notification_service import publish

logger = logging.getLogger(__name__)

# Two workers: enough to keep a burst of order events moving, few enough not
# to trip a provider's connection limits.
_smtp_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="smtp")

# Addresses that can never receive mail — synthesized for social accounts that
# didn't share an email (see auth._mock_email). Sending to them only bounces.
_UNDELIVERABLE_SUFFIXES = (".example.com", "@example.com", ".invalid", ".test", ".localhost")


def _undeliverable(address: str) -> bool:
    return address.lower().endswith(_UNDELIVERABLE_SUFFIXES)


def smtp_skip_reason(user: User) -> Optional[str]:
    """Why SMTP must not send to this user, or None when it may.

    Email/password accounts never prove they own their address (there is no
    verification step), so a made-up "bruce@gmail.com" could belong to a
    stranger. Unless SMTP_SEND_TO_LOCAL_ACCOUNTS is on, those users get only
    the in-app inbox copy. Google accounts carry a Google-verified address.
    """
    if _undeliverable(user.email):
        return "Placeholder address — nothing to deliver to. Readable in the app inbox."
    if (user.auth_provider or "local") == "local" and not settings.SMTP_SEND_TO_LOCAL_ACCOUNTS:
        return ("Local account with an unverified address — not sent over SMTP "
                "(SMTP_SEND_TO_LOCAL_ACCOUNTS=false). Readable in the app inbox.")
    return None


def delivery_description(user: User) -> str:
    """How mail to this user is delivered, in words the inbox page can show."""
    if not settings.EMAIL_ENABLED:
        return "Email is turned off for this store."
    if settings.EMAIL_BACKEND != "smtp":
        return "Kept in this in-app inbox only — no email is sent to the address."
    reason = smtp_skip_reason(user)
    if reason:
        return "Kept in this in-app inbox only — the address isn't verified, so nothing is sent to it."
    return "Sent to the address, with a copy kept in this inbox."


def send_email(
    db: Session,
    user: User,
    subject: str,
    body: str,
    html_body: Optional[str] = None,
    notification_type: Optional[str] = None,
) -> Optional[DevelopmentEmail]:
    """Record an email for `user` and deliver it via the configured backend.

    Returns the stored row, or None when email is disabled or the user has no
    address. Never raises for delivery problems — those land on the row.
    """
    if not settings.EMAIL_ENABLED or not user.email:
        return None

    skip_reason = smtp_skip_reason(user) if settings.EMAIL_BACKEND == "smtp" else None
    if settings.EMAIL_BACKEND != "smtp":
        status = EmailStatus.stored
    elif skip_reason:
        # Only matters when really sending: the inbox copy is kept either way.
        status = EmailStatus.skipped
    else:
        status = EmailStatus.queued

    email = DevelopmentEmail(
        user_id=user.id,
        to_email=user.email,
        from_email=settings.EMAIL_FROM,
        subject=subject,
        body=body,
        html_body=html_body,
        notification_type=notification_type,
        status=status.value,
        error=skip_reason,
    )
    db.add(email)
    db.commit()
    db.refresh(email)

    if status == EmailStatus.queued:
        _smtp_pool.submit(_deliver, email.id)

    # New mail → the recipient's open tabs update their inbox and unread badge.
    unread = (
        db.query(DevelopmentEmail)
        .filter(DevelopmentEmail.user_id == user.id, DevelopmentEmail.is_read.is_(False))
        .count()
    )
    publish([user.id], "email", {
        "id": email.id,
        "subject": email.subject,
        "notification_type": email.notification_type,
        "created_at": email.created_at,
        "unread_count": unread,
    })
    return email


def build_message(email: DevelopmentEmail) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = email.subject
    message["From"] = formataddr((settings.APP_NAME, email.from_email))
    message["To"] = email.to_email
    message["Message-ID"] = make_msgid(domain=email.from_email.split("@")[-1])
    message.set_content(email.body)
    if email.html_body:
        message.add_alternative(email.html_body, subtype="html")
    return message


def smtp_send(message: EmailMessage) -> None:
    """One SMTP conversation. Raises on any failure."""
    context = ssl.create_default_context()
    if settings.SMTP_USE_SSL:
        server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT,
                                  timeout=settings.SMTP_TIMEOUT, context=context)
    else:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT)
    with server:
        if settings.SMTP_USE_TLS and not settings.SMTP_USE_SSL:
            server.starttls(context=context)
        if settings.SMTP_USERNAME:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(message)


def _deliver(email_id: int) -> None:
    """Background worker: send one stored email and record the outcome.
    Uses its own session — the request's session is long closed by now."""
    from ..database import SessionLocal

    with SessionLocal() as db:
        email = db.get(DevelopmentEmail, email_id)
        if email is None:
            return  # user (and their mail) deleted before we got to it
        try:
            smtp_send(build_message(email))
            email.status = EmailStatus.sent.value
            email.sent_at = datetime.utcnow()
            email.error = None
        except Exception as exc:  # network, auth, refused recipient, ...
            logger.warning("Email %s to %s failed: %s", email.id, email.to_email, exc)
            email.status = EmailStatus.failed.value
            email.error = f"{exc.__class__.__name__}: {exc}"[:2000]
        db.commit()


def retry_email(db: Session, email: DevelopmentEmail) -> DevelopmentEmail:
    """Re-queue a failed SMTP email (admin action)."""
    email.status = EmailStatus.queued.value
    email.error = None
    db.commit()
    db.refresh(email)
    _smtp_pool.submit(_deliver, email.id)
    return email
