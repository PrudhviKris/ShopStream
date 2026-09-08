const CATEGORIES = ["electronics", "clothing", "home", "sports"];

function StockRibbon({ product }) {
  if (product.stock === 0) return <span className="ribbon out">Out of stock</span>;
  if (product.stock <= 30) return <span className="ribbon low">Only {product.stock} left</span>;
  if (product.popularity >= 300) return <span className="ribbon hot">Popular</span>;
  return null;
}

export function ProductCard({ product, onOpen, onAdd, canAdd }) {
  return (
    <article className="card" onClick={() => onOpen(product)}>
      <div className="card-img">
        <img src={product.images?.[0]} alt={product.name} loading="lazy" />
        <StockRibbon product={product} />
      </div>
      <div className="card-body">
        <span className="cat">{product.category}</span>
        <span className="title">{product.name}</span>
        <div className="card-foot">
          <span className="price">
            ${Math.floor(product.price)}
            <small>.{String(Math.round(product.price % 1 * 100)).padStart(2, "0")}</small>
          </span>
          <button
            className="add-btn"
            title={canAdd ? "Add to cart" : "Sign in to add"}
            disabled={product.stock === 0}
            onClick={(e) => { e.stopPropagation(); onAdd(product); }}
          >
            +
          </button>
        </div>
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
          <button className={`chip ${!filters.category ? "on" : ""}`} onClick={() => set({ category: "" })}>
            All
          </button>
          {CATEGORIES.map((c) => (
            <button
              key={c}
              className={`chip ${filters.category === c ? "on" : ""}`}
              onClick={() => set({ category: filters.category === c ? "" : c })}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      <div className="filter-group">
        <label className="title">Price range ($)</label>
        <div className="price-row">
          <input
            type="number" min="0" placeholder="Min" value={filters.min_price}
            onChange={(e) => set({ min_price: e.target.value })}
          />
          <input
            type="number" min="0" placeholder="Max" value={filters.max_price}
            onChange={(e) => set({ max_price: e.target.value })}
          />
        </div>
      </div>

      <div className="filter-group">
        <label className="check-row">
          <input
            type="checkbox" checked={filters.in_stock}
            onChange={(e) => set({ in_stock: e.target.checked })}
          />
          In stock only
        </label>
      </div>
    </aside>
  );
}

export function ProductModal({ product, qty, setQty, onClose, onAdd }) {
  if (!product) return null;
  const stockClass = product.stock === 0 ? "out" : product.stock <= 30 ? "low" : "ok";
  const stockText =
    product.stock === 0 ? "Out of stock" : product.stock <= 30 ? `Only ${product.stock} left in stock` : "In stock";
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-img">
          <img src={product.images?.[0]} alt={product.name} />
        </div>
        <div className="modal-body">
          <button className="modal-close" onClick={onClose}>✕</button>
          <span className="cat" style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", color: "var(--text-3)" }}>
            {product.category}
          </span>
          <h2>{product.name}</h2>
          <span className="price" style={{ fontSize: 24 }}>${product.price.toFixed(2)}</span>
          <p className="desc">{product.description}</p>
          <span className={`stock-note ${stockClass}`}>{stockText}</span>
          <div className="qty-row">
            <div className="qty">
              <button onClick={() => setQty((q) => Math.max(1, q - 1))}>−</button>
              <span>{qty}</span>
              <button onClick={() => setQty((q) => Math.min(product.stock || 1, q + 1))}>+</button>
            </div>
            <button
              className="btn btn-primary" style={{ flex: 1 }}
              disabled={product.stock === 0}
              onClick={() => onAdd(product, qty)}
            >
              🛒 Add to cart — ${(product.price * qty).toFixed(2)}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
