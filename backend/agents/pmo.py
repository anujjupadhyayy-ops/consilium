from __future__ import annotations

from typing import Any, ClassVar, Literal, Type

from pydantic import BaseModel, Field, field_validator

from orchestrator.state import AgentPosition

from .base import AgentConfig, ConfigurableAgent
from .rules import CheckResult

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
    hard_reject_multiple_of_tolerance: float = Field(2.0, ge=1.0, le=10.0)
    contract_variation_gate_name: str = "Change Control Gate 2 (contract variation)"
    tolerance_breach_gate_name: str = "Change Control Gate 1 (tolerance exception)"

    @field_validator("tolerances_pct")
    @classmethod
    def _validate_tolerances(cls, values: dict[str, float]) -> dict[str, float]:
        for dim, pct in values.items():
            if not (0 <= pct <= 200):
                raise ValueError(f"tolerances_pct[{dim}]={pct} out of range 0-200")
        return values


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

    # ---------------------------------------------------- P3.6 rules path --

    def derive(self, raw_facts: dict[str, Any]) -> dict[str, Any]:
        """Flattens the dict-shaped `tolerance_variances_pct` fact and the
        dict-shaped `tolerances_pct`/`adverse_direction` config into scalar
        names a rule's `when`/`description` can reference directly (the
        evaluator has no subscript access, by design -- this flattening
        happens in trusted code, not in an untrusted rule string). A
        variance dimension omitted from a STATED tolerance_variances_pct
        dict means "no variance" (PMOFacts' own long-standing docstring),
        so every configured dimension gets a tv_<dim> whenever the dict
        itself is stated at all -- but if the dict wasn't stated, no
        tv_<dim> is produced for any dimension, and every tolerance rule
        correctly reports it as unchecked rather than assuming zero."""
        cfg: PMOConfig = self.config
        derived: dict[str, Any] = {}
        for dim, tolerance in cfg.tolerances_pct.items():
            hard_reject = tolerance * cfg.hard_reject_multiple_of_tolerance
            derived[f"tol_{dim}"] = tolerance
            derived[f"tol_{dim}_hard_reject"] = hard_reject
            derived[f"neg_tol_{dim}"] = -tolerance
            derived[f"neg_tol_{dim}_hard_reject"] = -hard_reject

        variances = raw_facts.get("tolerance_variances_pct")
        if isinstance(variances, dict):
            for dim in cfg.tolerances_pct:
                derived[f"tv_{dim}"] = variances.get(dim, 0.0)
        return derived

    def derived_field_names(self) -> set[str]:
        names: set[str] = set()
        for dim in self.config.tolerances_pct:
            names |= {f"tol_{dim}", f"tol_{dim}_hard_reject", f"neg_tol_{dim}", f"neg_tol_{dim}_hard_reject", f"tv_{dim}"}
        return names

    def extra_reasoning_context(self, raw_facts: dict[str, Any]) -> str:
        """P3.6 change 6: portfolio_contention has no rule of its own --
        kept as reasoning context on a triggered position, matching
        evaluate()'s old behaviour exactly (appended only when the agent
        triggers, never a trigger by itself)."""
        if raw_facts.get("portfolio_contention") is True:
            return "It also re-sequences shared resource against another workstream's plan."
        return ""

    def _position_from_check(self, raw_facts: dict[str, Any], result: CheckResult) -> AgentPosition:
        """The generic base implementation joins fired rules' descriptions
        with "; " -- faithful for "no"/"blocker" stances here, but PMO's old
        `conditional` driving_constraint collapses every breaching dimension
        onto AT MOST TWO shared gate names ("Requires X, Y sign-off before
        proceeding"), not a per-dimension list. Overridden only for that
        stance so the differential test's equivalence holds exactly rather
        than approximately."""
        if result.stance != "conditional":
            return super()._position_from_check(raw_facts, result)

        env: dict[str, Any] = {**raw_facts, **self.derive(raw_facts), **self._config_scalar_env()}

        def render(desc: str) -> str:
            try:
                return desc.format(**env)
            except (KeyError, ValueError, IndexError):
                return desc

        gate_names: list[str] = []
        for f in result.fired:
            if f.stance != "conditional":
                continue
            gate_field = "contract_variation_gate_name" if f.id == "contract_variation_gate" else "tolerance_breach_gate_name"
            gate = env.get(gate_field)
            if gate and gate not in gate_names:
                gate_names.append(gate)
        joined_gates = ", ".join(gate_names)

        reasoning = "; ".join(render(f.description) for f in result.fired) + "."
        extra = self.extra_reasoning_context(raw_facts)
        if extra:
            reasoning = f"{reasoning} {extra}"

        driving_constraint = f"Requires {joined_gates} sign-off before proceeding"
        return AgentPosition(
            agent=self.id,
            stance="conditional",
            recommendation=f"Conditional yes -- only via {joined_gates}",
            reasoning=reasoning,
            driving_constraint=driving_constraint,
            lead_figure=driving_constraint,
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
