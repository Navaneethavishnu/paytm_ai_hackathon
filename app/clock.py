"""Single source of 'now' for seed data and the agent, so demos are deterministic."""
from datetime import datetime

from app.config import get_settings


def now() -> datetime:
    return datetime.fromisoformat(get_settings().demo_now)
