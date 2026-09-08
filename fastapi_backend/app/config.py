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

    # Database — MySQL 8.0+ (Windows service "MySQL80"/"MySQL90", port 3306).
    # Configure via MYSQL_* vars in .env, or set a full DATABASE_URL directly.
    # Falls back to local SQLite only when no MySQL password is configured,
    # so the project still runs before credentials are set up.
    MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
    MYSQL_DB = os.getenv("MYSQL_DB", "ecommerce")

    if os.getenv("DATABASE_URL"):
        DATABASE_URL = os.environ["DATABASE_URL"]
    elif MYSQL_PASSWORD:
        DATABASE_URL = (
            f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
            f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"
        )
    else:
        DATABASE_URL = f"sqlite:///{(BASE_DIR / 'ecommerce.db').as_posix()}"

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
