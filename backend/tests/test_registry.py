import json
import shutil

from agents.delivery import DeliveryAgent
from agents.finance import FinanceAgent
from agents.operations import OperationsAgent
from agents.pmo import PMOAgent
from agents.registry import DEFAULT_CONFIGS_DIR, DEFAULT_MANIFEST_PATH, list_enabled_agent_ids, load_agents_from_manifest


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


def test_editing_a_config_file_on_disk_changes_the_evaluated_stance(tmp_path, seed_facts):
    """The strongest editability proof: edit the actual JSON file a future
    P4 UI would write to, with zero code changes, and get a different
    stance on the same facts."""
    manifest_path, configs_dir = _copy_manifest_and_configs(tmp_path)
    finance_config_path = configs_dir / "finance.json"
    finance_config = json.loads(finance_config_path.read_text())
    finance_config["supplier_cost_increase_threshold_pct"] = 50.0  # well above the seed's 15%
    finance_config_path.write_text(json.dumps(finance_config))

    agents = load_agents_from_manifest(manifest_path=manifest_path, configs_dir=configs_dir)
    finance_agent = next(a for a in agents if a.id == "finance")

    position = finance_agent.evaluate(seed_facts["finance"])

    assert position["stance"] == "yes"
