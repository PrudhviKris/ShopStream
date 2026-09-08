"""Tests for the Django admin panel and analytics over the shared store schema."""
import json
from datetime import datetime

from django.contrib.auth.models import User as AdminUser
from django.test import TestCase
from django.urls import reverse

from .models import Invoice, Order, OrderItem, Payment, Product, Role, StoreUser


def make_store_data():
    """Seed the test database with a realistic slice of store data."""
    now = datetime.utcnow()
    customer = StoreUser.objects.create(
        name="Test Customer", email="cust@test.com", role="customer",
        auth_provider="local", created_at=now,
    )
    admin_user = StoreUser.objects.create(
        name="Test Admin", email="adm@test.com", role="admin",
        auth_provider="local", created_at=now,
    )
    p1 = Product.objects.create(
        name="Test Widget", description="", category="gadgets", price=10.0,
        stock=5, images=[], popularity=50, created_at=now,
    )
    p2 = Product.objects.create(
        name="Sold Out Thing", description="", category="gadgets", price=99.0,
        stock=0, images=[], popularity=200, created_at=now,
    )
    order = Order.objects.create(
        user=customer, subtotal=20.0, tax=1.6, total=21.6,
        payment_status="succeeded", order_status="paid", created_at=now,
    )
    OrderItem.objects.create(
        order=order, product=p1, product_name=p1.name, unit_price=10.0, quantity=2
    )
    Payment.objects.create(
        order=order, amount=21.6, currency="inr", payment_method="stripe-mock",
        transaction_id="mock_tx_1", status="succeeded", created_at=now, updated_at=now,
    )
    Invoice.objects.create(
        invoice_number="INV-TEST-00001", order=order, user=customer,
        subtotal=20.0, tax=1.6, total=21.6, currency="inr", issued_at=now,
    )
    for name in ("admin", "staff", "customer"):
        Role.objects.create(name=name, description=f"{name} role")
    return customer, admin_user, p1, p2, order


class StoreModelTests(TestCase):
    """The unmanaged models read and write the store schema correctly."""

    def test_crud_on_store_tables(self):
        customer, _, p1, _, order = make_store_data()
        self.assertEqual(StoreUser.objects.count(), 2)
        self.assertEqual(Product.objects.count(), 2)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.user.email, "cust@test.com")

        p1.stock = 42
        p1.save(update_fields=["stock"])
        self.assertEqual(Product.objects.get(pk=p1.pk).stock, 42)

        self.assertEqual(Invoice.objects.get(order=order).total, 21.6)
        self.assertSetEqual(
            set(Role.objects.values_list("name", flat=True)),
            {"admin", "staff", "customer"},
        )


class AdminSiteTests(TestCase):
    """The Django admin exposes every store table to a superuser."""

    @classmethod
    def setUpTestData(cls):
        make_store_data()
        cls.superuser = AdminUser.objects.create_superuser(
            "django-admin", "dj@test.com", "AdminTestPass123!"
        )

    def setUp(self):
        self.client.force_login(self.superuser)

    def test_admin_requires_login(self):
        self.client.logout()
        response = self.client.get("/admin/", follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_admin_index_lists_store_models(self):
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        for label in (b"Products", b"Orders", b"Payments", b"Invoices", b"Roles", b"Users"):
            self.assertIn(label, response.content)

    def test_changelists_render(self):
        for url_name in (
            "analytics_storeuser_changelist",
            "analytics_product_changelist",
            "analytics_order_changelist",
            "analytics_payment_changelist",
            "analytics_invoice_changelist",
            "analytics_role_changelist",
        ):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(f"admin:{url_name}"))
                self.assertEqual(response.status_code, 200)

    def test_order_detail_shows_line_items_inline(self):
        order = Order.objects.first()
        response = self.client.get(
            reverse("admin:analytics_order_change", args=[order.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Test Widget", response.content)

    def test_product_edit_through_admin(self):
        product = Product.objects.get(name="Test Widget")
        url = reverse("admin:analytics_product_change", args=[product.pk])
        response = self.client.post(
            url,
            {
                "name": "Renamed Widget",
                "description": "updated",
                "category": "gadgets",
                "price": "12.5",
                "stock": "7",
                "images": "[]",
                "popularity": "50",
                "created_at_0": "2026-09-08",
                "created_at_1": "00:00:00",
            },
            follow=False,
        )
        if response.status_code == 200:  # form re-rendered: surface the validation errors
            self.fail(f"admin form errors: {response.context['adminform'].form.errors.as_json()}")
        self.assertEqual(response.status_code, 302)  # saved -> redirect to changelist
        product.refresh_from_db()
        self.assertEqual(product.name, "Renamed Widget")
        self.assertEqual(product.stock, 7)


class AnalyticsDashboardTests(TestCase):
    """/analytics/ aggregates the store data and is staff-only."""

    @classmethod
    def setUpTestData(cls):
        make_store_data()
        cls.staff = AdminUser.objects.create_user(
            "staffer", "st@test.com", "StaffTestPass123!", is_staff=True
        )

    def test_requires_staff(self):
        response = self.client.get(reverse("analytics-dashboard"))
        self.assertEqual(response.status_code, 302)  # redirected to admin login

    def test_dashboard_aggregates(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("analytics-dashboard"))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["total_users"], 2)
        self.assertEqual(data["total_products"], 2)
        self.assertEqual(data["out_of_stock"], 1)
        self.assertEqual(data["total_orders"], 1)
        self.assertEqual(data["orders_by_status"], {"paid": 1})
        self.assertAlmostEqual(data["total_revenue"], 21.6)
        self.assertEqual(data["top_products"][0]["name"], "Sold Out Thing")
