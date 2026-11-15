"""Demo scenarios shared by scripts/run_case.py and scripts/stress.py.

name -> (mid, phone_last4, merchant text, expected final status, expected rule or diagnosis)
case2 pauses for approval; the stress script approves it and expects 'resolved'.
"""
CASES = {
    "case1":     ("M1001", "0001", "என் ORD-1001 ₹2,400 பணம் இன்னும் என் வங்கிக்கு வரவில்லை", "resolved", "R-07"),
    "case2":     ("M1002", "0002", "Customer says they were charged twice for ORD-2001, ₹12,000. Please check.", "waiting_approval", "R-22"),
    "case3":     ("M1003", "0003", "ORD-4001 for ₹48,000 never reached my account.", "escalated", "G-01"),
    "settled":   ("M1001", "0001", "Where is my money for ORD-1002?", "resolved", "SETTLED"),
    "pending":   ("M1001", "0001", "ORD-1003 payment not received yet", "resolved", "PAYOUT_PENDING_IN_WINDOW"),
    "failed":    ("M1001", "0001", "Customer paid for ORD-1004 but I didn't get it", "resolved", "TXN_FAILED"),
    "small_dup": ("M1002", "0002", "ORD-2003 charged twice, ₹1,499", "resolved", "R-21"),
    "risk":      ("M1005", "0005", "Why is my ₹8,000 payout for ORD-5001 on hold?", "escalated", "G-03"),
    "bad_pin":   ("M1001", "1234", "ORD-1001 money not received", "escalated", "G-02"),
    "no_order":  ("M1001", "0001", "My money didn't come", "needs_info", None),
    # Normalized Saaras transcript of demo_assets/case1_tamil.wav, so the voice demo is cached too.
    "case1_voice": ("M1001", "0001", "வணக்கம், என் ஆர்டர் ORD-1001-க்கான ₹2400 பணம் இன்னும் என் வங்கிக் கணக்கிற்கு வரவில்லை.",
                    "resolved", "R-07"),
    # Exactly what POST /events/payout-failed sends for PO-1001.
    "proactive": ("M1001", "", "System event: payout PO-1001 for order ORD-1001 failed (BANK_TIMEOUT).", "resolved", "R-07"),
}

CASES.update({
    # ₹75,000 failed payout: above the ₹50,000 auto limit, so the retry waits for Ops (R-10).
    "big_payout": ("M1004", "0004", "ORD-4002 ₹75,000 payment has not reached my bank account.", "waiting_approval", "R-10"),
    # Case 4: exactly what POST /events/duplicate-payment sends. Pauses for the CUSTOMER (keep/refund).
    "dup_proactive": ("M1006", "", "System event: duplicate payment detected on order ORD-6002 at M1006.",
                      "waiting_customer", "DUPLICATE_CHARGE"),
    "dup_big": ("M1006", "", "System event: duplicate payment detected on order ORD-6004 at M1006.",
                "waiting_customer", "DUPLICATE_CHARGE"),
})

# Extra run_case kwargs for scenarios that don't come from a merchant typing.
_DUP = {"source": "system", "language": "en-IN", "trigger": "duplicate_payment"}
EXTRA_KW = {"proactive": {"source": "system", "language": "ta-IN", "trigger": "payout_failed"},
            "dup_proactive": _DUP, "dup_big": _DUP}
