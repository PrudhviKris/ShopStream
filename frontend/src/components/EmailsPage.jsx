import { useEffect, useState } from "react";
import { api } from "../api";
import { isAdmin } from "../roles";
import { NOTIFICATION_META, useStoreEvent } from "../live";

const STATUS_FILTERS = ["", "stored", "queued", "sent", "failed", "skipped"];
const STATUS_HELP = {
  stored: "Kept in the in-app inbox (EMAIL_BACKEND=database) — not sent to a mail server.",
  queued: "Handed to the SMTP worker, waiting to be delivered.",
  sent: "Accepted by the SMTP server.",
  failed: "The SMTP server refused it or couldn't be reached.",
  skipped: "Not sent over SMTP (placeholder or unverified local address) — readable in the in-app inbox.",
};

const when = (iso) => new Date(iso + "Z").toLocaleString();

function EmailPreview({ email, onRetry, busy, showDelivery }) {
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
        <dt>Received</dt><dd>{when(email.created_at)}</dd>
        {showDelivery && (
          <>
            <dt>Delivery</dt>
            <dd>
              <span className={`badge email-${email.status}`}>{email.status}</span>
              {email.sent_at && <span className="sub"> · sent {when(email.sent_at)}</span>}
              <div className="sub">{STATUS_HELP[email.status]}</div>
              {email.error && <div className="email-error">{email.error}</div>}
              {onRetry && email.status === "failed" && (
                <button className="mini-btn" disabled={busy} onClick={() => onRetry(email)}>Retry sending</button>
              )}
            </dd>
          </>
        )}
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

function EmailList({ emails, selectedId, onSelect, showRecipient, inbox }) {
  return (
    <div className="panel email-list">
      {emails.map((e) => {
        const unread = inbox && !e.is_read;
        return (
          <button
            key={e.id}
            className={`email-row ${selectedId === e.id ? "on" : ""} ${unread ? "unread" : ""}`}
            onClick={() => onSelect(e)}
          >
            <div className="email-row-top">
              <strong>{unread && <span className="unread-dot" aria-label="Unread" />}{e.subject}</strong>
              {!inbox && <span className={`badge email-${e.status}`}>{e.status}</span>}
            </div>
            <div className="sub">
              {showRecipient ? `${e.user_name || ""} <${e.to_email}> · ` : ""}{when(e.created_at)}
            </div>
          </button>
        );
      })}
      {emails.length === 0 && (
        <div className="empty">
          <div className="big">📭</div>
          <strong>{inbox ? "Your inbox is empty" : "No emails"}</strong>
          <p>Order confirmations, payment results and shipping updates land here as soon as they're sent.</p>
        </div>
      )}
    </div>
  );
}

export default function EmailsPage({ user, notify, onUnreadChange }) {
  const admin = isAdmin(user.role);
  const [tab, setTab] = useState("mine");
  const [status, setStatus] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [emails, setEmails] = useState([]);
  const [selected, setSelected] = useState(null);
  const [summary, setSummary] = useState(null);
  const [busy, setBusy] = useState(false);
  const showingAll = admin && tab === "all";

  const load = () => {
    const request = showingAll
      ? api.adminEmails(status ? { status } : {})
      : api.myEmails(unreadOnly ? { unread_only: true } : {});
    if (!showingAll) {
      api.inboxSummary().then((s) => { setSummary(s); onUnreadChange?.(s.unread_count); }).catch(() => {});
    }
    return request.then((rows) => {
      setEmails(rows);
      // Keep the open email open; otherwise don't auto-open (that would mark it read unasked).
      setSelected((cur) => (cur ? rows.find((r) => r.id === cur.id) || null : showingAll ? rows[0] || null : null));
    }).catch(() => {});
  };

  useEffect(() => { setSelected(null); load(); }, [tab, status, unreadOnly]); // eslint-disable-line react-hooks/exhaustive-deps
  // New mail arrives with every order event; other tabs may mark mail read.
  useStoreEvent(["email", "emails_read", "order_status_updated"], load, 500);

  async function open(email) {
    setSelected(email);
    if (showingAll || email.is_read) return;
    // Opening your own email marks it read (admins browsing the log don't).
    setEmails((rows) => rows.map((r) => (r.id === email.id ? { ...r, is_read: true } : r)));
    try {
      const result = await api.markEmailsRead([email.id]);
      onUnreadChange?.(result.unread_count);
      setSummary((s) => (s ? { ...s, unread_count: result.unread_count } : s));
    } catch { /* stays unread server-side; the next load shows the truth */ }
  }

  async function markAllRead() {
    try {
      const result = await api.markEmailsRead();
      onUnreadChange?.(result.unread_count);
      await load();
    } catch (err) {
      notify("Couldn't mark emails read", err.message);
    }
  }

  async function retry(email) {
    setBusy(true);
    try {
      await api.retryEmail(email.id);
      notify("Email re-queued", email.subject);
      await load();
      setTimeout(load, 1500);
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
          <h1>{showingAll ? "Email log" : "Inbox"}</h1>
          <p>
            {showingAll
              ? "Every email the store has sent, and whether it was delivered."
              : "Order confirmations, payment results and shipping updates sent to you."}
          </p>
        </div>
        {admin && (
          <div className="tabs">
            <button className={`tab ${tab === "mine" ? "on" : ""}`} onClick={() => setTab("mine")}>✉️ My inbox</button>
            <button className={`tab ${tab === "all" ? "on" : ""}`} onClick={() => setTab("all")}>📋 All emails</button>
          </div>
        )}
      </div>

      {!showingAll && summary && (
        <div className="inbox-banner">
          <div>
            <small>Mail for</small>
            <strong>{summary.address}</strong>
            <span>{summary.delivery}</span>
          </div>
          <div className="inbox-banner-actions">
            <span className="sub">{summary.unread_count} unread of {summary.total}</span>
            <button className={`chip ${unreadOnly ? "on" : ""}`} onClick={() => setUnreadOnly((u) => !u)}>Unread only</button>
            <button className="mini-btn" disabled={summary.unread_count === 0} onClick={markAllRead}>Mark all read</button>
          </div>
        </div>
      )}

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
        <EmailList emails={emails} selectedId={selected?.id} onSelect={open} showRecipient={showingAll} inbox={!showingAll} />
        <EmailPreview email={selected} busy={busy} onRetry={showingAll ? retry : null} showDelivery={showingAll} />
      </div>
    </>
  );
}
