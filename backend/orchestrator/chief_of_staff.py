from __future__ import annotations

from agents.registry import list_enabled_agent_ids

from .state import AgentPosition, Conflict, ConsiliumState, Reconciliation
from .termination import assert_bounded
from .trace import make_trace_event, next_step

# P2's routing is still deterministic: route to every currently-enabled
# agent in the manifest. Real selective/LLM-driven routing (the master
# saying "operations isn't needed here") is P4 scope -- swap this
# function's body then; route_node's trace/state contract stays the same.
ROUTING_REASONING = (
    "Supplier milestone variations touch cost, schedule, governance, and "
    "operational capacity -- all currently-enabled agents are relevant here."
)

OPERATIONAL_BLOCKER_POLICY = (
    "Consilium's reconciliation policy treats a 'blocker' stance from any "
    "agent as decisive, independent of the cost/schedule trade-off: a plan "
    "that can't be executed is moot regardless of who wins that argument. "
    "This is a disclosed policy, not a hidden judgement call."
)


def route_node(state: ConsiliumState) -> dict:
    routed_agents = list_enabled_agent_ids()
    step = next_step(state)
    event = make_trace_event(
        step=step,
        kind="route",
        agent=None,
        summary=f"Routed to: {', '.join(routed_agents)}",
        payload={"routed_agents": routed_agents, "reasoning": ROUTING_REASONING},
    )
    return {
        "routed_agents": routed_agents,
        "routing_reasoning": ROUTING_REASONING,
        "trace": [event],
        "step_count": state["step_count"] + 1,
    }


def detect_conflict(positions: list[AgentPosition]) -> Conflict:
    yes_side = [p for p in positions if p["stance"] == "yes"]
    no_side = [p for p in positions if p["stance"] == "no"]
    conditional_side = [p for p in positions if p["stance"] == "conditional"]
    blocker_side = [p for p in positions if p["stance"] == "blocker"]

    disagreeing_pairs = [(y["agent"], n["agent"]) for y in yes_side for n in no_side]
    conditional_notes = [f"{p['agent']}: {p['driving_constraint']}" for p in conditional_side]
    blocker_notes = [f"{p['agent']}: {p['driving_constraint']}" for p in blocker_side]

    if blocker_side:
        names = ", ".join(p["agent"] for p in blocker_side)
        summary = f"{names} raise a hard blocker, independent of any cost/schedule disagreement"
    elif disagreeing_pairs:
        a, b = disagreeing_pairs[0]
        summary = f"{a} and {b} disagree on whether to proceed"
    else:
        summary = "No direct yes/no clash; conditional constraints apply"

    return Conflict(
        summary=summary,
        disagreeing_pairs=disagreeing_pairs,
        conditional_notes=conditional_notes,
        blocker_notes=blocker_notes,
    )


def build_reconciliation(positions: list[AgentPosition]) -> Reconciliation:
    blockers = [p for p in positions if p["stance"] == "blocker"]
    yes_side = next((p for p in positions if p["stance"] == "yes"), None)
    no_side = next((p for p in positions if p["stance"] == "no"), None)
    conditional_side = [p for p in positions if p["stance"] == "conditional"]

    if yes_side and no_side:
        trade_off = (
            f"Optimises for {yes_side['agent']}'s {yes_side['driving_constraint']} "
            f"at the cost of {no_side['agent']}'s {no_side['driving_constraint']}"
        )
    else:
        trade_off = "No direct cost/schedule trade-off identified."

    if blockers:
        blocker_detail = "; ".join(f"{p['agent']} ({p['driving_constraint']})" for p in blockers)
        recommendation = (
            "Do not proceed as currently scoped -- resolve the blocker(s) first, "
            "then re-run this decision via the appropriate governance gate."
        )
        why = f"{blocker_detail} raise a hard blocker that makes any cost/schedule trade-off moot until resolved. {OPERATIONAL_BLOCKER_POLICY}"
    elif yes_side and no_side:
        recommendation = f"Hold -- {no_side['agent']}'s objection stands"
        why = no_side["reasoning"]
    elif no_side:
        recommendation = f"Hold -- {no_side['agent']}'s objection stands"
        why = no_side["reasoning"]
    elif conditional_side:
        gates = "; ".join(f"{p['agent']}: {p['driving_constraint']}" for p in conditional_side)
        recommendation = "Proceed, but only via the stated gate(s)/condition(s)"
        why = gates
    else:
        recommendation = "Proceed"
        why = "No hard blocker, objection, or conditional gate identified among the routed agents."

    return Reconciliation(
        recommendation=recommendation,
        why=why,
        trade_off=trade_off,
        assumptions=[
            "Facts for this scenario are illustrative example inputs feeding real agent "
            "logic, not live 3PP/EVM/PRINCE2 system data -- a fork wires these to real "
            "data sources.",
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
