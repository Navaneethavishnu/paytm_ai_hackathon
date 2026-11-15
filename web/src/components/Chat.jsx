import { useEffect, useRef, useState } from "react";

// Exactly the texts in app/demo_cases.py, so DEMO_MODE answers them from the warmed cache.
const PROMPTS = {
  M1001: [
    ["Payout missing (Tamil)", "என் ORD-1001 ₹2,400 பணம் இன்னும் என் வங்கிக்கு வரவில்லை"],
    ["Already settled", "Where is my money for ORD-1002?"],
    ["Still on schedule", "ORD-1003 payment not received yet"],
    ["Payment failed", "Customer paid for ORD-1004 but I didn't get it"],
    ["No order ID", "My money didn't come"],
  ],
  M1002: [
    ["Charged twice ₹12,000", "Customer says they were charged twice for ORD-2001, ₹12,000. Please check."],
    ["Charged twice ₹1,499", "ORD-2003 charged twice, ₹1,499"],
  ],
  M1003: [["Someone else's order", "ORD-4001 for ₹48,000 never reached my account."]],
  M1004: [
    ["Big payout ₹75,000 failed", "ORD-4002 ₹75,000 payment has not reached my bank account."],
    ["Own order ORD-4001", "Where is my money for ORD-4001?"],
  ],
  M1005: [["Payout on hold", "Why is my ₹8,000 payout for ORD-5001 on hold?"]],
  // Extra history merchants (app/seed_bulk.py). Not in the demo cache: answered live by Sarvam.
  M1007: [["Payout failed (R-07)", "Where is my money for ORD-7014?"], ["Settled", "ORD-7002 payment status?"], ["Payment failed", "Customer paid for ORD-7001 but I didn't get it"]],
  M1008: [["2nd retry needs Ops (R-08)", "ORD-7113 money still not in my bank, please check"], ["₹1,25,000 paid twice", "Customer paid twice for ORD-7120, ₹1,25,000"]],
  M1009: [["Bank account invalid", "Where is my money for ORD-7213?"], ["₹18,500 paid twice", "Customer charged twice for ORD-7219, ₹18,500"]],
  M1010: [["Payout late", "ORD-7314 payout not received yet"], ["Payment pending", "What happened to ORD-7318?"]],
  M1011: [["Big payout failed (R-10)", "ORD-7415 money not reached my bank"]],
  M1012: [["₹480 paid twice", "Customer paid twice for ORD-7519, ₹480"], ["Settled", "Where is my money for ORD-7501?"]],
};

// Demo phones are 98400000NN, so the PIN (last 4 digits) is "00NN": M1001 -> 0001, M1012 -> 0012.
export const demoPin = (mid) => (mid ? "00" + mid.slice(-2) : "");

export default function Chat({ tabs, merchants, mid, setMid, pin, setPin, view, pending, busy, onSend, onVoice, onSample, onNewCase }) {
  const [text, setText] = useState("");
  const bottom = useRef(null);
  const merchant = merchants.find((m) => m.mid === mid);
  const messages = view?.messages || [];
  const running = busy || view?.running;
  const followUp = view?.status === "needs_info" && !view?.running;
  const outcome = OUTCOME[view?.status] || null;
  // Merchant-facing identity badge: a wrong PIN escalates under G-02; a system event needs no PIN.
  const identity = !view || view.running && !messages.length ? null
    : view.source === "system" ? { text: "System alert", tone: "info" }
    : view.policy?.rule_id === "G-02" ? { text: "✗ Not verified", tone: "bad" }
    : { text: "✓ Verified", tone: "ok" };

  // Braces matter: newer Chrome returns a Promise from scrollIntoView, and an effect may only return a cleanup function.
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages.length, pending, running]);

  function submit(t) {
    const msg = (t ?? text).trim();
    if (!msg || running) return;
    onSend(msg);
    setText("");
  }

  return (
    <section className="panel chat-panel" aria-label="Merchant chat">
      <div className="panel-head">
        {tabs}
        <button className="btn tiny ghost" onClick={onNewCase} disabled={running}>+ New case</button>
      </div>

      {/* Demo sign-in: who is using the phone. In production this is the merchant's logged-in app session. */}
      <div className="signin">
        <label htmlFor="merchant" className="signin-label">Signed in as</label>
        <select id="merchant" title={mid} value={mid} onChange={(e) => { setMid(e.target.value); setPin(demoPin(e.target.value)); }}>
          {merchants.map((m) => (
            <option key={m.mid} value={m.mid}>{m.name}{m.language === "ta-IN" ? " (Tamil)" : ""}</option>
          ))}
        </select>
        <label htmlFor="pin" className="signin-pin" title="Last 4 digits of the registered phone">
          PIN <input id="pin" value={pin} maxLength={4} inputMode="numeric" onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))} />
        </label>
      </div>

      <div className="phone">
        <div className="phone-top">
          <span className="avatar">{merchant?.name?.[0] || "?"}</span>
          <div>
            <b>Payments Help</b>
            <small>{merchant ? `${merchant.name}, ${merchant.city}` : ""}</small>
          </div>
          {identity && <span className={`id-badge ${identity.tone}`}>{identity.text}</span>}
        </div>

        <div className="messages">
          {!messages.length && !pending && (
            <div className="empty">Type a problem, tap a demo prompt, or use the mic. The agent will investigate and fix it.</div>
          )}
          {messages.map((m, i) => {
            const last = i === messages.length - 1 && m.role === "agent";
            return <Bubble key={i} m={m} voice={view?.voice && i === 0} citation={last ? view?.citation : null} outcome={last && !running ? outcome : null} />;
          })}
          {pending && !messages.length && <Bubble m={{ role: "merchant", content: pending.text }} voice={pending.voice} />}
          {followUp && !running && view?.order_choices?.length > 0 && (
            <div className="order-choices" aria-label="Recent payments">
              {view.order_choices.map((c) => (
                <button key={c.order_id} className="order-choice" onClick={() => submit(c.order_id)}>
                  <b>{c.order_id}</b>
                  <span className="oc-amt">₹{c.amount.toLocaleString("en-IN")}</span>
                  <small>{fmtTime(c.time)} · {STATUS_LABEL[c.status] || c.status}</small>
                </button>
              ))}
            </div>
          )}
          {running && <div className="typing"><span /><span /><span /> agent is working</div>}
          <div ref={bottom} />
        </div>

        <div className="prompts">
          {(PROMPTS[mid] || []).map(([label, t]) => (
            <button key={label} className="chip" onClick={() => submit(t)} disabled={running} title={t}>{label}</button>
          ))}
        </div>

        <form className="composer" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <input
            id="chat-input" value={text} onChange={(e) => setText(e.target.value)} maxLength={1000}
            placeholder={followUp ? "Reply with your order ID…" : "Describe the problem…"} disabled={running}
          />
          <Recorder disabled={running || pin.length !== 4} onDone={onVoice} />
          <button className="btn primary" type="submit" disabled={running || !text.trim()}>Send</button>
        </form>
        <button className="sample" onClick={onSample} disabled={running}>▶ Send recorded Tamil voice sample (Case 1)</button>
      </div>
    </section>
  );
}

// Merchant-friendly outcome under the latest reply. Rule IDs stay in the internal timeline.
const OUTCOME = {
  resolved: { text: "✓ Resolved", tone: "ok" },
  escalated: { text: "👤 A specialist will contact you", tone: "esc" },
  waiting_approval: { text: "⏳ With our operations team", tone: "wait" },
  waiting_customer: { text: "⏳ Waiting for the customer's answer", tone: "wait" },
  needs_info: { text: "❓ Tell us which order", tone: "wait" },
};

const STATUS_LABEL = { TXN_SUCCESS: "Paid", TXN_FAILURE: "Failed", PENDING: "Pending" };

// Server sends the mock system's own time ("2026-11-14 16:10:00", already local demo time).
function fmtTime(s) {
  const d = new Date(s.replace(" ", "T"));
  if (isNaN(d)) return s;
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

function Bubble({ m, voice, citation, outcome }) {
  const cls = m.role === "agent" ? "bubble agent" : m.role === "system" ? "bubble system" : "bubble merchant";
  return (
    <div className={cls}>
      {m.role === "system" && <small className="bubble-tag">system event</small>}
      {voice && m.role === "merchant" && <small className="bubble-tag">🎤 voice · transcribed</small>}
      <div>{m.content}</div>
      {outcome && <div className={`outcome ${outcome.tone}`}>{outcome.text}</div>}
      {citation && (
        <div className="citation" title={citation.text}>
          ℹ {citation.title} <span>({citation.doc})</span>
        </div>
      )}
    </div>
  );
}

// Browser mic -> MediaRecorder -> Blob (audio/webm in Chrome, audio/mp4 in Safari). Auto-stops at 25s.
function Recorder({ disabled, onDone }) {
  const [rec, setRec] = useState(null);
  const [secs, setSecs] = useState(0);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!rec) return;
    const t = setInterval(() => setSecs((s) => (s + 1 >= 25 ? (stop(), 25) : s + 1)), 1000);
    return () => clearInterval(t);
  }, [rec]); // eslint-disable-line react-hooks/exhaustive-deps

  async function start() {
    setErr("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      const chunks = [];
      mr.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      mr.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks, { type: mr.mimeType || "audio/webm" });
        if (blob.size) onDone(blob);
      };
      mr.start();
      setSecs(0);
      setRec(mr);
    } catch {
      setErr("Microphone blocked. Allow mic access in the browser.");
    }
  }

  function stop() {
    setRec((r) => {
      if (r && r.state !== "inactive") r.stop();
      return null;
    });
  }

  return (
    <>
      <button type="button" className={`btn mic ${rec ? "on" : ""}`} onClick={rec ? stop : start} disabled={disabled && !rec}
        title={rec ? "Stop and send" : "Speak your problem (Tamil or English)"} aria-label={rec ? "Stop recording" : "Record voice"}>
        {rec ? `■ ${secs}s` : "🎤"}
      </button>
      {err && <span className="mic-err">{err}</span>}
    </>
  );
}
