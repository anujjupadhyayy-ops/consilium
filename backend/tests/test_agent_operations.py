from agents.operations import OperationsAgent, OperationsConfig

ALL_GREEN_FACTS = {
    "capacity_utilisation_pct_if_accepted": 70.0,
    "third_party_spend_pct_of_budget": 80.0,
    "savings_delivery_ratio": 0.95,
    "licence_provisioned_for_new_date": True,
    "supplier_sla_in_place": True,
}


def _agent(config: OperationsConfig = None) -> OperationsAgent:
    return OperationsAgent(agent_id="operations", config=config or OperationsConfig(lens="test", rules_summary=[]))


def test_supplier_milestone_seed_is_blocked_on_the_licence(seed_facts):
    position = _agent().evaluate(seed_facts["operations"])

    assert position["stance"] == "blocker"
    assert "licence" in position["driving_constraint"].lower() or "sla" in position["driving_constraint"].lower()


def test_weakest_of_four_amber_is_conditional_not_averaged():
    """Even with three signals comfortably green, one amber signal must
    still govern the verdict -- proves it's a minimum, not a mean."""
    facts = {**ALL_GREEN_FACTS, "savings_delivery_ratio": 0.85}  # < 0.9 amber threshold

    position = _agent().evaluate(facts)

    assert position["stance"] == "conditional"
    assert "savings" in position["driving_constraint"].lower()


def test_all_four_signals_green_is_yes():
    position = _agent().evaluate(ALL_GREEN_FACTS)

    assert position["stance"] == "yes"


def test_any_red_signal_governs_regardless_of_the_other_three():
    facts = {**ALL_GREEN_FACTS, "capacity_utilisation_pct_if_accepted": 101.0}  # > 100% red

    position = _agent().evaluate(facts)

    assert position["stance"] == "blocker"


def test_config_swap_changes_the_stance_for_the_same_facts():
    facts = {**ALL_GREEN_FACTS, "third_party_spend_pct_of_budget": 92.0}  # green under default 95% amber line

    default_position = _agent().evaluate(facts)
    stricter_config = OperationsConfig(lens="test", rules_summary=[], spend_amber_threshold_pct=85.0)
    stricter_position = _agent(stricter_config).evaluate(facts)

    assert default_position["stance"] == "yes"
    assert stricter_position["stance"] == "conditional"
