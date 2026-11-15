import { useEffect, useRef, useState } from "react";
import { formatEvent } from "../events.js";
import GraphView from "./GraphView.jsx";
import OpsPanel from "./OpsPanel.jsx";
import HistoryView from "./HistoryView.jsx";

function savedMode() {
  try { return localStorage.getItem("timelineMode") || "graph"; } catch { return "graph"; }
}

const STATUS = {
  open: ["Working", "running"],
  needs_info: ["Needs info", "approval"],
  waiting_approval: ["Waiting for Ops", "approval"],
  waiting_customer: ["Waiting for customer", "approval"],
  resolved: ["Resolved", "auto"],
  escalated: ["Escalated", "escalate"],
};

// The server stores naive UTC timestamps; show them in the viewer's local time (IST at the venue).
const localTime = (ts) => new Date(ts + "Z").toLocaleTimeString("en-IN", { hour12: false });

export default function Timeline({ caseId, view, events, ops, merchants = [] }) {
  const bottom = useRef(null);
  // graph | cards | ops | history  (?tab=ops or ?tab=history opens that tab directly, handy for screenshots)
  const [mode, setModeState] = useState(() => window.location.search.match(/[?&]tab=(ops|history)\b/)?.[1] || savedMode());
  const [lastView, setLastView] = useState(savedMode); // where to return after an Ops decision
  const [opsCount, setOpsCount] = useState(0);
  const setMode = (m) => {
    setModeState(m);
    if (m === "graph" || m === "cards") { setLastView(m); try { localStorage.setItem("timelineMode", m); } catch { /* private window */ } }
  };
  // After Approve/Reject, jump back to the graph so the audience sees the case finish.
  const onDecided = (id) => { ops.onDecided(id); setMode(lastView); };
  const openFromOps = (id) => { ops.onOpen(id); setMode(lastView); };
  const rows = events.map((e) => ({ e, r: formatEvent(e) })).filter((x) => x.r);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [rows.length, mode]);

  const [label, tone] = view?.running ? ["Working", "running"] : STATUS[view?.status] || ["", ""];

  return (
    <section className="panel timeline-panel" aria-label="Agent timeline">
      <div className="panel-head">
        <h2>Agent timeline</h2>
        <div className="view-switch" role="tablist" aria-label="Timeline view">
          <button role="tab" aria-selected={mode === "graph"} className={mode === "graph" ? "on" : ""} onClick={() => setMode("graph")}>Graph</button>
          <button role="tab" aria-selected={mode === "cards"} className={mode === "cards" ? "on" : ""} onClick={() => setMode("cards")}>Cards</button>
          <button role="tab" aria-selected={mode === "ops"} className={`ops-tab ${mode === "ops" ? "on" : ""} ${opsCount ? "pending" : ""}`} onClick={() => setMode("ops")}>
            Ops approvals <span className="ops-count">{opsCount}</span>
          </button>
          <button role="tab" aria-selected={mode === "history"} className={mode === "history" ? "on" : ""} onClick={() => setMode("history")}>History</button>
        </div>
        <div className="legend">
          <span className="dot auto" /> auto
          <span className="dot approval" /> approval
          <span className="dot escalate" /> escalate
          <span className="dot guard" /> guardrail
          <span className="dot ai" /> AI step
        </div>
      </div>

      {caseId ? (
        <div className="case-strip">
          <code>{caseId}</code>
          {label && <span className={`status-pill ${tone}`}>{label}</span>}
          {view?.diagnosis && <span className="kv">diagnosis <b>{view.diagnosis}</b></span>}
          {view?.policy?.rule_id && <span className={`rule ${view.policy.tier}`}>{view.policy.rule_id} · {view.policy.tier}</span>}
          {view?.ticket_id && <span className="kv">ticket <b>{view.ticket_id}</b></span>}
          {view?.status === "waiting_approval" && !view?.running && mode !== "ops" && (
            <button className="btn tiny review-ops" onClick={() => setMode("ops")}>Review in Ops approvals →</button>
          )}
        </div>
      ) : null}

      <OpsPanel {...ops} onDecided={onDecided} onOpen={openFromOps} onCount={setOpsCount} hidden={mode !== "ops"} />

      <HistoryView token={ops.token} merchants={merchants} currentCase={caseId} onOpen={openFromOps}
        hidden={mode !== "history"} refreshKey={ops.refreshKey} />

      {mode === "ops" || mode === "history" ? null : mode === "graph" ? <GraphView caseId={caseId} view={view} events={events} onOpenOps={() => setMode("ops")} /> : (
      <ol className="events">
        {!caseId && (
          <li className="empty big">
            Start a case on the left to watch the agent work: it understands, verifies, investigates,
            diagnoses, asks the policy engine, acts, and checks its own work.
            <p className="principle">The LLM proposes · the policy engine decides · the verifier confirms</p>
          </li>
        )}
        {rows.map(({ e, r }, i) => (
          <li key={e.id} className={`ev ${r.tone}`} style={{ animationDelay: `${Math.min(i, 3) * 40}ms` }}>
            <span className="rail" aria-hidden="true" />
            <div className="ev-body">
              <div className="ev-title">
                <span>{r.title}</span>
                {r.badge && <span className={`badge ${r.tone}`}>{r.badge}</span>}
              </div>
              {r.detail && <div className="ev-detail">{r.detail}</div>}
              {r.sub && <div className="ev-sub">{r.sub}</div>}
              {r.citation && <div className="ev-sub">cited: {r.citation}</div>}
            </div>
            <time>{localTime(e.ts)}</time>
          </li>
        ))}
        {view?.running && <li className="ev running"><span className="rail" /><div className="ev-body"><div className="ev-title"><span className="spinner" /> working…</div></div></li>}
        <div ref={bottom} />
      </ol>
      )}
    </section>
  );
}
