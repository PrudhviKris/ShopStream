import enum
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    staff = "staff"
    customer = "customer"


class OrderStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"
    return_requested = "return_requested"   # customer asked to return it
    returned = "returned"                   # return approved and refunded


# Which statuses an order may move to from where it is now — the single source
# of truth for the status endpoint, the "what can I do next" field on every
# order response, and the storefront's status box.
#
# "paid" is deliberately unreachable here: an order only becomes paid by
# confirming its payment (Stripe webhook, or POST /payments/confirm/{order_id}),
# which also settles the payment record and issues the invoice.
# "return_requested" and "returned" are missing on purpose too: a return is
# opened by the customer (POST /orders/{id}/return) and closed by staff
# approving or rejecting it (POST /returns/{id}/approve|reject), which also
# handles the refund. Flipping the status by hand would skip both.
ORDER_TRANSITIONS: dict = {
    OrderStatus.pending: [OrderStatus.cancelled],
    OrderStatus.paid: [OrderStatus.shipped, OrderStatus.cancelled],
    OrderStatus.shipped: [OrderStatus.delivered, OrderStatus.cancelled],
    OrderStatus.delivered: [],
    OrderStatus.cancelled: [],
    OrderStatus.return_requested: [],
    OrderStatus.returned: [],
}


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    refunded = "refunded"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=True)  # null for social-login users
    role = Column(Enum(UserRole), default=UserRole.customer, nullable=False)
    auth_provider = Column(String(50), default="local")  # local / google / facebook
    # Deactivated accounts keep their orders and history but can't log in, and
    # any token they already hold stops working on the next request.
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Friendly, gapless "Customer #N" for display — distinct from id (the real
    # primary key, which JWTs and every foreign key reference and must never
    # be renumbered or reused). Assigned in creation order via Sequence.
    customer_number = Column(Integer, unique=True, index=True, nullable=True)

    cart_items = relationship("CartItem", back_populates="user", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="user")
    notifications = relationship("Notification", back_populates="user")
    development_emails = relationship("DevelopmentEmail", back_populates="user", cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, default="")
    category = Column(String(100), index=True, default="general")
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0, nullable=False)
    images = Column(JSON, default=list)  # list of image URLs
    popularity = Column(Integer, default=0, nullable=False)  # units sold, drives sorting
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    reviews = relationship("Review", back_populates="product")

    @property
    def approved_reviews(self) -> list:
        return [r for r in self.reviews if r.status == ReviewStatus.approved]

    @property
    def average_rating(self) -> Optional[float]:
        approved = self.approved_reviews
        return round(sum(r.rating for r in approved) / len(approved), 1) if approved else None

    @property
    def review_count(self) -> int:
        return len(self.approved_reviews)


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_user_product"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, default=1, nullable=False)

    user = relationship("User", back_populates="cart_items")
    product = relationship("Product")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    # Friendly, gapless "Order #N" for display — distinct from id. See
    # User.customer_number for why id itself is never renumbered.
    order_number = Column(Integer, unique=True, index=True, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    subtotal = Column(Float, nullable=False)
    tax = Column(Float, default=0.0)
    total = Column(Float, nullable=False)
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.pending, nullable=False)
    order_status = Column(Enum(OrderStatus), default=OrderStatus.pending, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # When it reached the customer. The return window counts from here.
    delivered_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    payment = relationship("Payment", back_populates="order", uselist=False)
    return_requests = relationship(
        "ReturnRequest", back_populates="order", cascade="all, delete-orphan",
        order_by="ReturnRequest.created_at.desc()",
    )

    @property
    def allowed_next_statuses(self) -> list:
        """The statuses PUT /orders/{id}/status will accept for this order
        right now — so a caller never has to guess what's legal from here."""
        return [s.value for s in ORDER_TRANSITIONS.get(self.order_status, [])]

    @property
    def can_confirm_payment(self) -> bool:
        """True when POST /payments/confirm/{order_id} still applies — i.e. the
        money hasn't been settled yet. This is how an order reaches 'paid'."""
        return self.payment_status != PaymentStatus.succeeded

    # ---------- returns ----------
    @property
    def return_deadline(self):
        """Last moment a return can be opened, or None if it never could.

        Counted from delivery. Orders delivered before `delivered_at` existed
        fall back to when they were placed, which is the conservative choice:
        it can only make the window shorter, never longer.
        """
        from .config import settings

        if self.order_status not in (OrderStatus.delivered, OrderStatus.return_requested,
                                     OrderStatus.returned):
            return None
        start = self.delivered_at or self.created_at
        return start + timedelta(days=settings.RETURN_WINDOW_DAYS)

    @property
    def open_return(self):
        """The return request still waiting on a decision, if there is one."""
        return next((r for r in self.return_requests if r.status == ReturnStatus.pending), None)

    @property
    def can_request_return(self) -> bool:
        """Delivered, inside the window, and not already being returned."""
        if self.order_status != OrderStatus.delivered:
            return False
        if self.open_return is not None:
            return False
        deadline = self.return_deadline
        return deadline is not None and datetime.utcnow() <= deadline

    @property
    def return_status(self):
        """The newest return request's status, for list responses."""
        return self.return_requests[0].status.value if self.return_requests else None


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    product_name = Column(String(200), nullable=False)  # snapshot at purchase time
    unit_price = Column(Float, nullable=False)          # snapshot at purchase time
    quantity = Column(Integer, nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    # Friendly, gapless "Payment #N" — see User.customer_number.
    payment_number = Column(Integer, unique=True, index=True, nullable=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, unique=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="usd")
    payment_method = Column(String(50), default="stripe")
    transaction_id = Column(String(255), nullable=True, index=True)  # Stripe session/intent id
    status = Column(Enum(PaymentStatus), default=PaymentStatus.pending, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    order = relationship("Order", back_populates="payment")

    @property
    def order_number(self):
        """The related order's friendly display number, for API responses
        that show "Order #N" alongside a payment (kept consistent with the
        Orders page rather than showing the raw order_id)."""
        return self.order.order_number if self.order else None


class Sequence(Base):
    """Backs gapless, sequential display numbers (order/invoice/customer #).

    Unlike a MySQL AUTO_INCREMENT column, a delete or a rolled-back
    transaction never advances this counter — it only moves forward when a
    creation actually commits, so "Order #7" always means the 7th order ever
    successfully placed, with no numbers silently burned by test data or
    failed attempts.
    """

    __tablename__ = "sequences"

    name = Column(String(50), primary_key=True)
    value = Column(Integer, nullable=False, default=0)


class Role(Base):
    """Reference table for the platform's roles and what they may do."""

    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    name = Column(String(20), unique=True, nullable=False)  # matches User.role values
    description = Column(String(255), default="")


class RefreshToken(Base):
    """Every issued refresh token (local or social login). Enables revocation
    and rotation: a refresh token that is missing, revoked, or expired here
    is rejected even if its JWT signature is valid."""

    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True)
    jti = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User")


class Invoice(Base):
    """Issued automatically when an order's payment succeeds."""

    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String(30), unique=True, index=True, nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    subtotal = Column(Float, nullable=False)
    tax = Column(Float, default=0.0)
    total = Column(Float, nullable=False)
    currency = Column(String(10), default="usd")
    issued_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    order = relationship("Order")
    user = relationship("User")

    @property
    def order_number(self):
        return self.order.order_number if self.order else None


class NotificationType(str, enum.Enum):
    """Every kind of notification the platform sends, one per order event.

    Stored as a plain string column (not a DB enum) so rows written before
    these existed — the older generic "order" / "payment" / "info" — still load.
    """

    order_placed = "order_placed"          # card order created, awaiting payment
    order_confirmed = "order_confirmed"    # cash-on-delivery order accepted
    payment_successful = "payment_successful"
    payment_failed = "payment_failed"
    order_shipped = "order_shipped"
    order_delivered = "order_delivered"
    order_cancelled = "order_cancelled"
    return_requested = "return_requested"
    return_approved = "return_approved"
    return_rejected = "return_rejected"
    info = "info"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(50), default=NotificationType.info.value, index=True)
    title = Column(String(200), nullable=False)
    message = Column(Text, default="")
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # The order this is about, when there is one — lets the storefront jump
    # straight to it. Nullable and not a foreign key: deleting an order must
    # not delete (or be blocked by) the customer's notification history.
    order_id = Column(Integer, nullable=True, index=True)

    user = relationship("User", back_populates="notifications")

    # The spec's field names, exposed alongside the column names the rest of
    # the platform (and the Django admin) already use.
    @property
    def read_status(self) -> bool:
        return self.is_read

    @property
    def timestamp(self) -> datetime:
        return self.created_at


class EmailStatus(str, enum.Enum):
    stored = "stored"    # EMAIL_BACKEND=database: kept in the dev inbox, not sent
    queued = "queued"    # handed to the SMTP worker, not delivered yet
    sent = "sent"        # accepted by the SMTP server
    failed = "failed"    # SMTP refused or unreachable — see `error`
    skipped = "skipped"  # not sent over SMTP: placeholder address, or an unverified
                         # local account (the inbox copy is still readable in the app)


class DevelopmentEmail(Base):
    """Every outgoing email, whichever backend delivered it.

    Doubles as each user's in-app inbox (GET /dev/emails): the copy is always
    kept, so a user can read their mail even when the address can't receive
    it — a made-up address on a local account, or no mail server at all.
    With EMAIL_BACKEND=smtp it's also the outbox log recording whether each
    message actually went out.
    """

    __tablename__ = "development_emails"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    to_email = Column(String(320), nullable=False)
    from_email = Column(String(320), nullable=False)
    subject = Column(String(300), nullable=False)
    body = Column(Text, nullable=False)
    html_body = Column(Text, nullable=True)
    notification_type = Column(String(50), nullable=True, index=True)
    status = Column(String(20), default=EmailStatus.stored.value, nullable=False, index=True)
    error = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    # Inbox state — whether the recipient has opened it in the app.
    is_read = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="development_emails")


class ReturnStatus(str, enum.Enum):
    pending = "pending"      # waiting for staff to decide
    approved = "approved"    # accepted; the refund has been processed
    rejected = "rejected"    # declined, with a reason


class ReturnRequest(Base):
    """A customer asking to send an order back.

    Opened by the customer within the return window, closed by staff. An
    approval also refunds the payment and puts the stock back, so this row is
    the audit trail for the money: who decided, when, and what was refunded.
    """

    __tablename__ = "return_requests"

    id = Column(Integer, primary_key=True, index=True)
    # Friendly, gapless "Return #N" — see User.customer_number.
    return_number = Column(Integer, unique=True, index=True, nullable=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    reason = Column(String(60), nullable=False)          # one of RETURN_REASONS
    comment = Column(Text, nullable=True)                # optional detail from the customer
    status = Column(Enum(ReturnStatus), default=ReturnStatus.pending, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Filled in when staff decide.
    decided_at = Column(DateTime, nullable=True)
    decided_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    decision_note = Column(Text, nullable=True)
    refund_amount = Column(Float, nullable=True)
    refund_reference = Column(String(255), nullable=True)  # Stripe refund id, or a CASH-... ref

    order = relationship("Order", back_populates="return_requests")
    user = relationship("User", foreign_keys=[user_id])
    decided_by = relationship("User", foreign_keys=[decided_by_id])


class ReturnReason(str, enum.Enum):
    """What a customer may pick. Free text goes in `comment`, so the reason
    itself stays something the store can count and report on."""

    damaged = "damaged"
    wrong_item = "wrong_item"
    not_as_described = "not_as_described"
    missing_parts = "missing_parts"
    no_longer_needed = "no_longer_needed"
    other = "other"


RETURN_REASONS = {
    ReturnReason.damaged.value: "Arrived damaged",
    ReturnReason.wrong_item.value: "Wrong item sent",
    ReturnReason.not_as_described.value: "Not as described",
    ReturnReason.missing_parts.value: "Parts missing",
    ReturnReason.no_longer_needed.value: "No longer needed",
    ReturnReason.other.value: "Other",
}


class ReviewStatus(str, enum.Enum):
    pending = "pending"    # just submitted, awaiting moderation
    approved = "approved"  # visible on the product page and counted in the average
    rejected = "rejected"  # declined (spam, abuse, off-topic) — never shown


class Review(Base):
    """A star rating + comment a customer leaves on a product.

    Only counts towards the product's average and appears on its page once
    `status` is approved — see routers/reviews.py for who is allowed to
    submit one and how a submission is moderated.
    """

    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_review_user_product"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_review_rating_range"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1-5, enforced by the CHECK constraint above too
    comment = Column(Text, nullable=True)
    status = Column(Enum(ReviewStatus), default=ReviewStatus.pending, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User")
    product = relationship("Product", back_populates="reviews")
