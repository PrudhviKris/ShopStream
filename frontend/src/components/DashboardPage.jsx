import { useEffect, useState } from "react";
import { api } from "../api";
import { ROLE_META, roleMeta } from "../roles";
import { formatMoneyShort } from "../money";

export default function DashboardPage({ user, products, cart, orders, onNavigate }) {
  const meta = roleMeta(user.role);
  const [adminStats, setAdminStats] = useState(null);
  const totalStock = products.reduce((a, p) => a + Number(p.stock || 0), 0);
  const cartItems = cart ? cart.items.reduce((a, i) => a + i.quantity, 0) : 0;

  useEffect(() => {
    if (user.role !== "admin") return;
    Promise.all([api.allOrders(), api.allPayments()]).then(([allOrders, allPayments]) => {
      const revenue = allPayments
        .filter((p) => p.status === "succeeded")
        .reduce((sum, p) => sum + p.amount, 0);
      const pending = allOrders.filter((o) => o.order_status === "pending").length;
      const customers = new Set(allOrders.map((o) => o.user_email)).size;
      setAdminStats({ totalOrders: allOrders.length, revenue, pending, customers });
    }).catch(() => {});
  }, [user.role]);

  const firstName = user.name.split(" ")[0];

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">{meta.label.toUpperCase()} PORTAL</p>
          <h1>{user.role === "customer" ? `Hello, ${firstName}.` : `${meta.label} control center`}</h1>
          <p>{user.role === "customer" ? "Browse products and manage your purchases." : meta.tagline}</p>
        </div>
        <div className="head-actions">
          <button className="btn btn-primary" onClick={() => onNavigate("products")}>Browse products</button>
        </div>
      </div>

      <div className={`role-banner ${user.role}`}>
        <p className="eyebrow" style={{ color: "rgba(255,255,255,0.75)" }}>
          {user.role === "admin" ? "FULL ACCESS" : user.role === "staff" ? "OPERATIONS" : "YOUR ACCOUNT"}
        </p>
        <h2>{user.role === "admin" ? "Administrator mode" : user.role === "staff" ? "Staff mode" : "Welcome to SmartCart"}</h2>
        <p>{meta.tagline}</p>
      </div>

      <div className="stats">
        <div className="stat">
          <small>PRODUCTS</small>
          <strong>{products.length}</strong>
          <span>Available catalog</span>
        </div>
        <div className="stat">
          <small>STOCK UNITS</small>
          <strong>{totalStock}</strong>
          <span>Current inventory</span>
        </div>
        <div className="stat">
          <small>YOUR CART</small>
          <strong>{cartItems}</strong>
          <span>Items selected</span>
        </div>
        {user.role === "admin" && adminStats ? (
          <div className="stat">
            <small>TOTAL REVENUE</small>
            <strong>{formatMoneyShort(adminStats.revenue)}</strong>
            <span>{adminStats.totalOrders} orders · {adminStats.customers} customers</span>
          </div>
        ) : (
          <div className="stat">
            <small>ROLE</small>
            <strong style={{ color: meta.color }}>{meta.label}</strong>
            <span>RBAC protected</span>
          </div>
        )}
      </div>

      {user.role === "admin" && adminStats && (
        <div className="stats">
          <div className="stat">
            <small>PENDING ORDERS</small>
            <strong>{adminStats.pending}</strong>
            <span>Need attention</span>
          </div>
          <div className="stat">
            <small>CUSTOMERS SERVED</small>
            <strong>{adminStats.customers}</strong>
            <span>Unique buyers</span>
          </div>
          <div className="stat">
            <small>YOUR ORDERS</small>
            <strong>{orders.length}</strong>
            <span>As a shopper too</span>
          </div>
          <div className="stat">
            <small>ROLE</small>
            <strong style={{ color: meta.color }}>Admin</strong>
            <span>RBAC protected</span>
          </div>
        </div>
      )}

      <div className="panel">
        <div className="panel-head"><h3>What you can do</h3></div>
        <div className="permission-grid">
          {Object.entries(ROLE_META).map(([key, r]) => (
            <div key={key} className={`permission ${key === user.role ? "current" : ""}`} style={{ "--role-color": r.color }}>
              <h4><span className="role-dot" /> {r.label}{key === user.role ? " (you)" : ""}</h4>
              <ul>
                {r.capabilities.map((c) => <li key={c}>{c}</li>)}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
