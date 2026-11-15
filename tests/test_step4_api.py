"""Step 4: FastAPI endpoints, background runs, ops token, proactive mode, mini-RAG citations."""
import time

import pytest
from fastapi.testclient import TestClient

from app import api
from app import mock_systems as ms
from app.config import get_settings
from app.db import init_engine
from app.kb import cite
from app.llm import OfflineLLM
from app.seed import reset_and_seed

OPS = {"X-Ops-Token": "demo-ops-token"}


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    init_engine(f"sqlite:///{tmp_path}/test.db")
    reset_and_seed()
    monkeypatch.setattr(get_settings(), "tool_retry_backoff", 0.0)
    monkeypatch.setattr(get_settings(), "ops_token", "demo-ops-token")
    api.set_llms(OfflineLLM())
    api._HITS.clear()
    api._ERRORS.clear()
    yield
    ms.reset_runtime_state()


@pytest.fixture
def client():
    return TestClient(api.app)


def wait(client, case_id, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        v = client.get(f"/cases/{case_id}").json()
        if not v["running"]:
            return v
        time.sleep(0.05)
    raise AssertionError("case did not finish")


def start(client, mid, last4, text):
    r = client.post("/cases", json={"mid": mid, "phone_last4": last4, "text": text})
    assert r.status_code == 202, r.text
    return r.json()["case_id"]


# ---------- happy paths ----------
def test_case1_over_api_with_timeline_and_citation(client):
    cid = start(client, "M1001", "0001", "என் ORD-1001 ₹2,400 பணம் வரவில்லை")
    v = wait(client, cid)
    assert v["status"] == "resolved" and v["policy"]["rule_id"] == "R-07"
    assert v["verification"]["utr"] in v["reply"]
    assert v["citation"]["doc"] == "kb/payout-retries.md"
    ev = client.get(f"/cases/{cid}/events").json()["events"]
    kinds = [e["kind"] for e in ev]
    assert "policy" in kinds and "action" in kinds and "verify" in kinds
    later = client.get(f"/cases/{cid}/events", params={"after": ev[3]["id"]}).json()["events"]
    assert later and later[0]["id"] == ev[4]["id"]                   # incremental polling works


def test_case_view_hides_raw_evidence(client):
    v = wait(client, start(client, "M1002", "0002", "ORD-2001 charged twice"))
    assert "evidence" not in v and "approval_request" not in v and "phone_last4" not in str(v)


def test_needs_info_then_follow_up_message(client):
    cid = start(client, "M1001", "0001", "My money didn't come")
    assert wait(client, cid)["status"] == "needs_info"
    assert client.post(f"/cases/{cid}/messages", json={"text": "It's ORD-1002"}).status_code == 202
    v = wait(client, cid)
    assert v["status"] == "resolved" and v["diagnosis"] == "SETTLED" and "UTR2611140001" in v["reply"]


def test_message_to_closed_case_rejected(client):
    cid = start(client, "M1001", "0001", "ORD-1002 status")
    wait(client, cid)
    assert client.post(f"/cases/{cid}/messages", json={"text": "also refund ORD-1001"}).status_code == 409


# ---------- approvals ----------
def test_approval_flow_over_api(client):
    cid = start(client, "M1002", "0002", "Charged twice for ORD-2001, ₹12,000")
    assert wait(client, cid)["status"] == "waiting_approval"
    pend = client.get("/approvals", headers=OPS).json()
    assert [p["case_id"] for p in pend] == [cid]
    h = pend[0]["evidence_hash"]
    r = client.post(f"/approvals/{cid}", headers=OPS, json={"decision": "approve", "reviewer": "priya", "evidence_hash": h})
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    assert r.json()["verification"]["status"] == "TXN_SUCCESS"
    assert client.get("/approvals", headers=OPS).json() == []
    again = client.post(f"/approvals/{cid}", headers=OPS, json={"decision": "approve", "reviewer": "priya", "evidence_hash": h})
    assert again.status_code == 409


def test_ops_endpoints_need_token(client):
    cid = start(client, "M1002", "0002", "Charged twice for ORD-2001")
    wait(client, cid)
    body = {"decision": "approve", "reviewer": "x", "evidence_hash": "0" * 16}
    assert client.get("/approvals").status_code == 401
    assert client.get("/approvals", headers={"X-Ops-Token": "guess"}).status_code == 401
    assert client.post(f"/approvals/{cid}", json=body).status_code == 401
    assert client.post("/demo/reset").status_code == 401
    assert client.post("/events/payout-failed", json={"payout_id": "PO-1001"}).status_code == 401


def test_wrong_hash_over_api_is_400_and_stays_paused(client):
    cid = start(client, "M1002", "0002", "Charged twice for ORD-2001")
    wait(client, cid)
    r = client.post(f"/approvals/{cid}", headers=OPS, json={"decision": "approve", "reviewer": "p", "evidence_hash": "0" * 16})
    assert r.status_code == 400
    assert client.get(f"/cases/{cid}").json()["status"] == "waiting_approval"


# ---------- proactive mode ----------
def test_proactive_payout_failed_event(client):
    r = client.post("/events/payout-failed", headers=OPS, json={"payout_id": "PO-1001"})
    assert r.status_code == 202
    v = wait(client, r.json()["case_id"])
    assert v["source"] == "system" and v["status"] == "resolved" and v["policy"]["rule_id"] == "R-07"
    assert v["language"] == "ta-IN"                                   # merchant's profile language
    assert v["verification"]["utr"] in v["reply"]


def test_proactive_rejects_non_failed_payout(client):
    assert client.post("/events/payout-failed", headers=OPS, json={"payout_id": "PO-1002"}).status_code == 409
    assert client.post("/events/payout-failed", headers=OPS, json={"payout_id": "PO-9999"}).status_code == 404


# ---------- input guards ----------
@pytest.mark.parametrize("body", [
    {"mid": "M1001", "phone_last4": "", "text": "x"},
    {"mid": "M1001", "phone_last4": "12a4", "text": "x"},
    {"mid": "1001", "phone_last4": "0001", "text": "x"},
    {"mid": "M1001", "phone_last4": "0001", "text": ""},
    {"mid": "M1001", "phone_last4": "0001", "text": "x" * 1001},
    {"mid": "M1001", "phone_last4": "0001"},
])
def test_invalid_case_input_rejected(client, body):
    assert client.post("/cases", json=body).status_code == 422


def test_oversized_body_rejected(client):
    r = client.post("/cases", content=b"{" + b" " * 20_000 + b"}", headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_per_min", 3)
    codes = [client.post("/cases", json={"mid": "M1001", "phone_last4": "0001", "text": "ORD-1002"}).status_code
             for _ in range(4)]
    assert codes == [202, 202, 202, 429]
    time.sleep(0.5)   # let background cases finish before teardown


def test_unknown_case_404(client):
    assert client.get("/cases/CASE-NOPE").status_code == 404


# ---------- reset / stats / merchants ----------
def test_stats_and_reset(client):
    wait(client, start(client, "M1001", "0001", "ORD-1002 status"))
    wait(client, start(client, "M1003", "0003", "ORD-4001 missing"))
    st = client.get("/stats").json()
    assert st["cases"] == 2 and st["auto_resolved"] == 1 and st["escalated"] == 1
    assert client.post("/demo/reset", headers=OPS).status_code == 200
    assert client.get("/stats").json()["cases"] == 0


def test_demo_merchants_have_no_phone(client):
    ms_ = client.get("/demo/merchants").json()
    assert len(ms_) == 6 and all("phone" not in m for m in ms_)


def test_cors_allows_web_app_only(client):
    ok = client.options("/cases", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    bad = client.options("/cases", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


# ---------- mini-RAG ----------
@pytest.mark.parametrize("q,doc", [
    ("PAYOUT_FAILED_TRANSIENT Payout failed: BANK_TIMEOUT", "payout-retries.md"),
    ("SETTLED Payout already succeeded", "settlement-timelines.md"),
    ("DUPLICATE_CHARGE ORD-2002 duplicates ORD-2001", "duplicate-charges.md"),
    ("TXN_FAILED Customer payment failed", "failed-payments.md"),
    ("escalation specialist ticket follow up", "escalations.md"),
])
def test_kb_citation(q, doc):
    assert cite(q)["doc"] == f"kb/{doc}"


def test_escalation_citation_does_not_hint_reason(client):
    v = wait(client, start(client, "M1003", "0003", "ORD-4001 missing"))
    assert v["citation"]["doc"] == "kb/escalations.md"
