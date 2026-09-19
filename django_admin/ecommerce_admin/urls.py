from django.contrib import admin
from django.urls import path

from analytics.reports import export_report, reports_index
from analytics.views import dashboard, dashboard_data

urlpatterns = [
    path("admin/", admin.site.urls),
    path("analytics/", dashboard, name="analytics-dashboard"),
    path("analytics/data/", dashboard_data, name="analytics-data"),
    path("reports/", reports_index, name="reports-index"),
    path("reports/<str:kind>.<str:fmt>", export_report, name="report-export"),
]

admin.site.site_header = "Smart E-Commerce Admin"
admin.site.site_title = "E-Commerce Admin"
admin.site.index_title = "Store Management & Analytics"
