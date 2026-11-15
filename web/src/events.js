// Turns raw audit events into human timeline rows: { title, detail, tone, badge, rule }.
// tone: ai | tool | code | auto | approval | escalate | guard | ok | muted
// Returns null for events that would only duplicate another row.

const inr = (n) => {
  const x = Number(n);
  if (!Number.isFinite(x)) return n;
  return "₹" + x.toLocaleString("en-IN", { maximumFractionDigits: 2 });
};

const SIGNALS = {
  ownership_mismatch: ["Order is not on this merchant's account", "escalate"],
  identity_unverified: ["Identity could not be verified", "escalate"],
  risk_flag: ["Account has an open risk flag", "escalate"],
  repeated_tool_failure: ["A system failed 3 times", "escalate"],
  conflicting_records: ["Systems disagree", "escalate"],
  needs_human: ["No safe diagnosis; needs a human", "escalate"],
  duplicate_verified: ["Duplicate confirmed by code check", "ok"],
};

const TIER_TONE = { auto: "auto", approval: "approval", escalate: "escalate" };

// Node events that are already covered by a more specific event.
const HIDDEN_NODES = new Set([
  "verify_merchant", "policy_gate", "execute", "verify_outcome", "respond",
  "escalate", "prepare_approval", "approval_rejected", "ask_customer", "notify_parties",
]);

function toolRow(name, d) {
  const r = d.result || {};
  switch (name) {
    case "verify_merchant":
      if (d.skipped) return { title: "Identity check skipped", detail: "System-initiated case (proactive)", tone: "code" };
      return r.verified
        ? { title: "Merchant verified", detail: `${d.args?.mid} · PIN ****`, tone: "ok", badge: "CODE" }
        : { title: "Merchant NOT verified", detail: r.locked ? "Locked after too many wrong PINs" : "Wrong PIN", tone: "escalate", badge: "CODE" };
    case "get_merchant":
      return null;
    case "speech_to_text":
      return { title: "Voice transcribed (Sarvam Saaras v4)", detail: `“${d.normalized}”${d.language ? ` · ${d.language}` : ""}`, tone: "ai", badge: "AI" };
    case "get_payment_status": {
      const b = r.body || {};
      const st = b.resultInfo?.resultStatus;
      if (st === "OWNERSHIP_MISMATCH") return { title: `Payments: ${d.args?.order_id}`, detail: "Not on this merchant's account. No details returned", tone: "escalate" };
      return { title: `Payments: ${d.args?.order_id}`, detail: `${st}${b.txnAmount ? ` · ${inr(b.txnAmount)}` : ""}${b.paymentMode ? ` · ${b.paymentMode}` : ""}`, tone: "tool" };
    }
    case "get_settlement_for_txn": {
      if (!r.found) return { title: `Settlement: ${d.args?.txn_id}`, detail: "No payout found", tone: "tool" };
      const p = r.payout;
      return { title: `Settlement: payout ${p.payoutId}`, detail: `${p.status}${p.failureReason ? ` · ${p.failureReason}` : ""}${p.utr ? ` · ${p.utr}` : ""}`, tone: p.status === "FAILED" ? "approval" : "tool" };
    }
    case "find_duplicate_payments": {
      const dups = r.duplicates || [];
      return { title: "Duplicate check", detail: dups.length ? `Found ${dups.map((x) => x.orderId).join(", ")} (same customer, amount, invoice)` : "No duplicates", tone: dups.length ? "approval" : "tool" };
    }
    case "get_risk_flags":
      return { title: "Risk flags", detail: (r.flags || []).length ? r.flags.join(", ") : "None", tone: (r.flags || []).length ? "escalate" : "tool" };
    case "get_payout_status": {
      if (!r.found) return { title: `Payout ${d.args?.payout_id}`, detail: r.reason === "OWNERSHIP_MISMATCH" ? "Not this merchant's payout. Nothing revealed" : "Not found", tone: "escalate" };
      return { title: `Payout ${r.payout.payoutId}`, detail: r.payout.status, tone: "tool" };
    }
    case "get_refund_status":
      return { title: "Refund status", detail: r.body?.resultInfo?.resultStatus, tone: "tool" };
    default:
      return { title: name, detail: "", tone: "tool" };
  }
}

export function formatEvent(e) {
  const d = e.detail || {};
  switch (e.kind) {
    case "node":
      switch (e.name) {
        case "start":
          return d.source === "system"
            ? { title: "Case opened by a system event (nobody complained)", detail: d.message, tone: "approval", badge: "PROACTIVE" }
            : { title: "Merchant message received", detail: `${d.mid}: “${d.message}”`, tone: "muted" };
        case "message":
          return { title: "Follow-up message", detail: `“${d.message}”`, tone: "muted" };
        case "intake":
          return { title: "Understood the request", detail: [d.intent?.replace("_", " "), d.order_id || "no order ID yet", d.language].filter(Boolean).join(" · "), tone: "ai", badge: "AI" };
        case "investigate":
          return { title: "Investigation complete", detail: `AI chose ${d.llm_tool_calls ?? 0} read-only lookups (max 5); code added any missing evidence`, tone: "ai", badge: "AI" };
        case "diagnose": {
          const g = d.diagnosis || {};
          return { title: `Diagnosis: ${g.code}`, detail: g.summary, tone: "code", badge: "CODE" };
        }
        case "propose_action": {
          const a = d.proposed_action;
          if (!a) return { title: "No action needed", detail: "Explain to the merchant only", tone: "code", badge: "CODE" };
          if (a.type === "create_ticket") return { title: "Proposed: hand to a specialist", detail: "", tone: "code", badge: "CODE" };
          const what = a.type === "retry_payout" ? `Retry payout ${a.params?.payout_id}` : `Refund ${a.params?.order_id}`;
          return { title: `Proposed: ${what}`, detail: `${inr(a.amount)}${a.prior_retries ? ` · prior retries ${a.prior_retries}` : ""}`, tone: "code", badge: "CODE" };
        }
        case "reply": {
          const how = d.source === "llm" ? "AI-phrased from verified facts" : "safe template";
          return { title: "Reply sent to merchant", detail: `“${d.text}”`, tone: d.source === "llm" ? "ai" : "code", badge: d.source === "llm" ? "AI" : "TEMPLATE", sub: how, citation: d.citation };
        }
        default:
          return HIDDEN_NODES.has(e.name) ? null : { title: e.name, detail: "", tone: "muted" };
      }
    case "tool":
      return toolRow(e.name, d);
    case "signal": {
      const [label, tone] = SIGNALS[e.name] || [e.name, "approval"];
      return { title: `Signal: ${e.name}`, detail: label, tone };
    }
    case "policy":
      return { title: `Policy ${e.name} → ${String(d.tier).toUpperCase()}`, detail: d.reason, tone: TIER_TONE[d.tier] || "code", rule: e.name, badge: "POLICY" };
    case "approval":
      switch (e.name) {
        case "requested":
          return { title: "Paused for Ops approval", detail: `${d.action?.type} ${inr(d.action?.amount)} · evidence hash ${d.hash}`, tone: "approval", rule: d.rule };
        case "approve":
          return { title: `Approved by ${d.reviewer}`, detail: `hash ${d.evidence_hash} matched`, tone: "auto" };
        case "reject":
          return { title: `Rejected by ${d.reviewer}`, detail: "No money moved", tone: "escalate" };
        case "invalid":
          return { title: "Approval refused", detail: d.why, tone: "guard", badge: "GUARDRAIL" };
        case "refused_attempt":
          return { title: "Approval attempt refused", detail: d.why, tone: "guard", badge: "GUARDRAIL" };
        default:
          return { title: `Approval: ${e.name}`, detail: "", tone: "approval" };
      }
    case "action": {
      const r = d.result || {};
      if (e.name === "retry_payout")
        return { title: `Executed: retry payout ${d.args?.payout_id}`, detail: `${r.accepted ? "accepted" : "NOT accepted"} · idempotency key …${String(d.args?.idempotency_key).slice(-22)}`, tone: r.accepted ? "auto" : "escalate" };
      if (e.name === "initiate_refund")
        return { title: `Executed: refund ${d.args?.order_id} ${inr(d.args?.amount)}`, detail: r.body?.refundId ? `refund ${r.body.refundId} · ref …${String(d.args?.ref_id).slice(-20)}` : r.body?.resultInfo?.resultMsg, tone: r.body?.refundId ? "auto" : "escalate" };
      return { title: `Executed: ${e.name}`, detail: "", tone: "auto" };
    }
    case "verify": {
      const r = d.result || {};
      if (e.name === "get_payout_status") {
        const p = r.payout || {};
        return { title: "Verified by re-reading payouts", detail: `${p.status}${p.utr ? ` · ${p.utr}` : ""}`, tone: p.status === "SUCCESS" ? "ok" : "approval", badge: "VERIFY" };
      }
      const s = r.body?.resultInfo?.resultStatus;
      return { title: "Verified by re-reading refunds", detail: `${s}${r.body?.refundId ? ` · ${r.body.refundId}` : ""}`, tone: s === "TXN_SUCCESS" ? "ok" : "approval", badge: "VERIFY" };
    }
    case "escalate":
      return { title: `Escalated: ticket ${d.ticket?.ticketId || "(ticket system down)"}`, detail: d.reason || "", tone: "escalate" };
    case "customer":
      switch (e.name) {
        case "asked":
          return { title: "Asked the customer: keep both or refund one?", detail: `to ${d.to} · “${d.question}”`, tone: "approval", badge: "CONSENT" };
        case "keep":
          return { title: "Customer chose: keep both", detail: "No money moves", tone: "auto", badge: "CUSTOMER" };
        case "refund":
          return { title: "Customer chose: refund one", detail: `consent bound to hash ${d.evidence_hash}. Now the policy decides`, tone: "auto", badge: "CUSTOMER" };
        case "no_response":
          return { title: "Customer did not reply", detail: "Both payments kept. Silence never moves money", tone: "code" };
        case "invalid":
        case "refused_attempt":
          return { title: "Guardrail: customer decision refused", detail: d.why, tone: "guard", badge: "GUARDRAIL" };
        default:
          return { title: `Customer: ${e.name}`, detail: "", tone: "approval" };
      }
    case "notice":
      return { title: `Notified the ${e.name}`, detail: `“${d.text}”`, tone: "ok", badge: e.name === "customer" ? "→ CUSTOMER" : "→ MERCHANT" };
    case "error": {
      if (e.name === "reply_validator") return { title: "Guardrail: AI reply rejected", detail: `${d.rejected} → safe template sent instead`, tone: "guard", badge: "GUARDRAIL" };
      if (d.ignored_args) return { title: "Guardrail: model tried to pass " + d.ignored_args.join(", "), detail: "Ignored. Merchant comes from the verified session", tone: "guard", badge: "GUARDRAIL" };
      if (d.rejected) return { title: `Guardrail: blocked ${e.name}`, detail: d.rejected, tone: "guard", badge: "GUARDRAIL" };
      if (d.attempt) return { title: `System error: ${e.name}`, detail: `attempt ${d.attempt} failed, retrying`, tone: "approval" };
      if (d.skipped) return { title: `Skipped ${e.name}`, detail: "systems are down", tone: "muted" };
      return { title: `Error: ${e.name}`, detail: d.error || "", tone: "approval" };
    }
    default:
      return { title: `${e.kind}: ${e.name}`, detail: "", tone: "muted" };
  }
}

export { inr };
