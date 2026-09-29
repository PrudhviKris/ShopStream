"""Reviews and ratings.

A customer submits a review (POST /reviews) on a product they have actually
received — this router checks that before anything is written. New reviews
start `pending`; staff approve or reject them here. Only `approved` reviews
count towards a product's average rating or appear on its page (see
GET /products/{id}/reviews in the products router).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import get_current_user, require_staff_or_admin
from ..models import Order, OrderItem, OrderStatus, Product, Review, ReviewStatus, User, UserRole
from ..schemas import AdminReviewOut, ReviewCreate, ReviewOut

router = APIRouter(prefix="/reviews", tags=["Reviews"])


def serialize(review: Review, admin: bool = False):
    """One shape for both audiences; the admin one adds the product name and
    the reviewer's email, for the moderation queue."""
    data = {
        "id": review.id,
        "user_id": review.user_id,
        "user_name": review.user.name if review.user else None,
        "product_id": review.product_id,
        "rating": review.rating,
        "comment": review.comment,
        "status": review.status,
        "created_at": review.created_at,
    }
    if not admin:
        return ReviewOut(**data)
    return AdminReviewOut(
        **data,
        user_email=review.user.email if review.user else "",
        product_name=review.product.name if review.product else "",
    )


def has_delivered_order(db: Session, user_id: int, product_id: int) -> bool:
    """True once at least one of this user's orders, containing this
    product, has actually been delivered — a "verified purchase" check."""
    return (
        db.query(OrderItem)
        .join(Order, OrderItem.order_id == Order.id)
        .filter(
            Order.user_id == user_id,
            Order.order_status == OrderStatus.delivered,
            OrderItem.product_id == product_id,
        )
        .first()
        is not None
    )


@router.post("", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
def create_review(
    body: ReviewCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Rate and review a product you've received.

    Two rules, enforced here: you must have a **delivered** order containing
    this product, and you may only review a product **once**. The review
    starts as `pending` and appears on the product page once staff approve it.
    """
    product = db.get(Product, body.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    if not has_delivered_order(db, user.id, body.product_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers who have received this product can review it.",
        )

    existing = (
        db.query(Review)
        .filter(Review.user_id == user.id, Review.product_id == body.product_id)
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="You have already reviewed this product.")

    review = Review(
        user_id=user.id,
        product_id=body.product_id,
        rating=body.rating,
        comment=(body.comment or "").strip() or None,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return serialize(review)


@router.get("/all", response_model=List[AdminReviewOut])
def all_reviews(
    db: Session = Depends(get_db),
    _staff: User = Depends(require_staff_or_admin),
    status_: Optional[ReviewStatus] = Query(default=None, alias="status", description="Filter by moderation state."),
    product_id: Optional[int] = Query(default=None, description="Only this product's reviews."),
):
    """Staff/admin: every review. `?status=pending` is the moderation queue."""
    query = db.query(Review).options(joinedload(Review.user), joinedload(Review.product))
    if status_ is not None:
        query = query.filter(Review.status == status_)
    if product_id is not None:
        query = query.filter(Review.product_id == product_id)
    reviews = query.order_by(Review.created_at.desc(), Review.id.desc()).all()
    return [serialize(r, admin=True) for r in reviews]


def _load(db: Session, review_id: int) -> Review:
    review = (
        db.query(Review)
        .options(joinedload(Review.user), joinedload(Review.product))
        .filter(Review.id == review_id)
        .first()
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


@router.post("/{review_id}/approve", response_model=AdminReviewOut)
def approve_review(
    review_id: int, db: Session = Depends(get_db), _staff: User = Depends(require_staff_or_admin)
):
    """Staff/admin: publish a review — it now counts in the product's average."""
    review = _load(db, review_id)
    review.status = ReviewStatus.approved
    db.commit()
    db.refresh(review)
    return serialize(review, admin=True)


@router.post("/{review_id}/reject", response_model=AdminReviewOut)
def reject_review(
    review_id: int, db: Session = Depends(get_db), _staff: User = Depends(require_staff_or_admin)
):
    """Staff/admin: decline a review (spam, abuse, off-topic) — it stays hidden."""
    review = _load(db, review_id)
    review.status = ReviewStatus.rejected
    db.commit()
    db.refresh(review)
    return serialize(review, admin=True)
