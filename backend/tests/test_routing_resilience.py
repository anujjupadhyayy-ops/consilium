"""A weak routing model can echo a facts_schema back as values or hand an
agent malformed facts. The run must degrade gracefully (defaults), never crash
with a raw validation error in the UI -- the defect found in live-model play."""
from orchestrator.chief_of_staff import RoutingDecision, _sanitize_extracted_facts, route_node
from orchestrator.state import initial_state


def _agents():
    from agents.registry import load_agents_from_manifest
    return load_agents_from_manifest()


def test_sanitizer_drops_schema_echo_but_keeps_valid():
    agents = _agents()
    schema_echo = {"finance": {"margin_erosion_pts": {"default": 0.0, "title": "Pts", "type": "number"}}}
    assert _sanitize_extracted_facts(schema_echo, agents) == {}      # dropped
    valid = {"finance": {"margin_erosion_pts": 12}}
    assert _sanitize_extracted_facts(valid, agents) == valid         # kept


def test_full_run_survives_a_schema_echoing_router(monkeypatch, seed_facts):
    """End-to-end: the routing model returns schema fragments as facts; the
    graph must still complete and reconcile, not raise FinanceFacts errors."""
    from model.llm import LLMUnavailableError
    from orchestrator.chief_of_staff import ReconciliationDraft

    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        if response_model is RoutingDecision:
            return RoutingDecision(
                rationale="engage finance",
                engaged={"finance": "budget matter"},
                skipped={},
                facts={"finance": {"margin_erosion_pts": {"default": 0.0, "type": "number"}}},
            )
        raise LLMUnavailableError("only routing under test")

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)

    from orchestrator.graph import build_graph
    from seeds.supplier_milestone import SUPPLIER_MILESTONE_SEED

    result = build_graph().invoke(
        initial_state("A 3PP budget breach worth reviewing.", {}),
        config={"recursion_limit": 10},
    )
    # completed without crashing, and -- because nothing was actually extracted
    # -- ABSTAINS rather than fabricating a confident verdict on defaults.
    rec = result["reconciliation"]["recommendation"].lower()
    assert "insufficient grounding" in rec
    assert result["positions"]                     # positions still produced (on defaults)


def test_grounded_seed_run_is_not_abstained(seed_input, seed_facts):
    """A seed supplies real facts, so the council must produce a genuine verdict,
    never the ungrounded-abstention message."""
    from orchestrator.graph import build_graph
    from orchestrator.state import initial_state as _init

    result = build_graph().invoke(_init(seed_input, seed_facts), config={"recursion_limit": 10})
    assert "insufficient grounding" not in result["reconciliation"]["recommendation"].lower()
