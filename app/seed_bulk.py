"""A week of extra synthetic history for 6 more merchants (M1007-M1012): about 110 transactions.

Kept separate from the 6 demo merchants on purpose: their data (and so the demo cases, tests and the
cached Sarvam answers) is unchanged. Deterministic: fixed seed + fixed clock, identical on every reset.

Scenarios hidden in the history (each is reachable by asking about the order, see SCENARIOS below):
  M1007 Murugan Bakery       yesterday's payout FAILED (BANK_TIMEOUT), first retry, <= ₹50,000 -> R-07 auto
  M1008 Selvi Silks          yesterday's payout FAILED again (already retried once)            -> R-08 Ops
                             + a ₹1,25,000 double charge (refund above ₹1,00,000)              -> R-23 escalate
  M1009 Ravi Electricals     yesterday's payout FAILED (ACCOUNT_INVALID, not transient)        -> G-06 escalate
                             + an ₹18,500 double charge                                       -> R-22 Ops
  M1010 Meena Medicals       yesterday's payout still SCHEDULED, past its date                -> G-06 escalate
                             + a payment stuck PENDING                                        -> G-06 escalate
  M1011 Anand Sweets         yesterday's payout FAILED (BANK_DOWNTIME), above ₹50,000         -> R-10 Ops
  M1012 Priya Cafe           a ₹480 double charge today                                       -> R-21 auto
All merchants: older payouts SUCCESS (UTR), today's payout SCHEDULED for 18:00, a few failed payments.
"""
import random
from datetime import timedelta

from app.models import Merchant, Payout, Transaction

MERCHANTS = [
    # mid, name, language, bank, block (order numbers ORD-<block>01..), amount range, yesterday's payout
    ("M1007", "Murugan Bakery", "ta-IN", "XXXX1107", 70, (40, 900), ("FAILED", "BANK_TIMEOUT", 0)),
    ("M1008", "Selvi Silks", "ta-IN", "XXXX2208", 71, (1500, 22000), ("FAILED", "BANK_DOWNTIME", 1)),
    ("M1009", "Ravi Electricals", "en-IN", "XXXX3309", 72, (300, 9000), ("FAILED", "ACCOUNT_INVALID", 0)),
    ("M1010", "Meena Medicals", "en-IN", "XXXX4410", 73, (60, 2500), ("SCHEDULED", "", 0)),
    ("M1011", "Anand Sweets", "ta-IN", "XXXX5511", 74, (150, 3000), ("FAILED", "BANK_DOWNTIME", 0)),
    ("M1012", "Priya Cafe", "en-IN", "XXXX6612", 75, (90, 700), ("SUCCESS", "", 0)),
]
FIRST_NAMES = ["arjun", "kavya", "suresh", "deepa", "vijay", "anitha", "karthik", "revathi", "bala", "nithya",
               "ganesh", "sangeetha", "hari", "lakshmi", "mohan", "priya", "rajesh", "uma", "venkat", "yamini"]
BANKS = ["okaxis", "oksbi", "okhdfc", "ybl", "okicici", "paytm"]
DAYS = range(-6, 1)          # six days ago .. today


def seed_bulk(s, now):
    rng = random.Random(20261115)
    s.add_all([Merchant(mid=mid, name=name, phone=f"98400000{mid[-2:]}", language=lang,
                        bank_account_masked=bank, city="Chennai")
               for mid, name, lang, bank, *_ in MERCHANTS])
    vpa_n = 0

    def vpa():
        nonlocal vpa_n
        vpa_n += 1                      # unique payer per payment, so no accidental duplicates
        return f"{rng.choice(FIRST_NAMES)}{vpa_n}@{rng.choice(BANKS)}"

    for mid, _name, _lang, _bank, block, (lo, hi), (y_status, y_reason, y_retries) in MERCHANTS:
        seq = 0
        by_day = {d: [] for d in DAYS}

        def txn(day, amount, *, status="TXN_SUCCESS", payer=None, invoice="", at=None):
            nonlocal seq
            seq += 1
            base = (now + timedelta(days=day)).replace(minute=0, second=0, microsecond=0)
            if at is None:              # today: only before the fixed 10:00 clock
                hour = rng.randint(7, 9) if day == 0 else rng.randint(8, 21)
                at = base.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59))
            t = Transaction(txn_id=f"TXN{block}{seq:02d}", order_id=f"ORD-{block}{seq:02d}", mid=mid,
                            amount=float(amount), status=status, customer_vpa=payer or vpa(),
                            merchant_invoice=invoice, created_at=at)
            s.add(t)
            if status == "TXN_SUCCESS":
                by_day[day].append(t)
            return t

        for day in DAYS:
            for _ in range(rng.randint(2, 3)):
                failed = rng.random() < 0.08
                txn(day, rng.randint(lo, hi), status="TXN_FAILURE" if failed else "TXN_SUCCESS")

        # ---- special scenarios ----
        y = now - timedelta(days=1)
        if mid == "M1008":              # ₹1,25,000 bridal silk paid twice: refund above ₹1,00,000 -> R-23
            p = vpa()
            txn(-1, 125000, payer=p, invoice="INV-S77", at=y.replace(hour=17, minute=5, second=0))
            txn(-1, 125000, payer=p, invoice="INV-S77", at=y.replace(hour=17, minute=6, second=40))
        if mid == "M1009":              # ₹18,500 inverter paid twice -> R-22 Ops approval
            p, d2 = vpa(), (now - timedelta(days=2))
            txn(-2, 18500, payer=p, invoice="INV-E42", at=d2.replace(hour=12, minute=30, second=0))
            txn(-2, 18500, payer=p, invoice="INV-E42", at=d2.replace(hour=12, minute=31, second=15))
        if mid == "M1010":              # payment stuck PENDING at the bank
            txn(0, 1240, status="PENDING")
        if mid == "M1011":              # wedding sweet orders push yesterday's payout above ₹50,000
            txn(-1, 42000, invoice="INV-W11")
            txn(-1, 18500, invoice="INV-W12")
        if mid == "M1012":              # ₹480 breakfast bill paid twice -> R-21 auto refund
            p = vpa()
            txn(0, 480, payer=p, invoice="INV-C09", at=now.replace(hour=8, minute=15, second=0))
            txn(0, 480, payer=p, invoice="INV-C09", at=now.replace(hour=8, minute=16, second=5))

        # ---- one payout per day ----
        for day in DAYS:
            txns = by_day[day]
            if not txns:
                continue
            pid = f"PO-{block}{day + 6:02d}"
            amount = float(sum(t.amount for t in txns))
            ids = [t.txn_id for t in txns]
            if day == 0:
                s.add(Payout(payout_id=pid, mid=mid, txn_ids=ids, amount=amount, status="SCHEDULED",
                             expected_date=now.replace(hour=18)))
            elif day == -1 and y_status != "SUCCESS":
                s.add(Payout(payout_id=pid, mid=mid, txn_ids=ids, amount=amount, status=y_status,
                             failure_reason=y_reason, retry_count=y_retries,
                             expected_date=(now - timedelta(days=1)).replace(hour=18) if y_status == "SCHEDULED"
                             else now.replace(hour=9)))
            else:
                exp = (now + timedelta(days=day + 1)).replace(hour=9, minute=0, second=0, microsecond=0)
                s.add(Payout(payout_id=pid, mid=mid, txn_ids=ids, amount=amount, status="SUCCESS",
                             utr=f"UTR{exp:%y%m%d}{block}{day + 6:02d}", expected_date=exp))
