"""Fast pytest suite (SQLite, mock Stripe, database email inbox).

The long end-to-end script in smoke_test.py still exists and targets MySQL; these tests
cover the payment, webhook and access-control rules and run anywhere, including CI.
"""
import os
import tempfile
from pathlib import Path

# Configure the app for testing *before* it is imported.
_tmp = Path(tempfile.mkdtemp(prefix="platform_test_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["JWT_SECRET_KEY"] = "test-only-jwt-secret-key-with-more-than-32-chars"
os.environ["STRIPE_SECRET_KEY"] = ""  # mock payments: never create real Stripe sessions
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test_secret_for_unit_tests"
os.environ["EMAIL_BACKEND"] = "database"
os.environ["EMAIL_ENABLED"] = "true"
os.environ["AUTH_RATE_LIMIT"] = "1000"
os.environ["AUTO_CREATE_SCHEMA"] = "true"
os.environ["APP_ENV"] = "development"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

import seed  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = "TestPass123!"
_counter = {"n": 0}


@pytest.fixture(scope="session")
def client():
    seed.seed()
    with TestClient(app) as c:
        yield c


def make_user(client, role="customer"):
    _counter["n"] += 1
    email = f"{role}{_counter['n']}@example.com"
    r = client.post("/auth/register", json={"name": f"Test {role}", "email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    token = r.json()["access_token"]
    if role != "customer":
        with SessionLocal() as db:  # promote the way an operator would: directly in the database
            db.execute(text("UPDATE users SET role = :r WHERE email = :e"), {"r": role, "e": email})
            db.commit()
    return {"email": email, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
def customer(client):
    return make_user(client, "customer")


@pytest.fixture
def staff(client):
    return make_user(client, "staff")


@pytest.fixture
def admin(client):
    return make_user(client, "admin")


@pytest.fixture
def product_id(client):
    with SessionLocal() as db:
        row = db.execute(text("SELECT id FROM products WHERE stock >= 5 ORDER BY id LIMIT 1")).first()
    assert row is not None, "seed.seed() should create sample products"
    return row[0]


def add_to_cart(client, headers, product_id, quantity=1):
    r = client.post("/cart/add", json={"product_id": product_id, "quantity": quantity}, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


def checkout(client, headers, payment_method="stripe"):
    r = client.post(f"/checkout?payment_method={payment_method}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()
