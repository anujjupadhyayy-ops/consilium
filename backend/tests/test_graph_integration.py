from orchestrator.graph import build_graph
from orchestrator.state import initial_state


def test_supplier_seed_runs_end_to_end(seed_input):
    compiled = build_graph()

    result = compiled.invoke(initial_state(seed_input), config={"recursion_limit": 10})

    assert len(result["positions"]) == 4
    assert result["conflict"] is not None
    assert result["reconciliation"] is not None

    kinds_seen = {event["kind"] for event in result["trace"]}
    assert kinds_seen == {"route", "position", "conflict", "reconciliation"}
