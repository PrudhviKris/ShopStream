"""Read/write access to the store tables owned by the FastAPI service.

managed = False -> Django never creates or migrates these tables.
"""
from django.db import models


class StoreUser(models.Model):
    ROLE_CHOICES = [("admin", "Admin"), ("staff", "Staff"), ("customer", "Customer")]

    name = models.CharField(max_length=120)
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=255, null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="customer")
    auth_provider = models.CharField(max_length=50, default="local")
    created_at = models.DateTimeField()

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
    images = models.JSONField(default=list)
    popularity = models.IntegerField(default=0)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "products"

    def __str__(self):
        return self.name


class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"), ("paid", "Paid"), ("shipped", "Shipped"),
        ("delivered", "Delivered"), ("cancelled", "Cancelled"),
    ]

    user = models.ForeignKey(StoreUser, on_delete=models.DO_NOTHING, db_column="user_id")
    subtotal = models.FloatField()
    tax = models.FloatField()
    total = models.FloatField()
    payment_status = models.CharField(max_length=20)
    order_status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "orders"

    def __str__(self):
        return f"Order #{self.id} ({self.order_status})"


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


class Payment(models.Model):
    order = models.ForeignKey(Order, on_delete=models.DO_NOTHING, db_column="order_id")
    amount = models.FloatField()
    currency = models.CharField(max_length=10)
    payment_method = models.CharField(max_length=50)
    transaction_id = models.CharField(max_length=255, null=True)
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField(null=True)

    class Meta:
        managed = False
        db_table = "payments"

    def __str__(self):
        return f"Payment #{self.id} for order #{self.order_id}"
