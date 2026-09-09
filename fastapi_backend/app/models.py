import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
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


# Which statuses an order may move to from where it is now — the single source
# of truth for the status endpoint, the "what can I do next" field on every
# order response, and the storefront's status box.
#
# "paid" is deliberately unreachable here: an order only becomes paid by
# confirming its payment (Stripe webhook, or POST /payments/confirm/{order_id}),
# which also settles the payment record and issues the invoice.
ORDER_TRANSITIONS: dict = {
    OrderStatus.pending: [OrderStatus.cancelled],
    OrderStatus.paid: [OrderStatus.shipped, OrderStatus.cancelled],
    OrderStatus.shipped: [OrderStatus.delivered, OrderStatus.cancelled],
    OrderStatus.delivered: [],
    OrderStatus.cancelled: [],
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
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Friendly, gapless "Customer #N" for display — distinct from id (the real
    # primary key, which JWTs and every foreign key reference and must never
    # be renumbered or reused). Assigned in creation order via Sequence.
    customer_number = Column(Integer, unique=True, index=True, nullable=True)

    cart_items = relationship("CartItem", back_populates="user", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="user")
    notifications = relationship("Notification", back_populates="user")


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

    user = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    payment = relationship("Payment", back_populates="order", uselist=False)

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


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(50), default="info")  # order / payment / info
    title = Column(String(200), nullable=False)
    message = Column(Text, default="")
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="notifications")
