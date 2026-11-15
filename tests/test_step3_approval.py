"""Step 3: human approval with interrupt() + SQLite checkpointer."""
import json

import pytest

from app import audit
from app import mock_systems as ms
from app.agent import graph
from app.agent.graph import ApprovalError, decide, get_case, run_case
from app.config import get_settings
from app.db import init_engine, session_scope
from app.llm import OfflineLLM
from app.models import Payout, Refund
from app.seed import reset_and_seed

OFF = OfflineLLM()
CASE2 = ("Customer says they were charged twice for ORD-2001, ₹12,000.", "M1002", "0002")


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    init_engine(f"sqlite:///{tmp_path}/test.db")
    reset_and_seed()
    monkeypatch.setattr(get_settings(), "tool_retry_backoff", 0.0)
    yield
    ms.reset_runtime_state()


def _refunds():
    with session_scope() as s:
        return [(r.order_id, r.amount, r.status) for r in s.query(Refund)]


def _pause_case2():
    s = run_case(*CASE2, llm=OFF)
    assert s["status"] == "waiting_approval"
    return s


def _decide(s, decision="approve", reviewer="priya", h=None):
    return decide(s["case_id"], decision, reviewer, h or s["approval_request"]["hash"], llm=OFF)


# ---------- pause ----------
def test_case2_pauses_with_evidence_pack_and_no_refund():
    s = _pause_case2()
    pack = s["approval_request"]["pack"]
    assert pack["rule_id"] == "R-22"
    assert pack["action"] == {"type": "refund_duplicate", "amount": 12000.0,
                              "params": {"order_id": "ORD-2002", "txn_id": "TXN2002"}}
    assert sorted(t["orderId"] for t in pack["transactions"]) == ["ORD-2001", "ORD-2002"]
    assert "suresh@okhdfc" not in json.dumps(pack)                      # PII masked in the pack
    assert "approval" in s["reply"] and "ORD-2002" in s["reply"]
    assert _refunds() == []


def test_small_duplicate_does_not_pause():
    s = run_case("ORD-2003 charged twice", "M1002", "0002", llm=OFF)
    assert s["status"] == "resolved" and not s.get("approval_request")


# ---------- approve / reject ----------
def test_approve_executes_and_verifies_refund():
    s = _decide(_pause_case2())
    assert s["status"] == "resolved" and s["approval"]["reviewer"] == "priya"
    assert s["verification"]["status"] == "TXN_SUCCESS"
    assert s["verification"]["refund_id"] in s["reply"]
    assert _refunds() == [("ORD-2002", 12000.0, "TXN_SUCCESS")]
    names = [(e["kind"], e["name"]) for e in audit.events(s["case_id"])]
    assert ("approval", "requested") in names and ("approval", "approve") in names
    assert names.index(("approval", "approve")) < names.index(("action", "initiate_refund"))


def test_reject_opens_ticket_and_explains():
    s = _decide(_pause_case2(), "reject")
    assert s["status"] == "resolved" and s["approval"]["decision"] == "reject"
    assert s["ticket_id"] and s["ticket_id"] in s["reply"] and "did not approve" in s["reply"]
    assert _refunds() == []
    assert ms.get_ticket("M1002", s["ticket_id"])["found"]


def test_resume_survives_restart():
    s = _pause_case2()
    graph._SAVERS.clear()                       # simulate a new process: no in-memory state
    again = get_case(s["case_id"])
    assert again["status"] == "waiting_approval"
    s2 = _decide(again)
    assert s2["status"] == "resolved" and _refunds() == [("ORD-2002", 12000.0, "TXN_SUCCESS")]


# ---------- approval guardrails ----------
def test_wrong_hash_is_refused_and_case_stays_paused():
    s = _pause_case2()
    with pytest.raises(ApprovalError, match="hash"):
        _decide(s, h="0000000000000000")
    assert get_case(s["case_id"])["status"] == "waiting_approval" and _refunds() == []
    assert any(e["name"] == "refused_attempt" for e in audit.events(s["case_id"]))
    assert _decide(s)["status"] == "resolved"   # the correct decision still works


@pytest.mark.parametrize("decision,reviewer", [("approve", ""), ("approve", "   "), ("yes", "priya"), ("approve", "x" * 65)])
def test_bad_decision_or_reviewer_refused(decision, reviewer):
    s = _pause_case2()
    with pytest.raises(ApprovalError):
        _decide(s, decision, reviewer)
    assert _refunds() == []


def test_double_approve_cannot_refund_twice():
    s = _pause_case2()
    _decide(s)
    with pytest.raises(ApprovalError, match="not waiting"):
        _decide(s)
    assert len(_refunds()) == 1


def test_decide_on_case_that_never_paused():
    s = run_case("Where is my money for ORD-1002?", "M1001", "0001", llm=OFF)
    with pytest.raises(ApprovalError, match="not waiting"):
        decide(s["case_id"], "approve", "priya", "whatever", llm=OFF)


def test_state_tampered_after_pack_shown_escalates_without_refund():
    s = _pause_case2()
    g = graph.build_graph(OFF, checkpointer=graph.get_checkpointer())
    cfg = {"configurable": {"thread_id": s["case_id"]}}
    bigger = {**s["proposed_action"], "amount": 99999.0}
    g.update_state(cfg, {"proposed_action": bigger})
    out = _decide(s)                            # Ops approves the pack they saw...
    assert out["status"] == "escalated"         # ...but the action changed underneath: refuse
    assert out["approval"]["decision"] == "invalid" and _refunds() == []


# ---------- generic approval (second payout retry, R-08) ----------
def test_second_payout_retry_needs_approval_then_succeeds():
    with session_scope() as db:
        db.get(Payout, "PO-1001").retry_count = 1
    s = run_case("ORD-1001 money not received", "M1001", "0001", llm=OFF)
    assert s["status"] == "waiting_approval" and s["approval_request"]["pack"]["rule_id"] == "R-08"
    assert "approval" in s["reply"]
    s2 = _decide(s)
    assert s2["status"] == "resolved" and s2["verification"]["utr"] in s2["reply"]
