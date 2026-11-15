"""Step 1 checks: seed data, mock systems and policy behave as the demo needs."""
import pytest

from app import mock_systems as ms
from app.db import init_engine
from app.policy_engine import ProposedAction, evaluate, load_policy
from app.seed import reset_and_seed


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    init_engine(f"sqlite:///{tmp_path}/test.db")
    reset_and_seed()
    ms.reset_runtime_state()
    yield


# ---------- Case 1: payout retry ----------
def test_case1_payout_failed_then_retry_succeeds():
    pay = ms.get_payment_status("ORD-1001", "M1001")["body"]
    assert pay["resultInfo"]["resultStatus"] == "TXN_SUCCESS"
    st = ms.get_settlement_for_txn("M1001", pay["txnId"])["payout"]
    assert st["status"] == "FAILED" and st["failureReason"] == "BANK_TIMEOUT"

    d = evaluate(ProposedAction("retry_payout", prior_retries=st["retryCount"], failure_reason=st["failureReason"]), set())
    assert (d.tier, d.rule_id) == ("auto", "R-07")

    r = ms.retry_payout("M1001", "PO-1001", "case1-retry-1")
    assert r["accepted"] and not r["duplicate_request"]
    again = ms.retry_payout("M1001", "PO-1001", "case1-retry-1")          # same key: no second retry
    assert again["duplicate_request"]
    v = ms.get_payout_status("M1001", "PO-1001")["payout"]                 # read-after-write
    assert v["status"] == "SUCCESS" and v["utr"].startswith("UTR")


# ---------- Case 2: duplicate charge ----------
def test_case2_duplicate_found_and_needs_approval():
    dups = ms.find_duplicate_payments("M1002", "ORD-2001")["duplicates"]
    assert [d["orderId"] for d in dups] == ["ORD-2002"]
    d = evaluate(ProposedAction("refund_duplicate", amount=12000), {"duplicate_verified"})
    assert (d.tier, d.rule_id) == ("approval", "R-22")


def test_small_duplicate_is_auto_refunded_once():
    d = evaluate(ProposedAction("refund_duplicate", amount=1499), {"duplicate_verified"})
    assert d.tier == "auto"
    r1 = ms.initiate_refund("M1002", "ORD-2004", "TXN2004", 1499, "case-x-refund-1")
    r2 = ms.initiate_refund("M1002", "ORD-2004", "TXN2004", 1499, "case-x-refund-1")
    assert r1["body"]["refundId"] == r2["body"]["refundId"] and r2["duplicate_request"]
    assert ms.get_refund_status("M1002", "case-x-refund-1")["body"]["resultInfo"]["resultStatus"] == "TXN_SUCCESS"


# ---------- Case 3: someone else's transaction ----------
def test_case3_ownership_mismatch_reveals_nothing_and_escalates():
    body = ms.get_payment_status("ORD-4001", "M1003")["body"]
    assert body["resultInfo"]["resultStatus"] == "OWNERSHIP_MISMATCH"
    assert "txnAmount" not in body and "customerVpa" not in body
    d = evaluate(ProposedAction("create_ticket"), {"ownership_mismatch"})
    assert (d.tier, d.rule_id) == ("escalate", "G-01")


# ---------- Safety edges ----------
def test_risk_flag_blocks_everything():
    assert ms.get_risk_flags("M1005")["flags"] == ["VELOCITY_ANOMALY"]
    assert evaluate(ProposedAction("refund_duplicate", amount=10), {"risk_flag"}).tier == "escalate"


def test_unknown_action_fails_closed():
    assert evaluate(ProposedAction("delete_merchant"), set()).tier == "escalate"


def test_identity_check():
    assert ms.verify_merchant("M1001", "0001")["verified"]
    assert not ms.verify_merchant("M1001", "9999")["verified"]


def test_forced_tool_failure_raises():
    ms.FORCED_FAILURES.add("get_payment_status")
    with pytest.raises(ms.ToolError):
        ms.get_payment_status("ORD-1001", "M1001")


def test_policy_file_loads():
    p = load_policy()
    assert p["version"] == 1 and "retry_payout" in p["actions"]
