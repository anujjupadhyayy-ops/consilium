from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Type, Union

from .base import ConfigurableAgent
from .delivery import DeliveryAgent
from .finance import FinanceAgent
from .operations import OperationsAgent
from .pmo import PMOAgent

# The only place a new agent *kind* (as opposed to a new config for an
# existing kind) needs registering. Removing/duplicating an existing kind
# is a manifest.json + configs/*.json change only -- no code.
AGENT_KIND_REGISTRY: dict[str, Type[ConfigurableAgent]] = {
    "finance": FinanceAgent,
    "delivery": DeliveryAgent,
    "pmo": PMOAgent,
    "operations": OperationsAgent,
}

_PACKAGE_DIR = Path(__file__).parent
DEFAULT_MANIFEST_PATH = _PACKAGE_DIR / "manifest.json"
DEFAULT_CONFIGS_DIR = _PACKAGE_DIR / "configs"

PathLike = Union[Path, str]


def load_agents_from_manifest(
    manifest_path: Optional[PathLike] = None,
    configs_dir: Optional[PathLike] = None,
) -> list[ConfigurableAgent]:
    """The add/remove-agents-without-code seam.

    Delete or set "enabled": false on an entry in manifest.json to remove
    an agent from the roster; add a new entry re-using an existing `kind`
    with a different config file to run a second instance of it (e.g. a
    Finance agent for a different business unit). Adding a genuinely new
    *kind* of reasoning still needs a Python evaluator class registered in
    AGENT_KIND_REGISTRY above -- that boundary is inherent to encoding new
    procedural logic, not something a JSON file can express on its own.
    """
    manifest_path = Path(manifest_path) if manifest_path else DEFAULT_MANIFEST_PATH
    configs_dir = Path(configs_dir) if configs_dir else DEFAULT_CONFIGS_DIR

    manifest = json.loads(manifest_path.read_text())
    agents: list[ConfigurableAgent] = []
    for entry in manifest["agents"]:
        if not entry.get("enabled", True):
            continue
        agent_cls = AGENT_KIND_REGISTRY[entry["kind"]]
        raw_config = json.loads((configs_dir / entry["config"]).read_text())
        config = agent_cls.config_model.model_validate(raw_config)
        agents.append(agent_cls(agent_id=entry["id"], config=config))
    return agents


def list_enabled_agent_ids(manifest_path: Optional[PathLike] = None) -> list[str]:
    manifest_path = Path(manifest_path) if manifest_path else DEFAULT_MANIFEST_PATH
    manifest = json.loads(manifest_path.read_text())
    return [entry["id"] for entry in manifest["agents"] if entry.get("enabled", True)]


def get_agent(agent_id: str) -> Optional[ConfigurableAgent]:
    """Used by /council/retest -- the one agent's base config, ready for
    the caller to layer overrides onto."""
    return next((a for a in load_agents_from_manifest() if a.id == agent_id), None)
