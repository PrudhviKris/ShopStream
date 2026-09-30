import { useEffect, useState } from "react";
import { api } from "../api";
import { formatMoney } from "../money";
import { SimilarProducts } from "./Recommendations";
import { RatingSummary, ReviewsSection } from "./Reviews";

const CATEGORIES = ["electronics", "clothing", "home", "sports"];

function Placeholder({ name }) {
  const initials = name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  return <div className="product-placeholder">{initials}</div>;
}

function StockRibbon({ product }) {
  if (product.stock === 0) return <span className="ribbon out">Out of stock</span>;
  if (product.stock <= 30) return <span className="ribbon low">Only {product.stock} left</span>;
  if (product.popularity >= 300) return <span className="ribbon hot">Popular</span>;
  return null;
}

export function ProductCard({ product, onOpen, onAdd, canAdd, canManage, onEdit, onDelete }) {
  const hasImage = Boolean(product.images?.[0]);
  return (
    <article className="product-card">
      <div className="product-img" onClick={() => onOpen(product)}>
        {hasImage ? <img src={product.images[0]} alt={product.name} loading="lazy" /> : <Placeholder name={product.name} />}
        <StockRibbon product={product} />
      </div>
      <div className="product-body">
        <span className="cat">{product.category}</span>
        <h3 className="title" onClick={() => onOpen(product)}>{product.name}</h3>
        <div className="product-id">Product #{product.product_number ?? product.id} <span className="mono">· id {product.id}</span></div>
        <RatingSummary product={product} />
        <div className="price-row2">
          <div>
            <span className="price">{formatMoney(product.price)}</span>
            <div className="stock-mini">{product.stock > 0 ? `${product.stock} in stock` : "Out of stock"}</div>
          </div>
          {/* Staff and admin shop like anyone else — the backend has always
              allowed it, so the catalog must offer them the cart too. */}
          <button
            className="add-btn" title={canAdd ? "Add to cart" : "Sign in to add"}
            disabled={product.stock === 0}
            onClick={(e) => { e.stopPropagation(); onAdd(product); }}
          >
            +
          </button>
        </div>
        {canManage && (
          <div className="manage-row">
            <button className="mini-btn" onClick={() => onEdit(product)}>Edit</button>
            <button className="mini-btn danger" onClick={() => onDelete(product)}>Delete</button>
          </div>
        )}
      </div>
    </article>
  );
}

export function Filters({ filters, setFilters }) {
  const set = (patch) => setFilters((f) => ({ ...f, ...patch }));
  return (
    <aside className="panel filters">
      <h3>Filters</h3>
      <div className="filter-group">
        <label className="title">Category</label>
        <div className="chip-row">
          <button className={`chip ${!filters.category ? "on" : ""}`} onClick={() => set({ category: "" })}>All</button>
          {CATEGORIES.map((c) => (
            <button key={c} className={`chip ${filters.category === c ? "on" : ""}`} onClick={() => set({ category: filters.category === c ? "" : c })}>
              {c}
            </button>
          ))}
        </div>
      </div>
      <div className="filter-group">
        <label className="title">Price range (₹)</label>
        <div className="price-row">
          <input type="number" min="0" placeholder="Min" value={filters.min_price} onChange={(e) => set({ min_price: e.target.value })} />
          <input type="number" min="0" placeholder="Max" value={filters.max_price} onChange={(e) => set({ max_price: e.target.value })} />
        </div>
      </div>
      <div className="filter-group">
        <label className="check-row">
          <input type="checkbox" checked={filters.in_stock} onChange={(e) => set({ in_stock: e.target.checked })} />
          In stock only
        </label>
      </div>
    </aside>
  );
}

export function ProductDetailModal({ product, qty, setQty, onClose, onAdd, onOpenProduct, user, notify }) {
  const productId = product?.id;
  useEffect(() => {
    if (user && productId) api.trackView(productId);
  }, [user, productId]);

  if (!product) return null;
  const hasImage = Boolean(product.images?.[0]);
  const stockClass = product.stock === 0 ? "out" : product.stock <= 30 ? "low" : "ok";
  const stockText = product.stock === 0 ? "Out of stock" : product.stock <= 30 ? `Only ${product.stock} left in stock` : "In stock";
  return (
    <div className="modal" onClick={onClose}>
      <div className="modal-backdrop" />
      <div className="modal-card product-detail" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close close-btn" onClick={onClose}>✕</button>
        <div className="product-img">
          {hasImage ? <img src={product.images[0]} alt={product.name} /> : <Placeholder name={product.name} />}
        </div>
        <div>
          <span className="cat">{product.category}</span>
          <h2 style={{ margin: "6px 0 4px" }}>{product.name}</h2>
          <p className="id-line mono">Product #{product.product_number ?? product.id} · id {product.id}</p>
          <span className="price" style={{ fontSize: 22 }}>{formatMoney(product.price)}</span>
          <p className="muted" style={{ margin: "10px 0" }}>{product.description}</p>
          <span className={`stock-note ${stockClass}`}>{stockText}</span>
          <div className="qty-row">
            <div className="qty">
              <button onClick={() => setQty((q) => Math.max(1, q - 1))}>−</button>
              <span>{qty}</span>
              <button onClick={() => setQty((q) => Math.min(product.stock || 1, q + 1))}>+</button>
            </div>
            <button className="btn btn-primary" style={{ flex: 1 }} disabled={product.stock === 0} onClick={() => onAdd(product, qty)}>
              🛒 Add to cart — {formatMoney(product.price * qty)}
            </button>
          </div>
        </div>
        <div style={{ gridColumn: "1 / -1" }}>
          <SimilarProducts
            productId={product.id}
            onOpen={onOpenProduct || (() => {})}
            onAdd={(p) => onAdd(p, 1)}
          />
          <ReviewsSection product={product} user={user} notify={notify} />
        </div>
      </div>
    </div>
  );
}

const BLANK_FORM = { name: "", description: "", category: "general", price: "", stock: "", image: "" };

export function ProductFormModal({ product, onClose, onSubmit, onDelete }) {
  const [form, setForm] = useState(BLANK_FORM);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const editing = Boolean(product);

  useEffect(() => {
    setForm(
      product
        ? {
            name: product.name, description: product.description || "", category: product.category,
            price: product.price, stock: product.stock, image: product.images?.[0] || "",
          }
        : BLANK_FORM
    );
    setError("");
  }, [product]);

  if (!product && product !== null) return null; // null = create mode, undefined = closed

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await onSubmit({
        name: form.name,
        description: form.description,
        category: form.category || "general",
        price: Number(form.price),
        stock: Number(form.stock),
        images: form.image ? [form.image] : [],
      }, product?.id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal-backdrop" />
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close close-btn" onClick={onClose}>✕</button>
        <h2>{editing ? "Edit product" : "Add product"}</h2>
        {editing && (
          <p className="id-line mono">Product #{product.product_number ?? product.id} · id {product.id}</p>
        )}
        {error && <div className="form-error">{error}</div>}
        <form onSubmit={submit}>
          <div className="field">
            <label>Name</label>
            <input value={form.name} required minLength={2} maxLength={255} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className="field">
            <label>Description</label>
            <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </div>
          <div className="form-grid">
            <div className="field">
              <label>Category</label>
              <input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
            </div>
            <div className="field">
              <label>Price</label>
              <input type="number" step="0.01" min="0.01" required value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} />
            </div>
          </div>
          <div className="form-grid">
            <div className="field">
              <label>Stock</label>
              <input type="number" min="0" required value={form.stock} onChange={(e) => setForm({ ...form, stock: e.target.value })} />
            </div>
            <div className="field">
              <label>Image URL <small className="muted">(optional)</small></label>
              <input value={form.image} placeholder="https://…" onChange={(e) => setForm({ ...form, image: e.target.value })} />
            </div>
          </div>
          <button className="btn btn-primary btn-block" disabled={busy}>
            {busy ? "Saving…" : editing ? "Save changes" : "Create product"}
          </button>
          {editing && (
            <button type="button" className="btn btn-danger-soft btn-block" style={{ marginTop: 8 }} onClick={() => onDelete(product)}>
              Delete product
            </button>
          )}
        </form>
      </div>
    </div>
  );
}
