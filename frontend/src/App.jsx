import { useEffect, useRef, useState } from "react";
import { api } from "./api";

export default function App() {
  const [user, setUser] = useState(null);
  const [products, setProducts] = useState([]);
  const [cart, setCart] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [error, setError] = useState("");
  const wsRef = useRef(null);

  useEffect(() => {
    if (api.isLoggedIn()) {
      api.me().then(setUser).catch(() => api.logout());
    }
    api.products({ sort: "popularity" }).then((d) => setProducts(d.items));
  }, []);

  // Real-time notifications over WebSocket
  useEffect(() => {
    if (!user) return;
    api.cart().then(setCart);
    const ws = api.notificationSocket();
    ws.onmessage = (event) => {
      const n = JSON.parse(event.data);
      setToasts((t) => [...t, n]);
      setTimeout(() => setToasts((t) => t.filter((x) => x.id !== n.id)), 6000);
    };
    wsRef.current = ws;
    return () => ws.close();
  }, [user]);

  async function handleLogin(e) {
    e.preventDefault();
    const form = new FormData(e.target);
    setError("");
    try {
      await api.login(form.get("email"), form.get("password"));
      setUser(await api.me());
    } catch (err) {
      setError(err.message);
    }
  }

  async function addToCart(id) {
    try { setCart(await api.addToCart(id, 1)); } catch (err) { setError(err.message); }
  }

  async function checkout() {
    try {
      const result = await api.checkout();
      setCart(await api.cart());
      if (result.checkout_url && !result.checkout_url.includes("mock-checkout")) {
        window.location.href = result.checkout_url; // Stripe hosted checkout
      } else {
        alert(`Order #${result.order_id} created (mock mode). Total: $${result.amount}`);
      }
    } catch (err) { setError(err.message); }
  }

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", fontFamily: "system-ui", padding: 16 }}>
      <h1>Smart E-Commerce</h1>
      {error && <p style={{ color: "crimson" }}>{error}</p>}

      {!user ? (
        <form onSubmit={handleLogin} style={{ display: "flex", gap: 8 }}>
          <input name="email" type="email" placeholder="Email" defaultValue="customer@example.com" required />
          <input name="password" type="password" placeholder="Password" required />
          <button type="submit">Login</button>
        </form>
      ) : (
        <p>
          Hi <b>{user.name}</b> ({user.role}) ·{" "}
          <a href="#" onClick={() => { api.logout(); setUser(null); setCart(null); }}>Logout</a>
        </p>
      )}

      <h2>Products</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 12 }}>
        {products.map((p) => (
          <div key={p.id} style={{ border: "1px solid #ddd", borderRadius: 8, padding: 12 }}>
            <b>{p.name}</b>
            <p style={{ margin: "4px 0", color: "#666" }}>{p.category}</p>
            <p>${p.price.toFixed(2)} · {p.stock > 0 ? `${p.stock} in stock` : "Out of stock"}</p>
            {user && p.stock > 0 && <button onClick={() => addToCart(p.id)}>Add to cart</button>}
          </div>
        ))}
      </div>

      {cart && cart.items.length > 0 && (
        <>
          <h2>Cart</h2>
          <ul>
            {cart.items.map((i) => (
              <li key={i.product_id}>
                {i.name} × {i.quantity} = ${i.item_total.toFixed(2)}{" "}
                <a href="#" onClick={async () => setCart(await api.removeFromCart(i.product_id))}>remove</a>
              </li>
            ))}
          </ul>
          <p>
            Subtotal ${cart.cart_total.toFixed(2)} + tax ${cart.tax.toFixed(2)} ={" "}
            <b>${cart.grand_total.toFixed(2)}</b>
          </p>
          <button onClick={checkout}>Checkout with Stripe</button>
        </>
      )}

      <div style={{ position: "fixed", bottom: 16, right: 16, display: "grid", gap: 8 }}>
        {toasts.map((t) => (
          <div key={t.id} style={{ background: "#222", color: "#fff", padding: "10px 14px", borderRadius: 8 }}>
            <b>{t.title}</b>
            <div style={{ fontSize: 13 }}>{t.message}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
