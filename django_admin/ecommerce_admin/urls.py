from django.contrib import admin
from django.urls import path

from analytics.views import dashboard, dashboard_data

urlpatterns = [
    path("admin/", admin.site.urls),
    path("analytics/", dashboard, name="analytics-dashboard"),
    path("analytics/data/", dashboard_data, name="analytics-data"),
]

admin.site.site_header = "Smart E-Commerce Admin"
admin.site.site_title = "E-Commerce Admin"
admin.site.index_title = "Store Management & Analytics"
