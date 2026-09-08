from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import User, UserRole
from ..schemas import (
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


def _issue_tokens(user: User) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user.id, user.role.value),
        refresh_token=create_refresh_token(user.id, user.role.value),
    )


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
    return _issue_tokens(user)


@router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return _issue_tokens(user)


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    payload = decode_token(body.refresh_token, expected_type="refresh")
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return _issue_tokens(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


# ---------- Social login via Auth0 (Google / Facebook) ----------
#
# Frontend flow:
#   1. User clicks "Login with Google/Facebook" -> Auth0 Universal Login.
#   2. Auth0 returns an ID token (RS256, signed by the tenant's JWKS).
#   3. Frontend POSTs the ID token here; we verify it against Auth0's JWKS,
#      auto-provision the user if new, and issue our own JWT pair.
@router.post("/social/auth0", response_model=TokenPair)
def social_login(body: SocialLoginRequest, db: Session = Depends(get_db)):
    if not settings.AUTH0_DOMAIN or not settings.AUTH0_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Auth0 not configured. Set AUTH0_DOMAIN and AUTH0_CLIENT_ID.",
        )

    import jwt as pyjwt
    from jwt import PyJWKClient

    jwks_url = f"https://{settings.AUTH0_DOMAIN}/.well-known/jwks.json"
    try:
        signing_key = PyJWKClient(jwks_url).get_signing_key_from_jwt(body.id_token)
        claims = pyjwt.decode(
            body.id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.AUTH0_CLIENT_ID,
            issuer=f"https://{settings.AUTH0_DOMAIN}/",
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Auth0 ID token")

    email = (claims.get("email") or "").lower()
    if not email:
        raise HTTPException(status_code=400, detail="Auth0 token has no email claim")

    # sub looks like "google-oauth2|1234" or "facebook|5678"
    provider = "auth0-" + claims.get("sub", "unknown|").split("|")[0]

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = User(
            name=claims.get("name") or email.split("@")[0],
            email=email,
            password_hash=None,
            role=UserRole.customer,
            auth_provider=provider,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return _issue_tokens(user)
