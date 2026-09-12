import pytest

from model.config import ModelConfig


def test_model_config_reads_from_env(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "oss")
    monkeypatch.setenv("MODEL_NAME", "qwen-2.5")
    monkeypatch.setenv("BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("API_KEY", "not-a-real-key")

    config = ModelConfig.from_env()

    assert config.provider == "oss"
    assert config.model_name == "qwen-2.5"
    assert config.base_url == "http://localhost:8000/v1"
    assert config.api_key == "not-a-real-key"


def test_model_config_has_sane_defaults(monkeypatch):
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)

    config = ModelConfig.from_env()

    assert config.provider == "openai"
    assert config.model_name


def test_full_seed_run_never_touches_the_model_client(monkeypatch, seed_input, seed_facts):
    """Config-driven agents are still deterministic rule evaluators in P2 --
    confirm this is a verified invariant, not just a convention, by making
    the model client raise if anything on the seed's code path calls it."""
    from orchestrator.graph import build_graph
    from orchestrator.state import initial_state

    def _boom(*args, **kwargs):
        raise AssertionError("model.client.get_client was called during a P2 run")

    monkeypatch.setattr("model.client.get_client", _boom)

    compiled = build_graph()
    result = compiled.invoke(initial_state(seed_input, seed_facts), config={"recursion_limit": 10})

    assert result["reconciliation"] is not None
