from agents.pmo import PMOAgent, PMOConfig

BASE_FACTS = {
    "is_contract_variation": False,
    "continued_business_case_justified": True,
    "portfolio_contention": False,
    "tolerance_variances_pct": {},
}


def _agent(config: PMOConfig = None) -> PMOAgent:
    return PMOAgent(agent_id="pmo", config=config or PMOConfig(lens="test", rules_summary=[]))


def test_supplier_milestone_seed_requires_the_contract_variation_gate(seed_facts):
    position = _agent().evaluate(seed_facts["pmo"])

    assert position["stance"] == "conditional"
    assert "Gate" in position["driving_constraint"]


def test_tolerance_breach_within_hard_reject_multiple_is_conditional():
    facts = {**BASE_FACTS, "tolerance_variances_pct": {"cost": 15.0}}  # > 10% tolerance, < 2x (20%)

    position = _agent().evaluate(facts)

    assert position["stance"] == "conditional"
    assert "cost" in position["reasoning"].lower()


def test_tolerance_breach_beyond_hard_reject_multiple_is_no():
    facts = {**BASE_FACTS, "tolerance_variances_pct": {"cost": 25.0}}  # > 2x the 10% tolerance

    position = _agent().evaluate(facts)

    assert position["stance"] == "no"
    assert "re-baseline" in position["reasoning"].lower()


def test_no_breach_and_not_a_variation_is_yes():
    position = _agent().evaluate(BASE_FACTS)

    assert position["stance"] == "yes"


def test_missing_business_case_justification_is_no():
    facts = {**BASE_FACTS, "continued_business_case_justified": False}

    position = _agent().evaluate(facts)

    assert position["stance"] == "no"
    assert "business-case" in position["reasoning"].lower()


def test_config_swap_changes_the_stance_for_the_same_facts():
    facts = {**BASE_FACTS, "tolerance_variances_pct": {"cost": 15.0}}

    default_position = _agent().evaluate(facts)
    lenient_config = PMOConfig(lens="test", rules_summary=[], tolerances_pct={"cost": 20.0})
    lenient_position = _agent(lenient_config).evaluate(facts)

    assert default_position["stance"] == "conditional"
    assert lenient_position["stance"] == "yes"
