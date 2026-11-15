"""Extra synthetic history (app/seed_bulk.py): ~115 transactions for M1007-M1012, each hidden scenario
reaches the outcome it was designed for, and the six demo merchants are untouched."""
import pytest

from app.agent.graph import run_case
from app.db import init_engine, session_scope
from app.llm import OfflineLLM
from app.models import Transaction
from app.seed import reset_and_seed

OFF = OfflineLLM()


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_engine(f"sqlite:///{tmp_path}/bulk.db")
    reset_and_seed()


def test_at_least_100_extra_transactions_and_demo_merchants_unchanged():
    with session_scope() as s:
        new = s.query(Transaction).filter(Transaction.mid >= "M1007").count()
        demo = s.query(Transaction).filter(Transaction.mid < "M1007").count()
        statuses = {t.status for t in s.query(Transaction).filter(Transaction.mid >= "M1007")}
    assert new >= 100
    assert demo == 15                      # the demo scenarios see exactly the same data as before
    assert statuses == {"TXN_SUCCESS", "TXN_FAILURE", "PENDING"}


@pytest.mark.parametrize("mid,order,status,rule", [
    ("M1007", "ORD-7014", "resolved", "R-07"),            # payout failed, first retry, small
    ("M1007", "ORD-7002", "resolved", "SETTLED"),
    ("M1007", "ORD-7016", "resolved", "PAYOUT_PENDING_IN_WINDOW"),
    ("M1007", "ORD-7001", "resolved", "TXN_FAILED"),
    ("M1008", "ORD-7113", "waiting_approval", "R-08"),    # second retry needs Ops
    ("M1008", "ORD-7120", "escalated", "R-23"),           # ₹1,25,000 duplicate: above refund limit
    ("M1009", "ORD-7213", "escalated", "G-06"),           # ACCOUNT_INVALID is not transient
    ("M1009", "ORD-7219", "waiting_approval", "R-22"),    # ₹18,500 duplicate
    ("M1010", "ORD-7314", "escalated", "G-06"),           # payout past its expected date
    ("M1010", "ORD-7318", "escalated", "G-06"),           # payment stuck PENDING
    ("M1011", "ORD-7415", "waiting_approval", "R-10"),    # payout above ₹50,000
    ("M1012", "ORD-7519", "resolved", "R-21"),            # ₹480 duplicate, auto refund
])
def test_hidden_scenarios(mid, order, status, rule):
    s = run_case(f"Where is my money for {order}?", mid, "00" + mid[-2:], llm=OFF, reply_llm=OFF)
    got = (s.get("policy_decision") or {}).get("rule_id") or (s.get("diagnosis") or {}).get("code")
    assert (s["status"], got) == (status, rule)
