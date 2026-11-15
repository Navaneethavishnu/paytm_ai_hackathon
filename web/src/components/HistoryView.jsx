import { useEffect, useState } from "react";
import { api } from "../api.js";

// Case history for support / Ops: every case the agent handled, newest first. Click a row to replay it.
const STATUS = {
  resolved: ["Resolved", "auto"],
  escalated: ["Escalated", "escalate"],
  waiting_approval: ["Waiting for Ops", "approval"],
  waiting_customer: ["Waiting for customer", "approval"],
  needs_info: ["Needs info", "approval"],
  open: ["Running", "running"],
};
const FILTERS = [["", "All"], ["resolved", "Resolved"], ["waiting", "Waiting"], ["escalated", "Escalated"], ["needs_info", "Needs info"]];

const localTime = (ts) => {
  const d = new Date(ts + "Z");
  return `${d.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}, ${d.toLocaleTimeString("en-IN", { hour12: false })}`;
};

export default function HistoryView({ token, merchants, currentCase, onOpen, hidden, refreshKey }) {
  const [rows, setRows] = useState([]);
  const [mid, setMid] = useState("");
  const [status, setStatus] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    if (hidden) return undefined;
    let stop = false;
    async function tick() {
      try {
        const r = await api.history(token, { mid, status });
        if (!stop) { setRows(r); setErr(""); }
      } catch (e) {
        if (!stop) setErr(e.status === 401 ? "Ops token rejected. Set it in the Ops approvals tab."
          : e.status === 405 || e.status === 404 ? "The backend is running older code without case history. Restart uvicorn (Ctrl+C, then start it again)."
          : e.message);
      }
    }
    tick();
    const t = setInterval(tick, 3000);
    return () => { stop = true; clearInterval(t); };
  }, [token, mid, status, hidden, refreshKey]);

  return (
    <div className="history" role="tabpanel" aria-label="Case history" hidden={hidden}>
      <div className="history-filters">
        <label htmlFor="hist-mid">Merchant</label>
        <select id="hist-mid" value={mid} onChange={(e) => setMid(e.target.value)}>
          <option value="">All merchants</option>
          {merchants.map((m) => <option key={m.mid} value={m.mid}>{m.mid} · {m.name}</option>)}
        </select>
        <div className="history-status" role="group" aria-label="Filter by outcome">
          {FILTERS.map(([v, label]) => (
            <button key={v} className={status === v ? "on" : ""} aria-pressed={status === v} onClick={() => setStatus(v)}>{label}</button>
          ))}
        </div>
        <span className="history-count">{rows.length} case{rows.length === 1 ? "" : "s"}</span>
      </div>
      {err && <div className="error small">{err}</div>}

      <div className="history-list">
        {!rows.length && !err && (
          <p className="empty">No cases yet{mid || status ? " for this filter" : ""}. Every case the agent handles is saved here with its full step-by-step trail.</p>
        )}
        {rows.length > 0 && (
          <table className="history-table">
            <thead>
              <tr><th>Time</th><th>Case</th><th>Merchant</th><th>Order</th><th>Outcome</th><th>Rule</th><th>Details</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const [label, tone] = STATUS[r.status] || [r.status, ""];
                const details = [
                  r.source === "system" ? (r.trigger === "duplicate_payment" ? "proactive · double payment" : "proactive · system event") : null,
                  r.approval?.decision === "approve" ? `approved by ${r.approval.reviewer}` : null,
                  r.approval?.decision === "reject" ? `rejected by ${r.approval.reviewer}` : null,
                  r.ticket_id ? `ticket ${r.ticket_id}` : null,
                  r.diagnosis,
                ].filter(Boolean).join(" · ");
                return (
                  <tr key={r.case_id} className={r.case_id === currentCase ? "current" : ""} tabIndex={0}
                    onClick={() => onOpen(r.case_id)} onKeyDown={(e) => e.key === "Enter" && onOpen(r.case_id)}
                    title={r.message ? `“${r.message}”` : ""}>
                    <td className="nowrap">{r.started ? localTime(r.started) : ""}</td>
                    <td><code>{r.case_id}</code></td>
                    <td>{r.merchant || r.mid}</td>
                    <td className="nowrap">{r.order_id || "–"}</td>
                    <td><span className={`status-pill ${tone}`}>{label}</span></td>
                    <td>{r.rule_id ? <span className={`rule ${r.tier}`}>{r.rule_id}</span> : "–"}</td>
                    <td className="history-details">{details}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      <p className="history-foot">Click a case to replay its full graph and timeline. Phone numbers and UPI IDs are masked in the audit log.</p>
    </div>
  );
}
