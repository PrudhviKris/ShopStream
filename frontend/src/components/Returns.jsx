import { useEffect, useState } from "react";
import { api } from "../api";
import { useStoreEvent } from "../live";
import { formatMoney } from "../money";

const when = (iso) => new Date(iso + "Z").toLocaleString();
const day = (iso) => new Date(iso + "Z").toLocaleDateString();

/** Customer: pick a reason, add an optional note, send the request. */
export function ReturnRequestModal({ order, onClose, onSubmitted, notify }) {
  const [reasons, setReasons] = useState([]);
  const [reason, setReason] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.returnReasons().then((rows) => {
      setReasons(rows);
      setReason((current) => current || rows[0]?.value || "");
    }).catch(() => {});
  }, []);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.requestReturn(order.id, reason, comment);
      notify("Return requested", `We'll review order #${order.order_number ?? order.id} shortly.`);
      onSubmitted();
    } catch (err) {
      notify("Couldn't request the return", err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal-backdrop" />
      <form className="modal-card status-box" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <button type="button" className="modal-close close-btn" onClick={onClose}>✕</button>
        <p className="eyebrow">REQUEST A RETURN</p>
        <h2>Order #{order.order_number ?? order.id}</h2>

        <div className="status-now">
          <div><small>Items</small><strong>{order.items.length}</strong></div>
          <div><small>Total</small><strong>{formatMoney(order.total)}</strong></div>
          <div>
            <small>Return by</small>
            <strong>{order.return_deadline ? day(order.return_deadline) : "—"}</strong>
          </div>
        </div>

        <label className="field">
          <span>Why are you returning it?</span>
          <select value={reason} onChange={(e) => setReason(e.target.value)} required>
            {reasons.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </label>

        <label className="field">
          <span>Anything else we should know? <em>(optional)</em></span>
          <textarea
            rows={3}
            maxLength={1000}
            value={comment}
            placeholder="E.g. the screen was cracked when the box arrived."
            onChange={(e) => setComment(e.target.value)}
          />
        </label>

        <p className="sub-note">
          Our team reviews every request. If it's approved we refund
          {" "}{formatMoney(order.total)} to your original payment method.
        </p>

        <div className="modal-actions">
          <button type="button" className="btn btn-outline" onClick={onClose}>Not now</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !reason}>
            {busy ? "Sending…" : "Send return request"}
          </button>
        </div>
      </form>
    </div>
  );
}

/** Customer: the state of a return, shown under the order it belongs to. */
export function ReturnState({ request }) {
  if (!request) return null;
  const { status } = request;
  return (
    <div className={`return-state ${status}`}>
      <span className={`badge return-${status}`}>
        {status === "pending" ? "⏳ return under review"
          : status === "approved" ? "✅ return approved" : "✖ return declined"}
      </span>
      <span className="sub">
        {request.reason_label} · asked {when(request.created_at)}
        {request.refund_amount ? ` · refunded ${formatMoney(request.refund_amount)}` : ""}
      </span>
      {request.decision_note && <div className="return-note">“{request.decision_note}”</div>}
    </div>
  );
}

/** Staff/admin: the queue, with approve and reject. */
export function ReturnsQueue({ notify }) {
  const [returns, setReturns] = useState([]);
  const [filter, setFilter] = useState("pending");
  const [busyId, setBusyId] = useState(null);

  const load = () => api.allReturns(filter).then(setReturns).catch(() => {});
  useEffect(() => { load(); }, [filter]); // eslint-disable-line react-hooks/exhaustive-deps
  // A customer opening a request, or a colleague deciding one, lands here live.
  useStoreEvent(["return_requested", "return_resolved", "order_status_updated"], load, 400);

  async function decide(request, approve) {
    const what = approve ? "Approve" : "Decline";
    const note = window.prompt(
      `${what} the return for order #${request.order_number ?? request.order_id}?\n\n` +
      (approve
        ? `${formatMoney(request.refund_amount ?? request.order_total)} will be refunded and the items restocked.`
        : "The order goes back to delivered.") +
      "\n\nAdd a note for the customer (optional):",
      "",
    );
    if (note === null) return;  // cancelled
    setBusyId(request.id);
    try {
      const updated = approve
        ? await api.approveReturn(request.id, note)
        : await api.rejectReturn(request.id, note);
      notify(
        approve ? "Return approved" : "Return declined",
        approve
          ? `${formatMoney(updated.refund_amount)} refunded · ref ${updated.refund_reference}`
          : `Order #${updated.order_number ?? updated.order_id} is back to delivered.`,
      );
      load();
    } catch (err) {
      notify("Couldn't update the return", err.message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <div className="toolbar">
        <div className="chip-row" role="group" aria-label="Filter returns">
          {[["pending", "Waiting on us"], ["approved", "Approved"], ["rejected", "Declined"], ["", "All"]].map(
            ([value, label]) => (
              <button key={value || "all"} className={`chip ${filter === value ? "on" : ""}`}
                      onClick={() => setFilter(value)}>{label}</button>
            ))}
        </div>
        <span className="sub">{returns.length} request{returns.length === 1 ? "" : "s"}</span>
      </div>

      <div className="panel table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Request</th><th>Order</th><th>Customer</th><th>Reason</th>
              <th className="num">Refund</th><th>Status</th><th></th>
            </tr>
          </thead>
          <tbody>
            {returns.map((r) => (
              <tr key={r.id}>
                <td>#{r.id}<div className="sub">{when(r.created_at)}</div></td>
                <td>#{r.order_number ?? r.order_id}</td>
                <td>{r.user_name}<div className="sub">{r.user_email}</div></td>
                <td>
                  {r.reason_label}
                  {r.comment && <div className="sub">“{r.comment}”</div>}
                </td>
                <td className="num">{formatMoney(r.refund_amount ?? r.order_total)}</td>
                <td>
                  <span className={`badge return-${r.status}`}>{r.status}</span>
                  {r.decided_by && <div className="sub">by {r.decided_by}</div>}
                  {r.refund_reference && <div className="sub mono">{r.refund_reference}</div>}
                </td>
                <td className="row-actions">
                  {r.status === "pending" ? (
                    <>
                      <button className="mini-btn" disabled={busyId === r.id} onClick={() => decide(r, true)}>
                        Approve &amp; refund
                      </button>
                      <button className="mini-btn danger" disabled={busyId === r.id} onClick={() => decide(r, false)}>
                        Decline
                      </button>
                    </>
                  ) : (
                    <span className="sub">{r.decided_at ? when(r.decided_at) : ""}</span>
                  )}
                </td>
              </tr>
            ))}
            {returns.length === 0 && (
              <tr><td colSpan={7} className="sub">
                {filter === "pending" ? "Nothing waiting — the queue is clear." : "No return requests here."}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
