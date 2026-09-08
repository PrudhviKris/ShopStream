import { useEffect, useState } from "react";
import { api } from "../api";

const ORDER_STATUSES = ["pending", "paid", "shipped", "delivered", "cancelled"];
const NEXT_STATUS = { pending: ["cancelled"], paid: ["shipped", "cancelled"], shipped: ["delivered"] };

function ProductEditor({ product, onSaved, onDeleted, notify }) {
  const [form, setForm] = useState({
    name: product.name,
    price: product.price,
    stock: product.stock,
    category: product.category,
    image: product.images?.[0] || "",
  });
  const [dirty, setDirty] = useState(false);

  const set = (patch) => { setForm((f) => ({ ...f, ...patch })); setDirty(true); };

  async function save() {
    try {
      const updated = await api.updateProduct(product.id, {
        name: form.name,
        price: Number(form.price),
        stock: Number(form.stock),
        category: form.category,
        images: form.image ? [form.image] : [],
      });
      setDirty(false);
      onSaved(updated);
      notify("Saved", `${updated.name} updated.`);
    } catch (err) {
      notify("Save failed", err.message);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete "${product.name}"? This cannot be undone.`)) return;
    try {
      await api.deleteProduct(product.id);
      onDeleted(product.id);
      notify("Deleted", `${product.name} removed from the catalog.`);
    } catch (err) {
      notify("Delete failed", err.message);
    }
  }

  return (
    <tr>
      <td><img src={form.image} alt="" className="admin-thumb" /></td>
      <td><input className="cell-input" value={form.name} onChange={(e) => set({ name: e.target.value })} /></td>
      <td><input className="cell-input sm" value={form.category} onChange={(e) => set({ category: e.target.value })} /></td>
      <td><input className="cell-input xs" type="number" step="0.01" min="0" value={form.price} onChange={(e) => set({ price: e.target.value })} /></td>
      <td><input className="cell-input xs" type="number" min="0" value={form.stock} onChange={(e) => set({ stock: e.target.value })} /></td>
      <td><input className="cell-input" placeholder="https://…" value={form.image} onChange={(e) => set({ image: e.target.value })} /></td>
      <td className="row-actions">
        <button className="btn btn-primary btn-sm" disabled={!dirty} onClick={save}>Save</button>
        <button className="btn btn-danger-soft btn-sm" onClick={remove}>Delete</button>
      </td>
    </tr>
  );
}

function NewProductRow({ onCreated, notify }) {
  const blank = { name: "", category: "general", price: "", stock: "", image: "" };
  const [form, setForm] = useState(blank);

  async function create() {
    try {
      const created = await api.createProduct({
        name: form.name,
        category: form.category || "general",
        price: Number(form.price),
        stock: Number(form.stock || 0),
        images: form.image ? [form.image] : [],
        description: "",
      });
      setForm(blank);
      onCreated(created);
      notify("Product created", created.name);
    } catch (err) {
      notify("Create failed", err.message);
    }
  }

  return (
    <tr className="new-row">
      <td>➕</td>
      <td><input className="cell-input" placeholder="New product name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></td>
      <td><input className="cell-input sm" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} /></td>
      <td><input className="cell-input xs" type="number" step="0.01" min="0" placeholder="Price" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} /></td>
      <td><input className="cell-input xs" type="number" min="0" placeholder="Qty" value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} /></td>
      <td><input className="cell-input" placeholder="Image URL" value={form.image} onChange={(e) => setForm({ ...form, image: e.target.value })} /></td>
      <td className="row-actions">
        <button className="btn btn-soft btn-sm" disabled={!form.name || !form.price} onClick={create}>Add</button>
      </td>
    </tr>
  );
}

export default function AdminPage({ user, notify }) {
  const isAdmin = user.role === "admin";
  const [tab, setTab] = useState("products");
  const [products, setProducts] = useState([]);
  const [orders, setOrders] = useState([]);
  const [payments, setPayments] = useState([]);
  const [invoices, setInvoices] = useState([]);

  useEffect(() => {
    api.products({ page_size: 100, sort: "newest" }).then((d) => setProducts(d.items));
  }, []);

  useEffect(() => {
    if (tab === "orders") api.allOrders().then(setOrders).catch(() => {});
    if (tab === "payments" && isAdmin) api.allPayments().then(setPayments).catch(() => {});
    if (tab === "invoices" && isAdmin) api.allInvoices().then(setInvoices).catch(() => {});
  }, [tab, isAdmin]);

  async function changeStatus(orderId, status) {
    try {
      await api.updateOrderStatus(orderId, status);
      setOrders(await api.allOrders());
      notify("Order updated", `Order #${orderId} → ${status}`);
    } catch (err) {
      notify("Update failed", err.message);
    }
  }

  const tabs = [
    { id: "products", label: "🗂️ Products" },
    { id: "orders", label: "📦 Orders" },
    ...(isAdmin ? [{ id: "payments", label: "💳 Payments" }, { id: "invoices", label: "🧾 Invoices" }] : []),
  ];

  return (
    <>
      <h1 className="page-title">Store management</h1>
      <div className="tabs">
        {tabs.map((t) => (
          <button key={t.id} className={`tab ${tab === t.id ? "on" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "products" && (
        <div className="panel table-wrap">
          <table className="admin-table">
            <thead>
              <tr><th></th><th>Name</th><th>Category</th><th>Price</th><th>Stock</th><th>Photo URL</th><th></th></tr>
            </thead>
            <tbody>
              <NewProductRow notify={notify} onCreated={(p) => setProducts((ps) => [p, ...ps])} />
              {products.map((p) => (
                <ProductEditor
                  key={p.id}
                  product={p}
                  notify={notify}
                  onSaved={(u) => setProducts((ps) => ps.map((x) => (x.id === u.id ? u : x)))}
                  onDeleted={(id) => setProducts((ps) => ps.filter((x) => x.id !== id))}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "orders" && (
        <div className="panel table-wrap">
          <table className="admin-table">
            <thead>
              <tr><th>Order</th><th>Customer</th><th>Items</th><th>Total</th><th>Payment</th><th>Status</th><th>Move to</th></tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <td>#{o.id}<div className="sub">{new Date(o.created_at + "Z").toLocaleDateString()}</div></td>
                  <td>{o.user_name}<div className="sub">{o.user_email}</div></td>
                  <td>{o.items.map((i) => `${i.product_name} × ${i.quantity}`).join(", ")}</td>
                  <td>{o.total.toFixed(2)}</td>
                  <td><span className={`pill ${o.payment_status}`}>{o.payment_status}</span></td>
                  <td><span className={`pill ${o.order_status}`}>{o.order_status}</span></td>
                  <td className="row-actions">
                    {(NEXT_STATUS[o.order_status] || []).map((s) => (
                      <button key={s} className="btn btn-ghost btn-sm" onClick={() => changeStatus(o.id, s)}>{s}</button>
                    ))}
                  </td>
                </tr>
              ))}
              {orders.length === 0 && <tr><td colSpan={7} className="sub">No orders yet.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {tab === "payments" && isAdmin && (
        <div className="panel table-wrap">
          <table className="admin-table">
            <thead>
              <tr><th>Payment</th><th>Order</th><th>Customer</th><th>Amount</th><th>Method</th><th>Transaction</th><th>Status</th></tr>
            </thead>
            <tbody>
              {payments.map((p) => (
                <tr key={p.id}>
                  <td>#{p.id}<div className="sub">{new Date(p.created_at + "Z").toLocaleString()}</div></td>
                  <td>#{p.order_id}</td>
                  <td>{p.user_name}<div className="sub">{p.user_email}</div></td>
                  <td>{p.currency.toUpperCase()} {p.amount.toFixed(2)}</td>
                  <td>{p.payment_method}</td>
                  <td className="mono">{p.transaction_id}</td>
                  <td><span className={`pill ${p.status}`}>{p.status}</span></td>
                </tr>
              ))}
              {payments.length === 0 && <tr><td colSpan={7} className="sub">No payments yet.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {tab === "invoices" && isAdmin && (
        <div className="panel table-wrap">
          <table className="admin-table">
            <thead>
              <tr><th>Invoice</th><th>Order</th><th>Customer</th><th>Subtotal</th><th>Tax</th><th>Total</th><th>Issued</th></tr>
            </thead>
            <tbody>
              {invoices.map((inv) => (
                <tr key={inv.id}>
                  <td className="mono">{inv.invoice_number}</td>
                  <td>#{inv.order_id}</td>
                  <td>{inv.user_name}<div className="sub">{inv.user_email}</div></td>
                  <td>{inv.subtotal.toFixed(2)}</td>
                  <td>{inv.tax.toFixed(2)}</td>
                  <td><b>{inv.currency.toUpperCase()} {inv.total.toFixed(2)}</b></td>
                  <td>{new Date(inv.issued_at + "Z").toLocaleString()}</td>
                </tr>
              ))}
              {invoices.length === 0 && <tr><td colSpan={7} className="sub">No invoices yet — they are issued automatically when a payment succeeds.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
