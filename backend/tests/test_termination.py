import pytest

from orchestrator.graph import RECURSION_LIMIT, build_graph
from orchestrator.state import initial_state
from orchestrator.termination import BoundedTerminationError, assert_bounded


def test_assert_bounded_passes_at_the_limit():
    state = initial_state("scenario")
    state["step_count"] = 1  # only route has run

    assert_bounded(state)  # should not raise


def test_assert_bounded_raises_over_the_limit():
    state = initial_state("scenario")
    state["step_count"] = 2  # route has run twice, or looped back -- not allowed

    with pytest.raises(BoundedTerminationError):
        assert_bounded(state)


def test_graph_topology_has_no_cycles():
    """The DAG shape is the primary termination guarantee: assert no edge
    exists that would let a specialist or reconcile route back into route
    or into another specialist -- a structural regression test that fails
    immediately if a future phase accidentally adds an agent-to-agent or
    a reconcile-to-route edge."""
    compiled = build_graph()
    drawable = compiled.get_graph()

    edges = {(edge.source, edge.target) for edge in drawable.edges}
    specialists = {"finance", "delivery", "pmo", "operations"}

    for source, target in edges:
        if target == "route":
            assert source == "__start__", f"unexpected edge into route: {source} -> route"
        if source in specialists:
            assert target == "reconcile", f"unexpected edge out of specialist: {source} -> {target}"
        if source == "reconcile":
            assert target == "__end__", f"unexpected edge out of reconcile: reconcile -> {target}"


def test_full_seed_run_stays_within_the_recursion_limit(seed_input):
    from orchestrator.state import initial_state as _initial_state

    compiled = build_graph()

    result = compiled.invoke(_initial_state(seed_input), config={"recursion_limit": RECURSION_LIMIT})

    assert result["reconciliation"] is not None


def test_recursion_limit_is_actually_enforced(seed_input):
    from langgraph.errors import GraphRecursionError

    from orchestrator.state import initial_state as _initial_state

    compiled = build_graph()

    with pytest.raises(GraphRecursionError):
        compiled.invoke(_initial_state(seed_input), config={"recursion_limit": 1})
