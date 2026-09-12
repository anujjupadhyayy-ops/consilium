import json

from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)


def _parse_sse(raw_text: str) -> list[tuple[str, dict]]:
    events = []
    for block in raw_text.strip().split("\n\n"):
        if not block:
            continue
        event_line, data_line = block.split("\n", 1)
        event = event_line.removeprefix("event: ")
        data = json.loads(data_line.removeprefix("data: "))
        events.append((event, data))
    return events


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_seeds_lists_four_seeds_one_available():
    response = client.get("/seeds")

    seeds = response.json()
    assert len(seeds) == 4
    assert sum(1 for s in seeds if s["available"]) == 1
    assert next(s for s in seeds if s["id"] == "supplier_milestone")["available"] is True
    assert "facts" not in seeds[0]  # summaries only


def test_stream_requires_text_or_seed_id():
    response = client.get("/run/stream")

    assert response.status_code == 422


def test_stream_unknown_seed_returns_404():
    response = client.get("/run/stream?seed_id=does-not-exist")

    assert response.status_code == 404


def test_stream_unavailable_seed_returns_409():
    response = client.get("/run/stream?seed_id=budget_overrun")

    assert response.status_code == 409


def test_stream_supplier_seed_emits_the_full_trace_in_order():
    """Under the autouse mocked-LLM-unavailable fallback: routing engages
    everyone, the seed's pre-supplied facts drive real evaluate(), reconcile
    falls back to the deterministic P2 logic -- same shape as a P1/P2 run."""
    response = client.get("/run/stream?seed_id=supplier_milestone&pace=0")

    events = _parse_sse(response.text)
    kinds = [data["kind"] for event, data in events if event == "trace"]

    assert kinds[0] == "route"
    assert kinds.count("position") == 4
    assert kinds[-2] == "conflict"
    assert kinds[-1] == "reconciliation"
    assert events[-1][0] == "done"


def test_stream_supplier_seed_positions_match_the_designed_conflict():
    response = client.get("/run/stream?seed_id=supplier_milestone&pace=0")

    events = _parse_sse(response.text)
    stances = {
        data["agent"]: data["payload"]["stance"]
        for event, data in events
        if event == "trace" and data["kind"] == "position"
    }

    assert stances == {"finance": "no", "delivery": "yes", "pmo": "conditional", "operations": "blocker"}


def test_stream_free_text_runs_on_neutral_defaults_when_model_unavailable():
    """No seed, no facts, and the LLM extraction is mocked off -- each
    agent's neutral Facts defaults keep the run from crashing."""
    response = client.get("/run/stream?text=Something+entirely+free-text&pace=0")

    events = _parse_sse(response.text)
    assert events[-1][0] == "done"
    kinds = [data["kind"] for event, data in events if event == "trace"]
    assert "reconciliation" in kinds


# --------------------------------------------------------------- council --

def test_council_retest_unknown_agent_404():
    response = client.post("/council/retest", json={"agent_id": "legal"})

    assert response.status_code == 404


def test_council_retest_finance_default_config_matches_seed_stance():
    response = client.post("/council/retest", json={"agent_id": "finance"})

    assert response.status_code == 200
    assert response.json()["stance"] == "no"


def test_council_retest_finance_lenient_config_flips_the_stance():
    response = client.post(
        "/council/retest",
        json={"agent_id": "finance", "config_overrides": {"supplier_cost_increase_threshold_pct": 50.0}},
    )

    assert response.json()["stance"] == "yes"


def test_council_retest_operations_licence_toggle_clears_the_blocker():
    response = client.post(
        "/council/retest",
        json={"agent_id": "operations", "fact_overrides": {"licence_provisioned_for_new_date": True}},
    )

    assert response.json()["stance"] == "yes"


# -------------------------------------------------------------- settings --

def test_get_model_settings_never_leaks_the_raw_key():
    response = client.get("/settings/model")

    assert response.status_code == 200
    assert "api_key" not in response.json()
    assert "api_key_set" in response.json()


def test_save_model_settings_persists_and_reports_connection(tmp_path, monkeypatch):
    from model import runtime_settings

    monkeypatch.setattr(runtime_settings, "RUNTIME_SETTINGS_PATH", tmp_path / "runtime_settings.json")
    monkeypatch.setattr("model.llm.test_connection", lambda config=None: (True, "mocked ok"))

    response = client.post(
        "/settings/model",
        json={"provider": "oss", "base_url": "http://localhost:11434/v1", "model_name": "llama3.2"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {"saved": True, "connection_ok": True, "message": "mocked ok"}
    assert runtime_settings.read_runtime_settings(tmp_path / "runtime_settings.json") == {
        "provider": "oss",
        "base_url": "http://localhost:11434/v1",
        "model_name": "llama3.2",
    }


# --------------------------------------------------------------- trigger --

def test_trigger_inbound_email_matches_pmo_and_delivery_keywords():
    response = client.post("/trigger/inbound-email", json={})

    assert response.status_code == 200
    body = response.json()
    assert "pmo" in body["convened"]  # "contract variation" is a PMO trigger keyword
    assert "delivery" in body["convened"]  # "milestone" is a Delivery trigger keyword
    assert body["run_text"]
