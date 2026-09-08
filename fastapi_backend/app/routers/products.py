from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_staff_or_admin
from ..models import Product, User
from ..schemas import ProductCreate, ProductList, ProductOut, ProductUpdate

router = APIRouter(prefix="/products", tags=["Products"])


def _apply_filters(
    query,
    category: Optional[str],
    min_price: Optional[float],
    max_price: Optional[float],
    in_stock: Optional[bool],
    search: Optional[str],
):
    if category:
        query = query.filter(Product.category == category)
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)
    if in_stock:
        query = query.filter(Product.stock > 0)
    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))
    return query


SORT_OPTIONS = {
    "popularity": Product.popularity.desc(),
    "price_asc": Product.price.asc(),
    "price_desc": Product.price.desc(),
    "newest": Product.created_at.desc(),
}


@router.get("", response_model=ProductList)
def list_products(
    db: Session = Depends(get_db),
    category: Optional[str] = None,
    min_price: Optional[float] = Query(default=None, ge=0),
    max_price: Optional[float] = Query(default=None, ge=0),
    in_stock: Optional[bool] = None,
    search: Optional[str] = None,
    sort: str = Query(default="popularity", pattern="^(popularity|price_asc|price_desc|newest)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    query = _apply_filters(db.query(Product), category, min_price, max_price, in_stock, search)
    total = query.count()
    items = (
        query.order_by(SORT_OPTIONS[sort])
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ProductList(total=total, page=page, page_size=page_size, items=items)


@router.get("/category/{category}", response_model=ProductList)
def products_by_category(
    category: str,
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    query = db.query(Product).filter(Product.category == category)
    total = query.count()
    items = (
        query.order_by(Product.popularity.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ProductList(total=total, page=page, page_size=page_size, items=items)


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


# ---------- Product management: staff & admin (RBAC) ----------
@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    body: ProductCreate,
    db: Session = Depends(get_db),
    _staff: User = Depends(require_staff_or_admin),
):
    product = Product(**body.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.put("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    body: ProductUpdate,
    db: Session = Depends(get_db),
    _staff: User = Depends(require_staff_or_admin),
):
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    _staff: User = Depends(require_staff_or_admin),
):
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    db.delete(product)
    db.commit()
