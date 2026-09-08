import { roleMeta } from "../roles";

const LINKS = [
  { id: "dashboard", label: "Overview", icon: "🏠" },
  { id: "products", label: "Products", icon: "🗂️" },
  { id: "orders", label: "Orders", icon: "📦" },
  { id: "payments", label: "Payments", icon: "💳" },
  { id: "invoices", label: "Invoices", icon: "🧾" },
];

export default function Sidebar({ user, view, onNavigate }) {
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
        {LINKS.map((l) => (
          <button key={l.id} className={view === l.id ? "active" : ""} onClick={() => onNavigate(l.id)}>
            <span>{l.icon}</span> {l.label}
          </button>
        ))}
      </div>
      <div className="side-footer">
        <span>Smart E-Commerce</span>
        <small>FastAPI • Django • React</small>
      </div>
    </aside>
  );
}
