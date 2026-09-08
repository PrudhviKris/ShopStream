from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import get_current_user, require_admin, require_staff_or_admin
from ..models import Invoice, Order, OrderStatus, Payment, Product, User, UserRole
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


@router.put("/{order_id}/status", response_model=OrderOut)
def update_order_status(
    order_id: int,
    body: OrderStatusUpdate,
    db: Session = Depends(get_db),
    _staff: User = Depends(require_staff_or_admin),
):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    valid_transitions = {
        OrderStatus.pending: {OrderStatus.paid, OrderStatus.cancelled},
        OrderStatus.paid: {OrderStatus.shipped, OrderStatus.cancelled},
        OrderStatus.shipped: {OrderStatus.delivered},
        OrderStatus.delivered: set(),
        OrderStatus.cancelled: set(),
    }
    if body.status not in valid_transitions[order.order_status]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from '{order.order_status.value}' to '{body.status.value}'",
        )
    order.order_status = body.status
    db.commit()
    db.refresh(order)

    notify(
        db,
        order.user_id,
        "order",
        f"Order #{order.id} {body.status.value}",
        f"Your order #{order.id} status changed to '{body.status.value}'.",
    )
    return order
