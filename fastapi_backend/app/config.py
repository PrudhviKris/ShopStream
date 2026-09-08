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


class Settings:
    APP_NAME = "Smart E-Commerce Platform"
    API_VERSION = "1.0.0"

    # Database — SQLite by default so the project runs out of the box.
    # Point at Postgres in production, e.g. postgresql+psycopg2://user:pass@host/db
    DATABASE_URL = os.getenv(
        "DATABASE_URL", f"sqlite:///{(BASE_DIR / 'ecommerce.db').as_posix()}"
    )

    # JWT
    JWT_SECRET_KEY = os.getenv(
        "JWT_SECRET_KEY", "dev-only-insecure-secret-change-me-in-production-0123456789"
    )
    JWT_ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

    # Auth0 social login (Google / Facebook are enabled inside the Auth0 dashboard)
    AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN", "")            # e.g. your-tenant.us.auth0.com
    AUTH0_CLIENT_ID = os.getenv("AUTH0_CLIENT_ID", "")      # SPA / native app client id

    # Stripe
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_CURRENCY = os.getenv("STRIPE_CURRENCY", "usd")
    CHECKOUT_SUCCESS_URL = os.getenv("CHECKOUT_SUCCESS_URL", "http://localhost:3000/checkout/success")
    CHECKOUT_CANCEL_URL = os.getenv("CHECKOUT_CANCEL_URL", "http://localhost:3000/checkout/cancel")

    # Cart
    TAX_RATE = float(os.getenv("TAX_RATE", "0.08"))  # 8% default, set 0 to disable

    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")


settings = Settings()
