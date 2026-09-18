from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agents.registry import load_agents_from_manifest

from .chief_of_staff import reconcile_node
from .state import ConsiliumState, initial_state

# fan-out (1 superstep, every agent in parallel) + reconcile (1) = 2
# supersteps. A generous margin over that -- if this is ever hit, the graph
# topology has almost certainly grown a loop it shouldn't have.
RECURSION_LIMIT = 10


def build_graph():
    graph = StateGraph(ConsiliumState)

    graph.add_node("reconcile", reconcile_node)
    graph.add_edge("reconcile", END)

    # P3.6: unconditional fan-out -- every registered agent runs on every
    # decision, no exceptions. There is no routing node deciding a subset
    # any more (that was the bug: an LLM held a veto over a code-enforced
    # rule -- see docs/P3.6-Rules-Trigger-Spec.md §1). Each agent's own
    # `run()` does extract (free text only) -> check -> narrate (if
    # triggered) internally and streams its own trace events; this is the
    # add/remove-agents-without-code seam (an agent disabled in
    # manifest.json never gets a node/edge here at all).
    for agent in load_agents_from_manifest():
        graph.add_node(agent.id, agent.run)
        graph.add_edge(START, agent.id)
        graph.add_edge(agent.id, "reconcile")

    return graph.compile()


def run_seed(seed_input: str, facts: dict) -> ConsiliumState:
    compiled = build_graph()
    return compiled.invoke(initial_state(seed_input, facts), config={"recursion_limit": RECURSION_LIMIT})
