from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agents.delivery import DeliveryAgent
from agents.finance import FinanceAgent
from agents.operations import OperationsAgent
from agents.pmo import PMOAgent

from .master import reconcile_node, route_node
from .state import ConsiliumState, initial_state

SPECIALIST_NAMES = ("finance", "delivery", "pmo", "operations")

# route(1) + parallel specialist superstep(1) + reconcile(1) = 3 supersteps.
# A generous margin over that -- if this is ever hit, the graph topology
# has almost certainly grown a loop it shouldn't have.
RECURSION_LIMIT = 10


def build_graph():
    graph = StateGraph(ConsiliumState)

    graph.add_node("route", route_node)
    graph.add_node("finance", FinanceAgent().run)
    graph.add_node("delivery", DeliveryAgent().run)
    graph.add_node("pmo", PMOAgent().run)
    graph.add_node("operations", OperationsAgent().run)
    graph.add_node("reconcile", reconcile_node)

    graph.add_edge(START, "route")

    # Deterministic fan-out in P1 (see master.route_node docstring). The
    # one-function swap point for P2/P4's selective/LLM-driven routing is
    # replacing these unconditional edges with add_conditional_edges keyed
    # off the master's own decision -- nothing else here needs to change.
    for specialist in SPECIALIST_NAMES:
        graph.add_edge("route", specialist)
        graph.add_edge(specialist, "reconcile")

    graph.add_edge("reconcile", END)

    return graph.compile()


def run_seed(seed_input: str) -> ConsiliumState:
    compiled = build_graph()
    return compiled.invoke(initial_state(seed_input), config={"recursion_limit": RECURSION_LIMIT})
