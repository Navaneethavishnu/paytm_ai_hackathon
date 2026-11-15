"""CaseState: everything the agent knows about one case.

Plain JSON-friendly types only (lists, not sets) so the Step 3 SQLite
checkpointer can save and resume it.
"""
from typing import Literal, TypedDict

Status = Literal["open", "needs_info", "waiting_approval", "waiting_customer", "resolved", "escalated"]


class CaseState(TypedDict, total=False):
    case_id: str
    messages: list[dict]            # [{"role": "merchant"|"agent", "content": str}]
    mid: str
    phone_last4: str                # used once by verify_merchant; never logged
    merchant_verified: bool
    merchant: dict                  # profile from get_merchant (language, masked bank)
    intent: str
    order_id: str | None
    claimed_amount: float | None
    order_choices: list[dict] | None  # no order ID given: merchant's own recent payments to tap (from a tool)
    language: str

    evidence: dict                  # {tool_name: {arg_key: result}} - only tool results, never LLM text
    signals: list[str]              # guard + evidence signals, set only by code
    tool_failures: int
    llm_tool_calls: int

    diagnosis: dict                 # {"code", "summary", "data"}
    proposed_action: dict | None    # ProposedAction as dict
    policy_decision: dict | None    # Decision as dict
    approval_request: dict | None   # {"pack": evidence pack shown to Ops, "hash": its sha256 prefix}
    approval: dict | None           # {"decision": approve|reject|invalid, "reviewer", "evidence_hash"}
    action_result: dict | None
    verification: dict | None       # {"ok": bool, ...}
    escalation_reason: str | None
    ticket_id: str | None

    source: str                     # "merchant" (chat/voice) | "system" (proactive event)
    trigger: str | None             # system cases: "payout_failed" | "duplicate_payment"
    # Case 4 (proactive duplicate): the CUSTOMER decides keep/refund; money never moves without consent.
    customer_vpa: str | None        # payer, from evidence (never logged unmasked)
    customer_ask: dict | None       # {"question", "token", "hash", "pack"} - token is the customer's one-time key
    customer_decision: dict | None  # {"decision": keep|refund|no_response}
    customer_messages: list[dict]   # notifications shown on the customer's phone
    citation: dict | None           # {"doc", "title", "text"} from kb/ - explanation only
    status: Status
    reply: str
