from __future__ import annotations

from typing import Any, ClassVar, Literal, Type

from pydantic import BaseModel

from orchestrator.state import AgentPosition

from .base import AgentConfig, ConfigurableAgent

AdverseDirection = Literal["over", "under"]


class PMOConfig(AgentConfig):
    trigger_keywords: list[str] = [
        "contract variation", "change control", "governance", "tolerance", "compliance", "pme", "gate",
    ]
    # PRINCE2/MSP delegated tolerance per dimension, as a % variance the PM
    # can absorb before an exception has to be escalated.
    tolerances_pct: dict[str, float] = {
        "cost": 10.0,
        "time": 10.0,
        "scope": 5.0,
        "quality": 5.0,
        "risk": 10.0,
        "benefit": 10.0,
    }
    # Which direction of variance is adverse per dimension -- "over" (a cost
    # or time variance above tolerance is bad) vs "under" (a benefit or
    # quality variance below tolerance is bad).
    adverse_direction: dict[str, AdverseDirection] = {
        "cost": "over",
        "time": "over",
        "scope": "over",
        "quality": "under",
        "risk": "over",
        "benefit": "under",
    }
    # A breach beyond tolerance * this multiple isn't a mere exception --
    # it needs a full re-baseline/rejection, not a change request.
    hard_reject_multiple_of_tolerance: float = 2.0
    contract_variation_gate_name: str = "Change Control Gate 2 (contract variation)"
    tolerance_breach_gate_name: str = "Change Control Gate 1 (tolerance exception)"


class PMOFacts(BaseModel):
    is_contract_variation: bool = False
    continued_business_case_justified: bool = True
    portfolio_contention: bool = False
    # % variance per PRINCE2 dimension this decision represents, e.g.
    # {"cost": 15.0} for a 15% cost increase. Omitted dimensions = no variance.
    tolerance_variances_pct: dict[str, float] = {}


class PMOAgent(ConfigurableAgent):
    kind = "pmo"
    config_model = PMOConfig
    facts_model: ClassVar[Type[BaseModel]] = PMOFacts

    def evaluate(self, facts_raw: dict[str, Any]) -> AgentPosition:
        facts = PMOFacts.model_validate(facts_raw)
        cfg: PMOConfig = self.config

        if not facts.continued_business_case_justified:
            return self._position(
                stance="no",
                recommendation="No -- lacks continued business-case justification",
                reasoning="PRINCE2's continued-business-case-justification principle is not met.",
                driving_constraint="Continued business case: not justified",
            )

        breaches, hard_rejects = self._tolerance_breaches(facts, cfg)

        if hard_rejects:
            dim, variance, tolerance = hard_rejects[0]
            return self._position(
                stance="no",
                recommendation=f"No -- {dim} variance exceeds what a change request can absorb",
                reasoning=(
                    f"{dim.title()} variance of {variance:+.0f}% is more than "
                    f"{cfg.hard_reject_multiple_of_tolerance:g}x the {tolerance:g}% delegated "
                    "tolerance -- this needs a full re-baseline, not a change request."
                ),
                driving_constraint=f"{dim} variance {variance:+.0f}% vs {tolerance:g}% tolerance (hard reject)",
            )

        gates = []
        reasons = []
        if breaches:
            for dim, variance, tolerance in breaches:
                gates.append(cfg.tolerance_breach_gate_name)
                reasons.append(f"{dim} variance {variance:+.0f}% breaches the {tolerance:g}% delegated tolerance")
        if facts.is_contract_variation:
            gates.append(cfg.contract_variation_gate_name)
            reasons.append("this is a contract variation, which always needs sign-off regardless of tolerance status")

        if gates:
            unique_gates = list(dict.fromkeys(gates))
            reasoning = "; ".join(reasons) + "."
            if facts.portfolio_contention:
                reasoning += " It also re-sequences shared resource against another workstream's plan."
            return self._position(
                stance="conditional",
                recommendation=f"Conditional yes -- only via {', '.join(unique_gates)}",
                reasoning=reasoning,
                driving_constraint=f"Requires {', '.join(unique_gates)} sign-off before proceeding",
            )

        return self._position(
            stance="yes",
            recommendation="Yes -- compliant, within tolerance, no gate required",
            reasoning="No PRINCE2/MSP tolerance is breached and this isn't a contract variation.",
            driving_constraint="Within all delegated tolerances; no gate required",
        )

    def _tolerance_breaches(self, facts: PMOFacts, cfg: PMOConfig):
        breaches = []
        hard_rejects = []
        for dim, variance in facts.tolerance_variances_pct.items():
            tolerance = cfg.tolerances_pct.get(dim)
            if tolerance is None:
                continue
            direction = cfg.adverse_direction.get(dim, "over")
            adverse = (direction == "over" and variance > tolerance) or (
                direction == "under" and variance < -tolerance
            )
            if not adverse:
                continue
            breaches.append((dim, variance, tolerance))
            if abs(variance) > tolerance * cfg.hard_reject_multiple_of_tolerance:
                hard_rejects.append((dim, variance, tolerance))
        return breaches, hard_rejects

    def _position(self, *, stance, recommendation, reasoning, driving_constraint) -> AgentPosition:
        return AgentPosition(
            agent=self.id,
            stance=stance,
            recommendation=recommendation,
            reasoning=reasoning,
            driving_constraint=driving_constraint,
            lead_figure=driving_constraint,
        )
