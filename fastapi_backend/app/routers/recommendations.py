"""Personalized recommendations for one user.

See services/recommendation_service.py for the logic (purchase history +
browsing history + a "customers who bought this also bought" collaborative
signal, falling back to top-rated/trending for a user with no history yet).
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import User, UserRole
from ..schemas import ProductOut
from ..services import recommendation_service

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


@router.get("/{user_id}", response_model=List[ProductOut])
def recommendations_for_user(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(default=8, ge=1, le=50),
):
    """"Recommended for you" — your own recommendations, or (staff/admin
    only) any customer's, e.g. to sanity-check what they're being shown."""
    if user_id != user.id and user.role == UserRole.customer:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your recommendations")
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    return recommendation_service.recommended_for_user(db, target, limit=limit)
