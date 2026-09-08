"""End-to-end smoke test using FastAPI's TestClient (no server needed).

Covers: register/login/refresh/me, RBAC, product filters, cart CRUD + totals,
checkout -> order -> payment, mock payment confirmation, order status flow,
notifications (DB + WebSocket real-time push).
"""
from fastapi.testclient import TestClient

import seed
from app.main import app

seed.seed()
client = TestClient(app)
client.__enter__()  # run app lifespan so real-time WebSocket pushes are wired up
passed = 0


def check(name, condition, detail=""):
    global passed
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not condition else ""))
    assert condition, f"{name}: {detail}"
    passed += 1


# ---- Auth ----
r = client.post("/auth/register", json={"name": "Smoke Tester", "email": "smoke@test.com", "password": "SmokePass123!"})
check("register", r.status_code in (201, 409), r.text)
r = client.post("/auth/login", json={"email": "smoke@test.com", "password": "SmokePass123!"})
check("login", r.status_code == 200, r.text)
tokens = r.json()
auth = {"Authorization": f"Bearer {tokens['access_token']}"}

r = client.post("/auth/login", json={"email": "smoke@test.com", "password": "wrong-password"})
check("login rejects bad password", r.status_code == 401)

r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
check("refresh", r.status_code == 200, r.text)
rotated = r.json()
r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
check("refresh token rotation (old token revoked)", r.status_code == 401, r.text)
r = client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
check("refresh rejects access token", r.status_code == 401)
r = client.post("/auth/logout", json={"refresh_token": rotated["refresh_token"]})
check("logout revokes refresh token", r.status_code == 200)
r = client.post("/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
check("revoked token cannot refresh", r.status_code == 401)
r = client.post("/auth/login", json={"email": "smoke@test.com", "password": "SmokePass123!"})
tokens = r.json()
auth = {"Authorization": f"Bearer {tokens['access_token']}"}

r = client.get("/auth/me", headers=auth)
check("me", r.status_code == 200 and r.json()["email"] == "smoke@test.com", r.text)
check("me requires auth", client.get("/auth/me").status_code == 401)

# ---- Products & filters ----
r = client.get("/products")
check("list products", r.status_code == 200 and r.json()["total"] >= 12, r.text)
r = client.get("/products", params={"category": "electronics", "min_price": 10, "max_price": 100, "in_stock": True})
data = r.json()
check(
    "filters (category+price+stock)",
    all(i["category"] == "electronics" and 10 <= i["price"] <= 100 and i["stock"] > 0 for i in data["items"]),
    r.text,
)
r = client.get("/products", params={"sort": "price_asc"})
prices = [i["price"] for i in r.json()["items"]]
check("sort by price", prices == sorted(prices))
r = client.get("/products/category/home")
check("by category endpoint", all(i["category"] == "home" for i in r.json()["items"]))
r = client.get("/products/1")
check("product detail", r.status_code == 200 and r.json()["id"] == 1)
check("product 404", client.get("/products/99999").status_code == 404)

# ---- RBAC: products ----
new_product = {"name": "RBAC Test Item", "price": 9.99, "stock": 5, "category": "test"}
check("customer cannot create product", client.post("/products", json=new_product, headers=auth).status_code == 403)
r = client.post("/auth/login", json={"email": "admin@example.com", "password": "AdminPass123!"})
admin_auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
r = client.post("/auth/login", json={"email": "staff@example.com", "password": "StaffPass123!"})
staff_auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

r = client.post("/products", json=new_product, headers=admin_auth)
check("admin can create product", r.status_code == 201, r.text)
rbac_id = r.json()["id"]
r = client.put(f"/products/{rbac_id}", json={"name": "Renamed by staff", "stock": 9,
    "images": ["https://example.com/new-photo.jpg"]}, headers=staff_auth)
check("staff can rename/restock/re-photo product",
      r.status_code == 200 and r.json()["name"] == "Renamed by staff"
      and r.json()["stock"] == 9 and r.json()["images"] == ["https://example.com/new-photo.jpg"], r.text)
check("customer cannot update product",
      client.put(f"/products/{rbac_id}", json={"price": 1.0}, headers=auth).status_code == 403)
check("staff can delete product", client.delete(f"/products/{rbac_id}", headers=staff_auth).status_code == 204)

# ---- Cart ----
r = client.post("/cart/add", json={"product_id": 1, "quantity": 2}, headers=auth)
check("cart add", r.status_code == 201, r.text)
r = client.post("/cart/add", json={"product_id": 5, "quantity": 1}, headers=auth)
cart = r.json()
check("cart merge/add second", len(cart["items"]) == 2, r.text)
r = client.put("/cart/update", json={"product_id": 1, "quantity": 3}, headers=auth)
cart = r.json()
item = next(i for i in cart["items"] if i["product_id"] == 1)
check("cart update quantity", item["quantity"] == 3)
expected_total = round(sum(i["item_total"] for i in cart["items"]), 2)
check("cart totals", cart["cart_total"] == expected_total and cart["grand_total"] == round(cart["cart_total"] + cart["tax"], 2))
r = client.post("/cart/add", json={"product_id": 10, "quantity": 1}, headers=auth)
check("stock validation on add", r.status_code == 400, r.text)  # product 10 seeded with stock 0

# ---- Checkout -> Order -> Payment ----
stock_before = client.get("/products/1").json()["stock"]
r = client.post("/checkout", headers=auth)
check("checkout", r.status_code == 200, r.text)
co = r.json()
check("checkout returns stripe session", co["transaction_id"] is not None and co["checkout_url"] is not None)
order_id = co["order_id"]
check("cart cleared after checkout", client.get("/cart", headers=auth).json()["items"] == [])
check("stock decremented", client.get("/products/1").json()["stock"] == stock_before - 3)
check("checkout with empty cart rejected", client.post("/checkout", headers=auth).status_code == 400)

r = client.get(f"/orders/{order_id}", headers=auth)
order = r.json()
check("order created", r.status_code == 200 and order["order_status"] == "pending" and order["total"] == co["amount"])
r = client.get(f"/payments/{order_id}", headers=auth)
check("payment tracked", r.status_code == 200 and r.json()["status"] == "pending", r.text)

# ---- Real-time notifications over WebSocket + payment confirmation ----
with client.websocket_connect(f"/ws/notifications?token={tokens['access_token']}") as ws:
    r = client.post(f"/payments/mock/confirm/{order_id}", headers=auth)
    check("mock payment confirm", r.status_code == 200 and r.json()["status"] == "succeeded", r.text)
    # Two pushes arrive: the auto-issued invoice, then the payment confirmation.
    msgs = [ws.receive_json(), ws.receive_json()]
    check("websocket invoice push received", any("Invoice INV-" in m["title"] for m in msgs), str(msgs))
    check("websocket payment push received",
          any(m["type"] == "payment" and "succeeded" in m["message"] for m in msgs), str(msgs))

r = client.get(f"/orders/{order_id}", headers=auth)
check("order marked paid", r.json()["order_status"] == "paid" and r.json()["payment_status"] == "succeeded")

# ---- Order status flow (staff/admin) ----
check("customer cannot update status", client.put(f"/orders/{order_id}/status", json={"status": "shipped"}, headers=auth).status_code == 403)
r = client.put(f"/orders/{order_id}/status", json={"status": "shipped"}, headers=admin_auth)
check("admin ships order", r.status_code == 200 and r.json()["order_status"] == "shipped", r.text)
check("invalid transition rejected", client.put(f"/orders/{order_id}/status", json={"status": "paid"}, headers=admin_auth).status_code == 400)
check("staff/admin order list", client.get("/orders/all", headers=admin_auth).status_code == 200)
check("customer denied /orders/all", client.get("/orders/all", headers=auth).status_code == 403)

# ---- Notifications API ----
r = client.get("/notifications", headers=auth)
notifs = r.json()
check("notifications persisted", len(notifs) >= 3, str(len(notifs)))  # order placed, payment, shipped
r = client.put(f"/notifications/{notifs[0]['id']}/read", headers=auth)
check("mark notification read", r.status_code == 200 and r.json()["is_read"] is True)
r = client.put("/notifications/read-all", headers=auth)
check("mark all read", r.status_code == 200)

# ---- Invoices ----
r = client.get("/invoices", headers=auth)
check("customer sees own invoices", r.status_code == 200 and len(r.json()) >= 1, r.text)
invoice = r.json()[0]
check("invoice matches paid order",
      invoice["order_id"] == order_id and invoice["total"] == co["amount"]
      and invoice["invoice_number"].startswith("INV-"), str(invoice))
r = client.get(f"/invoices/{invoice['id']}", headers=auth)
check("customer reads own invoice", r.status_code == 200)
check("customer denied /invoices/all", client.get("/invoices/all", headers=auth).status_code == 403)
check("staff denied /invoices/all", client.get("/invoices/all", headers=staff_auth).status_code == 403)
r = client.get("/invoices/all", headers=admin_auth)
check("admin sees everyone's invoices",
      r.status_code == 200 and any(i["user_email"] == "smoke@test.com" for i in r.json()), r.text)
r = client.get(f"/invoices/{invoice['id']}", headers=admin_auth)
check("admin reads any customer's invoice", r.status_code == 200)

# ---- Admin oversight: payments and orders of every customer ----
check("customer denied /payments/all", client.get("/payments/all", headers=auth).status_code == 403)
r = client.get("/payments/all", headers=admin_auth)
check("admin sees everyone's payments",
      r.status_code == 200 and any(p["user_email"] == "smoke@test.com" for p in r.json()), r.text)
r = client.get("/orders/all", headers=admin_auth)
check("admin order list shows customer identity",
      r.status_code == 200 and all("user_email" in o for o in r.json()), r.text)
r = client.get("/roles", headers=admin_auth)
check("roles table (admin)", r.status_code == 200 and {x["name"] for x in r.json()} == {"admin", "staff", "customer"}, r.text)
check("customer denied /roles", client.get("/roles", headers=auth).status_code == 403)

# ---- Admin can shop and buy like anyone ----
r = client.post("/cart/add", json={"product_id": 2, "quantity": 1}, headers=admin_auth)
check("admin can add to cart", r.status_code == 201, r.text)
r = client.post("/checkout", headers=admin_auth)
check("admin can checkout", r.status_code == 200, r.text)
admin_order = r.json()["order_id"]
r = client.post(f"/payments/mock/confirm/{admin_order}", headers=admin_auth)
check("admin can pay", r.status_code == 200 and r.json()["status"] == "succeeded", r.text)
r = client.get("/invoices", headers=admin_auth)
check("admin gets own invoice after buying", any(i["order_id"] == admin_order for i in r.json()), r.text)

# ---- Social login endpoints exist (503 until provider keys are configured) ----
r = client.post("/auth/social/google", json={"id_token": "x"})
check("google endpoint present", r.status_code in (401, 503), r.text)
r = client.post("/auth/social/facebook", json={"access_token": "x"})
check("facebook endpoint present", r.status_code in (401, 503), r.text)
check("auth0 endpoint removed", client.post("/auth/social/auth0", json={"id_token": "x"}).status_code == 404)

print(f"\nAll {passed} checks passed.")
