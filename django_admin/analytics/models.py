"""Read/write access to the store tables owned by the FastAPI service.

managed = False -> Django never creates or migrates these tables.

`created_at` columns carry a default so rows added through the admin match
what the FastAPI service writes (naive UTC, since USE_TZ is off).
"""
from datetime import datetime

from django.db import models


class StoreUser(models.Model):
    ROLE_CHOICES = [("admin", "Admin"), ("staff", "Staff"), ("customer", "Customer")]

    name = models.CharField(max_length=120)
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=255, null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="customer")
    auth_provider = models.CharField(max_length=50, default="local")
    is_active = models.BooleanField(
        default=True,
        verbose_name="active",
        help_text="Deactivated users keep their history but cannot log in, and any token they hold stops working.",
    )
    created_at = models.DateTimeField(default=datetime.utcnow)
    customer_number = models.IntegerField(null=True, blank=True, unique=True)

    class Meta:
        managed = False
        db_table = "users"
        verbose_name = "user"

    def __str__(self):
        return f"{self.name} <{self.email}>"


class Product(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100)
    price = models.FloatField()
    stock = models.IntegerField()
    images = models.JSONField(default=list, blank=True)  # empty photo list is valid
    popularity = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=datetime.utcnow)

    class Meta:
        managed = False
        db_table = "products"

    def __str__(self):
        return self.name


class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"), ("paid", "Paid"), ("shipped", "Shipped"),
        ("delivered", "Delivered"), ("cancelled", "Cancelled"),
        ("return_requested", "Return requested"), ("returned", "Returned"),
    ]

    # Mirrors ORDER_TRANSITIONS in fastapi_backend/app/models.py. "paid" is
    # never a manual move: an order becomes paid by confirming its payment.
    TRANSITIONS = {
        "pending": ["cancelled"],
        "paid": ["shipped", "cancelled"],
        "shipped": ["delivered", "cancelled"],
        "delivered": [],
        "cancelled": [],
    }

    order_number = models.IntegerField(null=True, blank=True, unique=True)
    user = models.ForeignKey(StoreUser, on_delete=models.DO_NOTHING, db_column="user_id")
    subtotal = models.FloatField()
    tax = models.FloatField()
    total = models.FloatField()
    payment_status = models.CharField(max_length=20)
    order_status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    created_at = models.DateTimeField(default=datetime.utcnow)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "orders"

    def __str__(self):
        return f"Order #{self.order_number or self.id} ({self.order_status})"

    def can_move_to(self, status):
        return status in self.TRANSITIONS.get(self.order_status, [])


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.DO_NOTHING, db_column="order_id",
                              related_name="items")
    product = models.ForeignKey(Product, on_delete=models.DO_NOTHING, db_column="product_id")
    product_name = models.CharField(max_length=200)
    unit_price = models.FloatField()
    quantity = models.IntegerField()

    class Meta:
        managed = False
        db_table = "order_items"


class Role(models.Model):
    name = models.CharField(max_length=20, unique=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        managed = False
        db_table = "roles"

    def __str__(self):
        return self.name


class Invoice(models.Model):
    invoice_number = models.CharField(max_length=30, unique=True)
    order = models.ForeignKey(Order, on_delete=models.DO_NOTHING, db_column="order_id")
    user = models.ForeignKey(StoreUser, on_delete=models.DO_NOTHING, db_column="user_id")
    subtotal = models.FloatField()
    tax = models.FloatField()
    total = models.FloatField()
    currency = models.CharField(max_length=10)
    issued_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "invoices"

    def __str__(self):
        return self.invoice_number


class Payment(models.Model):
    payment_number = models.IntegerField(null=True, blank=True, unique=True)
    order = models.ForeignKey(Order, on_delete=models.DO_NOTHING, db_column="order_id")
    amount = models.FloatField()
    currency = models.CharField(max_length=10)
    payment_method = models.CharField(max_length=50)
    transaction_id = models.CharField(max_length=255, null=True)
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField(default=datetime.utcnow)
    updated_at = models.DateTimeField(null=True)

    class Meta:
        managed = False
        db_table = "payments"

    def __str__(self):
        return f"Payment #{self.payment_number or self.id} for order #{self.order_id}"


class Notification(models.Model):
    TYPE_CHOICES = [
        ("order_placed", "Order placed"),
        ("order_confirmed", "Order confirmed"),
        ("payment_successful", "Payment successful"),
        ("payment_failed", "Payment failed"),
        ("order_shipped", "Order shipped"),
        ("order_delivered", "Order delivered"),
        ("order_cancelled", "Order cancelled"),
        ("info", "Info"),
        # written before event types existed
        ("order", "Order (legacy)"),
        ("payment", "Payment (legacy)"),
    ]

    user = models.ForeignKey(StoreUser, on_delete=models.DO_NOTHING, db_column="user_id",
                             related_name="notifications")
    type = models.CharField(max_length=50, choices=TYPE_CHOICES, default="info")
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    is_read = models.BooleanField(default=False, verbose_name="read")
    created_at = models.DateTimeField(default=datetime.utcnow)
    order_id = models.IntegerField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "notifications"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.title


class Email(models.Model):
    """Every outgoing email (the FastAPI `development_emails` table)."""

    STATUS_CHOICES = [
        ("stored", "Stored (database inbox)"),
        ("queued", "Queued for SMTP"),
        ("sent", "Sent"),
        ("failed", "Failed"),
        ("skipped", "Skipped (placeholder address)"),
    ]

    user = models.ForeignKey(StoreUser, on_delete=models.DO_NOTHING, db_column="user_id",
                             related_name="emails")
    to_email = models.CharField(max_length=320)
    from_email = models.CharField(max_length=320)
    subject = models.CharField(max_length=300)
    body = models.TextField()
    html_body = models.TextField(null=True, blank=True)
    notification_type = models.CharField(max_length=50, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="stored")
    error = models.TextField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    is_read = models.BooleanField(default=False, verbose_name="read by recipient")
    created_at = models.DateTimeField(default=datetime.utcnow)

    class Meta:
        managed = False
        db_table = "development_emails"
        ordering = ["-created_at", "-id"]
        verbose_name = "email"

    def __str__(self):
        return self.subject


class ReturnRequest(models.Model):
    """A customer's request to send an order back.

    Decisions are made through the store API (approving also refunds the
    payment and restocks the items), so this admin is read-only apart from
    the approve/decline actions.
    """

    STATUS_CHOICES = [("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")]
    REASON_CHOICES = [
        ("damaged", "Arrived damaged"), ("wrong_item", "Wrong item sent"),
        ("not_as_described", "Not as described"), ("missing_parts", "Parts missing"),
        ("no_longer_needed", "No longer needed"), ("other", "Other"),
    ]

    return_number = models.IntegerField(null=True, blank=True, unique=True)
    order = models.ForeignKey(Order, on_delete=models.DO_NOTHING, db_column="order_id",
                              related_name="return_requests")
    user = models.ForeignKey(StoreUser, on_delete=models.DO_NOTHING, db_column="user_id",
                             related_name="return_requests")
    reason = models.CharField(max_length=60, choices=REASON_CHOICES)
    comment = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(default=datetime.utcnow)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(StoreUser, on_delete=models.DO_NOTHING, db_column="decided_by_id",
                                   null=True, blank=True, related_name="return_decisions")
    decision_note = models.TextField(null=True, blank=True)
    refund_amount = models.FloatField(null=True, blank=True)
    refund_reference = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        managed = False
        db_table = "return_requests"
        ordering = ["-created_at", "-id"]
        verbose_name = "return request"

    def __str__(self):
        return f"Return #{self.return_number or self.id} for order #{self.order.order_number or self.order_id}"
