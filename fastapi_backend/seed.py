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
from app.services.sequence_service import next_sequence_value

Base.metadata.create_all(bind=engine)

ROLES = [
    ("admin", "Full access: shop, buy, manage products, see all orders/payments/invoices, manage order statuses and roles."),
    ("staff", "Can shop and manage products (create, rename, price, stock, photos, delete) and update order statuses."),
    ("customer", "Can shop: browse products, manage their cart, place orders, pay, and view their own orders and invoices."),
]

# (name, description, category, price_in_INR, stock, popularity)
# Prices are Indian rupees — the same currency Stripe is configured to charge
# (STRIPE_CURRENCY=inr), so what the catalog shows is what actually gets billed.
PRODUCTS = [
    # ---- Phones ----
    ("iPhone 15 Pro Max 256GB", "6.7\" titanium, A17 Pro chip, 48MP main camera", "electronics", 159900, 18, 940),
    ("iPhone 15 128GB", "6.1\" Super Retina XDR, Dynamic Island, USB-C", "electronics", 79900, 30, 880),
    ("iPhone 14 128GB", "6.1\" display, A15 Bionic, dual camera system", "electronics", 69900, 25, 610),
    ("iPhone SE (3rd gen) 64GB", "4.7\" compact iPhone with A15 Bionic and Touch ID", "electronics", 49900, 40, 300),
    ("Samsung Galaxy S24 Ultra 256GB", "6.8\" QHD+ AMOLED, S Pen, 200MP camera", "electronics", 129999, 20, 820),
    ("Samsung Galaxy S24 128GB", "6.2\" FHD+ AMOLED, Exynos 2400, Galaxy AI", "electronics", 74999, 35, 540),
    ("Samsung Galaxy A55 5G", "6.6\" Super AMOLED, 50MP OIS camera, 5000mAh", "electronics", 39999, 60, 430),
    ("Samsung Galaxy M35 5G", "6.6\" 120Hz display, 6000mAh battery", "electronics", 19999, 80, 380),

    # ---- iPhone lineup: every model, one variant each ----
    # (15 128GB, 15 Pro Max 256GB and SE 3rd gen 64GB are seeded above already)
    ("iPhone 11 64GB (Black)", "6.1\" Liquid Retina HD, A13 Bionic, dual 12MP camera", "electronics", 29999, 40, 260),
    ("iPhone 11 Pro 256GB (Midnight Green)", "5.8\" Super Retina XDR, A13 Bionic, triple camera", "electronics", 54900, 22, 190),
    ("iPhone 11 Pro Max 256GB (Space Gray)", "6.5\" Super Retina XDR, A13 Bionic, 4h longer battery", "electronics", 59900, 18, 170),
    ("iPhone 12 Mini 128GB (Blue)", "5.4\" Super Retina XDR, A14 Bionic, Ceramic Shield", "electronics", 39900, 28, 220),
    ("iPhone 12 128GB (Black)", "6.1\" Super Retina XDR, A14 Bionic, 5G", "electronics", 44900, 35, 300),
    ("iPhone 12 Pro 256GB (Pacific Blue)", "6.1\" Super Retina XDR, A14 Bionic, LiDAR scanner", "electronics", 64900, 20, 210),
    ("iPhone 12 Pro Max 256GB (Graphite)", "6.7\" Super Retina XDR, A14 Bionic, sensor-shift OIS", "electronics", 74900, 16, 180),
    ("iPhone 13 Mini 128GB (Pink)", "5.4\" Super Retina XDR, A15 Bionic, dual-camera system", "electronics", 44900, 30, 260),
    ("iPhone 13 256GB (Black)", "6.1\" Super Retina XDR, A15 Bionic, cinematic mode", "electronics", 59900, 38, 420),
    ("iPhone 13 Pro 256GB (Sierra Blue)", "6.1\" Super Retina XDR ProMotion 120Hz, A15 Bionic, 3x telephoto", "electronics", 84900, 24, 340),
    ("iPhone 13 Pro Max 256GB (Graphite)", "6.7\" Super Retina XDR ProMotion 120Hz, A15 Bionic, best-in-class battery", "electronics", 94900, 20, 300),
    ("iPhone 14 Plus 128GB (Blue)", "6.7\" Super Retina XDR, A15 Bionic, Crash Detection", "electronics", 79900, 26, 280),
    ("iPhone 14 Pro 256GB (Deep Purple)", "6.1\" Super Retina XDR, Dynamic Island, A16 Bionic, 48MP main", "electronics", 109900, 22, 360),
    ("iPhone 14 Pro Max 256GB (Space Black)", "6.7\" Super Retina XDR, Dynamic Island, A16 Bionic, Always-On display", "electronics", 129900, 16, 320),
    ("iPhone 15 Plus 128GB (Pink)", "6.7\" Super Retina XDR, Dynamic Island, USB-C, A16 Bionic", "electronics", 89900, 24, 300),
    ("iPhone 15 Pro 256GB (Natural Titanium)", "6.1\" titanium, A17 Pro chip, Action button, USB-C", "electronics", 134900, 18, 400),

    # ---- Headsets ----
    ("Sony WH-1000XM5", "Industry-leading ANC over-ear headphones, 30h battery", "electronics", 29990, 45, 760),
    ("Bose QuietComfort Ultra", "Spatial audio over-ear headphones with world-class ANC", "electronics", 34900, 22, 410),
    ("JBL Tune 770NC", "Adaptive noise cancelling wireless headphones, 70h playtime", "electronics", 8999, 90, 520),
    ("boAt Rockerz 550", "Over-ear Bluetooth headphones, 20h playback, 50mm drivers", "electronics", 1799, 200, 690),

    # ---- Laptops ----
    ("Apple MacBook Air 13\" M3", "8-core CPU, 8GB unified memory, 256GB SSD, 18h battery", "electronics", 114900, 15, 700),
    ("Apple MacBook Pro 14\" M3", "M3 Pro chip, 18GB memory, 512GB SSD, Liquid Retina XDR", "electronics", 169900, 10, 480),
    ("HP Pavilion 15", "Intel Core i5 13th gen, 16GB RAM, 512GB SSD, FHD display", "electronics", 62999, 28, 350),
    ("Lenovo IdeaPad Slim 5", "AMD Ryzen 7, 16GB RAM, 512GB SSD, 14\" WUXGA", "electronics", 58990, 32, 320),
    ("Dell Inspiron 15", "Intel Core i5, 8GB RAM, 512GB SSD, 15.6\" FHD", "electronics", 52990, 26, 290),
    ("Apple MacBook Pro 16\" M3 Pro", "12-core CPU, 18-core GPU, 18GB memory, 512GB SSD, 16.2\" Liquid Retina XDR", "electronics", 249900, 8, 260),
    ("Apple MacBook Air 15\" M2", "8-core CPU, 8GB unified memory, 256GB SSD, 15.3\" Liquid Retina", "electronics", 134900, 14, 310),
    ("Dell XPS 13", "Intel Core i7 13th gen, 16GB RAM, 512GB SSD, 13.4\" InfinityEdge", "electronics", 119990, 15, 240),
    ("HP Spectre x360 14", "Intel Core i7, 16GB RAM, 1TB SSD, 2-in-1 OLED touchscreen", "electronics", 149999, 10, 190),
    ("Lenovo Legion 5", "AMD Ryzen 7, RTX 4060, 16GB RAM, 512GB SSD, 165Hz display", "electronics", 99990, 18, 350),
    ("ASUS ROG Strix G16", "Intel Core i7 13th gen, RTX 4070, 16GB RAM, 1TB SSD, 165Hz display", "electronics", 134990, 12, 300),
    ("Acer Aspire 5", "AMD Ryzen 5, 8GB RAM, 512GB SSD, 15.6\" FHD", "electronics", 42990, 34, 270),
    ("ASUS VivoBook 15", "Intel Core i5 12th gen, 16GB RAM, 512GB SSD, 15.6\" FHD", "electronics", 47990, 30, 230),

    # ---- Smart watches ----
    ("Apple Watch Series 9 GPS 45mm", "Always-On Retina display, ECG, blood oxygen", "electronics", 41900, 30, 580),
    ("Samsung Galaxy Watch 6 44mm", "Super AMOLED, body composition, sleep coaching", "electronics", 28999, 34, 360),
    ("Noise ColorFit Pro 5", "1.85\" AMOLED, Bluetooth calling, 7-day battery", "electronics", 3499, 150, 640),

    # ---- Power banks ----
    ("Anker PowerCore 20000mAh", "20W USB-C Power Delivery, charges a phone 4x", "electronics", 3999, 110, 470),
    ("Mi Power Bank 3i 20000mAh", "18W fast charging, triple port, dual input", "electronics", 1999, 180, 550),

    # ---- Other electronics ----
    ("Apple AirPods Pro (2nd gen)", "Active noise cancellation, USB-C charging case", "electronics", 24900, 55, 810),
    ("Logitech MX Master 3S", "8K DPI silent wireless mouse, multi-device", "electronics", 9995, 70, 400),
    ("SanDisk Extreme 1TB Portable SSD", "1050MB/s read, IP55 water and dust resistant", "electronics", 8499, 65, 330),

    # ---- Large appliances ----
    ("Voltas 1.5 Ton 5 Star Inverter Split AC", "Copper condenser, anti-dust filter, turbo cooling", "electronics", 38990, 20, 410),
    ("LG 260L Frost-Free Double Door Refrigerator", "3 star, smart inverter compressor, convertible freezer", "electronics", 27990, 18, 380),
    ("Samsung 65L Convection Microwave Oven", "SlimFry technology, ceramic interior, auto-cook menus", "electronics", 14990, 32, 250),
    ("Whirlpool 7kg Front-Load Washing Machine", "1200 RPM, 6th Sense inverter motor, steam wash", "electronics", 26990, 20, 220),
    ("Mi 55\" Smart LED TV", "4K UHD, Dolby Vision & Atmos, Android TV, 3 HDMI ports", "electronics", 34999, 24, 390),
    ("Philips Air Purifier AC1215", "HEPA filter, removes 99.9% pollutants, covers up to 234 sq ft", "electronics", 8999, 40, 200),
    ("Kent Grand Plus RO Water Purifier", "8L storage, RO+UV+UF purification, TDS control", "electronics", 15999, 28, 230),

    # ---- Original catalog, repriced in rupees ----
    ("Wireless Mouse", "Ergonomic 2.4GHz wireless mouse", "electronics", 1299, 150, 320),
    ("Mechanical Keyboard", "RGB hot-swappable mechanical keyboard", "electronics", 6499, 60, 210),
    ("USB-C Hub", "7-in-1 USB-C hub with HDMI and PD", "electronics", 2499, 90, 180),
    ("Noise-Cancelling Headphones", "Over-ear ANC headphones, 30h battery", "electronics", 12999, 35, 450),
    ("Cotton T-Shirt", "Classic-fit 100% cotton t-shirt", "clothing", 799, 300, 520),
    ("Denim Jacket", "Vintage-wash denim jacket", "clothing", 3499, 45, 95),
    ("Running Shoes", "Lightweight breathable running shoes", "clothing", 4999, 80, 260),
    ("Espresso Maker", "Stovetop espresso maker, 6-cup", "home", 2999, 70, 140),
    ("Ceramic Mug Set", "Set of 4 handcrafted ceramic mugs", "home", 1499, 120, 88),
    ("LED Desk Lamp", "Dimmable LED desk lamp with USB port", "home", 1199, 0, 175),  # out of stock
    ("Yoga Mat", "Non-slip 6mm yoga mat", "sports", 999, 200, 310),
    ("Dumbbell Set", "Adjustable dumbbell set 2x10kg", "sports", 4499, 25, 130),
]

# A tinted, labelled placeholder per category. Real product photography would
# replace these — random stock photos (the previous picsum seeds) actively
# mislead, since a landscape shot tells you nothing about the item.
CATEGORY_TINT = {
    "electronics": "0f172a",
    "clothing": "3f2b56",
    "home": "1f3a34",
    "sports": "3a2417",
}


def product_image(name: str, category: str) -> str:
    from urllib.parse import quote_plus

    tint = CATEGORY_TINT.get(category, "1a1a2e")
    return f"https://placehold.co/600x600/{tint}/ffffff.png?text={quote_plus(name)}"


def seed() -> None:
    db = SessionLocal()
    try:
        for name, description in ROLES:
            existing = db.query(Role).filter(Role.name == name).first()
            if existing is None:
                db.add(Role(name=name, description=description))
            else:
                existing.description = description

        # Upsert by name so this can be re-run against a populated catalog: new
        # products get added, existing ones get the current price/description/
        # image. Stock and popularity are only set on creation — those move with
        # real trading and shouldn't be reset by a reseed.
        created = updated = 0
        for name, desc, category, price, stock, popularity in PRODUCTS:
            product = db.query(Product).filter(Product.name == name).first()
            if product is None:
                db.add(
                    Product(
                        name=name,
                        description=desc,
                        category=category,
                        price=price,
                        stock=stock,
                        popularity=popularity,
                        images=[product_image(name, category)],
                        product_number=next_sequence_value(db, "product_number"),
                    )
                )
                created += 1
            else:
                product.description = desc
                product.category = category
                product.price = price
                product.images = [product_image(name, category)]
                updated += 1
        print(f"Products: {created} created, {updated} updated (prices in INR)")
        db.commit()
        print("Seed complete. No demo users created — register through the app, "
              "then promote a user's role directly in MySQL if needed.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
