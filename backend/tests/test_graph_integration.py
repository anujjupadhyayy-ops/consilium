from orchestrator.graph import build_graph
from orchestrator.state import initial_state


def test_supplier_seed_runs_end_to_end(seed_input, seed_facts):
    compiled = build_graph()

    result = compiled.invoke(initial_state(seed_input, seed_facts), config={"recursion_limit": 10})

    assert len(result["checks"]) == 4
    assert result["conflict"] is not None
    assert result["reconciliation"] is not None

    # Rewrite: "route" trace kind is deleted (no routing node); "check" is
    # emitted by every agent every run instead of one centralised "route"
    # event -- reason: P3.6 replaces routing with per-agent rule checks.
    kinds_seen = {event["kind"] for event in result["trace"]}
    assert kinds_seen == {"check", "position", "conflict", "reconciliation"}


def test_supplier_seed_produces_the_designed_conflict_via_real_config(seed_input, seed_facts):
    """The flagship regression the whole migration exists for: with every
    agent unconditionally fanned out to (no router that could have skipped
    Operations), the seed's stances must match real config-driven
    evaluation -- Operations blocker included, every run."""
    compiled = build_graph()

    result = compiled.invoke(initial_state(seed_input, seed_facts), config={"recursion_limit": 10})

    stances = {p["agent"]: p["stance"] for p in result["positions"]}
    assert stances == {"finance": "no", "delivery": "yes", "pmo": "conditional", "operations": "blocker"}


def test_every_registered_agent_produces_a_check_on_every_run(tmp_path, seed_input, seed_facts, monkeypatch):
    """P3.6 §6.6: no router, nothing can be skipped -- every agent in the
    manifest (including one added purely for this test) produces a `check`
    entry on every run, triggered or not."""
    import json
    import shutil

    from agents import registry

    configs_dir = tmp_path / "configs"
    shutil.copytree(registry.DEFAULT_CONFIGS_DIR, configs_dir)
    manifest = json.loads(registry.DEFAULT_MANIFEST_PATH.read_text())
    # Register a second Finance instance under a new id, reusing the "finance"
    # kind with its own config file -- proves the fan-out is driven by the
    # manifest, not a hardcoded list of four agent ids.
    shutil.copy(configs_dir / "finance.json", configs_dir / "finance_b.json")
    manifest["agents"].append({"id": "finance_b", "kind": "finance", "config": "finance_b.json", "enabled": True})
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    monkeypatch.setattr(registry, "DEFAULT_CONFIGS_DIR", configs_dir)
    monkeypatch.setattr(registry, "DEFAULT_MANIFEST_PATH", manifest_path)

    compiled = build_graph()
    facts = {**seed_facts, "finance_b": seed_facts["finance"]}
    result = compiled.invoke(initial_state(seed_input, facts), config={"recursion_limit": 10})

    assert set(result["checks"]) == {"finance", "delivery", "pmo", "operations", "finance_b"}


def test_no_route_node_or_routing_symbols_importable():
    """P3.6 §6.6: assert removed -- route_node, _llm_route, RoutingDecision
    no longer exist anywhere the graph/orchestrator modules could reach them."""
    import orchestrator.chief_of_staff as cos

    for name in ("route_node", "_llm_route", "RoutingDecision", "_sanitize_extracted_facts", "LLMUnavailableForRouting", "LLMRoutingEmptyError"):
        assert not hasattr(cos, name), f"{name} should have been deleted with routing"
