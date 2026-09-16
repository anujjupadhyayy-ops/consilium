from __future__ import annotations

from typing import Any, ClassVar, Type

from pydantic import BaseModel, Field

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

    # ---------------------------------------------------- P3.6 rules path --

    def extra_reasoning_context(self, raw_facts: dict[str, Any]) -> str:
        return self.config.cost_of_delay_note

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
