from datetime import datetime

from django.contrib import admin, messages
from django.db import transaction
from django.utils.html import format_html

from .models import (
    Email,
    Invoice,
    Notification,
    Order,
    OrderItem,
    Payment,
    Product,
    Role,
    StoreUser,
)


@admin.register(StoreUser)
class StoreUserAdmin(admin.ModelAdmin):
    list_display = ("id", "customer_number", "name", "email", "role", "auth_provider", "created_at")
    list_filter = ("role", "auth_provider")
    search_fields = ("name", "email")
    readonly_fields = ("password_hash", "created_at", "customer_number")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "category", "price", "stock", "stock_state", "popularity")
    list_filter = ("category",)
    search_fields = ("name",)
    list_editable = ("price", "stock")

    @admin.display(description="Stock state")
    def stock_state(self, product):
        if product.stock <= 0:
            return "⛔ Out of stock"
        if product.stock <= 5:
            return f"⚠ Low ({product.stock})"
        return "✓ In stock"


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ("product", "product_name", "unit_price", "quantity")


# ---------- Order status actions ----------
#
# The storefront/API is the primary place to move orders along (it also sends
# the customer's email and pushes the live WebSocket update). These actions
# apply the same transition rules and write the same in-app notification, so
# an order changed here still shows up in the customer's notification inbox.

_STATUS_COPY = {
    "shipped": ("order_shipped", "Order {label} shipped", "Good news — order {label} is on its way!"),
    "delivered": ("order_delivered", "Order {label} delivered", "Order {label} has been delivered. Enjoy!"),
    "cancelled": ("order_cancelled", "Order {label} cancelled", "Order {label} has been cancelled."),
}


def _move_orders(modeladmin, request, queryset, status):
    moved, refused = [], []
    with transaction.atomic():
        for order in queryset.select_for_update():
            label = f"#{order.order_number or order.id}"
            if not order.can_move_to(status):
                refused.append(f"{label} ({order.order_status})")
                continue
            order.order_status = status
            order.save(update_fields=["order_status"])
            type_, title, message = _STATUS_COPY[status]
            Notification.objects.create(
                user_id=order.user_id, type=type_, title=title.format(label=label),
                message=message.format(label=label), order_id=order.id,
                is_read=False, created_at=datetime.utcnow(),
            )
            moved.append(label)
    if moved:
        modeladmin.message_user(
            request,
            f"Marked {status}: {', '.join(moved)}. Customers were notified in-app "
            "(emails and live updates are sent only when status is changed through the storefront/API).",
            messages.SUCCESS,
        )
    if refused:
        modeladmin.message_user(
            request, f"Not allowed to move to {status}: {', '.join(refused)}.", messages.WARNING
        )


@admin.action(description="Mark selected orders as shipped")
def mark_shipped(modeladmin, request, queryset):
    _move_orders(modeladmin, request, queryset, "shipped")


@admin.action(description="Mark selected orders as delivered")
def mark_delivered(modeladmin, request, queryset):
    _move_orders(modeladmin, request, queryset, "delivered")


@admin.action(description="Cancel selected orders")
def mark_cancelled(modeladmin, request, queryset):
    _move_orders(modeladmin, request, queryset, "cancelled")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "order_number", "user", "total", "payment_status", "order_status", "created_at")
    list_filter = ("order_status", "payment_status")
    search_fields = ("user__name", "user__email", "order_number")
    inlines = [OrderItemInline]
    actions = [mark_shipped, mark_delivered, mark_cancelled]
    # Status is changed only through the actions above (which enforce the
    # allowed transitions); payment status only by confirming the payment.
    readonly_fields = ("order_number", "subtotal", "tax", "total", "payment_status", "order_status", "created_at")
    date_hierarchy = "created_at"


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


# ---------- Notifications ----------

@admin.action(description="Mark selected notifications as read")
def mark_read(modeladmin, request, queryset):
    updated = queryset.update(is_read=True)
    modeladmin.message_user(request, f"{updated} notification(s) marked read.", messages.SUCCESS)


@admin.action(description="Mark selected notifications as unread")
def mark_unread(modeladmin, request, queryset):
    updated = queryset.update(is_read=False)
    modeladmin.message_user(request, f"{updated} notification(s) marked unread.", messages.SUCCESS)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "type", "user", "order_id", "is_read", "created_at")
    list_filter = ("type", "is_read")
    search_fields = ("title", "message", "user__name", "user__email")
    date_hierarchy = "created_at"
    actions = [mark_read, mark_unread]
    readonly_fields = ("user", "type", "title", "message", "order_id", "created_at")
    list_select_related = ("user",)

    def has_add_permission(self, request):
        return False  # notifications come from order events, not by hand


# ---------- Emails ----------

@admin.register(Email)
class EmailAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "to_email", "notification_type", "status", "is_read", "created_at", "sent_at")
    list_filter = ("status", "is_read", "notification_type")
    search_fields = ("subject", "to_email", "user__name")
    date_hierarchy = "created_at"
    list_select_related = ("user",)
    fields = ("user", "to_email", "from_email", "subject", "notification_type",
              "status", "error", "is_read", "created_at", "sent_at", "body", "preview")
    readonly_fields = fields

    @admin.display(description="HTML preview")
    def preview(self, email):
        if not email.html_body:
            return "—"
        # Sandboxed with no permissions: renders the email's markup without
        # letting it run script or touch the admin session.
        return format_html(
            '<iframe sandbox="" srcdoc="{}" style="width:100%;max-width:680px;height:520px;'
            'border:1px solid var(--hairline-color);border-radius:8px"></iframe>',
            email.html_body,
        )

    def has_add_permission(self, request):
        return False  # emails are an outbox log

    def has_change_permission(self, request, obj=None):
        return False
