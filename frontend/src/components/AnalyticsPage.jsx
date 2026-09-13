import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { formatMoney, formatMoneyShort } from "../money";
import { useStoreEvent } from "../live";
import { BarList, TrendChart } from "./charts";

const RANGES = [7, 30, 90];

const compactMoney = (v) =>
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", notation: "compact", maximumFractionDigits: 1 }).format(v);

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

export default function AnalyticsPage({ onNavigate }) {
  const [days, setDays] = useState(30);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [trendAsTable, setTrendAsTable] = useState(false);
  const [updatedAt, setUpdatedAt] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    return api.analytics(days)
      .then((data) => { setStats(data); setError(""); setUpdatedAt(new Date()); })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [days]);

  useEffect(() => { load(); }, [load]);

  // Live: any order or payment change anywhere re-pulls the numbers. A burst
  // of events for one action collapses into a single refetch.
  useStoreEvent(["order_status_updated", "order_deleted"], load, 600);

  if (!stats) {
    return (
      <>
        <AnalyticsHead days={days} setDays={setDays} updatedAt={updatedAt} />
        <div className="panel empty">
          {error ? <><div className="big">⚠️</div><strong>Couldn't load analytics</strong><p>{error}</p></>
                 : <><div className="big">📈</div><strong>Loading analytics…</strong></>}
        </div>
      </>
    );
  }

  const k = stats.kpis;
  const cur = stats.currency;
  const money = (v) => formatMoney(v, cur);
  const statusRows = Object.entries(stats.orders_by_status).map(([key, value]) => ({ key, label: key, value }));
  const categoryRows = stats.sales_by_category.map((c) => ({ key: c.category, label: c.category, value: c.revenue }));
  const methodRows = Object.entries(stats.revenue_by_method).map(([key, value]) => ({ key, label: key, value }));
  const emailRows = Object.entries(stats.emails.by_status).map(([key, value]) => ({ key, label: key, value }));

  return (
    <div className={`analytics ${loading ? "refreshing" : ""}`}>
      <AnalyticsHead days={days} setDays={setDays} updatedAt={updatedAt} />
      {error && <div className="inline-error">Showing the last numbers — refresh failed: {error}</div>}

      <div className="kpi-hero panel">
        <div>
          <small>Revenue · last {days} days</small>
          <strong className="hero-figure">{formatMoneyShort(stats.kpis.window_revenue, cur)}</strong>
          <span className="sub">
            {plural(k.window_orders, "order")} placed in this period · {formatMoneyShort(k.total_revenue, cur)} all time
          </span>
        </div>
        <div className="hero-side">
          <div><small>Average order value</small><b>{formatMoneyShort(k.average_order_value, cur)}</b></div>
          <div><small>Paid orders</small><b>{k.paid_orders} of {k.total_orders}</b></div>
          <div><small>Buyers</small><b>{k.buyers} of {k.accounts} accounts</b></div>
        </div>
      </div>

      <div className="stats">
        <button className="stat stat-link" onClick={() => onNavigate("orders")}>
          <small>Pending payment</small>
          <strong>{k.pending_orders}</strong>
          <span className="muted">Orders not yet paid</span>
        </button>
        <button className="stat stat-link" onClick={() => onNavigate("orders")}>
          <small>Awaiting shipment</small>
          <strong>{k.awaiting_shipment}</strong>
          <span className="muted">Paid, not shipped</span>
        </button>
        <button className="stat stat-link" onClick={() => onNavigate("products")}>
          <small>Low / out of stock</small>
          <strong>{k.low_stock} / {k.out_of_stock}</strong>
          <span className="muted">{k.units_in_stock} units across {k.products} products</span>
        </button>
        <div className="stat">
          <small>Unread notifications</small>
          <strong>{stats.notifications.unread}</strong>
          <span className="muted">{stats.notifications.total} sent in total</span>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <div>
            <h3>Revenue by day</h3>
            <p className="panel-sub">Settled payments, by the day they cleared (UTC)</p>
          </div>
          <div className="seg">
            <button className={!trendAsTable ? "on" : ""} onClick={() => setTrendAsTable(false)}>Chart</button>
            <button className={trendAsTable ? "on" : ""} onClick={() => setTrendAsTable(true)}>Table</button>
          </div>
        </div>
        {trendAsTable ? (
          <div className="table-wrap trend-table">
            <table className="data-table">
              <thead><tr><th>Date</th><th className="num">Orders placed</th><th className="num">Revenue</th></tr></thead>
              <tbody>
                {[...stats.trend].reverse().map((t) => (
                  <tr key={t.date}><td>{t.date}</td><td className="num">{t.orders}</td><td className="num">{money(t.revenue)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <TrendChart
            data={stats.trend}
            valueKey="revenue"
            format={money}
            formatAxis={compactMoney}
            secondary={(p) => plural(p.orders, "order")}
          />
        )}
      </div>

      <div className="viz-grid-2">
        <div className="panel">
          <div className="panel-head"><h3>Orders by status</h3></div>
          <BarList rows={statusRows} format={(v) => String(v)} emptyText="No orders yet." />
        </div>
        <div className="panel">
          <div className="panel-head"><div><h3>Sales by category</h3><p className="panel-sub">Excludes cancelled orders</p></div></div>
          <BarList rows={categoryRows} format={compactMoney} emptyText="No sales yet." />
        </div>
        <div className="panel">
          <div className="panel-head"><h3>Revenue by payment method</h3></div>
          <BarList rows={methodRows} format={compactMoney} emptyText="No settled payments yet." />
        </div>
        <div className="panel">
          <div className="panel-head">
            <div>
              <h3>Email delivery</h3>
              <p className="panel-sub">Backend: <b>{stats.emails.backend}</b> · {plural(stats.emails.total, "email")}</p>
            </div>
            <button className="mini-btn" onClick={() => onNavigate("emails")}>Open log</button>
          </div>
          <BarList rows={emailRows} format={(v) => String(v)} emptyText="No emails sent yet." />
        </div>
      </div>

      <div className="viz-grid-2">
        <div className="panel table-wrap">
          <div className="panel-head"><h3>Top products</h3></div>
          <table className="data-table compact">
            <thead><tr><th>Product</th><th className="num">Units sold</th><th className="num">Revenue</th></tr></thead>
            <tbody>
              {stats.top_products.map((p) => (
                <tr key={p.product_id}><td>{p.name}</td><td className="num">{p.units_sold}</td><td className="num">{money(p.revenue)}</td></tr>
              ))}
              {stats.top_products.length === 0 && <tr><td colSpan={3} className="sub">No sales yet.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="panel table-wrap">
          <div className="panel-head"><div><h3>Restock soon</h3><p className="panel-sub">5 units or fewer</p></div></div>
          <table className="data-table compact">
            <thead><tr><th>Product</th><th>Category</th><th className="num">Stock</th></tr></thead>
            <tbody>
              {stats.low_stock_products.map((p) => (
                <tr key={p.id}>
                  <td>{p.name}</td>
                  <td className="sub">{p.category}</td>
                  <td className="num">
                    {p.stock <= 0 ? <span className="badge cancelled">⛔ Out</span> : <span className="badge pending">⚠ {p.stock} left</span>}
                  </td>
                </tr>
              ))}
              {stats.low_stock_products.length === 0 && <tr><td colSpan={3} className="sub">Everything is well stocked.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="viz-grid-2 wide-left">
        <div className="panel table-wrap">
          <div className="panel-head">
            <h3>Recent orders</h3>
            <button className="mini-btn" onClick={() => onNavigate("orders")}>Manage orders</button>
          </div>
          <table className="data-table compact">
            <thead><tr><th>Order</th><th>Customer</th><th className="num">Total</th><th>Payment</th><th>Status</th></tr></thead>
            <tbody>
              {stats.recent_orders.map((o) => (
                <tr key={o.id}>
                  <td>#{o.order_number ?? o.id}<div className="sub">{new Date(o.created_at + "Z").toLocaleString()}</div></td>
                  <td>{o.customer}</td>
                  <td className="num">{money(o.total)}</td>
                  <td><span className={`badge ${o.payment_status}`}>{o.payment_status}</span></td>
                  <td><span className={`badge ${o.order_status}`}>{o.order_status}</span></td>
                </tr>
              ))}
              {stats.recent_orders.length === 0 && <tr><td colSpan={5} className="sub">No orders yet.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="panel">
          <div className="panel-head">
            <h3>Accounts</h3>
            <button className="mini-btn" onClick={() => onNavigate("users")}>View users</button>
          </div>
          <div className="role-counts">
            {Object.entries(stats.users_by_role).map(([role, count]) => (
              <div key={role} className="role-count">
                <span className={`badge role-${role}`}>{role}</span>
                <strong>{count}</strong>
              </div>
            ))}
          </div>
          <p className="panel-sub" style={{ marginTop: 14 }}>
            New accounts are always customers. Promote someone with
            <code> UPDATE users SET role='staff' WHERE id=…</code> in MySQL.
          </p>
        </div>
      </div>
    </div>
  );
}

function AnalyticsHead({ days, setDays, updatedAt }) {
  return (
    <div className="page-head">
      <div>
        <p className="eyebrow">ADMIN PANEL</p>
        <h1>Analytics</h1>
        <p>
          Revenue, orders, inventory and delivery — updates live as orders change.
          {updatedAt && <span className="sub"> Last updated {updatedAt.toLocaleTimeString()}.</span>}
        </p>
      </div>
      <div className="chip-row" role="group" aria-label="Date range">
        {RANGES.map((d) => (
          <button key={d} className={`chip ${days === d ? "on" : ""}`} onClick={() => setDays(d)}>
            Last {d} days
          </button>
        ))}
      </div>
    </div>
  );
}
