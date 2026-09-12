from __future__ import annotations

from typing import Any, ClassVar, Type

from pydantic import BaseModel

from orchestrator.state import AgentPosition

from .base import AgentConfig, ConfigurableAgent

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
    capacity_amber_threshold_pct: float = 90.0
    capacity_red_threshold_pct: float = 100.0
    spend_amber_threshold_pct: float = 95.0
    spend_red_threshold_pct: float = 100.0
    savings_amber_threshold_ratio: float = 0.9
    savings_red_threshold_ratio: float = 0.7


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
