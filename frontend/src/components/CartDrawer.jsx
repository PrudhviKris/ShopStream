import { formatMoney } from "../money";
import { YouMayAlsoLike } from "./Recommendations";

export default function CartDrawer({ open, cart, products, onClose, onUpdateQty, onRemove, onCheckout, onAdd, busy }) {
  if (!open) return null;
  const imageFor = (id) => products.find((p) => p.id === id)?.images?.[0];
  const items = cart?.items || [];

  return (
    <div className="drawer" onClick={onClose}>
      <div className="drawer-backdrop" />
      <aside className="drawer-panel" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <p className="eyebrow">YOUR CART</p>
            <h2>Shopping cart</h2>
          </div>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>

        <div className="drawer-scroll">
          {items.length === 0 ? (
            <div className="empty">
              <div className="big">🛒</div>
              <strong>Your cart is empty</strong>
              <p>Browse the catalog and add something you like.</p>
            </div>
          ) : (
            items.map((item) => (
              <div className="cart-item" key={item.product_id}>
                <img src={imageFor(item.product_id)} alt="" />
                <div className="meta">
                  <strong>{item.name}</strong>
                  <small>{formatMoney(item.unit_price)} each</small>
                  {!item.in_stock && <small style={{ color: "var(--danger)", display: "block" }}>Not enough stock</small>}
                  <div className="qty" style={{ marginTop: 8, width: "fit-content" }}>
                    <button onClick={() => onUpdateQty(item.product_id, item.quantity - 1)}>−</button>
                    <span>{item.quantity}</span>
                    <button onClick={() => onUpdateQty(item.product_id, item.quantity + 1)}>+</button>
                  </div>
                </div>
                <div className="right">
                  <span className="price" style={{ fontSize: 15 }}>{formatMoney(item.item_total)}</span>
                  <button className="link-danger" onClick={() => onRemove(item.product_id)}>Remove</button>
                </div>
              </div>
            ))
          )}
          {onAdd && (
            <YouMayAlsoLike
              excludeIds={items.map((i) => i.product_id)}
              onOpen={onAdd}
              onAdd={onAdd}
            />
          )}
        </div>

        {items.length > 0 && cart && (
          <div className="cart-footer">
            <div className="sum-row"><span>Subtotal</span><span>{formatMoney(cart.cart_total)}</span></div>
            <div className="sum-row"><span>Tax ({(cart.tax_rate * 100).toFixed(0)}%)</span><span>{formatMoney(cart.tax)}</span></div>
            <div className="sum-row total"><span>Total</span><span>{formatMoney(cart.grand_total)}</span></div>
            <div className="pay-btns">
              <button className="btn btn-primary btn-block" disabled={busy} onClick={() => onCheckout("stripe")}>
                {busy ? "Processing…" : "💳 Pay with Stripe"}
              </button>
              <button className="btn btn-soft btn-block" disabled={busy} onClick={() => onCheckout("cash")}>
                💵 Cash on delivery
              </button>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
