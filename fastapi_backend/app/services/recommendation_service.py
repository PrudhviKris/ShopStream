"""Product recommendations — plain heuristics over real store data, no ML.

Three building blocks, each usable on its own (see routers/recommendations.py):

    similar_products      "Similar Products" / "You may also like" on a
                           product page — same category, ranked by rating
                           and popularity.
    trending_products      "Trending now" — recent views + recent purchases,
                           falling back to all-time popularity when the
                           catalog has too little recent activity.
    recommended_for_user   "Recommended for you" — blends the user's past
                           purchases, their browsing history (product_views)
                           and a simple "customers who bought X also bought
                           Y" collaborative signal; falls back to top-rated
                           + trending for a user with no history yet.

Everything excludes what the user has already purchased (never recommend
something they already own) and out-of-stock items.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..models import Order, OrderItem, OrderStatus, Product, ProductView, User

# Recent activity only counts within this window — a view from months ago
# says little about what's trending or what someone wants right now.
RECENT_DAYS = 30
# How many purchases a customer needs before their orders start weighing in.
_PURCHASED_STATUSES = (OrderStatus.paid, OrderStatus.shipped, OrderStatus.delivered, OrderStatus.returned)


def _purchased_product_ids(db: Session, user_id: int) -> set:
    """Every product this user has actually paid for — recommendations never
    suggest something they already own, and this also seeds "customers who
    bought X also bought Y"."""
    rows = (
        db.query(OrderItem.product_id)
        .join(Order, OrderItem.order_id == Order.id)
        .filter(Order.user_id == user_id, Order.order_status.in_(_PURCHASED_STATUSES))
        .distinct()
        .all()
    )
    return {r[0] for r in rows}


def _with_ratings(db: Session, product_ids) -> List[Product]:
    """Load these products with reviews eagerly, so .average_rating /
    .review_count (Product properties) don't each trigger their own query."""
    if not product_ids:
        return []
    products = (
        db.query(Product)
        .options(joinedload(Product.reviews))
        .filter(Product.id.in_(product_ids))
        .all()
    )
    by_id = {p.id: p for p in products}
    return [by_id[pid] for pid in product_ids if pid in by_id]


def top_rated_products(db: Session, limit: int = 8, exclude: Optional[set] = None) -> List[Product]:
    """Highest-rated products with at least one approved review, best first."""
    exclude = exclude or set()
    candidates = (
        db.query(Product)
        .options(joinedload(Product.reviews))
        .filter(Product.stock > 0)
        .all()
    )
    rated = [p for p in candidates if p.id not in exclude and p.review_count > 0]
    rated.sort(key=lambda p: (p.average_rating, p.review_count), reverse=True)
    return rated[:limit]


def similar_products(db: Session, product: Product, limit: int = 8) -> List[Product]:
    """Same category, in stock, ranked by rating then popularity. Backfilled
    with the catalog's overall best-sellers if the category is too small —
    a product page should never show an empty "Similar Products" section."""
    same_category = (
        db.query(Product.id)
        .filter(Product.category == product.category, Product.id != product.id, Product.stock > 0)
        .all()
    )
    ids = [r[0] for r in same_category]
    products = _with_ratings(db, ids)
    products.sort(key=lambda p: (p.average_rating or 0, p.popularity), reverse=True)

    if len(products) < limit:
        have = {p.id for p in products} | {product.id}
        backfill = (
            db.query(Product)
            .filter(Product.stock > 0, ~Product.id.in_(have))
            .order_by(Product.popularity.desc())
            .limit(limit - len(products))
            .all()
        )
        products += backfill
    return products[:limit]


def trending_products(db: Session, limit: int = 8) -> List[Product]:
    """Recent views + recent purchases (purchases count far more — buying is
    a much stronger signal than glancing at a product page), blended with
    all-time popularity so the list is never sparse on a quiet catalog."""
    since = datetime.utcnow() - timedelta(days=RECENT_DAYS)

    view_counts = dict(
        db.query(ProductView.product_id, func.count(ProductView.id))
        .filter(ProductView.viewed_at >= since)
        .group_by(ProductView.product_id)
        .all()
    )
    purchase_counts = dict(
        db.query(OrderItem.product_id, func.sum(OrderItem.quantity))
        .join(Order, OrderItem.order_id == Order.id)
        .filter(Order.created_at >= since, Order.order_status.in_(_PURCHASED_STATUSES))
        .group_by(OrderItem.product_id)
        .all()
    )
    scored_ids = set(view_counts) | set(purchase_counts)
    scores = {
        pid: view_counts.get(pid, 0) + purchase_counts.get(pid, 0) * 5
        for pid in scored_ids
    }

    in_stock_ids = {
        pid for (pid,) in db.query(Product.id).filter(Product.id.in_(scored_ids), Product.stock > 0)
    } if scored_ids else set()
    ranked = sorted(in_stock_ids, key=lambda pid: scores[pid], reverse=True)
    products = _with_ratings(db, ranked)

    if len(products) < limit:
        have = {p.id for p in products}
        backfill = (
            db.query(Product)
            .filter(Product.stock > 0, ~Product.id.in_(have))
            .order_by(Product.popularity.desc())
            .limit(limit - len(products))
            .all()
        )
        products += backfill
    return products[:limit]


def recommended_for_user(db: Session, user: User, limit: int = 8) -> List[Product]:
    """Blends three signals into one ranked list:

      * category affinity — categories the user has bought from or
        recently viewed, weighted purchases > views
      * collaborative filtering — "customers who bought the same things you
        did also bought…", the classic co-purchase signal, computed with
        plain SQL joins rather than a model
      * rating — a small nudge towards better-reviewed products among ties

    Falls back to top-rated + trending when the user has no purchase or
    browsing history yet (a brand new account), so "Recommended for you"
    is never empty.
    """
    owned = _purchased_product_ids(db, user.id)

    since = datetime.utcnow() - timedelta(days=RECENT_DAYS * 3)  # browsing signal lives a bit longer than "trending"
    viewed_categories = dict(
        db.query(Product.category, func.count(ProductView.id))
        .join(ProductView, ProductView.product_id == Product.id)
        .filter(ProductView.user_id == user.id, ProductView.viewed_at >= since)
        .group_by(Product.category)
        .all()
    )
    purchased_categories = dict(
        db.query(Product.category, func.count(OrderItem.id))
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, OrderItem.order_id == Order.id)
        .filter(Order.user_id == user.id, Order.order_status.in_(_PURCHASED_STATUSES))
        .group_by(Product.category)
        .all()
    )
    category_weight = {}
    for cat, n in viewed_categories.items():
        category_weight[cat] = category_weight.get(cat, 0) + n
    for cat, n in purchased_categories.items():
        category_weight[cat] = category_weight.get(cat, 0) + n * 5

    # "Customers who bought what you bought also bought…"
    co_purchase_counts: dict = {}
    if owned:
        other_buyer_ids = {
            r[0] for r in db.query(OrderItem.order_id)
            .join(Order, OrderItem.order_id == Order.id)
            .filter(OrderItem.product_id.in_(owned), Order.user_id != user.id,
                    Order.order_status.in_(_PURCHASED_STATUSES))
        }
        if other_buyer_ids:
            rows = (
                db.query(OrderItem.product_id, func.count(OrderItem.id))
                .filter(OrderItem.order_id.in_(other_buyer_ids), ~OrderItem.product_id.in_(owned))
                .group_by(OrderItem.product_id)
                .all()
            )
            co_purchase_counts = dict(rows)

    candidate_ids = set(co_purchase_counts) | {
        pid for (pid,) in db.query(Product.id)
        .filter(Product.category.in_(category_weight.keys()), Product.stock > 0, ~Product.id.in_(owned))
    } if category_weight or co_purchase_counts else set()
    candidate_ids -= owned

    if not candidate_ids:
        # Cold start: no purchases, no views. Best-reviewed first, then
        # whatever's trending, deduplicated, so a new account still sees
        # a sensible, populated section instead of nothing.
        fallback = top_rated_products(db, limit=limit, exclude=owned)
        if len(fallback) < limit:
            seen = {p.id for p in fallback} | owned
            for p in trending_products(db, limit=limit):
                if p.id not in seen:
                    fallback.append(p)
                    seen.add(p.id)
                if len(fallback) >= limit:
                    break
        return fallback[:limit]

    products = _with_ratings(db, [pid for pid in candidate_ids])
    products = [p for p in products if p.stock > 0]

    def score(p: Product) -> float:
        return (
            co_purchase_counts.get(p.id, 0) * 3
            + category_weight.get(p.category, 0)
            + (p.average_rating or 0)
        )

    products.sort(key=score, reverse=True)

    if len(products) < limit:
        seen = {p.id for p in products} | owned
        for p in top_rated_products(db, limit=limit, exclude=seen):
            if p.id not in seen:
                products.append(p)
                seen.add(p.id)
            if len(products) >= limit:
                break
    return products[:limit]
