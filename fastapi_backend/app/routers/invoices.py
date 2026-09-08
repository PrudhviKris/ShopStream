from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import Invoice, Role, User, UserRole
from ..schemas import AdminInvoiceOut, InvoiceOut, RoleOut

router = APIRouter(tags=["Invoices"])


@router.get("/invoices", response_model=List[InvoiceOut])
def my_invoices(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return (
        db.query(Invoice)
        .filter(Invoice.user_id == user.id)
        .order_by(Invoice.issued_at.desc())
        .all()
    )


@router.get("/invoices/all", response_model=List[AdminInvoiceOut])
def all_invoices(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Admin only: every customer's invoices."""
    invoices = (
        db.query(Invoice)
        .options(joinedload(Invoice.user))
        .order_by(Invoice.issued_at.desc())
        .all()
    )
    return [
        AdminInvoiceOut(
            **InvoiceOut.model_validate(inv).model_dump(),
            user_name=inv.user.name,
            user_email=inv.user.email,
        )
        for inv in invoices
    ]


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
def get_invoice(
    invoice_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.user_id != user.id and user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Not your invoice")
    return invoice


@router.get("/roles", response_model=List[RoleOut])
def list_roles(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Admin only: the platform's role definitions."""
    return db.query(Role).order_by(Role.id).all()
