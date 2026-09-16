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
        agent = agent_cls(agent_id=entry["id"], config=config)
        agent.validate_rules()  # readable RuleError at load, never a silent bad rule
        agents.append(agent)
    return agents


def list_enabled_agent_ids(manifest_path: Optional[PathLike] = None) -> list[str]:
    manifest_path = Path(manifest_path) if manifest_path else DEFAULT_MANIFEST_PATH
    manifest = json.loads(manifest_path.read_text())
    return [entry["id"] for entry in manifest["agents"] if entry.get("enabled", True)]


def get_agent(agent_id: str) -> Optional[ConfigurableAgent]:
    """Used by /council/retest -- the one agent's base config, ready for
    the caller to layer overrides onto."""
    return next((a for a in load_agents_from_manifest() if a.id == agent_id), None)


class UnknownAgentError(KeyError):
    pass


def _find_manifest_entry(agent_id: str, manifest_path: Optional[PathLike] = None) -> dict:
    manifest_path = Path(manifest_path) if manifest_path else DEFAULT_MANIFEST_PATH
    manifest = json.loads(manifest_path.read_text())
    entry = next((e for e in manifest["agents"] if e["id"] == agent_id), None)
    if entry is None:
        raise UnknownAgentError(agent_id)
    return entry


def get_agent_config_raw(
    agent_id: str,
    manifest_path: Optional[PathLike] = None,
    configs_dir: Optional[PathLike] = None,
) -> dict:
    """The raw persisted JSON for one agent's config -- used by
    GET /agents/{id}/config so the Council UI can hydrate from truth
    (looks the agent up regardless of enabled/disabled state)."""
    configs_dir = Path(configs_dir) if configs_dir else DEFAULT_CONFIGS_DIR
    entry = _find_manifest_entry(agent_id, manifest_path)
    return json.loads((configs_dir / entry["config"]).read_text())


class BlockerRuleImmutableError(ValueError):
    """A save attempted to add, remove or alter a rule whose stance is
    `blocker` -- system-governed (P3.6 §5.2). Threshold/config-scalar edits
    and non-blocker rule edits are unaffected."""


def _blocker_rules(rules: list) -> dict:
    return {r["id"] if isinstance(r, dict) else r.id: r for r in rules if (r["stance"] if isinstance(r, dict) else r.stance) == "blocker"}


def save_agent_config(
    agent_id: str,
    config_overrides: dict,
    manifest_path: Optional[PathLike] = None,
    configs_dir: Optional[PathLike] = None,
) -> ConfigurableAgent:
    """PUT /agents/{id}/config -- P3.6's persistence seam. Merges
    `config_overrides` over the currently-persisted config, validates the
    result through that agent kind's Pydantic model (rules count/length,
    numeric bounds -- a malformed config raises pydantic.ValidationError
    and is never written), rejects any change to a blocker-stance rule
    (BlockerRuleImmutableError), validates every rule's `when` expression
    is safe and resolvable (RuleError), then writes the merged, validated
    config back to configs/*.json so it survives a restart and a fork ships
    with these as the new defaults. Returns an agent instance built from
    the saved config, ready to check/narrate immediately.
    """
    manifest_path = Path(manifest_path) if manifest_path else DEFAULT_MANIFEST_PATH
    configs_dir = Path(configs_dir) if configs_dir else DEFAULT_CONFIGS_DIR
    entry = _find_manifest_entry(agent_id, manifest_path)

    agent_cls = AGENT_KIND_REGISTRY[entry["kind"]]
    config_path = configs_dir / entry["config"]
    current = json.loads(config_path.read_text())

    if "rules" in config_overrides:
        current_blockers = _blocker_rules(current.get("rules", []))
        new_blockers = _blocker_rules(config_overrides["rules"])
        if current_blockers != new_blockers:
            raise BlockerRuleImmutableError(
                "blocker-stance rules are system-governed and cannot be added, removed or altered "
                "via config save (P3.6 §5.2)."
            )

    merged = {**current, **config_overrides}
    config = agent_cls.config_model.model_validate(merged)  # raises on anything malformed
    agent = agent_cls(agent_id=agent_id, config=config)
    agent.validate_rules()  # raises RuleError on an unsafe/unresolvable `when`

    config_path.write_text(json.dumps(config.model_dump(), indent=2) + "\n")
    return agent
