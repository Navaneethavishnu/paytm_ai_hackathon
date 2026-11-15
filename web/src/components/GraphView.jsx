import { useState } from "react";
import { formatEvent, inr } from "../events.js";

// The LangGraph state machine from app/agent/graph.py, drawn on a fixed 1000 x 960 canvas.
// Node centres are hand-placed so the 17 nodes read top to bottom like the real flow.
const W = 200, H = 66, VW = 1000, VH = 960;

const NODES = {
  intake:            { x: 130, y: 50,  label: "Understand",      kind: "ai" },
  verify_merchant:   { x: 130, y: 150, label: "Verify merchant", kind: "code" },
  suggest_orders:    { x: 400, y: 150, label: "Suggest orders",  kind: "code" },
  investigate:       { x: 130, y: 250, label: "Investigate",     kind: "ai" },
  diagnose:          { x: 130, y: 350, label: "Diagnose",        kind: "code" },
  propose_action:    { x: 130, y: 450, label: "Propose action",  kind: "code" },
  ask_customer:      { x: 640, y: 450, label: "Ask customer",    kind: "people" },
  customer_decision: { x: 870, y: 450, label: "Customer says", kind: "pause" },
  policy_gate:       { x: 130, y: 570, label: "Policy gate",     kind: "policy" },
  execute:           { x: 130, y: 690, label: "Execute",         kind: "money" },
  prepare_approval:  { x: 400, y: 690, label: "Evidence pack",   kind: "people" },
  escalate:          { x: 870, y: 690, label: "Escalate",        kind: "esc" },
  verify_outcome:    { x: 130, y: 800, label: "Verify result",   kind: "money" },
  human_approval:    { x: 400, y: 800, label: "Ops approval",    kind: "pause" },
  approval_rejected: { x: 640, y: 800, label: "Rejected",        kind: "esc" },
  respond:           { x: 130, y: 910, label: "Reply",           kind: "ai" },
  notify_parties:    { x: 640, y: 910, label: "Notify both",     kind: "people" },
};

// Edges exactly as in graph.py. `d` overrides the automatic curve where a straight line would cross nodes.
const EDGES = [
  ["intake", "verify_merchant"],
  ["verify_merchant", "investigate"],
  ["verify_merchant", "suggest_orders"],
  ["verify_merchant", "propose_action", "M30 160 C 6 170, 6 440, 30 445"],
  ["suggest_orders", "respond", "M400 183 C 400 230, 265 230, 265 290 L 265 860 C 265 905, 245 910, 230 910"],
  ["investigate", "diagnose"],
  ["diagnose", "propose_action"],
  ["propose_action", "policy_gate"],
  ["propose_action", "ask_customer"],
  ["propose_action", "respond", "M30 460 C 4 480, 4 890, 30 900"],
  ["ask_customer", "customer_decision"],
  ["customer_decision", "policy_gate", "M870 483 C 870 560, 420 570, 230 570"],
  ["customer_decision", "notify_parties", "M970 455 C 994 460, 994 500, 994 540 L 994 870 C 994 905, 960 910, 740 910"],
  ["policy_gate", "execute"],
  ["policy_gate", "prepare_approval"],
  ["policy_gate", "escalate", "M230 580 C 600 580, 870 600, 870 657"],
  ["prepare_approval", "human_approval"],
  ["human_approval", "execute", "M300 800 C 262 800, 268 690, 230 690"],
  ["human_approval", "approval_rejected"],
  ["human_approval", "escalate", "M500 785 C 520 745, 540 745, 570 745 L 815 745 C 850 745, 860 738, 860 723"],
  ["approval_rejected", "respond", "M600 833 C 600 875, 320 905, 230 910"],
  ["approval_rejected", "notify_parties"],
  ["execute", "verify_outcome"],
  ["execute", "escalate", "M230 705 C 250 745, 270 745, 300 745 L 815 745 C 850 745, 860 738, 860 723"],
  ["verify_outcome", "respond"],
  ["verify_outcome", "escalate", "M230 818 C 250 855, 270 855, 300 855 L 845 855 C 870 855, 878 840, 878 723"],
  ["verify_outcome", "notify_parties", "M230 822 C 250 855, 270 855, 300 855 L 600 855 C 630 855, 640 862, 640 877"],
];

function autoPath(a, b) {
  const A = NODES[a], B = NODES[b];
  if (Math.abs(A.y - B.y) < 10) {                       // same row: side to side
    const dir = B.x > A.x ? 1 : -1;
    return `M${A.x + dir * W / 2} ${A.y} L${B.x - dir * W / 2} ${B.y}`;
  }
  const y1 = A.y + H / 2, y2 = B.y - H / 2, my = (y1 + y2) / 2;
  return `M${A.x} ${y1} C ${A.x} ${my}, ${B.x} ${my}, ${B.x} ${y2}`;
}

// Which edges get which colour once taken.
function edgeTone(a, b, tier) {
  if (b === "escalate" || b === "approval_rejected") return "escalate";
  if (["prepare_approval", "human_approval"].includes(b) || a === "human_approval") return "approval";
  if (["ask_customer", "customer_decision"].includes(b) || a === "customer_decision") return "approval";
  if (a === "policy_gate" || ["execute", "verify_outcome"].includes(a)) return tier === "escalate" ? "escalate" : "auto";
  return "base";
}

// Replay the audit events into: the path taken, the events per node, and a one-line summary per node.
function trace(events) {
  let seq = [], byNode = {}, buf = [];
  const push = (id, evs) => {
    if (seq[seq.length - 1] !== id) seq.push(id);
    byNode[id] = (byNode[id] || []).concat(evs);
  };
  for (const e of events) {
    if (e.kind === "node" && e.name === "message") {     // follow-up message: the graph runs again
      seq = []; byNode = {}; buf = [e]; continue;
    }
    if (e.kind === "node" && NODES[e.name]) { push(e.name, [...buf, e]); buf = []; }
    else if (e.kind === "approval" && ["approve", "reject", "invalid"].includes(e.name)) { push("human_approval", [...buf, e]); buf = []; }
    else if (e.kind === "customer" && ["keep", "refund", "no_response", "invalid"].includes(e.name)) { push("customer_decision", [...buf, e]); buf = []; }
    else buf.push(e);
  }
  return { seq, byNode, pending: buf };
}

function summary(id, evs = []) {
  const find = (kind, name) => [...evs].reverse().find((e) => e.kind === kind && (!name || e.name === name));
  const node = find("node", id)?.detail || {};
  switch (id) {
    case "intake": return [node.order_id || "no order ID", node.language].filter(Boolean).join(" · ");
    case "verify_merchant": {
      const t = find("tool", "verify_merchant")?.detail || {};
      if (t.skipped) return t.skipped.startsWith("already") ? "already verified" : "system event";
      return t.result?.verified ? "PIN ok" : "NOT verified";
    }
    case "suggest_orders": {
      const n = find("tool", "list_recent_transactions")?.detail?.result?.transactions?.length;
      return n != null ? `${n} recent payments` : "asks for order ID";
    }
    case "investigate": return `${node.llm_tool_calls ?? 0} lookups (max 5)`;
    case "diagnose": return node.diagnosis?.code || "";
    case "propose_action": {
      const a = node.proposed_action;
      if (!a) return "no action needed";
      if (a.type === "create_ticket") return "hand to specialist";
      return `${a.type === "retry_payout" ? "retry payout" : "refund"} ${inr(a.amount)}`;
    }
    case "policy_gate": {
      const p = find("policy");
      return p ? `${p.name} · ${p.detail?.tier}` : "";
    }
    case "execute": {
      const a = find("action")?.detail?.result || {};
      return a.accepted || a.body?.refundId ? "done · idempotency key" : "not accepted";
    }
    case "verify_outcome": {
      const v = find("verify")?.detail?.result || {};
      return v.payout?.status || v.body?.resultInfo?.resultStatus || "re-read";
    }
    case "prepare_approval": {
      const r = find("approval", "requested")?.detail;
      return r ? `hash ${String(r.hash).slice(0, 8)}…` : "";
    }
    case "human_approval": {
      const a = find("approval");
      if (!a) return "";
      if (a.name === "approve") return `approved · ${a.detail?.reviewer}`;
      if (a.name === "reject") return `rejected · ${a.detail?.reviewer}`;
      return "refused";
    }
    case "ask_customer": return "keep both or refund one?";
    case "customer_decision": {
      const c = find("customer");
      return c ? { refund: "refund one", keep: "keep both", no_response: "no reply", invalid: "invalid → keep" }[c.name] || c.name : "";
    }
    case "respond": {
      const r = find("node", "reply")?.detail;
      return r ? (r.source === "llm" ? "AI-phrased, checked" : "safe template") : "";
    }
    case "escalate": {
      const t = find("escalate")?.detail?.ticket?.ticketId;
      return t ? `ticket ${t}` : "ticket raised";
    }
    case "approval_rejected": return "ticket, no money moved";
    case "notify_parties": return "customer + merchant told";
    default: return "";
  }
}

const KIND_TAG = { ai: "AI", pause: "PAUSE", policy: "POLICY", money: "MONEY" };

export default function GraphView({ caseId, view, events, onOpenOps }) {
  const [picked, setPicked] = useState(null);
  const { seq, byNode, pending } = trace(events);
  const tier = byNode.policy_gate && [...byNode.policy_gate].reverse().find((e) => e.kind === "policy")?.detail?.tier;

  const paused = !view?.running && view?.status === "waiting_approval" ? "human_approval"
    : !view?.running && view?.status === "waiting_customer" ? "customer_decision" : null;
  const taken = new Set(seq.slice(1).map((b, i) => `${seq[i]}>${b}`));
  if (paused && seq.length) taken.add(`${seq[seq.length - 1]}>${paused}`);
  const current = paused || seq[seq.length - 1];
  const order = Object.fromEntries(seq.map((id, i) => [id, i + 1]));

  const sel = picked && (byNode[picked] || picked === paused) ? picked : current;
  const selRows = sel ? [...(byNode[sel] || []), ...(sel === current && !paused ? pending : [])]
    .map((e) => ({ e, r: formatEvent(e) })).filter((x) => x.r) : [];

  return (
    <div className="graph-wrap">
      <div className="graph-layout">
      <div className="graph" role="img" aria-label={`Agent state machine. Path taken: ${seq.map((id) => NODES[id].label).join(", ") || "not started"}`}>
        <svg viewBox={`0 0 ${VW} ${VH}`} aria-hidden="true">
          <defs>
            {["base", "auto", "approval", "escalate", "idle"].map((t) => (
              <marker key={t} id={`arrow-${t}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0 0 L10 5 L0 10 z" className={`arrowhead ${t}`} />
              </marker>
            ))}
          </defs>
          {EDGES.map(([a, b, d]) => {
            const on = taken.has(`${a}>${b}`);
            const tone = on ? edgeTone(a, b, tier) : "idle";
            const waiting = on && paused && b === paused;
            return (
              <path key={`${a}>${b}${on}`} d={d || autoPath(a, b)} pathLength="1"
                className={`edge ${tone} ${on ? "taken" : ""} ${waiting ? "waiting" : ""}`}
                markerEnd={`url(#arrow-${tone})`} />
            );
          })}
        </svg>

        {Object.entries(NODES).map(([id, n]) => {
          const visited = id in order;
          const state = id === paused ? "paused" : visited ? "visited" : "idle";
          const sub = id === paused ? (id === "human_approval" ? "waiting · click to review" : "waiting for customer…") : visited ? summary(id, byNode[id]) : "";
          const tone = id === "policy_gate" && tier ? ` tier-${tier}` : "";
          return (
            <button key={id} type="button"
              className={`gnode k-${n.kind} ${state}${tone}${id === current ? " current" : ""}${id === sel && (visited || state === "paused") ? " selected" : ""}`}
              style={{ left: `${((n.x - W / 2) / VW) * 100}%`, top: `${((n.y - H / 2) / VH) * 100}%`, width: `${(W / VW) * 100}%`, height: `${(H / VH) * 100}%` }}
              onClick={() => (id === paused && id === "human_approval" && onOpenOps ? onOpenOps() : setPicked(id))} disabled={!visited && state !== "paused"}
              title={`${n.label} (${id})`}>
              <span className="gnode-top">
                {visited && <span className="gstep">{order[id]}</span>}
                <span className="glabel">{n.label}</span>
                {KIND_TAG[n.kind] && <span className="gtag">{KIND_TAG[n.kind]}</span>}
              </span>
              <span className="gsub">{sub || id}</span>
            </button>
          );
        })}
        {view?.running && <span className="graph-working"><span className="spinner" /> working…</span>}
      </div>

      <div className="graph-detail" aria-live="polite">
        {!caseId ? (
          <p className="graph-hint">Start a case on the left: the path it takes lights up here. <b>Grey</b> steps are branches it did not need.
            <span className="principle">The LLM proposes · the policy engine decides · the verifier confirms</span></p>
        ) : sel ? (
          <>
            <div className="graph-detail-head">
              <b>{NODES[sel]?.label}</b> <code>{sel}</code>
              <span className="graph-hint-inline">click any lit step to see what it did</span>
            </div>
            {selRows.length ? (
              <ul>
                {selRows.map(({ e, r }) => (
                  <li key={e.id} className={`gd-row ${r.tone}`}>
                    <span className="gd-title">{r.title}</span>
                    {r.badge && <span className={`badge ${r.tone}`}>{r.badge}</span>}
                    {r.detail && <div className="gd-detail">{r.detail}</div>}
                  </li>
                ))}
              </ul>
            ) : <p className="graph-hint">{sel === paused ? "Paused here. The case resumes when the decision arrives." : "No details for this step."}</p>}
          </>
        ) : <p className="graph-hint">Starting…</p>}
      </div>
      </div>
    </div>
  );
}
