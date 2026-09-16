from __future__ import annotations

from typing import Any, ClassVar, Type

from pydantic import BaseModel, Field

from orchestrator.state import AgentPosition

from .base import AgentConfig, ConfigurableAgent
from .rules import CheckResult

_SEVERITY = {"green": 0, "amber": 1, "red": 2}

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
    capacity_utilisation_pct_if_accepted: float = 50.0
    third_party_spend_pct_of_budget: float = 50.0
    savings_delivery_ratio: float = 1.0
    licence_provisioned_for_new_date: bool = True
    supplier_sla_in_place: bool = True


class OperationsAgent(ConfigurableAgent):
    kind = "operations"
    config_model = OperationsConfig
    facts_model: ClassVar[Type[BaseModel]] = OperationsFacts

    def evaluate(self, facts_raw: dict[str, Any]) -> AgentPosition:
        facts = OperationsFacts.model_validate(facts_raw)
        cfg: OperationsConfig = self.config

        signals = {
            "capacity": self._threshold_rag(
                facts.capacity_utilisation_pct_if_accepted, cfg.capacity_amber_threshold_pct, cfg.capacity_red_threshold_pct
            ),
            "third_party_spend": self._threshold_rag(
                facts.third_party_spend_pct_of_budget, cfg.spend_amber_threshold_pct, cfg.spend_red_threshold_pct
            ),
            "savings": self._inverse_threshold_rag(
                facts.savings_delivery_ratio, cfg.savings_amber_threshold_ratio, cfg.savings_red_threshold_ratio
            ),
            "supplier_sla": "green" if (facts.licence_provisioned_for_new_date and facts.supplier_sla_in_place) else "red",
        }

        from_severity = {v: k for k, v in _SEVERITY.items()}
        weakest_severity = max(_SEVERITY[rag] for rag in signals.values())
        weakest_signals = [name for name, rag in signals.items() if _SEVERITY[rag] == weakest_severity]
        weakest_rag = from_severity[weakest_severity]
        weakest_label = ", ".join(SIGNAL_NAMES[name] for name in weakest_signals)

        detail = "; ".join(f"{SIGNAL_NAMES[name]}: {rag}" for name, rag in signals.items())

        if weakest_rag == "red":
            stance = "blocker"
            recommendation = "Blocked -- cannot absorb the change as scoped"
            reasoning = (
                f"Operational Health is the weakest of four signals, not an average: "
                f"{weakest_label} is RED, which governs the verdict regardless of the "
                f"other three ({detail})."
            )
        elif weakest_rag == "amber":
            stance = "conditional"
            recommendation = "Conditional -- feasible, but degrades an operational signal"
            reasoning = (
                f"{weakest_label} is AMBER, the weakest of the four signals ({detail}) -- "
                "feasible, but this signal degrades if the change proceeds."
            )
        else:
            stance = "yes"
            recommendation = "Yes -- the operation can absorb this"
            reasoning = f"All four operational signals hold green ({detail})."

        driving_constraint = f"Weakest signal: {weakest_label} ({weakest_rag.upper()})"
        return AgentPosition(
            agent=self.id,
            stance=stance,
            recommendation=recommendation,
            reasoning=reasoning,
            driving_constraint=driving_constraint,
            lead_figure=f"{driving_constraint} -- {detail}",
        )

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
        env: dict[str, Any] = {**raw_facts, **self.derive(raw_facts), **self._config_scalar_env()}

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

    def _threshold_rag(self, value: float, amber_at: float, red_at: float) -> str:
        if value >= red_at:
            return "red"
        if value >= amber_at:
            return "amber"
        return "green"

    def _inverse_threshold_rag(self, ratio: float, amber_below: float, red_below: float) -> str:
        if ratio < red_below:
            return "red"
        if ratio < amber_below:
            return "amber"
        return "green"
