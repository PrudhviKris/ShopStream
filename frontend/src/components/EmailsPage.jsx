import { useEffect, useState } from "react";
import { api } from "../api";
import { isAdmin } from "../roles";
import { NOTIFICATION_META, useStoreEvent } from "../live";

const STATUS_FILTERS = ["", "stored", "queued", "sent", "failed", "skipped"];
const STATUS_HELP = {
  stored: "Kept in this inbox (EMAIL_BACKEND=database) — not sent to a mail server.",
  queued: "Handed to the SMTP worker, waiting to be delivered.",
  sent: "Accepted by the SMTP server.",
  failed: "The SMTP server refused it or couldn't be reached.",
  skipped: "Placeholder address (e.g. a Facebook account with no email) — nothing to deliver to.",
};

const when = (iso) => new Date(iso + "Z").toLocaleString();

function EmailPreview({ email, onRetry, busy }) {
  if (!email) {
    return <div className="panel empty email-preview"><div className="big">✉️</div><strong>Select an email</strong><p>Its full content shows here.</p></div>;
  }
  return (
    <div className="panel email-preview">
      <p className="eyebrow">{(NOTIFICATION_META[email.notification_type]?.label || "Email").toUpperCase()}</p>
      <h3 className="email-subject">{email.subject}</h3>
      <dl className="email-meta">
        <dt>To</dt><dd>{email.user_name ? `${email.user_name} <${email.to_email}>` : email.to_email}</dd>
        <dt>From</dt><dd>{email.from_email}</dd>
        <dt>Created</dt><dd>{when(email.created_at)}</dd>
        <dt>Status</dt>
        <dd>
          <span className={`badge email-${email.status}`}>{email.status}</span>
          {email.sent_at && <span className="sub"> · sent {when(email.sent_at)}</span>}
          <div className="sub">{STATUS_HELP[email.status]}</div>
          {email.error && <div className="email-error">{email.error}</div>}
          {onRetry && email.status === "failed" && (
            <button className="mini-btn" disabled={busy} onClick={() => onRetry(email)}>Retry sending</button>
          )}
        </dd>
      </dl>
      {email.html_body ? (
        // sandbox with no permissions: the email's HTML renders, but can't run
        // script, navigate this page, or reach its storage/cookies.
        <iframe className="email-frame" title={email.subject} sandbox="" srcDoc={email.html_body} />
      ) : (
        <pre className="email-text">{email.body}</pre>
      )}
    </div>
  );
}

function EmailList({ emails, selectedId, onSelect, showRecipient }) {
  return (
    <div className="panel email-list">
      {emails.map((e) => (
        <button key={e.id} className={`email-row ${selectedId === e.id ? "on" : ""}`} onClick={() => onSelect(e)}>
          <div className="email-row-top">
            <strong>{e.subject}</strong>
            <span className={`badge email-${e.status}`}>{e.status}</span>
          </div>
          <div className="sub">
            {showRecipient ? `${e.user_name || ""} <${e.to_email}> · ` : ""}{when(e.created_at)}
          </div>
        </button>
      ))}
      {emails.length === 0 && <div className="empty"><div className="big">📭</div><strong>No emails yet</strong><p>Order confirmations, payment and shipping updates land here.</p></div>}
    </div>
  );
}

export default function EmailsPage({ user, notify }) {
  const admin = isAdmin(user.role);
  const [tab, setTab] = useState("mine");
  const [status, setStatus] = useState("");
  const [emails, setEmails] = useState([]);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const showingAll = admin && tab === "all";

  const load = () => {
    const request = showingAll ? api.adminEmails(status ? { status } : {}) : api.myEmails();
    return request.then((rows) => {
      setEmails(rows);
      setSelected((cur) => rows.find((r) => r.id === cur?.id) || rows[0] || null);
    }).catch(() => {});
  };

  useEffect(() => { load(); }, [tab, status]); // eslint-disable-line react-hooks/exhaustive-deps
  // Every order event sends an email, so refresh when one arrives.
  useStoreEvent(["notification", "order_status_updated"], load, 700);

  async function retry(email) {
    setBusy(true);
    try {
      await api.retryEmail(email.id);
      notify("Email re-queued", email.subject);
      setTimeout(load, 1500);
      await load();
    } catch (err) {
      notify("Retry failed", err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{showingAll ? "Email log" : "My emails"}</h1>
          <p>
            {showingAll
              ? "Every email the store has sent, and whether it was delivered."
              : "Order confirmations, payment results and shipping updates sent to you."}
          </p>
        </div>
        {admin && (
          <div className="tabs">
            <button className={`tab ${tab === "mine" ? "on" : ""}`} onClick={() => setTab("mine")}>✉️ My emails</button>
            <button className={`tab ${tab === "all" ? "on" : ""}`} onClick={() => setTab("all")}>📋 All emails</button>
          </div>
        )}
      </div>

      {showingAll && (
        <div className="toolbar">
          <div className="chip-row" role="group" aria-label="Filter by delivery status">
            {STATUS_FILTERS.map((s) => (
              <button key={s || "all"} className={`chip ${status === s ? "on" : ""}`} onClick={() => setStatus(s)}>
                {s || "All statuses"}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="email-layout">
        <EmailList emails={emails} selectedId={selected?.id} onSelect={setSelected} showRecipient={showingAll} />
        <EmailPreview email={selected} busy={busy} onRetry={showingAll ? retry : null} />
      </div>
    </>
  );
}
