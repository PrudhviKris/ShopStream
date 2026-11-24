from tests.conftest import PASSWORD, make_user


def test_register_always_creates_a_customer(client):
    r = client.post(
        "/auth/register",
        json={"name": "Mallory", "email": "mallory.platform@example.com", "password": PASSWORD, "role": "admin"},
    )
    assert r.status_code == 201
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["role"] == "customer"


def test_login_with_wrong_password_fails(client, customer):
    r = client.post("/auth/login", json={"email": customer["email"], "password": "not-the-password"})
    assert r.status_code == 401


def test_protected_routes_need_a_valid_token(client):
    assert client.get("/auth/me").status_code in (401, 403)
    assert client.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_role_change_applies_on_the_very_next_request(client):
    user = make_user(client, "customer")
    assert client.get("/payments/all", headers=user["headers"]).status_code == 403

    from sqlalchemy import text
    from app.database import SessionLocal

    with SessionLocal() as db:
        db.execute(text("UPDATE users SET role = 'admin' WHERE email = :e"), {"e": user["email"]})
        db.commit()
    # same token, no re-login: the role is re-read from the database on every request
    assert client.get("/payments/all", headers=user["headers"]).status_code == 200
