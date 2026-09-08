import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import CartItem, Order, OrderItem, Payment, PaymentStatus, User
from ..schemas import CheckoutResponse
from ..services import stripe_service
from ..services.notification_service import notify

router = APIRouter(tags=["Checkout"])


@router.post("/checkout", response_model=CheckoutResponse)
def checkout(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    flow: str = Query(default="session", pattern="^(session|intent)$"),
    payment_method: str = Query(default="stripe", pattern="^(stripe|cash)$"),
):
    """Validate cart -> create order + payment record -> initialize payment.

    payment_method=stripe -> Stripe Checkout Session (flow=session, returns
        checkout_url) or PaymentIntent (flow=intent, returns client_secret)
    payment_method=cash   -> cash on delivery; a CASH-... transaction id is
        issued immediately and staff/admin confirm receipt on delivery via
        POST /payments/cash/confirm/{order_id}
    """
    cart_items = (
        db.query(CartItem)
        .options(joinedload(CartItem.product))
        .filter(CartItem.user_id == user.id)
        .all()
    )
    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    # 1. Validate stock for every line item
    for item in cart_items:
        if item.product.stock < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for '{item.product.name}' "
                f"(requested {item.quantity}, available {item.product.stock})",
            )

    # 2. Calculate totals
    subtotal = round(sum(i.product.price * i.quantity for i in cart_items), 2)
    tax = round(subtotal * settings.TAX_RATE, 2)
    total = round(subtotal + tax, 2)

    # 3. Create order with line-item snapshots, reserve stock
    order = Order(user_id=user.id, subtotal=subtotal, tax=tax, total=total)
    db.add(order)
    db.flush()

    line_items = []
    for item in cart_items:
        db.add(
            OrderItem(
                order_id=order.id,
                product_id=item.product_id,
                product_name=item.product.name,
                unit_price=item.product.price,
                quantity=item.quantity,
            )
        )
        item.product.stock -= item.quantity
        item.product.popularity += item.quantity
        line_items.append(
            {"name": item.product.name, "unit_price": item.product.price, "quantity": item.quantity}
        )
    if tax > 0:
        line_items.append({"name": "Tax", "unit_price": tax, "quantity": 1})

    # 4. Initialize the payment (Stripe session/intent, or a cash transaction id)
    if payment_method == "cash":
        provider = "cash"
        checkout_url = None
        stripe_data = {
            "transaction_id": f"CASH-{datetime.utcnow():%Y}-{uuid.uuid4().hex[:10].upper()}",
            "client_secret": None,
        }
    elif flow == "intent":
        provider = "stripe" if stripe_service.is_live() else "stripe-mock"
        checkout_url = None
        stripe_data = stripe_service.create_payment_intent(order.id, total, settings.STRIPE_CURRENCY)
    else:
        provider = "stripe" if stripe_service.is_live() else "stripe-mock"
        stripe_data = stripe_service.create_checkout_session(
            order.id, total, settings.STRIPE_CURRENCY, line_items
        )
        checkout_url = stripe_data.get("checkout_url")

    payment = Payment(
        order_id=order.id,
        amount=total,
        currency=settings.STRIPE_CURRENCY,
        payment_method=provider,
        transaction_id=stripe_data["transaction_id"],
        status=PaymentStatus.pending,
    )
    db.add(payment)

    # 5. Clear the cart
    for item in cart_items:
        db.delete(item)
    db.commit()

    if payment_method == "cash":
        message = (
            f"Order #{order.id} placed — cash on delivery. Keep your transaction ref "
            f"{stripe_data['transaction_id']}; pay {settings.STRIPE_CURRENCY.upper()} "
            f"{total:.2f} when your order arrives."
        )
    else:
        message = (
            f"Order #{order.id} created for {settings.STRIPE_CURRENCY.upper()} {total:.2f}. "
            "Complete payment to confirm."
        )
    notify(db, user.id, "order", "Order placed", message)

    return CheckoutResponse(
        order_id=order.id,
        amount=total,
        currency=settings.STRIPE_CURRENCY,
        payment_provider=provider,
        checkout_url=checkout_url,
        client_secret=stripe_data.get("client_secret"),
        transaction_id=stripe_data["transaction_id"],
    )
