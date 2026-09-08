from django.contrib import admin

from .models import Invoice, Order, OrderItem, Payment, Product, Role, StoreUser


@admin.register(StoreUser)
class StoreUserAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "email", "role", "auth_provider", "created_at")
    list_filter = ("role", "auth_provider")
    search_fields = ("name", "email")
    readonly_fields = ("password_hash", "created_at")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "category", "price", "stock", "popularity")
    list_filter = ("category",)
    search_fields = ("name",)
    list_editable = ("price", "stock")


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ("product", "product_name", "unit_price", "quantity")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "total", "payment_status", "order_status", "created_at")
    list_filter = ("order_status", "payment_status")
    inlines = [OrderItemInline]
    readonly_fields = ("subtotal", "tax", "total", "created_at")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "amount", "currency", "payment_method", "status", "created_at")
    list_filter = ("status", "payment_method")
    search_fields = ("transaction_id",)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "order", "user", "total", "currency", "issued_at")
    search_fields = ("invoice_number",)
    readonly_fields = ("invoice_number", "order", "user", "subtotal", "tax", "total", "issued_at")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "description")
