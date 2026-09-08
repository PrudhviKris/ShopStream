import { useEffect, useState } from "react";
import { api } from "../api";
import { isAdmin } from "../roles";

const TRACK_STEPS = ["pending", "paid", "shipped", "delivered"];
const NEXT_STATUS = { pending: ["cancelled"], paid: ["shipped", "cancelled"], shipped: ["delivered"] };

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

function MyOrders({ orders, invoices, onPayNow, onShop }) {
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
            <span className="id">Order #{order.id}</span>
            <span className="date">{new Date(order.created_at + "Z").toLocaleString()}</span>
            <span className={`badge ${order.order_status}`}>{order.order_status}</span>
            <span className={`badge ${order.payment_status}`}>payment: {order.payment_status}</span>
            {invoiceFor(order.id) && <span className="invoice-tag">🧾 {invoiceFor(order.id).invoice_number}</span>}
            <span className="total">${order.total.toFixed(2)}</span>
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
            order.payment?.payment_method === "cash" ? (
              <span className="sub-note">Pay in cash when your order arrives — staff will confirm receipt.</span>
            ) : (
              <div><button className="btn btn-soft btn-sm" onClick={() => onPayNow(order.id)}>💳 Complete payment</button></div>
            )
          )}
        </div>
      ))}
    </div>
  );
}

function AllOrders({ user, notify }) {
  const [orders, setOrders] = useState([]);

  const reload = () => api.allOrders().then(setOrders).catch(() => {});
  useEffect(() => { reload(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function changeStatus(id, status) {
    try { await api.updateOrderStatus(id, status); reload(); notify("Order updated", `Order #${id} → ${status}`); }
    catch (err) { notify("Update failed", err.message); }
  }
  async function confirmCash(id) {
    try { await api.confirmCashPayment(id); reload(); notify("Cash received", `Order #${id} marked paid; invoice issued.`); }
    catch (err) { notify("Confirm failed", err.message); }
  }
  async function remove(id) {
    if (!window.confirm(`Delete order #${id} with its payment and invoice? Stock is restored unless shipped.`)) return;
    try { await api.deleteOrder(id); reload(); notify("Order deleted", `Order #${id} removed.`); }
    catch (err) { notify("Delete failed", err.message); }
  }

  return (
    <div className="panel table-wrap">
      <table className="data-table">
        <thead><tr><th>Order</th><th>Customer</th><th>Items</th><th>Total</th><th>Payment</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id}>
              <td>#{o.id}<div className="sub">{new Date(o.created_at + "Z").toLocaleDateString()}</div></td>
              <td>{o.user_name}<div className="sub">{o.user_email}</div></td>
              <td>{o.items.map((i) => `${i.product_name} × ${i.quantity}`).join(", ")}</td>
              <td>${o.total.toFixed(2)}</td>
              <td><span className={`badge ${o.payment_status}`}>{o.payment_status}</span></td>
              <td><span className={`badge ${o.order_status}`}>{o.order_status}</span></td>
              <td className="row-actions">
                {o.payment?.payment_method === "cash" && o.payment_status === "pending" && (
                  <button className="mini-btn" onClick={() => confirmCash(o.id)}>💵 cash received</button>
                )}
                {(NEXT_STATUS[o.order_status] || []).map((s) => (
                  <button key={s} className="mini-btn" onClick={() => changeStatus(o.id, s)}>{s}</button>
                ))}
                {isAdmin(user.role) && <button className="mini-btn danger" onClick={() => remove(o.id)}>Delete</button>}
              </td>
            </tr>
          ))}
          {orders.length === 0 && <tr><td colSpan={7} className="sub">No orders yet.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

export default function OrdersPage({ user, orders, invoices, canManage, onPayNow, onShop, notify }) {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{canManage ? "Order management" : "My orders"}</h1>
          <p>{canManage ? "Every customer's order — update status or confirm cash payments." : "Track and manage your own orders."}</p>
        </div>
      </div>
      {canManage
        ? <AllOrders user={user} notify={notify} />
        : <MyOrders orders={orders} invoices={invoices} onPayNow={onPayNow} onShop={onShop} />}
    </>
  );
}
