"""P3.6-Rules-Trigger-Spec.md §6.6: a weak per-agent extraction call must
degrade that ONE agent to "couldn't check" gracefully -- never crash the
run, never silently spread to other agents. The routing-era equivalent of
this file tested `_sanitize_extracted_facts`, the single combined
routing+extraction call's defence against a schema-echoing model; that
whole mechanism is deleted along with routing (extraction is now per-agent,
and its own defence -- dropping unverifiable/wrong-type/out-of-schema
values -- lives in agents/evidence.py, covered directly by
tests/test_extraction.py). test_sanitizer_drops_schema_echo_but_keeps_valid
is removed here with no replacement in this file: tests removed behaviour
(the routing-era sanitizer function no longer exists).
"""
from orchestrator.graph import build_graph
from orchestrator.state import initial_state


def test_one_agents_extraction_raising_does_not_crash_the_run(monkeypatch, seed_input):
    """A malformed/garbage extraction response for one agent (finance) must
    leave that agent with no stated facts (reported as couldn't-check, not
    a crash) while the other three still run normally."""
    from agents.finance import FinanceAgent
    from model.llm import LLMUnavailableError

    real_extract = FinanceAgent.extract_facts

    def broken_extract(self, message):
        raise ValueError("simulated malformed extraction response")

    monkeypatch.setattr(FinanceAgent, "extract_facts", broken_extract)

    def unavailable(*args, **kwargs):
        raise LLMUnavailableError("mocked: no model reachable in this test")

    monkeypatch.setattr("model.llm.call_structured", unavailable)

    compiled = build_graph()
    result = compiled.invoke(initial_state(seed_input, {}), config={"recursion_limit": 10})

    assert result["reconciliation"] is not None  # completed, did not crash
    finance_check = result["checks"]["finance"]
    assert finance_check["triggered"] is False
    assert {"delivery", "pmo", "operations"} <= set(result["checks"])  # others unaffected

    monkeypatch.setattr(FinanceAgent, "extract_facts", real_extract)


def test_grounded_seed_run_produces_real_triggers_not_the_no_trigger_fallback(seed_input, seed_facts):
    """A seed supplies real, stated facts, so the council must produce
    genuine triggered positions -- never the "no rule triggered on stated
    facts" fallback that free-text-with-nothing-extracted hits."""
    compiled = build_graph()

    result = compiled.invoke(initial_state(seed_input, seed_facts), config={"recursion_limit": 10})

    assert result["positions"], "the seed's engineered facts must trigger at least one agent"
    assert "no rule triggered" not in result["reconciliation"]["recommendation"].lower()
