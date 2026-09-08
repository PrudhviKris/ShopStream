from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import RefreshToken, User, UserRole
from ..schemas import (
    FacebookLoginRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    SocialLoginRequest,
    TokenPair,
    UserOut,
)
from ..security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def issue_tokens(db: Session, user: User) -> TokenPair:
    """Create an access + refresh pair and persist the refresh token so it can
    be rotated and revoked. Used for EVERY login: local and social alike."""
    refresh_token, jti, expires_at = create_refresh_token(user.id, user.role.value)
    db.add(RefreshToken(jti=jti, user_id=user.id, expires_at=expires_at))
    db.commit()
    return TokenPair(
        access_token=create_access_token(user.id, user.role.value),
        refresh_token=refresh_token,
    )


def _get_or_create_social_user(db: Session, email: str, name: str, provider: str) -> User:
    user = db.query(User).filter(User.email == email.lower()).first()
    if user is None:
        user = User(
            name=name or email.split("@")[0],
            email=email.lower(),
            password_hash=None,
            role=UserRole.customer,
            auth_provider=provider,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


# ---------- Email / password ----------
@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email.lower()).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        name=body.name,
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        role=UserRole.customer,
        auth_provider="local",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return issue_tokens(db, user)


@router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return issue_tokens(db, user)


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    payload = decode_token(body.refresh_token, expected_type="refresh")
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    record = db.query(RefreshToken).filter(RefreshToken.jti == payload.get("jti")).first()
    if record is None or record.revoked or record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Refresh token revoked or unknown")

    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    record.revoked = True  # rotation: each refresh token is single-use
    db.commit()
    return issue_tokens(db, user)


@router.post("/logout")
def logout(body: RefreshRequest, db: Session = Depends(get_db)):
    """Revoke a refresh token (the access token simply expires)."""
    payload = decode_token(body.refresh_token, expected_type="refresh")
    if payload:
        db.query(RefreshToken).filter(RefreshToken.jti == payload.get("jti")).update(
            {RefreshToken.revoked: True}
        )
        db.commit()
    return {"logged_out": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


# ---------- Social login: direct Google Sign-In ----------
#
# Get a client id at https://console.cloud.google.com/apis/credentials
# (OAuth client ID, type "Web application") and set GOOGLE_CLIENT_ID in .env.
# Frontend uses Google Identity Services to obtain an ID token and POSTs it here.
@router.post("/social/google", response_model=TokenPair)
def google_login(body: SocialLoginRequest, db: Session = Depends(get_db)):
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google login not configured. Set GOOGLE_CLIENT_ID.")

    import jwt as pyjwt
    from jwt import PyJWKClient

    try:
        signing_key = PyJWKClient("https://www.googleapis.com/oauth2/v3/certs").get_signing_key_from_jwt(body.id_token)
        claims = pyjwt.decode(
            body.id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.GOOGLE_CLIENT_ID,
        )
        if claims.get("iss") not in ("https://accounts.google.com", "accounts.google.com"):
            raise ValueError("bad issuer")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Google ID token")

    email = (claims.get("email") or "").lower()
    if not email or not claims.get("email_verified", False):
        raise HTTPException(status_code=400, detail="Google account has no verified email")
    user = _get_or_create_social_user(db, email, claims.get("name", ""), "google")
    return issue_tokens(db, user)


# ---------- Social login: direct Facebook Login ----------
#
# Create an app at https://developers.facebook.com/apps (add "Facebook Login"),
# set FACEBOOK_APP_ID and FACEBOOK_APP_SECRET in .env. Frontend uses the FB JS
# SDK to obtain a user access token and POSTs it here.
@router.post("/social/facebook", response_model=TokenPair)
def facebook_login(body: FacebookLoginRequest, db: Session = Depends(get_db)):
    if not (settings.FACEBOOK_APP_ID and settings.FACEBOOK_APP_SECRET):
        raise HTTPException(
            status_code=503,
            detail="Facebook login not configured. Set FACEBOOK_APP_ID and FACEBOOK_APP_SECRET.",
        )
    app_token = f"{settings.FACEBOOK_APP_ID}|{settings.FACEBOOK_APP_SECRET}"
    try:
        with httpx.Client(timeout=10) as client:
            debug = client.get(
                "https://graph.facebook.com/debug_token",
                params={"input_token": body.access_token, "access_token": app_token},
            ).json()
            data = debug.get("data", {})
            if not data.get("is_valid") or data.get("app_id") != settings.FACEBOOK_APP_ID:
                raise ValueError("invalid token")
            profile = client.get(
                "https://graph.facebook.com/me",
                params={"fields": "id,name,email", "access_token": body.access_token},
            ).json()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Facebook access token")

    email = (profile.get("email") or "").lower()
    if not email:
        raise HTTPException(
            status_code=400,
            detail="Facebook account has no email (grant the email permission)",
        )
    user = _get_or_create_social_user(db, email, profile.get("name", ""), "facebook")
    return issue_tokens(db, user)
