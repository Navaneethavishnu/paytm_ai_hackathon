"""Step 7: DEMO_MODE cache replays identical runs without calling the model."""
import json

import pytest
from langchain_core.messages import AIMessage

from app import mock_systems as ms
from app.agent.graph import reset_checkpoints, run_case
from app.agent.nodes import IntakeResult
from app.config import get_settings
from app.db import init_engine
from app.llm import CachingLLM
from app.seed import reset_and_seed


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    init_engine(f"sqlite:///{tmp_path}/test.db")
    reset_and_seed()
    monkeypatch.setattr(get_settings(), "tool_retry_backoff", 0.0)
    CachingLLM._DATA.clear()
    CachingLLM._LOADED.clear()
    yield
    ms.reset_runtime_state()


class CountingLLM:
    """Deterministic fake 'live' model that counts every call."""

    def __init__(self):
        self.calls = 0

    def with_structured_output(self, schema, **kw):
        outer = self

        class _S:
            def invoke(self, msgs, **k):
                outer.calls += 1
                return IntakeResult(intent="missing_payout", order_id="ORD-1001", claimed_amount=2400, language="ta-IN")
        return _S()

    def bind_tools(self, tools, **kw):
        outer = self

        class _B:
            def invoke(self, msgs, **k):
                outer.calls += 1
                if not any(getattr(m, "type", "") == "tool" for m in msgs):
                    return AIMessage(content="", tool_calls=[{"name": "get_payment_status", "args": {"order_id": "ORD-1001"},
                                                              "id": "call_1", "type": "tool_call"}])
                return AIMessage(content="done")
        return _B()

    def invoke(self, msgs, **kw):
        self.calls += 1
        return AIMessage(content="உங்கள் {order_id} ₹{amount} {bank_account} UTR {utr}")


def _run(agent, reply):
    return run_case("என் ORD-1001 ₹2,400 பணம் வரவில்லை", "M1001", "0001", llm=agent, reply_llm=reply)


def test_second_identical_run_is_served_from_cache(tmp_path):
    path = str(tmp_path / "cache.json")
    live_a, live_r = CountingLLM(), CountingLLM()
    a, r = CachingLLM(live_a, path, "agent"), CachingLLM(live_r, path, "reply")

    s1 = _run(a, r)
    first_calls = live_a.calls + live_r.calls
    assert s1["status"] == "resolved" and first_calls >= 4          # intake + 2 tool rounds + reply

    reset_and_seed()
    reset_checkpoints()
    s2 = _run(a, r)
    assert live_a.calls + live_r.calls == first_calls                # zero new model calls
    assert a.hits >= 3 and r.hits == 1
    assert s2["status"] == "resolved" and s2["policy_decision"]["rule_id"] == "R-07"
    assert s1["reply"].replace(s1["verification"]["utr"], "") == s2["reply"].replace(s2["verification"]["utr"], "")


def test_cache_persists_to_disk_and_reloads(tmp_path):
    path = tmp_path / "cache.json"
    _run(CachingLLM(CountingLLM(), str(path), "agent"), CachingLLM(CountingLLM(), str(path), "reply"))
    assert path.exists() and len(json.loads(path.read_text(encoding="utf-8"))) >= 4

    CachingLLM._DATA.clear()
    CachingLLM._LOADED.clear()                                       # simulate a fresh process
    reset_and_seed()
    reset_checkpoints()
    live = CountingLLM()
    s = _run(CachingLLM(live, str(path), "agent"), CachingLLM(live, str(path), "reply"))
    assert live.calls == 0 and s["status"] == "resolved"


def test_different_input_misses_cache(tmp_path):
    path = str(tmp_path / "cache.json")
    live = CountingLLM()
    a = CachingLLM(live, path, "reply")
    from langchain_core.messages import HumanMessage
    a.invoke([HumanMessage("one")])
    a.invoke([HumanMessage("two")])
    a.invoke([HumanMessage("one")])
    assert live.calls == 2 and a.hits == 1
