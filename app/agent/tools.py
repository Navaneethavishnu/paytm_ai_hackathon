"""Tool layer between the agent and the mock systems.

Guardrails enforced here (not in the prompt):
  - The LLM only ever sees READ-ONLY tools, and their schemas have no `mid`.
    The wrapper injects the verified `mid` from case state; any `mid` (or other
    unexpected arg) the model sends is dropped and logged.
  - Args are validated (known names, short ID-like strings only).
  - Every call is retried 2x with backoff. Each ToolError counts toward
    `tool_failures`; at 3 the `repeated_tool_failure` signal is set and no
    further tools are called (policy guard G-05 then escalates).
  - Signals are derived from tool RESULTS by code, never from model text.
"""
import json
import re
import time
from typing import Any, Callable

from app import audit
from app import mock_systems as ms
from app.config import get_settings

MAX_ATTEMPTS = 3                  # 1 try + 2 retries
FAILURE_LIMIT = 3                 # per case -> repeated_tool_failure
_ARG_OK = re.compile(r"^[A-Za-z0-9:_.-]{1,64}$")


def _spec(name: str, desc: str, params: dict[str, str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object",
                       "properties": {k: {"type": "string", "description": d} for k, d in params.items()},
                       "required": list(params)}}}


# name -> (schema shown to the LLM, function taking the INJECTED mid first)
READ_TOOLS: dict[str, tuple[dict, Callable[..., dict]]] = {
    "get_payment_status": (
        _spec("get_payment_status", "Payment status of an order for this merchant.", {"order_id": "e.g. ORD-1001"}),
        lambda mid, order_id: ms.get_payment_status(order_id, mid)),
    "find_duplicate_payments": (
        _spec("find_duplicate_payments", "Find other successful payments by the same customer, same amount and invoice within 10 minutes.", {"order_id": "e.g. ORD-2001"}),
        lambda mid, order_id: ms.find_duplicate_payments(mid, order_id)),
    "get_settlement_for_txn": (
        _spec("get_settlement_for_txn", "Find the payout (settlement to the merchant's bank) that contains a transaction.", {"txn_id": "e.g. TXN1001"}),
        lambda mid, txn_id: ms.get_settlement_for_txn(mid, txn_id)),
    "get_payout_status": (
        _spec("get_payout_status", "Current status of a payout.", {"payout_id": "e.g. PO-1001"}),
        lambda mid, payout_id: ms.get_payout_status(mid, payout_id)),
    "get_refund_status": (
        _spec("get_refund_status", "Status of a refund by its refId.", {"ref_id": "refund reference id"}),
        lambda mid, ref_id: ms.get_refund_status(mid, ref_id)),
    "get_risk_flags": (
        _spec("get_risk_flags", "Open risk or fraud flags on this merchant's account.", {}),
        lambda mid: ms.get_risk_flags(mid)),
}
LLM_TOOL_SPECS = [spec for spec, _ in READ_TOOLS.values()]


class Ctx:
    """Mutable working copy of the bits of state a node changes; `.updates()` returns them."""

    def __init__(self, state: dict):
        self.case_id = state["case_id"]
        self.mid = state["mid"]
        self.evidence = json.loads(json.dumps(state.get("evidence") or {}))
        self.signals = list(state.get("signals") or [])
        self.tool_failures = int(state.get("tool_failures") or 0)

    def signal(self, name: str):
        if name not in self.signals:
            self.signals.append(name)
            audit.log(self.case_id, "signal", name)

    @property
    def tools_down(self) -> bool:
        return "repeated_tool_failure" in self.signals

    def updates(self) -> dict:
        return {"evidence": self.evidence, "signals": self.signals, "tool_failures": self.tool_failures}


def _derive_signals(ctx: Ctx, name: str, result: dict):
    if "OWNERSHIP_MISMATCH" in json.dumps(result):
        ctx.signal("ownership_mismatch")
    if name == "get_risk_flags" and result.get("flags"):
        ctx.signal("risk_flag")


def call(ctx: Ctx, name: str, fn: Callable[[], dict], *, kind: str = "tool",
         args: dict | None = None, evidence_key: str | None = None) -> dict | None:
    """Run one tool with retries. Returns the result, or None if the system stayed down."""
    if ctx.tools_down:
        audit.log(ctx.case_id, "error", name, {"skipped": "repeated_tool_failure already set"})
        return None
    backoff = get_settings().tool_retry_backoff
    for attempt in range(MAX_ATTEMPTS):
        try:
            result = fn()
        except ms.ToolError as e:
            ctx.tool_failures += 1
            audit.log(ctx.case_id, "error", name, {"attempt": attempt + 1, "error": str(e)})
            if ctx.tool_failures >= FAILURE_LIMIT:
                ctx.signal("repeated_tool_failure")
                return None
            if attempt < MAX_ATTEMPTS - 1 and backoff:
                time.sleep(backoff * (2 ** attempt))
            continue
        audit.log(ctx.case_id, kind, name, {"args": args or {}, "result": result})
        _derive_signals(ctx, name, result)
        if evidence_key is not None:
            ctx.evidence.setdefault(name, {})[evidence_key] = result
        return result
    return None


def call_read_tool(ctx: Ctx, name: str, raw_args: dict) -> dict:
    """Execute a tool call requested by the LLM. Always returns something to show the model."""
    if name not in READ_TOOLS:
        audit.log(ctx.case_id, "error", name, {"rejected": "not an allowed read-only tool", "args": raw_args})
        return {"error": f"Tool '{name}' is not available. Only read-only tools are allowed."}
    spec, fn = READ_TOOLS[name]
    allowed = spec["function"]["parameters"]["properties"]
    ignored = sorted(set(raw_args) - set(allowed))
    if ignored:
        audit.log(ctx.case_id, "error", name, {"ignored_args": ignored,
                                               "note": "mid comes from verified case state, not the model"})
    args = {}
    for k in allowed:
        v = raw_args.get(k)
        if not isinstance(v, str) or not _ARG_OK.match(v):
            audit.log(ctx.case_id, "error", name, {"rejected": f"invalid argument {k}", "args": raw_args})
            return {"error": f"Invalid or missing argument '{k}'."}
        args[k] = v
    key = next(iter(args.values()), "_")
    result = call(ctx, name, lambda: fn(ctx.mid, **args), args=args, evidence_key=key)
    return result if result is not None else {"error": "System unavailable, try later."}


def read(ctx: Ctx, name: str, **args: Any) -> dict | None:
    """Deterministic (code-chosen) read, reusing evidence if we already have it."""
    key = next(iter(args.values()), "_")
    if key in ctx.evidence.get(name, {}):
        return ctx.evidence[name][key]
    _, fn = READ_TOOLS[name]
    return call(ctx, name, lambda: fn(ctx.mid, **args), args=args, evidence_key=key)
