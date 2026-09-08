from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Sum
from django.http import JsonResponse

from .models import Order, Payment, Product, StoreUser


@staff_member_required
def dashboard(request):
    """Store-wide analytics summary (JSON). Visit /analytics/ while logged into /admin/."""
    revenue = (
        Payment.objects.filter(status="succeeded").aggregate(total=Sum("amount"))["total"] or 0
    )
    orders_by_status = dict(
        Order.objects.values_list("order_status").annotate(count=Count("id"))
    )
    top_products = list(
        Product.objects.order_by("-popularity").values("name", "popularity", "stock")[:5]
    )
    return JsonResponse(
        {
            "total_users": StoreUser.objects.count(),
            "total_products": Product.objects.count(),
            "out_of_stock": Product.objects.filter(stock=0).count(),
            "total_orders": Order.objects.count(),
            "orders_by_status": orders_by_status,
            "total_revenue": round(revenue, 2),
            "top_products": top_products,
        }
    )
