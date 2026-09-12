from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agents.registry import load_agents_from_manifest

from .chief_of_staff import reconcile_node, route_node
from .state import ConsiliumState, initial_state

# route(1) + parallel specialist superstep(1) + reconcile(1) = 3 supersteps.
# A generous margin over that -- if this is ever hit, the graph topology
# has almost certainly grown a loop it shouldn't have.
RECURSION_LIMIT = 10


def _route_selector(state: ConsiliumState) -> list[str]:
    """Fan-out to whichever subset of agents the Chief of Staff engaged --
    selective by design (docs/00's "Selective routing" rule). Verified
    (tests/test_chief_of_staff.py) that LangGraph's fan-in at `reconcile`
    correctly waits only for the engaged branches, not the skipped ones."""
    return state["routed_agents"]


def build_graph():
    graph = StateGraph(ConsiliumState)

    graph.add_node("route", route_node)
    graph.add_node("reconcile", reconcile_node)
    graph.add_edge(START, "route")
    graph.add_edge("reconcile", END)

    all_agents = load_agents_from_manifest()
    for agent in all_agents:
        graph.add_node(agent.id, agent.run)
        graph.add_edge(agent.id, "reconcile")

    # Conditional, not unconditional (P3.5): route_node decides the subset
    # at runtime (an LLM decision, with a deterministic "engage everyone"
    # fallback if the model is unavailable -- see chief_of_staff.route_node).
    # This is also still the add/remove-agents-without-code seam: an agent
    # disabled in manifest.json never gets a node/edge here at all.
    graph.add_conditional_edges("route", _route_selector, {agent.id: agent.id for agent in all_agents})

    return graph.compile()


def run_seed(seed_input: str, facts: dict) -> ConsiliumState:
    compiled = build_graph()
    return compiled.invoke(initial_state(seed_input, facts), config={"recursion_limit": RECURSION_LIMIT})
