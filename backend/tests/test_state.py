from langgraph.graph import END, START, StateGraph

from orchestrator.state import initial_state
from orchestrator.trace import make_trace_event, next_step


def test_initial_state_shape():
    state = initial_state("some scenario")

    assert state["input"] == "some scenario"
    assert state["routed_agents"] == []
    assert state["routing_reasoning"] == ""
    assert state["positions"] == []
    assert state["conflict"] is None
    assert state["reconciliation"] is None
    assert state["trace"] == []
    assert state["step_count"] == 0


def test_positions_and_trace_reducers_accumulate_across_parallel_writes():
    """Regression guard: without an operator.add reducer on `positions`/`trace`,
    LangGraph's default "last write wins" merge would silently drop 3 of the
    4 specialists' output when they run in the same parallel superstep.
    """
    from orchestrator.state import ConsiliumState

    def make_writer(agent_name: str):
        def _node(state: ConsiliumState) -> dict:
            step = next_step(state)
            position = {
                "agent": agent_name,
                "stance": "yes",
                "recommendation": "test",
                "reasoning": "test",
                "driving_constraint": "test",
                "lead_figure": "test",
            }
            event = make_trace_event(step, "position", agent_name, "test", {})
            return {"positions": [position], "trace": [event]}

        return _node

    graph = StateGraph(ConsiliumState)
    for name in ("a", "b", "c", "d"):
        graph.add_node(name, make_writer(name))
        graph.add_edge(START, name)
        graph.add_edge(name, END)
    compiled = graph.compile()

    result = compiled.invoke(initial_state("scenario"), config={"recursion_limit": 10})

    assert len(result["positions"]) == 4
    assert {p["agent"] for p in result["positions"]} == {"a", "b", "c", "d"}
    assert len(result["trace"]) == 4
