"""Admin panel APIs: store analytics, the user directory, and the email log.

Admin only. Staff run the catalog and fulfilment but don't see revenue or
the customer directory, which matches the platform's RBAC split.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..database import get_db
from ..deps import require_admin
from ..models import (
    DevelopmentEmail,
    EmailStatus,
    Notification,
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    PaymentStatus,
    Product,
    User,
    UserRole,
)
from ..schemas import AdminEmailOut, AdminUserOut
from ..services.email_service import retry_email

router = APIRouter(prefix="/admin", tags=["Admin"])

LOW_STOCK_THRESHOLD = 5


@router.get("/analytics")
def analytics(
    days: int = Query(default=30, ge=7, le=365, description="Size of the revenue/orders trend window."),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Everything the analytics dashboard shows, in one call.

    Revenue counts only settled (succeeded) payments. Units sold and category
    sales exclude cancelled orders. All timestamps are UTC.
    """
    now = datetime.utcnow()
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    orders = db.query(Order).all()
    payments = db.query(Payment).all()
    products = db.query(Product).all()
    settled = [p for p in payments if p.status == PaymentStatus.succeeded]

    revenue = round(sum(p.amount for p in settled), 2)
    paid_orders = [o for o in orders if o.payment_status == PaymentStatus.succeeded]

    # ---- trend: revenue by the day the payment settled, orders by the day placed ----
    by_day = {(start + timedelta(days=i)).date(): {"revenue": 0.0, "orders": 0} for i in range(days)}
    for p in settled:
        day = (p.updated_at or p.created_at).date()
        if day in by_day:
            by_day[day]["revenue"] += p.amount
    for o in orders:
        if o.created_at.date() in by_day:
            by_day[o.created_at.date()]["orders"] += 1
    trend = [
        {"date": d.isoformat(), "revenue": round(v["revenue"], 2), "orders": v["orders"]}
        for d, v in sorted(by_day.items())
    ]
    window_revenue = round(sum(t["revenue"] for t in trend), 2)
    window_orders = sum(t["orders"] for t in trend)

    # ---- product performance (from order line items, not cancelled orders) ----
    live_items = (
        db.query(OrderItem)
        .join(Order, OrderItem.order_id == Order.id)
        .filter(Order.order_status != OrderStatus.cancelled)
        .all()
    )
    product_category = {p.id: p.category for p in products}
    units = Counter()
    sales = defaultdict(float)
    category_sales = defaultdict(lambda: {"revenue": 0.0, "units": 0})
    names = {}
    for item in live_items:
        units[item.product_id] += item.quantity
        sales[item.product_id] += item.unit_price * item.quantity
        names[item.product_id] = item.product_name
        category = product_category.get(item.product_id, "deleted products")
        category_sales[category]["revenue"] += item.unit_price * item.quantity
        category_sales[category]["units"] += item.quantity
    top_products = [
        {"product_id": pid, "name": names[pid], "units_sold": qty, "revenue": round(sales[pid], 2)}
        for pid, qty in units.most_common(8)
    ]

    users_by_role = Counter(u.role.value for u in db.query(User.role).all())
    unread = db.query(func.count(Notification.id)).filter(Notification.is_read.is_(False)).scalar()
    emails_by_status = dict(
        db.query(DevelopmentEmail.status, func.count(DevelopmentEmail.id))
        .group_by(DevelopmentEmail.status)
        .all()
    )

    recent = (
        db.query(Order)
        .options(joinedload(Order.user))
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(8)
        .all()
    )

    return {
        "generated_at": now.isoformat() + "Z",
        "currency": settings.STRIPE_CURRENCY,
        "window_days": days,
        "kpis": {
            "total_revenue": revenue,
            "window_revenue": window_revenue,
            "total_orders": len(orders),
            "window_orders": window_orders,
            "paid_orders": len(paid_orders),
            "average_order_value": round(revenue / len(paid_orders), 2) if paid_orders else 0.0,
            "pending_orders": sum(1 for o in orders if o.order_status == OrderStatus.pending),
            "awaiting_shipment": sum(1 for o in orders if o.order_status == OrderStatus.paid),
            "customers": users_by_role.get("customer", 0),
            "buyers": len({o.user_id for o in paid_orders}),  # staff/admin shop too
            "accounts": sum(users_by_role.values()),
            "products": len(products),
            "out_of_stock": sum(1 for p in products if p.stock <= 0),
            "low_stock": sum(1 for p in products if 0 < p.stock <= LOW_STOCK_THRESHOLD),
            "units_in_stock": sum(max(p.stock, 0) for p in products),
        },
        "trend": trend,
        "orders_by_status": {s.value: sum(1 for o in orders if o.order_status == s) for s in OrderStatus},
        "payments_by_status": {s.value: sum(1 for p in payments if p.status == s) for s in PaymentStatus},
        "revenue_by_method": {
            method: round(sum(p.amount for p in settled if p.payment_method == method), 2)
            for method in sorted({p.payment_method for p in settled})
        },
        "sales_by_category": sorted(
            ({"category": c, "revenue": round(v["revenue"], 2), "units": v["units"]}
             for c, v in category_sales.items()),
            key=lambda row: row["revenue"], reverse=True,
        ),
        "top_products": top_products,
        "low_stock_products": [
            {"id": p.id, "name": p.name, "category": p.category, "stock": p.stock}
            for p in sorted(products, key=lambda p: (p.stock, p.name))
            if p.stock <= LOW_STOCK_THRESHOLD
        ][:10],
        "users_by_role": {r.value: users_by_role.get(r.value, 0) for r in UserRole},
        "recent_orders": [
            {
                "id": o.id,
                "order_number": o.order_number,
                "customer": o.user.name if o.user else None,
                "total": o.total,
                "order_status": o.order_status.value,
                "payment_status": o.payment_status.value,
                "created_at": o.created_at,
            }
            for o in recent
        ],
        "notifications": {
            "total": db.query(func.count(Notification.id)).scalar(),
            "unread": unread,
        },
        "emails": {
            "backend": settings.EMAIL_BACKEND if settings.EMAIL_ENABLED else "disabled",
            "by_status": emails_by_status,
            "total": sum(emails_by_status.values()),
        },
    }


@router.get("/users", response_model=List[AdminUserOut])
def list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
    role: Optional[UserRole] = Query(default=None),
    search: Optional[str] = Query(default=None, description="Matches name or email."),
):
    """Every account with its order count and lifetime spend.

    Read-only by design: roles are changed directly in MySQL
    (`UPDATE users SET role = 'staff' WHERE id = ...`).
    """
    query = db.query(User)
    if role is not None:
        query = query.filter(User.role == role)
    if search:
        like = f"%{search.strip()}%"
        query = query.filter((User.name.ilike(like)) | (User.email.ilike(like)))
    users = query.order_by(User.created_at.desc()).all()

    stats = {
        user_id: (count, last)
        for user_id, count, last in db.query(Order.user_id, func.count(Order.id), func.max(Order.created_at))
        .group_by(Order.user_id)
        .all()
    }
    spent = dict(
        db.query(Order.user_id, func.sum(Payment.amount))
        .join(Payment, Payment.order_id == Order.id)
        .filter(Payment.status == PaymentStatus.succeeded)
        .group_by(Order.user_id)
        .all()
    )
    return [
        AdminUserOut(
            id=u.id,
            customer_number=u.customer_number,
            name=u.name,
            email=u.email,
            role=u.role,
            auth_provider=u.auth_provider or "local",
            created_at=u.created_at,
            orders=stats.get(u.id, (0, None))[0],
            last_order_at=stats.get(u.id, (0, None))[1],
            total_spent=round(float(spent.get(u.id) or 0), 2),
        )
        for u in users
    ]


def _email_out(email: DevelopmentEmail) -> AdminEmailOut:
    fields = {k: getattr(email, k) for k in AdminEmailOut.model_fields if k != "user_name"}
    return AdminEmailOut(**fields, user_name=email.user.name if email.user else None)


@router.get("/emails", response_model=List[AdminEmailOut])
def list_emails(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
    status: Optional[EmailStatus] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
):
    """Every outgoing email and whether it was delivered."""
    query = db.query(DevelopmentEmail).options(joinedload(DevelopmentEmail.user))
    if status is not None:
        query = query.filter(DevelopmentEmail.status == status.value)
    emails = query.order_by(DevelopmentEmail.created_at.desc(), DevelopmentEmail.id.desc()).limit(limit).all()
    return [_email_out(e) for e in emails]


@router.post("/emails/{email_id}/retry", response_model=AdminEmailOut)
def retry_failed_email(
    email_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Re-send an email that failed over SMTP."""
    email = db.get(DevelopmentEmail, email_id)
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")
    if email.status != EmailStatus.failed.value:
        raise HTTPException(status_code=400, detail=f"Only failed emails can be retried (this one is '{email.status}').")
    if settings.EMAIL_BACKEND != "smtp":
        raise HTTPException(status_code=400, detail="Retry needs EMAIL_BACKEND=smtp.")
    return _email_out(retry_email(db, email))
