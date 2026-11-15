"""Mock 'Paytm-like' systems. SYNTHETIC ONLY: no real Paytm APIs are called.

Response shapes for payment status and refunds are modelled on Paytm Payment
Gateway's public API contracts (orderId, txnId, refId, resultInfo.resultStatus),
so a real adapter can replace these functions later without changing the agent.

Safety properties live here, at the tool layer, not in the LLM:
  1. Ownership: every tool takes the requesting `mid` and refuses records that
     belong to another merchant, revealing nothing about them.
  2. Idempotency: payout retries and refunds carry a unique key, so a
     repeated call can never move money twice. Reusing a key for a different
     request is rejected.
  3. Refund limits: amount must be positive, and the total refunded on a
     payment can never exceed what the customer paid.
  4. Identity: exactly 4 ASCII digits, and the merchant is locked after
     MAX_VERIFY_ATTEMPTS wrong tries.
"""
import math
import random
import uuid
from datetime import timedelta

from app.config import get_settings
from app.db import session_scope
from app.models import Merchant, Payout, Refund, RiskFlag, Ticket, Transaction


class ToolError(Exception):
    """Raised when a mock system is 'down'. The agent retries, then escalates."""


# Tests can force a named tool to fail: FORCED_FAILURES.add("get_payment_status")
FORCED_FAILURES: set[str] = set()

# Identity lockout. In-memory is enough for the demo; a real system would persist it.
MAX_VERIFY_ATTEMPTS = 3
_VERIFY_FAILURES: dict[str, int] = {}


def reset_runtime_state():
    """Clear forced failures and lockouts (called by seed / demo reset / tests)."""
    FORCED_FAILURES.clear()
    _VERIFY_FAILURES.clear()


def _maybe_fail(tool: str):
    if tool in FORCED_FAILURES or random.random() < get_settings().mock_failure_rate:
        raise ToolError(f"{tool}: upstream system unavailable (simulated)")


def _result(status: str, code: str, msg: str) -> dict:
    return {"resultStatus": status, "resultCode": code, "resultMsg": msg}


_NOT_YOURS = ("OWNERSHIP_MISMATCH", "403", "Record does not belong to this merchant")


# ---------------- Merchant ----------------
def get_merchant(mid: str) -> dict:
    _maybe_fail("get_merchant")
    with session_scope() as s:
        m = s.get(Merchant, mid)
        if not m:
            return {"found": False, "mid": mid}
        return {"found": True, "mid": m.mid, "name": m.name, "language": m.language,
                "bank_account": m.bank_account_masked, "city": m.city}


def verify_merchant(mid: str, phone_last4: str) -> dict:
    """Mock identity check. Real life would be OTP / app session.

    Guardrails: the input must be exactly 4 ASCII digits (an empty string used to
    match every phone via str.endswith), and MAX_VERIFY_ATTEMPTS wrong tries lock
    the merchant so the 10,000 combinations can't be brute-forced.
    """
    _maybe_fail("verify_merchant")
    if _VERIFY_FAILURES.get(mid, 0) >= MAX_VERIFY_ATTEMPTS:
        return {"mid": mid, "verified": False, "locked": True}
    valid = isinstance(phone_last4, str) and len(phone_last4) == 4 and phone_last4.isascii() and phone_last4.isdigit()
    with session_scope() as s:
        m = s.get(Merchant, mid)
        ok = bool(m) and valid and m.phone[-4:] == phone_last4
    if ok:
        _VERIFY_FAILURES.pop(mid, None)
    else:
        _VERIFY_FAILURES[mid] = _VERIFY_FAILURES.get(mid, 0) + 1
    return {"mid": mid, "verified": ok, "locked": _VERIFY_FAILURES.get(mid, 0) >= MAX_VERIFY_ATTEMPTS}


# ---------------- Payments ----------------
def _txn_body(t: Transaction) -> dict:
    return {
        "resultInfo": _result(t.status, "01" if t.status == "TXN_SUCCESS" else "227" if t.status == "TXN_FAILURE" else "402",
                              {"TXN_SUCCESS": "Txn Success", "TXN_FAILURE": "Txn Failed", "PENDING": "Txn Pending"}[t.status]),
        "txnId": t.txn_id, "orderId": t.order_id, "txnAmount": f"{t.amount:.2f}",
        "txnDate": t.created_at.isoformat(sep=" "), "paymentMode": t.payment_mode,
        "customerVpa": t.customer_vpa, "merchantInvoice": t.merchant_invoice,
    }


def get_payment_status(order_id: str, mid: str) -> dict:
    """Look up a payment, but only if it belongs to the requesting merchant."""
    _maybe_fail("get_payment_status")
    with session_scope() as s:
        t = s.query(Transaction).filter_by(order_id=order_id).one_or_none()
        if t is None:
            return {"body": {"resultInfo": _result("NOT_FOUND", "334", "Invalid Order Id"), "orderId": order_id}}
        if t.mid != mid:
            # Deliberately reveal nothing about the transaction.
            return {"body": {"resultInfo": _result(*_NOT_YOURS), "orderId": order_id}}
        return {"body": _txn_body(t)}


def find_duplicate_payments(mid: str, order_id: str, window_seconds: int = 600) -> dict:
    """Deterministic duplicate check: same customer, amount and invoice within a window."""
    _maybe_fail("find_duplicate_payments")
    with session_scope() as s:
        t = s.query(Transaction).filter_by(order_id=order_id, mid=mid).one_or_none()
        if t is None:
            return {"orderId": order_id, "duplicates": []}
        lo, hi = t.created_at - timedelta(seconds=window_seconds), t.created_at + timedelta(seconds=window_seconds)
        rows = (s.query(Transaction)
                .filter(Transaction.mid == mid, Transaction.customer_vpa == t.customer_vpa,
                        Transaction.amount == t.amount, Transaction.status == "TXN_SUCCESS",
                        Transaction.created_at.between(lo, hi), Transaction.txn_id != t.txn_id))
        dups = [r for r in rows if not t.merchant_invoice or r.merchant_invoice == t.merchant_invoice]
        return {"orderId": order_id, "duplicates": [_txn_body(d) for d in dups]}


def list_recent_transactions(mid: str, since_hours: int = 48, amount: float | None = None,
                             limit: int = 5) -> dict:
    """The merchant's own recent payments, newest first, so they can pick an order instead of typing it.
    If an amount is given and some payments match it, only those are returned. No customer VPA (PII)."""
    _maybe_fail("list_recent_transactions")
    from app.clock import now
    hi = now()
    lo = hi - timedelta(hours=since_hours)
    with session_scope() as s:
        rows = (s.query(Transaction)
                .filter(Transaction.mid == mid, Transaction.created_at.between(lo, hi))
                .order_by(Transaction.created_at.desc(), Transaction.txn_id.desc()).all())
        if amount is not None and math.isfinite(amount):
            matching = [r for r in rows if abs(r.amount - amount) < 0.005]
            rows = matching or rows
        return {"transactions": [{"orderId": r.order_id, "txnAmount": f"{r.amount:.2f}",
                                  "txnDate": r.created_at.isoformat(sep=" "), "status": r.status}
                                 for r in rows[:limit]]}


# ---------------- Settlement ----------------
def _payout_dict(p: Payout) -> dict:
    return {"payoutId": p.payout_id, "status": p.status, "amount": f"{p.amount:.2f}",
            "failureReason": p.failure_reason, "retryCount": p.retry_count,
            "utr": p.utr, "expectedDate": p.expected_date.isoformat(sep=" ")}


def get_settlement_for_txn(mid: str, txn_id: str) -> dict:
    _maybe_fail("get_settlement_for_txn")
    with session_scope() as s:
        for p in s.query(Payout).filter_by(mid=mid):
            if txn_id in p.txn_ids:
                return {"txnId": txn_id, "found": True, "payout": _payout_dict(p)}
        return {"txnId": txn_id, "found": False}


def retry_payout(mid: str, payout_id: str, idempotency_key: str) -> dict:
    """ACTION. Re-queues a failed payout. Same key twice = no second retry.
    Ownership is checked first, so another merchant's payout can never be touched."""
    _maybe_fail("retry_payout")
    if not idempotency_key:
        return {"accepted": False, "reason": "IDEMPOTENCY_KEY_REQUIRED"}
    with session_scope() as s:
        p = s.get(Payout, payout_id)
        if p is None:
            return {"accepted": False, "reason": "PAYOUT_NOT_FOUND"}
        if p.mid != mid:
            return {"accepted": False, "reason": "OWNERSHIP_MISMATCH"}
        if p.last_idempotency_key == idempotency_key:
            return {"accepted": True, "duplicate_request": True, "payout": _payout_dict(p)}
        if p.status != "FAILED":
            return {"accepted": False, "reason": f"PAYOUT_NOT_RETRYABLE_{p.status}"}
        p.status, p.retry_count, p.last_idempotency_key = "PROCESSING", p.retry_count + 1, idempotency_key
        return {"accepted": True, "duplicate_request": False, "payout": _payout_dict(p)}


def get_payout_status(mid: str, payout_id: str) -> dict:
    """Simulates the bank: a PROCESSING payout succeeds on the next status check."""
    _maybe_fail("get_payout_status")
    with session_scope() as s:
        p = s.get(Payout, payout_id)
        if p is None:
            return {"found": False, "payoutId": payout_id, "reason": "NOT_FOUND"}
        if p.mid != mid:
            return {"found": False, "payoutId": payout_id, "reason": "OWNERSHIP_MISMATCH"}
        if p.status == "PROCESSING":
            p.status, p.failure_reason = "SUCCESS", ""
            p.utr = "UTR" + uuid.uuid4().hex[:10].upper()
        return {"found": True, "payout": _payout_dict(p)}


# ---------------- Refunds ----------------
def _refund_dict(r: Refund) -> dict:
    return {"refundId": r.refund_id, "refId": r.ref_id, "orderId": r.order_id, "txnId": r.txn_id,
            "refundAmount": f"{r.amount:.2f}", "resultInfo": _result(r.status, "601" if r.status == "PENDING" else "10",
                                                                       "Refund pending" if r.status == "PENDING" else "Refund successful")}


def _refund_rejected(code: str, msg: str) -> dict:
    return {"body": {"resultInfo": _result("TXN_FAILURE", code, msg)}}


def initiate_refund(mid: str, order_id: str, txn_id: str, amount: float, ref_id: str) -> dict:
    """ACTION. ref_id must be unique; a repeat returns the existing refund, never a new one.

    Guardrails: positive finite amount only; a ref_id reused for a different request
    (or by another merchant) is rejected; and the total of all refunds on a payment
    can never exceed what the customer paid, even across different cases/keys.
    """
    _maybe_fail("initiate_refund")
    if not ref_id:
        return _refund_rejected("600", "refId is required")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0:
        return _refund_rejected("608", "Refund amount must be a positive number")
    amount = round(float(amount), 2)
    with session_scope() as s:
        existing = s.query(Refund).filter_by(ref_id=ref_id).one_or_none()
        if existing:
            if existing.mid != mid:
                return {"body": {"resultInfo": _result(*_NOT_YOURS)}}
            if (existing.order_id, existing.txn_id, existing.amount) != (order_id, txn_id, amount):
                return _refund_rejected("609", "refId already used for a different refund")
            return {"body": _refund_dict(existing), "duplicate_request": True}
        t = s.query(Transaction).filter_by(order_id=order_id, txn_id=txn_id, mid=mid).one_or_none()
        if t is None or t.status != "TXN_SUCCESS":
            return _refund_rejected("607", "Refund not allowed for this transaction")
        already = sum(r.amount for r in s.query(Refund).filter(Refund.txn_id == txn_id, Refund.status != "TXN_FAILURE"))
        if round(already + amount, 2) > round(t.amount, 2):
            return _refund_rejected("617", "Refund exceeds the remaining refundable amount")
        r = Refund(refund_id="RF" + uuid.uuid4().hex[:10].upper(), ref_id=ref_id, mid=mid, order_id=order_id,
                   txn_id=txn_id, amount=amount, status="PENDING")
        s.add(r)
        s.flush()
        return {"body": _refund_dict(r), "duplicate_request": False}


def get_refund_status(mid: str, ref_id: str) -> dict:
    """Refunds are asynchronous: PENDING first, success after a status poll."""
    _maybe_fail("get_refund_status")
    with session_scope() as s:
        r = s.query(Refund).filter_by(ref_id=ref_id).one_or_none()
        if r is None:
            return {"body": {"resultInfo": _result("NOT_FOUND", "631", "Refund not found"), "refId": ref_id}}
        if r.mid != mid:
            return {"body": {"resultInfo": _result(*_NOT_YOURS), "refId": ref_id}}
        r.polls += 1
        if r.status == "PENDING" and r.polls >= 1:
            r.status = "TXN_SUCCESS"
        return {"body": _refund_dict(r)}


# ---------------- Risk & tickets ----------------
def get_risk_flags(mid: str) -> dict:
    _maybe_fail("get_risk_flags")
    with session_scope() as s:
        return {"mid": mid, "flags": [f.flag for f in s.query(RiskFlag).filter_by(mid=mid)]}


def create_ticket(mid: str, case_id: str, category: str, summary: str) -> dict:
    _maybe_fail("create_ticket")
    with session_scope() as s:
        t = Ticket(ticket_id="TCK" + uuid.uuid4().hex[:8].upper(), mid=mid, case_id=case_id,
                   category=category, summary=summary, status="OPEN")
        s.add(t)
        return {"ticketId": t.ticket_id, "status": t.status}


def get_ticket(mid: str, ticket_id: str) -> dict:
    with session_scope() as s:
        t = s.get(Ticket, ticket_id)
        if t is None or t.mid != mid:   # same answer either way: reveal nothing
            return {"found": False, "ticketId": ticket_id, "status": None}
        return {"found": True, "ticketId": ticket_id, "status": t.status}
