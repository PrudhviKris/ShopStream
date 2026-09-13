"""Tests for the Django admin panel and analytics over the shared store schema."""
import json
from datetime import datetime

from django.contrib.auth.models import User as AdminUser
from django.test import TestCase
from django.urls import reverse

from .models import Email, Invoice, Notification, Order, OrderItem, Payment, Product, Role, StoreUser
from .stats import store_stats
from .templatetags.store_extras import inr, inr_compact


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
    Notification.objects.create(
        user=customer, type="payment_successful", title="Payment successful",
        message="Payment for order #1 succeeded.", order_id=order.id, is_read=False, created_at=now,
    )
    Email.objects.create(
        user=customer, to_email=customer.email, from_email="no-reply@ecommerce.local",
        subject="Payment successful - order #1 confirmed", body="Hi Test Customer",
        html_body="<h1>Payment received</h1><script>alert(1)</script>",
        notification_type="payment_successful", status="stored", created_at=now,
    )
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
        for label in (b"Products", b"Orders", b"Payments", b"Invoices", b"Roles", b"Users",
                      b"Notifications", b"Emails"):
            self.assertIn(label, response.content)
        self.assertIn(reverse("analytics-dashboard").encode(), response.content)  # dashboard shortcut

    def test_changelists_render(self):
        for url_name in (
            "analytics_storeuser_changelist",
            "analytics_product_changelist",
            "analytics_order_changelist",
            "analytics_payment_changelist",
            "analytics_invoice_changelist",
            "analytics_role_changelist",
            "analytics_notification_changelist",
            "analytics_email_changelist",
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


class NotificationAndEmailAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer, _, _, _, cls.order = make_store_data()
        cls.superuser = AdminUser.objects.create_superuser("django-admin", "dj@test.com", "AdminTestPass123!")

    def setUp(self):
        self.client.force_login(self.superuser)

    def test_mark_notifications_read_action(self):
        note = Notification.objects.get()
        response = self.client.post(
            reverse("admin:analytics_notification_changelist"),
            {"action": "mark_read", "_selected_action": [note.pk]},
        )
        self.assertEqual(response.status_code, 302)
        note.refresh_from_db()
        self.assertTrue(note.is_read)

    def test_notifications_and_emails_cannot_be_added_by_hand(self):
        self.assertEqual(self.client.get(reverse("admin:analytics_notification_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:analytics_email_add")).status_code, 403)

    def test_email_detail_previews_html_in_a_sandbox(self):
        email = Email.objects.get()
        response = self.client.get(reverse("admin:analytics_email_change", args=[email.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<iframe sandbox=""', response.content)
        # The email markup is escaped into srcdoc, never injected into the admin page.
        self.assertNotIn(b"<script>alert(1)</script>", response.content)

    def test_email_log_filters_by_status(self):
        url = reverse("admin:analytics_email_changelist")
        self.assertContains(self.client.get(url, {"status__exact": "stored"}), "order #1 confirmed")
        self.assertNotContains(self.client.get(url, {"status__exact": "failed"}), "order #1 confirmed")


class OrderActionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer, _, _, _, cls.paid_order = make_store_data()
        cls.pending_order = Order.objects.create(
            user=cls.customer, subtotal=5, tax=0, total=5, payment_status="pending",
            order_status="pending", created_at=datetime.utcnow(),
        )
        cls.superuser = AdminUser.objects.create_superuser("django-admin", "dj@test.com", "AdminTestPass123!")

    def setUp(self):
        self.client.force_login(self.superuser)

    def _act(self, action, *orders):
        return self.client.post(
            reverse("admin:analytics_order_changelist"),
            {"action": action, "_selected_action": [o.pk for o in orders]},
            follow=True,
        )

    def test_ship_paid_order_notifies_customer(self):
        response = self._act("mark_shipped", self.paid_order)
        self.paid_order.refresh_from_db()
        self.assertEqual(self.paid_order.order_status, "shipped")
        note = Notification.objects.get(type="order_shipped")
        self.assertEqual((note.user_id, note.order_id, note.is_read), (self.customer.id, self.paid_order.id, False))
        self.assertContains(response, "Marked shipped")

    def test_disallowed_transitions_are_refused(self):
        response = self._act("mark_shipped", self.pending_order)  # pending must be paid first
        self.pending_order.refresh_from_db()
        self.assertEqual(self.pending_order.order_status, "pending")
        self.assertFalse(Notification.objects.filter(type="order_shipped").exists())
        self.assertContains(response, "Not allowed to move to shipped")

    def test_full_lifecycle_and_final_states(self):
        self._act("mark_shipped", self.paid_order)
        self._act("mark_delivered", self.paid_order)
        self._act("mark_cancelled", self.paid_order)  # delivered is final
        self.paid_order.refresh_from_db()
        self.assertEqual(self.paid_order.order_status, "delivered")

    def test_status_is_not_editable_in_the_form(self):
        response = self.client.get(reverse("admin:analytics_order_change", args=[self.paid_order.pk]))
        self.assertNotContains(response, 'name="order_status"')


class AnalyticsDashboardTests(TestCase):
    """/analytics/ aggregates the store data and is staff-only."""

    @classmethod
    def setUpTestData(cls):
        make_store_data()
        cls.staff = AdminUser.objects.create_user(
            "staffer", "st@test.com", "StaffTestPass123!", is_staff=True
        )

    def test_requires_staff(self):
        for name in ("analytics-dashboard", "analytics-data"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)  # redirected to admin login

    def test_dashboard_aggregates(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("analytics-data"))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["total_users"], 2)
        self.assertEqual(data["total_products"], 2)
        self.assertEqual(data["out_of_stock"], 1)
        self.assertEqual(data["total_orders"], 1)
        self.assertEqual(data["orders_by_status"], {"paid": 1})
        self.assertAlmostEqual(data["total_revenue"], 21.6)
        self.assertEqual(data["top_products"][0]["name"], "Sold Out Thing")
        top = data["top_sellers"][0]
        self.assertEqual((top["name"], top["units_sold"], top["revenue"]), ("Test Widget", 2, 20.0))
        self.assertEqual(data["sales_by_category"], [{"category": "gadgets", "revenue": 20.0}])
        self.assertEqual(data["users_by_role"], {"admin": 1, "staff": 0, "customer": 1})
        self.assertEqual(data["notifications"], {"total": 1, "unread": 1})
        self.assertEqual(data["emails"], {"total": 1, "by_status": {"stored": 1}})
        self.assertEqual(data["awaiting_shipment"], 1)

    def test_trend_window(self):
        stats = store_stats(7)
        self.assertEqual(len(stats["trend"]), 7)
        self.assertEqual(stats["trend"][-1]["orders"], 1)  # today's order
        self.assertAlmostEqual(stats["trend"][-1]["revenue"], 21.6)
        self.assertAlmostEqual(stats["window_revenue"], 21.6)
        self.client.force_login(self.staff)
        data = json.loads(self.client.get(reverse("analytics-data"), {"days": 90}).content)
        self.assertEqual(len(data["trend"]), 90)
        data = json.loads(self.client.get(reverse("analytics-data"), {"days": "bogus"}).content)
        self.assertEqual(len(data["trend"]), 30)  # anything unexpected falls back to 30

    def test_dashboard_page_renders(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("analytics-dashboard"), {"days": 7})
        self.assertEqual(response.status_code, 200)
        for text in ("Store analytics", "Revenue by day", "Orders by status", "Sales by category",
                     "Email delivery", "Top sellers", "Restock soon", "Recent orders",
                     "Last 7 days", "Show as table", "\u20b921.60"):
            self.assertContains(response, text)
        self.assertContains(response, 'id="an-points"')  # hover data for the trend chart


class CurrencyFormatTests(TestCase):
    def test_inr_uses_indian_grouping(self):
        self.assertEqual(inr(1234567.891), "\u20b912,34,567.89")
        self.assertEqual(inr(999), "\u20b9999.00")
        self.assertEqual(inr(159900, 0), "\u20b91,59,900")
        self.assertEqual(inr(-2500.5), "-\u20b92,500.50")

    def test_inr_compact(self):
        self.assertEqual(inr_compact(773297), "\u20b97.7L")
        self.assertEqual(inr_compact(12000000), "\u20b91.2Cr")
        self.assertEqual(inr_compact(9800), "\u20b99.8K")
        self.assertEqual(inr_compact(400000), "\u20b94L")
        self.assertEqual(inr_compact(250), "\u20b9250")
