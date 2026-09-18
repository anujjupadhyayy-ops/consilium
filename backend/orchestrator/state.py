from __future__ import annotations

import operator
from typing import Annotated, Literal, NotRequired, Optional, TypedDict

# "blocker" added in P2: a hard, agent-agnostic operational/structural
# constraint that the reconcile engine treats as decisive regardless of
# any cost/schedule trade-off (see orchestrator/chief_of_staff.py).
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


class Check(TypedDict):
    """P3.6: one per agent, every run -- no agent is ever skipped. `triggered`
    mirrors `stance is not None` (kept as its own bool for a cheap frontend/
    API check without re-deriving it). `fired` is the list of rule ids that
    fired (most severe stance wins the agent's overall `stance`); `unchecked`
    is every field referenced by >=1 rule that wasn't stated; `unclear` is
    the tripwire subset of `unchecked` where a blocker rule's keyword was
    mentioned in the input text but the field itself wasn't confirmed.
    `evidence` carries the verified quotes behind every stated field (or
    "seeded" for seed-supplied facts); `provenance` says how each stated
    field was obtained.
    """

    agent: str
    triggered: bool
    stance: Optional[Stance]
    fired: list[str]
    unchecked: list[str]
    unclear: list[str]
    # Blocker fields (referenced by a blocker rule) that are unstated AND
    # whose tripwire keyword was NOT found in the input either -- the
    # weaker of the two verdict-cap levels (§5.5): the verdict may still
    # proceed on stated facts, but must disclose these as not in the brief.
    blocker_not_mentioned: list[str]
    evidence: dict[str, list[str]]
    provenance: dict[str, Literal["seeded", "extracted"]]
    # field name -> the human label (the facts model's `title`) for every
    # fact of this agent. The UI shows these, never a raw field name.
    labels: dict[str, str]


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
    # Facts that couldn't be checked, structured for the verdict panel:
    # {"confirm_first": [{agent, field, label}], "groups": [{agent, items:
    # [{field, label, blocker, unclear}]}]}. Display data only -- it never
    # feeds a stance or the verdict's direction.
    not_checked: NotRequired[dict]


def _max2(a: int, b: int) -> int:
    """Plain wrapper around max() -- LangGraph introspects a reducer's
    signature to wire it up, and the builtin `max` has none to introspect."""
    return max(a, b)


def merge_dicts(a: dict, b: dict) -> dict:
    """LangGraph reducer for `checks`: each of the four parallel agent nodes
    writes exactly one {agent_id: Check} entry in the same superstep: the
    default "last write wins" merge would silently drop three of the four,
    same pitfall `positions`/`trace` already guard against with
    `operator.add` -- this is that reducer's dict-merge equivalent."""
    return {**a, **b}


class ConsiliumState(TypedDict):
    input: str
    # Structured, per-agent decision inputs each agent checks its rules
    # against (facts[agent_id] -> that agent's raw facts dict, seed-authored
    # or None-valued for "not stated"). `input` stays as the human-readable
    # scenario text for display; a seed-populated agent never parses it, a
    # free-text agent extracts its own facts from it (see agents/base.py).
    facts: dict
    checks: Annotated[dict, merge_dicts]
    positions: Annotated[list[AgentPosition], operator.add]
    conflict: Optional[Conflict]
    reconciliation: Optional[Reconciliation]
    trace: Annotated[list[dict], operator.add]
    # Every agent in the fan-out superstep writes the same literal (1) --
    # `max` resolves concurrent identical writes safely without a data
    # channel raising on "more than one value this step" (LangGraph's
    # default LastValue channel rejects concurrent writes outright, even
    # equal ones).
    step_count: Annotated[int, _max2]


def initial_state(seed_input: str, facts: Optional[dict] = None) -> ConsiliumState:
    return ConsiliumState(
        input=seed_input,
        facts=facts or {},
        checks={},
        positions=[],
        conflict=None,
        reconciliation=None,
        trace=[],
        step_count=0,
    )
