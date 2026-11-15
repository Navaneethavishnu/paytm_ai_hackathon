"""Deterministic policy gate: 'the LLM proposes, the policy engine disposes'.

Plain Python, no model calls. Given a proposed action and the case's signals,
it returns auto / approval / escalate plus the rule ID that decided it.
That rule ID is logged and shown on the agent timeline.

Signals come in two kinds, both set ONLY by deterministic code, never by the LLM:
  - guard signals (ownership_mismatch, risk_flag, ...) block everything;
  - evidence signals (duplicate_verified, ...) are required by some rules.
"""
import math
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Literal

import yaml

from app.config import get_settings

Tier = Literal["auto", "approval", "escalate"]
TIERS = {"auto", "approval", "escalate"}
KNOWN_CONDITIONS = {"max_amount", "min_amount", "max_prior_retries", "failure_reason_in", "requires_signals"}


@dataclass
class ProposedAction:
    type: str                         # e.g. "retry_payout", "refund_duplicate"
    amount: float = 0.0
    prior_retries: int = 0
    failure_reason: str = ""
    params: dict | None = None        # passed through to the executor untouched


@dataclass
class Decision:
    tier: Tier
    rule_id: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def validate_policy(policy: dict) -> dict:
    """Fail at load time, not mid-demo: every rule must be well-formed."""
    seen: set[str] = set()

    def _id(rid: str):
        if rid in seen:
            raise ValueError(f"Duplicate policy id: {rid}")
        seen.add(rid)

    for g in policy.get("global_guards", []):
        for k in ("id", "signal", "reason"):
            if k not in g:
                raise ValueError(f"Global guard missing '{k}': {g}")
        _id(g["id"])

    for action, rules in (policy.get("actions") or {}).items():
        if not rules:
            raise ValueError(f"Action '{action}' has no rules")
        for r in rules:
            for k in ("id", "tier", "reason"):
                if k not in r:
                    raise ValueError(f"Rule in '{action}' missing '{k}': {r}")
            _id(r["id"])
            if r["tier"] not in TIERS:
                raise ValueError(f"Rule {r['id']}: unknown tier '{r['tier']}'")
            unknown = set(r.get("when") or {}) - KNOWN_CONDITIONS
            if unknown:
                raise ValueError(f"Rule {r['id']}: unknown condition(s) {sorted(unknown)}")
        if rules[-1].get("when"):
            raise ValueError(f"Action '{action}': last rule must be a catch-all with no 'when'")
    return policy


@lru_cache
def load_policy(path: str | None = None) -> dict:
    with open(path or get_settings().policy_file, encoding="utf-8") as f:
        return validate_policy(yaml.safe_load(f))


def _matches(when: dict, a: ProposedAction, signals: set[str]) -> bool:
    when = when or {}
    unknown = set(when) - KNOWN_CONDITIONS
    if unknown:  # checked before evaluating, so a typo can't hide behind a failing condition
        raise ValueError(f"Unknown policy condition(s): {sorted(unknown)}")
    for key, val in when.items():
        if key == "max_amount" and not a.amount <= val:
            return False
        if key == "min_amount" and not a.amount >= val:
            return False
        if key == "max_prior_retries" and not a.prior_retries <= val:
            return False
        if key == "failure_reason_in" and a.failure_reason not in val:
            return False
        if key == "requires_signals" and not set(val) <= signals:
            return False
    return True


def evaluate(action: ProposedAction, signals: set[str], policy: dict | None = None) -> Decision:
    policy = validate_policy(policy) if policy is not None else load_policy()
    signals = set(signals)

    for g in policy.get("global_guards", []):
        if g["signal"] in signals:
            return Decision("escalate", g["id"], g["reason"])

    if not math.isfinite(action.amount) or action.amount < 0 or action.prior_retries < 0:
        return Decision("escalate", "R-00", "Proposed action has an invalid amount or retry count")

    rules = policy.get("actions", {}).get(action.type)
    if not rules:
        return Decision("escalate", "R-00", f"Action '{action.type}' is not in the policy")

    for r in rules:
        if _matches(r.get("when"), action, signals):
            return Decision(r["tier"], r["id"], r["reason"])

    return Decision("escalate", "R-00", "No policy rule matched")  # fail closed
