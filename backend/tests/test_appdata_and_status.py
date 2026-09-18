"""Packaging-robustness fixes: writable state lives outside the source tree
(so --reload doesn't self-destruct), the CoS persona falls back to its shipped
default on a fresh clone, and the model-status endpoint reports reachability
for the header's fallback banner."""
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import app
from appdata import data_dir

client = TestClient(app)


def test_data_dir_respects_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("CONSILIUM_DATA_DIR", str(tmp_path / "d"))
    assert data_dir() == tmp_path / "d"


def test_data_dir_defaults_to_home(monkeypatch):
    monkeypatch.delenv("CONSILIUM_DATA_DIR", raising=False)
    assert data_dir() == Path.home() / ".consilium"


def test_cos_settings_falls_back_to_packaged_default(monkeypatch, tmp_path):
    from orchestrator import cos_settings

    # user copy absent -> shipped default persona, not a crash
    monkeypatch.setattr(cos_settings, "COS_SETTINGS_PATH", tmp_path / "absent.json")
    assert "persona" in cos_settings.read_cos_settings()


def test_cos_write_creates_parent_and_roundtrips(monkeypatch, tmp_path):
    from orchestrator import cos_settings

    p = tmp_path / "nested" / "cos.json"
    monkeypatch.setattr(cos_settings, "COS_SETTINGS_PATH", p)
    cos_settings.write_cos_settings("Be terse.")
    assert p.exists()
    assert cos_settings.read_cos_settings()["persona"] == "Be terse."


def test_runtime_settings_write_creates_parent(monkeypatch, tmp_path):
    from model import runtime_settings

    p = tmp_path / "nested" / "runtime.json"
    monkeypatch.setattr(runtime_settings, "RUNTIME_SETTINGS_PATH", p)
    runtime_settings.write_runtime_settings({"model_name": "x"})
    assert p.exists()
    assert runtime_settings.read_runtime_settings()["model_name"] == "x"


def test_model_status_reports_unreachable(monkeypatch):
    monkeypatch.setattr("model.llm.probe_model", lambda cfg=None: False)
    r = client.get("/settings/model/status")
    assert r.status_code == 200
    body = r.json()
    assert body["reachable"] is False
    assert "model" in body and "base_url" in body


def test_model_status_reports_reachable(monkeypatch):
    monkeypatch.setattr("model.llm.probe_model", lambda cfg=None: True)
    assert client.get("/settings/model/status").json()["reachable"] is True


def test_pre_p3_6_history_entries_load_and_render_data_without_error(monkeypatch, tmp_path):
    """HistoryEntry.positions is an untyped list[dict] and no routing shape
    was ever persisted in history, so a pre-P3.6 entry (positions with
    stance/agent only, no checks) loads unchanged -- nothing to migrate;
    this proves it explicitly rather than assuming it."""
    import json

    monkeypatch.setenv("CONSILIUM_DATA_DIR", str(tmp_path))
    (tmp_path / "run_history.json").write_text(json.dumps([{
        "label": "Old run", "q": "old scenario", "when": "09:00", "verdict": "Decline",
        "positions": [{"agent": "finance", "stance": "no", "driving_constraint": "x", "reasoning": "y",
                       "recommendation": "z", "lead_figure": "w"}],
    }]))
    runs = client.get("/history").json()["runs"]
    assert runs[0]["label"] == "Old run" and runs[0]["positions"][0]["stance"] == "no"
