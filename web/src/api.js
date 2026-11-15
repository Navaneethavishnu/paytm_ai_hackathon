// Thin wrapper over the FastAPI backend. Every call goes to /api/* (Vite proxies it).
const BASE = import.meta.env.VITE_API_BASE || "/api";

function detailText(detail) {
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
  return JSON.stringify(detail);
}

async function req(path, { method = "GET", body, headers = {}, raw = false } = {}) {
  const opts = { method, headers: { ...headers } };
  if (body !== undefined) {
    if (raw) opts.body = body;
    else {
      opts.body = JSON.stringify(body);
      opts.headers["Content-Type"] = "application/json";
    }
  }
  let r;
  try {
    r = await fetch(BASE + path, opts);
  } catch {
    throw new Error("Can't reach the backend. Is uvicorn running on port 8000?");
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const e = new Error(detailText(data.detail) || `Request failed (${r.status})`);
    e.status = r.status;
    throw e;
  }
  return data;
}

const ops = (token) => ({ "X-Ops-Token": token });
const audioType = (blob) => (blob.type || "audio/webm").split(";")[0];

export const api = {
  health: () => req("/health"),
  merchants: () => req("/demo/merchants"),
  stats: () => req("/stats"),

  createCase: (mid, pin, text) => req("/cases", { method: "POST", body: { mid, phone_last4: pin, text } }),
  sendMessage: (id, text) => req(`/cases/${id}/messages`, { method: "POST", body: { text } }),
  voiceCase: (mid, pin, blob) =>
    req("/cases/voice", {
      method: "POST", raw: true, body: blob,
      headers: { "Content-Type": audioType(blob), "X-Mid": mid, "X-Phone-Last4": pin },
    }),
  voiceMessage: (id, blob) =>
    req(`/cases/${id}/voice`, { method: "POST", raw: true, body: blob, headers: { "Content-Type": audioType(blob) } }),

  getCase: (id) => req(`/cases/${id}`),
  events: (id, after) => req(`/cases/${id}/events?after=${after}`),

  approvals: (token) => req("/approvals", { headers: ops(token) }),
  decide: (token, id, decision, reviewer, hash) =>
    req(`/approvals/${id}`, {
      method: "POST", headers: ops(token),
      body: { decision, reviewer, evidence_hash: hash },
    }),
  reset: (token) => req("/demo/reset", { method: "POST", headers: ops(token) }),
  payoutFailed: (token, payoutId) =>
    req("/events/payout-failed", { method: "POST", headers: ops(token), body: { payout_id: payoutId } }),

  // Case 4: proactive duplicate payment, the customer decides
  duplicatePayment: (token, orderId) =>
    req("/events/duplicate-payment", { method: "POST", headers: ops(token), body: { order_id: orderId } }),
  customerInbox: (vpa) => req(`/customer/inbox?vpa=${encodeURIComponent(vpa)}`),
  customerDecide: (id, decision, token, hash) =>
    req(`/customer/decisions/${id}`, { method: "POST", body: { decision, token, evidence_hash: hash } }),
  customerNoReply: (opsToken, id) => req(`/cases/${id}/customer-no-reply`, { method: "POST", headers: ops(opsToken) }),
};
