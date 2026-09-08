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
    """ID token obtained on the frontend from Auth0 (Google/Facebook connection)."""
    id_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    role: UserRole
    auth_provider: str
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
    amount: float
    currency: str
    payment_method: str
    transaction_id: Optional[str]
    status: PaymentStatus
    created_at: datetime


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    subtotal: float
    tax: float
    total: float
    payment_status: PaymentStatus
    order_status: OrderStatus
    created_at: datetime
    items: List[OrderItemOut]


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


# ---------- Notifications ----------
class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    title: str
    message: str
    is_read: bool
    created_at: datetime
