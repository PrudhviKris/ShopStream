"""Exportable reports: orders, sales and users, as CSV or PDF.

Each report is defined once (rows + columns) and rendered into either format,
so the two can never drift apart. Staff-only, same as the dashboard.
"""
import csv
from datetime import datetime, timedelta

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.db.models import Count, F, Sum

from .models import Order, OrderItem, Payment, StoreUser
from .pdf import PdfReport

# Helvetica has no rupee sign, and a CSV opened in Excel is happier with a
# plain code too, so money is written as "INR 1,234.00" in exports.
def money(amount) -> str:
    whole, _, frac = f"{float(amount or 0):.2f}".partition(".")
    negative = whole.startswith("-")
    whole = whole.lstrip("-")
    if len(whole) > 3:  # Indian grouping: 12,34,567
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{'-' if negative else ''}INR {whole}.{frac}"


def _date_range(request):
    """(start, end, label) from ?from=YYYY-MM-DD&to=YYYY-MM-DD, defaulting to
    the last 30 days. `end` is exclusive so the last day is included whole."""
    today = datetime.utcnow().date()

    def parse(name, fallback):
        raw = request.GET.get(name)
        if not raw:
            return fallback
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return fallback

    start = parse("from", today - timedelta(days=29))
    end = parse("to", today)
    if end < start:
        start, end = end, start
    return (
        datetime.combine(start, datetime.min.time()),
        datetime.combine(end + timedelta(days=1), datetime.min.time()),
        f"{start:%Y-%m-%d} to {end:%Y-%m-%d}",
    )


# ---------- report definitions ----------

def orders_report(start, end):
    orders = (
        Order.objects.select_related("user")
        .filter(created_at__gte=start, created_at__lt=end)
        .order_by("-created_at", "-id")
    )
    payments = {p.order_id: p for p in Payment.objects.filter(order__created_at__gte=start,
                                                              order__created_at__lt=end)}
    rows = []
    for order in orders:
        payment = payments.get(order.id)
        rows.append([
            f"#{order.order_number or order.id}",
            f"{order.created_at:%Y-%m-%d %H:%M}",
            order.user.name,
            order.user.email,
            order.order_status,
            order.payment_status,
            payment.payment_method if payment else "—",
            payment.transaction_id if payment else "—",
            money(order.subtotal),
            money(order.tax),
            money(order.total),
        ])
    total = sum(o.total for o in orders)
    return {
        "columns": [
            ("Order", 55, "left"), ("Placed (UTC)", 95, "left"), ("Customer", 105, "left"),
            ("Email", 150, "left"), ("Status", 62, "left"), ("Payment", 62, "left"),
            ("Method", 70, "left"), ("Transaction", 130, "left"),
            ("Subtotal", 70, "right"), ("Tax", 55, "right"), ("Total", 75, "right"),
        ],
        "rows": rows,
        "summary": [f"{len(rows)} order(s)", f"Value: {money(total)}"],
    }


def sales_report(start, end):
    """Revenue that actually settled, by day."""
    payments = Payment.objects.filter(
        status="succeeded", updated_at__gte=start, updated_at__lt=end
    ).values_list("amount", "updated_at", "order_id")

    by_day = {}
    for amount, settled_at, order_id in payments:
        day = settled_at.date()
        bucket = by_day.setdefault(day, {"revenue": 0.0, "orders": set()})
        bucket["revenue"] += amount
        bucket["orders"].add(order_id)

    units_by_day = {}
    for row in (OrderItem.objects
                .filter(order__payment_status="succeeded", order__created_at__gte=start,
                        order__created_at__lt=end)
                .values("order__created_at__date")
                .annotate(units=Sum("quantity"))):
        units_by_day[row["order__created_at__date"]] = row["units"]

    rows, total_revenue, total_orders = [], 0.0, 0
    for day in sorted(by_day):
        bucket = by_day[day]
        orders = len(bucket["orders"])
        total_revenue += bucket["revenue"]
        total_orders += orders
        rows.append([
            day.isoformat(), str(orders), str(units_by_day.get(day, 0)),
            money(bucket["revenue"]),
            money(bucket["revenue"] / orders if orders else 0),
        ])
    return {
        "columns": [
            ("Date", 90, "left"), ("Paid orders", 80, "right"), ("Units sold", 80, "right"),
            ("Revenue", 110, "right"), ("Average order", 110, "right"),
        ],
        "rows": rows,
        "summary": [
            f"{total_orders} paid order(s) across {len(rows)} day(s)",
            f"Revenue: {money(total_revenue)}",
            f"Average order: {money(total_revenue / total_orders if total_orders else 0)}",
        ],
    }


def users_report(start, end):
    """Every account, with what they've bought (orders in the period)."""
    users = StoreUser.objects.order_by("-created_at", "-id")
    order_stats = {
        row["user_id"]: row
        for row in Order.objects.filter(created_at__gte=start, created_at__lt=end)
        .values("user_id").annotate(orders=Count("id"), last=F("created_at"))
    }
    spend = {
        row["order__user_id"]: row["spent"]
        for row in Payment.objects.filter(status="succeeded", order__created_at__gte=start,
                                          order__created_at__lt=end)
        .values("order__user_id").annotate(spent=Sum("amount"))
    }
    rows = []
    for user in users:
        stats = order_stats.get(user.id, {})
        rows.append([
            str(user.id), f"#{user.customer_number or '—'}", user.name, user.email,
            user.role, "active" if user.is_active else "deactivated",
            user.auth_provider, f"{user.created_at:%Y-%m-%d}",
            str(stats.get("orders", 0)), money(spend.get(user.id, 0)),
        ])
    by_role = {role: users.filter(role=role).count() for role in ("admin", "staff", "customer")}
    return {
        "columns": [
            ("ID", 40, "right"), ("Customer #", 70, "right"), ("Name", 120, "left"),
            ("Email", 175, "left"), ("Role", 60, "left"), ("State", 75, "left"),
            ("Sign-in", 60, "left"), ("Joined", 70, "left"),
            ("Orders", 55, "right"), ("Spent", 90, "right"),
        ],
        "rows": rows,
        "summary": [
            f"{len(rows)} account(s): " + ", ".join(f"{count} {role}" for role, count in by_role.items()),
            f"Deactivated: {users.filter(is_active=False).count()}",
        ],
    }


REPORTS = {
    "orders": ("Orders report", "Every order placed in the period", orders_report),
    "sales": ("Sales report", "Revenue that settled in the period, by day", sales_report),
    "users": ("User report", "All accounts, with their activity in the period", users_report),
}


# ---------- views ----------

@staff_member_required
def reports_index(request):
    start, end, label = _date_range(request)
    context = {
        **admin.site.each_context(request),
        "title": "Export reports",
        "reports": [(key, title, description) for key, (title, description, _fn) in REPORTS.items()],
        "date_from": start.date().isoformat(),
        "date_to": (end.date() - timedelta(days=1)).isoformat(),
        "range_label": label,
    }
    return render(request, "analytics/reports.html", context)


@staff_member_required
def export_report(request, kind, fmt):
    if kind not in REPORTS or fmt not in ("csv", "pdf"):
        raise Http404("Unknown report")

    title, description, build = REPORTS[kind]
    start, end, label = _date_range(request)
    report = build(start, end)
    filename = f"{kind}-report-{start:%Y%m%d}-{(end - timedelta(days=1)):%Y%m%d}.{fmt}"

    if fmt == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        # UTF-8 BOM so Excel opens accented names and symbols correctly.
        response.write("﻿")
        writer = csv.writer(response)
        writer.writerow([heading for heading, _w, _a in report["columns"]])
        writer.writerows(report["rows"])
        writer.writerow([])
        for line in report["summary"]:
            writer.writerow([line])
    else:
        document = PdfReport(
            title=title,
            subtitle=f"{description} · {label} · {len(report['rows'])} row(s)",
            columns=report["columns"],
        )
        document.add_rows(report["rows"])
        document.add_summary(report["summary"])
        response = HttpResponse(document.render(), content_type="application/pdf")

    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
