"""Central configuration, loaded from environment variables / .env.

Everything that might change between your laptop and the venue lives here,
so no other module reads os.environ directly.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sarvam_api_key: str = ""
    llm_provider: str = "sarvam"
    llm_model: str = "sarvam-105b"
    openai_api_key: str = ""
    llm_max_tokens: int = 2048             # reasoning tokens DO count toward this on sarvam-105b
    # Replies use the low-latency, no-reasoning model. sarvam-105b spent its whole
    # token budget reasoning and returned empty replies (tested 13 Nov 2026).
    llm_reply_model: str = "sarvam-105b-conversations"
    llm_reasoning_effort: str = ""         # "" (off) | low | medium | high

    # Fixed demo clock so "is this payout late?" gives the same answer every run.
    demo_now: str = "2026-11-15T10:00:00"
    tool_retry_backoff: float = 0.3        # seconds; doubles per retry

    database_url: str = "sqlite:///./msa.db"
    checkpoint_db: str = "checkpoints.db"   # LangGraph SqliteSaver: paused cases survive restarts
    policy_file: str = "policy/policy.yaml"

    # API (Step 4)
    ops_token: str = "demo-ops-token"      # X-Ops-Token for approvals, reset, system events. Change in .env.
    # The web app normally goes through Vite's /api proxy (same origin, no CORS needed).
    # These cover calling the API directly from a browser dev server.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    rate_limit_per_min: int = 20           # per client IP, on case-creating endpoints
    llm_offline: bool = False              # true = never call Sarvam (OfflineLLM)

    mock_failure_rate: float = 0.0
    demo_mode: bool = False                # true = replay cached LLM answers (CachingLLM), live only on a miss
    llm_cache_file: str = "demo_assets/llm_cache.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
