from django.contrib import admin
from django.urls import path

from analytics.views import dashboard

urlpatterns = [
    path("admin/", admin.site.urls),
    path("analytics/", dashboard, name="analytics-dashboard"),
]

admin.site.site_header = "Smart E-Commerce Admin"
admin.site.site_title = "E-Commerce Admin"
admin.site.index_title = "Store Management & Analytics"
