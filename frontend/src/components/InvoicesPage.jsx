import { useEffect, useState } from "react";
import { api } from "../api";
import { formatMoney } from "../money";

export default function InvoicesPage({ user }) {
  const admin = user.role === "admin";
  const [invoices, setInvoices] = useState([]);

  useEffect(() => {
    (admin ? api.allInvoices() : api.myInvoices()).then(setInvoices).catch(() => {});
  }, [admin]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{admin ? "All invoices" : "My invoices"}</h1>
          <p>{admin ? "Every invoice ever issued, across every customer." : "Issued automatically the moment a payment succeeds."}</p>
        </div>
      </div>

      {invoices.length === 0 ? (
        <div className="panel empty"><div className="big">🧾</div><strong>No invoices yet</strong><p>They appear here once a payment succeeds.</p></div>
      ) : (
        <div className="panel table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Invoice</th><th>Order</th>
                {admin && <th>Customer</th>}
                <th>Subtotal</th><th>Tax</th><th>Total</th><th>Issued</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <tr key={inv.id}>
                  <td className="mono">{inv.invoice_number}</td>
                  <td>#{inv.order_number ?? inv.order_id}<div className="sub mono">order ID {inv.order_id}</div></td>
                  {admin && (
                    <td>
                      {inv.user_name}
                      <div className="sub">{inv.user_email}</div>
                      <div className="sub mono">user ID {inv.user_id}</div>
                    </td>
                  )}
                  <td>{formatMoney(inv.subtotal, inv.currency)}</td>
                  <td>{formatMoney(inv.tax, inv.currency)}</td>
                  <td><strong>{formatMoney(inv.total, inv.currency)}</strong></td>
                  <td>{new Date(inv.issued_at + "Z").toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
