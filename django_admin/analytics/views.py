from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render

from .stats import chart_payload, store_stats

RANGES = (7, 30, 90)


def _days(request):
    try:
        days = int(request.GET.get("days", 30))
    except ValueError:
        days = 30
    return days if days in RANGES else 30


@staff_member_required
def dashboard(request):
    """Analytics dashboard, rendered inside the admin's own chrome.
    Visit /analytics/ while logged into /admin/."""
    days = _days(request)
    stats = store_stats(days)
    context = {
        **admin.site.each_context(request),
        "title": "Store analytics",
        "stats": stats,
        "chart_data": chart_payload(stats),
        "days": days,
        "ranges": RANGES,
    }
    return render(request, "analytics/dashboard.html", context)


@staff_member_required
def dashboard_data(request):
    """The same numbers as JSON: /analytics/data/?days=30"""
    return JsonResponse(store_stats(_days(request)))
