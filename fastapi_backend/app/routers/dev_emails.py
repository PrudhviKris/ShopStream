from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import DevelopmentEmail, User
from ..schemas import DevelopmentEmailOut

router = APIRouter(prefix="/dev/emails", tags=["Development Email"])


@router.get("", response_model=List[DevelopmentEmailOut])
def list_development_emails(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Emails sent to the current user, newest first.

    With EMAIL_BACKEND=database this is the inbox itself; with smtp it's the
    record of what was sent, with each message's delivery `status`.
    """
    return (
        db.query(DevelopmentEmail)
        .filter(DevelopmentEmail.user_id == user.id)
        .order_by(DevelopmentEmail.created_at.desc(), DevelopmentEmail.id.desc())
        .limit(100)
        .all()
    )


@router.get("/{email_id}", response_model=DevelopmentEmailOut)
def get_development_email(
    email_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """One email sent to the current user."""
    email = (
        db.query(DevelopmentEmail)
        .filter(
            DevelopmentEmail.id == email_id,
            DevelopmentEmail.user_id == user.id,
        )
        .first()
    )
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")
    return email
