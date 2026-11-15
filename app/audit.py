"""Audit log: every node, tool call, policy decision and action lands in AuditEvent.

PII is masked BEFORE it is written, so the timeline, tickets and logs never hold
raw phone numbers or customer UPI IDs.
"""
import re
from typing import Any

from app.db import session_scope
from app.models import AuditEvent

_VPA = re.compile(r"\b([A-Za-z0-9._-]{1,64})@([A-Za-z]{2,32})\b")
# 10-digit mobile -> ******1234. (?<!\w) so IDs like UTR2064451642 are NOT masked.
_PHONE = re.compile(r"(?<!\w)(\d{6})(\d{4})(?!\d)")
_PII_KEYS = {"phone", "customerVpa", "customer_vpa"}


def mask_text(s: str) -> str:
    s = _VPA.sub(lambda m: m.group(1)[:2] + "***@" + m.group(2), s)
    return _PHONE.sub(lambda m: "******" + m.group(2), s)


def mask(obj: Any) -> Any:
    """Recursively mask PII in dicts/lists/strings."""
    if isinstance(obj, dict):
        return {k: ("***" if k in _PII_KEYS and obj[k] else mask(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [mask(v) for v in obj]
    if isinstance(obj, str):
        return mask_text(obj)
    return obj


def log(case_id: str, kind: str, name: str, detail: Any = None) -> None:
    """kind: node | tool | policy | approval | action | verify | escalate | error"""
    with session_scope() as s:
        s.add(AuditEvent(case_id=case_id, kind=kind, name=name, detail=mask(detail or {})))


def events(case_id: str, after_id: int = 0) -> list[dict]:
    with session_scope() as s:
        rows = (s.query(AuditEvent).filter(AuditEvent.case_id == case_id, AuditEvent.id > after_id)
                .order_by(AuditEvent.id).all())
        return [{"id": r.id, "ts": r.ts.isoformat(), "kind": r.kind, "name": r.name, "detail": r.detail} for r in rows]
