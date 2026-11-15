import { useEffect, useState } from "react";
import { api } from "../api.js";

// Case 4: the PAYER's phone. Nobody raised a ticket: the system noticed the double payment
// and asks here. In production this is the customer's logged-in payments app (push notification).
const CUSTOMERS = [
  ["vasanth@oksbi", "Vasanth: ₹650 meal at Kumar Hotel", "ORD-6002"],
  ["lalitha@okaxis", "Lalitha: ₹7,200 hall booking at Kumar Hotel", "ORD-6004"],
];

export default function CustomerPhone({ tabs, vpa, setVpa, opsToken, onOpenCase, onDecided, onError }) {
  const [inbox, setInbox] = useState([]);
  const [busy, setBusy] = useState(null);

  useEffect(() => {
    let stop = false;
    const tick = () => api.customerInbox(vpa).then((x) => !stop && setInbox(x)).catch(() => {});
    tick();
    const t = setInterval(tick, 1500);
    return () => { stop = true; clearInterval(t); };
  }, [vpa]);

  const order = CUSTOMERS.find((c) => c[0] === vpa)?.[2];

  async function act(key, fn) {
    setBusy(key);
    try { await fn(); setInbox(await api.customerInbox(vpa)); }
    catch (e) { onError(e.message); }
    finally { setBusy(null); }
  }

  const simulate = () => act("sim", async () => {
    try {
      const r = await api.duplicatePayment(opsToken, order);
      onOpenCase(r.case_id);
    } catch (e) {
      if (e.status === 409) throw new Error("That double payment was already handled. Press Reset to replay it.");
      throw e;
    }
  });

  const decide = (item, decision) => act(item.case_id + decision, async () => {
    await api.customerDecide(item.case_id, decision, item.ask.token, item.ask.evidence_hash);
    onDecided(item.case_id);
  });

  const noReply = (item) => act(item.case_id + "nr", async () => {
    await api.customerNoReply(opsToken, item.case_id);
    onDecided(item.case_id);
  });

  return (
    <section className="panel chat-panel" aria-label="Customer phone">
      <div className="panel-head">{tabs}</div>

      <div className="who">
        <label htmlFor="vpa">Customer</label>
        <select id="vpa" value={vpa} onChange={(e) => setVpa(e.target.value)}>
          {CUSTOMERS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </select>
      </div>

      <div className="phone customer">
        <div className="phone-top cust">
          <span className="avatar">{vpa[0].toUpperCase()}</span>
          <div>
            <b>My Payments</b>
            <small>{vpa}</small>
          </div>
        </div>

        <div className="messages">
          {!inbox.length && (
            <div className="empty">
              No alerts. Press <b>Simulate double payment</b> below: the customer pays the same bill twice by
              mistake, and the AI notices on its own, without any complaint or ticket.
            </div>
          )}
          {inbox.map((it) => (
            <div key={it.case_id} className="cust-thread">
              <small className="thread-tag">{it.merchant} · {it.case_id}</small>
              {it.messages.map((m, i) => <div key={i} className="bubble agent">{m.content}</div>)}
              {it.ask && (
                <div className="consent">
                  <button className="btn approve" disabled={!!busy} onClick={() => decide(it, "keep")}>
                    {busy === it.case_id + "keep" ? "…" : "Keep both"}
                  </button>
                  <button className="btn refund" disabled={!!busy} onClick={() => decide(it, "refund")}>
                    {busy === it.case_id + "refund" ? "…" : "Refund one"}
                  </button>
                  <button className="link small" disabled={!!busy} onClick={() => noReply(it)} title="Ops records that the customer never answered">
                    simulate no reply
                  </button>
                </div>
              )}
              {it.status === "waiting_approval" && <div className="sys-note">⏳ Refund under review by our team</div>}
            </div>
          ))}
        </div>

        <button className="sample" onClick={simulate} disabled={!!busy || !order}>
          ⚡ Simulate double payment ({order})
        </button>
      </div>
    </section>
  );
}
