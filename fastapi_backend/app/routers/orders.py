from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import get_current_user, require_admin, require_staff_or_admin
from ..models import (
    ORDER_TRANSITIONS,
    Invoice,
    Order,
    OrderStatus,
    Payment,
    Product,
    User,
    UserRole,
)
from ..schemas import AdminOrderOut, OrderOut, OrderStatusUpdate
from ..services.notification_service import notify

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.get("", response_model=List[OrderOut])
def my_orders(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(Order.user_id == user.id)
        .order_by(Order.created_at.desc())
        .all()
    )


@router.get("/all", response_model=List[AdminOrderOut])
def all_orders(
    db: Session = Depends(get_db), _staff: User = Depends(require_staff_or_admin)
):
    """Staff/admin: every customer's orders, with customer identity."""
    orders = (
        db.query(Order)
        .options(joinedload(Order.items), joinedload(Order.user))
        .order_by(Order.created_at.desc())
        .all()
    )
    return [
        AdminOrderOut(
            **OrderOut.model_validate(o).model_dump(),
            user_name=o.user.name,
            user_email=o.user.email,
        )
        for o in orders
    ]


@router.get("/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    order = (
        db.query(Order).options(joinedload(Order.items)).filter(Order.id == order_id).first()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.user_id != user.id and user.role == UserRole.customer:
        raise HTTPException(status_code=403, detail="Not your order")
    return order


@router.delete("/{order_id}", status_code=204)
def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Admin only: delete an order with its items, payment, and invoice.
    Reserved stock is returned to products unless the order already shipped."""
    order = db.query(Order).options(joinedload(Order.items)).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.order_status not in (OrderStatus.shipped, OrderStatus.delivered):
        for item in order.items:
            product = db.get(Product, item.product_id)
            if product is not None:
                product.stock += item.quantity
                product.popularity = max(0, product.popularity - item.quantity)

    db.query(Invoice).filter(Invoice.order_id == order.id).delete()
    db.query(Payment).filter(Payment.order_id == order.id).delete()
    db.delete(order)  # order_items cascade
    db.commit()


@router.get("/{order_id}/status-options", tags=["Orders"])
def order_status_options(
    order_id: int,
    db: Session = Depends(get_db),
    _staff: User = Depends(require_staff_or_admin),
):
    """What can I do with this order right now?

    Ask this before calling the status endpoint and you never have to guess:
    it returns the order's current status and exactly which values
    `PUT /orders/{order_id}/status` will accept for it, plus whether the
    payment can still be confirmed.
    """
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "order_status": order.order_status.value,
        "payment_status": order.payment_status.value,
        "allowed_next_statuses": order.allowed_next_statuses,
        "can_confirm_payment": order.can_confirm_payment,
        "hint": (
            "Confirm the payment with POST /payments/confirm/{order_id} to move this "
            "order to 'paid'."
            if order.can_confirm_payment
            else ("This order is final — no further status changes are possible."
                  if not order.allowed_next_statuses
                  else "Pick one of allowed_next_statuses for PUT /orders/{order_id}/status.")
        ),
    }


@router.put("/{order_id}/status", response_model=OrderOut)
def update_order_status(
    order_id: int,
    status: Optional[OrderStatus] = Query(
        default=None,
        description=(
            "The new order status — pick one from the list. Which values are "
            "actually accepted depends on where the order is now:\n\n"
            "* **pending** → `cancelled` (to mark it paid, confirm the payment "
            "instead: POST /payments/confirm/{order_id})\n"
            "* **paid** → `shipped` or `cancelled`\n"
            "* **shipped** → `delivered` or `cancelled`\n"
            "* **delivered** / **cancelled** → final, nothing further\n\n"
            "GET /orders/{order_id}/status-options tells you the answer for one "
            "specific order."
        ),
    ),
    db: Session = Depends(get_db),
    _staff: User = Depends(require_staff_or_admin),
    body: Optional[OrderStatusUpdate] = None,
):
    """Move an order along its lifecycle (staff/admin).

    `pending → paid → shipped → delivered`, and `cancelled` from any stage
    before delivery. An order never reaches **paid** here — that happens by
    confirming its payment, which also settles the payment record and issues
    the invoice.
    """
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    # `status` is a query parameter so Swagger renders it as a dropdown of the
    # valid values; a JSON body ({"status": "..."}) still works for older callers.
    new_status = status if status is not None else (body.status if body else None)
    if new_status is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Pick a status. Add ?status=<value> to the URL (Swagger shows the "
                f"choices as a dropdown). Allowed for this order right now: "
                + (", ".join(order.allowed_next_statuses) or "nothing — this order is final")
            ),
        )

    if new_status not in ORDER_TRANSITIONS[order.order_status]:
        allowed = order.allowed_next_statuses
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot change an order that is '{order.order_status.value}' to "
                f"'{new_status.value}'. Allowed from here: "
                + (", ".join(allowed) if allowed else "nothing — this order is final")
                + (". Use POST /payments/confirm/{order_id} to mark it paid."
                   if order.order_status == OrderStatus.pending else "")
            ),
        )
    order.order_status = new_status
    db.commit()
    db.refresh(order)

    notify(
        db,
        order.user_id,
        "order",
        f"Order #{order.id} {new_status.value}",
        f"Your order #{order.id} status changed to '{new_status.value}'.",
    )
    return order
