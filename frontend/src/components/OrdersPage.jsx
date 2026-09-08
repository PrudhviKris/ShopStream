const TRACK_STEPS = ["pending", "paid", "shipped", "delivered"];

function Track({ status }) {
  if (status === "cancelled") return null;
  const idx = TRACK_STEPS.indexOf(status);
  return (
    <div className="order-track">
      {TRACK_STEPS.map((step, i) => (
        <span key={step} style={{ display: "contents" }}>
          {i > 0 && <span className={`step-bar ${i <= idx ? "done" : ""}`} />}
          <span className={`step ${i <= idx ? "done" : ""}`}>
            <span className="dot" /> {step}
          </span>
        </span>
      ))}
    </div>
  );
}

export default function OrdersPage({ orders, invoices, onPayNow, onShop }) {
  const invoiceFor = (orderId) => (invoices || []).find((i) => i.order_id === orderId);
  if (orders.length === 0) {
    return (
      <div className="panel empty">
        <div className="big">📦</div>
        <h3>No orders yet</h3>
        <p>Your orders will appear here after checkout.</p>
        <button className="btn btn-primary" onClick={onShop}>Start shopping</button>
      </div>
    );
  }

  return (
    <>
      <h1 className="page-title">My orders</h1>
      <div className="panel">
        {orders.map((order) => (
          <div className="order" key={order.id}>
            <div className="order-head">
              <span className="id">Order #{order.id}</span>
              <span className="date">{new Date(order.created_at + "Z").toLocaleString()}</span>
              <span className={`pill ${order.order_status}`}>{order.order_status}</span>
              <span className={`pill ${order.payment_status}`}>payment: {order.payment_status}</span>
              {invoiceFor(order.id) && (
                <span className="invoice-tag" title="Invoice number">
                  🧾 {invoiceFor(order.id).invoice_number}
                </span>
              )}
              <span className="total">${order.total.toFixed(2)}</span>
            </div>
            <div className="order-items">
              {order.items.map((i) => `${i.product_name} × ${i.quantity}`).join("  ·  ")}
            </div>
            <Track status={order.order_status} />
            {order.order_status === "pending" && order.payment_status === "pending" && (
              <div>
                <button className="btn btn-soft btn-sm" onClick={() => onPayNow(order.id)}>
                  💳 Complete payment
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
