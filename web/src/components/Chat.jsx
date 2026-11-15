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
  M1005: [["Payout on hold", "Why is my ₹8,000 payout for ORD-5001 on hold?"]],};

export const demoPin = (mid) => (mid ? "000" + mid.slice(-1) : "");

export default function Chat({ tabs, merchants, mid, setMid, pin, setPin, view, pending, busy, onSend, onVoice, onSample, onNewCase }) {
  const [text, setText] = useState("");
  const bottom = useRef(null);
  const merchant = merchants.find((m) => m.mid === mid);
  const messages = view?.messages || [];
  const running = busy || view?.running;
  const followUp = view?.status === "needs_info" && !view?.running;

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

      <div className="who">
        <label htmlFor="merchant">Merchant</label>
        <select id="merchant" value={mid} onChange={(e) => { setMid(e.target.value); setPin(demoPin(e.target.value)); }}>
          {merchants.map((m) => (
            <option key={m.mid} value={m.mid}>{m.mid} · {m.name}{m.language === "ta-IN" ? " (Tamil)" : ""}</option>
          ))}
        </select>
        <label htmlFor="pin">PIN (last 4 of phone)</label>
        <input id="pin" value={pin} maxLength={4} inputMode="numeric" onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))} />
      </div>

      <div className="phone">
        <div className="phone-top">
          <span className="avatar">{merchant?.name?.[0] || "?"}</span>
          <div>
            <b>Payments Help</b>
            <small>{merchant ? `${merchant.name}, ${merchant.city}` : ""}</small>
          </div>
        </div>

        <div className="messages">
          {!messages.length && !pending && (
            <div className="empty">Type a problem, tap a demo prompt, or use the mic. The agent will investigate and fix it.</div>
          )}
          {messages.map((m, i) => (
            <Bubble key={i} m={m} voice={view?.voice && i === 0} citation={i === messages.length - 1 && m.role === "agent" ? view?.citation : null} />
          ))}
          {pending && !messages.length && <Bubble m={{ role: "merchant", content: pending.text }} voice={pending.voice} />}
          {running && <div className="typing"><span /><span /><span /> agent is working</div>}
          {view?.status === "waiting_approval" && !running && <div className="sys-note">⏳ Waiting for the operations team to approve</div>}
          {view?.status === "waiting_customer" && !running && <div className="sys-note">⏳ Waiting for the customer to answer</div>}
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

function Bubble({ m, voice, citation }) {
  const cls = m.role === "agent" ? "bubble agent" : m.role === "system" ? "bubble system" : "bubble merchant";
  return (
    <div className={cls}>
      {m.role === "system" && <small className="bubble-tag">system event</small>}
      {voice && m.role === "merchant" && <small className="bubble-tag">🎤 voice · transcribed</small>}
      <div>{m.content}</div>
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
