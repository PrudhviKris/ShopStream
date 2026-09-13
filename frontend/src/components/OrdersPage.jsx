import { useEffect, useState } from "react";
import { api } from "../api";
import { useStoreEvent } from "../live";
import { isAdmin } from "../roles";
import { formatMoney } from "../money";

const TRACK_STEPS = ["pending", "paid", "shipped", "delivered"];

// What an order in each state can become, and how that reads to a human.
// Mirrors the backend exactly: "paid" is only ever reached by confirming the
// payment (which also issues the invoice), never by a plain status flip.
const STATUS_ACTIONS = {
  pending: [
    { kind: "confirm", label: "Confirm payment", icon: "✅", hint: "Marks the payment received, moves the order to paid and issues the invoice." },
    { kind: "status", to: "cancelled", label: "Cancel order", icon: "✖", danger: true, hint: "Cancels the order. Nothing is charged." },
  ],
  paid: [
    { kind: "status", to: "shipped", label: "Mark as shipped", icon: "🚚", hint: "Tells the customer their order is on the way." },
    { kind: "status", to: "cancelled", label: "Cancel order", icon: "✖", danger: true, hint: "Cancels a paid order — refund the customer separately in Stripe." },
  ],
  shipped: [
    { kind: "status", to: "delivered", label: "Mark as delivered", icon: "📦", hint: "Completes the order." },
    { kind: "status", to: "cancelled", label: "Cancel order", icon: "✖", danger: true, hint: "Cancels an order already in transit." },
  ],
  delivered: [],
  cancelled: [],
};

function Track({ status }) {
  if (status === "cancelled") return null;
  const idx = TRACK_STEPS.indexOf(status);
  return (
    <div className="order-track">
      {TRACK_STEPS.map((step, i) => (
        <span key={step} style={{ display: "contents" }}>
          {i > 0 && <span className={`step-bar ${i <= idx ? "done" : ""}`} />}
          <span className={`step ${i <= idx ? "done" : ""}`}><span className="dot" /> {step}</span>
        </span>
      ))}
    </div>
  );
}

function MyOrders({ orders, invoices, onShop }) {
  const invoiceFor = (orderId) => (invoices || []).find((i) => i.order_id === orderId);
  if (orders.length === 0) {
    return (
      <div className="panel empty">
        <div className="big">📦</div>
        <strong>No orders yet</strong>
        <p>Your orders will appear here after checkout.</p>
        <button className="btn btn-primary" onClick={onShop}>Start shopping</button>
      </div>
    );
  }
  return (
    <div className="panel">
      {orders.map((order) => (
        <div className="order" key={order.id}>
          <div className="order-head">
            <span className="id">Order #{order.order_number ?? order.id}</span>
            <span className="date">{new Date(order.created_at + "Z").toLocaleString()}</span>
            <span className={`badge ${order.order_status}`}>{order.order_status}</span>
            <span className={`badge ${order.payment_status}`}>payment: {order.payment_status}</span>
            {invoiceFor(order.id) && <span className="invoice-tag">🧾 {invoiceFor(order.id).invoice_number}</span>}
            <span className="total">{formatMoney(order.total)}</span>
          </div>
          <div className="order-items">{order.items.map((i) => `${i.product_name} × ${i.quantity}`).join("  ·  ")}</div>
          {order.payment && (
            <div className="pay-line">
              <span className={`badge ${order.payment.payment_method}`}>
                {order.payment.payment_method === "cash" ? "💵 cash on delivery" : "💳 stripe"}
              </span>
              <span className="mono">txn: {order.payment.transaction_id}</span>
            </div>
          )}
          <Track status={order.order_status} />
          {order.order_status === "pending" && order.payment_status === "pending" && (
            <span className="sub-note">
              {order.payment?.payment_method === "cash"
                ? "Pay in cash when your order arrives — staff will confirm receipt."
                : "Waiting on payment confirmation. It updates here automatically once your card payment clears."}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function StatusBox({ order, user, busy, onConfirm, onStatus, onDelete, onClose }) {
  const actions = STATUS_ACTIONS[order.order_status] || [];
  const isFinal = actions.length === 0;
  const label = `#${order.order_number ?? order.id}`;

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal-backdrop" />
      <div className="modal-card status-box" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close close-btn" onClick={onClose}>✕</button>
        <p className="eyebrow">UPDATE ORDER STATUS</p>
        <h2>Order {label}</h2>

        <div className="status-now">
          <div>
            <small>Customer</small>
            <strong>{order.user_name}</strong>
          </div>
          <div>
            <small>Order status</small>
            <span className={`badge ${order.order_status}`}>{order.order_status}</span>
          </div>
          <div>
            <small>Payment</small>
            <span className={`badge ${order.payment_status}`}>{order.payment_status}</span>
          </div>
          <div>
            <small>Total</small>
            <strong>{formatMoney(order.total)}</strong>
          </div>
        </div>

        <div className="status-actions">
          <p className="status-actions-title">
            {isFinal
              ? "This order is final — no further status changes are possible."
              : "What would you like to do next?"}
          </p>

          {actions.map((a) => (
            <button
              key={a.label}
              className={`status-action ${a.danger ? "danger" : ""}`}
              disabled={busy}
              onClick={() =>
                a.kind === "confirm" ? onConfirm(order) : onStatus(order, a.to)
              }
            >
              <span className="ico">{a.icon}</span>
              <span>
                <strong>{a.label}</strong>
                <small>{a.hint}</small>
              </span>
            </button>
          ))}

          {isAdmin(user.role) && (
            <button className="status-action danger" disabled={busy} onClick={() => onDelete(order)}>
              <span className="ico">🗑</span>
              <span>
                <strong>Delete order</strong>
                <small>Admin only. Removes the order, its payment and invoice; stock is restored unless already shipped.</small>
              </span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function AllOrders({ user, notify }) {
  const [orders, setOrders] = useState([]);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);

  const reload = () => api.allOrders().then(setOrders).catch(() => {});
  useEffect(() => { reload(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // Live: new orders, payments and status changes from anyone appear without a refresh.
  useStoreEvent(["order_status_updated", "order_deleted"], reload, 300);

  const label = (o) => `#${o.order_number ?? o.id}`;

  async function run(fn, onOk) {
    setBusy(true);
    try {
      await fn();
      const fresh = await api.allOrders();
      setOrders(fresh);
      setSelected(null);
      onOk();
    } catch (err) {
      notify("Couldn't update the order", err.message);
    } finally {
      setBusy(false);
    }
  }

  const confirmPayment = (o) =>
    run(
      // Cash gets the cash-specific endpoint so the intent stays explicit;
      // everything else goes through the general confirm.
      () => (o.payment?.payment_method === "cash"
        ? api.confirmCashPayment(o.id)
        : api.confirmPayment(o.id)),
      () => notify("Payment confirmed", `Order ${label(o)} is now paid — invoice issued.`),
    );

  const changeStatus = (o, status) =>
    run(() => api.updateOrderStatus(o.id, status),
        () => notify("Order updated", `Order ${label(o)} → ${status}.`));

  const remove = (o) => {
    if (!window.confirm(`Delete order ${label(o)} with its payment and invoice? Stock is restored unless shipped.`)) return;
    return run(() => api.deleteOrder(o.id),
               () => notify("Order deleted", `Order ${label(o)} removed.`));
  };

  return (
    <>
      <div className="panel table-wrap">
        <table className="data-table">
          <thead><tr><th>Order</th><th>Customer</th><th>Items</th><th>Total</th><th>Payment</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td>{label(o)}<div className="sub">{new Date(o.created_at + "Z").toLocaleDateString()}</div></td>
                <td>{o.user_name}<div className="sub">{o.user_email}</div></td>
                <td>{o.items.map((i) => `${i.product_name} × ${i.quantity}`).join(", ")}</td>
                <td>{formatMoney(o.total)}</td>
                <td><span className={`badge ${o.payment_status}`}>{o.payment_status}</span></td>
                <td><span className={`badge ${o.order_status}`}>{o.order_status}</span></td>
                <td className="row-actions">
                  <button className="mini-btn" onClick={() => setSelected(o)}>Update status</button>
                </td>
              </tr>
            ))}
            {orders.length === 0 && <tr><td colSpan={7} className="sub">No orders yet.</td></tr>}
          </tbody>
        </table>
      </div>

      {selected && (
        <StatusBox
          order={selected}
          user={user}
          busy={busy}
          onConfirm={confirmPayment}
          onStatus={changeStatus}
          onDelete={remove}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}

export default function OrdersPage({ user, orders, invoices, canManage, onShop, notify }) {
  // Staff and admin shop here too, so they get both views: everyone's orders to
  // work through, and their own purchases as a customer.
  const [tab, setTab] = useState("all");
  const showingMine = !canManage || tab === "mine";

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{showingMine ? "My orders" : "Order management"}</h1>
          <p>
            {showingMine
              ? "Track and manage your own purchases."
              : "Every customer's order — update status or confirm payments."}
          </p>
        </div>
        {canManage && (
          <div className="tabs">
            <button className={`tab ${tab === "all" ? "on" : ""}`} onClick={() => setTab("all")}>
              📋 All orders
            </button>
            <button className={`tab ${tab === "mine" ? "on" : ""}`} onClick={() => setTab("mine")}>
              🛍️ My orders ({orders.length})
            </button>
          </div>
        )}
      </div>
      {showingMine
        ? <MyOrders orders={orders} invoices={invoices} onShop={onShop} />
        : <AllOrders user={user} notify={notify} />}
    </>
  );
}
