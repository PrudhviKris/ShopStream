"""Django admin/analytics service.

Reads the SAME database the FastAPI service writes to (SQLite by default;
set DATABASE_URL-equivalent env vars for Postgres in production). The store
models are managed=False so Django never migrates FastAPI-owned tables —
`migrate` only creates Django's own auth/session tables.
"""
import importlib.util
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-in-production")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["*"] if DEBUG else [
    host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

if not DEBUG:
    if SECRET_KEY == "dev-only-change-in-production":
        raise RuntimeError("Set DJANGO_SECRET_KEY before running with DJANGO_DEBUG=0.")
    # Behind a TLS terminator (nginx, a load balancer, a tunnel) these make
    # Django trust the forwarded scheme and keep cookies off plain HTTP.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = os.getenv("DJANGO_SECURE_COOKIES", "1") == "1"
    CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"
    # Both off by default: the compose stack serves plain HTTP on localhost,
    # and turning either on without real TLS locks you out of the admin.
    SECURE_SSL_REDIRECT = os.getenv("DJANGO_SSL_REDIRECT", "0") == "1"
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_HSTS_SECONDS", "0"))  # set once HTTPS is certain
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "analytics",
    "ecommerce_admin",  # the store models (managed=False) and test runner
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves the admin's CSS and the vendored Chart.js under gunicorn, where
    # there is no runserver static handler. Optional: development without it
    # installed still works.
    *(["whitenoise.middleware.WhiteNoiseMiddleware"] if importlib.util.find_spec("whitenoise") else []),
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ecommerce_admin.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # project-level overrides (admin index)
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ecommerce_admin.wsgi.application"

# Shared store database (FastAPI owns these tables) + Django's own tables.
# Reads the same MYSQL_* variables as the FastAPI service (from its .env);
# falls back to the shared SQLite file when no MySQL password is configured.
def _load_fastapi_env():
    env_file = BASE_DIR.parent / "fastapi_backend" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


_load_fastapi_env()

_mysql_password = os.getenv("MYSQL_PASSWORD", "")
if _mysql_password == "your-mysql-root-password":  # untouched .env.example placeholder
    _mysql_password = ""

if _mysql_password:
    import pymysql

    pymysql.install_as_MySQLdb()  # lets Django's mysql backend use PyMySQL
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.getenv("MYSQL_DB", "ecommerce"),
            "USER": os.getenv("MYSQL_USER", "root"),
            "PASSWORD": _mysql_password,
            "HOST": os.getenv("MYSQL_HOST", "127.0.0.1"),
            "PORT": os.getenv("MYSQL_PORT", "3306"),
            "OPTIONS": {"charset": "utf8mb4"},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR.parent / "fastapi_backend" / "ecommerce.db",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = False  # store timestamps are naive UTC (matches FastAPI)

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # `collectstatic` target for production
if importlib.util.find_spec("whitenoise"):
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Product images uploaded through the admin. They live in a directory the
# FastAPI service serves at /media/..., so the storefront and the admin both
# resolve the same site-relative URLs stored on products.images.
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR.parent / "fastapi_backend" / "media"))
# Where the storefront runs, for admin previews of those relative image URLs.
STORE_PUBLIC_URL = os.getenv("STORE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

# Creates tables for the unmanaged store models inside the test database.
TEST_RUNNER = "ecommerce_admin.test_runner.UnmanagedModelTestRunner"
