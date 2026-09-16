from langgraph.graph import END, START, StateGraph

from orchestrator.state import initial_state
from orchestrator.trace import make_trace_event, next_step


def test_initial_state_shape():
    """Rewrite: routed_agents/skipped_agents/routing_reasoning are deleted
    (P3.6 removes routing); `checks` replaces them as the per-agent record
    every run produces -- reason: fields removed, no LLM decides who runs."""
    state = initial_state("some scenario")

    assert state["input"] == "some scenario"
    assert state["checks"] == {}
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


def test_checks_dict_reducer_accumulates_across_parallel_writes():
    """New for P3.6: `checks` is a dict, not a list -- operator.add doesn't
    apply to dicts, so it needs its own merge reducer (merge_dicts). Without
    it, LangGraph's default LastValue channel would reject (or silently
    drop) concurrent writes from the four parallel agent nodes the same way
    positions/trace needed operator.add."""
    from orchestrator.state import ConsiliumState

    def make_writer(agent_name: str):
        def _node(state: ConsiliumState) -> dict:
            return {"checks": {agent_name: {"agent": agent_name, "triggered": False}}}

        return _node

    graph = StateGraph(ConsiliumState)
    for name in ("a", "b", "c", "d"):
        graph.add_node(name, make_writer(name))
        graph.add_edge(START, name)
        graph.add_edge(name, END)
    compiled = graph.compile()

    result = compiled.invoke(initial_state("scenario"), config={"recursion_limit": 10})

    assert set(result["checks"]) == {"a", "b", "c", "d"}
    assert all(v["agent"] == k for k, v in result["checks"].items())
