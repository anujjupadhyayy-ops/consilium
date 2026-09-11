import pytest


@pytest.fixture(autouse=True)
def _blank_real_credentials(monkeypatch):
    """Never let a test accidentally talk to a real model or LangSmith endpoint."""
    for var in ("API_KEY", "LANGCHAIN_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")


@pytest.fixture
def seed_input() -> str:
    from seeds.supplier_milestone import SUPPLIER_MILESTONE_SEED

    return SUPPLIER_MILESTONE_SEED["scenario"]


@pytest.fixture
def built_graph():
    from orchestrator.graph import build_graph

    return build_graph()
