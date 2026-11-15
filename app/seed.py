"""Synthetic data that encodes the demo scenarios. All data is fake.

Case 1  M1001 Lakshmi Tiffin Centre  ORD-1001 ₹2,400  payout failed (bank timeout)  -> auto retry
Case 2  M1002 Arun Mobiles           ORD-2001/2002 ₹12,000 duplicate charge         -> refund needs approval
Case 3  M1003 Sri Balaji Stores      claims ORD-4001, which belongs to M1004        -> escalate
Case 4  M1006 Kumar Hotel            customer paid ₹650 bill twice (ORD-6001/6002)    -> proactive: ask customer keep/refund
Extras  settled txn, pending-in-window txn, failed txn, small duplicate (auto refund), risk-flagged merchant

Run:  python -m app.seed
"""
from datetime import datetime, timedelta

from app.db import Base, get_engine, session_scope
from app.models import AuditEvent, Merchant, Payout, Refund, RiskFlag, Ticket, Transaction


def _now() -> datetime:
    # Fixed "today" (DEMO_NOW, default 2026-11-15 10:00) so the demo behaves identically every run.
    from app.clock import now
    return now()


def reset_and_seed():
    from app.mock_systems import reset_runtime_state
    reset_runtime_state()               # clear lockouts / forced failures too
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    now = _now()
    y = now - timedelta(days=1)

    with session_scope() as s:
        s.add_all([
            Merchant(mid="M1001", name="Lakshmi Tiffin Centre", phone="9840000001", language="ta-IN", bank_account_masked="XXXX4521", city="Chennai"),
            Merchant(mid="M1002", name="Arun Mobiles", phone="9840000002", language="en-IN", bank_account_masked="XXXX7710", city="Chennai"),
            Merchant(mid="M1003", name="Sri Balaji Stores", phone="9840000003", language="en-IN", bank_account_masked="XXXX3398", city="Chennai"),
            Merchant(mid="M1004", name="Kaveri Textiles", phone="9840000004", language="ta-IN", bank_account_masked="XXXX9012", city="Chennai"),
            Merchant(mid="M1005", name="Green Leaf Pharmacy", phone="9840000005", language="en-IN", bank_account_masked="XXXX5566", city="Chennai"),
            Merchant(mid="M1006", name="Kumar Hotel", phone="9840000006", language="en-IN", bank_account_masked="XXXX6120", city="Chennai"),
        ])

        s.add_all([
            # Case 1: success, but its payout failed on a transient bank error
            Transaction(txn_id="TXN1001", order_id="ORD-1001", mid="M1001", amount=2400, status="TXN_SUCCESS", customer_vpa="ravi@okaxis", created_at=y.replace(hour=13)),
            # M1001 extras: settled, and pending-in-window
            Transaction(txn_id="TXN1002", order_id="ORD-1002", mid="M1001", amount=650, status="TXN_SUCCESS", customer_vpa="meena@oksbi", created_at=y - timedelta(days=1)),
            Transaction(txn_id="TXN1003", order_id="ORD-1003", mid="M1001", amount=900, status="TXN_SUCCESS", customer_vpa="karthik@ybl", created_at=now - timedelta(hours=2)),
            Transaction(txn_id="TXN1004", order_id="ORD-1004", mid="M1001", amount=300, status="TXN_FAILURE", customer_vpa="divya@okicici", created_at=y.replace(hour=18)),

            # Case 2: same customer, same invoice, same amount, 90 seconds apart
            Transaction(txn_id="TXN2001", order_id="ORD-2001", mid="M1002", amount=12000, status="TXN_SUCCESS", customer_vpa="suresh@okhdfc", merchant_invoice="INV-778", created_at=y.replace(hour=16, minute=10, second=0)),
            Transaction(txn_id="TXN2002", order_id="ORD-2002", mid="M1002", amount=12000, status="TXN_SUCCESS", customer_vpa="suresh@okhdfc", merchant_invoice="INV-778", created_at=y.replace(hour=16, minute=11, second=30)),
            # Small duplicate for testing the auto-refund branch
            Transaction(txn_id="TXN2003", order_id="ORD-2003", mid="M1002", amount=1499, status="TXN_SUCCESS", customer_vpa="priya@ybl", merchant_invoice="INV-801", created_at=y.replace(hour=11, minute=0, second=0)),
            Transaction(txn_id="TXN2004", order_id="ORD-2004", mid="M1002", amount=1499, status="TXN_SUCCESS", customer_vpa="priya@ybl", merchant_invoice="INV-801", created_at=y.replace(hour=11, minute=1, second=0)),

            # Case 3: this order belongs to M1004, not M1003
            Transaction(txn_id="TXN4001", order_id="ORD-4001", mid="M1004", amount=48000, status="TXN_SUCCESS", customer_vpa="anand@okaxis", created_at=y.replace(hour=12)),

            # Big failed payout (₹75,000 > ₹50,000 limit): retry needs Ops approval (R-10)
            Transaction(txn_id="TXN4002", order_id="ORD-4002", mid="M1004", amount=75000, status="TXN_SUCCESS", customer_vpa="silks.buyer@okhdfc", created_at=y.replace(hour=15)),

            # Risk-flagged merchant
            Transaction(txn_id="TXN5001", order_id="ORD-5001", mid="M1005", amount=8000, status="TXN_SUCCESS", customer_vpa="unknown1@ybl", created_at=y.replace(hour=23, minute=50)),

            # Case 4 (proactive duplicate): a diner paid the same ₹650 bill twice, 70 seconds apart.
            # Nobody complains; the system notices and asks the CUSTOMER: keep both or refund one?
            Transaction(txn_id="TXN6001", order_id="ORD-6001", mid="M1006", amount=650, status="TXN_SUCCESS", customer_vpa="vasanth@oksbi", merchant_invoice="INV-901", created_at=now.replace(hour=9, minute=2, second=10)),
            Transaction(txn_id="TXN6002", order_id="ORD-6002", mid="M1006", amount=650, status="TXN_SUCCESS", customer_vpa="vasanth@oksbi", merchant_invoice="INV-901", created_at=now.replace(hour=9, minute=3, second=20)),
            # Bigger duplicate (₹7,200 hall booking): customer says refund -> still needs Ops approval (R-22)
            Transaction(txn_id="TXN6003", order_id="ORD-6003", mid="M1006", amount=7200, status="TXN_SUCCESS", customer_vpa="lalitha@okaxis", merchant_invoice="INV-950", created_at=now.replace(hour=9, minute=20, second=0)),
            Transaction(txn_id="TXN6004", order_id="ORD-6004", mid="M1006", amount=7200, status="TXN_SUCCESS", customer_vpa="lalitha@okaxis", merchant_invoice="INV-950", created_at=now.replace(hour=9, minute=21, second=5)),
        ])

        s.add_all([
            Payout(payout_id="PO-1001", mid="M1001", txn_ids=["TXN1001"], amount=2400, status="FAILED", failure_reason="BANK_TIMEOUT", retry_count=0, expected_date=now.replace(hour=9)),
            Payout(payout_id="PO-1002", mid="M1001", txn_ids=["TXN1002"], amount=650, status="SUCCESS", utr="UTR2611140001", expected_date=y.replace(hour=9)),
            Payout(payout_id="PO-1003", mid="M1001", txn_ids=["TXN1003"], amount=900, status="SCHEDULED", expected_date=(now + timedelta(days=1)).replace(hour=9)),
            Payout(payout_id="PO-2001", mid="M1002", txn_ids=["TXN2001", "TXN2002", "TXN2003", "TXN2004"], amount=26998, status="SCHEDULED", expected_date=now.replace(hour=18)),
            Payout(payout_id="PO-4001", mid="M1004", txn_ids=["TXN4001"], amount=48000, status="SUCCESS", utr="UTR2611150044", expected_date=now.replace(hour=9)),
            Payout(payout_id="PO-4002", mid="M1004", txn_ids=["TXN4002"], amount=75000, status="FAILED", failure_reason="BANK_DOWNTIME", retry_count=0, expected_date=now.replace(hour=9)),
            Payout(payout_id="PO-5001", mid="M1005", txn_ids=["TXN5001"], amount=8000, status="ON_HOLD", failure_reason="RISK_REVIEW", expected_date=now.replace(hour=9)),
            Payout(payout_id="PO-6001", mid="M1006", txn_ids=["TXN6001", "TXN6002", "TXN6003", "TXN6004"], amount=15700, status="SCHEDULED", expected_date=now.replace(hour=18)),
        ])

        s.add(RiskFlag(mid="M1005", flag="VELOCITY_ANOMALY", note="Unusual late-night volume from new VPAs"))

        # A week of extra history for 6 more merchants (M1007-M1012). Demo merchants above are untouched.
        from app.seed_bulk import seed_bulk
        seed_bulk(s, now)

    print("Seeded synthetic data.")


if __name__ == "__main__":
    reset_and_seed()
