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
    """Blocker rules by id, each normalised through RuleConfig so a client
    that omits a defaulted key (label, threshold, ...) isn't mistaken for
    one that altered the rule."""
    from .base import RuleConfig

    normalised = [RuleConfig.model_validate(r).model_dump() if isinstance(r, dict) else r.model_dump() for r in rules]
    return {r["id"]: r for r in normalised if r["stance"] == "blocker"}


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
    if "rules" in config_overrides:
        from .rule_edit import enforce_rule_policy

        enforce_rule_policy(agent, current.get("rules", []), config.rules)  # raises RuleEditError

    config_path.write_text(json.dumps(config.model_dump(), indent=2) + "\n")
    return agent


def _agent_of(entry: dict, agent_id: str, config: dict) -> ConfigurableAgent:
    cls = AGENT_KIND_REGISTRY[entry["kind"]]
    return cls(agent_id=agent_id, config=cls.config_model.model_validate(config))


def apply_rules_request(
    agent_id: str,
    body: dict,
    manifest_path: Optional[PathLike] = None,
    configs_dir: Optional[PathLike] = None,
) -> ConfigurableAgent:
    """PUT /agents/{id}/rules -- the Council tab's structured save. `body` is
    the desired state of the editable parts:

      {"rules": [{"id": "supplier_cost_high", "label": ..., "stance": ..., "value": ...},   # edit
                 {"label": ..., "stance": ..., "condition": {"field", "op", "value"}}],     # add
       "thresholds": {"supplier_cost_increase_threshold_pct": 12}}

    A rule missing from the list is a delete request. This only BUILDS the
    candidate config; save_agent_config is what validates and enforces the
    policy, so nothing here can loosen it."""
    from .rule_edit import RuleEditError, escape_text

    manifest_path = Path(manifest_path) if manifest_path else DEFAULT_MANIFEST_PATH
    configs_dir = Path(configs_dir) if configs_dir else DEFAULT_CONFIGS_DIR
    entry = _find_manifest_entry(agent_id, manifest_path)
    current = json.loads((configs_dir / entry["config"]).read_text())
    current_rules = {r["id"]: r for r in current.get("rules", [])}

    items = body.get("rules")
    if not isinstance(items, list):
        raise RuleEditError("`rules` must be a list.")
    unknown = set(body) - {"rules", "thresholds"}
    if unknown:
        raise RuleEditError(f"Unexpected field(s): {', '.join(sorted(unknown))}.")

    new_rules: list[dict] = []
    taken = set(current_rules)
    for item in items:
        if not isinstance(item, dict):
            raise RuleEditError("Each rule must be an object.")
        rid = item.get("id")
        if rid:
            if rid not in current_rules:
                raise RuleEditError(f"There is no rule '{rid}' to edit.")
            rule = dict(current_rules[rid])
            if rule["stance"] == "blocker":
                if any(k in item and item[k] != rule.get(k) for k in ("label", "stance", "condition")):
                    raise RuleEditError(
                        f"'{rule.get('label') or rid}' is a blocker rule -- system-governed, so it can't be edited "
                        "(its threshold can)."
                    )
            else:
                if "label" in item and item["label"] != rule.get("label"):
                    rule["label"], rule["description"] = item["label"], escape_text(str(item["label"]))
                if "stance" in item:
                    rule["stance"] = item["stance"]
                if "value" in item and rule.get("user_added") and rule.get("condition"):
                    from .rule_edit import build_when
                    from .base import RuleCondition

                    cond = {**rule["condition"], "value": item["value"]}
                    rule["condition"] = cond
                    rule["when"] = build_when(RuleCondition.model_validate(cond))
        else:
            n = 1
            while f"user_{n}" in taken:
                n += 1
            rid = f"user_{n}"
            taken.add(rid)
            cond = item.get("condition")
            if not isinstance(cond, dict):
                raise RuleEditError("A new rule needs a field, an operator and a value.")
            from .base import RuleCondition
            from .rule_edit import build_when

            from .rule_edit import OPERATORS, validate_condition

            if cond.get("op") not in OPERATORS:
                raise RuleEditError(f"'{cond.get('op')}' isn't an operator you can use -- choose one of {', '.join(OPERATORS)}.")
            condition = RuleCondition.model_validate(cond)
            validate_condition(_agent_of(entry, agent_id, current), condition)   # readable field/type/range reasons first
            label = str(item.get("label", ""))
            rule = {
                "id": rid, "label": label, "description": escape_text(label), "fields": [condition.field],
                "when": build_when(condition), "stance": item.get("stance", ""), "keywords": [],
                "threshold": None, "user_added": True, "condition": condition.model_dump(),
            }
        new_rules.append(rule)

    overrides: dict = {"rules": new_rules}
    thresholds = body.get("thresholds") or {}
    allowed_keys = {r["threshold"]["key"] for r in current_rules.values() if r.get("threshold")}
    for key, value in thresholds.items():
        if key not in allowed_keys:
            raise RuleEditError(f"'{key}' isn't a threshold this agent lets you edit.")
        if "." in key:
            head, sub = key.split(".", 1)
            overrides[head] = {**overrides.get(head, current[head]), sub: value}
        else:
            overrides[key] = value
    return save_agent_config(agent_id, overrides, manifest_path=manifest_path, configs_dir=configs_dir)
