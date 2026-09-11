from __future__ import annotations

from .state import AgentPosition, Conflict, ConsiliumState, Reconciliation
from .termination import assert_bounded
from .trace import make_trace_event, next_step

ALL_AGENT_NAMES = ["finance", "delivery", "pmo", "operations"]

# P1's routing is deterministic: the one seed in scope is designed to need
# all 4 functions, so there's no selection judgement to make yet. Real
# selective/LLM-driven routing (the master saying "operations isn't needed
# here") is P2/P4 scope -- swap this function's body then; route_node's
# signature and its trace/state contract stay the same.
ROUTING_REASONING = (
    "Supplier milestone variations touch cost, schedule, governance, and "
    "operational capacity -- all four functions are relevant here."
)

OPERATIONAL_BLOCKER_POLICY = (
    "P1's reconciliation policy treats a hard operational blocker as decisive, "
    "independent of the cost/schedule trade-off: a plan that can't be "
    "executed is moot regardless of who wins the cost/schedule argument."
)


def route_node(state: ConsiliumState) -> dict:
    step = next_step(state)
    event = make_trace_event(
        step=step,
        kind="route",
        agent=None,
        summary=f"Routed to: {', '.join(ALL_AGENT_NAMES)}",
        payload={"routed_agents": ALL_AGENT_NAMES, "reasoning": ROUTING_REASONING},
    )
    return {
        "routed_agents": ALL_AGENT_NAMES,
        "routing_reasoning": ROUTING_REASONING,
        "trace": [event],
        "step_count": state["step_count"] + 1,
    }


def detect_conflict(positions: list[AgentPosition]) -> Conflict:
    yes_side = [p for p in positions if p["stance"] == "yes"]
    no_side = [p for p in positions if p["stance"] == "no"]
    conditional_side = [p for p in positions if p["stance"] == "conditional"]

    disagreeing_pairs = [(y["agent"], n["agent"]) for y in yes_side for n in no_side]
    conditional_notes = [f"{p['agent']}: {p['driving_constraint']}" for p in conditional_side]

    if disagreeing_pairs:
        a, b = disagreeing_pairs[0]
        summary = f"{a} and {b} disagree on whether to proceed"
    else:
        summary = "No direct yes/no clash; conditional constraints apply"

    return Conflict(
        summary=summary,
        disagreeing_pairs=disagreeing_pairs,
        conditional_notes=conditional_notes,
    )


def build_reconciliation(positions: list[AgentPosition]) -> Reconciliation:
    by_agent = {p["agent"]: p for p in positions}
    yes_side = next((p for p in positions if p["stance"] == "yes"), None)
    no_side = next((p for p in positions if p["stance"] == "no"), None)
    operations = by_agent.get("operations")

    if yes_side and no_side:
        trade_off = (
            f"Optimises for {yes_side['agent']}'s {yes_side['driving_constraint']} "
            f"at the cost of {no_side['agent']}'s {no_side['driving_constraint']}"
        )
    else:
        trade_off = "No direct cost/schedule trade-off identified."

    is_hard_blocker = bool(
        operations and operations["stance"] == "conditional" and "blocked" in operations["recommendation"].lower()
    )

    if is_hard_blocker:
        recommendation = (
            "Do not proceed as currently scoped -- resolve the operational "
            "blocker first, then re-run this decision via the PMO governance gate."
        )
        why = (
            f"Operations flags a hard blocker ({operations['driving_constraint']}) "
            f"that makes the finance/delivery trade-off moot until it's resolved. "
            f"{OPERATIONAL_BLOCKER_POLICY}"
        )
    elif no_side:
        recommendation = f"Hold -- {no_side['agent']}'s objection stands"
        why = no_side["reasoning"]
    else:
        recommendation = "Proceed"
        why = "No hard blocker or objection identified among the routed agents."

    return Reconciliation(
        recommendation=recommendation,
        why=why,
        trade_off=trade_off,
        assumptions=[
            "Illustrative margin/revenue/licence figures used for this seed, "
            "not real 3PP data -- P2 will source these from Anuj's own models.",
        ],
        not_considered=[
            "Alternative suppliers",
            "Partial or phased cutover instead of a full 3-week pull-forward",
        ],
    )


def reconcile_node(state: ConsiliumState) -> dict:
    assert_bounded(state)

    step = next_step(state)
    conflict = detect_conflict(state["positions"])
    reconciliation = build_reconciliation(state["positions"])

    conflict_event = make_trace_event(step, "conflict", None, conflict["summary"], dict(conflict))
    reconciliation_event = make_trace_event(
        step + 1, "reconciliation", None, reconciliation["recommendation"], dict(reconciliation)
    )

    return {
        "conflict": conflict,
        "reconciliation": reconciliation,
        "trace": [conflict_event, reconciliation_event],
        "step_count": state["step_count"] + 1,
    }
