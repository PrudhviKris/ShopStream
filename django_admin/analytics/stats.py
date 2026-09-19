"""Store analytics, computed once and shared by the HTML dashboard and the
JSON endpoint so the two can never disagree."""
import os
from collections import defaultdict
from datetime import datetime, timedelta

from django.db.models import Count, F, Sum

from .models import Email, Notification, Order, OrderItem, Payment, Product, StoreUser

LOW_STOCK_THRESHOLD = 5
ORDER_STATUSES = ["pending", "paid", "shipped", "delivered", "cancelled"]


def store_stats(days=30):
    now = datetime.utcnow()
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    settled = Payment.objects.filter(status="succeeded")
    # Amounts are MySQL FLOAT columns; SUM() over them in SQL drifts by paise.
    # Summing the fetched values matches what the FastAPI dashboard reports.
    settled_rows = list(settled.values_list("amount", "payment_method", "updated_at", "created_at"))
    revenue = sum(row[0] for row in settled_rows)
    by_method = defaultdict(float)
    for amount, method, _, _ in settled_rows:
        by_method[method] += amount
    paid_orders = Order.objects.filter(payment_status="succeeded").count()

    # ---- trend: revenue by the day a payment settled, orders by the day placed ----
    by_day = {(start + timedelta(days=i)).date(): {"revenue": 0.0, "orders": 0} for i in range(days)}
    for amount, _, updated, created in settled_rows:
        day = (updated or created).date()
        if day in by_day:
            by_day[day]["revenue"] += amount
    for created in Order.objects.filter(created_at__gte=start).values_list("created_at", flat=True):
        if created.date() in by_day:
            by_day[created.date()]["orders"] += 1
    trend = [
        {"date": d.isoformat(), "revenue": round(v["revenue"], 2), "orders": v["orders"]}
        for d, v in sorted(by_day.items())
    ]

    status_counts = dict(Order.objects.values_list("order_status").annotate(count=Count("id")))

    live_items = OrderItem.objects.exclude(order__order_status="cancelled")
    top_sellers = list(
        live_items.values("product_id", "product_name")
        .annotate(units=Sum("quantity"), revenue=Sum(F("unit_price") * F("quantity")))
        .order_by("-units", "product_name")[:8]
    )
    categories = dict(Product.objects.values_list("id", "category"))
    category_sales = defaultdict(float)
    for row in live_items.values("product_id").annotate(revenue=Sum(F("unit_price") * F("quantity"))):
        category_sales[categories.get(row["product_id"], "deleted products")] += row["revenue"]

    products = Product.objects.all()
    emails_by_status = dict(Email.objects.values_list("status").annotate(count=Count("id")))

    return {
        "generated_at": now.isoformat() + "Z",
        "window_days": days,
        # ---- headline numbers ----
        "total_users": StoreUser.objects.count(),
        "users_by_role": {
            role: StoreUser.objects.filter(role=role).count() for role in ("admin", "staff", "customer")
        },
        "total_products": products.count(),
        "out_of_stock": products.filter(stock__lte=0).count(),
        "low_stock": products.filter(stock__gt=0, stock__lte=LOW_STOCK_THRESHOLD).count(),
        "total_orders": Order.objects.count(),
        "paid_orders": paid_orders,
        "pending_orders": status_counts.get("pending", 0),
        "awaiting_shipment": status_counts.get("paid", 0),
        "orders_by_status": status_counts,
        "total_revenue": round(revenue, 2),
        "window_revenue": round(sum(t["revenue"] for t in trend), 2),
        "average_order_value": round(revenue / paid_orders, 2) if paid_orders else 0.0,
        "revenue_by_method": {method: round(total, 2) for method, total in sorted(by_method.items())},
        # ---- breakdowns ----
        "trend": trend,
        # Most popular by the catalogue's popularity counter (units sold, incl. cancelled).
        "top_products": list(products.order_by("-popularity").values("name", "popularity", "stock")[:5]),
        "top_sellers": [
            {"product_id": r["product_id"], "name": r["product_name"], "units_sold": r["units"],
             "revenue": round(r["revenue"] or 0, 2)}
            for r in top_sellers
        ],
        "sales_by_category": sorted(
            ({"category": c, "revenue": round(v, 2)} for c, v in category_sales.items()),
            key=lambda row: row["revenue"], reverse=True,
        ),
        "low_stock_products": list(
            products.filter(stock__lte=LOW_STOCK_THRESHOLD).order_by("stock", "name")
            .values("id", "name", "category", "stock")[:10]
        ),
        "recent_orders": [
            {"id": o.id, "order_number": o.order_number, "customer": o.user.name, "total": o.total,
             "order_status": o.order_status, "payment_status": o.payment_status, "created_at": o.created_at}
            for o in Order.objects.select_related("user").order_by("-created_at", "-id")[:8]
        ],
        "notifications": {
            "total": Notification.objects.count(),
            "unread": Notification.objects.filter(is_read=False).count(),
        },
        "emails": {"total": sum(emails_by_status.values()), "by_status": emails_by_status},
    }


def chart_payload(stats):
    """Just the series Chart.js needs: labels + values, nothing pre-rendered."""
    def short(iso):
        day = datetime.fromisoformat(iso)
        return day.strftime("%-d %b") if os.name != "nt" else day.strftime("%#d %b")

    return {
        "trend": [
            {"label": short(t["date"]), "revenue": t["revenue"], "orders": t["orders"]}
            for t in stats["trend"]
        ],
        "status": [
            {"label": status.title(), "value": stats["orders_by_status"].get(status, 0)}
            for status in ORDER_STATUSES
        ],
        "category": [
            {"label": row["category"].title(), "value": row["revenue"]}
            for row in stats["sales_by_category"]
        ],
        "top": [
            {"label": row["name"], "value": row["units_sold"]}
            for row in stats["top_sellers"]
        ],
        "method": [
            {"label": method, "value": total} for method, total in stats["revenue_by_method"].items()
        ],
        "email": [
            {"label": status, "value": count} for status, count in stats["emails"]["by_status"].items()
        ],
    }
