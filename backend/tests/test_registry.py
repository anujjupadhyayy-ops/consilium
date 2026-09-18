import json
import shutil

import pytest

from agents.delivery import DeliveryAgent
from agents.finance import FinanceAgent
from agents.operations import OperationsAgent
from agents.pmo import PMOAgent
from agents.registry import (
    BlockerRuleImmutableError,
    DEFAULT_CONFIGS_DIR,
    DEFAULT_MANIFEST_PATH,
    list_enabled_agent_ids,
    load_agents_from_manifest,
    save_agent_config,
)
from agents.rules import RuleError


def test_manifest_loads_all_four_default_agents():
    agents = load_agents_from_manifest()

    by_id = {agent.id: agent for agent in agents}
    assert set(by_id) == {"finance", "delivery", "pmo", "operations"}
    assert isinstance(by_id["finance"], FinanceAgent)
    assert isinstance(by_id["delivery"], DeliveryAgent)
    assert isinstance(by_id["pmo"], PMOAgent)
    assert isinstance(by_id["operations"], OperationsAgent)


def test_list_enabled_agent_ids_matches_the_default_manifest():
    assert set(list_enabled_agent_ids()) == {"finance", "delivery", "pmo", "operations"}


def _copy_manifest_and_configs(tmp_path):
    configs_dir = tmp_path / "configs"
    shutil.copytree(DEFAULT_CONFIGS_DIR, configs_dir)
    manifest = json.loads(DEFAULT_MANIFEST_PATH.read_text())
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return manifest_path, configs_dir


def test_disabling_an_agent_in_the_manifest_removes_it_without_code(tmp_path):
    """The add/remove-agents-without-code seam: this only edits manifest.json,
    never touches a .py file."""
    manifest_path, configs_dir = _copy_manifest_and_configs(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["agents"]:
        if entry["id"] == "operations":
            entry["enabled"] = False
    manifest_path.write_text(json.dumps(manifest))

    agents = load_agents_from_manifest(manifest_path=manifest_path, configs_dir=configs_dir)

    assert {a.id for a in agents} == {"finance", "delivery", "pmo"}
    assert set(list_enabled_agent_ids(manifest_path=manifest_path)) == {"finance", "delivery", "pmo"}


# ---------------------------------------------------------- P3.6 rules[] --

def test_every_shipped_config_validates():
    """load_agents_from_manifest() already calls agent.validate_rules() on
    every agent -- if any shipped config had an unsafe/unresolvable `when`,
    this would raise. Explicit here as its own named test per §6.2."""
    agents = load_agents_from_manifest()
    for agent in agents:
        agent.validate_rules()  # no raise


def test_invalid_rule_expression_rejected_with_a_readable_error_at_load(tmp_path):
    manifest_path, configs_dir = _copy_manifest_and_configs(tmp_path)
    finance_config_path = configs_dir / "finance.json"
    config = json.loads(finance_config_path.read_text())
    config["rules"] = [{
        "id": "bad", "description": "bad", "fields": ["margin_erosion_pts"],
        "when": "__import__('os').system('echo hi')", "stance": "no",
    }]
    finance_config_path.write_text(json.dumps(config))

    with pytest.raises(RuleError):
        load_agents_from_manifest(manifest_path=manifest_path, configs_dir=configs_dir)


def test_invalid_rule_expression_rejected_via_config_save_endpoint(tmp_path):
    manifest_path, configs_dir = _copy_manifest_and_configs(tmp_path)
    with pytest.raises(RuleError):
        save_agent_config(
            "finance",
            {"rules": [{
                "id": "bad", "description": "bad", "fields": ["margin_erosion_pts"],
                "when": "unknown_field > 5", "stance": "no",
            }]},
            manifest_path=manifest_path, configs_dir=configs_dir,
        )


def test_blocker_rule_without_keywords_is_rejected(tmp_path):
    manifest_path, configs_dir = _copy_manifest_and_configs(tmp_path)
    with pytest.raises(Exception):  # pydantic.ValidationError, wrapping RuleConfig's own check
        save_agent_config(
            "operations",
            {"rules": [{
                "id": "bad_blocker", "description": "bad", "fields": ["licence_provisioned_for_new_date"],
                "when": "licence_provisioned_for_new_date == False", "stance": "blocker",
            }]},
            manifest_path=manifest_path, configs_dir=configs_dir,
        )


def test_save_endpoint_cannot_add_a_blocker_rule(tmp_path):
    manifest_path, configs_dir = _copy_manifest_and_configs(tmp_path)
    with pytest.raises(BlockerRuleImmutableError):
        save_agent_config(
            "finance",
            {"rules": [{
                "id": "new_blocker", "description": "new", "fields": ["margin_erosion_pts"],
                "when": "margin_erosion_pts > 5", "stance": "blocker", "keywords": ["margin"],
            }]},
            manifest_path=manifest_path, configs_dir=configs_dir,
        )


def test_save_endpoint_cannot_remove_an_existing_blocker_rule(tmp_path):
    manifest_path, configs_dir = _copy_manifest_and_configs(tmp_path)
    with pytest.raises(BlockerRuleImmutableError):
        save_agent_config(
            "operations",
            {"rules": []},  # would silently drop every existing blocker rule
            manifest_path=manifest_path, configs_dir=configs_dir,
        )


def test_save_endpoint_cannot_alter_an_existing_blocker_rules_when(tmp_path):
    manifest_path, configs_dir = _copy_manifest_and_configs(tmp_path)
    current = json.loads((configs_dir / "operations.json").read_text())
    tampered_rules = [
        {**r, "when": "True"} if r["stance"] == "blocker" else r
        for r in current["rules"]
    ]
    with pytest.raises(BlockerRuleImmutableError):
        save_agent_config("operations", {"rules": tampered_rules}, manifest_path=manifest_path, configs_dir=configs_dir)


def test_threshold_edit_accepted_and_reflected_in_the_next_run(tmp_path):
    manifest_path, configs_dir = _copy_manifest_and_configs(tmp_path)
    agent = save_agent_config(
        "finance", {"supplier_cost_increase_threshold_pct": 50.0},
        manifest_path=manifest_path, configs_dir=configs_dir,
    )
    assert agent.config.supplier_cost_increase_threshold_pct == 50.0
    result = agent.check({"supplier_cost_increase_pct": 20.0})
    # 20% no longer trips the now-50%-threshold supplier-cost rule.
    assert not any("supplier_cost" in f.id for f in result.fired)


def test_editing_a_config_file_on_disk_changes_the_evaluated_stance(tmp_path, seed_facts):
    """The strongest editability proof: edit the actual JSON file the
    Council UI writes to, with zero code changes, and get a different
    stance on the same facts -- via the new check() path."""
    manifest_path, configs_dir = _copy_manifest_and_configs(tmp_path)
    finance_config_path = configs_dir / "finance.json"
    finance_config = json.loads(finance_config_path.read_text())
    finance_config["supplier_cost_increase_threshold_pct"] = 50.0  # well above the seed's 15%
    finance_config_path.write_text(json.dumps(finance_config))

    agents = load_agents_from_manifest(manifest_path=manifest_path, configs_dir=configs_dir)
    finance_agent = next(a for a in agents if a.id == "finance")

    result = finance_agent.check(seed_facts["finance"])

    assert not any("supplier_cost" in f.id for f in result.fired)


# ------------------------------------- name-collision guard (config vs facts) --

def test_config_scalar_named_like_a_facts_field_is_rejected_at_load_with_a_readable_error():
    from agents.finance import FinanceAgent, FinanceConfig

    class CollidingConfig(FinanceConfig):
        margin_erosion_pts: float = 5.0  # same name as FinanceFacts.margin_erosion_pts

    agent = FinanceAgent(agent_id="finance", config=CollidingConfig(lens="t", rules_summary=[]))
    with pytest.raises(RuleError) as exc:
        agent.validate_rules()
    assert "margin_erosion_pts" in str(exc.value) and "rename" in str(exc.value).lower()


def test_no_shipped_config_scalar_collides_with_a_facts_field():
    for agent in load_agents_from_manifest():
        assert not (set(agent.facts_model.model_fields) & set(agent._config_scalar_env())), agent.id
        assert not (set(agent.facts_model.model_fields) & agent.derived_field_names()), agent.id


def test_facts_take_precedence_over_derived_then_config_in_the_rule_environment():
    agent = load_agents_from_manifest()[0]
    agent._config_scalar_env = lambda: {"x": "config", "y": "config"}
    env = agent._rule_env({"x": "fact"}, derived={"x": "derived", "y": "derived"})
    assert env["x"] == "fact" and env["y"] == "derived"
