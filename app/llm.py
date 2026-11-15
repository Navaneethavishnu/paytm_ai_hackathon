"""LLM provider factory.

The agent only uses three LangChain chat-model methods: `with_structured_output`,
`bind_tools` and `invoke`. Anything implementing those can be swapped in
(Sarvam, a test double, or the OfflineLLM below).

ChatSarvam params checked against the installed langchain-sarvam 0.1.2 source:
model, temperature, max_tokens, reasoning_effort, api_key, max_retries.
"""
import hashlib
import json
import os
import threading
from pathlib import Path

from langchain_core.messages import AIMessage

from app.config import get_settings


class OfflineLLM:
    """No-network stand-in. Returns nothing useful on purpose, so the agent's
    deterministic fallbacks (regex intake, required evidence, reply templates)
    do all the work. Lets you run and demo the whole graph without an API key."""
    offline = True

    def with_structured_output(self, schema, **kwargs):
        return self

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages, **kwargs):
        return AIMessage(content="")


class CachingLLM:
    """DEMO_MODE: replay saved LLM answers for identical inputs, call live only on a miss.

    Keys are sha256 of (purpose, call kind, schema/tool names, every message's role, content,
    tool calls). Inputs are deterministic for the seeded demo (fixed clock, no case IDs in
    prompts, replies use placeholder skeletons), so a warmed cache makes every demo case
    instant and identical. Warm it with:  DEMO_MODE=true python scripts/run_case.py all --approve priya
    """

    def __init__(self, inner, path: str, purpose: str):
        self.inner, self.path, self.purpose = inner, Path(path), purpose
        self.hits = self.misses = 0

    # --- storage (shared by all wrappers in the process) ---
    _LOCK = threading.Lock()
    _DATA: dict[str, dict] = {}
    _LOADED: set[str] = set()

    def _store(self) -> dict:
        with self._LOCK:
            key = str(self.path)
            if key not in self._LOADED:
                if self.path.exists():
                    self._DATA.update(json.loads(self.path.read_text(encoding="utf-8")))
                self._LOADED.add(key)
            return self._DATA

    def _save(self, k: str, v: dict):
        with self._LOCK:
            self._DATA[k] = v
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._DATA, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self.path)

    def _key(self, kind: str, extra: str, messages) -> str:
        parts = [self.purpose, kind, extra]
        for m in messages:
            parts.append(json.dumps({"t": m.type, "c": m.content, "tc": [(t["name"], t["args"]) for t in getattr(m, "tool_calls", None) or []],
                                     "id": getattr(m, "tool_call_id", None)}, ensure_ascii=False, sort_keys=True, default=str))
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()

    def _cached(self, k: str, live, encode, decode):
        hit = self._store().get(k)
        if hit is not None:
            self.hits += 1
            return decode(hit)
        self.misses += 1
        out = live()
        self._save(k, encode(out))
        return out

    # --- the three LangChain methods the agent uses ---
    def invoke(self, messages, **kw):
        return self._cached(self._key("invoke", "", messages), lambda: self.inner.invoke(messages, **kw),
                            lambda m: {"content": m.content}, lambda d: AIMessage(content=d["content"]))

    def bind_tools(self, tools, **kw):
        names = ",".join(sorted(t["function"]["name"] if isinstance(t, dict) else getattr(t, "name", str(t)) for t in tools))
        bound, outer = self.inner.bind_tools(tools, **kw), self

        class _Bound:
            def invoke(self, messages, **k):
                return outer._cached(
                    outer._key("tools", names, messages), lambda: bound.invoke(messages, **k),
                    lambda m: {"content": m.content, "tool_calls": [{"name": t["name"], "args": t["args"], "id": t.get("id")} for t in m.tool_calls or []]},
                    lambda d: AIMessage(content=d["content"], tool_calls=[{**t, "type": "tool_call"} for t in d["tool_calls"]]))
        return _Bound()

    def with_structured_output(self, schema, **kw):
        runnable, outer = self.inner.with_structured_output(schema, **kw), self

        class _Structured:
            def invoke(self, messages, **k):
                return outer._cached(
                    outer._key("structured", schema.__name__, messages), lambda: runnable.invoke(messages, **k),
                    lambda r: {"data": r.model_dump() if hasattr(r, "model_dump") else None},
                    lambda d: schema(**d["data"]) if d["data"] is not None else None)
        return _Structured()


def get_llm(offline: bool = False, purpose: str = "agent"):
    """purpose='agent' -> LLM_MODEL (intake, tool use); purpose='reply' -> LLM_REPLY_MODEL.
    DEMO_MODE=true wraps the live model in CachingLLM."""
    s = get_settings()
    if offline:
        return OfflineLLM()
    live = _live_llm(s, purpose)
    return CachingLLM(live, s.llm_cache_file, purpose) if s.demo_mode else live


def _live_llm(s, purpose: str):
    if s.llm_provider == "sarvam":
        if not s.sarvam_api_key or s.sarvam_api_key == "your_sarvam_key_here":
            raise RuntimeError("SARVAM_API_KEY is not set. Add it to .env, or run with --offline.")
        from langchain_sarvam import ChatSarvam
        if purpose == "reply":
            return ChatSarvam(model=s.llm_reply_model, temperature=0, max_tokens=400,
                              api_key=s.sarvam_api_key, max_retries=1)
        kwargs = dict(model=s.llm_model, temperature=0, max_tokens=s.llm_max_tokens,
                      api_key=s.sarvam_api_key, max_retries=1)
        if s.llm_reasoning_effort:
            kwargs["reasoning_effort"] = s.llm_reasoning_effort
        return ChatSarvam(**kwargs)
    raise RuntimeError(f"LLM_PROVIDER={s.llm_provider!r} is not wired up yet "
                       "(the fallback needs a new dependency, so ask before adding it).")
