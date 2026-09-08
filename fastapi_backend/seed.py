"""Seed the database with the role reference table and sample products.

Run:  python seed.py

No demo user accounts are created here. Every user — local registration or
Google/Facebook login — is always created with role "customer" (see
app/routers/auth.py). To make someone staff or admin, update their row
directly in MySQL:

    UPDATE users SET role = 'admin' WHERE email = 'someone@example.com';
    UPDATE users SET role = 'staff' WHERE email = 'someone@example.com';
    UPDATE users SET role = 'customer' WHERE email = 'someone@example.com';  -- demote

The `role` column is a native MySQL ENUM('admin','staff','customer'), so the
database itself rejects any other value — there is no way to introduce a
fourth role by editing this column.
"""
from app.database import Base, SessionLocal, engine
from app.models import Product, Role

Base.metadata.create_all(bind=engine)

ROLES = [
    ("admin", "Full access: shop, buy, manage products, see all orders/payments/invoices, manage order statuses and roles."),
    ("staff", "Can shop and manage products (create, rename, price, stock, photos, delete) and update order statuses."),
    ("customer", "Can shop: browse products, manage their cart, place orders, pay, and view their own orders and invoices."),
]

PRODUCTS = [
    ("Wireless Mouse", "Ergonomic 2.4GHz wireless mouse", "electronics", 24.99, 150, 320),
    ("Mechanical Keyboard", "RGB hot-swappable mechanical keyboard", "electronics", 89.99, 60, 210),
    ("USB-C Hub", "7-in-1 USB-C hub with HDMI and PD", "electronics", 39.99, 90, 180),
    ("Noise-Cancelling Headphones", "Over-ear ANC headphones, 30h battery", "electronics", 199.99, 35, 450),
    ("Cotton T-Shirt", "Classic-fit 100% cotton t-shirt", "clothing", 14.99, 300, 520),
    ("Denim Jacket", "Vintage-wash denim jacket", "clothing", 59.99, 45, 95),
    ("Running Shoes", "Lightweight breathable running shoes", "clothing", 79.99, 80, 260),
    ("Espresso Maker", "Stovetop espresso maker, 6-cup", "home", 32.50, 70, 140),
    ("Ceramic Mug Set", "Set of 4 handcrafted ceramic mugs", "home", 27.99, 120, 88),
    ("LED Desk Lamp", "Dimmable LED desk lamp with USB port", "home", 21.99, 0, 175),  # out of stock
    ("Yoga Mat", "Non-slip 6mm yoga mat", "sports", 18.99, 200, 310),
    ("Dumbbell Set", "Adjustable dumbbell set 2x10kg", "sports", 64.99, 25, 130),
]


def seed() -> None:
    db = SessionLocal()
    try:
        for name, description in ROLES:
            existing = db.query(Role).filter(Role.name == name).first()
            if existing is None:
                db.add(Role(name=name, description=description))
            else:
                existing.description = description

        if db.query(Product).count() == 0:
            for name, desc, category, price, stock, popularity in PRODUCTS:
                db.add(
                    Product(
                        name=name,
                        description=desc,
                        category=category,
                        price=price,
                        stock=stock,
                        popularity=popularity,
                        images=[f"https://picsum.photos/seed/{name.replace(' ', '-')}/400/400"],
                    )
                )
            print(f"Created {len(PRODUCTS)} products")
        db.commit()
        print("Seed complete. No demo users created — register through the app, "
              "then promote a user's role directly in MySQL if needed.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
