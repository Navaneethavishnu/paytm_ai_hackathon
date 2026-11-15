"""The LangGraph state machine.

intake -> verify_merchant -> investigate -> diagnose -> propose_action -> policy_gate
   policy_gate: auto     -> execute -> verify_outcome -> respond
                approval -> prepare_approval -> human_approval (PAUSE via interrupt)
                               resume approve -> execute -> verify_outcome -> respond
                               resume reject  -> approval_rejected (ticket) -> respond
                               invalid        -> escalate
                escalate -> escalate
   verify fails  -> propose_action (guard G-02 escalates; no data tools are called)
   no order ID   -> verify_merchant -> suggest_orders (recent payments to tap) -> respond (asks for it)
   info-only diagnosis (settled, pending, failed, not found) -> respond, no action

Every case runs on thread_id = case_id with a SQLite checkpointer, so a case paused
for approval survives a server restart and can be resumed from another process.
"""
import sqlite3
import uuid
from functools import partial
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app import audit
from app.agent import nodes
from app.agent.state import CaseState
from app.config import get_settings
from app.llm import get_llm


class ApprovalError(Exception):
    """Decision refused before resuming; the case stays paused."""


# ---------------- checkpointer ----------------
_SAVERS: dict[str, SqliteSaver] = {}


def get_checkpointer() -> SqliteSaver:
    path = get_settings().checkpoint_db
    if path not in _SAVERS:
        _SAVERS[path] = SqliteSaver(sqlite3.connect(path, check_same_thread=False))
    return _SAVERS[path]


def reset_checkpoints():
    """Drop every saved case (used by demo reset)."""
    path = get_settings().checkpoint_db
    saver = _SAVERS.pop(path, None)
    if saver:
        saver.conn.close()
    Path(path).unlink(missing_ok=True)


# ---------------- graph ----------------
def _audited(name, fn):
    keys = ("status", "diagnosis", "proposed_action", "policy_decision", "action_result",
            "verification", "signals", "order_id", "language", "intent", "merchant_verified",
            "llm_tool_calls", "approval")

    def run(state):
        out = fn(state)
        audit.log(state["case_id"], "node", name, {k: out[k] for k in keys if k in out})
        return out
    run.__name__ = name
    return run


def _after_intake(s):
    # Always verify first, even without an order ID: we may show the merchant their recent payments.
    return "verify_merchant"


def _after_verify(s):
    if not s.get("merchant_verified"):
        return "propose_action"          # G-02 escalates; no data tools are called
    return "suggest_orders" if s.get("status") == "needs_info" else "investigate"


def _dup(s) -> bool:
    return s.get("trigger") == "duplicate_payment"


def _after_propose(s):
    a = s.get("proposed_action")
    if not a:
        return "respond"
    if _dup(s) and a["type"] == "refund_duplicate" and not s.get("customer_decision"):
        return "ask_customer"          # Case 4: never refund without the payer's consent
    return "policy_gate"


def _after_customer(s):
    return "policy_gate" if s["customer_decision"]["decision"] == "refund" else "notify_parties"


def _after_rejected(s):
    return "notify_parties" if _dup(s) else "respond"


def _after_policy(s):
    return {"auto": "execute", "approval": "prepare_approval"}.get(s["policy_decision"]["tier"], "escalate")


def _after_approval(s):
    return {"approve": "execute", "reject": "approval_rejected"}.get(s["approval"]["decision"], "escalate")


def _after_execute(s):
    return "verify_outcome" if s["action_result"]["ok"] else "escalate"


def _after_verify_outcome(s):
    if not s["verification"]["ok"]:
        return "escalate"
    return "notify_parties" if _dup(s) else "respond"


def build_graph(llm=None, checkpointer=None, reply_llm=None):
    if llm is None:
        llm, reply_llm = get_llm(), reply_llm or get_llm(purpose="reply")
    reply_llm = reply_llm or llm
    g = StateGraph(CaseState)
    g.add_node("intake", _audited("intake", partial(nodes.intake, llm=llm)))
    g.add_node("verify_merchant", _audited("verify_merchant", nodes.verify_merchant))
    g.add_node("suggest_orders", _audited("suggest_orders", nodes.suggest_orders))
    g.add_node("investigate", _audited("investigate", partial(nodes.investigate, llm=llm)))
    g.add_node("diagnose", _audited("diagnose", nodes.diagnose))
    g.add_node("propose_action", _audited("propose_action", nodes.propose_action))
    g.add_node("policy_gate", _audited("policy_gate", nodes.policy_gate))
    g.add_node("prepare_approval", _audited("prepare_approval", nodes.prepare_approval))
    # not wrapped in _audited: interrupt() re-runs the node on resume; it logs its own events.
    g.add_node("human_approval", nodes.human_approval)
    g.add_node("approval_rejected", _audited("approval_rejected", nodes.approval_rejected))
    g.add_node("ask_customer", _audited("ask_customer", nodes.ask_customer))
    g.add_node("customer_decision", nodes.customer_decision)      # interrupt(): logs its own events
    g.add_node("notify_parties", _audited("notify_parties", nodes.notify_parties))
    g.add_node("execute", _audited("execute", nodes.execute))
    g.add_node("verify_outcome", _audited("verify_outcome", nodes.verify_outcome))
    g.add_node("respond", _audited("respond", partial(nodes.respond, llm=reply_llm)))
    g.add_node("escalate", _audited("escalate", nodes.escalate))

    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", _after_intake, ["verify_merchant"])
    g.add_conditional_edges("verify_merchant", _after_verify, ["investigate", "propose_action", "suggest_orders"])
    g.add_edge("suggest_orders", "respond")
    g.add_edge("investigate", "diagnose")
    g.add_edge("diagnose", "propose_action")
    g.add_conditional_edges("propose_action", _after_propose, ["policy_gate", "respond", "ask_customer"])
    g.add_edge("ask_customer", "customer_decision")
    g.add_conditional_edges("customer_decision", _after_customer, ["policy_gate", "notify_parties"])
    g.add_conditional_edges("policy_gate", _after_policy, ["execute", "prepare_approval", "escalate"])
    g.add_edge("prepare_approval", "human_approval")
    g.add_conditional_edges("human_approval", _after_approval, ["execute", "approval_rejected", "escalate"])
    g.add_conditional_edges("approval_rejected", _after_rejected, ["respond", "notify_parties"])
    g.add_conditional_edges("execute", _after_execute, ["verify_outcome", "escalate"])
    g.add_conditional_edges("verify_outcome", _after_verify_outcome, ["respond", "escalate", "notify_parties"])
    g.add_edge("respond", END)
    g.add_edge("escalate", END)
    g.add_edge("notify_parties", END)
    return g.compile(checkpointer=checkpointer)


def _cfg(case_id: str) -> dict:
    return {"configurable": {"thread_id": case_id}}


# ---------------- public API (CLI now, FastAPI in Step 4) ----------------
def new_case_id() -> str:
    return "CASE-" + uuid.uuid4().hex[:8].upper()


def run_case(text: str, mid: str, phone_last4: str = "", *, llm=None, reply_llm=None,
             case_id: str | None = None, source: str = "merchant", language: str | None = None,
             trigger: str | None = None) -> dict:
    """source='system' is ONLY for token-authenticated internal events (proactive mode).
    trigger: 'payout_failed' | 'duplicate_payment' (Case 4: customer decides keep/refund)."""
    case_id = case_id or new_case_id()
    graph = build_graph(llm, reply_llm=reply_llm, checkpointer=get_checkpointer())
    if graph.get_state(_cfg(case_id)).values:
        raise ValueError(f"{case_id} already exists")
    audit.log(case_id, "node", "start", {"mid": mid, "message": text, "source": source})
    init = {"case_id": case_id, "mid": mid, "phone_last4": phone_last4, "status": "open", "source": source,
            "messages": [{"role": "system" if source == "system" else "merchant", "content": text}]}
    if language:
        init["language"] = language
    if trigger:
        init["trigger"] = trigger
    graph.invoke(init, _cfg(case_id))
    return graph.get_state(_cfg(case_id)).values


class CaseStateError(Exception):
    """Message not accepted in the case's current state."""


def continue_case(case_id: str, text: str, *, llm=None, reply_llm=None) -> dict:
    """Follow-up merchant message. Only a case that asked for more info (needs_info) re-runs;
    the merchant cannot steer a case that is paused, resolved or escalated."""
    graph = build_graph(llm, reply_llm=reply_llm, checkpointer=get_checkpointer())
    s = graph.get_state(_cfg(case_id)).values
    if not s:
        raise KeyError(case_id)
    if s.get("status") != "needs_info":
        raise CaseStateError(f"case is {s.get('status')}; start a new case for a new issue")
    audit.log(case_id, "node", "message", {"message": text})
    graph.invoke({"messages": s["messages"] + [{"role": "merchant", "content": text}], "status": "open"},
                 _cfg(case_id))
    return graph.get_state(_cfg(case_id)).values


def get_case(case_id: str) -> dict:
    """Current saved state of a case ({} if unknown). No LLM needed."""
    from app.llm import OfflineLLM
    return build_graph(OfflineLLM(), checkpointer=get_checkpointer()).get_state(_cfg(case_id)).values


def decide(case_id: str, decision: str, reviewer: str, evidence_hash: str, *,
           llm=None, reply_llm=None) -> dict:
    """Ops approves/rejects a paused case. Validated BEFORE resuming, so a bad attempt
    (wrong hash, no reviewer, case not paused) leaves the case paused and logs the attempt."""
    graph = build_graph(llm, reply_llm=reply_llm, checkpointer=get_checkpointer())
    snap = graph.get_state(_cfg(case_id))
    if "human_approval" not in (snap.next or ()):
        raise ApprovalError(f"{case_id} is not waiting for approval")
    payload = {"decision": decision, "reviewer": reviewer, "evidence_hash": evidence_hash}
    ok, why = nodes.validate_approval(payload, snap.values["approval_request"]["hash"])
    if not ok:
        audit.log(case_id, "approval", "refused_attempt", {"why": why, "reviewer": reviewer})
        raise ApprovalError(why)
    graph.invoke(Command(resume=payload), _cfg(case_id))
    return graph.get_state(_cfg(case_id)).values


def customer_decide(case_id: str, decision: str, evidence_hash: str, *, token: str | None = None,
                    by_ops: bool = False, llm=None, reply_llm=None) -> dict:
    """Case 4: the payer answers keep/refund (with their one-time token), or Ops records 'no_response'.
    Validated BEFORE resuming, so a bad attempt leaves the question open."""
    graph = build_graph(llm, reply_llm=reply_llm, checkpointer=get_checkpointer())
    snap = graph.get_state(_cfg(case_id))
    if "customer_decision" not in (snap.next or ()):
        raise ApprovalError(f"{case_id} is not waiting for the customer")
    payload = {"decision": decision, "evidence_hash": evidence_hash, "token": token}
    if by_ops:
        payload["by"] = "ops"
    ok, why = nodes.validate_customer(payload, snap.values["customer_ask"])
    if not ok:
        audit.log(case_id, "customer", "refused_attempt", {"why": why})
        raise ApprovalError(why)
    graph.invoke(Command(resume=payload), _cfg(case_id))
    return graph.get_state(_cfg(case_id)).values
