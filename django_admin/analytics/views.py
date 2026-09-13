from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render

from .stats import store_stats, with_chart_geometry

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
    context = {
        **admin.site.each_context(request),
        "title": "Store analytics",
        "stats": with_chart_geometry(store_stats(days)),
        "days": days,
        "ranges": RANGES,
    }
    return render(request, "analytics/dashboard.html", context)


@staff_member_required
def dashboard_data(request):
    """The same numbers as JSON: /analytics/data/?days=30"""
    return JsonResponse(store_stats(_days(request)))
