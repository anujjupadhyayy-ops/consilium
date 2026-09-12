from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from orchestrator.state import AgentPosition

from .base import AgentConfig, ConfigurableAgent

RAG = Literal["green", "amber", "red"]
_SEVERITY = {"green": 0, "amber": 1, "red": 2}
_FROM_SEVERITY = {v: k for k, v in _SEVERITY.items()}


class DeliveryConfig(AgentConfig):
    # "Effective RAG" floor for unresourced work -- an unresourced milestone
    # can never read better than this, however good its reported status.
    unresourced_floor_rag: RAG = "amber"


class DeliveryFacts(BaseModel):
    budget: float
    actual_pct: float  # 0-1: proportion of budget's worth of work done
    schedule_pct: float  # 0-1: proportion of work planned to be done by now
    spend_to_date: float
    slip_days_before_change: float = 0.0
    is_resourced: bool
    is_on_critical_path: bool
    is_revenue_tagged: bool
    revenue_value: float
    reported_rag_before: RAG
    reported_rag_after: RAG  # if the proposed change is accepted


class DeliveryAgent(ConfigurableAgent):
    kind = "delivery"
    config_model = DeliveryConfig

    def evaluate(self, facts_raw: dict[str, Any]) -> AgentPosition:
        facts = DeliveryFacts.model_validate(facts_raw)
        cfg: DeliveryConfig = self.config

        ev = facts.budget * facts.actual_pct
        pv = facts.budget * facts.schedule_pct
        spi = ev / pv if pv else 1.0
        cpi = ev / facts.spend_to_date if facts.spend_to_date else 1.0
        eac = facts.budget / cpi if cpi else facts.budget

        effective_before = self._effective_rag(facts.reported_rag_before, facts.is_resourced)
        effective_after = self._effective_rag(facts.reported_rag_after, facts.is_resourced)

        crar_before = self._critical_revenue_at_risk(effective_before, facts)
        crar_after = self._critical_revenue_at_risk(effective_after, facts)
        crar_reduction = crar_before - crar_after

        # "Helps schedule" is judged on the *reported* RAG (ignoring the
        # unresourced floor) -- criticality != health, and this is what lets
        # a genuinely-improving-but-unresourced milestone still read as
        # "helps schedule" even though its effective RAG can't move.
        helps_schedule = _SEVERITY[facts.reported_rag_after] < _SEVERITY[facts.reported_rag_before]

        backing = (
            f"SPI {spi:.2f}, CPI {cpi:.2f}, EAC £{eac:,.0f}"
            + (f", {facts.slip_days_before_change:g} days behind schedule pre-change" if facts.slip_days_before_change else "")
        )

        if crar_reduction > 0:
            return self._position(
                stance="yes",
                recommendation="Yes -- pull the milestone forward",
                reasoning=(
                    f"This milestone is on the critical path and revenue-tagged; effective RAG "
                    f"moves {effective_before} -> {effective_after}, reducing Critical Revenue at "
                    f"Risk by £{crar_reduction:,.0f}."
                ),
                crar_before=crar_before,
                crar_after=crar_after,
                backing=backing,
            )

        if helps_schedule:
            reason_bits = []
            if not facts.is_resourced:
                reason_bits.append(
                    f"the milestone is unresourced, so effective RAG is floored at "
                    f"{cfg.unresourced_floor_rag} regardless of reported status"
                )
            if not facts.is_on_critical_path:
                reason_bits.append("it is off the critical path, so it carries no Critical Revenue at Risk")
            if not facts.is_revenue_tagged:
                reason_bits.append("it isn't revenue-tagged, so it carries no Critical Revenue at Risk")
            return self._position(
                stance="conditional",
                recommendation="Conditional -- schedule improves but doesn't yet de-risk revenue",
                reasoning=(
                    f"Reported RAG improves {facts.reported_rag_before} -> {facts.reported_rag_after}, but "
                    + " and ".join(reason_bits)
                    + f" -- Critical Revenue at Risk stays at £{crar_after:,.0f}."
                ),
                crar_before=crar_before,
                crar_after=crar_after,
                backing=backing,
            )

        return self._position(
            stance="no",
            recommendation="No -- doesn't protect critical-path revenue",
            reasoning=(
                f"Reported RAG does not improve ({facts.reported_rag_before} -> {facts.reported_rag_after}); "
                f"this change doesn't touch critical-path revenue exposure, currently £{crar_before:,.0f} "
                "at risk."
            ),
            crar_before=crar_before,
            crar_after=crar_after,
            backing=backing,
        )

    def _effective_rag(self, reported: RAG, is_resourced: bool) -> RAG:
        if is_resourced:
            return reported
        floor = self.config.unresourced_floor_rag
        return _FROM_SEVERITY[max(_SEVERITY[reported], _SEVERITY[floor])]

    def _critical_revenue_at_risk(self, effective_rag: RAG, facts: DeliveryFacts) -> float:
        at_risk = facts.revenue_value if facts.is_revenue_tagged and effective_rag in ("amber", "red") else 0.0
        return at_risk if facts.is_on_critical_path else 0.0

    def _position(self, *, stance, recommendation, reasoning, crar_before, crar_after, backing) -> AgentPosition:
        reduction = crar_before - crar_after
        direction = "reduced" if reduction > 0 else ("increased" if reduction < 0 else "unchanged")
        driving_constraint = (
            f"Critical Revenue at Risk {direction} by £{abs(reduction):,.0f} "
            f"(£{crar_before:,.0f} -> £{crar_after:,.0f})"
        )
        return AgentPosition(
            agent=self.id,
            stance=stance,
            recommendation=recommendation,
            reasoning=reasoning,
            driving_constraint=driving_constraint,
            lead_figure=f"{driving_constraint}; {backing}",
        )
