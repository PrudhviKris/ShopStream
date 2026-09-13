import { roleMeta } from "../roles";

// `roles` limits a link to those roles; omitted means everyone.
const LINKS = [
  { id: "dashboard", label: "Overview", icon: "🏠" },
  { id: "products", label: "Products", icon: "🗂️" },
  { id: "orders", label: "Orders", icon: "📦" },
  { id: "payments", label: "Payments", icon: "💳" },
  { id: "invoices", label: "Invoices", icon: "🧾" },
  { id: "emails", label: "Inbox", icon: "✉️" },
  { id: "analytics", label: "Analytics", icon: "📈", roles: ["admin"], section: "Admin panel" },
  { id: "users", label: "Users", icon: "👥", roles: ["admin"] },
];

export default function Sidebar({ user, view, onNavigate, badges = {} }) {
  const meta = roleMeta(user.role);
  return (
    <aside className="sidebar" style={{ "--role-color": meta.color, "--role-soft": meta.soft }}>
      <div className="side-role">
        <span className="role-dot" />
        <div>
          <small>Signed in as</small>
          <strong>{meta.label.toUpperCase()}</strong>
        </div>
      </div>
      <div className="side-links">
        {LINKS.filter((l) => !l.roles || l.roles.includes(user.role)).map((l) => (
          <div key={l.id} className="side-link-group">
            {l.section && <small className="side-section">{l.section}</small>}
            <button className={view === l.id ? "active" : ""} onClick={() => onNavigate(l.id)}>
              <span>{l.icon}</span> {l.label}
              {badges[l.id] > 0 && (
                <span className="side-badge" aria-label={`${badges[l.id]} unread`}>{badges[l.id]}</span>
              )}
            </button>
          </div>
        ))}
      </div>
      <div className="side-footer">
        <span>Smart E-Commerce</span>
        <small>FastAPI • Django • React</small>
      </div>
    </aside>
  );
}
