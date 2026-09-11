from __future__ import annotations

import operator
from typing import Annotated, Literal, Optional, TypedDict

Stance = Literal["yes", "no", "conditional"]


class AgentPosition(TypedDict):
    agent: str
    stance: Stance
    recommendation: str
    reasoning: str
    driving_constraint: str


class Conflict(TypedDict):
    summary: str
    disagreeing_pairs: list[tuple[str, str]]
    conditional_notes: list[str]


class Reconciliation(TypedDict):
    recommendation: str
    why: str
    trade_off: str
    assumptions: list[str]
    not_considered: list[str]


class ConsiliumState(TypedDict):
    input: str
    routed_agents: list[str]
    routing_reasoning: str
    positions: Annotated[list[AgentPosition], operator.add]
    conflict: Optional[Conflict]
    reconciliation: Optional[Reconciliation]
    trace: Annotated[list[dict], operator.add]
    step_count: int


def initial_state(seed_input: str) -> ConsiliumState:
    return ConsiliumState(
        input=seed_input,
        routed_agents=[],
        routing_reasoning="",
        positions=[],
        conflict=None,
        reconciliation=None,
        trace=[],
        step_count=0,
    )
