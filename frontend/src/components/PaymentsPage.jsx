import { useEffect, useState } from "react";
import { api } from "../api";

function MyPayments({ orders }) {
  const payments = orders.filter((o) => o.payment).map((o) => ({ ...o.payment, order_id: o.id }));
  if (payments.length === 0) {
    return <div className="panel empty"><div className="big">💳</div><strong>No payments yet</strong><p>Payments appear here once you check out.</p></div>;
  }
  return (
    <div className="panel table-wrap">
      <table className="data-table">
        <thead><tr><th>Payment</th><th>Order</th><th>Amount</th><th>Method</th><th>Transaction</th><th>Status</th></tr></thead>
        <tbody>
          {payments.map((p) => (
            <tr key={p.id}>
              <td>#{p.id}<div className="sub">{new Date(p.created_at + "Z").toLocaleString()}</div></td>
              <td>#{p.order_id}</td>
              <td>{p.currency.toUpperCase()} {p.amount.toFixed(2)}</td>
              <td><span className={`badge ${p.payment_method}`}>{p.payment_method}</span></td>
              <td className="mono">{p.transaction_id}</td>
              <td><span className={`badge ${p.status}`}>{p.status}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AllPayments({ notify }) {
  const [payments, setPayments] = useState([]);
  const reload = () => api.allPayments().then(setPayments).catch(() => {});
  useEffect(() => { reload(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function remove(id) {
    if (!window.confirm(`Delete payment #${id}? Its order reverts to payment pending.`)) return;
    try { await api.deletePayment(id); reload(); notify("Payment deleted", `Payment #${id} removed.`); }
    catch (err) { notify("Delete failed", err.message); }
  }

  return (
    <div className="panel table-wrap">
      <table className="data-table">
        <thead><tr><th>Payment</th><th>Order</th><th>Customer</th><th>Amount</th><th>Method</th><th>Transaction</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {payments.map((p) => (
            <tr key={p.id}>
              <td>#{p.id}<div className="sub">{new Date(p.created_at + "Z").toLocaleString()}</div></td>
              <td>#{p.order_id}</td>
              <td>{p.user_name}<div className="sub">{p.user_email}</div></td>
              <td>{p.currency.toUpperCase()} {p.amount.toFixed(2)}</td>
              <td><span className={`badge ${p.payment_method}`}>{p.payment_method}</span></td>
              <td className="mono">{p.transaction_id}</td>
              <td><span className={`badge ${p.status}`}>{p.status}</span></td>
              <td><button className="mini-btn danger" onClick={() => remove(p.id)}>Delete</button></td>
            </tr>
          ))}
          {payments.length === 0 && <tr><td colSpan={8} className="sub">No payments yet.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

export default function PaymentsPage({ user, orders, notify }) {
  const admin = user.role === "admin";
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{admin ? "All payments" : "My payments"}</h1>
          <p>{admin ? "Every payment across every customer, with its Stripe or cash transaction id." : "Your payment history, Stripe and cash alike."}</p>
        </div>
      </div>
      {admin ? <AllPayments notify={notify} /> : <MyPayments orders={orders} />}
    </>
  );
}
