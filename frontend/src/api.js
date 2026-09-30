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
  // Adopt tokens delivered via the OAuth redirect fragment (#access_token=…)
  adoptTokens: (access_token, refresh_token) => tokens.set({ access_token, refresh_token }),
  // Browser-redirect entry points for the server-side OAuth flow
  socialLoginUrl: (provider) => `${ABSOLUTE_BASE}/auth/${provider}/login`,

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

  checkout: (paymentMethod = "stripe") =>
    request(`/checkout?flow=session&payment_method=${paymentMethod}`, { method: "POST" }),
  orders: () => request("/orders"),
  // Staff/admin: confirm an order's payment by order id (works for Stripe and
  // cash alike — the manual counterpart to the Stripe webhook).
  confirmPayment: (orderId) =>
    request(`/payments/confirm/${orderId}?outcome=success`, { method: "POST" }),
  confirmCashPayment: (orderId) =>
    request(`/payments/cash/confirm/${orderId}`, { method: "POST" }),
  deleteOrder: (orderId) => request(`/orders/${orderId}`, { method: "DELETE" }),
  deletePayment: (paymentId) => request(`/payments/${paymentId}`, { method: "DELETE" }),
  notifications: () => request("/notifications"),
  // POST /notifications/read — pass ids to mark just those, nothing to mark all.
  markNotificationsRead: (ids) =>
    request("/notifications/read", { method: "POST", body: ids ? { notification_ids: ids } : { all: true } }),

  // ---- email ----
  myEmails: (params = {}) => request(`/dev/emails?${new URLSearchParams(params)}`),
  inboxSummary: () => request("/dev/emails/summary"),
  // Pass ids to mark just those, nothing to mark every email read.
  markEmailsRead: (ids) =>
    request("/dev/emails/read", { method: "POST", body: ids ? { email_ids: ids } : { all: true } }),

  // ---- admin panel ----
  analytics: (days = 30) => request(`/admin/analytics?days=${days}`),
  adminUsers: (params = {}) => request(`/admin/users?${new URLSearchParams(params)}`),
  adminEmails: (params = {}) => request(`/admin/emails?${new URLSearchParams(params)}`),
  retryEmail: (id) => request(`/admin/emails/${id}/retry`, { method: "POST" }),

  // ---- returns & refunds ----
  returnReasons: () => request("/returns/reasons"),
  requestReturn: (orderId, reason, comment) =>
    request(`/orders/${orderId}/return`, { method: "POST", body: { reason, comment: comment || null } }),
  myReturns: () => request("/returns"),
  // staff/admin
  allReturns: (status) => request(`/returns/all${status ? `?status=${status}` : ""}`),
  approveReturn: (id, note) => request(`/returns/${id}/approve`, { method: "POST", body: { note: note || null } }),
  rejectReturn: (id, note) => request(`/returns/${id}/reject`, { method: "POST", body: { note: note || null } }),

  // ---- reviews & ratings ----
  productReviews: (productId, sort = "recent") => request(`/products/${productId}/reviews?sort=${sort}`),
  myReviewEligibility: (productId) => request(`/products/${productId}/reviews/mine`),
  createReview: (product_id, rating, comment) =>
    request("/reviews", { method: "POST", body: { product_id, rating, comment: comment || null } }),
  // staff/admin
  allReviews: (status) => request(`/reviews/all${status ? `?status=${status}` : ""}`),
  approveReview: (id) => request(`/reviews/${id}/approve`, { method: "POST" }),
  rejectReview: (id) => request(`/reviews/${id}/reject`, { method: "POST" }),

  // ---- recommendations ----
  trackView: (productId) => request(`/products/${productId}/view`, { method: "POST" }).catch(() => {}),
  similarProducts: (productId, limit = 8) => request(`/products/${productId}/similar?limit=${limit}`),
  trendingProducts: (limit = 8) => request(`/products/trending?limit=${limit}`),
  recommendations: (userId, limit = 8) => request(`/recommendations/${userId}?limit=${limit}`),

  // ---- invoices ----
  myInvoices: () => request("/invoices"),

  // ---- staff/admin: product management ----
  createProduct: (data) => request("/products", { method: "POST", body: data }),
  updateProduct: (id, data) => request(`/products/${id}`, { method: "PUT", body: data }),
  deleteProduct: (id) => request(`/products/${id}`, { method: "DELETE" }),
  updateOrderStatus: (id, status) =>
    request(`/orders/${id}/status?status=${encodeURIComponent(status)}`, { method: "PUT" }),
  orderStatusOptions: (id) => request(`/orders/${id}/status-options`),
  // Receipt for a completed checkout — Stripe redirects back with session_id.
  receipt: ({ session_id, order_id }) =>
    request(`/payments/receipt?${new URLSearchParams(
      session_id ? { session_id } : { order_id }
    )}`),

  // ---- admin: everything, every customer ----
  allOrders: () => request("/orders/all"),
  allPayments: () => request("/payments/all"),
  allInvoices: () => request("/invoices/all"),
  roles: () => request("/roles"),

  // Make sure the access token is fresh before opening a socket with it
  // (a socket can't refresh mid-handshake the way request() does).
  ensureFreshToken: () => request("/auth/me").then(() => true).catch(() => false),

  // Real-time event stream (wss:// automatically when served over https)
  notificationSocket() {
    const ws = new WebSocket(
      `${ABSOLUTE_BASE.replace(/^http/, "ws")}/ws/notifications?token=${tokens.access}`
    );
    return ws;
  },
};
