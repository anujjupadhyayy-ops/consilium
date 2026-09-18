from __future__ import annotations

from typing import Any, ClassVar, Literal, Type

from pydantic import BaseModel, Field

from .base import AgentConfig, ConfigurableAgent

RAG = Literal["green", "amber", "red"]
_SEVERITY = {"green": 0, "amber": 1, "red": 2}


class DeliveryConfig(AgentConfig):
    trigger_keywords: list[str] = [
        "milestone", "schedule", "critical path", "delay", "delivery date", "resourcing", "slip",
    ]
    # "Effective RAG" floor for unresourced work -- an unresourced milestone
    # can never read better than this, however good its reported status.
    unresourced_floor_rag: RAG = "amber"


class DeliveryFacts(BaseModel):
    # Neutral/no-concern defaults -- used when the Chief of Staff's LLM
    # extraction is unavailable and evaluation must degrade gracefully.
    # `description` is plain-English guidance for the extraction prompt.
    budget: float = Field(
        100_000.0, title="milestone budget",
        description="The total budget of the milestone, as a plain number in the currency used (no symbol).")
    actual_pct: float = Field(  # 0-1
        0.5, title="work completed so far (share of budget)",
        description="How much of the milestone's work is done so far, as a fraction between 0 and 1 "
                    "(e.g. '40% complete' is 0.4).")
    schedule_pct: float = Field(  # 0-1
        0.5, title="work planned to be done by now (share)",
        description="How much of the milestone's work the plan says should be done by now, as a fraction "
                    "between 0 and 1 (e.g. 'should be 60% complete' is 0.6).")
    spend_to_date: float = Field(
        50_000.0, title="spend to date",
        description="Money already spent on the milestone so far, as a plain number in the currency used.")
    slip_days_before_change: float = Field(
        0.0, title="days behind schedule before the change",
        description="How many days the milestone is already behind its planned date before the proposed change.")
    is_resourced: bool = Field(
        True, title="milestone is resourced",
        description="True if people/capacity are assigned to deliver the milestone; false if it is unstaffed.")
    is_on_critical_path: bool = Field(
        False, title="milestone is on the critical path",
        description="True if the milestone is on the project's critical path, so a slip delays the whole delivery date.")
    is_revenue_tagged: bool = Field(
        False, title="milestone is revenue-tagged",
        description="True if revenue is tied to the milestone being completed (e.g. an invoicing or payment milestone).")
    revenue_value: float = Field(
        0.0, title="revenue tied to the milestone",
        description="The amount of revenue that depends on this milestone, as a plain number in the currency used.")
    reported_rag_before: RAG = Field(
        "green", title="reported RAG status before the change",
        description="The milestone's red/amber/green status as reported before the proposed change.")
    reported_rag_after: RAG = Field(  # if accepted
        "green", title="reported RAG status after the change",
        description="The milestone's red/amber/green status it would be reported at if the change is accepted.")


class DeliveryAgent(ConfigurableAgent):
    kind = "delivery"
    config_model = DeliveryConfig
    facts_model: ClassVar[Type[BaseModel]] = DeliveryFacts

    # ---------------------------------------------------- P3.6 rules path --

    def derive(self, raw_facts: dict[str, Any]) -> dict[str, Any]:
        """rag_{before,after}_severity are cheap ordinal versions of the two
        RAG facts, always available once both are stated -- used by every
        rule's `when` for the "did it improve" comparison (the evaluator
        has no ordinal-string comparison, only numeric/boolean/==/!=).

        crar_before/after/reduction/direction/abs_reduction need ALL SIX
        of is_resourced, is_on_critical_path, is_revenue_tagged,
        revenue_value, reported_rag_before, reported_rag_after -- exactly
        the fields evaluate() read to compute the same formula -- and are
        omitted entirely (not partially computed) if any one is missing.
        """
        derived: dict[str, Any] = {}
        before, after = raw_facts.get("reported_rag_before"), raw_facts.get("reported_rag_after")
        if before is not None and after is not None:
            derived["rag_before_severity"] = _SEVERITY[before]
            derived["rag_after_severity"] = _SEVERITY[after]

        is_resourced = raw_facts.get("is_resourced")
        is_on_critical_path = raw_facts.get("is_on_critical_path")
        is_revenue_tagged = raw_facts.get("is_revenue_tagged")
        revenue_value = raw_facts.get("revenue_value")
        needed = (before, after, is_resourced, is_on_critical_path, is_revenue_tagged, revenue_value)
        if any(v is None for v in needed):
            return derived

        cfg: DeliveryConfig = self.config
        floor_severity = _SEVERITY[cfg.unresourced_floor_rag]
        effective_before = _SEVERITY[before] if is_resourced else max(_SEVERITY[before], floor_severity)
        effective_after = _SEVERITY[after] if is_resourced else max(_SEVERITY[after], floor_severity)

        def crar(effective_severity: int) -> float:
            at_risk = revenue_value if (is_revenue_tagged and effective_severity >= _SEVERITY["amber"]) else 0.0
            return at_risk if is_on_critical_path else 0.0

        crar_before, crar_after = crar(effective_before), crar(effective_after)
        reduction = crar_before - crar_after
        derived.update({
            "crar_before": crar_before,
            "crar_after": crar_after,
            "crar_reduction": reduction,
            "crar_abs_reduction": abs(reduction),
            "crar_direction": "reduced" if reduction > 0 else ("increased" if reduction < 0 else "unchanged"),
        })
        return derived

    def derived_field_names(self) -> set[str]:
        return {
            "rag_before_severity", "rag_after_severity", "crar_before", "crar_after",
            "crar_reduction", "crar_abs_reduction", "crar_direction",
        }

