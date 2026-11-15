import pytest


@pytest.fixture(autouse=True)
def _isolated_checkpoints(tmp_path, monkeypatch):
    """Each test gets its own LangGraph checkpoint DB."""
    from app.agent import graph
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "checkpoint_db", str(tmp_path / "checkpoints.db"))
    yield
    graph.reset_checkpoints()
