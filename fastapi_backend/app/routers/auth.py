import logging
from datetime import datetime
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
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
    create_oauth_state,
    create_refresh_token,
    decode_oauth_state,
    decode_token,
    hash_password,
    verify_password,
)
from ..services.sequence_service import next_sequence_value

logger = logging.getLogger(__name__)

GOOGLE_REDIRECT_URI = f"{settings.PUBLIC_URL}/api/auth/google/callback"
FACEBOOK_REDIRECT_URI = f"{settings.PUBLIC_URL}/api/auth/facebook/callback"

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


def _require_active(user: User) -> None:
    """Deactivated accounts can't get new tokens, whichever way they log in."""
    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="This account has been deactivated. Contact the store administrator.",
        )


def _get_or_create_social_user(db: Session, email: str, name: str, provider: str) -> User:
    user = db.query(User).filter(User.email == email.lower()).first()
    if user is not None:
        _require_active(user)
    if user is None:
        user = User(
            name=name or email.split("@")[0],
            email=email.lower(),
            password_hash=None,
            role=UserRole.customer,
            auth_provider=provider,
            customer_number=next_sequence_value(db, "customer_number"),
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
        customer_number=next_sequence_value(db, "customer_number"),
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
    _require_active(user)
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
    _require_active(user)

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


# ---------- Social login: Google ----------
def _verify_google_id_token(id_token: str) -> dict:
    import jwt as pyjwt
    from jwt import PyJWKClient

    signing_key = PyJWKClient("https://www.googleapis.com/oauth2/v3/certs").get_signing_key_from_jwt(id_token)
    claims = pyjwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.GOOGLE_CLIENT_ID,
        # Tolerate a bit of clock drift between this machine and Google's
        # servers — a freshly-issued token can otherwise look "not yet valid"
        # (iat in the future) or "expired" by a few seconds on an unsynced clock.
        leeway=60,
    )
    if claims.get("iss") not in ("https://accounts.google.com", "accounts.google.com"):
        raise ValueError("bad issuer")
    return claims


def _finish_social_login(db: Session, email: str, name: str, provider: str, want_json: bool):
    """Issue the JWT pair.

    want_json=True (opt in with ?json=1 on the /login redirect starter) returns
    the pair as plain JSON — useful for testing the flow directly in a browser
    or via a tool that follows redirects and can show you the response body.
    Default (want_json=False) is what the app's own "Sign in with Google/Facebook"
    button uses: redirect back to the SPA with the tokens in the URL fragment,
    since a top-level browser navigation can't hand a fetch() caller a JSON body.
    """
    user = _get_or_create_social_user(db, email, name, provider)
    pair = issue_tokens(db, user)
    if want_json:
        return pair
    fragment = urlencode(
        {"access_token": pair.access_token, "refresh_token": pair.refresh_token, "provider": provider}
    )
    return RedirectResponse(f"{settings.PUBLIC_URL}/#{fragment}")


def _social_error(message: str, want_json: bool = False):
    if want_json:
        raise HTTPException(status_code=401, detail=message)
    return RedirectResponse(f"{settings.PUBLIC_URL}/#{urlencode({'social_error': message})}")


def _mock_email(provider: str, external_id: str) -> str:
    """Synthesize a stable, unique, schema-valid email for a social account that
    didn't share a real one (e.g. a Facebook account with no email on file, or
    one that never granted the email permission). example.com is IANA-reserved
    for documentation and never resolves — nothing gets sent there."""
    return f"{provider}_{external_id}@{provider}.example.com"


# Browser flow (redirect URIs registered in the Google console):
#   {PUBLIC_URL}/api/auth/google/callback
# Pass ?json=1 to get the token pair back as JSON instead of a redirect to the
# SPA — handy for testing the flow directly (e.g. open the /login URL in a
# browser tab and read the JSON the callback lands on).
@router.get("/google/login")
def google_oauth_start(json: bool = Query(default=False)):
    if not (settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET):
        raise HTTPException(status_code=503, detail="Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.")
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": create_oauth_state(want_json=json),
        "prompt": "select_account",
    }
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


@router.get("/google/callback", response_model=None)
def google_oauth_callback(
    code: str = None, state: str = None, error: str = None, db: Session = Depends(get_db)
):
    state_payload = decode_oauth_state(state)
    want_json = bool(state_payload and state_payload.get("json"))

    if error or not code:
        return _social_error(error or "Google login was cancelled", want_json)
    if state_payload is None:
        return _social_error("Login session expired, please try again", want_json)
    try:
        with httpx.Client(timeout=15) as client:
            token_resp = client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            ).json()
            if "id_token" not in token_resp:
                raise RuntimeError(f"Google token exchange failed: {token_resp}")
        claims = _verify_google_id_token(token_resp["id_token"])
    except Exception:
        logger.exception("Google OAuth callback failed")  # full traceback in the server console
        return _social_error("Google login failed, please try again", want_json)

    email = (claims.get("email") or "").lower()
    if not email or not claims.get("email_verified", False):
        return _social_error("Google account has no verified email", want_json)
    return _finish_social_login(db, email, claims.get("name", ""), "google", want_json)


# Token-verification flow (SPA obtains an ID token via Google Identity Services)
@router.post("/social/google", response_model=TokenPair)
def google_token_login(body: SocialLoginRequest, db: Session = Depends(get_db)):
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google login not configured. Set GOOGLE_CLIENT_ID.")
    try:
        claims = _verify_google_id_token(body.id_token)
    except Exception:
        logger.exception("Google ID token verification failed")
        raise HTTPException(status_code=401, detail="Invalid Google ID token")
    email = (claims.get("email") or "").lower()
    if not email or not claims.get("email_verified", False):
        raise HTTPException(status_code=400, detail="Google account has no verified email")
    user = _get_or_create_social_user(db, email, claims.get("name", ""), "google")
    return issue_tokens(db, user)


# ---------- Social login: Facebook ----------
# Browser flow (redirect URI registered under Facebook Login > Settings >
# Valid OAuth Redirect URIs):  {PUBLIC_URL}/api/auth/facebook/callback
@router.get("/facebook/login")
def facebook_oauth_start(json: bool = Query(default=False)):
    if not (settings.FACEBOOK_APP_ID and settings.FACEBOOK_APP_SECRET):
        raise HTTPException(status_code=503, detail="Set FACEBOOK_APP_ID and FACEBOOK_APP_SECRET.")
    params = {
        "client_id": settings.FACEBOOK_APP_ID,
        "redirect_uri": FACEBOOK_REDIRECT_URI,
        "response_type": "code",
        "scope": "email,public_profile",
        "state": create_oauth_state(want_json=json),
    }
    return RedirectResponse("https://www.facebook.com/v19.0/dialog/oauth?" + urlencode(params))


@router.get("/facebook/callback", response_model=None)
def facebook_oauth_callback(
    code: str = None, state: str = None, error: str = None, db: Session = Depends(get_db)
):
    state_payload = decode_oauth_state(state)
    want_json = bool(state_payload and state_payload.get("json"))

    if error or not code:
        return _social_error(error or "Facebook login was cancelled", want_json)
    if state_payload is None:
        return _social_error("Login session expired, please try again", want_json)
    try:
        with httpx.Client(timeout=15) as client:
            token_resp = client.get(
                "https://graph.facebook.com/v19.0/oauth/access_token",
                params={
                    "client_id": settings.FACEBOOK_APP_ID,
                    "client_secret": settings.FACEBOOK_APP_SECRET,
                    "redirect_uri": FACEBOOK_REDIRECT_URI,
                    "code": code,
                },
            ).json()
            if "access_token" not in token_resp:
                raise RuntimeError(f"Facebook token exchange failed: {token_resp}")
            profile = client.get(
                "https://graph.facebook.com/me",
                params={"fields": "id,name,email", "access_token": token_resp["access_token"]},
            ).json()
    except Exception:
        logger.exception("Facebook OAuth callback failed")  # full traceback in the server console
        return _social_error("Facebook login failed, please try again", want_json)

    # Some Facebook accounts have no email on file, or the person declined the
    # email permission. Rather than block login, fall back to a synthetic,
    # stable, unique email tied to their Facebook user id.
    email = (profile.get("email") or "").lower() or _mock_email("facebook", profile["id"])
    return _finish_social_login(db, email, profile.get("name", ""), "facebook", want_json)


# Token-verification flow (SPA obtains an access token via the FB JS SDK)
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
        logger.exception("Facebook access token verification failed")
        raise HTTPException(status_code=401, detail="Invalid Facebook access token")

    # See the callback flow above: some Facebook accounts have no email on
    # file, or declined the permission — use a synthetic one rather than block.
    email = (profile.get("email") or "").lower() or _mock_email("facebook", profile["id"])
    user = _get_or_create_social_user(db, email, profile.get("name", ""), "facebook")
    return issue_tokens(db, user)
