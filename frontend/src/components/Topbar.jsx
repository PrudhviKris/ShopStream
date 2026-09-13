import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { roleMeta } from "../roles";
import { notificationIcon } from "../live";

function timeAgo(iso) {
  const secs = Math.max(1, Math.floor((Date.now() - new Date(iso + "Z")) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

export default function Topbar({ user, cartCount, onOpenCart, onNavigate, onSearch, onLogout, notifRefresh, live }) {
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
  const meta = user ? roleMeta(user.role) : null;

  async function markAll() {
    setNotifs((ns) => ns.map((n) => ({ ...n, is_read: true, read_status: true })));
    await api.markNotificationsRead().catch(() => {});
  }

  async function openNotification(n) {
    if (!n.is_read) {
      setNotifs((ns) => ns.map((x) => (x.id === n.id ? { ...x, is_read: true, read_status: true } : x)));
      api.markNotificationsRead([n.id]).catch(() => {});
    }
    if (n.order_id) {
      setOpen(false);
      onNavigate("orders");
    }
  }

  return (
    <header className="topbar">
      <button className="brand" onClick={() => onNavigate("dashboard")}>
        <span className="brand-mark">🛍️</span> SMART<span className="dot">•</span>SHOP
      </button>

      {user && (
        <div className="search">
          <span className="icon">🔍</span>
          <input
            placeholder="Search products…"
            onChange={(e) => onSearch(e.target.value)}
            aria-label="Search products"
          />
        </div>
      )}

      <div className="top-actions">
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
                  <span className="dropdown-title">
                    Notifications
                    <span className={`live-pill ${live ? "on" : ""}`}>
                      <span className="live-dot" />{live ? "Live" : "Reconnecting…"}
                    </span>
                  </span>
                  {unread > 0 && <button onClick={markAll}>Mark all read</button>}
                </div>
                {notifs.length === 0 && <div className="notif"><div className="m">No notifications yet.</div></div>}
                {notifs.map((n) => (
                  <button
                    key={n.id}
                    className={`notif ${n.is_read ? "" : "unread"}`}
                    onClick={() => openNotification(n)}
                    title={n.order_id ? "Open orders" : "Mark as read"}
                  >
                    <span>{notificationIcon(n.type)}</span>
                    <div>
                      <div className="t">{n.title}</div>
                      <div className="m">{n.message}</div>
                      <div className="d">{timeAgo(n.created_at)}</div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <button className="icon-btn" title="Cart" onClick={onOpenCart}>
          🛒
          {cartCount > 0 && <span className="badge-dot">{cartCount}</span>}
        </button>

        {user ? (
          <div className="user-chip">
            <span className="avatar">{user.name.slice(0, 1).toUpperCase()}</span>
            <div className="who" style={{ "--role-color": meta.color }}>
              <strong>{user.name}</strong>
              <small>{meta.label}</small>
            </div>
            <button className="ghost-btn" onClick={onLogout}>Logout</button>
          </div>
        ) : (
          <button className="btn btn-primary btn-sm" onClick={() => onNavigate("auth")}>Sign in</button>
        )}
      </div>
    </header>
  );
}
