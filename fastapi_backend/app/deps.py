"""Shared dependencies: current user resolution and role-based access control."""
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User, UserRole
from .security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials, expected_type="access")
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    # Checked on every request, not just at login: deactivating an account
    # takes effect immediately, even for a token issued moments earlier.
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Contact the store administrator.",
        )
    return user


def require_roles(*roles: UserRole):
    """Dependency factory: require_roles(UserRole.admin, UserRole.staff)."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(r.value for r in roles)}",
            )
        return user

    return checker


require_admin = require_roles(UserRole.admin)
require_staff_or_admin = require_roles(UserRole.admin, UserRole.staff)

SERVICE_TOKEN_HEADER = "X-Service-Token"


def staff_admin_or_service(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Staff/admin, or a trusted internal service.

    The Django admin runs as its own process with no store JWT, so it
    authenticates with SERVICE_API_TOKEN instead. This lets an order shipped
    from /admin/ go through the same endpoint as one shipped from the
    storefront — and therefore send the same email and live update.

    Returns the acting user, or None when the caller is the service. The
    token is optional: leave SERVICE_API_TOKEN unset and only JWTs work.
    """
    offered = request.headers.get(SERVICE_TOKEN_HEADER)
    if offered and settings.SERVICE_API_TOKEN:
        # compare_digest: don't leak the token one character at a time.
        if secrets.compare_digest(offered, settings.SERVICE_API_TOKEN):
            return None
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")

    user = get_current_user(credentials, db)
    if user.role not in (UserRole.admin, UserRole.staff):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires one of roles: admin, staff",
        )
    return user
