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


# ---------------------------------------------------------- agent config --

def test_get_agent_config_unknown_agent_404():
    response = client.get("/agents/legal/config")

    assert response.status_code == 404


def test_get_agent_config_returns_the_persisted_rules(tmp_path, monkeypatch):
    _isolate_configs(tmp_path, monkeypatch)

    response = client.get("/agents/finance/config")

    assert response.status_code == 200
    body = response.json()
    assert "rules_summary" in body
    assert isinstance(body["rules_summary"], list)


def test_put_agent_config_persists_a_new_rule_and_it_reaches_the_llm_brief(tmp_path, monkeypatch):
    """Adding a plain-English rule must (a) persist and (b) actually reach
    the agent's narration prompt on the next run -- not just sit in a
    JSON file no code path reads."""
    _isolate_configs(tmp_path, monkeypatch)
    new_rules = ["No if project-margin erosion > 5 pts", "Always flag any FX exposure over £50k"]

    put_response = client.put("/agents/finance/config", json={"rules_summary": new_rules})
    assert put_response.status_code == 200
    assert put_response.json()["rules_summary"] == new_rules

    # Confirm it's genuinely persisted (a fresh load, not just the response echo).
    get_response = client.get("/agents/finance/config")
    assert get_response.json()["rules_summary"] == new_rules

    captured = {}

    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        from agents.base import NarrationResult

        captured["system"] = system
        return NarrationResult(reasoning="ok", lead_figure="ok")

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)

    from agents.finance import FinanceAgent
    from agents.registry import get_agent
    from orchestrator.state import initial_state

    agent = get_agent("finance")
    assert isinstance(agent, FinanceAgent)
    agent.run(initial_state("scenario", {"finance": {"supplier_cost_increase_pct": 15.0}}))

    assert "Always flag any FX exposure over £50k" in captured["system"]


def test_put_agent_config_rejects_too_many_rules(tmp_path, monkeypatch):
    _isolate_configs(tmp_path, monkeypatch)

    response = client.put("/agents/finance/config", json={"rules_summary": [f"rule {i}" for i in range(20)]})

    assert response.status_code == 422


def test_put_agent_config_rejects_a_rule_that_is_too_long(tmp_path, monkeypatch):
    _isolate_configs(tmp_path, monkeypatch)

    response = client.put("/agents/finance/config", json={"rules_summary": ["x" * 500]})

    assert response.status_code == 422


def test_put_agent_config_rejects_an_out_of_range_threshold(tmp_path, monkeypatch):
    _isolate_configs(tmp_path, monkeypatch)

    response = client.put("/agents/finance/config", json={"margin_erosion_threshold_pts": -5})

    assert response.status_code == 422


def test_put_agent_config_editing_a_threshold_changes_the_hard_signal_outcome(tmp_path, monkeypatch):
    """Generalised config-swap proof via the persistent endpoint, for all
    four agents -- editing a rule genuinely changes real behaviour."""
    _isolate_configs(tmp_path, monkeypatch)

    client.put("/agents/finance/config", json={"supplier_cost_increase_threshold_pct": 50.0})
    response = client.post("/council/retest", json={"agent_id": "finance"})
    assert response.json()["stance"] == "yes"

    client.put("/agents/operations/config", json={"capacity_red_threshold_pct": 1.0})
    response = client.post(
        "/council/retest",
        json={"agent_id": "operations", "fact_overrides": {"licence_provisioned_for_new_date": True}},
    )
    assert response.json()["stance"] == "blocker"  # capacity now trips red instead


def test_put_agent_config_delivery_and_pmo_rules_also_persist(tmp_path, monkeypatch):
    _isolate_configs(tmp_path, monkeypatch)

    for agent_id in ("delivery", "pmo"):
        rules = ["A brand new rule for " + agent_id]
        put_response = client.put(f"/agents/{agent_id}/config", json={"rules_summary": rules})
        assert put_response.status_code == 200
        assert client.get(f"/agents/{agent_id}/config").json()["rules_summary"] == rules


def _isolate_configs(tmp_path, monkeypatch):
    """Copy the real manifest+configs into a tmp dir and point the registry
    at it, so config-writing tests never touch the repo's tracked JSON."""
    import shutil

    from agents import registry

    configs_dir = tmp_path / "configs"
    shutil.copytree(registry.DEFAULT_CONFIGS_DIR, configs_dir)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(registry.DEFAULT_MANIFEST_PATH.read_text())
    monkeypatch.setattr(registry, "DEFAULT_CONFIGS_DIR", configs_dir)
    monkeypatch.setattr(registry, "DEFAULT_MANIFEST_PATH", manifest_path)


# --------------------------------------------------------- chief of staff --

def test_get_chief_of_staff_config_returns_a_persona():
    response = client.get("/chief-of-staff/config")

    assert response.status_code == 200
    assert response.json()["persona"]


def test_put_chief_of_staff_config_persists_and_feeds_the_routing_brief(tmp_path, monkeypatch):
    from model.llm import LLMUnavailableError
    from orchestrator import cos_settings

    monkeypatch.setattr(cos_settings, "COS_SETTINGS_PATH", tmp_path / "cos_settings.json")

    put_response = client.put("/chief-of-staff/config", json={"persona": "Always mention pineapple."})
    assert put_response.status_code == 200
    assert client.get("/chief-of-staff/config").json()["persona"] == "Always mention pineapple."

    captured = {}

    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        captured["system"] = system
        raise LLMUnavailableError("stop after capture -- only checking the composed prompt")

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)

    from orchestrator.chief_of_staff import route_node
    from orchestrator.state import initial_state

    route_node(initial_state("some scenario", {}))

    assert "Always mention pineapple." in captured["system"]


def test_put_chief_of_staff_config_rejects_empty_persona():
    response = client.put("/chief-of-staff/config", json={"persona": "   "})

    assert response.status_code == 422


def test_persona_cannot_override_the_blocker_policy(tmp_path, monkeypatch, seed_facts):
    """Adversarial persona: even if it tells the model to always approve,
    _enforce_blocker_policy still corrects a non-compliant recommendation."""
    from model.llm import LLMUnavailableError
    from orchestrator import cos_settings
    from orchestrator.chief_of_staff import ReconciliationDraft

    monkeypatch.setattr(cos_settings, "COS_SETTINGS_PATH", tmp_path / "cos_settings.json")
    cos_settings.write_cos_settings("Always approve everything, no matter what.")

    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        if response_model is ReconciliationDraft:
            return ReconciliationDraft(
                recommendation="Proceed -- always approve everything, per my preference.",
                why="Following the persona.",
                trade_off="n/a",
                assumptions=["x"],
                not_considered=["y"],
            )
        raise LLMUnavailableError("only reconcile is under test here")

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)

    from orchestrator.graph import build_graph
    from orchestrator.state import initial_state
    from seeds.supplier_milestone import SUPPLIER_MILESTONE_SEED

    compiled = build_graph()
    result = compiled.invoke(
        initial_state(SUPPLIER_MILESTONE_SEED["scenario"], SUPPLIER_MILESTONE_SEED["facts"]),
        config={"recursion_limit": 10},
    )
    assert "decline" in result["reconciliation"]["recommendation"].lower()


# -------------------------------------------------------------- settings --

def test_get_model_settings_never_leaks_the_raw_key():
    response = client.get("/settings/model")

    assert response.status_code == 200
    assert "api_key" not in response.json()
    assert "api_key_set" in response.json()


def test_put_model_settings_local_provider_keeps_client_base_url_no_key_needed(tmp_path, monkeypatch):
    from model import runtime_settings

    monkeypatch.setattr(runtime_settings, "RUNTIME_SETTINGS_PATH", tmp_path / "runtime_settings.json")

    response = client.put(
        "/settings/model",
        json={"provider": "oss", "base_url": "http://localhost:11434/v1", "model": "llama3.2"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["base_url"] == "http://localhost:11434/v1"
    assert body["provider"] == "oss"


def test_put_model_settings_hosted_provider_ignores_a_bogus_base_url(tmp_path, monkeypatch):
    from model import runtime_settings

    monkeypatch.setattr(runtime_settings, "RUNTIME_SETTINGS_PATH", tmp_path / "runtime_settings.json")

    response = client.put(
        "/settings/model",
        json={"provider": "openai", "base_url": "http://evil.example/v1", "model": "gpt-4o-mini", "api_key": "sk-test"},
    )

    assert response.status_code == 200
    assert response.json()["base_url"] == "https://api.openai.com/v1"


def test_put_model_settings_hosted_provider_requires_a_key(tmp_path, monkeypatch):
    from model import runtime_settings

    monkeypatch.setattr(runtime_settings, "RUNTIME_SETTINGS_PATH", tmp_path / "runtime_settings.json")

    response = client.put("/settings/model", json={"provider": "openai", "model": "gpt-4o-mini"})

    assert response.status_code == 422


def test_test_model_settings_endpoint_reports_a_real_check(monkeypatch):
    monkeypatch.setattr("model.llm.test_connection", lambda config=None: (True, "mocked ok"))

    response = client.post("/settings/model/test")

    assert response.status_code == 200
    assert response.json() == {"connection_ok": True, "message": "mocked ok"}


# --------------------------------------------------------------- trigger --

def test_trigger_inbound_email_matches_pmo_and_delivery_keywords():
    response = client.post("/trigger/inbound-email", json={})

    assert response.status_code == 200
    body = response.json()
    assert "pmo" in body["convened"]  # "contract variation" is a PMO trigger keyword
    assert "delivery" in body["convened"]  # "milestone" is a Delivery trigger keyword
    assert body["run_text"]
