"""Case 4: proactive duplicate payment. Nobody complains; the system asks the CUSTOMER keep/refund,
and notifies the merchant. Money never moves without the customer's valid consent."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import api, audit
from app import mock_systems as ms
from app.agent.graph import ApprovalError, customer_decide, decide, run_case
from app.config import get_settings
from app.db import init_engine, session_scope
from app.llm import OfflineLLM
from app.models import Refund
from app.seed import reset_and_seed

OFF = OfflineLLM()
OPS = {"X-Ops-Token": "demo-ops-token"}


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    init_engine(f"sqlite:///{tmp_path}/test.db")
    reset_and_seed()
    monkeypatch.setattr(get_settings(), "tool_retry_backoff", 0.0)
    monkeypatch.setattr(get_settings(), "ops_token", "demo-ops-token")
    api.set_llms(OfflineLLM())
    api._HITS.clear()
    yield
    ms.reset_runtime_state()


def _refunds():
    with session_scope() as s:
        return [(r.order_id, r.amount, r.status) for r in s.query(Refund)]


def _start(order="ORD-6002"):
    s = run_case(f"System event: duplicate payment detected on order {order} at M1006.", "M1006", llm=OFF,
                 source="system", language="en-IN", trigger="duplicate_payment")
    return s


def _answer(s, decision, token=None, h=None):
    return customer_decide(s["case_id"], decision, h or s["customer_ask"]["hash"],
                           token=token if token is not None else s["customer_ask"]["token"], llm=OFF)


# ---------- the pause ----------
def test_detects_duplicate_and_asks_customer_without_moving_money():
    s = _start()
    assert s["status"] == "waiting_customer" and s["diagnosis"]["code"] == "DUPLICATE_CHARGE"
    q = s["customer_messages"][0]["content"]
    assert "₹650 twice to Kumar Hotel" in q and "INV-901" in q and "9:02 AM" in q and "9:03 AM" in q
    assert "asked the customer" in s["reply"] and "ORD-6002" in s["reply"]         # merchant heads-up
    assert s["customer_vpa"] == "vasanth@oksbi"
    assert _refunds() == [] and not [e for e in audit.events(s["case_id"]) if e["kind"] in ("action", "policy")]


def test_token_and_raw_vpa_never_logged():
    s = _start()
    blob = json.dumps(audit.events(s["case_id"]))
    assert s["customer_ask"]["token"] not in blob and "vasanth@oksbi" not in blob


# ---------- customer answers ----------
def test_keep_both_moves_no_money_and_tells_both():
    s = _answer(_start(), "keep")
    assert s["status"] == "resolved" and _refunds() == []
    assert "Both payments of ₹650" in s["customer_messages"][-1]["content"]
    assert "confirmed both payments" in s["reply"]


def test_refund_one_auto_r21_verified_and_tells_both():
    s = _answer(_start(), "refund")
    assert s["status"] == "resolved" and s["policy_decision"]["rule_id"] == "R-21"
    assert _refunds() == [("ORD-6002", 650.0, "TXN_SUCCESS")]                       # only the LATER one
    rid = s["verification"]["refund_id"]
    assert rid in s["customer_messages"][-1]["content"] and rid in s["reply"]


def test_big_refund_still_needs_ops_r22():
    s = _start("ORD-6004")
    assert "₹7,200" in s["customer_messages"][0]["content"]
    s = _answer(s, "refund")
    assert s["status"] == "waiting_approval" and s["policy_decision"]["rule_id"] == "R-22"
    assert "being reviewed" in s["customer_messages"][-1]["content"] and _refunds() == []
    s = decide(s["case_id"], "approve", "priya", s["approval_request"]["hash"], llm=OFF)
    assert s["status"] == "resolved" and _refunds() == [("ORD-6004", 7200.0, "TXN_SUCCESS")]
    assert "refunded" in s["customer_messages"][-1]["content"]


def test_big_refund_rejected_by_ops():
    s = _answer(_start("ORD-6004"), "refund")
    s = decide(s["case_id"], "reject", "priya", s["approval_request"]["hash"], llm=OFF)
    assert s["status"] == "resolved" and _refunds() == [] and s["ticket_id"]
    assert "could not refund" in s["customer_messages"][-1]["content"]


def test_no_reply_keeps_both():
    s = _start()
    s = customer_decide(s["case_id"], "no_response", s["customer_ask"]["hash"], by_ops=True, llm=OFF)
    assert s["status"] == "resolved" and _refunds() == []
    assert "didn't hear back" in s["customer_messages"][-1]["content"]


# ---------- consent guardrails ----------
def test_wrong_token_refused_and_question_stays_open():
    s = _start()
    with pytest.raises(ApprovalError, match="token"):
        _answer(s, "refund", token="0" * 16)
    assert _refunds() == []
    assert _answer(s, "refund")["status"] == "resolved"                            # real customer still can


def test_wrong_hash_refused():
    s = _start()
    with pytest.raises(ApprovalError, match="hash"):
        _answer(s, "refund", h="0" * 16)


def test_customer_cannot_fake_no_reply():
    s = _start()
    with pytest.raises(ApprovalError, match="Ops"):
        customer_decide(s["case_id"], "no_response", s["customer_ask"]["hash"], token=s["customer_ask"]["token"], llm=OFF)


def test_answer_twice_refused_single_refund():
    s = _start()
    _answer(s, "refund")
    with pytest.raises(ApprovalError, match="not waiting"):
        _answer(s, "refund")
    assert len(_refunds()) == 1


def test_merchant_complaint_flow_unchanged():
    """Case 2-style merchant complaint still goes straight to policy (no customer step)."""
    s = run_case("ORD-2003 charged twice", "M1002", "0002", llm=OFF)
    assert s["status"] == "resolved" and s["policy_decision"]["rule_id"] == "R-21" and not s.get("customer_ask")


# ---------- API ----------
@pytest.fixture
def client():
    return TestClient(api.app)


def wait(client, cid, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        v = client.get(f"/cases/{cid}").json()
        if not v["running"]:
            return v
        time.sleep(0.05)
    raise AssertionError("case did not finish")


def test_api_end_to_end_refund(client):
    r = client.post("/events/duplicate-payment", headers=OPS, json={"order_id": "ORD-6002"})
    assert r.status_code == 202
    cid = r.json()["case_id"]
    v = wait(client, cid)
    assert v["status"] == "waiting_customer" and v["trigger"] == "duplicate_payment"
    inbox = client.get("/customer/inbox", params={"vpa": "vasanth@oksbi"}).json()
    assert len(inbox) == 1 and inbox[0]["ask"] and "twice" in inbox[0]["messages"][0]["content"]
    ask = inbox[0]["ask"]
    r = client.post(f"/customer/decisions/{cid}", json={"decision": "refund", "token": ask["token"], "evidence_hash": ask["evidence_hash"]})
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    inbox = client.get("/customer/inbox", params={"vpa": "vasanth@oksbi"}).json()
    assert inbox[0]["ask"] is None and "refunded" in inbox[0]["messages"][-1]["content"]


def test_inbox_only_shows_your_own_payments(client):
    wait(client, client.post("/events/duplicate-payment", headers=OPS, json={"order_id": "ORD-6002"}).json()["case_id"])
    assert client.get("/customer/inbox", params={"vpa": "lalitha@okaxis"}).json() == []
    assert client.get("/customer/inbox", params={"vpa": "not a vpa"}).status_code == 422


def test_api_wrong_token_403(client):
    cid = client.post("/events/duplicate-payment", headers=OPS, json={"order_id": "ORD-6002"}).json()["case_id"]
    wait(client, cid)
    h = client.get("/customer/inbox", params={"vpa": "vasanth@oksbi"}).json()[0]["ask"]["evidence_hash"]
    r = client.post(f"/customer/decisions/{cid}", json={"decision": "refund", "token": "0" * 16, "evidence_hash": h})
    assert r.status_code == 403 and client.get(f"/cases/{cid}").json()["status"] == "waiting_customer"


def test_api_no_reply_needs_ops(client):
    cid = client.post("/events/duplicate-payment", headers=OPS, json={"order_id": "ORD-6002"}).json()["case_id"]
    wait(client, cid)
    assert client.post(f"/cases/{cid}/customer-no-reply").status_code == 401
    r = client.post(f"/cases/{cid}/customer-no-reply", headers=OPS)
    assert r.status_code == 200 and r.json()["status"] == "resolved" and _refunds() == []


def test_event_for_non_duplicate_is_409(client):
    assert client.post("/events/duplicate-payment", headers=OPS, json={"order_id": "ORD-1002"}).status_code == 409
    assert client.post("/events/duplicate-payment", headers=OPS, json={"order_id": "ORD-9999"}).status_code == 404
    assert client.post("/events/duplicate-payment", json={"order_id": "ORD-6002"}).status_code == 401
