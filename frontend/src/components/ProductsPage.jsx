import { useState } from "react";
import { Filters, ProductCard } from "./Catalog";
import { ReviewsQueue } from "./Reviews";

export default function ProductsPage({ products, total, filters, setFilters, user, canManage, onOpen, onAdd, onEdit, onDelete, onCreate, notify }) {
  const [tab, setTab] = useState("catalog");
  const showingReviews = canManage && tab === "reviews";

  return (
    <>
      <div className="page-head" style={{ marginBottom: 6 }}>
        <div>
          <h1>{showingReviews ? "Review moderation" : "Products"}</h1>
          <p>
            {showingReviews
              ? "Customer reviews awaiting a decision — approve to publish, reject to keep hidden."
              : canManage
                ? "Browse the catalog, or manage what's for sale."
                : "Find what you're looking for."}
          </p>
        </div>
        {canManage && (
          <div className="tabs">
            <button className={`tab ${tab === "catalog" ? "on" : ""}`} onClick={() => setTab("catalog")}>
              🛍️ Catalog
            </button>
            <button className={`tab ${tab === "reviews" ? "on" : ""}`} onClick={() => setTab("reviews")}>
              ⭐ Reviews
            </button>
          </div>
        )}
        {!showingReviews && canManage && (
          <button className="btn btn-primary" onClick={onCreate}>+ Add product</button>
        )}
      </div>
      {showingReviews ? (
        <ReviewsQueue notify={notify} />
      ) : (
        <div className="shop-layout">
          <Filters filters={filters} setFilters={setFilters} />
          <section>
            <div className="toolbar">
              <span className="count">{total} product{total === 1 ? "" : "s"}{filters.category ? ` in ${filters.category}` : ""}</span>
              <div className="sort-control">
                <span>Sort</span>
                <select value={filters.sort} onChange={(e) => setFilters((f) => ({ ...f, sort: e.target.value }))}>
                  <option value="popularity">Most popular</option>
                  <option value="price_asc">Price: low to high</option>
                  <option value="price_desc">Price: high to low</option>
                  <option value="newest">Newest</option>
                </select>
              </div>
            </div>
            {products.length === 0 ? (
              <div className="panel empty"><div className="big">🔎</div><strong>No products match</strong><p>Try clearing some filters.</p></div>
            ) : (
              <div className="product-grid">
                {products.map((p) => (
                  <ProductCard
                    key={p.id}
                    product={p}
                    canAdd={Boolean(user)}
                    canManage={canManage}
                    onOpen={onOpen}
                    onAdd={onAdd}
                    onEdit={onEdit}
                    onDelete={onDelete}
                  />
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </>
  );
}
