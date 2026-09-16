import pytest

from orchestrator.graph import RECURSION_LIMIT, build_graph
from orchestrator.state import initial_state
from orchestrator.termination import BoundedTerminationError, assert_bounded


def test_assert_bounded_passes_at_the_limit():
    state = initial_state("scenario")
    state["step_count"] = 1  # only the fan-out superstep has run

    assert_bounded(state)  # should not raise


def test_assert_bounded_raises_over_the_limit():
    state = initial_state("scenario")
    state["step_count"] = 2  # the fan-out has run twice, or looped back -- not allowed

    with pytest.raises(BoundedTerminationError):
        assert_bounded(state)


def test_graph_topology_has_no_cycles():
    """The DAG shape is the primary termination guarantee (rewrite: no more
    `route` node -- P3.6 deletes routing, every agent is now a direct
    START edge): assert no edge exists that would let a specialist or
    reconcile loop back into another specialist -- a structural regression
    test that fails immediately if a future phase accidentally adds an
    agent-to-agent or a reconcile-to-agent edge."""
    from agents.registry import list_enabled_agent_ids

    compiled = build_graph()
    drawable = compiled.get_graph()

    edges = {(edge.source, edge.target) for edge in drawable.edges}
    specialists = set(list_enabled_agent_ids())

    for source, target in edges:
        if target in specialists:
            assert source == "__start__", f"unexpected edge into agent {target}: {source} -> {target}"
        if source in specialists:
            assert target == "reconcile", f"unexpected edge out of specialist: {source} -> {target}"
        if source == "reconcile":
            assert target == "__end__", f"unexpected edge out of reconcile: reconcile -> {target}"


def test_termination_bound_holds_with_n_agents(tmp_path, seed_input, seed_facts):
    """P3.6 §6.6: the bound doesn't depend on there being exactly four
    agents -- add a fifth (a second Finance instance) and the run must
    still complete within the same recursion_limit, no topology change
    needed."""
    import json
    import shutil

    from agents import registry

    configs_dir = tmp_path / "configs"
    shutil.copytree(registry.DEFAULT_CONFIGS_DIR, configs_dir)
    shutil.copy(configs_dir / "finance.json", configs_dir / "finance_b.json")
    manifest = json.loads(registry.DEFAULT_MANIFEST_PATH.read_text())
    manifest["agents"].append({"id": "finance_b", "kind": "finance", "config": "finance_b.json", "enabled": True})
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    mp = pytest.MonkeyPatch()
    mp.setattr(registry, "DEFAULT_CONFIGS_DIR", configs_dir)
    mp.setattr(registry, "DEFAULT_MANIFEST_PATH", manifest_path)
    try:
        compiled = build_graph()
        facts = {**seed_facts, "finance_b": seed_facts["finance"]}
        result = compiled.invoke(initial_state(seed_input, facts), config={"recursion_limit": RECURSION_LIMIT})
        assert result["reconciliation"] is not None
    finally:
        mp.undo()


def test_full_seed_run_stays_within_the_recursion_limit(seed_input, seed_facts):
    from orchestrator.state import initial_state as _initial_state

    compiled = build_graph()

    result = compiled.invoke(_initial_state(seed_input, seed_facts), config={"recursion_limit": RECURSION_LIMIT})

    assert result["reconciliation"] is not None


def test_recursion_limit_is_actually_enforced(seed_input, seed_facts):
    from langgraph.errors import GraphRecursionError

    from orchestrator.state import initial_state as _initial_state

    compiled = build_graph()

    with pytest.raises(GraphRecursionError):
        compiled.invoke(_initial_state(seed_input, seed_facts), config={"recursion_limit": 1})
