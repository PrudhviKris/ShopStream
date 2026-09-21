from datetime import datetime

from django.conf import settings
from django.contrib import admin, messages
from django.db import transaction
from django.utils.html import format_html, format_html_join

from . import store_api
from .forms import ProductAdminForm
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


def _image_src(url: str) -> str:
    """Product images are stored as site-relative URLs (/media/... or /static/...)
    that the storefront serves; the admin runs on a different port, so point
    previews at the storefront's host."""
    if url.startswith("/"):
        return f"{settings.STORE_PUBLIC_URL}{url}"
    return url


# ---------- Users ----------

@admin.action(description="Activate selected users")
def activate_users(modeladmin, request, queryset):
    updated = queryset.update(is_active=True)
    modeladmin.message_user(request, f"{updated} user(s) activated.", messages.SUCCESS)


@admin.action(description="Deactivate selected users (blocks login immediately)")
def deactivate_users(modeladmin, request, queryset):
    # Locking every admin out of the store would leave nobody able to undo it
    # from the storefront side, so keep at least one active admin.
    remaining_admins = (
        StoreUser.objects.filter(role="admin", is_active=True).exclude(pk__in=queryset).count()
    )
    if remaining_admins == 0 and queryset.filter(role="admin", is_active=True).exists():
        modeladmin.message_user(
            request,
            "That would deactivate the last active admin. Promote or activate another admin first.",
            messages.ERROR,
        )
        return
    updated = queryset.update(is_active=False)
    modeladmin.message_user(
        request,
        f"{updated} user(s) deactivated. They can no longer log in, and tokens they already "
        "hold stop working on their next request.",
        messages.WARNING,
    )


@admin.register(StoreUser)
class StoreUserAdmin(admin.ModelAdmin):
    """View, edit, assign roles to, and activate/deactivate store users.

    The role column is the same one the API reads on every request, so a change
    here applies immediately — the user doesn't need to log in again.
    """

    list_display = ("id", "customer_number", "name", "email", "role", "is_active",
                    "auth_provider", "orders", "created_at")
    list_display_links = ("id", "name")
    list_editable = ("role", "is_active")
    list_filter = ("role", "is_active", "auth_provider")
    search_fields = ("name", "email")
    readonly_fields = ("password_hash", "created_at", "customer_number", "auth_provider", "orders")
    actions = [activate_users, deactivate_users]
    fieldsets = (
        ("Account", {"fields": ("name", "email", "customer_number", "auth_provider", "created_at")}),
        ("Access", {
            "fields": ("role", "is_active"),
            "description": "Roles: <b>admin</b> can do everything · <b>staff</b> manage products and "
                           "orders · <b>customer</b> can shop. Deactivated users keep their history "
                           "but cannot log in.",
        }),
        ("Credentials", {"fields": ("password_hash",), "classes": ("collapse",)}),
    )

    @admin.display(description="Orders")
    def orders(self, user):
        return user.order_set.count() if hasattr(user, "order_set") else Order.objects.filter(user=user).count()

    def has_delete_permission(self, request, obj=None):
        # Deleting a user would orphan their orders, payments and invoices;
        # deactivate instead.
        return False


# ---------- Products ----------

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Add, edit and delete products, update stock, and upload images."""

    form = ProductAdminForm
    list_display = ("id", "thumbnail", "name", "category", "price", "stock", "stock_state", "popularity")
    list_display_links = ("id", "name")
    list_filter = ("category",)
    search_fields = ("name", "description")
    list_editable = ("price", "stock")
    readonly_fields = ("popularity", "created_at", "image_gallery", "delete_state")
    fieldsets = (
        (None, {"fields": ("name", "description", "category")}),
        ("Pricing & stock", {"fields": ("price", "stock", "popularity")}),
        ("Images", {
            "fields": ("upload_image", "image_gallery", "images"),
            "description": "Upload a file, or edit the JSON list directly to use external URLs.",
        }),
        ("Meta", {"fields": ("created_at", "delete_state"), "classes": ("collapse",)}),
    )

    @admin.display(description="Stock state")
    def stock_state(self, product):
        if product.stock <= 0:
            return "⛔ Out of stock"
        if product.stock <= 5:
            return f"⚠ Low ({product.stock})"
        return "✓ In stock"

    @admin.display(description="")
    def thumbnail(self, product):
        images = product.images or []
        if not images:
            return "—"
        return format_html(
            '<img src="{}" alt="" style="height:38px;width:38px;object-fit:cover;border-radius:6px">',
            _image_src(images[0]),
        )

    def has_delete_permission(self, request, obj=None):
        # A product that appears on an order can't be deleted: order_items
        # references it, so the database would refuse with a foreign-key error
        # (and deleting it would rewrite order history). Retire it by setting
        # its stock to 0. Django applies this per object, so a bulk delete
        # that includes one is refused too.
        if obj is not None and OrderItem.objects.filter(product_id=obj.pk).exists():
            return False
        return super().has_delete_permission(request, obj)

    @admin.display(description="Deletable")
    def delete_state(self, product):
        if product.pk is None:
            return "—"
        ordered = OrderItem.objects.filter(product_id=product.pk).count()
        if ordered:
            return (f"No — on {ordered} order line(s). Deleting would rewrite order history; "
                    "set stock to 0 to retire it instead.")
        return "Yes — never ordered."

    @admin.display(description="Current images")
    def image_gallery(self, product):
        images = product.images or []
        if not images:
            return "No images yet."
        return format_html(
            '<div style="display:flex;gap:8px;flex-wrap:wrap">{}</div>',
            format_html_join(
                "",
                '<img src="{}" alt="" title="{}" style="height:90px;border-radius:8px;'
                'border:1px solid var(--hairline-color)">',
                ((_image_src(url), url) for url in images),
            ),
        )


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ("product", "product_name", "unit_price", "quantity")


class PaymentInline(admin.TabularInline):
    """The order's payment, read-only: amount, method, transaction id, status.

    Payments settle through Stripe's webhook or a staff confirmation, so they
    are never edited by hand here.
    """

    model = Payment
    extra = 0
    can_delete = False
    verbose_name_plural = "Payment"
    fields = ("amount", "currency", "payment_method", "transaction_id", "status", "created_at", "updated_at")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


# ---------- Order status actions ----------
#
# These call the store API (PUT /orders/{id}/status) so an order shipped from
# here does exactly what one shipped from the storefront does: notification,
# email, and the live WebSocket update to the customer and every connected
# staff member.
#
# If the API can't be reached, we fall back to writing the status and the
# notification directly — the operator's action shouldn't be lost because a
# service is down — and the admin message says which path was taken.

_STATUS_COPY = {
    "shipped": ("order_shipped", "Order {label} shipped", "Good news — order {label} is on its way!"),
    "delivered": ("order_delivered", "Order {label} delivered", "Order {label} has been delivered. Enjoy!"),
    "cancelled": ("order_cancelled", "Order {label} cancelled", "Order {label} has been cancelled."),
}


def _move_locally(order, status, label):
    """Fallback when the API is unreachable: write the status and the
    notification ourselves. No email and no live push — that logic lives in
    the API — so the caller warns the operator."""
    order.order_status = status
    order.save(update_fields=["order_status"])
    type_, title, message = _STATUS_COPY[status]
    Notification.objects.create(
        user_id=order.user_id, type=type_, title=title.format(label=label),
        message=message.format(label=label), order_id=order.id,
        is_read=False, created_at=datetime.utcnow(),
    )


def _move_orders(modeladmin, request, queryset, status):
    notified, offline, refused = [], [], []
    failures = set()

    for order in queryset:
        label = f"#{order.order_number or order.id}"
        if not order.can_move_to(status):
            refused.append(f"{label} ({order.order_status})")
            continue
        try:
            store_api.set_order_status(order.id, status)
            notified.append(label)
        except store_api.StoreApiUnavailable as exc:
            failures.add(str(exc))
            with transaction.atomic():
                _move_locally(order, status, label)
            offline.append(label)

    if notified:
        modeladmin.message_user(
            request,
            f"Marked {status}: {', '.join(notified)}. Each customer got the in-app "
            "notification, the email, and a live update on screen.",
            messages.SUCCESS,
        )
    if offline:
        modeladmin.message_user(
            request,
            f"Marked {status}: {', '.join(offline)} — but the store API was unreachable, so only "
            "the in-app notification was created (no email, no live update). "
            f"Reason: {'; '.join(sorted(failures))[:300]}",
            messages.WARNING,
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
    list_display = ("id", "order_number", "user", "total", "payment_status", "payment_method",
                    "order_status", "next_statuses", "created_at")
    list_display_links = ("id", "order_number")
    list_filter = ("order_status", "payment_status")
    search_fields = ("user__name", "user__email", "order_number")
    inlines = [OrderItemInline, PaymentInline]
    actions = [mark_shipped, mark_delivered, mark_cancelled]
    # Status is changed only through the actions above (which enforce the
    # allowed transitions); payment status only by confirming the payment.
    readonly_fields = ("order_number", "subtotal", "tax", "total", "payment_status", "order_status", "created_at")
    date_hierarchy = "created_at"

    @admin.display(description="Paid with")
    def payment_method(self, order):
        payment = order.payment_set.first()
        return payment.payment_method if payment else "—"

    @admin.display(description="Can move to")
    def next_statuses(self, order):
        allowed = order.TRANSITIONS.get(order.order_status, [])
        return ", ".join(allowed) if allowed else "final"


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
