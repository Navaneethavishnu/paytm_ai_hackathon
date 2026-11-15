import { useEffect, useRef } from "react";
import { formatEvent } from "../events.js";

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

export default function Timeline({ caseId, view, events }) {
  const bottom = useRef(null);
  const rows = events.map((e) => ({ e, r: formatEvent(e) })).filter((x) => x.r);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [rows.length]);

  const [label, tone] = view?.running ? ["Working", "running"] : STATUS[view?.status] || ["", ""];

  return (
    <section className="panel timeline-panel" aria-label="Agent timeline">
      <div className="panel-head">
        <h2>Agent timeline</h2>
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
        </div>
      ) : null}

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
    </section>
  );
}
