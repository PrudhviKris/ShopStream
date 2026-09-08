from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import BASE_DIR, settings


def _ensure_mysql_database() -> None:
    """Create the MySQL schema if it doesn't exist yet (first run convenience)."""
    server_url = settings.DATABASE_URL.rsplit("/", 1)[0]
    tmp_engine = create_engine(server_url, pool_pre_ping=True)
    with tmp_engine.connect() as conn:
        conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{settings.MYSQL_DB}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
        conn.commit()
    tmp_engine.dispose()


def _make_engine():
    url = settings.DATABASE_URL
    if url.startswith("mysql"):
        try:
            _ensure_mysql_database()
        except Exception as exc:
            url = f"sqlite:///{(BASE_DIR / 'ecommerce.db').as_posix()}"
            print(
                f"WARNING: MySQL connection failed ({exc.__class__.__name__}: {exc}).\n"
                f"         Check MYSQL_PASSWORD in fastapi_backend/.env.\n"
                f"         Falling back to SQLite at {url}"
            )
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # pool_pre_ping revalidates pooled connections (MySQL closes idle ones)
    return create_engine(url, pool_pre_ping=True, pool_recycle=3600)


engine = _make_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
