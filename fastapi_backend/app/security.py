"""Password hashing and JWT creation/verification."""
import uuid
from datetime import datetime, timedelta
from typing import Optional

import jwt
from passlib.context import CryptContext

from .config import settings

# pbkdf2_sha256: strong, pure-python (no native bcrypt wheel needed on Windows)
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _create_token(
    user_id: int, role: str, token_type: str, expires_delta: timedelta, jti: Optional[str] = None
) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    if jti:
        payload["jti"] = jti
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: int, role: str) -> str:
    return _create_token(
        user_id, role, "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )


def create_refresh_token(user_id: int, role: str) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at) so the caller can persist the token record."""
    jti = uuid.uuid4().hex
    delta = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    token = _create_token(user_id, role, "refresh", delta, jti=jti)
    return token, jti, datetime.utcnow() + delta


def decode_token(token: str, expected_type: str = "access") -> Optional[dict]:
    """Return the payload if the token is valid and of the expected type, else None."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != expected_type:
        return None
    return payload
