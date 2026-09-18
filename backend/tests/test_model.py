import os
import stat

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


# ------------------------------- LangSmith is opt-in; the key file is private --

@pytest.mark.parametrize("flag,key", [("LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY"), ("LANGSMITH_TRACING", "LANGSMITH_API_KEY")])
def test_tracing_is_switched_off_when_on_without_a_key(monkeypatch, flag, key):
    """A fresh clone copies .env.example; tracing on with no key used to upload
    every run's text to LangSmith and fail with a 401 each time."""
    from model.config import disable_tracing_without_key

    for var in ("LANGCHAIN_API_KEY", "LANGSMITH_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(flag, "true")
    disable_tracing_without_key()
    assert os.environ[flag] == "false"


def test_tracing_stays_on_when_a_key_is_present(monkeypatch):
    from model.config import disable_tracing_without_key

    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "a-real-looking-key")
    disable_tracing_without_key()
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"


def test_the_shipped_env_example_does_not_enable_tracing():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
    assert "LANGCHAIN_TRACING_V2=false" in text and "LANGCHAIN_TRACING_V2=true\n" not in text


def test_the_runtime_settings_file_holding_an_api_key_is_owner_only(tmp_path):
    from model.runtime_settings import write_runtime_settings

    path = tmp_path / "runtime_settings.json"
    write_runtime_settings({"api_key": "secret-value"}, path=path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
