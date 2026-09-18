"""P3.6-Rules-Trigger-Spec.md §6.4 -- per-agent free-text extraction:
evidence-verified, whole-message, no estimates, no persona, never
truncated."""
import pytest

from agents.evidence import ExtractedValue, ExtractionResult, MessageTooLongError
from agents.finance import FinanceAgent, FinanceConfig
from model.llm import LLMUnavailableError


def _agent() -> FinanceAgent:
    return FinanceAgent(agent_id="finance", config=FinanceConfig(lens="test", rules_summary=[]))


def test_prompt_contains_only_this_agents_fields_no_estimate_wording_no_persona(monkeypatch):
    captured = {}

    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        captured["system"] = system
        captured["user"] = user
        captured["temperature"] = temperature
        raise LLMUnavailableError("stop after capture")

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)

    agent = _agent()
    agent.extract_facts("A 15% supplier cost increase is proposed.")

    system = captured["system"]
    for field in FinanceAgent.facts_model.model_fields:
        assert field in system
    for other_field in ("capacity_utilisation_pct_if_accepted", "is_contract_variation", "spend_to_date"):
        assert other_field not in system  # another agent's field never appears
    # The old routing prompt's instruction-to-estimate is gone (P3.6 §5.4)
    # -- check for the specific phrase, not the bare word "estimate", since
    # the new prompt legitimately PROHIBITS estimating (using that word to
    # forbid it, not to request it).
    assert "make a clearly reasonable illustrative estimate" not in system.lower()
    assert "never invent, estimate" in system.lower()  # the prohibition itself is present
    assert "Always mention pineapple" not in system  # a persona string never reaches extraction


def test_temperature_zero_and_whole_message_present(monkeypatch):
    captured = {}

    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        captured["user"] = user
        captured["temperature"] = temperature
        raise LLMUnavailableError("stop after capture")

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)

    long_message = ("Paragraph one, background context. " * 20) + "Final paragraph names the actual figure: 15%."
    _agent().extract_facts(long_message)

    assert captured["temperature"] == 0
    assert "Final paragraph names the actual figure: 15%." in captured["user"]


def test_over_context_message_raises_clear_error_no_call_made(monkeypatch):
    called = {"n": 0}

    def fake_call_structured(*args, **kwargs):
        called["n"] += 1
        raise LLMUnavailableError("should never be reached")

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)

    from model.config import ModelConfig

    tiny_config = ModelConfig(provider="oss", model_name="x", context_tokens=5)
    monkeypatch.setattr(ModelConfig, "current", classmethod(lambda cls: tiny_config))

    with pytest.raises(MessageTooLongError):
        _agent().extract_facts("This message is definitely longer than five estimated tokens of content.")
    assert called["n"] == 0


def test_null_values_stay_not_stated_no_defaults_substituted(monkeypatch):
    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        return ExtractionResult(fields={
            "supplier_cost_increase_pct": ExtractedValue(value=None, evidence=[]),
        })

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)

    raw_facts, evidence = _agent().extract_facts("Some message.")
    assert raw_facts == {}  # not defaulted to 0.0 -- simply absent
    assert evidence == {}


def test_evidence_quote_not_in_message_is_discarded(monkeypatch):
    message = "The supplier proposes a cost increase."

    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        return ExtractionResult(fields={
            "supplier_cost_increase_pct": ExtractedValue(value=15.0, evidence=["a fifteen percent uplift"]),
        })

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)
    raw_facts, evidence = _agent().extract_facts(message)
    assert raw_facts == {}


def test_empty_evidence_list_is_discarded(monkeypatch):
    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        return ExtractionResult(fields={
            "supplier_cost_increase_pct": ExtractedValue(value=15.0, evidence=[]),
        })

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)
    raw_facts, evidence = _agent().extract_facts("A 15% cost increase.")
    assert raw_facts == {}


def test_paraphrased_quote_does_not_verify(monkeypatch):
    message = "The supplier wants a 15% cost increase on the current fee."

    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        return ExtractionResult(fields={
            "supplier_cost_increase_pct": ExtractedValue(
                value=15.0, evidence=["the vendor is asking for fifteen percent more money"]
            ),
        })

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)
    raw_facts, evidence = _agent().extract_facts(message)
    assert raw_facts == {}


def test_whitespace_and_linebreak_differences_still_verify(monkeypatch):
    message = "The supplier proposes\n   a 15% cost   increase on the fee."

    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        return ExtractionResult(fields={
            "supplier_cost_increase_pct": ExtractedValue(
                value=15.0, evidence=["a 15% cost increase on the fee"]  # single-spaced, one line
            ),
        })

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)
    raw_facts, evidence = _agent().extract_facts(message)
    assert raw_facts == {"supplier_cost_increase_pct": 15.0}


def test_cross_paragraph_fact_accepted_with_both_quotes(monkeypatch):
    message = (
        "Paragraph one talks about the schedule.\n\n"
        "Paragraph two: the change is a contract variation.\n\n"
        "Paragraph three, much later: the margin erosion from this is expected to be 6 points."
    )

    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        return ExtractionResult(fields={
            "margin_erosion_pts": ExtractedValue(
                value=6.0,
                evidence=["the change is a contract variation", "margin erosion from this is expected to be 6 points"],
            ),
        })

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)
    raw_facts, evidence = _agent().extract_facts(message)
    assert raw_facts == {"margin_erosion_pts": 6.0}
    assert len(evidence["margin_erosion_pts"]) == 2


def test_wrong_type_is_discarded_run_continues(monkeypatch):
    """A string for a numeric field (with a perfectly valid quote) must be
    discarded -- otherwise it would reach a rule comparison and crash it --
    while a correctly-typed sibling field survives."""
    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        return ExtractionResult(fields={
            "supplier_cost_increase_pct": ExtractedValue(value="fifteen percent-ish", evidence=["fifteen percent-ish"]),
            "margin_erosion_pts": ExtractedValue(value=6.0, evidence=["6 points of margin erosion"]),
        })

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)
    raw_facts, evidence = _agent().extract_facts("fifteen percent-ish, 6 points of margin erosion")
    assert "supplier_cost_increase_pct" not in raw_facts
    assert raw_facts["margin_erosion_pts"] == 6.0


def test_boolean_for_a_numeric_field_and_a_number_for_a_boolean_field_are_discarded():
    from agents.evidence import value_matches_type

    assert not value_matches_type(True, float)
    assert not value_matches_type(1, bool)
    assert value_matches_type(False, bool) and value_matches_type(3, float)


def test_pmo_dict_shaped_variance_fact_can_be_extracted_with_evidence(monkeypatch):
    from agents.pmo import PMOAgent, PMOConfig

    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        return ExtractionResult(fields={
            "tolerance_variances_pct": ExtractedValue(value={"cost": 15.0}, evidence=["a 15% cost increase"]),
        })

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)
    agent = PMOAgent(agent_id="pmo", config=PMOConfig(lens="t", rules_summary=[]))
    raw, ev = agent.extract_facts("The supplier wants a 15% cost increase.")
    assert raw == {"tolerance_variances_pct": {"cost": 15.0}} and ev["tolerance_variances_pct"]


def test_out_of_schema_key_is_dropped_run_continues(monkeypatch):
    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        return ExtractionResult(fields={
            "not_a_real_finance_field": ExtractedValue(value=99, evidence=["ninety nine"]),
            "margin_erosion_pts": ExtractedValue(value=6.0, evidence=["6 points of margin erosion"]),
        })

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)
    raw_facts, evidence = _agent().extract_facts("ninety nine, 6 points of margin erosion")
    assert "not_a_real_finance_field" not in raw_facts
    assert raw_facts["margin_erosion_pts"] == 6.0


def test_seed_run_never_calls_extraction(seed_input, seed_facts):
    """Seeds bypass extraction entirely (§5.4) -- covered end-to-end via the
    graph: a seed-populated agent's `run()` must never call extract_facts()."""
    called = {"n": 0}
    real_extract = FinanceAgent.extract_facts

    def counting_extract(self, message):
        called["n"] += 1
        return real_extract(self, message)

    FinanceAgent.extract_facts = counting_extract
    try:
        from orchestrator.graph import build_graph
        from orchestrator.state import initial_state

        build_graph().invoke(initial_state(seed_input, seed_facts), config={"recursion_limit": 10})
    finally:
        FinanceAgent.extract_facts = real_extract

    assert called["n"] == 0


# ------------- plain-English field descriptions reach the extraction prompt --

FEE_UPLIFT_BRIEF = (
    "Hi -- our supplier has written to say there will be a 15% uplift on our fee from next quarter "
    "if we want the earlier delivery date."
)


def _capture_system_prompt(monkeypatch, agent, message="A brief."):
    captured = {}

    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        captured["system"] = system
        raise LLMUnavailableError("stop after capture")

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)
    agent.extract_facts(message)
    return captured["system"]


@pytest.mark.parametrize("agent_id", ["finance", "delivery", "pmo", "operations"])
def test_every_facts_field_has_a_plain_english_description(agent_id):
    from agents.registry import get_agent

    for name, info in get_agent(agent_id).facts_model.model_fields.items():
        assert info.description and len(info.description.split()) >= 5, f"{agent_id}.{name} needs a description"


@pytest.mark.parametrize("agent_id", ["finance", "delivery", "pmo", "operations"])
def test_each_fields_description_is_in_that_agents_extraction_prompt(monkeypatch, agent_id):
    from agents.registry import get_agent

    agent = get_agent(agent_id)
    system = _capture_system_prompt(monkeypatch, agent)
    for name, info in agent.facts_model.model_fields.items():
        assert f"{name} (" in system and info.description in system


def test_finance_prompt_names_fee_uplift_phrasings_for_supplier_cost_increase(monkeypatch):
    system = _capture_system_prompt(monkeypatch, _agent(), FEE_UPLIFT_BRIEF)
    line = next(part for part in system.split("; ") if "supplier_cost_increase_pct" in part)
    assert "uplift on our fee" in line and "15" in line
    assert "match on the meaning" in system            # told to map wording to the field...
    assert "never invent, estimate" in system.lower()   # ...without loosening the no-inference rule


def test_a_fee_uplift_brief_extracts_supplier_cost_increase_and_fires_the_rule(monkeypatch):
    """Plumbing for the reported miss: when the model returns 15 with the
    brief's own words as evidence, the value is kept (the quote is verbatim)
    and Finance's supplier-cost rule fires. Whether the model does so is the
    live test below."""
    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        return ExtractionResult(fields={
            "supplier_cost_increase_pct": ExtractedValue(value=15.0, evidence=["a 15% uplift on our fee"]),
        })

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)
    facts, evidence = _agent().extract_facts(FEE_UPLIFT_BRIEF)

    assert facts == {"supplier_cost_increase_pct": 15.0}
    assert evidence["supplier_cost_increase_pct"] == ["a 15% uplift on our fee"]


@pytest.mark.live
@pytest.mark.parametrize("phrasing", [
    "a 15% uplift on our fee",
    "there will be a 15% uplift on our fee from next quarter",
    "they want 15% on our fee",
])
def test_live_model_extracts_fee_uplift_phrasings(phrasing):
    """Owner-run (`pytest -m live`): the real model must map fee-uplift
    wording to supplier_cost_increase_pct."""
    from agents.registry import get_agent

    facts, _ = get_agent("finance").extract_facts(f"Hi -- the supplier says {phrasing} if we want the earlier date.")
    assert facts.get("supplier_cost_increase_pct") == 15.0
