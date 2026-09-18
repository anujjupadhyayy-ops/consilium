"""Rewrite for P3.6: loads the real agent (agents/configs/pmo.json) via the
registry instead of a bare PMOConfig(rules_summary=[]), and calls
check()/_position_from_check() instead of evaluate() -- see
test_agent_finance.py's module docstring for the full rationale."""
from agents.registry import get_agent

BASE_FACTS = {
    "is_contract_variation": False,
    "continued_business_case_justified": True,
    "portfolio_contention": False,
    "tolerance_variances_pct": {},
}


def _agent():
    return get_agent("pmo")


def _position(agent, facts):
    result = agent.check(facts)
    assert result.stance is not None, f"expected a trigger, got nothing fired ({result.unchecked=})"
    return agent._position_from_check(facts, result)


def test_supplier_milestone_seed_requires_the_contract_variation_gate(seed_facts):
    position = _position(_agent(), seed_facts["pmo"])

    assert position["stance"] == "conditional"
    assert "Gate" in position["driving_constraint"]


def test_tolerance_breach_within_hard_reject_multiple_is_conditional():
    facts = {**BASE_FACTS, "tolerance_variances_pct": {"cost": 15.0}}  # > 10% tolerance, < 2x (20%)

    position = _position(_agent(), facts)

    assert position["stance"] == "conditional"
    assert "cost" in position["reasoning"].lower()


def test_tolerance_breach_beyond_hard_reject_multiple_is_no():
    facts = {**BASE_FACTS, "tolerance_variances_pct": {"cost": 25.0}}  # > 2x the 10% tolerance

    position = _position(_agent(), facts)

    assert position["stance"] == "no"
    assert "hard reject" in position["reasoning"].lower()


def test_no_breach_and_not_a_variation_is_all_clear():
    """Rewrite: old explicit "Yes, compliant" is now the all-clear
    "no rule triggered, nothing unchecked" state (P3.6 change 3/equivalence
    rule) -- every field here is stated, so nothing is unchecked either."""
    result = _agent().check(BASE_FACTS)

    assert result.stance is None
    assert result.unchecked == ()


def test_missing_business_case_justification_is_no():
    facts = {**BASE_FACTS, "continued_business_case_justified": False}

    position = _position(_agent(), facts)

    assert position["stance"] == "no"
    assert "business case" in position["reasoning"].lower()


def test_config_swap_changes_the_stance_for_the_same_facts():
    facts = {**BASE_FACTS, "tolerance_variances_pct": {"cost": 15.0}}

    default_result = _agent().check(facts)

    lenient_agent = get_agent("pmo")
    lenient_agent.config = lenient_agent.config.model_copy(update={"tolerances_pct": {**lenient_agent.config.tolerances_pct, "cost": 20.0}})
    lenient_result = lenient_agent.check(facts)

    assert default_result.stance == "conditional"
    assert lenient_result.stance is None  # 15% no longer breaches the now-20% cost tolerance
