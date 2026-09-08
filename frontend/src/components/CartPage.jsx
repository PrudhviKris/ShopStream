export default function CartPage({ cart, products, onUpdateQty, onRemove, onCheckout, onShop, busy }) {
  const imageFor = (id) => products.find((p) => p.id === id)?.images?.[0];

  if (!cart || cart.items.length === 0) {
    return (
      <div className="panel empty">
        <div className="big">🛒</div>
        <h3>Your cart is empty</h3>
        <p>Browse the catalog and add something you like.</p>
        <button className="btn btn-primary" onClick={onShop}>Continue shopping</button>
      </div>
    );
  }

  return (
    <>
      <h1 className="page-title">Your cart</h1>
      <div className="two-col">
        <div className="panel">
          {cart.items.map((item) => (
            <div className="cart-item" key={item.product_id}>
              <img src={imageFor(item.product_id)} alt="" />
              <div className="meta">
                <div className="t">{item.name}</div>
                <div className="s">${item.unit_price.toFixed(2)} each</div>
                {!item.in_stock && <div className="s" style={{ color: "var(--danger)" }}>Not enough stock</div>}
                <div className="qty" style={{ marginTop: 8, width: "fit-content" }}>
                  <button onClick={() => onUpdateQty(item.product_id, item.quantity - 1)}>−</button>
                  <span>{item.quantity}</span>
                  <button onClick={() => onUpdateQty(item.product_id, item.quantity + 1)}>+</button>
                </div>
              </div>
              <div className="right">
                <span className="price">${item.item_total.toFixed(2)}</span>
                <button className="link-danger" onClick={() => onRemove(item.product_id)}>Remove</button>
              </div>
            </div>
          ))}
        </div>

        <aside className="panel summary">
          <h3>Order summary</h3>
          <div className="sum-row"><span>Subtotal</span><span>${cart.cart_total.toFixed(2)}</span></div>
          <div className="sum-row">
            <span>Tax ({(cart.tax_rate * 100).toFixed(0)}%)</span>
            <span>${cart.tax.toFixed(2)}</span>
          </div>
          <div className="sum-row total"><span>Total</span><span>${cart.grand_total.toFixed(2)}</span></div>
          <button
            className="btn btn-primary btn-block" style={{ marginTop: 16 }}
            disabled={busy} onClick={() => onCheckout("stripe")}
          >
            {busy ? "Processing…" : "💳 Pay with Stripe"}
          </button>
          <button
            className="btn btn-soft btn-block" style={{ marginTop: 10 }}
            disabled={busy} onClick={() => onCheckout("cash")}
          >
            💵 Cash on delivery
          </button>
        </aside>
      </div>
    </>
  );
}
