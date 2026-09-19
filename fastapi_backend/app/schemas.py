from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, ConfigDict

from .models import OrderStatus, PaymentStatus, UserRole


# ---------- Auth ----------
class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class SocialLoginRequest(BaseModel):
    """ID token obtained on the frontend (Google Identity Services)."""
    id_token: str


class FacebookLoginRequest(BaseModel):
    """User access token obtained on the frontend from the Facebook JS SDK."""
    access_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_number: Optional[int] = None  # friendly "Customer #N", gapless
    name: str
    email: EmailStr
    role: UserRole
    auth_provider: str
    is_active: bool = True
    created_at: datetime


# ---------- Products ----------
class ProductBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    category: str = "general"
    price: float = Field(gt=0)
    stock: int = Field(ge=0)
    images: List[str] = []


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = Field(default=None, gt=0)
    stock: Optional[int] = Field(default=None, ge=0)
    images: Optional[List[str]] = None


class ProductOut(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    popularity: int
    created_at: datetime


class ProductList(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[ProductOut]


# ---------- Cart ----------
class CartAddRequest(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1)


class CartUpdateRequest(BaseModel):
    product_id: int
    quantity: int = Field(ge=1)


class CartItemOut(BaseModel):
    product_id: int
    name: str
    unit_price: float
    quantity: int
    item_total: float
    in_stock: bool


class CartOut(BaseModel):
    items: List[CartItemOut]
    cart_total: float
    tax_rate: float
    tax: float
    grand_total: float


# ---------- Orders / Checkout / Payments ----------
class CheckoutResponse(BaseModel):
    order_id: int
    amount: float
    currency: str
    payment_provider: str
    checkout_url: Optional[str] = None      # Stripe hosted checkout
    client_secret: Optional[str] = None     # PaymentIntent flow
    transaction_id: Optional[str] = None


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    product_name: str
    unit_price: float
    quantity: int


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    order_number: Optional[int] = None  # the paid order's friendly number
    amount: float
    currency: str
    payment_method: str
    transaction_id: Optional[str]
    status: PaymentStatus
    created_at: datetime


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_number: Optional[int] = None  # friendly "Order #N", gapless from creation
    user_id: int
    subtotal: float
    tax: float
    total: float
    payment_status: PaymentStatus
    order_status: OrderStatus
    created_at: datetime
    items: List[OrderItemOut]
    payment: Optional[PaymentOut] = None  # method + transaction id (stripe / cash)
    # What you may do with this order right now, so callers don't have to guess:
    allowed_next_statuses: List[str] = []   # valid values for PUT /orders/{id}/status
    can_confirm_payment: bool = False       # whether POST /payments/confirm/{id} applies


class AdminOrderOut(OrderOut):
    """Order with customer identity — for staff/admin listings."""
    user_name: str
    user_email: EmailStr


class AdminPaymentOut(PaymentOut):
    user_name: str
    user_email: EmailStr


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_number: str
    order_id: int
    order_number: Optional[int] = None
    user_id: int
    subtotal: float
    tax: float
    total: float
    currency: str
    issued_at: datetime


class AdminInvoiceOut(InvoiceOut):
    user_name: str
    user_email: EmailStr


class ReceiptOut(BaseModel):
    """Everything needed to render a payment receipt after checkout.

    Combines what this database knows (order, totals, invoice) with what only
    Stripe knows (cardholder name, card brand/last4, receipt email).
    """
    order_id: int
    order_number: Optional[int] = None
    order_status: OrderStatus
    payment_status: PaymentStatus
    amount: float
    currency: str
    payment_method: str
    transaction_id: Optional[str] = None
    paid_at: Optional[datetime] = None
    created_at: datetime
    invoice_number: Optional[str] = None
    items: List[OrderItemOut] = []
    # From Stripe, when the payment went through a card and details are available
    card_holder_name: Optional[str] = None
    card_brand: Optional[str] = None
    card_last4: Optional[str] = None
    receipt_email: Optional[EmailStr] = None
    receipt_url: Optional[str] = None
    # True while the Stripe webhook hasn't landed yet — the page polls until it has
    awaiting_confirmation: bool = False


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str


# ---------- Notifications ----------
class NotificationOut(BaseModel):
    """`read_status` / `timestamp` are the same values as `is_read` /
    `created_at` — both spellings are returned so either works for clients."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    title: str
    message: str
    order_id: Optional[int] = None
    is_read: bool
    read_status: bool
    created_at: datetime
    timestamp: datetime


class NotificationReadRequest(BaseModel):
    notification_ids: Optional[List[int]] = Field(
        default=None,
        description="Mark these notifications read. Omit (or send `all: true`) to mark every one read.",
        examples=[[12, 13]],
    )
    all: bool = Field(default=False, description="Mark every unread notification read.")


class NotificationReadResult(BaseModel):
    marked_read: int
    unread_count: int


class UnreadCount(BaseModel):
    unread_count: int


# ---------- Email ----------
class DevelopmentEmailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    to_email: str
    from_email: str
    subject: str
    body: str
    html_body: Optional[str] = None
    notification_type: Optional[str] = None
    status: str
    error: Optional[str] = None
    sent_at: Optional[datetime] = None
    is_read: bool = False
    created_at: datetime


class EmailReadRequest(BaseModel):
    email_ids: Optional[List[int]] = Field(
        default=None, description="Mark these emails read. Omit (or send `all: true`) to mark every one read.",
        examples=[[4, 5]],
    )
    all: bool = Field(default=False, description="Mark every unread email read.")


class InboxSummary(BaseModel):
    address: str
    total: int
    unread_count: int
    delivery: str  # how mail to this address is delivered, in plain words


class AdminEmailOut(DevelopmentEmailOut):
    user_id: int
    user_name: Optional[str] = None


# ---------- Admin ----------
class AdminUserOut(BaseModel):
    id: int
    customer_number: Optional[int] = None
    name: str
    email: str
    role: UserRole
    auth_provider: str
    is_active: bool
    created_at: datetime
    orders: int
    total_spent: float
    last_order_at: Optional[datetime] = None
