import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import Header from "./components/Header";
import { Filters, ProductCard, ProductModal } from "./components/Catalog";
import CartPage from "./components/CartPage";
import OrdersPage from "./components/OrdersPage";
import AuthPage from "./components/AuthPage";
import AdminPage from "./components/AdminPage";

const TOAST_ICONS = { order: "📦", payment: "💳", info: "🔔" };

export default function App() {
  const [view, setView] = useState("shop"); // shop | cart | orders | auth
  const [user, setUser] = useState(null);
  const [products, setProducts] = useState([]);
  const [total, setTotal] = useState(0);
  const [cart, setCart] = useState(null);
  const [orders, setOrders] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [toasts, setToasts] = useState([]);
  const [notifRefresh, setNotifRefresh] = useState(0);
  const [modalProduct, setModalProduct] = useState(null);
  const [qty, setQty] = useState(1);
  const [busy, setBusy] = useState(false);
  const [filters, setFilters] = useState({
    category: "", min_price: "", max_price: "", in_stock: false, search: "", sort: "popularity",
  });
  const searchDebounce = useRef(null);

  const pushToast = useCallback((toast) => {
    const id = toast.id ?? `local-${Date.now()}`;
    setToasts((t) => [...t, { ...toast, id }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5500);
  }, []);

  // ---- data loading ----
  const loadProducts = useCallback(() => {
    const params = { sort: filters.sort, page_size: 50 };
    if (filters.category) params.category = filters.category;
    if (filters.min_price !== "") params.min_price = filters.min_price;
    if (filters.max_price !== "") params.max_price = filters.max_price;
    if (filters.in_stock) params.in_stock = true;
    if (filters.search) params.search = filters.search;
    api.products(params).then((d) => { setProducts(d.items); setTotal(d.total); }).catch(() => {});
  }, [filters]);

  useEffect(loadProducts, [loadProducts]);

  useEffect(() => {
    if (api.isLoggedIn()) {
      api.me().then((u) => { setUser(u); }).catch(() => api.logout());
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    api.cart().then(setCart).catch(() => {});
    api.orders().then(setOrders).catch(() => {});
    api.myInvoices().then(setInvoices).catch(() => {});
  }, [user]);

  // ---- real-time notifications ----
  useEffect(() => {
    if (!user) return;
    const ws = api.notificationSocket();
    ws.onmessage = (event) => {
      const n = JSON.parse(event.data);
      pushToast(n);
      setNotifRefresh((x) => x + 1);
      api.orders().then(setOrders).catch(() => {});
      api.myInvoices().then(setInvoices).catch(() => {});
    };
    return () => ws.close();
  }, [user, pushToast]);

  // ---- actions ----
  function handleSearch(text) {
    clearTimeout(searchDebounce.current);
    searchDebounce.current = setTimeout(
      () => setFilters((f) => ({ ...f, search: text })), 300
    );
  }

  function requireAuth() {
    if (user) return true;
    setView("auth");
    return false;
  }

  async function addToCart(product, quantity = 1) {
    if (!requireAuth()) return;
    try {
      setCart(await api.addToCart(product.id, quantity));
      setModalProduct(null);
      pushToast({ type: "info", title: "Added to cart", message: `${product.name} × ${quantity}` });
    } catch (err) {
      pushToast({ type: "info", title: "Couldn't add", message: err.message });
    }
  }

  async function updateQty(productId, quantity) {
    try {
      setCart(quantity <= 0 ? await api.removeFromCart(productId) : await api.updateCart(productId, quantity));
    } catch (err) {
      pushToast({ type: "info", title: "Cart", message: err.message });
    }
  }

  async function checkout() {
    setBusy(true);
    try {
      const result = await api.checkout();
      setCart(await api.cart());
      setOrders(await api.orders());
      loadProducts();
      if (result.checkout_url && !result.checkout_url.includes("mock-checkout")) {
        window.location.href = result.checkout_url; // Stripe hosted page
      } else {
        setView("orders");
      }
    } catch (err) {
      pushToast({ type: "info", title: "Checkout failed", message: err.message });
    } finally {
      setBusy(false);
    }
  }

  async function payNow(orderId) {
    try {
      await api.mockConfirmPayment(orderId);
      setOrders(await api.orders());
    } catch (err) {
      pushToast({ type: "info", title: "Payment", message: err.message });
    }
  }

  function logout() {
    api.logout(); // revokes the refresh token server-side
    setUser(null);
    setCart(null);
    setOrders([]);
    setInvoices([]);
    setView("shop");
  }

  const cartCount = cart ? cart.items.reduce((sum, i) => sum + i.quantity, 0) : 0;

  return (
    <div className="shell">
      <Header
        user={user}
        cartCount={cartCount}
        view={view}
        onNavigate={setView}
        onSearch={handleSearch}
        onLogout={logout}
        notifRefresh={notifRefresh}
      />

      <main className="main">
        {view === "shop" && (
          <div className="shop-layout">
            <Filters filters={filters} setFilters={setFilters} />
            <section>
              <div className="toolbar">
                <span className="count">
                  {total} product{total === 1 ? "" : "s"}
                  {filters.category ? ` in ${filters.category}` : ""}
                </span>
                <select
                  value={filters.sort}
                  onChange={(e) => setFilters((f) => ({ ...f, sort: e.target.value }))}
                >
                  <option value="popularity">Most popular</option>
                  <option value="price_asc">Price: low to high</option>
                  <option value="price_desc">Price: high to low</option>
                  <option value="newest">Newest</option>
                </select>
              </div>
              {products.length === 0 ? (
                <div className="panel empty">
                  <div className="big">🔎</div>
                  <h3>No products match</h3>
                  <p>Try clearing some filters.</p>
                </div>
              ) : (
                <div className="grid">
                  {products.map((p) => (
                    <ProductCard
                      key={p.id}
                      product={p}
                      canAdd={Boolean(user)}
                      onOpen={(prod) => { setModalProduct(prod); setQty(1); }}
                      onAdd={(prod) => addToCart(prod, 1)}
                    />
                  ))}
                </div>
              )}
            </section>
          </div>
        )}

        {view === "cart" && (
          <CartPage
            cart={cart}
            products={products}
            onUpdateQty={updateQty}
            onRemove={(id) => updateQty(id, 0)}
            onCheckout={checkout}
            onShop={() => setView("shop")}
            busy={busy}
          />
        )}

        {view === "orders" && (
          <OrdersPage orders={orders} invoices={invoices} onPayNow={payNow} onShop={() => setView("shop")} />
        )}

        {view === "admin" && user && (user.role === "admin" || user.role === "staff") && (
          <AdminPage
            user={user}
            notify={(title, message) => pushToast({ type: "info", title, message })}
          />
        )}

        {view === "auth" && (
          <AuthPage
            onSuccess={async () => { setUser(await api.me()); setView("shop"); }}
          />
        )}
      </main>

      <footer className="footer">
        Smart E-Commerce Platform — FastAPI · Django · React · Stripe · MySQL
      </footer>

      <ProductModal
        product={modalProduct}
        qty={qty}
        setQty={setQty}
        onClose={() => setModalProduct(null)}
        onAdd={addToCart}
      />

      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className="toast">
            <span>{TOAST_ICONS[t.type] || "🔔"}</span>
            <div>
              <div className="t">{t.title}</div>
              <div className="m">{t.message}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
