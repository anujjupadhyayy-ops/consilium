from orchestrator.chief_of_staff import ReconciliationDraft, _enforce_blocker_policy
from orchestrator.graph import build_graph
from orchestrator.state import initial_state

# P3.6-Rules-Trigger-Spec.md §6.6: routing is deleted, not migrated.
# test_router_selects_a_genuine_subset and
# test_router_falls_back_to_engaging_everyone_when_model_unusable removed --
# tests removed behaviour (LLM routing). The first asserted an LLM could
# select a subset of agents to engage (`routed_agents`/`skipped_agents`,
# both deleted from ConsiliumState); the second asserted the routing
# fallback engaged everyone, which is now true unconditionally and by
# construction (every agent is an unconditional graph edge -- see
# orchestrator/graph.py), so the assertion is structural, not behavioural,
# and covered instead by test_graph_integration.py's
# test_every_registered_agent_produces_a_check_on_every_run.


def test_narration_cannot_override_the_computed_stance(monkeypatch, seed_facts):
    """A misbehaving/adversarial narration response that includes a stance
    field must be silently ignored -- NarrationResult has no such field."""
    from agents.finance import FinanceAgent, FinanceConfig
    from orchestrator.state import initial_state as _initial_state

    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        # Simulates a model that "helpfully" tries to flip the stance --
        # extra keys a pydantic model doesn't declare are dropped, not errors.
        return response_model.model_validate(
            {"reasoning": "Actually this looks fine to me.", "lead_figure": "All clear", "stance": "yes"}
        )

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)

    from agents.registry import get_agent

    agent = get_agent("finance")
    assert isinstance(agent, FinanceAgent)
    state = _initial_state("scenario", {"finance": seed_facts["finance"]})

    update = agent.run(state)

    assert update["positions"], "finance must trigger on the seed's 15% supplier-cost breach"
    position = update["positions"][0]
    assert position["stance"] == "no"  # unchanged: the seed's 15% supplier-cost breach
    assert position["reasoning"] == "Actually this looks fine to me."  # narration DID take effect on prose


def test_blocker_policy_enforced_even_when_model_recommends_proceeding():
    """Direct unit test of the safety net: an LLM reconciliation that
    doesn't decline in the presence of a blocker gets overridden."""
    blockers = [
        {
            "agent": "operations",
            "stance": "blocker",
            "recommendation": "Blocked",
            "reasoning": "Licence not provisioned.",
            "driving_constraint": "Licence not provisioned for the new date",
            "lead_figure": "Licence gap",
        }
    ]
    noncompliant = {
        "recommendation": "Proceed with the accelerated timeline -- the upside is worth it.",
        "why": "Delivery's revenue protection outweighs the concerns.",
        "trade_off": "Speed vs cost.",
        "assumptions": ["x"],
        "not_considered": ["y"],
    }

    enforced = _enforce_blocker_policy(noncompliant, blockers)

    assert "decline" in enforced["recommendation"].lower()
    assert "operations" in enforced["recommendation"]


def _operations_blocker():
    return [
        {
            "agent": "operations",
            "stance": "blocker",
            "recommendation": "Blocked",
            "reasoning": "Licence not provisioned.",
            "driving_constraint": "Licence not provisioned for the new date",
            "lead_figure": "Licence gap",
        }
    ]


def test_blocker_policy_normalizes_even_a_compliant_recommendation():
    """The verdict is code-authoritative under a blocker: even a model line
    that already declines is replaced by the system-authored verdict, so the
    decisive text never depends on classifying the model's prose. The model's
    why/trade_off are preserved for provenance."""
    blockers = _operations_blocker()
    compliant = {
        "recommendation": "Decline as scoped until the licence is sorted.",
        "why": "The licence gap is decisive.",
        "trade_off": "Speed vs governance.",
        "assumptions": ["x"],
        "not_considered": ["y"],
    }

    enforced = _enforce_blocker_policy(compliant, blockers)

    assert "decline" in enforced["recommendation"].lower()
    assert "operations" in enforced["recommendation"]
    assert enforced["trade_off"] == compliant["trade_off"]
    assert compliant["why"] in enforced["why"]


def test_blocker_policy_survives_negation_bypass():
    """Regression for the negation bypass: a recommendation that embeds a
    decline word inside a negation ("do not hold back") must NOT slip a
    proceed past the blocker. The old keyword check matched the substring
    "hold" and waved this through; the code-authoritative verdict does not."""
    blockers = _operations_blocker()
    negation_attack = {
        "recommendation": "Proceed now and do not hold back -- approve the accelerated timeline.",
        "why": "The upside is worth it.",
        "trade_off": "Speed vs cost.",
        "assumptions": ["x"],
        "not_considered": ["y"],
    }

    enforced = _enforce_blocker_policy(negation_attack, blockers)

    assert "decline" in enforced["recommendation"].lower()
    assert "operations" in enforced["recommendation"]
    assert "proceed now" not in enforced["recommendation"].lower()


def test_reconcile_via_mocked_llm_still_enforced_end_to_end(monkeypatch, seed_input, seed_facts):
    """Full graph run: a mocked reconcile model tries to recommend
    proceeding despite the seed's Operations blocker -- the final
    reconciliation must still decline. Narration is left to fall back
    deterministically (LLMUnavailableError) so only the reconcile step's
    behaviour is under test here."""
    from model.llm import LLMUnavailableError

    def fake_call_structured(system, user, response_model, config=None, temperature=0.2):
        if response_model is ReconciliationDraft:
            return ReconciliationDraft(
                recommendation="Proceed -- the numbers work out in our favour.",
                why="Ignoring the blocker for this test.",
                trade_off="Cost vs schedule.",
                assumptions=["illustrative"],
                not_considered=["alternatives"],
            )
        raise LLMUnavailableError("mocked: only reconcile is under test here")

    monkeypatch.setattr("model.llm.call_structured", fake_call_structured)

    compiled = build_graph()
    result = compiled.invoke(initial_state(seed_input, seed_facts), config={"recursion_limit": 10})

    assert "decline" in result["reconciliation"]["recommendation"].lower()


def test_fallback_path_does_not_duplicate_the_blocker_policy_sentence(monkeypatch, seed_input, seed_facts):
    """Regression guard: build_reconciliation() (the deterministic fallback)
    used to bake OPERATIONAL_BLOCKER_POLICY into `why` itself, and
    _enforce_blocker_policy -- applied unconditionally, by design, to close
    the negation-bypass -- appended it a second time. Every reconciliation
    the graph actually returns must state the policy exactly once."""
    from model.llm import LLMUnavailableError

    def unavailable(*args, **kwargs):
        raise LLMUnavailableError("mocked: forcing the deterministic fallback path")

    monkeypatch.setattr("model.llm.call_structured", unavailable)

    compiled = build_graph()
    result = compiled.invoke(initial_state(seed_input, seed_facts), config={"recursion_limit": 10})

    why = result["reconciliation"]["why"]
    assert why.count("independent of the cost/schedule trade-off") == 1
