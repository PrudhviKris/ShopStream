// Thin API client with automatic JWT refresh.
// Default "/api" goes through the Vite dev-server proxy (same origin), so the app
// works identically on localhost and through a public ngrok tunnel.
const BASE_URL = import.meta.env.VITE_API_URL || "/api";
const ABSOLUTE_BASE = BASE_URL.startsWith("http") ? BASE_URL : window.location.origin + BASE_URL;

const tokens = {
  get access() { return localStorage.getItem("access_token"); },
  get refresh() { return localStorage.getItem("refresh_token"); },
  set(pair) {
    localStorage.setItem("access_token", pair.access_token);
    localStorage.setItem("refresh_token", pair.refresh_token);
  },
  clear() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
  },
};

async function request(path, { method = "GET", body, retry = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (tokens.access) headers.Authorization = `Bearer ${tokens.access}`;
  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && retry && tokens.refresh) {
    const ok = await refreshTokens();
    if (ok) return request(path, { method, body, retry: false });
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Request failed (${res.status})`);
  }
  return res.status === 204 ? null : res.json();
}

async function refreshTokens() {
  try {
    const res = await fetch(`${BASE_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: tokens.refresh }),
    });
    if (!res.ok) { tokens.clear(); return false; }
    tokens.set(await res.json());
    return true;
  } catch {
    return false;
  }
}

export const api = {
  register: (name, email, password) =>
    request("/auth/register", { method: "POST", body: { name, email, password } }).then((t) => tokens.set(t)),
  login: (email, password) =>
    request("/auth/login", { method: "POST", body: { email, password } }).then((t) => tokens.set(t)),
  logout: async () => {
    if (tokens.refresh) {
      // Revoke the refresh token server-side; ignore failures (e.g. offline).
      await request("/auth/logout", { method: "POST", body: { refresh_token: tokens.refresh } }).catch(() => {});
    }
    tokens.clear();
  },
  me: () => request("/auth/me"),
  isLoggedIn: () => Boolean(tokens.access),

  products: (params = {}) =>
    request(`/products?${new URLSearchParams(params)}`),
  product: (id) => request(`/products/${id}`),

  cart: () => request("/cart"),
  addToCart: (product_id, quantity = 1) =>
    request("/cart/add", { method: "POST", body: { product_id, quantity } }),
  updateCart: (product_id, quantity) =>
    request("/cart/update", { method: "PUT", body: { product_id, quantity } }),
  removeFromCart: (product_id) =>
    request(`/cart/remove/${product_id}`, { method: "DELETE" }),

  checkout: () => request("/checkout?flow=session", { method: "POST" }),
  orders: () => request("/orders"),
  mockConfirmPayment: (orderId) =>
    request(`/payments/mock/confirm/${orderId}?outcome=success`, { method: "POST" }),
  notifications: () => request("/notifications"),
  markNotificationRead: (id) => request(`/notifications/${id}/read`, { method: "PUT" }),
  markAllNotificationsRead: () => request("/notifications/read-all", { method: "PUT" }),

  // ---- invoices ----
  myInvoices: () => request("/invoices"),

  // ---- staff/admin: product management ----
  createProduct: (data) => request("/products", { method: "POST", body: data }),
  updateProduct: (id, data) => request(`/products/${id}`, { method: "PUT", body: data }),
  deleteProduct: (id) => request(`/products/${id}`, { method: "DELETE" }),
  updateOrderStatus: (id, status) =>
    request(`/orders/${id}/status`, { method: "PUT", body: { status } }),

  // ---- admin: everything, every customer ----
  allOrders: () => request("/orders/all"),
  allPayments: () => request("/payments/all"),
  allInvoices: () => request("/invoices/all"),
  roles: () => request("/roles"),

  // Real-time notification stream (wss:// automatically when served over https)
  notificationSocket() {
    const ws = new WebSocket(
      `${ABSOLUTE_BASE.replace(/^http/, "ws")}/ws/notifications?token=${tokens.access}`
    );
    return ws;
  },
};
