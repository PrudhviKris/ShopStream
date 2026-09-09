import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { formatMoney } from "../money";

const fmtTime = (iso) => (iso ? new Date(iso + "Z").toLocaleString() : "—");

function Row({ label, value, mono }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="receipt-row">
      <span className="receipt-label">{label}</span>
      <span className={`receipt-value ${mono ? "mono" : ""}`}>{value}</span>
    </div>
  );
}

export default function ReceiptPage({ sessionId, orderId, cancelled, onDone }) {
  const [receipt, setReceipt] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!cancelled);
  const polls = useRef(0);

  const load = useCallback(async () => {
    try {
      const data = await api.receipt({ session_id: sessionId, order_id: orderId });
      setReceipt(data);
      setError("");
      return data;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setLoading(false);
    }
  }, [sessionId, orderId]);

  useEffect(() => {
    if (cancelled) return;
    let timer;
    const tick = async () => {
      const data = await load();
      // Stripe's redirect usually beats its own webhook by a second or two, so
      // keep checking briefly rather than showing a payment as unconfirmed.
      if (data?.awaiting_confirmation && polls.current < 10) {
        polls.current += 1;
        timer = setTimeout(tick, 2000);
      }
    };
    tick();
    return () => clearTimeout(timer);
  }, [load, cancelled]);

  if (cancelled) {
    return (
      <div className="receipt-wrap">
        <div className="panel receipt cancelled">
          <div className="receipt-mark">✖</div>
          <h1>Payment cancelled</h1>
          <p className="muted">
            No money was taken and your order is still waiting. You can pay for it any time from
            your orders.
          </p>
          <div className="receipt-actions">
            <button className="btn btn-primary" onClick={() => onDone("orders")}>View my orders</button>
            <button className="btn btn-outline" onClick={() => onDone("products")}>Keep shopping</button>
          </div>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="receipt-wrap">
        <div className="panel receipt"><p className="muted">Loading your receipt…</p></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="receipt-wrap">
        <div className="panel receipt cancelled">
          <div className="receipt-mark">!</div>
          <h1>We couldn't load this receipt</h1>
          <p className="muted">{error}</p>
          <div className="receipt-actions">
            <button className="btn btn-primary" onClick={() => onDone("orders")}>View my orders</button>
          </div>
        </div>
      </div>
    );
  }

  const paid = receipt.payment_status === "succeeded";
  const pendingCash = receipt.payment_method === "cash" && !paid;

  return (
    <div className="receipt-wrap">
      <div className={`panel receipt ${paid ? "" : "pending"}`}>
        <div className="receipt-mark">{paid ? "✓" : pendingCash ? "💵" : "⏳"}</div>
        <h1>
          {paid ? "Payment successful" : pendingCash ? "Order placed — pay on delivery" : "Confirming your payment"}
        </h1>
        <p className="muted">
          {paid
            ? `Thank you. Order #${receipt.order_number ?? receipt.order_id} is confirmed.`
            : pendingCash
              ? `Pay ${formatMoney(receipt.amount, receipt.currency)} in cash when your order arrives.`
              : "Your card payment went through and we're waiting for the final confirmation. This page updates itself."}
        </p>

        <div className="receipt-amount">{formatMoney(receipt.amount, receipt.currency)}</div>

        <div className="receipt-details">
          <Row label="Card holder" value={receipt.card_holder_name} />
          <Row label="Card" value={receipt.card_brand && `${receipt.card_brand.toUpperCase()} •••• ${receipt.card_last4}`} />
          <Row label="Amount paid" value={formatMoney(receipt.amount, receipt.currency)} />
          <Row label="Payment method" value={receipt.payment_method === "cash" ? "Cash on delivery" : "Card (Stripe)"} />
          <Row label="Transaction ID" value={receipt.transaction_id} mono />
          <Row label="Time" value={fmtTime(receipt.paid_at || receipt.created_at)} />
          <Row label="Order" value={`#${receipt.order_number ?? receipt.order_id}`} />
          <Row label="Order status" value={receipt.order_status} />
          <Row label="Payment status" value={receipt.payment_status} />
          <Row label="Invoice" value={receipt.invoice_number} mono />
          <Row label="Receipt sent to" value={receipt.receipt_email} />
        </div>

        {receipt.items?.length > 0 && (
          <div className="receipt-items">
            <h3>Items</h3>
            {receipt.items.map((i) => (
              <div className="receipt-item" key={`${i.product_id}-${i.product_name}`}>
                <span>{i.product_name} × {i.quantity}</span>
                <span>{formatMoney(i.unit_price * i.quantity, receipt.currency)}</span>
              </div>
            ))}
          </div>
        )}

        <div className="receipt-actions">
          {receipt.receipt_url && (
            <a className="btn btn-outline" href={receipt.receipt_url} target="_blank" rel="noreferrer">
              Stripe receipt ↗
            </a>
          )}
          <button className="btn btn-primary" onClick={() => onDone("orders")}>View my orders</button>
          <button className="btn btn-outline" onClick={() => onDone("products")}>Keep shopping</button>
        </div>
      </div>
    </div>
  );
}
