import { useEffect, useState } from "react";
import { api } from "../api";
import { formatMoney } from "../money";
import { RatingSummary } from "./Reviews";

function Placeholder({ name }) {
  const initials = name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  return <div className="product-placeholder">{initials}</div>;
}

function RailCard({ product, onOpen, onAdd }) {
  const hasImage = Boolean(product.images?.[0]);
  return (
    <article className="product-card rail-card">
      <div className="product-img" onClick={() => onOpen(product)}>
        {hasImage ? <img src={product.images[0]} alt={product.name} loading="lazy" /> : <Placeholder name={product.name} />}
      </div>
      <div className="product-body">
        <span className="cat">{product.category}</span>
        <h3 className="title" onClick={() => onOpen(product)}>{product.name}</h3>
        <RatingSummary product={product} />
        <div className="price-row2">
          <span className="price">{formatMoney(product.price)}</span>
          <button
            className="add-btn" title="Add to cart"
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

/** Horizontal-scrolling row of product cards. Renders nothing while loading
 * or once loaded empty — a section with nothing to show shouldn't take up
 * space or announce itself. */
export function ProductRail({ title, subtitle, products, onOpen, onAdd }) {
  if (products !== null && products.length === 0) return null;
  return (
    <div className="rail-section">
      <div className="rail-head">
        <h3>{title}</h3>
        {subtitle && <span className="sub">{subtitle}</span>}
      </div>
      {products === null ? (
        <div className="rail skeleton">
          {[1, 2, 3, 4].map((i) => <div key={i} className="rail-card-skeleton" />)}
        </div>
      ) : (
        <div className="rail">
          {products.map((p) => <RailCard key={p.id} product={p} onOpen={onOpen} onAdd={onAdd} />)}
        </div>
      )}
    </div>
  );
}

/** "Recommended for you" — the signed-in user's own personalized picks. */
export function RecommendedForYou({ userId, onOpen, onAdd }) {
  const [products, setProducts] = useState(null);
  useEffect(() => {
    setProducts(null);
    api.recommendations(userId).then(setProducts).catch(() => setProducts([]));
  }, [userId]);
  return (
    <ProductRail
      title="Recommended For You"
      subtitle="Based on what you've bought and browsed"
      products={products}
      onOpen={onOpen}
      onAdd={onAdd}
    />
  );
}

/** "You may also like" — trending picks, with anything already in the cart
 * filtered out (no point suggesting what's already there). */
export function YouMayAlsoLike({ excludeIds = [], onOpen, onAdd }) {
  const [products, setProducts] = useState(null);
  useEffect(() => {
    api.trendingProducts(12).then(setProducts).catch(() => setProducts([]));
  }, []);
  const filtered = products === null ? null : products.filter((p) => !excludeIds.includes(p.id)).slice(0, 8);
  return (
    <ProductRail title="You May Also Like" products={filtered} onOpen={onOpen} onAdd={onAdd} />
  );
}

/** "Similar Products" — shown on a product's detail view. */
export function SimilarProducts({ productId, onOpen, onAdd }) {
  const [products, setProducts] = useState(null);
  useEffect(() => {
    setProducts(null);
    api.similarProducts(productId).then(setProducts).catch(() => setProducts([]));
  }, [productId]);
  return (
    <ProductRail title="Similar Products" products={products} onOpen={onOpen} onAdd={onAdd} />
  );
}
