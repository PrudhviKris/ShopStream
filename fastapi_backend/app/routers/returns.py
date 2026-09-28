"""Returns and refunds.

A customer opens a return on a delivered order inside the return window
(POST /orders/{order_id}/return, in the orders router). Staff then approve
or reject it here. Approving also refunds the payment and puts the stock
back, so the money and the inventory can't drift apart from the decision.
"""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import get_current_user, require_staff_or_admin, staff_admin_or_service
from ..models import (
    RETURN_REASONS,
    Order,
    OrderStatus,
    PaymentStatus,
    Product,
    ReturnRequest,
    ReturnStatus,
    User,
    UserRole,
)
from ..schemas import AdminReturnOut, ReturnDecision, ReturnRequestOut
from ..services import order_events, stripe_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/returns", tags=["Returns"])


def serialize(request: ReturnRequest, admin: bool = False):
    """One shape for both audiences; the admin one adds who's who."""
    data = {
        "id": request.id,
        "return_number": request.return_number,
        "order_id": request.order_id,
        "order_number": request.order.order_number if request.order else None,
        "user_id": request.user_id,
        "reason": request.reason,
        "reason_label": RETURN_REASONS.get(request.reason, request.reason),
        "comment": request.comment,
        "status": request.status,
        "created_at": request.created_at,
        "decided_at": request.decided_at,
        "decision_note": request.decision_note,
        "refund_amount": request.refund_amount,
        "refund_reference": request.refund_reference,
        "order_total": request.order.total if request.order else None,
    }
    if not admin:
        return ReturnRequestOut(**data)
    return AdminReturnOut(
        **data,
        user_name=request.user.name if request.user else "",
        user_email=request.user.email if request.user else "",
        decided_by=request.decided_by.name if request.decided_by else None,
    )


def _load(db: Session, return_id: int) -> ReturnRequest:
    request = (
        db.query(ReturnRequest)
        .options(joinedload(ReturnRequest.order).joinedload(Order.items),
                 joinedload(ReturnRequest.user))
        .filter(ReturnRequest.id == return_id)
        .first()
    )
    if request is None:
        raise HTTPException(status_code=404, detail="Return request not found")
    return request


def _require_pending(request: ReturnRequest) -> None:
    if request.status != ReturnStatus.pending:
        raise HTTPException(
            status_code=409,
            detail=f"This return was already {request.status.value} on "
                   f"{request.decided_at:%Y-%m-%d %H:%M} UTC.",
        )


@router.get("", response_model=List[ReturnRequestOut])
def my_returns(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Your own return requests, newest first."""
    requests = (
        db.query(ReturnRequest)
        .options(joinedload(ReturnRequest.order))
        .filter(ReturnRequest.user_id == user.id)
        .order_by(ReturnRequest.created_at.desc(), ReturnRequest.id.desc())
        .all()
    )
    return [serialize(r) for r in requests]


@router.get("/all", response_model=List[AdminReturnOut])
def all_returns(
    db: Session = Depends(get_db),
    _staff: User = Depends(require_staff_or_admin),
    status: Optional[ReturnStatus] = Query(default=None, description="Filter by decision state."),
):
    """Staff/admin: every return request. `?status=pending` is the work queue."""
    query = db.query(ReturnRequest).options(
        joinedload(ReturnRequest.order), joinedload(ReturnRequest.user),
        joinedload(ReturnRequest.decided_by),
    )
    if status is not None:
        query = query.filter(ReturnRequest.status == status)
    requests = query.order_by(ReturnRequest.created_at.desc(), ReturnRequest.id.desc()).all()
    return [serialize(r, admin=True) for r in requests]


@router.get("/reasons")
def return_reasons():
    """The reasons a customer may choose, for the storefront's dropdown."""
    return [{"value": value, "label": label} for value, label in RETURN_REASONS.items()]


@router.get("/{return_id}", response_model=ReturnRequestOut)
def get_return(
    return_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    request = _load(db, return_id)
    if request.user_id != user.id and user.role == UserRole.customer:
        raise HTTPException(status_code=403, detail="Not your return request")
    return serialize(request)


@router.post("/{return_id}/approve", response_model=AdminReturnOut)
def approve_return(
    return_id: int,
    body: Optional[ReturnDecision] = None,
    db: Session = Depends(get_db),
    # Staff/admin by JWT, or the Django admin with SERVICE_API_TOKEN — the
    # same door the order-status endpoint opens, so a decision made in
    # /admin/ refunds and emails exactly like one made in the storefront.
    staff: Optional[User] = Depends(staff_admin_or_service),
):
    """Staff/admin: approve a return, refund the payment, restock the items.

    The refund goes through Stripe for live card payments; cash, mock-mode
    and anything Stripe can't refund get a local reference so the money still
    has an audit trail. The customer is notified and emailed either way.
    """
    request = _load(db, return_id)
    _require_pending(request)
    order = request.order

    amount = order.total
    payment = order.payment
    try:
        refund = stripe_service.refund_payment(
            payment.transaction_id if payment else None,
            amount,
            payment.currency if payment else None,
        )
    except Exception as exc:
        # Nothing has been written yet, so the operator can fix the cause and
        # try again on a request that is still pending.
        logger.exception("Refund failed for return %s (order %s)", return_id, order.id)
        raise HTTPException(status_code=502, detail=f"Refund failed, nothing was changed: {exc}")

    previous_status = order.order_status.value
    request.status = ReturnStatus.approved
    request.decided_at = datetime.utcnow()
    request.decided_by_id = staff.id if staff else None   # None = via the admin service token
    request.decision_note = body.note if body else None
    request.refund_amount = amount
    request.refund_reference = refund["reference"]

    order.order_status = OrderStatus.returned
    if payment is not None:
        payment.status = PaymentStatus.refunded
        order.payment_status = PaymentStatus.refunded

    # The goods are coming back, so the stock does too.
    for item in order.items:
        product = db.get(Product, item.product_id)
        if product is not None:
            product.stock += item.quantity
            product.popularity = max(0, product.popularity - item.quantity)

    db.commit()
    db.refresh(request)
    order_events.return_approved(db, order, request, previous_status)
    return serialize(request, admin=True)


@router.post("/{return_id}/reject", response_model=AdminReturnOut)
def reject_return(
    return_id: int,
    body: Optional[ReturnDecision] = None,
    db: Session = Depends(get_db),
    staff: Optional[User] = Depends(staff_admin_or_service),
):
    """Staff/admin: decline a return. The order goes back to delivered."""
    request = _load(db, return_id)
    _require_pending(request)
    order = request.order

    previous_status = order.order_status.value
    request.status = ReturnStatus.rejected
    request.decided_at = datetime.utcnow()
    request.decided_by_id = staff.id if staff else None
    request.decision_note = body.note if body else None
    order.order_status = OrderStatus.delivered

    db.commit()
    db.refresh(request)
    order_events.return_rejected(db, order, request, previous_status)
    return serialize(request, admin=True)
