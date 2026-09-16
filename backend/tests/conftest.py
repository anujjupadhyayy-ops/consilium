import pytest


@pytest.fixture(autouse=True)
def _blank_real_credentials(monkeypatch):
    """Never let a test accidentally talk to a real model or LangSmith endpoint."""
    for var in ("API_KEY", "LANGCHAIN_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")


@pytest.fixture(autouse=True)
def _mock_llm_unavailable_by_default(monkeypatch):
    """P3.5: agents/routing/reconcile all call model.llm.call_structured.
    Every test gets a fast, deterministic run by default -- the model is
    "unavailable", which exercises the same graceful-fallback path a real
    outage would (engage everyone; deterministic reconcile). Tests that
    want to verify genuine LLM-driven behaviour (a subset selected, the
    blocker policy enforced against a misbehaving model, ...) override
    this explicitly with their own monkeypatch -- see test_chief_of_staff.py.
    """
    from model.llm import LLMUnavailableError

    def _raise(*args, **kwargs):
        raise LLMUnavailableError("mocked: no model in tests by default")

    monkeypatch.setattr("model.llm.call_structured", _raise)


@pytest.fixture
def seed_input() -> str:
    from seeds.supplier_milestone import SUPPLIER_MILESTONE_SEED

    return SUPPLIER_MILESTONE_SEED["scenario"]


@pytest.fixture
def seed_facts() -> dict:
    from seeds.supplier_milestone import SUPPLIER_MILESTONE_SEED

    return SUPPLIER_MILESTONE_SEED["facts"]


@pytest.fixture
def built_graph():
    from orchestrator.graph import build_graph

    return build_graph()
