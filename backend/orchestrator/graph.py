from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agents.registry import load_agents_from_manifest

from .master import reconcile_node, route_node
from .state import ConsiliumState, initial_state

# route(1) + parallel specialist superstep(1) + reconcile(1) = 3 supersteps.
# A generous margin over that -- if this is ever hit, the graph topology
# has almost certainly grown a loop it shouldn't have.
RECURSION_LIMIT = 10


def build_graph():
    graph = StateGraph(ConsiliumState)

    graph.add_node("route", route_node)
    graph.add_node("reconcile", reconcile_node)
    graph.add_edge(START, "route")
    graph.add_edge("reconcile", END)

    # Deterministic fan-out in P2 (see master.route_node docstring): every
    # currently-enabled agent in agents/manifest.json gets a node and an
    # unconditional route->agent->reconcile pair. This is also the seam
    # that makes "remove an agent without code" real: disable it in the
    # manifest and it simply isn't added here.
    for agent in load_agents_from_manifest():
        graph.add_node(agent.id, agent.run)
        graph.add_edge("route", agent.id)
        graph.add_edge(agent.id, "reconcile")

    return graph.compile()


def run_seed(seed_input: str, facts: dict) -> ConsiliumState:
    compiled = build_graph()
    return compiled.invoke(initial_state(seed_input, facts), config={"recursion_limit": RECURSION_LIMIT})
