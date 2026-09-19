"""Application configuration loaded from environment variables (.env supported)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()



_PLACEHOLDERS = {
    "your-mysql-root-password",
    "sk_test_...",
    "whsec_...",
    "generate-a-long-random-secret",
    "your-google-client-id.apps.googleusercontent.com",
    "your-google-client-secret",
    "your-facebook-app-id",
    "your-facebook-app-secret",
}


def _env(key: str, default: str = "") -> str:
    value = os.getenv(key, default)
    return default if value in _PLACEHOLDERS else value


class Settings:
    APP_NAME = "Smart E-Commerce Platform"
    API_VERSION = "1.0.0"

    # Database — MySQL 8.0+ (Windows service "MySQL80"/"MySQL90", port 3306).
    # Configure via MYSQL_* vars in .env, or set a full DATABASE_URL directly.
    # Falls back to local SQLite only when no MySQL password is configured,
    # so the project still runs before credentials are set up.
    MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = _env("MYSQL_PASSWORD")
    MYSQL_DB = os.getenv("MYSQL_DB", "ecommerce")

    if os.getenv("DATABASE_URL"):
        DATABASE_URL = os.environ["DATABASE_URL"]
    elif MYSQL_PASSWORD:
        from urllib.parse import quote_plus

        # quote_plus: passwords may contain URL-special characters like @ or /
        DATABASE_URL = (
            f"mysql+pymysql://{quote_plus(MYSQL_USER)}:{quote_plus(MYSQL_PASSWORD)}"
            f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"
        )
    else:
        DATABASE_URL = f"sqlite:///{(BASE_DIR / 'ecommerce.db').as_posix()}"

    # JWT
    JWT_SECRET_KEY = _env(
        "JWT_SECRET_KEY", "dev-only-insecure-secret-change-me-in-production-0123456789"
    )
    JWT_ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

    # Public origin users reach the app through (ngrok URL when tunneling,
    # http://localhost:3000 otherwise). OAuth redirect URIs are built from it:
    #   {PUBLIC_URL}/api/auth/google/callback
    #   {PUBLIC_URL}/api/auth/facebook/callback
    PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:3000").rstrip("/")

    # Google Sign-In (console.cloud.google.com -> APIs & Services -> Credentials)
    GOOGLE_CLIENT_ID = _env("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = _env("GOOGLE_CLIENT_SECRET")
    # Facebook Login (developers.facebook.com -> your app); both naming styles accepted
    FACEBOOK_APP_ID = _env("FACEBOOK_APP_ID") or _env("FACEBOOK_CLIENT_ID")
    FACEBOOK_APP_SECRET = _env("FACEBOOK_APP_SECRET") or _env("FACEBOOK_CLIENT_SECRET")

    # Stripe
    STRIPE_SECRET_KEY = _env("STRIPE_SECRET_KEY")
    STRIPE_WEBHOOK_SECRET = _env("STRIPE_WEBHOOK_SECRET")
    STRIPE_CURRENCY = os.getenv("STRIPE_CURRENCY", "usd")
    # Where Stripe sends the shopper afterwards. Both land on the storefront's
    # receipt page (Stripe appends ?session_id=... to the success URL, which the
    # page reads back via GET /payments/receipt). Note the path deliberately
    # avoids "/checkout" — that prefix belongs to the API.
    CHECKOUT_SUCCESS_URL = os.getenv("CHECKOUT_SUCCESS_URL") or f"{PUBLIC_URL}/receipt"
    CHECKOUT_CANCEL_URL = os.getenv("CHECKOUT_CANCEL_URL") or f"{PUBLIC_URL}/receipt?cancelled=1"

    # Email
    # EMAIL_BACKEND picks how order emails are delivered:
    #   database — stored in development_emails and readable at GET /dev/emails
    #              (default: works with no mail server at all)
    #   smtp     — actually sent through SMTP_* below, and still logged there.
    # SendGrid and AWS SES are both SMTP relays, so "smtp" covers them too:
    #   SendGrid: SMTP_HOST=smtp.sendgrid.net  SMTP_PORT=587  SMTP_USE_TLS=true
    #             SMTP_USERNAME=apikey  SMTP_PASSWORD=<your SendGrid API key>
    #   AWS SES:  SMTP_HOST=email-smtp.<region>.amazonaws.com  SMTP_PORT=587
    #             SMTP_USE_TLS=true  SMTP_USERNAME/PASSWORD=<SES SMTP credentials>
    # EMAIL_FROM must be a sender address the provider has verified.
    EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "true").lower() == "true"
    EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "database").strip().lower()
    SMTP_HOST = os.getenv("SMTP_HOST", "127.0.0.1")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "false").lower() == "true"  # STARTTLS (port 587)
    SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() == "true"  # implicit TLS (port 465)
    SMTP_TIMEOUT = float(os.getenv("SMTP_TIMEOUT", "15"))
    # Email/password accounts never verify their address, so by default SMTP
    # doesn't send to them (a made-up bruce@gmail.com may be a stranger's
    # inbox). They still read every email in the in-app inbox. Set true once
    # local users register with addresses they really own.
    SMTP_SEND_TO_LOCAL_ACCOUNTS = os.getenv("SMTP_SEND_TO_LOCAL_ACCOUNTS", "false").lower() == "true"
    EMAIL_FROM = os.getenv("EMAIL_FROM", "no-reply@ecommerce.local")

    # Schema management
    # Dev convenience: create missing tables/columns at startup. Production
    # runs `alembic upgrade head` in the release step instead, so set this
    # false there and let migrations be the only thing that touches DDL.
    AUTO_CREATE_SCHEMA = os.getenv("AUTO_CREATE_SCHEMA", "true").lower() == "true"

    # Cart
    TAX_RATE = float(os.getenv("TAX_RATE", "0.08"))  # 8% default, set 0 to disable

    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")


settings = Settings()
