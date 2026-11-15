import { useEffect, useState } from "react";
import { api } from "../api.js";
import { inr } from "../events.js";

const load = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } };
const save = (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } };

// Rendered inside the timeline's Ops tab. Stays mounted (hidden) so the tab badge keeps counting.
export default function OpsPanel({ token, setToken, onDecided, onOpen, refreshKey, onCount, hidden }) {
  const [items, setItems] = useState([]);
  const [reviewer, setReviewer] = useState(() => load("msa.reviewer", ""));
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(null);
  const [showToken, setShowToken] = useState(false);

  useEffect(() => {
    let stop = false;
    async function tick() {
      try {
        const a = await api.approvals(token);
        if (!stop) { setItems(a); setErr(""); onCount?.(a.length); }
      } catch (e) {
        if (!stop) setErr(e.status === 401 ? "Ops token rejected. Check it below." : e.message);
      }
    }
    tick();
    const t = setInterval(tick, 2000);
    return () => { stop = true; clearInterval(t); };
  }, [token, refreshKey]);

  async function decide(item, decision) {
    if (!reviewer.trim()) { setErr("Enter your name as reviewer first."); return; }
    setBusy(item.case_id + decision);
    try {
      await api.decide(token, item.case_id, decision, reviewer.trim(), item.evidence_hash);
      const left = items.filter((x) => x.case_id !== item.case_id);
      setItems(left);
      onCount?.(left.length);
      onDecided(item.case_id);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="ops-embedded" role="tabpanel" aria-label="Operations approvals" hidden={hidden}>

      <div className="reviewer">
        <label htmlFor="reviewer">Reviewer</label>
        <input id="reviewer" value={reviewer} placeholder="your name" maxLength={64}
          onChange={(e) => { setReviewer(e.target.value); save("msa.reviewer", e.target.value); }} />
        <button className="btn tiny ghost" onClick={() => setShowToken((s) => !s)}>{showToken ? "hide token" : "token"}</button>
      </div>
      {showToken && (
        <div className="reviewer">
          <label htmlFor="ops-token">X-Ops-Token</label>
          <input id="ops-token" value={token} onChange={(e) => setToken(e.target.value)} />
        </div>
      )}
      {err && <div className="error small">{err}</div>}

      <div className="approvals">
        {!items.length && (
          <div className="empty">
            Nothing to approve. Actions above the policy's auto limits (like a ₹12,000 refund, rule R-22) pause here
            with an evidence pack.
          </div>
        )}
        {items.map((it) => <Card key={it.case_id} it={it} busy={busy} onDecide={decide} onOpen={onOpen} />)}
      </div>
    </div>
  );
}

function Card({ it, busy, onDecide, onOpen }) {
  const p = it.pack;
  const a = p.action;
  const what = a.type === "refund_duplicate"
    ? `Refund ${inr(a.amount)} for ${a.params.order_id}`
    : a.type === "retry_payout" ? `Retry payout ${a.params.payout_id} (${inr(a.amount)})` : a.type;
  return (
    <article className="approval-card">
      <header>
        <span className="rule approval">{p.rule_id} · approval</span>
        <button className="link" onClick={() => onOpen(it.case_id)}>{it.case_id}</button>
      </header>
      <h3>{what}</h3>
      <p className="muted">{p.merchant} ({p.mid}) · {p.reason}</p>
      <p className="muted">Diagnosis: <b>{p.diagnosis?.code}</b>. {p.diagnosis?.summary}</p>

      {p.transactions?.length > 0 && (
        <div className="tx-wrap">
          <table className="tx">
            <thead><tr><th>Order</th><th>Amount</th><th>Time</th><th>Invoice</th><th>Customer</th></tr></thead>
            <tbody>
              {p.transactions.map((t) => (
                <tr key={t.txnId} className={t.orderId === a.params?.order_id ? "hl" : ""}>
                  <td>{t.orderId}</td><td>{inr(t.txnAmount)}</td><td>{t.txnDate?.slice(11, 19)}</td>
                  <td>{t.merchantInvoice || "–"}</td><td>{t.customerVpa}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {p.payout && <p className="muted">Payout {p.payout.payoutId}: {p.payout.status} {p.payout.failureReason} · retries {p.payout.retryCount}</p>}

      <p className="hash">evidence hash <code>{it.evidence_hash}</code>: approval only releases this exact action</p>
      <div className="decide">
        <button className="btn approve" disabled={!!busy} onClick={() => onDecide(it, "approve")}>
          {busy === it.case_id + "approve" ? "Approving…" : "Approve"}
        </button>
        <button className="btn reject" disabled={!!busy} onClick={() => onDecide(it, "reject")}>
          {busy === it.case_id + "reject" ? "Rejecting…" : "Reject"}
        </button>
      </div>
    </article>
  );
}
