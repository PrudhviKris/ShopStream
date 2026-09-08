import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { canManageProducts } from "./roles";
import Topbar from "./components/Topbar";
import Sidebar from "./components/Sidebar";
import AuthPage from "./components/AuthPage";
import DashboardPage from "./components/DashboardPage";
import ProductsPage from "./components/ProductsPage";
import OrdersPage from "./components/OrdersPage";
import PaymentsPage from "./components/PaymentsPage";
import InvoicesPage from "./components/InvoicesPage";
import CartDrawer from "./components/CartDrawer";
import { ProductDetailModal, ProductFormModal } from "./components/Catalog";

const TOAST_ICONS = { order: "📦", payment: "💳", info: "🔔" };

export default function App() {
  const [view, setView] = useState("dashboard"); // dashboard | products | orders | payments | invoices | auth
  const [user, setUser] = useState(null);
  const [products, setProducts] = useState([]);
  const [total, setTotal] = useState(0);
  const [cart, setCart] = useState(null);
  const [cartOpen, setCartOpen] = useState(false);
  const [orders, setOrders] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [toasts, setToasts] = useState([]);
  const [notifRefresh, setNotifRefresh] = useState(0);
  const [detailProduct, setDetailProduct] = useState(null); // shopping detail modal
  const [formProduct, setFormProduct] = useState(undefined); // undefined=closed, null=create, object=edit
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
    // Returning from a Google/Facebook OAuth redirect: tokens (or an error)
    // arrive in the URL fragment.
    const hash = new URLSearchParams(window.location.hash.slice(1));
    if (hash.get("access_token")) {
      api.adoptTokens(hash.get("access_token"), hash.get("refresh_token"));
      window.history.replaceState(null, "", window.location.pathname);
    } else if (hash.get("social_error")) {
      pushToast({ type: "info", title: "Social login failed", message: hash.get("social_error") });
      window.history.replaceState(null, "", window.location.pathname);
    }
    if (api.isLoggedIn()) {
      api.me().then((u) => setUser(u)).catch(() => api.logout());
    } else {
      setView("auth");
    }
  }, [pushToast]);

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
    searchDebounce.current = setTimeout(() => setFilters((f) => ({ ...f, search: text })), 300);
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
      setDetailProduct(null);
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

  async function checkout(paymentMethod) {
    setBusy(true);
    try {
      const result = await api.checkout(paymentMethod);
      setCart(await api.cart());
      setOrders(await api.orders());
      loadProducts();
      if (result.checkout_url && !result.checkout_url.includes("mock-checkout")) {
        window.location.href = result.checkout_url; // Stripe hosted page
      } else {
        if (paymentMethod === "cash") {
          pushToast({ type: "order", title: "Order placed — cash on delivery", message: `Transaction ref ${result.transaction_id}. Pay on delivery.` });
        }
        setCartOpen(false);
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

  async function saveProduct(data, id) {
    const saved = id ? await api.updateProduct(id, data) : await api.createProduct(data);
    setFormProduct(undefined);
    loadProducts();
    pushToast({ type: "info", title: id ? "Product updated" : "Product created", message: saved.name });
  }

  async function deleteProduct(product) {
    if (!window.confirm(`Delete "${product.name}"? This cannot be undone.`)) return;
    try {
      await api.deleteProduct(product.id);
      setFormProduct(undefined);
      loadProducts();
      pushToast({ type: "info", title: "Deleted", message: `${product.name} removed from the catalog.` });
    } catch (err) {
      pushToast({ type: "info", title: "Delete failed", message: err.message });
    }
  }

  function logout() {
    api.logout();
    setUser(null);
    setCart(null);
    setOrders([]);
    setInvoices([]);
    setView("auth");
  }

  const cartCount = cart ? cart.items.reduce((sum, i) => sum + i.quantity, 0) : 0;
  const notify = (title, message) => pushToast({ type: "info", title, message });

  if (!user) {
    return (
      <>
        <AuthPage onSuccess={async () => { setUser(await api.me()); setView("dashboard"); }} />
        <div className="toasts">
          {toasts.map((t) => (
            <div key={t.id} className="toast">
              <span>{TOAST_ICONS[t.type] || "🔔"}</span>
              <div><div className="t">{t.title}</div><div className="m">{t.message}</div></div>
            </div>
          ))}
        </div>
      </>
    );
  }

  const manage = canManageProducts(user.role);

  return (
    <div className="shell">
      <Topbar
        user={user}
        cartCount={cartCount}
        onOpenCart={() => setCartOpen(true)}
        onNavigate={setView}
        onSearch={handleSearch}
        onLogout={logout}
        notifRefresh={notifRefresh}
      />

      <div className="layout">
        <Sidebar user={user} view={view} onNavigate={setView} />

        <main className="main">
          {view === "dashboard" && (
            <DashboardPage user={user} products={products} cart={cart} orders={orders} onNavigate={setView} />
          )}

          {view === "products" && (
            <ProductsPage
              products={products}
              total={total}
              filters={filters}
              setFilters={setFilters}
              user={user}
              canManage={manage}
              onOpen={(p) => { setDetailProduct(p); setQty(1); }}
              onAdd={(p) => addToCart(p, 1)}
              onEdit={(p) => setFormProduct(p)}
              onDelete={deleteProduct}
              onCreate={() => setFormProduct(null)}
            />
          )}

          {view === "orders" && (
            <OrdersPage
              user={user}
              orders={orders}
              invoices={invoices}
              canManage={manage}
              onPayNow={payNow}
              onShop={() => setView("products")}
              notify={notify}
            />
          )}

          {view === "payments" && <PaymentsPage user={user} orders={orders} notify={notify} />}
          {view === "invoices" && <InvoicesPage user={user} />}
        </main>
      </div>

      <footer className="footer">Smart E-Commerce Platform — FastAPI · Django · React · Stripe · MySQL</footer>

      <CartDrawer
        open={cartOpen}
        cart={cart}
        products={products}
        onClose={() => setCartOpen(false)}
        onUpdateQty={updateQty}
        onRemove={(id) => updateQty(id, 0)}
        onCheckout={checkout}
        busy={busy}
      />

      <ProductDetailModal product={detailProduct} qty={qty} setQty={setQty} onClose={() => setDetailProduct(null)} onAdd={addToCart} />

      {formProduct !== undefined && (
        <ProductFormModal product={formProduct} onClose={() => setFormProduct(undefined)} onSubmit={saveProduct} onDelete={deleteProduct} />
      )}

      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className="toast">
            <span>{TOAST_ICONS[t.type] || "🔔"}</span>
            <div><div className="t">{t.title}</div><div className="m">{t.message}</div></div>
          </div>
        ))}
      </div>
    </div>
  );
}
