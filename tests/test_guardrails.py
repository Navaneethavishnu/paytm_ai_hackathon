"""Guardrail checks: each test pins one hole found in the security review."""
import pytest

from app import mock_systems as ms
from app.db import init_engine
from app.policy_engine import ProposedAction, evaluate, load_policy, validate_policy
from app.seed import reset_and_seed


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    init_engine(f"sqlite:///{tmp_path}/test.db")
    reset_and_seed()
    ms.reset_runtime_state()
    yield


def _status(resp):
    return resp["body"]["resultInfo"]["resultStatus"]


# ---------- 1. Identity ----------
@pytest.mark.parametrize("bad", ["", "1", "001", "00001", "abcd", "٠٠٠١", None])
def test_identity_rejects_malformed_last4(bad):
    assert not ms.verify_merchant("M1001", bad)["verified"]


def test_identity_locks_after_three_wrong_tries():
    for _ in range(ms.MAX_VERIFY_ATTEMPTS):
        assert not ms.verify_merchant("M1001", "9999")["verified"]
    r = ms.verify_merchant("M1001", "0001")          # correct, but locked
    assert not r["verified"] and r["locked"]
    assert ms.verify_merchant("M1002", "0002")["verified"]   # other merchants unaffected


def test_identity_success_resets_counter():
    ms.verify_merchant("M1001", "9999")
    ms.verify_merchant("M1001", "9999")
    assert ms.verify_merchant("M1001", "0001")["verified"]
    ms.verify_merchant("M1001", "9999")
    ms.verify_merchant("M1001", "9999")
    assert ms.verify_merchant("M1001", "0001")["verified"]


# ---------- 2. Ownership on every tool ----------
def test_cannot_retry_another_merchants_payout():
    r = ms.retry_payout("M1003", "PO-1001", "attacker-key")
    assert r == {"accepted": False, "reason": "OWNERSHIP_MISMATCH"}
    p = ms.get_payout_status("M1001", "PO-1001")["payout"]
    assert p["status"] == "FAILED" and p["retryCount"] == 0      # untouched


def test_retry_requires_idempotency_key():
    assert ms.retry_payout("M1001", "PO-1001", "")["reason"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_cannot_read_another_merchants_payout():
    r = ms.get_payout_status("M1003", "PO-4001")
    assert r == {"found": False, "payoutId": "PO-4001", "reason": "OWNERSHIP_MISMATCH"}


def test_cannot_read_another_merchants_refund():
    ms.initiate_refund("M1002", "ORD-2004", "TXN2004", 1499, "case-a:refund")
    r = ms.get_refund_status("M1001", "case-a:refund")
    assert _status(r) == "OWNERSHIP_MISMATCH" and "refundAmount" not in r["body"]
    # and the foreign poll did not advance the refund
    assert _status(ms.get_refund_status("M1002", "case-a:refund")) == "TXN_SUCCESS"


def test_cannot_read_another_merchants_ticket():
    t = ms.create_ticket("M1002", "case-a", "refund", "review")
    assert ms.get_ticket("M1002", t["ticketId"])["found"]
    assert ms.get_ticket("M1001", t["ticketId"]) == {"found": False, "ticketId": t["ticketId"], "status": None}


def test_cannot_hijack_another_merchants_refund_key():
    ms.initiate_refund("M1002", "ORD-2004", "TXN2004", 1499, "case-a:refund")
    r = ms.initiate_refund("M1001", "ORD-1001", "TXN1001", 100, "case-a:refund")
    assert _status(r) == "OWNERSHIP_MISMATCH" and "refundId" not in r["body"]


# ---------- 3. Refund totals ----------
def test_second_refund_with_new_key_cannot_exceed_payment():
    assert not ms.initiate_refund("M1002", "ORD-2004", "TXN2004", 1499, "case-a:refund")["duplicate_request"]
    r = ms.initiate_refund("M1002", "ORD-2004", "TXN2004", 1499, "case-b:refund")   # new case, new key
    assert r["body"]["resultInfo"]["resultCode"] == "617"


def test_partial_refunds_allowed_up_to_payment_total():
    assert "refundId" in ms.initiate_refund("M1002", "ORD-2004", "TXN2004", 1000, "k1")["body"]
    assert "refundId" in ms.initiate_refund("M1002", "ORD-2004", "TXN2004", 499, "k2")["body"]
    assert ms.initiate_refund("M1002", "ORD-2004", "TXN2004", 1, "k3")["body"]["resultInfo"]["resultCode"] == "617"


def test_reused_key_for_different_refund_is_rejected():
    ms.initiate_refund("M1002", "ORD-2004", "TXN2004", 1000, "k1")
    r = ms.initiate_refund("M1002", "ORD-2004", "TXN2004", 499, "k1")
    assert r["body"]["resultInfo"]["resultCode"] == "609"


# ---------- 4. Invalid amounts ----------
@pytest.mark.parametrize("amt", [0, -500, float("nan"), float("inf"), True])
def test_tool_rejects_non_positive_or_invalid_refund(amt):
    r = ms.initiate_refund("M1002", "ORD-2004", "TXN2004", amt, "k-bad")
    assert r["body"]["resultInfo"]["resultCode"] == "608"


@pytest.mark.parametrize("amt", [-500, float("nan"), float("inf")])
def test_policy_escalates_invalid_amount(amt):
    d = evaluate(ProposedAction("refund_duplicate", amount=amt), {"duplicate_verified"})
    assert d.tier == "escalate"


def test_policy_escalates_zero_refund():
    d = evaluate(ProposedAction("refund_duplicate", amount=0), {"duplicate_verified"})
    assert (d.tier, d.rule_id) == ("escalate", "R-23")


# ---------- 5. Refund needs a verified duplicate ----------
def test_refund_without_verified_duplicate_escalates():
    d = evaluate(ProposedAction("refund_duplicate", amount=1499), set())
    assert (d.tier, d.rule_id) == ("escalate", "R-23")


# ---------- 6. Policy file validation ----------
def _policy_with(rule):
    return {"actions": {"x": [rule, {"id": "X-9", "tier": "escalate", "reason": "catch-all"}]}}


def test_policy_typo_after_failing_condition_still_caught():
    bad = _policy_with({"id": "X-1", "tier": "auto", "reason": "r", "when": {"max_amount": 1, "max_amout": 5}})
    with pytest.raises(ValueError, match="max_amout"):
        validate_policy(bad)


def test_policy_rejects_unknown_tier_and_missing_catch_all():
    with pytest.raises(ValueError, match="tier"):
        validate_policy(_policy_with({"id": "X-1", "tier": "yolo", "reason": "r"}))
    with pytest.raises(ValueError, match="catch-all"):
        validate_policy({"actions": {"x": [{"id": "X-1", "tier": "auto", "reason": "r", "when": {"max_amount": 1}}]}})


def test_shipped_policy_is_valid():
    load_policy.cache_clear()
    assert validate_policy(load_policy())


# ---------- 7. Payout retry amount limit (₹50,000) ----------
@pytest.mark.parametrize("amt,tier,rule", [
    (2400, "auto", "R-07"), (50000, "auto", "R-07"), (50000.01, "approval", "R-10"), (500000, "approval", "R-10"),
])
def test_payout_retry_limit(amt, tier, rule):
    d = evaluate(ProposedAction("retry_payout", amount=amt, failure_reason="BANK_TIMEOUT"), set())
    assert (d.tier, d.rule_id) == (tier, rule)


def test_big_payout_retry_pauses_for_ops_then_succeeds():
    from app.agent.graph import decide, run_case
    from app.db import session_scope
    from app.llm import OfflineLLM
    from app.models import Payout, Transaction
    with session_scope() as s:
        s.get(Payout, "PO-1001").amount = 75000
        s.query(Transaction).filter_by(txn_id="TXN1001").one().amount = 75000
    st = run_case("ORD-1001 money not received", "M1001", "0001", llm=OfflineLLM())
    assert st["status"] == "waiting_approval" and st["policy_decision"]["rule_id"] == "R-10"
    assert ms.get_payout_status("M1001", "PO-1001")["payout"]["status"] == "FAILED"      # nothing moved yet
    st = decide(st["case_id"], "approve", "priya", st["approval_request"]["hash"], llm=OfflineLLM())
    assert st["status"] == "resolved" and st["verification"]["utr"] in st["reply"]
