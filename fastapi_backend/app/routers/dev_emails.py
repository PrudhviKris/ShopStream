from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import false
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import DevelopmentEmail, User
from ..schemas import DevelopmentEmailOut, EmailReadRequest, InboxSummary, NotificationReadResult
from ..services.email_service import delivery_description
from ..services.notification_service import publish

router = APIRouter(prefix="/dev/emails", tags=["Development Email"])


def _mine(db: Session, user: User):
    return db.query(DevelopmentEmail).filter(DevelopmentEmail.user_id == user.id)


def _unread(db: Session, user: User) -> int:
    return _mine(db, user).filter(DevelopmentEmail.is_read.is_(False)).count()


@router.get("", response_model=List[DevelopmentEmailOut])
def list_development_emails(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    unread_only: bool = Query(default=False, description="Only emails not opened yet."),
):
    """Your inbox: every email the store sent you, newest first.

    A copy of each email is always kept here, so this works even when your
    address can't receive mail (a made-up address on a local account, or no
    mail server configured).
    """
    query = _mine(db, user)
    if unread_only:
        query = query.filter(DevelopmentEmail.is_read.is_(False))
    return query.order_by(DevelopmentEmail.created_at.desc(), DevelopmentEmail.id.desc()).limit(100).all()


@router.get("/summary", response_model=InboxSummary)
def inbox_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Unread count for the inbox badge, and how mail to your address is delivered."""
    return {
        "address": user.email,
        "total": _mine(db, user).count(),
        "unread_count": _unread(db, user),
        "delivery": delivery_description(user),
    }


@router.post("/read", response_model=NotificationReadResult)
def mark_emails_read(
    body: Optional[EmailReadRequest] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark emails as read: `{"email_ids": [4, 5]}`, or `{"all": true}` / an empty body for all.

    Only your own emails are touched. Your other open tabs get an
    `emails_read` WebSocket event so their unread badge updates too.
    """
    query = _mine(db, user).filter(DevelopmentEmail.is_read.is_(False))
    ids = body.email_ids if body is not None and not body.all else None
    if ids is not None:
        query = query.filter(DevelopmentEmail.id.in_(ids)) if ids else query.filter(false())
    marked = query.update({DevelopmentEmail.is_read: True}, synchronize_session=False)
    db.commit()

    remaining = _unread(db, user)
    if marked:
        publish([user.id], "emails_read",
                {"email_ids": ids if ids is not None else "all", "unread_count": remaining})
    return {"marked_read": marked, "unread_count": remaining}


@router.get("/{email_id}", response_model=DevelopmentEmailOut)
def get_development_email(
    email_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """One email sent to you. Reading it doesn't mark it read — use POST /dev/emails/read."""
    email = _mine(db, user).filter(DevelopmentEmail.id == email_id).first()
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")
    return email
