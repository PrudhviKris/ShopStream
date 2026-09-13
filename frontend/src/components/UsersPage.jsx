import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { formatMoney } from "../money";
import { useStoreEvent } from "../live";

const ROLE_FILTERS = ["", "admin", "staff", "customer"];

export default function UsersPage() {
  const [users, setUsers] = useState([]);
  const [role, setRole] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const debounce = useRef(null);

  const load = () => {
    const params = {};
    if (role) params.role = role;
    if (query) params.search = query;
    setLoading(true);
    return api.adminUsers(params).then(setUsers).catch(() => {}).finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [role, query]); // eslint-disable-line react-hooks/exhaustive-deps
  // Order counts and spend change as orders are placed and paid.
  useStoreEvent(["order_status_updated", "order_deleted"], load, 800);

  function onSearch(text) {
    setSearch(text);
    clearTimeout(debounce.current);
    debounce.current = setTimeout(() => setQuery(text.trim()), 300);
  }

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">ADMIN PANEL</p>
          <h1>Users</h1>
          <p>Every account, with orders placed and lifetime spend.</p>
        </div>
      </div>

      <div className="toolbar">
        <input
          className="toolbar-search"
          placeholder="Search name or email…"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          aria-label="Search users"
        />
        <div className="chip-row" role="group" aria-label="Filter by role">
          {ROLE_FILTERS.map((r) => (
            <button key={r || "all"} className={`chip ${role === r ? "on" : ""}`} onClick={() => setRole(r)}>
              {r ? r[0].toUpperCase() + r.slice(1) : "All roles"}
            </button>
          ))}
        </div>
        <span className="sub">{loading ? "Loading…" : `${users.length} account${users.length === 1 ? "" : "s"}`}</span>
      </div>

      <div className="panel table-wrap">
        <table className="data-table">
          <thead>
            <tr><th>Customer #</th><th>Name</th><th>Role</th><th>Sign-in</th><th>Joined</th><th className="num">Orders</th><th className="num">Spent</th></tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>#{u.customer_number ?? "—"}<div className="sub">id {u.id}</div></td>
                <td>{u.name}<div className="sub">{u.email}</div></td>
                <td><span className={`badge role-${u.role}`}>{u.role}</span></td>
                <td className="sub">{u.auth_provider}</td>
                <td className="sub">{new Date(u.created_at + "Z").toLocaleDateString()}</td>
                <td className="num">
                  {u.orders}
                  {u.last_order_at && <div className="sub">last {new Date(u.last_order_at + "Z").toLocaleDateString()}</div>}
                </td>
                <td className="num">{formatMoney(u.total_spent)}</td>
              </tr>
            ))}
            {!loading && users.length === 0 && <tr><td colSpan={7} className="sub">No users match.</td></tr>}
          </tbody>
        </table>
      </div>

      <p className="sub-note" style={{ marginTop: 12 }}>
        Roles are read-only here by design — change them in MySQL
        (<code>UPDATE users SET role = 'staff' WHERE id = …;</code>). The change applies on the user's next request.
      </p>
    </>
  );
}
