from __future__ import annotations

import operator
from typing import Annotated, Literal, Optional, TypedDict

# "blocker" added in P2: a hard, agent-agnostic operational/structural
# constraint that the reconcile engine treats as decisive regardless of
# any cost/schedule trade-off (see orchestrator/master.py).
Stance = Literal["yes", "no", "conditional", "blocker"]


class AgentPosition(TypedDict):
    agent: str
    stance: Stance
    recommendation: str
    reasoning: str
    # Terse "metric vs threshold" string -- what reconcile uses to build the
    # trade-off text (e.g. "15% supplier cost increase (>7% threshold)").
    driving_constraint: str
    # The doc-specified headline figure for this agent (docs/P2-Agent-Logic-Spec.md),
    # e.g. Delivery's "Critical Revenue at Risk reduced by £420k; SPI 0.85" --
    # narrative where driving_constraint is terse.
    lead_figure: str


class Conflict(TypedDict):
    summary: str
    disagreeing_pairs: list[tuple[str, str]]
    conditional_notes: list[str]
    blocker_notes: list[str]


class Reconciliation(TypedDict):
    recommendation: str
    why: str
    trade_off: str
    assumptions: list[str]
    not_considered: list[str]


class ConsiliumState(TypedDict):
    input: str
    # Structured, per-agent decision inputs the config-driven agents evaluate
    # against (facts[agent_id] -> that agent's raw facts dict). `input` stays
    # as the human-readable scenario text for display; agents never parse it.
    facts: dict
    routed_agents: list[str]
    routing_reasoning: str
    positions: Annotated[list[AgentPosition], operator.add]
    conflict: Optional[Conflict]
    reconciliation: Optional[Reconciliation]
    trace: Annotated[list[dict], operator.add]
    step_count: int


def initial_state(seed_input: str, facts: Optional[dict] = None) -> ConsiliumState:
    return ConsiliumState(
        input=seed_input,
        facts=facts or {},
        routed_agents=[],
        routing_reasoning="",
        positions=[],
        conflict=None,
        reconciliation=None,
        trace=[],
        step_count=0,
    )
