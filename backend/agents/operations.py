from __future__ import annotations

from typing import Any, ClassVar, Type

from pydantic import BaseModel, Field

from orchestrator.state import AgentPosition

from .base import AgentConfig, ConfigurableAgent
from .rules import CheckResult

SIGNAL_NAMES = {
    "capacity": "Capacity",
    "third_party_spend": "Third-party spend",
    "savings": "Savings delivery",
    "supplier_sla": "Supplier/SLA & licence-kit control",
}


class OperationsConfig(AgentConfig):
    trigger_keywords: list[str] = [
        "capacity", "licence", "license", "sla", "kit", "resourcing", "operational", "supplier",
    ]
    capacity_amber_threshold_pct: float = Field(90.0, ge=0, le=200)
    capacity_red_threshold_pct: float = Field(100.0, ge=0, le=200)
    spend_amber_threshold_pct: float = Field(95.0, ge=0, le=200)
    spend_red_threshold_pct: float = Field(100.0, ge=0, le=200)
    savings_amber_threshold_ratio: float = Field(0.9, ge=0, le=2)
    savings_red_threshold_ratio: float = Field(0.7, ge=0, le=2)


class OperationsFacts(BaseModel):
    # Neutral/no-concern defaults (all-green) -- used when the Chief of
    # Staff's LLM extraction is unavailable and evaluation must degrade
    # gracefully.
    capacity_utilisation_pct_if_accepted: float = Field(50.0, title="capacity utilisation if accepted (%)")
    third_party_spend_pct_of_budget: float = Field(50.0, title="third-party spend (% of budget)")
    savings_delivery_ratio: float = Field(1.0, title="savings delivered vs committed (ratio)")
    licence_provisioned_for_new_date: bool = Field(True, title="licence provisioned for the new date")
    supplier_sla_in_place: bool = Field(True, title="supplier SLA in place")


class OperationsAgent(ConfigurableAgent):
    kind = "operations"
    config_model = OperationsConfig
    facts_model: ClassVar[Type[BaseModel]] = OperationsFacts

    # ---------------------------------------------------- P3.6 rules path --

    # Every threshold rule references its own config scalar directly (e.g.
    # `capacity_utilisation_pct_if_accepted >= capacity_red_threshold_pct`)
    # -- no arithmetic/flattening needed, so derive() stays the base no-op.

    _RULE_SIGNAL = {
        "capacity_red": SIGNAL_NAMES["capacity"], "capacity_amber": SIGNAL_NAMES["capacity"],
        "spend_red": SIGNAL_NAMES["third_party_spend"], "spend_amber": SIGNAL_NAMES["third_party_spend"],
        "savings_red": SIGNAL_NAMES["savings"], "savings_amber": SIGNAL_NAMES["savings"],
        "licence_not_provisioned": SIGNAL_NAMES["supplier_sla"], "supplier_sla_not_in_place": SIGNAL_NAMES["supplier_sla"],
    }
    _SEVERITY_WORD = {"blocker": "RED", "conditional": "AMBER"}
    _STANCE_SEVERITY = {"yes": 0, "conditional": 1, "no": 2, "blocker": 3}

    def _position_from_check(self, raw_facts: dict[str, Any], result: CheckResult) -> AgentPosition:
        """evaluate()'s old driving_constraint names the WEAKEST signal(s)
        as "Weakest signal: <name(s)> (<RAG>)", joining every signal tied at
        that severity into one comma-separated name list (never an average,
        never a per-signal breakdown) -- the base class's generic "; "-join
        of each fired rule's own rendered description doesn't reproduce
        that shape when more than one DIFFERENT signal ties, so Operations
        rebuilds it the same way evaluate() did, via the signal-name lookup
        above rather than per-rule dynamic text."""
        if result.stance not in ("blocker", "conditional"):
            return super()._position_from_check(raw_facts, result)

        top_severity = max(self._STANCE_SEVERITY[f.stance] for f in result.fired)
        top_fired = [f for f in result.fired if self._STANCE_SEVERITY[f.stance] == top_severity]
        signal_names: list[str] = []
        for f in top_fired:
            name = self._RULE_SIGNAL.get(f.id, f.id)
            if name not in signal_names:
                signal_names.append(name)

        driving_constraint = f"Weakest signal: {', '.join(signal_names)} ({self._SEVERITY_WORD[result.stance]})"
        env: dict[str, Any] = self._rule_env(raw_facts)

        def render(desc: str) -> str:
            try:
                return desc.format(**env)
            except (KeyError, ValueError, IndexError):
                return desc

        reasoning = "; ".join(render(f.description) for f in result.fired) + "."
        recommendation = (
            "Blocked -- cannot absorb the change as scoped" if result.stance == "blocker"
            else "Conditional -- feasible, but degrades an operational signal"
        )
        return AgentPosition(
            agent=self.id,
            stance=result.stance,
            recommendation=recommendation,
            reasoning=reasoning,
            driving_constraint=driving_constraint,
            lead_figure=driving_constraint,
        )

