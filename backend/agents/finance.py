from __future__ import annotations

from typing import Any, ClassVar, Type

from pydantic import BaseModel, Field

from orchestrator.state import AgentPosition

from .base import AgentConfig, ConfigurableAgent


class FinanceConfig(AgentConfig):
    trigger_keywords: list[str] = [
        "cost", "budget", "supplier", "margin", "3pp", "invoice", "price increase", "spend",
    ]
    margin_erosion_threshold_pts: float = Field(5.0, ge=0, le=100)
    supplier_cost_increase_threshold_pct: float = Field(7.0, ge=0, le=200)
    # Hard breach = 100% (never-exceed line) + this generic overspend test.
    generic_overspend_test_pct: float = Field(5.0, ge=0, le=100)
    # Early-warning threshold, linearly interpolated between these two
    # illustrative anchor points from the spec (month 2 -> 80%, month 12 ->
    # 100%) -- both anchors, not just the interpolation, are editable.
    early_forecast_month: int = Field(2, ge=1, le=12)
    early_forecast_threshold_pct: float = Field(80.0, ge=0, le=100)
    late_forecast_month: int = Field(12, ge=1, le=12)
    late_forecast_threshold_pct: float = Field(100.0, ge=0, le=200)
    cost_of_delay_note: str = (
        "Cost-of-delay lens: weigh the margin/penalty exposure of proceeding "
        "against the revenue-at-risk exposure of not proceeding -- Delivery "
        "quantifies the schedule side of that trade-off."
    )


class FinanceFacts(BaseModel):
    # Neutral/no-concern defaults -- used when the Chief of Staff's LLM
    # extraction is unavailable and evaluation must degrade gracefully
    # rather than crash on a missing required field.
    margin_erosion_pts: float = 0.0
    supplier_cost_increase_pct: float = 0.0
    budget_forecast_utilisation_pct: float = 50.0
    fy_month_elapsed: int = 6


class FinanceAgent(ConfigurableAgent):
    kind = "finance"
    config_model = FinanceConfig
    facts_model: ClassVar[Type[BaseModel]] = FinanceFacts

    def evaluate(self, facts_raw: dict[str, Any]) -> AgentPosition:
        facts = FinanceFacts.model_validate(facts_raw)
        cfg: FinanceConfig = self.config

        if facts.supplier_cost_increase_pct > cfg.supplier_cost_increase_threshold_pct:
            return self._position(
                stance="no",
                recommendation="No -- do not accept the variation as proposed",
                reasoning=(
                    f"A single supplier's cost rises {facts.supplier_cost_increase_pct:g}%, "
                    f"above the {cfg.supplier_cost_increase_threshold_pct:g}% no-line for "
                    "any single supplier cost increase."
                ),
                driving_constraint=(
                    f"{facts.supplier_cost_increase_pct:g}% supplier cost increase "
                    f"(>{cfg.supplier_cost_increase_threshold_pct:g}% threshold)"
                ),
                lead_figure=(
                    f"Supplier cost increase {facts.supplier_cost_increase_pct:g}% "
                    f"(>{cfg.supplier_cost_increase_threshold_pct:g}% line)"
                ),
            )

        if facts.margin_erosion_pts > cfg.margin_erosion_threshold_pts:
            return self._position(
                stance="no",
                recommendation="No -- do not accept the variation as proposed",
                reasoning=(
                    f"Expected project margin erosion of {facts.margin_erosion_pts:g}pts "
                    f"exceeds the {cfg.margin_erosion_threshold_pts:g}pt no-line."
                ),
                driving_constraint=(
                    f"{facts.margin_erosion_pts:g}pt margin erosion "
                    f"(>{cfg.margin_erosion_threshold_pts:g}pt threshold)"
                ),
                lead_figure=(
                    f"Erodes project margin ~{facts.margin_erosion_pts:g}pts "
                    f"(>{cfg.margin_erosion_threshold_pts:g}pt line)"
                ),
            )

        hard_breach_threshold = 100.0 + cfg.generic_overspend_test_pct
        if facts.budget_forecast_utilisation_pct > hard_breach_threshold:
            return self._position(
                stance="no",
                recommendation="No -- 3PP budget forecast breaches the hard overspend line",
                reasoning=(
                    f"Full-year 3PP forecast utilisation of {facts.budget_forecast_utilisation_pct:g}% "
                    f"exceeds the {hard_breach_threshold:g}% hard breach line (100% budget + "
                    f"{cfg.generic_overspend_test_pct:g}% generic overspend test)."
                ),
                driving_constraint=(
                    f"{facts.budget_forecast_utilisation_pct:g}% full-year 3PP forecast "
                    f"(>{hard_breach_threshold:g}% hard breach line)"
                ),
                lead_figure=(
                    f"3PP forecast {facts.budget_forecast_utilisation_pct:g}% of budget "
                    f"(>{hard_breach_threshold:g}% hard line)"
                ),
            )

        concern_threshold = self._early_late_threshold(facts.fy_month_elapsed)
        if facts.budget_forecast_utilisation_pct >= concern_threshold:
            return self._position(
                stance="conditional",
                recommendation="Conditional -- monitor 3PP forecast for the rest of the FY",
                reasoning=(
                    f"Full-year 3PP forecast utilisation of {facts.budget_forecast_utilisation_pct:g}% "
                    f"read in month {facts.fy_month_elapsed} trips the early-warning threshold "
                    f"({concern_threshold:g}% at this point in the FY) -- not yet a breach, but "
                    "flag to monitor all year."
                ),
                driving_constraint=(
                    f"{facts.budget_forecast_utilisation_pct:g}% full-year 3PP forecast in month "
                    f"{facts.fy_month_elapsed} (early-concern threshold {concern_threshold:g}%)"
                ),
                lead_figure=(
                    f"3PP forecast {facts.budget_forecast_utilisation_pct:g}% read early "
                    f"(month {facts.fy_month_elapsed}) -- monitor"
                ),
            )

        return self._position(
            stance="yes",
            recommendation="Yes -- no financial threshold is tripped",
            reasoning="No margin, supplier-cost, or 3PP-forecast threshold is tripped by this change.",
            driving_constraint=(
                f"{facts.budget_forecast_utilisation_pct:g}% full-year 3PP forecast in month "
                f"{facts.fy_month_elapsed} (within the {concern_threshold:g}% threshold for "
                "this point in the FY)"
            ),
            lead_figure=f"No financial threshold tripped ({facts.budget_forecast_utilisation_pct:g}% 3PP forecast)",
        )

    # ---------------------------------------------------- P3.6 rules path --

    def derive(self, raw_facts: dict[str, Any]) -> dict[str, Any]:
        """hard_breach_threshold_pct is config-only (always computable);
        forecast_concern_threshold_pct is the fy_month_elapsed-interpolated
        early-warning line, omitted when fy_month_elapsed isn't stated --
        the rule referencing it (forecast_early_warning) then correctly
        reports fy_month_elapsed as unchecked rather than silently
        defaulting the interpolation."""
        cfg: FinanceConfig = self.config
        derived: dict[str, Any] = {"hard_breach_threshold_pct": 100.0 + cfg.generic_overspend_test_pct}
        month = raw_facts.get("fy_month_elapsed")
        if month is not None:
            derived["forecast_concern_threshold_pct"] = self._early_late_threshold(month)
        return derived

    def derived_field_names(self) -> set[str]:
        return {"hard_breach_threshold_pct", "forecast_concern_threshold_pct"}

    def _early_late_threshold(self, month_elapsed: int) -> float:
        cfg: FinanceConfig = self.config
        if cfg.late_forecast_month == cfg.early_forecast_month:
            return cfg.early_forecast_threshold_pct
        slope = (cfg.late_forecast_threshold_pct - cfg.early_forecast_threshold_pct) / (
            cfg.late_forecast_month - cfg.early_forecast_month
        )
        threshold = cfg.early_forecast_threshold_pct + slope * (month_elapsed - cfg.early_forecast_month)
        return max(min(threshold, 100.0), 0.0)

    def _position(self, *, stance, recommendation, reasoning, driving_constraint, lead_figure) -> AgentPosition:
        cfg: FinanceConfig = self.config
        return AgentPosition(
            agent=self.id,
            stance=stance,
            recommendation=recommendation,
            reasoning=f"{reasoning} {cfg.cost_of_delay_note}",
            driving_constraint=driving_constraint,
            lead_figure=lead_figure,
        )
