"""Rewrite for P3.6: loads the real agent (agents/configs/operations.json)
via the registry instead of a bare OperationsConfig(rules_summary=[]), and
calls check()/_position_from_check() instead of evaluate() -- see
test_agent_finance.py's module docstring for the full rationale."""
from agents.registry import get_agent

ALL_GREEN_FACTS = {
    "capacity_utilisation_pct_if_accepted": 70.0,
    "third_party_spend_pct_of_budget": 80.0,
    "savings_delivery_ratio": 0.95,
    "licence_provisioned_for_new_date": True,
    "supplier_sla_in_place": True,
}


def _agent():
    return get_agent("operations")


def _position(agent, facts):
    result = agent.check(facts)
    assert result.stance is not None, f"expected a trigger, got nothing fired ({result.unchecked=})"
    return agent._position_from_check(facts, result)


def test_supplier_milestone_seed_is_blocked_on_the_licence(seed_facts):
    position = _position(_agent(), seed_facts["operations"])

    assert position["stance"] == "blocker"
    assert "licence" in position["driving_constraint"].lower() or "sla" in position["driving_constraint"].lower()


def test_weakest_of_four_amber_is_conditional_not_averaged():
    """Even with three signals comfortably green, one amber signal must
    still govern the verdict -- proves it's a minimum, not a mean."""
    facts = {**ALL_GREEN_FACTS, "savings_delivery_ratio": 0.85}  # < 0.9 amber threshold

    position = _position(_agent(), facts)

    assert position["stance"] == "conditional"
    assert "savings" in position["driving_constraint"].lower()


def test_all_four_signals_green_is_all_clear():
    """Rewrite: old explicit "Yes, the operation can absorb this" is now
    the all-clear "no rule triggered, nothing unchecked" state (P3.6
    change 3 / equivalence rule)."""
    result = _agent().check(ALL_GREEN_FACTS)

    assert result.stance is None
    assert result.unchecked == ()


def test_any_red_signal_governs_regardless_of_the_other_three():
    facts = {**ALL_GREEN_FACTS, "capacity_utilisation_pct_if_accepted": 101.0}  # > 100% red

    position = _position(_agent(), facts)

    assert position["stance"] == "blocker"


def test_two_simultaneous_red_signals_both_named_in_the_driving_constraint():
    """Regression for the multi-signal-tied case the migration diff review
    specifically checked: evaluate() used to join every tied-weakest signal
    name into one string rather than averaging or picking arbitrarily --
    the rules-based rebuild must still do that, not just report one."""
    facts = {**ALL_GREEN_FACTS, "capacity_utilisation_pct_if_accepted": 101.0, "third_party_spend_pct_of_budget": 101.0}

    position = _position(_agent(), facts)

    assert position["stance"] == "blocker"
    assert "Capacity" in position["driving_constraint"]
    assert "Third-party spend" in position["driving_constraint"]


def test_licence_and_sla_both_failing_collapse_to_one_named_signal():
    """Licence and SLA are two different fields but ONE signal
    (Supplier/SLA & licence-kit control) -- both failing must not double up
    the signal name."""
    facts = {**ALL_GREEN_FACTS, "licence_provisioned_for_new_date": False, "supplier_sla_in_place": False}

    position = _position(_agent(), facts)

    assert position["driving_constraint"].count("Supplier/SLA") == 1


def test_config_swap_changes_the_stance_for_the_same_facts():
    facts = {**ALL_GREEN_FACTS, "third_party_spend_pct_of_budget": 92.0}  # green under default 95% amber line

    default_result = _agent().check(facts)

    stricter_agent = get_agent("operations")
    stricter_agent.config = stricter_agent.config.model_copy(update={"spend_amber_threshold_pct": 85.0})
    stricter_result = stricter_agent.check(facts)

    assert default_result.stance is None
    assert stricter_result.stance == "conditional"
