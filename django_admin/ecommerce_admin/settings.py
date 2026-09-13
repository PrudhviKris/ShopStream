"""Django admin/analytics service.

Reads the SAME database the FastAPI service writes to (SQLite by default;
set DATABASE_URL-equivalent env vars for Postgres in production). The store
models are managed=False so Django never migrates FastAPI-owned tables —
`migrate` only creates Django's own auth/session tables.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-in-production")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["*"] if DEBUG else os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",")

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
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Creates tables for the unmanaged store models inside the test database.
TEST_RUNNER = "ecommerce_admin.test_runner.UnmanagedModelTestRunner"
