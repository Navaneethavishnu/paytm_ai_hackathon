"""Tables for the mock 'Paytm-like' systems plus the agent's audit log.

Each table stands in for a separate real system (payments, settlement,
refunds, risk, ticketing). Keeping them separate lets the agent genuinely
reconcile across systems, which is the whole point of the demo.
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Merchant(Base):
    __tablename__ = "merchants"
    mid: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    phone: Mapped[str] = mapped_column(String)        # used for mock identity check
    language: Mapped[str] = mapped_column(String, default="en-IN")
    bank_account_masked: Mapped[str] = mapped_column(String)
    city: Mapped[str] = mapped_column(String, default="Chennai")


class Transaction(Base):
    """Payment system. Fields modelled on Paytm PG's transaction-status response."""
    __tablename__ = "transactions"
    txn_id: Mapped[str] = mapped_column(String, primary_key=True)
    order_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    mid: Mapped[str] = mapped_column(ForeignKey("merchants.mid"))
    amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String)        # TXN_SUCCESS | TXN_FAILURE | PENDING
    customer_vpa: Mapped[str] = mapped_column(String)
    merchant_invoice: Mapped[str] = mapped_column(String, default="")
    payment_mode: Mapped[str] = mapped_column(String, default="UPI")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Payout(Base):
    """Settlement system: money moving from Paytm to the merchant's bank."""
    __tablename__ = "payouts"
    payout_id: Mapped[str] = mapped_column(String, primary_key=True)
    mid: Mapped[str] = mapped_column(ForeignKey("merchants.mid"))
    txn_ids: Mapped[list] = mapped_column(JSON)
    amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String)        # SCHEDULED | PROCESSING | SUCCESS | FAILED | ON_HOLD
    failure_reason: Mapped[str] = mapped_column(String, default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    utr: Mapped[str] = mapped_column(String, default="")
    last_idempotency_key: Mapped[str] = mapped_column(String, default="")
    expected_date: Mapped[datetime] = mapped_column(DateTime)


class Refund(Base):
    """Refund system. ref_id is the merchant-side unique key: duplicates are rejected."""
    __tablename__ = "refunds"
    refund_id: Mapped[str] = mapped_column(String, primary_key=True)
    ref_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    mid: Mapped[str] = mapped_column(String, index=True)   # owner, for ownership checks
    order_id: Mapped[str] = mapped_column(String)
    txn_id: Mapped[str] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String)        # PENDING | TXN_SUCCESS | TXN_FAILURE
    polls: Mapped[int] = mapped_column(Integer, default=0)


class RiskFlag(Base):
    __tablename__ = "risk_flags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mid: Mapped[str] = mapped_column(String, index=True)
    flag: Mapped[str] = mapped_column(String)
    note: Mapped[str] = mapped_column(String, default="")


class Ticket(Base):
    __tablename__ = "tickets"
    ticket_id: Mapped[str] = mapped_column(String, primary_key=True)
    mid: Mapped[str] = mapped_column(String)
    case_id: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditEvent(Base):
    """Every node, tool call, policy decision and approval lands here."""
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    kind: Mapped[str] = mapped_column(String)          # node | tool | policy | approval | action | verify | escalate
    name: Mapped[str] = mapped_column(String)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
