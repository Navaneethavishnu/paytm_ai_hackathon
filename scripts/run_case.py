"""Run a demo case end to end and print the agent timeline.

    python scripts/run_case.py case1                     # real Sarvam LLM (needs SARVAM_API_KEY)
    python scripts/run_case.py case1 --offline           # no API key: deterministic fallbacks only
    python scripts/run_case.py all --offline             # every scenario
    python scripts/run_case.py case2 --approve priya     # pause for approval, then approve
    python scripts/run_case.py case2 --reject priya      # ... or reject
    python scripts/run_case.py case2                     # pause and exit; resume later (even after restart):
    python scripts/run_case.py resume CASE-XXXX --approve priya
    python scripts/run_case.py custom --mid M1001 --last4 0001 --text "ORD-1002 status?"

The DB and saved cases are reset before each run unless --no-reset (resume never resets).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import audit  # noqa: E402
from app.agent.graph import ApprovalError, decide, get_case, reset_checkpoints, run_case  # noqa: E402
from app.llm import get_llm  # noqa: E402
from app.seed import reset_and_seed  # noqa: E402

from app.demo_cases import CASES, EXTRA_KW  # noqa: E402

COLORS = {"policy": "\033[1;36m", "action": "\033[1;32m", "verify": "\033[32m", "escalate": "\033[1;31m",
          "error": "\033[33m", "signal": "\033[35m", "approval": "\033[1;33m"}
RESET = "\033[0m"


def _short(d: dict) -> str:
    s = json.dumps(d, ensure_ascii=False)
    return s if len(s) <= 160 else s[:157] + "..."


def print_events(case_id: str, after: int = 0) -> int:
    last = after
    for e in audit.events(case_id, after_id=after):
        last = e["id"]
        if e["kind"] == "node" and e["name"] == "start":
            continue
        c = COLORS.get(e["kind"], "")
        print(f"  {c}{e['kind']:<8}{RESET} {e['name']:<24} {_short(e['detail'])}")
    return last


def print_outcome(s: dict):
    pd = s.get("policy_decision") or {}
    print(f"  -> case={s['case_id']}  status={s['status']}  diagnosis={(s.get('diagnosis') or {}).get('code')}"
          f"  rule={pd.get('rule_id')}  ticket={s.get('ticket_id')}")
    print(f"  -> reply: {s['reply']}")
    if s["status"] == "waiting_approval":
        req = s["approval_request"]
        print(f"  -> WAITING FOR OPS. evidence hash={req['hash']}  action={json.dumps(req['pack']['action'])}")


def resolve(case_id: str, decision: str, reviewer: str, llms, after: int = 0):
    s = get_case(case_id)
    try:
        s = decide(case_id, decision, reviewer, s["approval_request"]["hash"], llm=llms[0], reply_llm=llms[1])
    except ApprovalError as e:
        print(f"  !! approval refused: {e}")
        return
    print(f"\n  --- Ops {decision} by {reviewer} ---")
    print_events(case_id, after)
    print_outcome(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case", choices=[*CASES, "all", "custom", "resume"])
    ap.add_argument("case_id", nargs="?", help="for resume")
    ap.add_argument("--offline", action="store_true", help="no LLM calls; deterministic fallbacks")
    ap.add_argument("--no-reset", action="store_true")
    ap.add_argument("--approve", metavar="REVIEWER")
    ap.add_argument("--reject", metavar="REVIEWER")
    ap.add_argument("--mid"); ap.add_argument("--last4"); ap.add_argument("--text")
    a = ap.parse_args()

    llms = (get_llm(offline=a.offline), get_llm(offline=a.offline, purpose="reply"))
    decision = ("approve", a.approve) if a.approve else ("reject", a.reject) if a.reject else None

    if a.case == "resume":
        if not a.case_id or not decision:
            ap.error("resume needs CASE_ID and --approve/--reject REVIEWER")
        before = audit.events(a.case_id)
        resolve(a.case_id, *decision, llms, after=before[-1]["id"] if before else 0)
        return

    for n in (list(CASES) if a.case == "all" else [a.case]):
        if not a.no_reset:
            reset_and_seed()
            reset_checkpoints()
        mid, last4, text = (a.mid, a.last4, a.text) if n == "custom" else CASES[n][:3]
        print(f"\n=== {n}: {mid}  \"{text}\"")
        s = run_case(text, mid, last4, llm=llms[0], reply_llm=llms[1], **EXTRA_KW.get(n, {}))
        last = print_events(s["case_id"])
        print_outcome(s)
        if s["status"] == "waiting_approval" and decision:
            resolve(s["case_id"], *decision, llms, after=last)


if __name__ == "__main__":
    main()
