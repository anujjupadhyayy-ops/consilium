from orchestrator.graph import build_graph
from orchestrator.state import initial_state


def test_supplier_seed_runs_end_to_end(seed_input, seed_facts):
    compiled = build_graph()

    result = compiled.invoke(initial_state(seed_input, seed_facts), config={"recursion_limit": 10})

    assert len(result["positions"]) == 4
    assert result["conflict"] is not None
    assert result["reconciliation"] is not None

    kinds_seen = {event["kind"] for event in result["trace"]}
    assert kinds_seen == {"route", "position", "conflict", "reconciliation"}


def test_supplier_seed_produces_the_designed_conflict_via_real_config(seed_input, seed_facts):
    """P2's version of the P1 invariant: real config-driven evaluation, not
    hand-written stub strings, produces the same designed conflict."""
    compiled = build_graph()

    result = compiled.invoke(initial_state(seed_input, seed_facts), config={"recursion_limit": 10})

    stances = {p["agent"]: p["stance"] for p in result["positions"]}
    assert stances == {"finance": "no", "delivery": "yes", "pmo": "conditional", "operations": "blocker"}
