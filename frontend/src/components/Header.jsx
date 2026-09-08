import { useEffect, useRef, useState } from "react";
import { api } from "../api";

function timeAgo(iso) {
  const secs = Math.max(1, Math.floor((Date.now() - new Date(iso + "Z")) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

const NOTIF_ICONS = { order: "📦", payment: "💳", info: "🔔" };

export default function Header({ user, cartCount, view, onNavigate, onSearch, onLogout, notifRefresh }) {
  const [notifs, setNotifs] = useState([]);
  const [open, setOpen] = useState(false);
  const anchorRef = useRef(null);

  useEffect(() => {
    if (user) api.notifications().then(setNotifs).catch(() => {});
    else setNotifs([]);
  }, [user, notifRefresh]);

  useEffect(() => {
    function onClickAway(e) {
      if (anchorRef.current && !anchorRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickAway);
    return () => document.removeEventListener("mousedown", onClickAway);
  }, []);

  const unread = notifs.filter((n) => !n.is_read).length;

  async function markAll() {
    await api.markAllNotificationsRead();
    setNotifs((ns) => ns.map((n) => ({ ...n, is_read: true })));
  }

  return (
    <header className="header">
      <div className="header-inner">
        <button className="brand" onClick={() => onNavigate("shop")}>
          <span className="brand-mark">🛍️</span> SmartCart
        </button>

        <div className="search">
          <span className="icon">🔍</span>
          <input
            placeholder="Search products…"
            onChange={(e) => onSearch(e.target.value)}
            aria-label="Search products"
          />
        </div>

        <div className="header-actions">
          {user && (
            <div className="dropdown-anchor" ref={anchorRef}>
              <button
                className={`icon-btn ${open ? "active" : ""}`}
                title="Notifications"
                onClick={() => setOpen((o) => !o)}
              >
                🔔
                {unread > 0 && <span className="badge-dot alert">{unread}</span>}
              </button>
              {open && (
                <div className="dropdown">
                  <div className="dropdown-head">
                    Notifications
                    {unread > 0 && <button onClick={markAll}>Mark all read</button>}
                  </div>
                  {notifs.length === 0 && (
                    <div className="notif"><div className="m">No notifications yet.</div></div>
                  )}
                  {notifs.map((n) => (
                    <div key={n.id} className={`notif ${n.is_read ? "" : "unread"}`}>
                      <span className="ico">{NOTIF_ICONS[n.type] || "🔔"}</span>
                      <div>
                        <div className="t">{n.title}</div>
                        <div className="m">{n.message}</div>
                        <div className="d">{timeAgo(n.created_at)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {user && (user.role === "admin" || user.role === "staff") && (
            <button
              className={`icon-btn ${view === "admin" ? "active" : ""}`}
              title="Store management"
              onClick={() => onNavigate("admin")}
            >
              ⚙️
            </button>
          )}

          {user && (
            <button
              className={`icon-btn ${view === "orders" ? "active" : ""}`}
              title="My orders"
              onClick={() => onNavigate("orders")}
            >
              📦
            </button>
          )}

          <button
            className={`icon-btn ${view === "cart" ? "active" : ""}`}
            title="Cart"
            onClick={() => onNavigate(user ? "cart" : "auth")}
          >
            🛒
            {cartCount > 0 && <span className="badge-dot">{cartCount}</span>}
          </button>

          {user ? (
            <div className="user-chip" title={`${user.email} (${user.role})`}>
              <span className="avatar">{user.name.slice(0, 1).toUpperCase()}</span>
              <span className="name">{user.name}</span>
              <button className="icon-btn" style={{ width: 28, height: 28, fontSize: 14 }} title="Logout" onClick={onLogout}>
                ⏻
              </button>
            </div>
          ) : (
            <button className="btn btn-primary btn-sm" onClick={() => onNavigate("auth")}>
              Sign in
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
