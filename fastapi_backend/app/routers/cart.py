from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import CartItem, Product, User
from ..schemas import CartAddRequest, CartItemOut, CartOut, CartUpdateRequest

router = APIRouter(prefix="/cart", tags=["Cart"])


def build_cart(db: Session, user_id: int) -> CartOut:
    items = (
        db.query(CartItem)
        .options(joinedload(CartItem.product))
        .filter(CartItem.user_id == user_id)
        .all()
    )
    out_items = []
    cart_total = 0.0
    for item in items:
        item_total = round(item.product.price * item.quantity, 2)
        cart_total += item_total
        out_items.append(
            CartItemOut(
                product_id=item.product_id,
                name=item.product.name,
                unit_price=item.product.price,
                quantity=item.quantity,
                item_total=item_total,
                in_stock=item.product.stock >= item.quantity,
            )
        )
    cart_total = round(cart_total, 2)
    tax = round(cart_total * settings.TAX_RATE, 2)
    return CartOut(
        items=out_items,
        cart_total=cart_total,
        tax_rate=settings.TAX_RATE,
        tax=tax,
        grand_total=round(cart_total + tax, 2),
    )


@router.get("", response_model=CartOut)
def view_cart(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return build_cart(db, user.id)


@router.post("/add", response_model=CartOut, status_code=status.HTTP_201_CREATED)
def add_to_cart(
    body: CartAddRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    product = db.get(Product, body.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    item = (
        db.query(CartItem)
        .filter(CartItem.user_id == user.id, CartItem.product_id == body.product_id)
        .first()
    )
    new_quantity = (item.quantity if item else 0) + body.quantity
    if product.stock < new_quantity:
        raise HTTPException(
            status_code=400, detail=f"Only {product.stock} unit(s) of '{product.name}' in stock"
        )
    if item:
        item.quantity = new_quantity
    else:
        db.add(CartItem(user_id=user.id, product_id=body.product_id, quantity=body.quantity))
    db.commit()
    return build_cart(db, user.id)


@router.put("/update", response_model=CartOut)
def update_cart_item(
    body: CartUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = (
        db.query(CartItem)
        .filter(CartItem.user_id == user.id, CartItem.product_id == body.product_id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Product not in cart")
    if item.product.stock < body.quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Only {item.product.stock} unit(s) of '{item.product.name}' in stock",
        )
    item.quantity = body.quantity
    db.commit()
    return build_cart(db, user.id)


@router.delete("/remove/{product_id}", response_model=CartOut)
def remove_from_cart(
    product_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    item = (
        db.query(CartItem)
        .filter(CartItem.user_id == user.id, CartItem.product_id == product_id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Product not in cart")
    db.delete(item)
    db.commit()
    return build_cart(db, user.id)
