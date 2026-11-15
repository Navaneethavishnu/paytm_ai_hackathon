const LLM_LABEL = {
  ChatSarvam: "Sarvam live",
  CachingLLM: "Sarvam · demo cache",
  OfflineLLM: "Offline (no AI)",
};

export default function TopBar({ stats, llm, onProactive, onDouble, onReset, busy }) {
  const s = stats || {};
  return (
    <header className="topbar">
      <div className="brand">
        <span className="logo" aria-hidden="true">◆</span>
        <div>
          <h1>Merchant Success AI</h1>
          <p>AI teammate that closes payment cases · <b>synthetic data</b></p>
        </div>
      </div>

      <div className="stats" aria-label="Demo session stats">
        <span className="stats-label">demo session</span>
        <Stat n={s.cases} label="cases" />
        <Stat n={s.auto_resolved} label="auto-resolved" tone="auto" />
        <Stat n={s.approved} label="approved" tone="approval" />
        <Stat n={s.waiting} label="waiting" tone="approval" />
        <Stat n={s.escalated} label="escalated" tone="escalate" />
      </div>

      <div className="actions">
        <span className={`llm-pill ${llm === "OfflineLLM" ? "warn" : ""}`}>{LLM_LABEL[llm] || "connecting…"}</span>
        <button className="btn ghost" onClick={onProactive} disabled={busy} title="Simulate the payout system reporting PO-1001 failed">
          ⚡ Payout failure
        </button>
        <button className="btn ghost" onClick={onDouble} disabled={busy} title="Simulate a customer paying the same ₹650 bill twice">
          ⚡ Double payment
        </button>
        <button className="btn ghost danger" onClick={onReset} disabled={busy}>
          ↺ Reset
        </button>
      </div>
    </header>
  );
}

function Stat({ n, label, tone }) {
  return (
    <span className={`stat ${tone || ""}`}>
      <b>{n ?? 0}</b> {label}
    </span>
  );
}
