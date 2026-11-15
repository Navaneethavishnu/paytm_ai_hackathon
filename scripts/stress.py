"""Demo hardening: run every scenario N times in a row and check outcomes + money safety.

    python scripts/stress.py                    # offline, 10x each, must be 100% expected
    python scripts/stress.py --live             # real Sarvam (set DEMO_MODE=true to use/warm the cache)
    python scripts/stress.py --chaos 0.2        # tools fail 20% of the time: must never crash,
                                                # never move money twice; escalation is acceptable
Exit code 1 if anything is wrong.
"""
import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import mock_systems as ms  # noqa: E402
from app.agent.graph import customer_decide, decide, reset_checkpoints, run_case  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.demo_cases import CASES, EXTRA_KW  # noqa: E402
from app.llm import get_llm  # noqa: E402
from app.models import Payout, Refund  # noqa: E402
from app.seed import reset_and_seed  # noqa: E402


def money_safety_problems() -> list[str]:
    """Invariants that must hold after ANY run, chaos or not."""
    out = []
    with session_scope() as s:
        per_txn = Counter(r.txn_id for r in s.query(Refund))
        out += [f"{t} refunded {n} times" for t, n in per_txn.items() if n > 1]
        out += [f"{p.payout_id} retried {p.retry_count} times" for p in s.query(Payout) if p.retry_count > 1]
    return out


def run_one(name: str, llms) -> tuple[str, str | None, str]:
    mid, pin, text, _, _ = CASES[name]
    s = run_case(text, mid, pin, llm=llms[0], reply_llm=llms[1], **EXTRA_KW.get(name, {}))
    first = s["status"]
    if s["status"] == "waiting_customer":            # Case 4: the customer says "refund one"
        key = (s.get("diagnosis") or {}).get("code")
        s = customer_decide(s["case_id"], "refund", s["customer_ask"]["hash"], token=s["customer_ask"]["token"],
                            llm=llms[0], reply_llm=llms[1])
        if s["status"] == "waiting_approval":        # big refund: Ops approves too
            s = decide(s["case_id"], "approve", "stress-bot", s["approval_request"]["hash"], llm=llms[0], reply_llm=llms[1])
        return first, key, s["status"]
    if s["status"] == "waiting_approval":
        s2 = decide(s["case_id"], "approve", "stress-bot", s["approval_request"]["hash"], llm=llms[0], reply_llm=llms[1])
        return s["status"], (s.get("policy_decision") or {}).get("rule_id"), s2["status"]
    key = (s.get("policy_decision") or {}).get("rule_id") or (s.get("diagnosis") or {}).get("code")
    return s["status"], key, s["status"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--chaos", type=float, default=0.0, help="MOCK_FAILURE_RATE during the run")
    ap.add_argument("cases", nargs="*", default=list(CASES))
    a = ap.parse_args()

    settings = get_settings()
    settings.tool_retry_backoff = 0.0 if not a.live else settings.tool_retry_backoff
    llms = (get_llm(offline=not a.live), get_llm(offline=not a.live, purpose="reply"))
    bad, timings = [], {}
    for name in a.cases:
        exp_status, exp_key = CASES[name][3], CASES[name][4]
        got, t0 = Counter(), time.time()
        for i in range(a.n):
            reset_and_seed()
            reset_checkpoints()
            settings.mock_failure_rate = a.chaos
            try:
                status, key, final = run_one(name, llms)
            except Exception as e:  # a crash is always a failure
                status, key, final = f"CRASH {type(e).__name__}: {e}", None, "crash"
            finally:
                settings.mock_failure_rate = 0.0
                ms.FORCED_FAILURES.clear()
            got[(status, key)] += 1
            problems = money_safety_problems()
            if problems:
                bad.append(f"{name} run {i + 1}: MONEY SAFETY {problems}")
            expected = status == exp_status and (exp_key is None or key == exp_key)
            if status.startswith("CRASH"):
                bad.append(f"{name} run {i + 1}: {status}")
            elif not expected and not (a.chaos and status == "escalated"):
                bad.append(f"{name} run {i + 1}: got {status}/{key}, expected {exp_status}/{exp_key}")
        timings[name] = (time.time() - t0) / a.n
        summary = ", ".join(f"{s}/{k} x{n}" for (s, k), n in got.most_common())
        print(f"{name:<10} {timings[name]:5.2f}s/run  {summary}")

    mode = f"{'live' if a.live else 'offline'}{', DEMO_MODE cache' if settings.demo_mode and a.live else ''}" \
           f"{f', chaos {a.chaos:.0%}' if a.chaos else ''}"
    total = a.n * len(a.cases)
    print(f"\n{total - len(bad)}/{total} runs OK ({mode})")
    for b in bad[:30]:
        print("  FAIL", b)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
